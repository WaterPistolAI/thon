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

"""REST API routes for groups and users management."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.db import GroupRecord, UserRecord
from app.services.groups_service import (
    DuplicateError,
    GroupNotFoundError,
    GroupsService,
    UserNotFoundError,
)

router = APIRouter(prefix="/api/groups", tags=["groups"])


class CreateGroupRequest(BaseModel):
    name: str


class UpdateGroupRequest(BaseModel):
    name: str


class CreateUserRequest(BaseModel):
    username: str


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    workspace_path: Optional[str] = None
    storage_path: Optional[str] = None


def _get_service() -> GroupsService:
    from app.main import get_groups_service

    return get_groups_service()


def _handle_error(e: Exception) -> HTTPException:
    if isinstance(e, (GroupNotFoundError, UserNotFoundError)):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, DuplicateError):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=list[GroupRecord])
async def list_groups() -> list[GroupRecord]:
    """List all groups with their users."""
    svc = _get_service()
    return svc.list_groups()


@router.post("", response_model=GroupRecord, status_code=201)
async def create_group(req: CreateGroupRequest) -> GroupRecord:
    """Create a new group."""
    svc = _get_service()
    try:
        return svc.create_group(req.name)
    except (DuplicateError, GroupNotFoundError) as e:
        raise _handle_error(e) from e


@router.get("/export")
async def export_groups() -> dict:
    """Export groups as a groups.yaml-compatible dict."""
    svc = _get_service()
    return svc.export_to_yaml()


@router.get("/{group_id}", response_model=GroupRecord)
async def get_group(group_id: str) -> GroupRecord:
    """Get a single group by UUID."""
    svc = _get_service()
    try:
        return svc.get_group(group_id)
    except GroupNotFoundError as e:
        raise _handle_error(e) from e


@router.put("/{group_id}", response_model=GroupRecord)
async def update_group(group_id: str, req: UpdateGroupRequest) -> GroupRecord:
    """Rename a group."""
    svc = _get_service()
    try:
        return svc.update_group(group_id, req.name)
    except (GroupNotFoundError, DuplicateError) as e:
        raise _handle_error(e) from e


@router.delete("/{group_id}")
async def delete_group(group_id: str) -> dict:
    """Delete a group and all its users."""
    svc = _get_service()
    try:
        svc.delete_group(group_id)
        return {"status": "deleted", "id": group_id}
    except GroupNotFoundError as e:
        raise _handle_error(e) from e


# ── Users within a group ─────────────────────────────────────────────


@router.post("/{group_id}/users", response_model=UserRecord, status_code=201)
async def create_user(group_id: str, req: CreateUserRequest) -> UserRecord:
    """Add a user to a group."""
    svc = _get_service()
    try:
        return svc.create_user(group_id, req.username)
    except (GroupNotFoundError, DuplicateError) as e:
        raise _handle_error(e) from e


@router.put("/{group_id}/users/{user_id}", response_model=UserRecord)
async def update_user(group_id: str, user_id: str, req: UpdateUserRequest) -> UserRecord:
    """Update a user's fields."""
    svc = _get_service()
    try:
        return svc.update_user(user_id, req.username)
    except (UserNotFoundError, DuplicateError) as e:
        raise _handle_error(e) from e


@router.delete("/{group_id}/users/{user_id}")
async def delete_user(group_id: str, user_id: str) -> dict:
    """Delete a user from a group."""
    svc = _get_service()
    try:
        svc.delete_user(user_id)
        return {"status": "deleted", "id": user_id}
    except UserNotFoundError as e:
        raise _handle_error(e) from e
