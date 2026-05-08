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

"""REST API routes for group and user management."""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import (
    create_group,
    create_user,
    delete_group,
    delete_user,
    get_group,
    get_groups,
    get_user,
    get_users,
    rename_group,
    update_user,
)

router = APIRouter(prefix="/api/groups", tags=["groups"])


def _db_path() -> str:
    from app.main import get_app_config
    return get_app_config().database.path


# ── Pydantic schemas ────────────────────────────────────────────────


class GroupOut(BaseModel):
    id: str
    name: str
    user_count: int


class GroupDetailOut(BaseModel):
    id: str
    name: str
    users: list["UserOut"]


class UserOut(BaseModel):
    id: str
    group_id: str
    username: str
    workspace_path: Optional[str] = None
    storage_path: Optional[str] = None


class CreateGroupRequest(BaseModel):
    name: str


class RenameGroupRequest(BaseModel):
    name: str


class CreateUserRequest(BaseModel):
    username: str
    workspace_path: Optional[str] = None
    storage_path: Optional[str] = None


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    workspace_path: Optional[str] = None
    storage_path: Optional[str] = None


# ── Group endpoints ─────────────────────────────────────────────────


@router.get("", response_model=list[GroupDetailOut])
async def list_groups():
    """List all groups with their users."""
    groups = get_groups(db_path=_db_path())
    result = []
    for g in groups:
        result.append(_group_detail(g.id))
    return [r for r in result if r]


@router.post("", response_model=GroupDetailOut, status_code=201)
async def create_group_endpoint(req: CreateGroupRequest):
    """Create a new group."""
    try:
        group = create_group(req.name, db_path=_db_path())
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _group_detail(group.id)


@router.get("/{group_id}", response_model=GroupDetailOut)
async def get_group_endpoint(group_id: str):
    """Get a group with its users."""
    detail = _group_detail(group_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Group not found")
    return detail


@router.put("/{group_id}", response_model=GroupDetailOut)
async def rename_group_endpoint(group_id: str, req: RenameGroupRequest):
    """Rename a group."""
    group = rename_group(group_id, req.name, db_path=_db_path())
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return _group_detail(group.id)


@router.delete("/{group_id}")
async def delete_group_endpoint(group_id: str):
    """Delete a group and all its users."""
    if not delete_group(group_id, db_path=_db_path()):
        raise HTTPException(status_code=404, detail="Group not found")
    return {"status": "deleted", "id": group_id}


# ── User endpoints ──────────────────────────────────────────────────


@router.post("/{group_id}/users", response_model=UserOut, status_code=201)
async def add_user(group_id: str, req: CreateUserRequest):
    """Add a user to a group."""
    group = get_group(group_id, db_path=_db_path())
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    user = create_user(
        group_id,
        req.username,
        workspace_path=req.workspace_path,
        storage_path=req.storage_path,
        db_path=_db_path(),
    )
    return _user_out(user)


@router.put("/{group_id}/users/{user_id}", response_model=UserOut)
async def update_user_endpoint(group_id: str, user_id: str, req: UpdateUserRequest):
    """Update a user's fields."""
    user = update_user(
        user_id,
        username=req.username,
        workspace_path=req.workspace_path,
        storage_path=req.storage_path,
        db_path=_db_path(),
    )
    if not user or user.group_id != group_id:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_out(user)


@router.delete("/{group_id}/users/{user_id}")
async def delete_user_endpoint(group_id: str, user_id: str):
    """Remove a user from a group."""
    user = get_user(user_id, db_path=_db_path())
    if not user or user.group_id != group_id:
        raise HTTPException(status_code=404, detail="User not found")
    delete_user(user_id, db_path=_db_path())
    return {"status": "deleted", "id": user_id}


# ── Helpers ─────────────────────────────────────────────────────────


def _group_detail(group_id: str) -> Optional[GroupDetailOut]:
    group = get_group(group_id, db_path=_db_path())
    if not group:
        return None
    users = get_users(group_id, db_path=_db_path())
    return GroupDetailOut(
        id=group.id,
        name=group.name,
        users=[_user_out(u) for u in users],
    )


def _user_out(user) -> UserOut:
    return UserOut(
        id=user.id,
        group_id=user.group_id,
        username=user.username,
        workspace_path=user.workspace_path,
        storage_path=user.storage_path,
    )
