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

"""REST API routes for user management with instance association."""

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import (
    UserRecord,
    create_user,
    delete_user,
    find_user_by_group_and_name,
    find_user_by_sandbox,
    get_groups,
    get_user,
    get_users,
    update_user,
)
from app.exceptions import SandboxOperationError
from app.models import UserInfo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserRequest(BaseModel):
    username: str
    group_id: str
    email: Optional[str] = None


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    group_id: str
    username: str
    email: Optional[str] = None
    sandbox_id: Optional[str] = None
    instance_state: Optional[str] = None
    workspace_path: Optional[str] = None


class UsersListResponse(BaseModel):
    users: list[UserResponse]
    total: int


def _user_to_response(
    user: UserRecord, instance_state: Optional[str] = None
) -> UserResponse:
    return UserResponse(
        id=user.id,
        group_id=user.group_id,
        username=user.username,
        email=user.email,
        sandbox_id=user.sandbox_id,
        instance_state=instance_state,
        workspace_path=user.workspace,
    )


def _get_db_path() -> str:
    from app.main import get_app_config

    return get_app_config().database.path


def _get_app_config():
    from app.main import get_app_config

    return get_app_config()


def _get_sandbox_service():
    from app.main import get_sandbox_service

    return get_sandbox_service()


@router.get("", response_model=UsersListResponse)
async def list_users(
    group_id: Optional[str] = None,
) -> UsersListResponse:
    """List all users, optionally filtered by group."""
    db_path = _get_db_path()
    if group_id:
        users = get_users(group_id, db_path=db_path)
    else:
        groups = get_groups(db_path=db_path)
        users = []
        for g in groups:
            users.extend(get_users(g.id, db_path=db_path))

    svc = _get_sandbox_service()
    instance_states: dict[str, str] = {}
    try:
        instances, _ = await svc.list_instances()
        for inst in instances:
            if inst.id:
                instance_states[inst.id] = inst.state.value
    except Exception:
        pass

    responses = [
        _user_to_response(
            u, instance_states.get(u.sandbox_id) if u.sandbox_id else None
        )
        for u in users
    ]
    return UsersListResponse(users=responses, total=len(responses))


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_endpoint(user_id: str) -> UserResponse:
    """Get a single user by ID."""
    db_path = _get_db_path()
    user = get_user(user_id, db_path=db_path)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    instance_state = None
    if user.sandbox_id:
        svc = _get_sandbox_service()
        try:
            inst = await svc.get_instance(user.sandbox_id)
            instance_state = inst.state.value
        except Exception:
            instance_state = "Unknown"

    return _user_to_response(user, instance_state)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user_endpoint(req: CreateUserRequest) -> UserResponse:
    """Create a new user in a group."""
    db_path = _get_db_path()
    existing = find_user_by_group_and_name(req.group_id, req.username, db_path=db_path)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"User {req.username} already exists in this group",
        )
    user = create_user(
        group_id=req.group_id,
        username=req.username,
        email=req.email,
        db_path=db_path,
    )
    return _user_to_response(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user_endpoint(user_id: str, req: UpdateUserRequest) -> UserResponse:
    """Update a user's username or email."""
    db_path = _get_db_path()
    user = get_user(user_id, db_path=db_path)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    updated = update_user(
        user_id,
        username=req.username,
        email=req.email,
        db_path=db_path,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return _user_to_response(updated)


@router.delete("/{user_id}")
async def delete_user_endpoint(user_id: str) -> dict:
    """Delete a user. If they have a running instance, kill it first."""
    db_path = _get_db_path()
    user = get_user(user_id, db_path=db_path)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if user.sandbox_id:
        svc = _get_sandbox_service()
        try:
            await svc.kill_instance(user.sandbox_id)
        except Exception as e:
            logger.warning("Failed to kill instance for user %s: %s", user_id, e)

    success = delete_user(user_id, db_path=db_path)
    if not success:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return {"status": "deleted", "user_id": user_id}


@router.post("/{user_id}/launch", response_model=UserResponse)
async def launch_user_instance(user_id: str) -> UserResponse:
    """Launch a VS Code instance for a user (1:1)."""
    db_path = _get_db_path()
    user = get_user(user_id, db_path=db_path)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if user.sandbox_id:
        rec = find_user_by_sandbox(user.sandbox_id, db_path=db_path)
        if rec:
            raise HTTPException(
                status_code=409,
                detail=f"User already has instance {user.sandbox_id}",
            )

    groups = get_groups(db_path=db_path)
    group_name = "default"
    for g in groups:
        if g.id == user.group_id:
            group_name = g.name
            break

    svc = _get_sandbox_service()
    cfg = _get_app_config()
    secure = os.getenv("THON_SECURE", "false").lower() in ("true", "1", "yes")
    workspace_volume = user.workspace_path if user.workspace_path else None
    try:
        await svc.create_instance(
            user=UserInfo(group=group_name, username=user.username),
            secure=secure,
            workspace_dir=cfg.workspace_dir or None,
            workspace_volume=workspace_volume,
        )
    except SandboxOperationError as e:
        raise HTTPException(status_code=409, detail=str(e))

    user = get_user(user_id, db_path=db_path)
    return _user_to_response(user, "Running")


@router.post("/{user_id}/stop")
async def stop_user_instance(user_id: str) -> dict:
    """Kill the VS Code instance for a user."""
    db_path = _get_db_path()
    user = get_user(user_id, db_path=db_path)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    if not user.sandbox_id:
        raise HTTPException(status_code=404, detail="User has no running instance")

    svc = _get_sandbox_service()
    try:
        await svc.kill_instance(user.sandbox_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop instance: {e}")

    return {"status": "stopped", "user_id": user_id}
