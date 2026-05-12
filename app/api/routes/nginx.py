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

"""REST API routes for nginx reverse proxy management."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.models import NginxStatus
from app.services.sandbox_service import SandboxService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/nginx", tags=["nginx"])

SITES_AVAILABLE = Path("/etc/nginx/sites-available")
SSL_DIR = Path("/etc/nginx/ssl")
CONFIG_NAME = "sandbox-thon"


def _get_service() -> SandboxService:
    from app.main import get_sandbox_service

    return get_sandbox_service()


def _get_nginx_status(svc: SandboxService) -> NginxStatus:
    ng = svc.nginx
    if ng is None:
        return NginxStatus(available=False)

    external_ip = svc._config.nginx.external_ip or ""
    ssl_configured = False
    try:
        ng._find_cert_pair()
        ssl_configured = True
    except FileNotFoundError:
        pass

    config_path = SITES_AVAILABLE / CONFIG_NAME
    ports: list[int] = []
    if config_path.exists():
        try:
            content = config_path.read_text()
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("location /") and stripped.endswith("/ {"):
                    port_str = stripped.split("/")[1].rstrip("/")
                    try:
                        ports.append(int(port_str))
                    except ValueError:
                        pass
        except PermissionError:
            pass

    return NginxStatus(
        available=True,
        external_ip=external_ip,
        ssl_configured=ssl_configured,
        ports=sorted(ports),
        config_path=str(config_path) if config_path.exists() else "",
    )


@router.get("/status", response_model=NginxStatus)
async def get_nginx_status() -> NginxStatus:
    """Get current nginx reverse proxy status."""
    svc = _get_service()
    return _get_nginx_status(svc)


@router.post("/refresh")
async def refresh_nginx_config() -> dict:
    """Regenerate nginx config from all active instance endpoints."""
    svc = _get_service()
    ng = svc.nginx
    if ng is None:
        raise HTTPException(
            status_code=400,
            detail="Nginx not available — set EXTERNAL_IP to enable nginx proxy",
        )
    ports = svc.sync_nginx()
    return {"status": "refreshed", "ports": ports}


@router.post("/cleanup")
async def cleanup_nginx_config() -> dict:
    """Remove all THON nginx sandbox configs and reload."""
    svc = _get_service()
    ng = svc.nginx
    if ng is None:
        raise HTTPException(
            status_code=400,
            detail="Nginx not available — set EXTERNAL_IP to enable nginx proxy",
        )
    ng.cleanup_all()
    return {"status": "cleaned_up"}
