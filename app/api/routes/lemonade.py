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

"""REST API routes for Lemonade server monitoring and management."""

from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query

from app.exceptions import LemonadeConnectionError
from app.models import (
    LemonadeBackendRequest,
    LemonadeDeleteRequest,
    LemonadeLoadRequest,
    LemonadePullRequest,
    LemonadeSlotActionRequest,
    LemonadeStatus,
    LemonadeUnloadRequest,
)
from app.services.lemonade_service import LemonadeService

router = APIRouter(prefix="/api/lemonade", tags=["lemonade"])


def _get_service() -> LemonadeService:
    from app.main import get_lemonade_service

    return get_lemonade_service()


def _handle_connection_error(exc: LemonadeConnectionError) -> NoReturn:
    raise HTTPException(status_code=502, detail=str(exc))


# ── Status & Info ──────────────────────────────────────────────────


@router.get("/status", response_model=LemonadeStatus)
async def lemonade_status() -> LemonadeStatus:
    """Get current Lemonade server status snapshot."""
    svc = _get_service()
    return svc.get_status()


@router.get("/models")
async def lemonade_models() -> dict:
    """List available Lemonade models."""
    svc = _get_service()
    return {"models": svc.list_models()}


@router.get("/api-info")
async def lemonade_api_info() -> dict:
    """Get Lemonade API endpoint information."""
    svc = _get_service()
    return svc.get_api_info()


# ── Server Information (Lemonade API proxies) ─────────────────────


@router.get("/health")
async def lemonade_health() -> dict:
    """Proxy: GET /v1/health — server health, loaded models, max_models."""
    svc = _get_service()
    try:
        return svc.health()
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.get("/stats")
async def lemonade_stats() -> dict:
    """Proxy: GET /v1/stats — performance statistics from the last request."""
    svc = _get_service()
    try:
        return svc.stats()
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.get("/system-info")
async def lemonade_system_info() -> dict:
    """Proxy: GET /v1/system-info — hardware details and device enumeration."""
    svc = _get_service()
    try:
        return svc.system_info()
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.get("/live")
async def lemonade_liveness() -> dict:
    """Proxy: GET /live — lightweight liveness probe."""
    svc = _get_service()
    try:
        return svc.liveness()
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


# ── Model Management (Lemonade API proxies) ───────────────────────


@router.post("/pull")
async def lemonade_pull(body: LemonadePullRequest) -> dict:
    """Proxy: POST /v1/pull — install or register-and-install a model."""
    svc = _get_service()
    try:
        return svc.pull(body.model_dump(exclude_none=True))
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.get("/pull/variants")
async def lemonade_pull_variants(
    checkpoint: str = Query(
        ..., description="HuggingFace repo id, e.g. unsloth/Qwen3-8B-GGUF"
    ),
) -> dict:
    """Proxy: GET /v1/pull/variants — enumerate GGUF variants for a checkpoint."""
    svc = _get_service()
    try:
        return svc.pull_variants(checkpoint)
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.post("/delete")
async def lemonade_delete(body: LemonadeDeleteRequest) -> dict:
    """Proxy: POST /v1/delete — delete a model from local storage."""
    svc = _get_service()
    try:
        return svc.delete(body.model_dump(exclude_none=True))
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.post("/load")
async def lemonade_load(body: LemonadeLoadRequest) -> dict:
    """Proxy: POST /v1/load — load a model into memory."""
    svc = _get_service()
    try:
        return svc.load(body.model_dump(exclude_none=True))
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.post("/unload")
async def lemonade_unload(
    body: LemonadeUnloadRequest = LemonadeUnloadRequest(),
) -> dict:
    """Proxy: POST /v1/unload — unload a model from memory."""
    svc = _get_service()
    try:
        payload = body.model_dump(exclude_none=True)
        return svc.unload(payload or None)
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


# ── Backend Management (Lemonade API proxies) ─────────────────────


@router.post("/install")
async def lemonade_install_backend(body: LemonadeBackendRequest) -> dict:
    """Proxy: POST /v1/install — install or update a backend."""
    svc = _get_service()
    try:
        return svc.install_backend(body.model_dump(exclude_none=True))
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.post("/uninstall")
async def lemonade_uninstall_backend(body: LemonadeBackendRequest) -> dict:
    """Proxy: POST /v1/uninstall — remove a backend."""
    svc = _get_service()
    try:
        payload = {"recipe": body.recipe, "backend": body.backend}
        return svc.uninstall_backend(payload)
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


# ── llama.cpp-specific (Lemonade API proxies) ─────────────────────


@router.get("/slots")
async def lemonade_slots() -> list[dict]:
    """Proxy: GET /v1/slots — current slots processing state."""
    svc = _get_service()
    try:
        return svc.slots()
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.post("/slots/{slot_id}/save")
async def lemonade_slot_save(slot_id: int, body: LemonadeSlotActionRequest) -> dict:
    """Proxy: POST /v1/slots/{id}?action=save — save prompt cache."""
    svc = _get_service()
    try:
        return svc.slot_action(slot_id, "save", body.model_dump(exclude_none=True))
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.post("/slots/{slot_id}/restore")
async def lemonade_slot_restore(slot_id: int, body: LemonadeSlotActionRequest) -> dict:
    """Proxy: POST /v1/slots/{id}?action=restore — restore prompt cache."""
    svc = _get_service()
    try:
        return svc.slot_action(slot_id, "restore", body.model_dump(exclude_none=True))
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.post("/slots/{slot_id}/erase")
async def lemonade_slot_erase(slot_id: int) -> dict:
    """Proxy: POST /v1/slots/{id}?action=erase — erase prompt cache."""
    svc = _get_service()
    try:
        return svc.slot_action(slot_id, "erase")
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)


@router.post("/rescale")
async def lemonade_rescale(
    num_users: int = Query(..., description="Number of parallel users"),
) -> dict:
    """Rescale the Lemonade server for a different number of parallel users.

    Updates recipe_options.json (ctx_size, -np), restarts the service,
    and reloads models so new settings take effect immediately.
    """
    svc = _get_service()
    try:
        from pathlib import Path

        from thon.config import ThonConfig

        thon_yaml = Path.home() / ".thon" / "thon.yaml"
        chat_args = None
        emb_args = None
        if thon_yaml.is_file():
            try:
                tc = ThonConfig.from_yaml(thon_yaml)
                chat_args = tc.lemonade.llamacpp.to_args(num_users)
                emb_args = tc.lemonade.llamacpp.to_embedding_args(num_users)
            except Exception:
                pass
        return svc.rescale(
            num_users=num_users,
            llamacpp_args=chat_args,
            embedding_llamacpp_args=emb_args,
        )
    except LemonadeConnectionError as exc:
        _handle_connection_error(exc)
