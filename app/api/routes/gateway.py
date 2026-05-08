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

"""REST API routes for APISIX AI Gateway management."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.exceptions import GatewayConnectionError, GatewayNotEnabledError
from app.models import (
    ConsumerCreateRequest,
    ConsumerInfo,
    GatewaySetupRequest,
    GatewayStatus,
)
from app.services.apisix_service import ApisixService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gateway", tags=["gateway"])


class RouteCreateRequest(BaseModel):
    lemonade_url: str
    lemonade_api_key: str | None = None
    lemonade_model: str = "user.gemma-4-31b-it"


def _get_service() -> ApisixService:
    from app.main import get_apisix_service

    return get_apisix_service()


@router.get("/status", response_model=GatewayStatus)
async def gateway_status() -> GatewayStatus:
    """Get current AI Gateway status."""
    svc = _get_service()
    try:
        return svc.get_status()
    except GatewayConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/consumers", response_model=list[ConsumerInfo])
async def list_consumers() -> list[ConsumerInfo]:
    """List all gateway consumers with their API keys and rate limits."""
    svc = _get_service()
    try:
        return svc.list_consumers()
    except GatewayNotEnabledError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GatewayConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/consumers", response_model=ConsumerInfo, status_code=201)
async def create_consumer(req: ConsumerCreateRequest) -> ConsumerInfo:
    """Create a new gateway consumer with API key and rate limit."""
    svc = _get_service()
    try:
        return svc.create_consumer(
            username=req.username,
            api_key=req.api_key,
            rate_limit=req.rate_limit,
            time_window=req.time_window,
        )
    except GatewayNotEnabledError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GatewayConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/consumers/{username}")
async def delete_consumer(username: str) -> dict:
    """Delete a gateway consumer."""
    svc = _get_service()
    try:
        svc.delete_consumer(username)
        return {"status": "deleted", "username": username}
    except GatewayNotEnabledError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GatewayConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/setup", response_model=list[ConsumerInfo])
async def setup_gateway(req: GatewaySetupRequest) -> list[ConsumerInfo]:
    """Full gateway setup: create AI route and consumers from DB groups/users."""
    svc = _get_service()
    try:
        from app.db import get_groups, get_users
        from app.main import get_app_config

        cfg = get_app_config()

        usernames: list[str] | None = None
        db_groups = get_groups(db_path=cfg.database.path)
        if db_groups:
            usernames = []
            for group in db_groups:
                group_users = get_users(group.id, db_path=cfg.database.path)
                for user in group_users:
                    usernames.append(f"{group.name}-{user.username}")

        return svc.setup_gateway(
            lemonade_url=req.lemonade_url,
            lemonade_api_key=req.lemonade_api_key,
            lemonade_model=req.lemonade_model,
            usernames=usernames,
            rate_limit=req.rate_limit,
            time_window=req.time_window,
        )
    except GatewayNotEnabledError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GatewayConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/cleanup")
async def cleanup_gateway() -> dict:
    """Remove all gateway consumers and routes."""
    svc = _get_service()
    try:
        svc.cleanup()
        return {"status": "cleaned"}
    except GatewayNotEnabledError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GatewayConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/route")
async def create_ai_route(req: RouteCreateRequest) -> dict:
    """Create or update the AI proxy route."""
    svc = _get_service()
    try:
        result = svc.create_ai_route(
            lemonade_url=req.lemonade_url,
            lemonade_api_key=req.lemonade_api_key,
            lemonade_model=req.lemonade_model,
        )
        return {"status": "created", "route": result}
    except GatewayNotEnabledError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GatewayConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete("/route")
async def delete_ai_route() -> dict:
    """Delete the AI proxy route."""
    svc = _get_service()
    try:
        svc.delete_ai_route()
        return {"status": "deleted"}
    except GatewayNotEnabledError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GatewayConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))
