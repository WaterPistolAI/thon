# Copyright 2025 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
THON - The Hackathon Organizer Node

Runs multiple VS Code sandbox instances driven by a groups.yaml config.
Each user gets their own sandbox with workspace at /workspace/{group}/{username}.
Nginx reverse proxy with SSL termination maps /{port}/ to each instance.

Bridge/host mode is auto-detected from the server-returned endpoint format.
The displayed URL includes the full endpoint path so browsers hit execd correctly.

Usage:
    # Setup (one-time)
    bash ./scripts/setup.sh

    # Run all groups (nginx+SSL on by default)
    python ./scripts/main.py --groups groups.yaml --external-ip 165.245.138.159

    # Run a single group
    python ./scripts/main.py --groups groups.yaml --group alpha --external-ip 1.2.3.4

    # Auto-detect external IP
    python ./scripts/main.py --groups groups.yaml

    # With per-user passwords
    python ./scripts/main.py --groups groups.yaml --secure --external-ip 1.2.3.4

    # Direct HTTP without nginx
    python ./scripts/main.py --no-nginx

    # With persistent workspace bind mounts
    python ./scripts/main.py --groups groups.yaml --workspace-dir /thon-workspace

    # Cleanup all nginx configs
    python ./scripts/main.py --cleanup
"""

import argparse
import base64
import asyncio
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))  # noqa: E402

from app.env import load_env

load_env()


def resolve_path(path_str: str) -> Path:
    """Resolve a path relative to SCRIPT_DIR if not absolute."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    resolved = SCRIPT_DIR / p
    if resolved.exists():
        return resolved
    return p


from datetime import timedelta  # noqa: E402
from typing import Optional, TYPE_CHECKING  # noqa: E402

import yaml  # noqa: E402

from opensandbox import Sandbox  # noqa: E402
from opensandbox.config import ConnectionConfig  # noqa: E402
from opensandbox.models.execd import RunCommandOpts  # noqa: E402
from opensandbox.models.sandboxes import Host, PVC, Volume  # noqa: E402

from nginx_config import NginxConfigGenerator  # noqa: E402
from ssl_cert import SSLCertificateGenerator  # noqa: E402
from app.db import upsert_record, mark_terminated, set_setting  # noqa: E402
from app.services.groups_service import GroupsService  # noqa: E402

if TYPE_CHECKING:
    from thon.config import ThonConfig


@dataclass
class UserInfo:
    group: str
    username: str

    @property
    def workspace(self) -> str:
        return f"{self.group}/{self.username}"

    @property
    def label(self) -> str:
        return f"{self.group}/{self.username}"


@dataclass
class SandboxInstance:
    user: UserInfo
    port: int
    sandbox: Sandbox
    endpoint: str
    password: Optional[str] = None


def load_groups(groups_file: str, group_filter: Optional[str] = None) -> list[UserInfo]:
    with open(groups_file) as f:
        data = yaml.safe_load(f)

    groups = data.get("groups", {})
    users: list[UserInfo] = []

    for group_name, group_data in groups.items():
        if group_filter and group_name != group_filter:
            continue
        for username in group_data.get("users", []):
            users.append(UserInfo(group=group_name, username=username))

    return users


def _load_users_from_db(
    db_path: Optional[str] = None, group_filter: Optional[str] = None
) -> list[UserInfo]:
    """Read users from the database, optionally filtered by group name."""
    from app.db import GroupRecord as DBGroupRecord, UserRecord as DBUserRecord, get_session as db_get_session
    from sqlmodel import select as sql_select

    users: list[UserInfo] = []
    try:
        with db_get_session(db_path) as session:
            group_name_map: dict[str, str] = {}
            for g in session.exec(sql_select(DBGroupRecord)).all():
                group_name_map[g.id] = g.name
            for db_u in session.exec(sql_select(DBUserRecord)).all():
                gname = group_name_map.get(db_u.group_id, "default")
                if group_filter and gname != group_filter:
                    continue
                users.append(UserInfo(group=gname, username=db_u.username))
    except Exception as e:
        print(f"Error reading from database: {e}")
    return users


def _resolve_file_content(
    file_path: Optional[str], db_key: str, label: str, db_path: Optional[str] = None
) -> Optional[str]:
    """Resolve config file content from a file path or the database.

    Priority: file_path (if provided and exists) > database (if stored) > None.
    """
    if file_path:
        resolved = resolve_path(file_path)
        if resolved.exists():
            with open(resolved) as f:
                content = f.read()
            return content
        print(f"Warning: {label} not found at {file_path}")
    from app.db import get_setting
    db_content = get_setting(db_key, db_path=db_path)
    if db_content and db_content.strip():
        return db_content
    return None


def _ensure_docker_volume(volume_name: str) -> None:
    """Create a Docker named volume if it does not already exist."""
    try:
        subprocess.run(
            ["docker", "volume", "create", volume_name],
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Warning: Failed to create Docker volume '{volume_name}': {e}")


def _ensure_volumes_for_users(
    db_user_map: dict[tuple[str, str], object]
) -> None:
    """Ensure all PVC volumes referenced by DB user records exist."""
    ensured = 0
    for db_user in db_user_map.values():
        if not hasattr(db_user, "workspace_path") or not db_user.workspace_path:
            continue
        if db_user.workspace_path.startswith("thon-"):
            _ensure_docker_volume(db_user.workspace_path)
            ensured += 1
    if ensured:
        print(f"  Ensured {ensured} Docker volume(s) exist")


def generate_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)


def detect_external_ip() -> Optional[str]:
    """Detect the external IP from hostname -I, filtering private ranges."""
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            check=True,
        )
        ips = result.stdout.strip().split()
        for ip in ips:
            if ip.startswith(("10.", "172.", "127.", "192.168.")):
                continue
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                return ip
    except Exception:
        pass
    return None


def parse_endpoint_port(endpoint_str: str) -> int:
    """Extract the port after the IP from an endpoint string.

    Examples:
      "127.0.0.1:8443"             -> 8443
      "127.0.0.1:55002/proxy/8443" -> 55002
    """
    host_port_part = endpoint_str.split("/", 1)[0]
    if ":" in host_port_part:
        return int(host_port_part.rsplit(":", 1)[1])
    return 80


async def _print_logs(label: str, execution) -> None:
    for msg in execution.logs.stdout:
        print(f"[{label} stdout] {msg.text}")
    for msg in execution.logs.stderr:
        print(f"[{label} stderr] {msg.text}")
    if execution.error:
        print(f"[{label} error] {execution.error.name}: {execution.error.value}")


async def _inject_kilo_config(
    user: UserInfo, sandbox: "Sandbox", config_content: str
) -> None:
    if "PLACEHOLDER" in config_content:
        print(
            f"[{user.label}] Warning: kilo.json contains PLACEHOLDER — "
            f"run setup-lemonade.sh --generate-keys to generate real API keys"
        )

    kilo_dir = "/home/vscode/.config/kilo"
    await sandbox.commands.run(f"mkdir -p {kilo_dir}")
    encoded = base64.b64encode(config_content.encode()).decode()
    write_cmd = f"echo {encoded} | base64 -d > {kilo_dir}/config.json"
    await sandbox.commands.run(write_cmd)
    print(f"[{user.label}] Injected kilo config -> {kilo_dir}/config.json")


async def _inject_vscode_settings(
    user: UserInfo, sandbox: "Sandbox", settings_content: str
) -> None:
    try:
        with open(settings_path) as f:
            settings_content = f.read()
    except FileNotFoundError:
        print(
            f"[{user.label}] Warning: VS Code settings not found at {settings_path}, skipping"
        )
        return

    settings_dir = "/home/vscode/.local/share/code-server/User"
    await sandbox.commands.run(f"mkdir -p {settings_dir}")
    encoded = base64.b64encode(settings_content.encode()).decode()
    write_cmd = f"echo {encoded} | base64 -d > {settings_dir}/settings.json"
    await sandbox.commands.run(write_cmd)
    print(f"[{user.label}] Injected VS Code settings -> {settings_dir}/settings.json")


async def create_instance(
    user: UserInfo,
    port: int,
    config: ConnectionConfig,
    image: str,
    python_version: str,
    timeout: timedelta,
    external_ip: Optional[str] = None,
    secure: bool = False,
    workspace_dir: Optional[str] = None,
    lemonade_config_content: Optional[str] = None,
    vscode_settings_content: Optional[str] = None,
    gateway_api_key: Optional[str] = None,
    gateway_external_ip: Optional[str] = None,
    db_user: Optional[object] = None,
) -> SandboxInstance:
    env = {"PYTHON_VERSION": python_version}

    volumes: list[Volume] | None = None
    if (
        db_user
        and hasattr(db_user, "workspace_path")
        and db_user.workspace_path
        and db_user.workspace_path.startswith("thon-")
    ):
        volumes = [
            Volume(
                name="workspace",
                pvc=PVC(claimName=db_user.workspace_path),
                mountPath="/workspace",
            ),
        ]
        if db_user.storage_path and db_user.storage_path.startswith("thon-"):
            volumes.append(
                Volume(
                    name="storage",
                    pvc=PVC(claimName=db_user.storage_path),
                    mountPath="/storage",
                    readOnly=False,
                ),
            )
        print(
            f"[{user.label}] Mounting PVC volumes: {db_user.workspace_path} -> /workspace"
        )
        if len(volumes) > 1:
            print(f"[{user.label}]   storage: {db_user.storage_path} -> /storage")
    elif workspace_dir:
        host_path = os.path.join(workspace_dir, user.workspace)
        os.makedirs(host_path, exist_ok=True)
        volumes = [
            Volume(
                name=f"workspace-{user.group}-{user.username}",
                host=Host(path=host_path),
                mount_path="/workspace",
            )
        ]
        print(f"[{user.label}] Bind-mounting {host_path} -> /workspace")

    metadata = {
        "group": user.group,
        "username": user.username,
        "port": str(port),
        "managed-by": "thon-client",
    }

    sandbox = await Sandbox.create(
        image,
        connection_config=config,
        env=env,
        timeout=timeout,
        volumes=volumes,
        metadata=metadata,
    )

    endpoint = await sandbox.get_endpoint(port)
    endpoint_str = endpoint.endpoint
    endpoint_port = parse_endpoint_port(endpoint_str)
    network_mode = "bridge" if "/" in endpoint_str else "host"
    print(f"[{user.label}] Endpoint: {endpoint_str} (detected {network_mode} mode)")

    upsert_record(
        sandbox_id=sandbox.id if hasattr(sandbox, "id") else "",
        group_name=user.group,
        username=user.username,
        port=endpoint_port,
        endpoint=endpoint_str,
        external_ip=external_ip,
        image=image,
        db_path=os.getenv("THON_DB_PATH"),
    )

    password = None
    auth_flag = "--auth none"
    if secure:
        password = generate_password()
        auth_flag = "--auth password"

    if not volumes:
        await sandbox.commands.run("mkdir -p /workspace")
        await sandbox.commands.run("chown -R vscode:vscode /workspace")

    if lemonade_config_content:
        await _inject_kilo_config(user, sandbox, lemonade_config_content)

    if vscode_settings_content:
        await _inject_vscode_settings(user, sandbox, vscode_settings_content)

    if gateway_api_key:
        from apisix_gateway import generate_kilo_gateway_config

        gateway_url = f"http://{gateway_external_ip}:9080"
        kilo_content = generate_kilo_gateway_config(
            gateway_url=gateway_url,
            api_key=gateway_api_key,
            enable_embedding=True,
        )
        kilo_dir = "/home/vscode/.config/kilo"
        await sandbox.commands.run(f"mkdir -p {kilo_dir}")
        encoded = base64.b64encode(kilo_content.encode()).decode()
        write_cmd = f"echo {encoded} | base64 -d > {kilo_dir}/config.json"
        await sandbox.commands.run(write_cmd)
        print(f"[{user.label}] Injected gateway kilo config -> {kilo_dir}/config.json")

    if secure and password:
        config_dir = "/home/vscode/.config/code-server"
        config_content = (
            f"bind-addr: 0.0.0.0:{port}\n"
            f"auth: password\n"
            f"password: {password}\n"
            f"cert: false\n"
        )
        await sandbox.commands.run(f"mkdir -p {config_dir}")
        write_config = (
            f"cat > {config_dir}/config.yaml << 'CONFIGEOF'\n{config_content}CONFIGEOF"
        )
        await sandbox.commands.run(write_config)

    code_server_cmd = (
        f"code-server --bind-addr 0.0.0.0:{port} "
        f"{auth_flag} "
        f"--disable-telemetry "
        f"/workspace"
    )
    print(f"[{user.label}] Starting code-server on port {port}")

    start_exec = await sandbox.commands.run(
        code_server_cmd,
        opts=RunCommandOpts(background=True),
    )
    await _print_logs(user.label, start_exec)

    return SandboxInstance(
        user=user,
        port=endpoint_port,
        sandbox=sandbox,
        endpoint=endpoint_str,
        password=password,
    )


async def run_from_config(
    thon_cfg: "ThonConfig",
    group_filter: Optional[str] = None,
) -> None:
    """Run VS Code instances directly from a ThonConfig object.

    This is the programmatic entry point used by ``thon run`` so it
    doesn't need to shell out to a subprocess.
    """
    use_nginx = thon_cfg.nginx.enabled

    external_ip = thon_cfg.external_ip or detect_external_ip()
    if external_ip and not thon_cfg.external_ip:
        print(f"[Auto] Detected external IP: {external_ip}")

    if external_ip:
        set_setting("external_ip", external_ip, db_path=os.getenv("THON_DB_PATH"))

    domain = thon_cfg.sandbox.domain or os.getenv("SANDBOX_DOMAIN", "localhost:8080")
    api_key = thon_cfg.sandbox.api_key or os.getenv("SANDBOX_API_KEY")
    image = thon_cfg.sandbox.image or os.getenv(
        "SANDBOX_IMAGE", "waterpistol/thon:latest"
    )
    python_version = thon_cfg.sandbox.python_version or "3.11"
    starting_port = thon_cfg.sandbox.starting_port
    timeout_minutes = thon_cfg.sandbox.timeout_minutes
    secure = thon_cfg.vscode.secure
    workspace_dir = thon_cfg.workspace.dir or None
    lemonade_path = thon_cfg.kilo.config_file or None
    vscode_settings_path = thon_cfg.vscode.settings_file or None

    user_tuples = thon_cfg.get_users(group_filter)
    users = [UserInfo(group=g, username=u) for g, u in user_tuples]
    if not users:
        users = [UserInfo(group="default", username="workspace")]

    groups_svc = GroupsService(
        db_path=os.getenv("THON_DB_PATH"),
        workspace_dir=workspace_dir,
    )
    yaml_data = {
        "groups": {
            name: {"users": user_list} for name, user_list in thon_cfg.groups.items()
        }
    }
    groups_svc.import_from_yaml(yaml_data)
    groups_svc.backfill_storage_paths()

    total = len(users)
    port_range = f"{starting_port} - {starting_port + total - 1}"

    print(f"Starting {total} VS Code sandbox instance(s)...")
    print(f"  Domain: {domain}")
    print(f"  Image: {image}")
    print(f"  Port range: {port_range}")
    print(f"  Secure: {'Yes (per-user passwords)' if secure else 'No (--auth none)'}")
    print(f"  Nginx: {'Yes (HTTPS)' if use_nginx else 'No (direct HTTP)'}")
    if external_ip:
        print(f"  External IP: {external_ip}")
    if workspace_dir:
        print(f"  Workspace dir: {workspace_dir} (persistent bind mounts)")
    if lemonade_path:
        print(f"  Lemonade: {lemonade_path} (Kilo Code config injection)")
    if vscode_settings_path:
        print(f"  VS Code settings: {vscode_settings_path}")
    if thon_cfg.gateway.enabled:
        print(
            f"  AI Gateway: enabled (rate limit: {thon_cfg.gateway.rate_limit} tokens/{thon_cfg.gateway.time_window}s)"
        )
        if thon_cfg.gateway.redis_host:
            print(f"  Gateway Redis: {thon_cfg.gateway.redis_host}")
    if group_filter:
        print(f"  Group filter: {group_filter}")
    print()

    conn_config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=60),
    )
    sandbox_timeout = (
        timedelta(minutes=timeout_minutes) if timeout_minutes > 0 else None
    )

    db_user_map: dict[tuple[str, str], object] = {}
    try:
        from app.db import (
            GroupRecord as DBGroupRecord,
            UserRecord as DBUserRecord,
            get_session as db_get_session,
        )
        from sqlmodel import select as sql_select

        with db_get_session(os.getenv("THON_DB_PATH")) as session:
            group_name_map: dict[str, str] = {}
            for g in session.exec(sql_select(DBGroupRecord)).all():
                group_name_map[g.id] = g.name
            for db_u in session.exec(sql_select(DBUserRecord)).all():
                gname = group_name_map.get(db_u.group_id, "default")
                db_user_map[(gname, db_u.username)] = db_u
    except Exception:
        pass

    instances: list[SandboxInstance] = []

    gateway_consumers: list[dict] = []
    if thon_cfg.gateway.enabled:
        from apisix_gateway import ApisixGatewayManager

        admin_key = thon_cfg.gateway.admin_key or os.getenv(
            "GATEWAY_ADMIN_KEY", "edd1c9f034335f136f87ad84b625c8f1"
        )
        gateway_mgr = ApisixGatewayManager(
            admin_url="http://127.0.0.1:9180",
            admin_key=admin_key,
            redis_host=thon_cfg.gateway.redis_host or None,
            redis_port=thon_cfg.gateway.redis_port,
        )

        lemonade_host = thon_cfg.lemonade.host or "127.0.0.1"
        if lemonade_host == "0.0.0.0":
            lemonade_host = "127.0.0.1"
        lemonade_port = str(thon_cfg.lemonade.port)
        lemonade_url = f"http://{lemonade_host}:{lemonade_port}"
        lemonade_api_key = thon_cfg.lemonade.api_key or os.getenv("LEMONADE_API_KEY")

        gateway_mgr.create_ai_route(
            lemonade_url=lemonade_url,
            lemonade_api_key=lemonade_api_key,
        )

        if thon_cfg.gateway.mode == "per-group":
            group_names: dict[str, list[UserInfo]] = {}
            for user in users:
                group_names.setdefault(user.group, []).append(user)
            for gn, group_users in group_names.items():
                user_count = len(group_users)
                group_rate_limit = thon_cfg.gateway.rate_limit * user_count
                consumer = gateway_mgr.create_consumer(
                    username=f"group-{gn}",
                    rate_limit=group_rate_limit,
                    time_window=thon_cfg.gateway.time_window,
                )
                for user in group_users:
                    gateway_consumers.append(
                        {
                            "user": user,
                            "api_key": consumer.api_key,
                            "rate_limit": consumer.rate_limit,
                            "time_window": consumer.time_window,
                            "group_name": gn,
                            "user_count": user_count,
                        }
                    )
                print(
                    f"[Gateway] Created group consumer: group-{gn} ({user_count} users, {group_rate_limit} tokens/{thon_cfg.gateway.time_window}s)"
                )
        else:
            for user in users:
                consumer = gateway_mgr.create_consumer(
                    username=user.label,
                    rate_limit=thon_cfg.gateway.rate_limit,
                    time_window=thon_cfg.gateway.time_window,
                )
                gateway_consumers.append(
                    {
                        "user": user,
                        "api_key": consumer.api_key,
                        "rate_limit": consumer.rate_limit,
                        "time_window": consumer.time_window,
                    }
                )
    try:
        tasks = []
        for i, user in enumerate(users):
            gw_api_key = None
            if gateway_consumers:
                for gc in gateway_consumers:
                    if gc["user"].label == user.label:
                        gw_api_key = gc["api_key"]
                        break

            db_user = db_user_map.get((user.group, user.username))
            tasks.append(
                create_instance(
                    user=user,
                    port=starting_port + i,
                    config=conn_config,
                    image=image,
                    python_version=python_version,
                    timeout=sandbox_timeout,
                    external_ip=external_ip,
                    secure=secure,
                    workspace_dir=workspace_dir,
                    lemonade_config=lemonade_path,
                    vscode_settings=vscode_settings_path,
                    gateway_api_key=gw_api_key,
                    gateway_external_ip=external_ip,
                    db_user=db_user,
                )
            )

        instances = list(await asyncio.gather(*tasks))

        if use_nginx:
            nginx_gen = NginxConfigGenerator()
            nginx_gen._remove_default_site()

            ssl_gen = SSLCertificateGenerator(output_dir=thon_cfg.nginx.ssl_dir)
            cert_path, key_path = ssl_gen.generate_server_cert(
                server_ip=external_ip,
            )

            ca_cert_path = ""
            ca_root = ssl_gen.get_mkcert_ca_root()
            if ca_root:
                ca_root_pem = os.path.join(ca_root, "rootCA.pem")
                if os.path.exists(ca_root_pem):
                    ca_serve_path = os.path.join(thon_cfg.nginx.ssl_dir, "rootCA.pem")
                    try:
                        shutil.copy2(ca_root_pem, ca_serve_path)
                    except PermissionError:
                        subprocess.run(
                            ["sudo", "cp", ca_root_pem, ca_serve_path],
                            check=True,
                        )
                    ca_cert_path = ca_serve_path
                    print(
                        f"[SSL] CA cert available at https://{external_ip or 'localhost'}/ca.crt"
                    )
                else:
                    print(
                        f"[SSL] Warning: mkcert CA root dir exists but no rootCA.pem in {ca_root}"
                    )
            else:
                print(
                    "[SSL] No mkcert CA root found (ca.crt download unavailable — install mkcert for browser-trusted certs)"
                )

            ports = [inst.port for inst in instances]
            nginx_gen.generate_combined_config(
                ports=ports,
                cert_path=cert_path,
                key_path=key_path,
                ca_cert_path=ca_cert_path,
            )

            nginx_gen.test_config()
            nginx_gen.reload_nginx()

        print("\n" + "=" * 70)
        print("VS Code Web Endpoints")
        print("=" * 70)

        current_group: Optional[str] = None
        for inst in instances:
            if inst.user.group != current_group:
                current_group = inst.user.group
                print(f"\n  Group: {current_group}")

            ext_ip = external_ip or "localhost"
            endpoint_path = (
                inst.endpoint.split(":", 1)[1]
                if ":" in inst.endpoint
                else inst.endpoint
            )

            if use_nginx:
                https_url = f"https://{ext_ip}/{endpoint_path}/"
            else:
                https_url = None

            http_url = f"http://{inst.endpoint}/"

            print(f"    {inst.user.username}:")
            if https_url:
                print(f"      URL: {https_url}")
            print(f"      Local: {http_url}")
            print("      Workspace: /workspace")
            if workspace_dir:
                print(
                    f"      Host path: {os.path.join(workspace_dir, inst.user.workspace)}"
                )
            if inst.password:
                print(f"      Password: {inst.password}")
            if lemonade_path:
                print("      Kilo Code: /home/vscode/.config/kilo/config.json")
            if gateway_consumers:
                for gc in gateway_consumers:
                    if gc["user"].label == inst.user.label:
                        ext_ip = external_ip or "localhost"
                        gateway_url = f"http://{ext_ip}:9080"
                        print(f"      Gateway API Key: {gc['api_key']}")
                        print(
                            f"      Gateway Endpoint: {gateway_url}/v1/chat/completions"
                        )
                        if gc.get("group_name"):
                            print(
                                f"      Gateway Mode: per-group ({gc['group_name']}, {gc.get('user_count', '?')} users sharing)"
                            )
                        print(
                            f"      Rate Limit: {gc['rate_limit']} tokens / {gc['time_window']}s"
                        )
                        break

        print()
        if use_nginx and ca_cert_path:
            ext_ip = external_ip or "localhost"
            print(f"  CA Certificate: https://{ext_ip}/ca.crt")
            print("  (Download and import into browser to trust HTTPS)")
        print(
            f"Keeping sandboxes alive {'indefinitely' if timeout_minutes == 0 else f'for {timeout_minutes} minutes'}. "
            f"Press Ctrl+C to exit."
        )

        try:
            if timeout_minutes > 0:
                await asyncio.sleep(timeout_minutes * 60)
            else:
                await asyncio.Event().wait()
        except KeyboardInterrupt:
            print("\nStopping...")

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        print("\nCleaning up...")

        if thon_cfg.gateway.enabled:
            try:
                from apisix_gateway import ApisixGatewayManager

                admin_key = thon_cfg.gateway.admin_key or os.getenv(
                    "GATEWAY_ADMIN_KEY", "edd1c9f034335f136f87ad84b625c8f1"
                )
                gateway_mgr = ApisixGatewayManager(
                    admin_url="http://127.0.0.1:9180",
                    admin_key=admin_key,
                    redis_host=thon_cfg.gateway.redis_host or None,
                )
                gateway_mgr.cleanup()
            except Exception as e:
                print(f"  Note: Gateway cleanup error: {e}")

        if use_nginx:
            nginx_gen = NginxConfigGenerator()
            try:
                nginx_gen.cleanup_all()
            except Exception as e:
                print(f"  Note: Nginx cleanup error: {e}")

        for inst in instances:
            try:
                await inst.sandbox.kill()
                mark_terminated(
                    inst.sandbox.id if hasattr(inst.sandbox, "id") else "",
                    db_path=os.getenv("THON_DB_PATH"),
                )
            except Exception as e:
                print(
                    f"  Note: Sandbox {inst.user.label} may already be terminated: {e}"
                )

        print("Cleanup complete.")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run VS Code sandbox instances with nginx SSL reverse proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all groups with nginx SSL (default)
  python ./scripts/main.py --groups groups.yaml --external-ip 165.245.138.159

  # Auto-detect external IP
  python ./scripts/main.py --groups groups.yaml

  # Run a single group
  python ./scripts/main.py --groups groups.yaml --group alpha --external-ip 1.2.3.4

  # Start instances for remaining groups from the database
  python ./scripts/main.py --from-db --group beta --external-ip 1.2.3.4

  # Start instances for ALL groups from the database
  python ./scripts/main.py --from-db --external-ip 1.2.3.4

  # With per-user passwords
  python ./scripts/main.py --groups groups.yaml --secure --external-ip 1.2.3.4

  # Direct HTTP without nginx
  python ./scripts/main.py --no-nginx

  # Cleanup all nginx configs
  python ./scripts/main.py --cleanup
        """,
    )

    parser.add_argument(
        "--groups",
        type=str,
        default=None,
        help="Path to groups.yaml file",
    )
    parser.add_argument(
        "--group",
        type=str,
        default=None,
        help="Run only this group (works with --groups or --from-db)",
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        default=False,
        help="Read groups/users from the database instead of a YAML file. "
        "Use --group to filter to a specific group.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help="Starting port for code-server instances (default: 8443)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Timeout in minutes to keep sandboxes alive (default: 0 = no timeout)",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Sandbox domain (default: localhost:8080)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Sandbox API key (optional)",
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="Docker image for sandbox (default: waterpistol/thon:latest)",
    )
    parser.add_argument(
        "--python-version",
        type=str,
        default="3.11",
        help="Python version for the sandbox (default: 3.11)",
    )
    parser.add_argument(
        "--secure",
        action="store_true",
        default=False,
        help="Enable per-user password authentication for code-server",
    )
    parser.add_argument(
        "--external-ip",
        type=str,
        default=None,
        help="External IP for SSL cert SAN and URLs (auto-detected from hostname -I if omitted)",
    )
    parser.add_argument(
        "--ssl-dir",
        type=str,
        default="/etc/nginx/ssl",
        help="Directory to store SSL certificates (default: /etc/nginx/ssl)",
    )
    parser.add_argument(
        "--no-nginx",
        action="store_true",
        default=False,
        help="Disable nginx reverse proxy (use direct HTTP access)",
    )
    parser.add_argument(
        "--workspace-dir",
        type=str,
        default=None,
        help="Host directory for persistent workspace bind mounts (e.g. /thon-workspace). "
        "Each user gets {workspace_dir}/{group}/{username} mounted to /workspace/{group}/{username}",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        default=False,
        help="Remove all sandbox nginx configs and reload, then exit",
    )
    parser.add_argument(
        "--lemonade",
        type=str,
        default=None,
        metavar="KILO_JSON",
        help="Path to kilo.json generated by lemonade_server.py; injected into each sandbox workspace",
    )
    parser.add_argument(
        "--vscode-settings",
        type=str,
        default=None,
        metavar="SETTINGS_JSON",
        help="Path to VS Code settings JSON file; injected into each sandbox's code-server User settings",
    )
    parser.add_argument(
        "--gateway",
        action="store_true",
        default=False,
        help="Enable APISIX AI Gateway with rate limiting and per-consumer API keys",
    )
    parser.add_argument(
        "--gateway-per-group",
        action="store_true",
        default=False,
        help="Create one gateway consumer per group (shared API key) instead of per user",
    )
    parser.add_argument(
        "--gateway-redis-host",
        type=str,
        default=None,
        help="Redis host for gateway rate limiting (default: local policy if not set)",
    )
    parser.add_argument(
        "--gateway-rate-limit",
        type=int,
        default=500,
        help="Token limit per consumer per time window (default: 500)",
    )
    parser.add_argument(
        "--gateway-time-window",
        type=int,
        default=60,
        help="Rate limit time window in seconds (default: 60)",
    )

    args = parser.parse_args()

    if args.cleanup:
        nginx_gen = NginxConfigGenerator()
        nginx_gen.cleanup_all()
        print("Cleanup complete.")
        return

    use_nginx = not args.no_nginx

    external_ip = args.external_ip
    if not external_ip:
        external_ip = detect_external_ip()
        if external_ip:
            print(f"[Auto] Detected external IP: {external_ip}")

    if external_ip:
        set_setting("external_ip", external_ip, db_path=os.getenv("THON_DB_PATH"))

    domain = args.domain or os.getenv("SANDBOX_DOMAIN", "localhost:8080")
    api_key = args.api_key or os.getenv("SANDBOX_API_KEY")
    image = args.image or os.getenv("SANDBOX_IMAGE", "waterpistol/thon:latest")
    python_version = args.python_version or os.getenv("PYTHON_VERSION", "3.11")

    groups_path = resolve_path(args.groups) if args.groups else None

    db_path_env = (
        os.getenv("THON_DB_PATH")
    )

    users: list[UserInfo]
    if args.groups:
        users = load_groups(str(groups_path), group_filter=args.group)
        if not users:
            print("Error: No users found in groups config")
            sys.exit(1)
        if args.group and not any(u.group == args.group for u in users):
            print(f"Error: Group '{args.group}' not found in {args.groups}")
            sys.exit(1)

        with open(groups_path) as f:
            yaml_data = yaml.safe_load(f)
        env_event_id = os.getenv("THON_EVENT_ID")
        groups_svc = GroupsService(
            db_path=db_path_env,
            workspace_dir=args.workspace_dir,
        )
        imported = groups_svc.import_from_yaml(yaml_data, event_id=env_event_id)
        backfilled = groups_svc.backfill_storage_paths()
        if imported > 0:
            print(f"  Synced {imported} user(s) from groups.yaml to database")
        if backfilled > 0:
            print(f"  Backfilled storage paths for {backfilled} user(s)")
    elif args.from_db:
        users = _load_users_from_db(
            db_path=db_path_env,
            group_filter=args.group,
        )
        if not users:
            if args.group:
                print(f"Error: No users found in database for group '{args.group}'")
            else:
                print("Error: No users found in database. Load a groups.yaml first.")
            sys.exit(1)
        print(f"  Loaded {len(users)} user(s) from database")
    else:
        db_users = _load_users_from_db(db_path=db_path_env, group_filter=args.group)
        if db_users:
            users = db_users
            print(f"  Loaded {len(users)} user(s) from database (no flags — using DB config)")
        else:
            from app.db import get_setting
            db_yaml = get_setting("config_groups_yaml", db_path=db_path_env)
            if db_yaml and db_yaml.strip():
                yaml_data = yaml.safe_load(db_yaml)
                groups_list = yaml_data.get("groups", {})
                users = []
                env_event_id = os.getenv("THON_EVENT_ID")
                for group_name, group_data in groups_list.items():
                    group_data = group_data or {}
                    if args.group and group_name != args.group:
                        continue
                    for username in group_data.get("users", []):
                        users.append(UserInfo(group=group_name, username=username))
                if users:
                    groups_svc = GroupsService(
                        db_path=db_path_env,
                        workspace_dir=args.workspace_dir,
                    )
                    groups_svc.import_from_yaml(yaml_data, event_id=env_event_id)
                    groups_svc.backfill_storage_paths()
                    print(f"  Loaded {len(users)} user(s) from DB-stored groups.yaml")
            if not users:
                users = [UserInfo(group="default", username="workspace")]
                groups_svc = GroupsService(
                    db_path=db_path_env,
                    workspace_dir=args.workspace_dir,
                )
                yaml_data = {"groups": {"default": {"users": ["workspace"]}}}
                groups_svc.import_from_yaml(yaml_data)
                groups_svc.backfill_storage_paths()

    lemonade_config_content = _resolve_file_content(
        args.lemonade, "config_kilo_json", "kilo.json", db_path=db_path_env
    )
    vscode_settings_content = _resolve_file_content(
        args.vscode_settings, "config_vscode_settings", "VS Code settings", db_path=db_path_env
    )

    total = len(users)
    port_range = f"{args.port} - {args.port + total - 1}"

    print(f"Starting {total} VS Code sandbox instance(s)...")
    print(f"  Domain: {domain}")
    print(f"  Image: {image}")
    print(f"  Port range: {port_range}")
    print(
        f"  Secure: {'Yes (per-user passwords)' if args.secure else 'No (--auth none)'}"
    )
    print(f"  Nginx: {'Yes (HTTPS)' if use_nginx else 'No (direct HTTP)'}")
    if external_ip:
        print(f"  External IP: {external_ip}")
    if args.workspace_dir:
        print(f"  Workspace dir: {args.workspace_dir} (persistent bind mounts)")
    if lemonade_config_content:
        src = "file" if args.lemonade else "database"
        print(f"  Lemonade: ({src}) Kilo Code config injection")
    if vscode_settings_content:
        src = "file" if args.vscode_settings else "database"
        print(f"  VS Code settings: ({src})")
    if args.gateway:
        print(
            f"  AI Gateway: enabled (rate limit: {args.gateway_rate_limit} tokens/{args.gateway_time_window}s)"
        )
        if args.gateway_redis_host:
            print(f"  Gateway Redis: {args.gateway_redis_host}")
    if args.groups:
        print(f"  Groups file: {args.groups}")
        if args.group:
            print(f"  Group filter: {args.group}")
    elif args.from_db:
        print("  Source: database")
        if args.group:
            print(f"  Group filter: {args.group}")
    print()

    config = ConnectionConfig(
        domain=domain,
        api_key=api_key,
        request_timeout=timedelta(seconds=60),
    )
    sandbox_timeout = timedelta(minutes=args.timeout) if args.timeout > 0 else None

    db_user_map: dict[tuple[str, str], object] = {}
    try:
        from app.db import (
            GroupRecord as DBGroupRecord,
            UserRecord as DBUserRecord,
            get_session as db_get_session,
        )
        from sqlmodel import select as sql_select

        with db_get_session(os.getenv("THON_DB_PATH")) as session:
            group_name_map: dict[str, str] = {}
            for g in session.exec(sql_select(DBGroupRecord)).all():
                group_name_map[g.id] = g.name
            for db_u in session.exec(sql_select(DBUserRecord)).all():
                gname = group_name_map.get(db_u.group_id, "default")
                db_user_map[(gname, db_u.username)] = db_u
    except Exception:
        pass

    _ensure_volumes_for_users(db_user_map)

    instances: list[SandboxInstance] = []

    gateway_consumers: list[dict] = []
    if args.gateway:
        from apisix_gateway import ApisixGatewayManager

        admin_key = os.getenv("GATEWAY_ADMIN_KEY", "edd1c9f034335f136f87ad84b625c8f1")
        gateway_mgr = ApisixGatewayManager(
            admin_url="http://127.0.0.1:9180",
            admin_key=admin_key,
            redis_host=args.gateway_redis_host,
            redis_port=6379,
        )

        lemonade_host = os.getenv("LEMONADE_HOST", "127.0.0.1")
        lemonade_port = os.getenv("LEMONADE_PORT", "13305")
        lemonade_url = f"http://{lemonade_host}:{lemonade_port}"
        lemonade_api_key = os.getenv("LEMONADE_API_KEY")

        gateway_mgr.create_ai_route(
            lemonade_url=lemonade_url,
            lemonade_api_key=lemonade_api_key,
        )
        gateway_mgr.create_embedding_route(
            lemonade_url=lemonade_url,
            lemonade_api_key=lemonade_api_key,
        )

        if args.gateway_per_group:
            group_names: dict[str, list[UserInfo]] = {}
            for user in users:
                group_names.setdefault(user.group, []).append(user)
            for group_name, group_users in group_names.items():
                user_count = len(group_users)
                group_rate_limit = args.gateway_rate_limit * user_count
                consumer = gateway_mgr.create_consumer(
                    username=f"group-{group_name}",
                    rate_limit=group_rate_limit,
                    time_window=args.gateway_time_window,
                )
                for user in group_users:
                    gateway_consumers.append(
                        {
                            "user": user,
                            "api_key": consumer.api_key,
                            "rate_limit": consumer.rate_limit,
                            "time_window": consumer.time_window,
                            "group_name": group_name,
                            "user_count": user_count,
                        }
                    )
                print(
                    f"[Gateway] Created group consumer: group-{group_name} ({user_count} users, {group_rate_limit} tokens/{args.gateway_time_window}s)"
                )
        else:
            for user in users:
                consumer = gateway_mgr.create_consumer(
                    username=user.label,
                    rate_limit=args.gateway_rate_limit,
                    time_window=args.gateway_time_window,
                )
                gateway_consumers.append(
                    {
                        "user": user,
                        "api_key": consumer.api_key,
                        "rate_limit": consumer.rate_limit,
                        "time_window": consumer.time_window,
                    }
                )
    try:
        tasks = []
        for i, user in enumerate(users):
            gateway_api_key = None
            if gateway_consumers:
                for gc in gateway_consumers:
                    if gc["user"].label == user.label:
                        gateway_api_key = gc["api_key"]
                        break

            db_user = db_user_map.get((user.group, user.username))
            tasks.append(
                create_instance(
                    user=user,
                    port=args.port + i,
                    config=config,
                    image=image,
                    python_version=python_version,
                    timeout=sandbox_timeout,
                    external_ip=external_ip,
                    secure=args.secure,
                    workspace_dir=args.workspace_dir,
                    lemonade_config_content=lemonade_config_content,
                    vscode_settings_content=vscode_settings_content,
                    gateway_api_key=gateway_api_key,
                    gateway_external_ip=external_ip,
                    db_user=db_user,
                )
            )

        instances = list(await asyncio.gather(*tasks))

        if use_nginx:
            nginx_gen = NginxConfigGenerator()
            nginx_gen._remove_default_site()

            ssl_gen = SSLCertificateGenerator(output_dir=args.ssl_dir)
            cert_path, key_path = ssl_gen.generate_server_cert(
                server_ip=external_ip,
            )

            ca_cert_path = ""
            ca_root = ssl_gen.get_mkcert_ca_root()
            if ca_root:
                ca_root_pem = os.path.join(ca_root, "rootCA.pem")
                if os.path.exists(ca_root_pem):
                    ca_serve_path = os.path.join(args.ssl_dir, "rootCA.pem")
                    try:
                        shutil.copy2(ca_root_pem, ca_serve_path)
                    except PermissionError:
                        subprocess.run(
                            ["sudo", "cp", ca_root_pem, ca_serve_path],
                            check=True,
                        )
                    ca_cert_path = ca_serve_path
                    print(
                        f"[SSL] CA cert available at https://{external_ip or 'localhost'}/ca.crt"
                    )
                else:
                    print(
                        f"[SSL] Warning: mkcert CA root dir exists but no rootCA.pem in {ca_root}"
                    )
            else:
                print(
                    "[SSL] No mkcert CA root found (ca.crt download unavailable — install mkcert for browser-trusted certs)"
                )

            ports = [inst.port for inst in instances]
            nginx_gen.generate_combined_config(
                ports=ports,
                cert_path=cert_path,
                key_path=key_path,
                ca_cert_path=ca_cert_path,
            )

            nginx_gen.test_config()
            nginx_gen.reload_nginx()

        print("\n" + "=" * 70)
        print("VS Code Web Endpoints")
        print("=" * 70)

        current_group: Optional[str] = None
        for inst in instances:
            if inst.user.group != current_group:
                current_group = inst.user.group
                print(f"\n  Group: {current_group}")

            ext_ip = external_ip or "localhost"
            endpoint_path = (
                inst.endpoint.split(":", 1)[1]
                if ":" in inst.endpoint
                else inst.endpoint
            )

            if use_nginx:
                https_url = f"https://{ext_ip}/{endpoint_path}/"
            else:
                https_url = None

            http_url = f"http://{inst.endpoint}/"

            print(f"    {inst.user.username}:")
            if https_url:
                print(f"      URL: {https_url}")
            print(f"      Local: {http_url}")
            print("      Workspace: /workspace")
            if args.workspace_dir:
                print(
                    f"      Host path: {os.path.join(args.workspace_dir, inst.user.workspace)}"
                )
            if inst.password:
                print(f"      Password: {inst.password}")
            if lemonade_config_content:
                print("      Kilo Code: /home/vscode/.config/kilo/config.json")
            if gateway_consumers:
                for gc in gateway_consumers:
                    if gc["user"].label == inst.user.label:
                        ext_ip = external_ip or "localhost"
                        gateway_url = f"http://{ext_ip}:9080"
                        print(f"      Gateway API Key: {gc['api_key']}")
                        print(f"      Gateway Chat: {gateway_url}/v1/chat/completions")
                        print(f"      Gateway Embedding: {gateway_url}/v1/embeddings")
                        if gc.get("group_name"):
                            print(
                                f"      Gateway Mode: per-group ({gc['group_name']}, {gc.get('user_count', '?')} users sharing)"
                            )
                        print(
                            f"      Rate Limit: {gc['rate_limit']} tokens / {gc['time_window']}s"
                        )
                        break

        print()
        if use_nginx and ca_cert_path:
            ext_ip = external_ip or "localhost"
            print(f"  CA Certificate: https://{ext_ip}/ca.crt")
            print("  (Download and import into browser to trust HTTPS)")
        print(
            f"Keeping sandboxes alive {'indefinitely' if args.timeout == 0 else f'for {args.timeout} minutes'}. "
            f"Press Ctrl+C to exit."
        )

        try:
            if args.timeout > 0:
                await asyncio.sleep(args.timeout * 60)
            else:
                await asyncio.Event().wait()
        except KeyboardInterrupt:
            print("\nStopping...")

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        print("\nCleaning up...")

        if args.gateway:
            try:
                from apisix_gateway import ApisixGatewayManager

                admin_key = os.getenv(
                    "GATEWAY_ADMIN_KEY", "edd1c9f034335f136f87ad84b625c8f1"
                )
                gateway_mgr = ApisixGatewayManager(
                    admin_url="http://127.0.0.1:9180",
                    admin_key=admin_key,
                    redis_host=args.gateway_redis_host,
                )
                gateway_mgr.cleanup()
            except Exception as e:
                print(f"  Note: Gateway cleanup error: {e}")

        if use_nginx:
            nginx_gen = NginxConfigGenerator()
            try:
                nginx_gen.cleanup_all()
            except Exception as e:
                print(f"  Note: Nginx cleanup error: {e}")

        for inst in instances:
            try:
                await inst.sandbox.kill()
                mark_terminated(
                    inst.sandbox.id if hasattr(inst.sandbox, "id") else "",
                    db_path=os.getenv("THON_DB_PATH"),
                )
            except Exception as e:
                print(
                    f"  Note: Sandbox {inst.user.label} may already be terminated: {e}"
                )

        print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
