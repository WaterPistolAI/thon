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

"""Sandbox service wrapping sandbox SDK SandboxManager for fleet operations."""

import asyncio
import logging
import os
import secrets
from datetime import timedelta
from typing import Optional

import httpx
from opensandbox import Sandbox, SandboxManager
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.sandboxes import Host, PVC, Volume, SandboxFilter

from app.config import AppConfig, SandboxConfig
from app.nginx_service import NginxConfigGenerator
from app.db import (
    find_user_by_group_and_name,
    find_user_by_sandbox,
    get_groups,
    get_record,
    get_records,
    get_setting,
    link_user_sandbox,
    mark_terminated,
    unlink_user_sandbox,
    update_endpoint,
    upsert_record,
)
from app.exceptions import SandboxOperationError
from app.models import InstanceInfo, InstanceState, UserInfo

try:
    from opensandbox.exceptions.sandbox import SandboxInternalException
except ImportError:
    SandboxInternalException = None

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8443


class SandboxService:
    """High-level service for managing VS Code sandbox instances.

    Wraps the ``SandboxManager`` for fleet-level operations
    (list, kill, pause, resume) and ``Sandbox`` for single-instance interaction
    (create, run commands, get endpoints).
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._sandbox_cfg: SandboxConfig = config.sandbox
        self._manager: Optional[SandboxManager] = None
        self._closed = False
        self._nginx: Optional[NginxConfigGenerator] = None

    @property
    def nginx(self) -> Optional[NginxConfigGenerator]:
        if self._nginx is None and self._config.nginx.external_ip:
            try:
                self._nginx = NginxConfigGenerator()
            except Exception as exc:
                logger.debug("Nginx init failed: %s", exc)
        return self._nginx

    async def _get_manager(self) -> SandboxManager:
        """Lazy-initialize and return the shared SandboxManager."""
        if self._manager is None or self._closed:
            conn = ConnectionConfig(
                domain=self._sandbox_cfg.domain,
                api_key=self._sandbox_cfg.api_key,
                request_timeout=timedelta(
                    seconds=self._sandbox_cfg.request_timeout_seconds
                ),
            )
            self._manager = await SandboxManager.create(conn)
            self._closed = False
        return self._manager

    async def close(self) -> None:
        """Release the manager transport."""
        if self._manager and not self._closed:
            await self._manager.close()
            self._manager = None
            self._closed = True

    @staticmethod
    def _is_sandbox_error(exc: BaseException) -> bool:
        """Check if an exception indicates a sandbox server problem.

        Covers connection failures, broken responses, Docker/image errors,
        and any other server-side failure that means we cannot list sandboxes.
        """
        import json

        if isinstance(exc, httpx.ConnectError):
            return True
        if SandboxInternalException is not None and isinstance(
            exc, SandboxInternalException
        ):
            return True
        if isinstance(exc, json.JSONDecodeError):
            return True
        msg = str(exc).lower()
        return any(
            kw in msg
            for kw in (
                "imagenotfound",
                "no such image",
                "connect",
                "failed",
                "500",
                "internal server error",
            )
        )

    @staticmethod
    def _is_sdk_or_server_error(exc: BaseException) -> bool:
        """Check if an exception originates from the opensandbox SDK or network.

        Only catches errors from the SDK call itself, NOT our own code bugs
        (like AttributeError, KeyError, etc.).
        """
        import json

        if isinstance(exc, httpx.ConnectError):
            return True
        if SandboxInternalException is not None and isinstance(
            exc, SandboxInternalException
        ):
            return True
        if isinstance(exc, json.JSONDecodeError):
            return True
        tb_module = type(exc).__module__
        tb_name = type(exc).__name__
        if tb_module.startswith("opensandbox") or tb_module.startswith("docker"):
            return True
        if tb_module.startswith("httpx") or tb_module.startswith("httpcore"):
            return True
        if "ImageNotFound" in tb_name or "docker.errors" in tb_module:
            return True
        return False

    def sync_nginx(self) -> list[int]:
        """Regenerate nginx config from all active instance endpoints.

        Returns the list of ports that were configured, or empty list
        if nginx is not available.
        """
        ng = self.nginx
        if ng is None:
            return []
        try:
            records = get_records(db_path=self._config.database.path)
            endpoints = [
                r.endpoint
                for r in records.values()
                if r.endpoint and r.port and r.terminated_at is None
            ]
            ports: set[int] = set()
            for ep in endpoints:
                try:
                    host_port = ep.split("/")[0]
                    port_str = host_port.split(":")[1]
                    ports.add(int(port_str))
                except (IndexError, ValueError):
                    continue
            sorted_ports = sorted(ports)
            ng.sync_from_endpoints(endpoints)
            logger.info("Nginx synced: %d port(s) %s", len(sorted_ports), sorted_ports)
            return sorted_ports
        except Exception as exc:
            logger.warning("Nginx sync failed: %s", exc)
            return []

    def _sync_nginx(self) -> None:
        self.sync_nginx()

    # ── Fleet Operations ──────────────────────────────────────────────

    async def list_instances(
        self,
        states: Optional[list[InstanceState]] = None,
        metadata_filter: Optional[dict[str, str]] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[InstanceInfo], int]:
        """List sandbox instances with optional filtering and pagination.

        Returns:
            Tuple of (instances, total_items). Returns ([], 0) if the
            sandbox server is unreachable.
        """
        try:
            mgr = await self._get_manager()
            state_strs = [s.value for s in states] if states else None
            f = SandboxFilter(
                states=state_strs,
                metadata=metadata_filter,
                page=page,
                page_size=page_size,
            )
            result = await mgr.list_sandbox_infos(f)
        except Exception as e:
            if self._is_sdk_or_server_error(e):
                logger.warning("Sandbox server error: %s", e)
                return [], 0
            raise

        instances = []
        for info in result.sandbox_infos:
            meta = info.metadata or {}
            image_str = (
                info.image.image if hasattr(info.image, "image") else str(info.image)
            )
            instances.append(
                InstanceInfo(
                    id=info.id,
                    user=UserInfo(
                        group=meta.get("group", "default"),
                        username=meta.get("username", "workspace"),
                    ),
                    state=InstanceState(info.status.state),
                    port=int(meta.get("port", DEFAULT_PORT)),
                    endpoint=meta.get("endpoint"),
                    image=image_str,
                    created_at=info.created_at,
                    expires_at=info.expires_at,
                    metadata=meta,
                )
            )

        sandbox_ids = [inst.id for inst in instances]
        db_records = get_records(sandbox_ids, db_path=self._config.database.path)
        db_external_ip = None
        for inst in instances:
            rec = db_records.get(inst.id)
            if rec:
                inst.user = UserInfo(group=rec.group_name, username=rec.username)
                if rec.endpoint and not inst.endpoint:
                    inst.endpoint = rec.endpoint
                if rec.port and inst.port == DEFAULT_PORT and rec.port != DEFAULT_PORT:
                    inst.port = rec.port
                if rec.password:
                    inst.password = rec.password
                if rec.external_ip:
                    db_external_ip = rec.external_ip
            elif inst.state in (InstanceState.RUNNING, InstanceState.PAUSED):
                upsert_record(
                    sandbox_id=inst.id,
                    group_name=inst.user.group,
                    username=inst.user.username,
                    port=inst.port,
                    endpoint=inst.endpoint,
                    image=inst.image,
                    db_path=self._config.database.path,
                )

        running_ids = [
            (inst.id, inst.port)
            for inst in instances
            if inst.state == InstanceState.RUNNING and not inst.endpoint
        ]
        if running_ids:
            endpoints = await self._resolve_endpoints(running_ids)
            for inst in instances:
                if inst.id in endpoints:
                    inst.endpoint = endpoints[inst.id]
                    update_endpoint(
                        inst.id, endpoints[inst.id], db_path=self._config.database.path
                    )

        for inst in instances:
            if inst.state == InstanceState.TERMINATED:
                mark_terminated(inst.id, db_path=self._config.database.path)

        for inst in instances:
            if inst.endpoint:
                inst.public_url = self._build_public_url(
                    inst.endpoint, fallback_ip=db_external_ip
                )

        return instances, result.pagination.total_items if result.pagination else len(
            instances
        )

    async def get_instance(self, sandbox_id: str) -> InstanceInfo:
        """Fetch details for a single sandbox instance."""
        mgr = await self._get_manager()
        info = await mgr.get_sandbox_info(sandbox_id)
        meta = info.metadata or {}
        image_str = (
            info.image.image if hasattr(info.image, "image") else str(info.image)
        )
        user = UserInfo(
            group=meta.get("group", "default"),
            username=meta.get("username", "workspace"),
        )
        endpoint = meta.get("endpoint")
        port = int(meta.get("port", DEFAULT_PORT))
        password = None
        rec = get_record(sandbox_id, db_path=self._config.database.path)
        db_external_ip = None
        if rec:
            user = UserInfo(group=rec.group_name, username=rec.username)
            if rec.endpoint and not endpoint:
                endpoint = rec.endpoint
            if rec.port and port == DEFAULT_PORT and rec.port != DEFAULT_PORT:
                port = rec.port
            password = rec.password
            db_external_ip = rec.external_ip
        return InstanceInfo(
            id=info.id,
            user=user,
            state=InstanceState(info.status.state),
            port=port,
            endpoint=endpoint,
            public_url=self._build_public_url(endpoint, fallback_ip=db_external_ip)
            if endpoint
            else None,
            password=password,
            image=image_str,
            created_at=info.created_at,
            expires_at=info.expires_at,
            metadata=meta,
        )

    async def pause_instance(self, sandbox_id: str) -> None:
        """Pause a running sandbox (retains state)."""
        mgr = await self._get_manager()
        try:
            await mgr.pause_sandbox(sandbox_id)
        except Exception as e:
            raise SandboxOperationError(f"Failed to pause {sandbox_id}: {e}") from e

    async def resume_instance(self, sandbox_id: str) -> InstanceInfo:
        """Resume a paused sandbox and return updated info."""
        mgr = await self._get_manager()
        try:
            await mgr.resume_sandbox(sandbox_id)
        except Exception as e:
            raise SandboxOperationError(f"Failed to resume {sandbox_id}: {e}") from e
        return await self.get_instance(sandbox_id)

    async def kill_instance(self, sandbox_id: str) -> None:
        """Terminate a sandbox instance permanently."""
        mgr = await self._get_manager()
        try:
            await mgr.kill_sandbox(sandbox_id)
            mark_terminated(sandbox_id, db_path=self._config.database.path)
            db_user = find_user_by_sandbox(
                sandbox_id, db_path=self._config.database.path
            )
            if db_user:
                unlink_user_sandbox(db_user.id, db_path=self._config.database.path)
            self._sync_nginx()
        except Exception as e:
            raise SandboxOperationError(f"Failed to kill {sandbox_id}: {e}") from e

    async def renew_instance(self, sandbox_id: str, timeout_minutes: int = 60) -> None:
        """Extend a sandbox's TTL."""
        mgr = await self._get_manager()
        try:
            await mgr.renew_sandbox(sandbox_id, timedelta(minutes=timeout_minutes))
        except Exception as e:
            raise SandboxOperationError(f"Failed to renew {sandbox_id}: {e}") from e

    # ── Instance Creation ────────────────────────────────────────────

    async def create_instance(
        self,
        user: UserInfo,
        port: int = DEFAULT_PORT,
        secure: bool = False,
        workspace_dir: Optional[str] = None,
        workspace_volume: Optional[str] = None,
        timeout: Optional[timedelta] = None,
    ) -> InstanceInfo:
        """Create a new VS Code sandbox instance and start code-server.

        Enforces 1:1 user→instance: if the user already has a running
        instance, raises SandboxOperationError.

        Args:
            user: Group/username for this instance.
            port: Port for code-server inside the container.
            secure: Enable password authentication.
            workspace_dir: Host path for persistent bind mount.
            workspace_volume: Docker named volume (PVC claimName) for
                persistent workspace. Takes precedence over workspace_dir.
            timeout: Sandbox lifetime (None = indefinite).

        Returns:
            InstanceInfo with endpoint and state.
        """
        db_user = None
        groups = get_groups(db_path=self._config.database.path)
        for g in groups:
            if g.name == user.group:
                db_user = find_user_by_group_and_name(
                    group_id=g.id,
                    username=user.username,
                    db_path=self._config.database.path,
                )
                break
        if db_user and db_user.sandbox_id:
            rec = get_record(db_user.sandbox_id, db_path=self._config.database.path)
            if rec and rec.terminated_at is None:
                raise SandboxOperationError(
                    f"User {user.label} already has instance {db_user.sandbox_id}"
                )

        env = {"PYTHON_VERSION": "3.12"}
        volumes: list[Volume] | None = None

        if workspace_volume and workspace_volume.startswith("thon-"):
            safe_volume = workspace_volume.replace("/", "-")
            volumes = [
                Volume(
                    name="workspace",
                    pvc=PVC(claimName=safe_volume),
                    mountPath="/workspace",
                ),
            ]
            logger.info(
                "Mounting PVC volume %s -> /workspace for %s",
                workspace_volume,
                user.label,
            )
        elif workspace_dir:
            host_path = os.path.join(workspace_dir, user.workspace)
            os.makedirs(host_path, exist_ok=True)
            volumes = [
                Volume(
                    name=f"workspace-{user.group}-{user.username}".replace("/", "-"),
                    host=Host(path=host_path),
                    mount_path="/workspace",
                )
            ]

        metadata = {
            "group": user.group,
            "username": user.username,
            "port": str(port),
            "managed-by": "thon-client",
        }

        sandbox = await Sandbox.create(
            self._sandbox_cfg.image,
            connection_config=ConnectionConfig(
                domain=self._sandbox_cfg.domain,
                api_key=self._sandbox_cfg.api_key,
                request_timeout=timedelta(
                    seconds=self._sandbox_cfg.request_timeout_seconds
                ),
            ),
            env=env,
            timeout=timeout,
            volumes=volumes,
            metadata=metadata,
        )

        endpoint = await sandbox.get_endpoint(port)
        endpoint_str = endpoint.endpoint
        endpoint_port = self._parse_endpoint_port(endpoint_str)

        password = None
        if secure:
            password = secrets.token_urlsafe(24)

        if not volumes:
            await sandbox.commands.run("mkdir -p /workspace")
            await sandbox.commands.run("chown -R vscode:vscode /workspace")

        auth_flag = "--auth password" if secure else "--auth none"
        code_server_cmd = (
            f"code-server --bind-addr 0.0.0.0:{port} "
            f"{auth_flag} --disable-telemetry /workspace"
        )

        if secure and password:
            config_dir = "/home/vscode/.config/code-server"
            config_content = (
                f"bind-addr: 0.0.0.0:{port}\n"
                f"auth: password\n"
                f"password: {password}\n"
                f"cert: false\n"
            )
            await sandbox.commands.run(f"mkdir -p {config_dir}")
            write_cmd = (
                f"cat > {config_dir}/config.yaml << 'CONFIGEOF'\n"
                f"{config_content}CONFIGEOF"
            )
            await sandbox.commands.run(write_cmd)

        await sandbox.commands.run(
            code_server_cmd,
            opts=RunCommandOpts(background=True),
        )

        sandbox_id = sandbox.id if hasattr(sandbox, "id") else ""

        upsert_record(
            sandbox_id=sandbox_id,
            group_name=user.group,
            username=user.username,
            port=endpoint_port,
            endpoint=endpoint_str,
            image=self._sandbox_cfg.image,
            password=password,
            db_path=self._config.database.path,
        )

        if db_user:
            link_user_sandbox(
                db_user.id, sandbox_id, db_path=self._config.database.path
            )

        self._sync_nginx()

        return InstanceInfo(
            id=sandbox_id,
            user=user,
            state=InstanceState.RUNNING,
            port=endpoint_port,
            endpoint=endpoint_str,
            password=password,
            image=self._sandbox_cfg.image,
            metadata=metadata,
        )

    async def recreate_instance(self, sandbox_id: str) -> InstanceInfo:
        """Re-create a sandbox from its DB record, reusing the same workspace.

        Looks up the terminated/failed sandbox's group, username, and port
        from the database and creates a fresh instance.  If the DB user has
        a ``workspace_path`` (PVC volume), it is reattached so files persist.
        Otherwise, if ``workspace_dir`` is configured, a host bind mount is used.

        Returns:
            New InstanceInfo with updated endpoint.
        """
        rec = get_record(sandbox_id, db_path=self._config.database.path)
        if not rec:
            raise SandboxOperationError(f"No DB record for sandbox {sandbox_id}")
        user = UserInfo(group=rec.group_name, username=rec.username)
        workspace_volume = None
        workspace_dir = self._config.workspace_dir
        groups = get_groups(db_path=self._config.database.path)
        group_id = None
        for g in groups:
            if g.name == rec.group_name:
                group_id = g.id
                break
        if group_id:
            db_user = find_user_by_group_and_name(
                group_id, rec.username, db_path=self._config.database.path
            )
            if (
                db_user
                and db_user.workspace_path
                and db_user.workspace_path.startswith("thon-")
            ):
                workspace_volume = db_user.workspace_path
                workspace_dir = None
        return await self.create_instance(
            user=user,
            port=rec.port,
            secure=bool(rec.password),
            workspace_dir=workspace_dir,
            workspace_volume=workspace_volume,
        )

    async def create_instances_for_group(
        self,
        users: list[UserInfo],
        start_port: int = DEFAULT_PORT,
        secure: bool = False,
        workspace_dir: Optional[str] = None,
        user_volumes: Optional[dict[str, str]] = None,
        timeout: Optional[timedelta] = None,
    ) -> list[InstanceInfo]:
        """Create multiple instances concurrently for a list of users.

        Args:
            users: Users to create instances for.
            start_port: Starting port number (incremented per user).
            secure: Enable password authentication.
            workspace_dir: Host path for persistent bind mount.
            user_volumes: Mapping of ``user.label`` (``group/username``)
                to PVC claimName for persistent workspace volumes.
            timeout: Sandbox lifetime (None = indefinite).
        """
        tasks = []
        for i, user in enumerate(users):
            vol = (user_volumes or {}).get(user.label)
            tasks.append(
                self.create_instance(
                    user=user,
                    port=start_port + i,
                    secure=secure,
                    workspace_dir=workspace_dir if not vol else None,
                    workspace_volume=vol,
                    timeout=timeout,
                )
            )
        return list(await asyncio.gather(*tasks))

    # ── Bulk Operations ───────────────────────────────────────────────

    async def kill_all(self, metadata_filter: Optional[dict[str, str]] = None) -> int:
        """Kill all instances matching filter. Returns count killed."""
        instances, total = await self.list_instances(metadata_filter=metadata_filter)
        count = 0
        for inst in instances:
            if inst.state in (InstanceState.RUNNING, InstanceState.PAUSED):
                try:
                    await self.kill_instance(inst.id)
                    count += 1
                except SandboxOperationError as exc:
                    logger.warning("Failed to kill %s: %s", inst.id, exc)
        return count

    # ── Internal Helpers ─────────────────────────────────────────────

    async def _resolve_endpoints(
        self, sandbox_ports: list[tuple[str, int]]
    ) -> dict[str, str]:
        """Resolve endpoints for a list of (sandbox_id, port) pairs concurrently."""
        conn = ConnectionConfig(
            domain=self._sandbox_cfg.domain,
            api_key=self._sandbox_cfg.api_key,
            request_timeout=timedelta(
                seconds=self._sandbox_cfg.request_timeout_seconds
            ),
        )

        async def _get(sid: str, port: int) -> tuple[str, str]:
            try:
                sb = await Sandbox.connect(
                    sid, connection_config=conn, skip_health_check=True
                )
                ep = await sb.get_endpoint(port)
                return sid, ep.endpoint
            except Exception as exc:
                logger.warning(
                    "Failed to resolve endpoint for %s port %s: %s", sid, port, exc
                )
                return sid, ""

        results = await asyncio.gather(
            *[_get(sid, port) for sid, port in sandbox_ports]
        )
        return {sid: ep for sid, ep in results if ep}

    @staticmethod
    def _parse_endpoint_port(endpoint_str: str) -> int:
        host_port_part = endpoint_str.split("/", 1)[0]
        if ":" in host_port_part:
            return int(host_port_part.rsplit(":", 1)[1])
        return 80

    def _build_public_url(
        self, endpoint_str: str, fallback_ip: Optional[str] = None
    ) -> Optional[str]:
        """Build a public HTTPS URL from an internal endpoint string.

        Converts ``127.0.0.1:47887/proxy/8443`` → ``https://{external_ip}/47887/proxy/8443/``
        """
        ext_ip = (
            self._config.nginx.external_ip
            or fallback_ip
            or get_setting("external_ip", db_path=self._config.database.path)
        )
        if not ext_ip or not endpoint_str:
            return None
        endpoint_path = (
            endpoint_str.split(":", 1)[1] if ":" in endpoint_str else endpoint_str
        )
        return f"https://{ext_ip}/{endpoint_path}/"
