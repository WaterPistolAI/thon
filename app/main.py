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

"""FastAPI REST API entry point for THON — dashboard served via Streamlit."""

import logging
import subprocess
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.config import AppConfig
from app.services.apisix_service import ApisixService
from app.services.groups_service import GroupsService
from app.services.lemonade_service import LemonadeService
from app.services.sandbox_service import SandboxService

logger = logging.getLogger(__name__)

_app_config: AppConfig | None = None
_sandbox_service: SandboxService | None = None
_lemonade_service: LemonadeService | None = None
_apisix_service: ApisixService | None = None
_groups_service: GroupsService | None = None


def configure_logging(cfg: AppConfig) -> None:
    """Configure root and service-level logging from AppConfig."""
    level_name = cfg.log.level.upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = cfg.log.format

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(fmt))
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setLevel(level)
            handler.setFormatter(logging.Formatter(fmt))

    for name in (
        "opensandbox.adapters.sandboxes_adapter",
        "opensandbox.sandbox",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def get_app_config() -> AppConfig:
    global _app_config
    if _app_config is None:
        _app_config = AppConfig.from_env()
    return _app_config


def get_sandbox_service() -> SandboxService:
    global _sandbox_service
    if _sandbox_service is None:
        cfg = get_app_config()
        _sandbox_service = SandboxService(cfg)
    return _sandbox_service


def get_lemonade_service() -> LemonadeService:
    global _lemonade_service
    if _lemonade_service is None:
        cfg = get_app_config()
        _lemonade_service = LemonadeService(cfg.lemonade)
    return _lemonade_service


def get_apisix_service() -> ApisixService:
    global _apisix_service
    if _apisix_service is None:
        cfg = get_app_config()
        _apisix_service = ApisixService(cfg.gateway)
    return _apisix_service


def get_groups_service() -> GroupsService:
    global _groups_service
    if _groups_service is None:
        cfg = get_app_config()
        _groups_service = GroupsService(
            db_path=cfg.database.path,
            workspace_dir=cfg.workspace_dir,
        )
    return _groups_service


def _log_startup_diagnostics(cfg: AppConfig) -> None:
    """Log status of all services at startup."""
    logger.info("THON server starting")
    logger.info("  Database: %s", cfg.database.path)
    logger.info("  Dashboard: %s:%s", cfg.dashboard.host, cfg.dashboard.port)
    logger.info("  Sandbox domain: %s", cfg.sandbox.domain)
    logger.info("  Sandbox image: %s", cfg.sandbox.image)
    logger.info("  Log level: %s", cfg.log.level.upper())

    gs = get_groups_service()
    backfilled = gs.backfill_storage_paths()
    if backfilled:
        logger.info("Backfilled storage paths for %d user(s)", backfilled)

    groups = gs.list_groups()
    total_users = sum(len(g.users) for g in groups)
    logger.info("  Groups: %d, Users: %d", len(groups), total_users)

    ls = get_lemonade_service()
    lemonade_status = ls.get_status()
    logger.info(
        "  Lemonade: %s (endpoint=%s, model=%s)",
        "running" if lemonade_status.running else "offline",
        lemonade_status.endpoint,
        lemonade_status.model or "N/A",
    )

    try:
        aps = get_apisix_service()
        gateway_status = aps.get_status()
        logger.info(
            "  Gateway: %s (installed=%s, consumers=%d, route=%s)",
            "running" if gateway_status.running else "offline",
            gateway_status.installed,
            gateway_status.consumers_count,
            "configured" if gateway_status.route_configured else "not configured",
        )
        if gateway_status.redis_connected:
            logger.info("  Gateway Redis: connected")
    except Exception as exc:
        logger.debug("Gateway diagnostics failed: %s", exc)
        logger.info("  Gateway: not configured")

    if cfg.nginx.external_ip:
        logger.info("  External IP: %s", cfg.nginx.external_ip)
        try:
            from app.api.routes.nginx import _get_nginx_status

            ns = _get_nginx_status(get_sandbox_service())
            logger.info(
                "  Nginx: available=%s ssl=%s ports=%s",
                ns.available,
                ns.ssl_configured,
                ns.ports or "none",
            )
        except Exception as exc:
            logger.debug("Nginx diagnostics failed: %s", exc)
    if cfg.auth.enabled:
        logger.info("  Auth: enabled")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_app_config()
    configure_logging(cfg)
    _log_startup_diagnostics(cfg)
    yield
    svc = get_sandbox_service()
    await svc.close()
    logger.info("THON server stopped")


def _get_git_version() -> str:
    try:
        describe = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            check=False,
        )
        rev = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        dirty = subprocess.run(
            ["git", "diff", "--quiet"],
            capture_output=True,
            text=True,
            check=False,
        )
        tag = describe.stdout.strip() if describe.returncode == 0 else None
        sha = rev.stdout.strip() if rev.returncode == 0 else None
        if not tag and not sha:
            return "0.1.0"
        parts: list[str] = [tag or sha or "0.1.0"]
        if sha and tag and not tag.startswith(sha):
            parts.append(sha)
        if dirty.returncode != 0:
            parts.append("dirty")
        return "-".join(parts)
    except FileNotFoundError:
        return "0.1.0"


def create_app(config: AppConfig | None = None) -> FastAPI:
    global _app_config
    if config:
        _app_config = config

    app = FastAPI(
        title="THON",
        description="Dashboard for managing THON VS Code instances and Lemonade inference",
        version=_get_git_version(),
        lifespan=lifespan,
    )

    from app.api.routes.auth import router as auth_router
    from app.api.routes.config_files import router as config_files_router
    from app.api.routes.gateway import router as gateway_router
    from app.api.routes.groups import router as groups_router
    from app.api.routes.instances import router as instances_router
    from app.api.routes.lemonade import router as lemonade_router
    from app.api.routes.nginx import router as nginx_router

    app.include_router(auth_router)
    app.include_router(config_files_router)
    app.include_router(gateway_router)
    app.include_router(groups_router)
    app.include_router(instances_router)
    app.include_router(lemonade_router)
    app.include_router(nginx_router)

    @app.get("/")
    async def index():
        return RedirectResponse(url="/docs")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = get_app_config()
    uvicorn.run(
        "app.main:app",
        host=cfg.dashboard.host,
        port=cfg.dashboard.port,
        reload=cfg.dashboard.debug,
    )
