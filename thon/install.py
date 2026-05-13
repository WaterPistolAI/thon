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

"""System-level package installer for THON — ``python -m thon install``.

Installs OS packages, configures the OpenSandbox server, and optionally
sets up APISIX and Lemonade.  Idempotent — safe to re-run.

This phase is *config-free* — it only touches system packages and
generates the ``~/.sandbox.toml`` that later phases (``thon init``,
``thon setup``) read from.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Optional



def _run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True, **kwargs)  # type: ignore[arg-type]


def _yes_no(label: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    raw = input(f"  {label} [{d}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def _is_installed(package: str) -> bool:
    result = _run(["dpkg", "-s", package])
    return result.returncode == 0


def _section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _info(msg: str) -> None:
    print(f"  ℹ  {msg}")


def _ok(msg: str) -> None:
    print(f"  ✓  {msg}")


def install_system_packages() -> None:
    _section("System Packages")
    _info("Installing core prerequisites (nginx, docker, mkcert, openssl)...")

    packages = [
        "python3-full",
        "python3-venv",
        "python3-pip",
        "python-is-python3",
        "nginx",
        "mkcert",
        "docker.io",
        "docker-buildx",
        "openssl",
        "ca-certificates",
        "curl",
        "libnss3-tools",
        "software-properties-common",
    ]

    subprocess.run(["sudo", "apt-get", "update"], check=False)
    subprocess.run(
        ["sudo", "apt-get", "install", "-y", "--no-install-recommends"] + packages,
        check=False,
    )
    _ok("Core packages installed")


def install_docker_group() -> None:
    if not _is_installed("docker.io"):
        return
    result = _run(["groups"])
    if result.returncode == 0 and "docker" in result.stdout:
        _ok("User already in docker group")
        return
    _info("Adding user to docker group...")
    subprocess.run(["sudo", "usermod", "-aG", "docker", os.environ["USER"]], check=False)
    _info("Run 'newgrp docker' or log out/in for group change to take effect")


def install_ssl_dirs(ssl_dir: str = "/etc/nginx/ssl") -> None:
    _section("SSL & Nginx")
    subprocess.run(["sudo", "mkdir", "-p", ssl_dir], check=False)
    username = os.environ.get("USER", os.environ.get("LOGNAME", ""))
    if username:
        subprocess.run(
            ["sudo", "chown", "-R", f"{username}:{username}", ssl_dir], check=False
        )

    for d in ["/etc/nginx/sites-available", "/etc/nginx/sites-enabled"]:
        subprocess.run(["sudo", "mkdir", "-p", d], check=False)
        if username:
            subprocess.run(
                ["sudo", "chown", "-R", f"{username}:{username}", d], check=False
            )

    nginx_conf = Path("/etc/nginx/nginx.conf")
    if nginx_conf.exists():
        content = nginx_conf.read_text()
        if "sites-enabled" not in content:
            _info("Adding sites-enabled include to nginx.conf...")
            subprocess.run(
                [
                    "sudo",
                    "sed",
                    "-i",
                    r"/http {/a\\\\tinclude /etc/nginx/sites-enabled/*;",
                    str(nginx_conf),
                ],
                check=False,
            )

    default_site = Path("/etc/nginx/sites-enabled/default")
    if default_site.exists():
        subprocess.run(["sudo", "rm", "-f", str(default_site)], check=False)

    subprocess.run(["sudo", "mkcert", "-install"], check=False)
    _ok(f"SSL dir: {ssl_dir}")
    _ok("Nginx dirs configured")


def install_opensandbox(project_root: Path) -> None:
    _section("OpenSandbox")

    venv_dir = Path.home() / ".venv"
    if not (venv_dir / "bin" / "python").exists():
        _info("Creating ~/.venv...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    else:
        _ok("~/.venv already exists")

    pip_path = str(venv_dir / "bin" / "pip")
    _info("Installing opensandbox SDK + CLI...")
    subprocess.run([pip_path, "install", "opensandbox", "opensandbox-cli"], check=False)
    _ok("opensandbox installed")

    toml_path = Path.home() / ".sandbox.toml"
    if not toml_path.exists():
        _info("Initializing ~/.sandbox.toml...")
        cli_path = str(venv_dir / "bin" / "opensandbox-server")
        subprocess.run(
            [cli_path, "init-config", str(toml_path), "--example", "docker"],
            check=False,
        )
    else:
        _ok("~/.sandbox.toml already exists")

    _ensure_sandbox_api_key(toml_path)

    dockerfile = project_root / "Dockerfile"
    if dockerfile.exists():
        _info("Building Docker image waterpistol/thon:latest...")
        subprocess.run(
            ["docker", "build", "-t", "waterpistol/thon:latest", "-f", str(dockerfile), str(project_root)],
            check=False,
        )
        _ok("Docker image built")
    else:
        _info("No Dockerfile found — skipping image build")


def _ensure_sandbox_api_key(toml_path: Path) -> None:
    import tomllib

    if not toml_path.exists():
        return

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    server = data.get("server", {})
    if not isinstance(server, dict):
        return

    existing_key = server.get("api_key", "")
    if isinstance(existing_key, str) and existing_key.strip():
        _ok("~/.sandbox.toml already has an API key")
        return

    api_key = secrets.token_urlsafe(24)
    _write_toml_api_key(toml_path, api_key)
    _ok("Generated and wrote API key to ~/.sandbox.toml")


def _write_toml_api_key(toml_path: Path, api_key: str) -> None:
    content = toml_path.read_text()
    import re

    new_content = re.sub(
        r'^#\s*api_key\s*=\s*"[^"]*"',
        f'api_key = "{api_key}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if new_content != content:
        toml_path.write_text(new_content)
        return

    new_content = re.sub(
        r'^api_key\s*=\s*""',
        f'api_key = "{api_key}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if new_content != content:
        toml_path.write_text(new_content)
        return

    lines = content.split("\n")
    result: list[str] = []
    for line in lines:
        result.append(line)
        if line.strip() == "[server]":
            result.append(f'api_key = "{api_key}"')
    toml_path.write_text("\n".join(result))


def install_apisix() -> None:
    _section("APISIX AI Gateway")

    if _is_installed("apisix"):
        _ok("APISIX already installed")
    else:
        _info("Installing etcd, Redis, and APISIX...")
        subprocess.run(["sudo", "apt-get", "update"], check=False)
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "--no-install-recommends", "etcd-server", "redis"],
            check=False,
        )

        _info("Adding APISIX repository...")
        subprocess.run(
            ["wget", "-q", "-O", "/tmp/apisix-gpg.key", "http://repos.apiseven.com/pubkey.gpg"],
            check=False,
        )
        subprocess.run(
            ["sudo", "gpg", "--dearmor", "-o", "/etc/apt/trusted.gpg.d/apisix.gpg", "/tmp/apisix-gpg.key"],
            check=False,
        )
        Path("/tmp/apisix-gpg.key").unlink(missing_ok=True)

        sources_path = Path("/etc/apt/sources.list.d/apisix.list")
        sources_path.write_text("deb http://repos.apiseven.com/packages/debian bullseye main\n")
        subprocess.run(["sudo", "apt-get", "update"], check=False)
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "--no-install-recommends", "apisix"],
            check=False,
        )
        _ok("APISIX packages installed")

    _configure_apisix_admin_key()


def _configure_apisix_admin_key() -> None:
    import re

    config_path = Path("/usr/local/apisix/conf/config.yaml")
    if not config_path.exists():
        _info("APISIX config not found — skipping admin key configuration")
        return

    content = config_path.read_text()
    key_match = re.search(r"^\s*key:\s*['\"]?(\S+?)['\"]?\s*$", content, re.MULTILINE)
    if key_match and key_match.group(1):
        _ok("APISIX admin key already configured")
        return

    admin_key = secrets.token_urlsafe(24)

    if "admin_key:" in content:
        if re.search(r"key:\s*['\"]{2}", content):
            content = re.sub(
                r"key:\s*['\"]{2}.*$",
                f"key: {admin_key}",
                content,
                count=1,
                flags=re.MULTILINE,
            )
        elif re.search(r"key:\s*$", content, re.MULTILINE):
            content = re.sub(
                r"key:\s*$",
                f"key: {admin_key}",
                content,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            content = content.replace(
                "admin_key:",
                f"admin_key:\n      - name: admin\n        key: {admin_key}\n        role: admin",
            )
    else:
        content += f"\ndeployment:\n  admin:\n    admin_key:\n      - name: admin\n        key: {admin_key}\n        role: admin\n    admin_listen:\n      ip: 0.0.0.0\n      port: 9180\n"

    try:
        config_path.write_text(content)
    except PermissionError:
        tmp = Path(f"/tmp/apisix-config-{os.getpid()}.yaml")
        tmp.write_text(content)
        subprocess.run(["sudo", "cp", str(tmp), str(config_path)], check=True)
        tmp.unlink(missing_ok=True)

    _ok("APISIX admin key configured")

    subprocess.run(["sudo", "systemctl", "enable", "etcd"], check=False)
    subprocess.run(["sudo", "systemctl", "start", "etcd"], check=False)
    subprocess.run(["sudo", "systemctl", "enable", "redis-server"], check=False)
    subprocess.run(["sudo", "systemctl", "start", "redis-server"], check=False)
    subprocess.run(["sudo", "systemctl", "enable", "apisix"], check=False)
    subprocess.run(["sudo", "systemctl", "start", "apisix"], check=False)

    _info("Waiting for APISIX to be ready...")
    for _ in range(30):
        result = _run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "http://127.0.0.1:9180/apisix/admin/routes",
                "-H",
                f"X-API-KEY: {admin_key}",
            ]
        )
        if "200" in result.stdout:
            _ok("APISIX is ready")
            return
        import time

        time.sleep(1)
    _info("APISIX did not respond within 30s — it may need manual start")


def install_lemonade() -> None:
    _section("Lemonade Server (Local LLM Inference)")

    if _is_installed("lemonade-server"):
        _ok("lemonade-server already installed")
    else:
        _info("Adding lemonade-server PPA...")
        subprocess.run(
            ["sudo", "add-apt-repository", "-y", "ppa:lemonade-team/stable"], check=False
        )
        subprocess.run(["sudo", "apt-get", "update"], check=False)
        subprocess.run(
            ["sudo", "apt-get", "install", "-y", "--no-install-recommends", "lemonade-server"],
            check=False,
        )
        subprocess.run(["sudo", "update-pciids"], check=False)
        _ok("lemonade-server installed")


def run_install(
    non_interactive: bool = False,
    install_apisix_flag: Optional[bool] = None,
    install_lemonade_flag: Optional[bool] = None,
    ssl_dir: str = "/etc/nginx/ssl",
) -> None:
    """Run the full install phase.

    Args:
        non_interactive: Skip prompts, install everything.
        install_apisix_flag: Override for whether to install APISIX.
        install_lemonade_flag: Override for whether to install Lemonade.
        ssl_dir: Directory for SSL certificates.
    """
    project_root = Path(__file__).resolve().parent.parent

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║          THON Install — System Prerequisites            ║")
    print("║                                                         ║")
    print("║  This installs OS packages, Docker images, and          ║")
    print("║  generates server configs. Idempotent — safe to rerun.  ║")
    print("╚══════════════════════════════════════════════════════════╝")

    install_system_packages()
    install_docker_group()
    install_ssl_dirs(ssl_dir)
    install_opensandbox(project_root)

    if install_apisix_flag is None:
        if non_interactive:
            install_apisix_flag = False
        else:
            _section("Optional Components")
            install_apisix_flag = _yes_no(
                "Install APISIX AI Gateway (APISIX + etcd + Redis)?", default=False
            )

    if install_apisix_flag:
        install_apisix()

    if install_lemonade_flag is None:
        if non_interactive:
            install_lemonade_flag = True
        else:
            install_lemonade_flag = _yes_no(
                "Install Lemonade Server (local LLM inference)?", default=True
            )

    if install_lemonade_flag:
        install_lemonade()

    print()
    print("═" * 60)
    print("  Install complete!")
    print("═" * 60)
    print()
    print("  Next steps:")
    print("    1. python -m thon init      # Create/update thon.yaml config")
    print("    2. python -m thon setup     # Configure services from thon.yaml")
    print("    3. python -m thon run       # Start the API server")
    print()
