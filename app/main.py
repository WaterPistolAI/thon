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

"""FastAPI application entry point for THON dashboard."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import AppConfig
from app.services.lemonade_service import LemonadeService
from app.services.sandbox_service import SandboxService

logger = logging.getLogger(__name__)

_app_config: AppConfig | None = None
_sandbox_service: SandboxService | None = None
_lemonade_service: LemonadeService | None = None


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    svc = get_sandbox_service()
    logger.info("THON dashboard starting")
    yield
    await svc.close()
    logger.info("THON dashboard stopped")


def create_app(config: AppConfig | None = None) -> FastAPI:
    global _app_config
    if config:
        _app_config = config

    app = FastAPI(
        title="THON",
        description="Dashboard for managing THON VS Code instances and Lemonade inference",
        version="0.1.0",
        lifespan=lifespan,
    )

    from app.api.routes.auth import router as auth_router
    from app.api.routes.instances import router as instances_router
    from app.api.routes.lemonade import router as lemonade_router

    app.include_router(auth_router)
    app.include_router(instances_router)
    app.include_router(lemonade_router)

    dashboard_dir = Path(__file__).parent.parent / "dashboard"
    static_dir = dashboard_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def index():
        index_path = dashboard_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"message": "THON API", "docs": "/docs"}

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
