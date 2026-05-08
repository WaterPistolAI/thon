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

"""Groups service for CRUD operations on groups and users stored in SQLite."""

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import select

from app.db import (
    GroupRecord,
    UserRecord,
    create_group as db_create_group,
    create_user as db_create_user,
    delete_group as db_delete_group,
    delete_user as db_delete_user,
    get_group as db_get_group,
    get_groups as db_get_groups,
    get_session,
    get_users as db_get_users,
    rename_group as db_rename_group,
    update_user as db_update_user,
)
from app.exceptions import GroupsLoadError

logger = logging.getLogger(__name__)


class GroupNotFoundError(GroupsLoadError):
    """Raised when a requested group does not exist."""


class UserNotFoundError(GroupsLoadError):
    """Raised when a requested user does not exist."""


class DuplicateError(GroupsLoadError):
    """Raised when a unique constraint would be violated."""


class GroupsService:
    """Manages groups and users in the SQLite database.

    Wraps the CRUD functions in ``app.db`` with workspace/storage path
    derivation, backfill support, and typed exception handling.
    """

    def __init__(self, db_path: Optional[str] = None, workspace_dir: Optional[str] = None) -> None:
        self._db_path = db_path
        self._workspace_dir = workspace_dir

    # ── Groups ────────────────────────────────────────────────────────

    def list_groups(self) -> list[GroupRecord]:
        """Return all groups with their users populated."""
        groups = db_get_groups(db_path=self._db_path)
        for group in groups:
            group.users = db_get_users(group.id, db_path=self._db_path)
        return groups

    def get_group(self, group_id: str) -> GroupRecord:
        """Fetch a single group by UUID."""
        group = db_get_group(group_id, db_path=self._db_path)
        if group is None:
            raise GroupNotFoundError(f"Group {group_id} not found")
        group.users = db_get_users(group_id, db_path=self._db_path)
        return group

    def create_group(self, name: str) -> GroupRecord:
        """Create a new group with an auto-generated UUID."""
        try:
            group = db_create_group(name, db_path=self._db_path)
        except ValueError as e:
            raise DuplicateError(str(e)) from e
        group.users = []
        logger.info("Created group '%s' (id=%s)", name, group.id)
        return group

    def update_group(self, group_id: str, name: str) -> GroupRecord:
        """Rename an existing group."""
        group = db_rename_group(group_id, name, db_path=self._db_path)
        if group is None:
            raise GroupNotFoundError(f"Group {group_id} not found")
        group.users = db_get_users(group_id, db_path=self._db_path)
        return group

    def delete_group(self, group_id: str) -> None:
        """Delete a group and all its users (cascade)."""
        if not db_delete_group(group_id, db_path=self._db_path):
            raise GroupNotFoundError(f"Group {group_id} not found")
        logger.info("Deleted group %s", group_id)

    # ── Users ─────────────────────────────────────────────────────────

    def create_user(
        self,
        group_id: str,
        username: str,
        workspace_dir: Optional[str] = None,
    ) -> UserRecord:
        """Add a user to a group with an auto-generated UUID.

        Derives ``workspace_path`` and ``storage_path``:
          - workspace_path: ``{ws_dir}/{group_name}/{username}``
          - storage_path:   ``{ws_dir}/.storage/{user_uuid}``
        """
        ws_dir = workspace_dir or self._workspace_dir
        group = db_get_group(group_id, db_path=self._db_path)
        if group is None:
            raise GroupNotFoundError(f"Group {group_id} not found")

        workspace_path: Optional[str] = None
        storage_path: Optional[str] = None
        user_id = str(uuid.uuid4())
        if ws_dir:
            workspace_path = f"{ws_dir}/{group.name}/{username}"
            storage_path = f"{ws_dir}/.storage/{user_id}"

        user = db_create_user(
            group_id=group_id,
            username=username,
            workspace_path=workspace_path,
            storage_path=storage_path,
            db_path=self._db_path,
        )
        logger.info("Created user '%s/%s' (id=%s)", group.name, username, user.id)
        return user

    def update_user(self, user_id: str, username: str) -> UserRecord:
        """Rename a user."""
        user = db_update_user(user_id, username=username, db_path=self._db_path)
        if user is None:
            raise UserNotFoundError(f"User {user_id} not found")
        return user

    def delete_user(self, user_id: str) -> None:
        """Delete a user."""
        if not db_delete_user(user_id, db_path=self._db_path):
            raise UserNotFoundError(f"User {user_id} not found")
        logger.info("Deleted user %s", user_id)

    # ── Storage path backfill ─────────────────────────────────────────

    def backfill_storage_paths(self) -> int:
        """Populate workspace_path and storage_path for users missing them.

        Uses ``self._workspace_dir`` to derive paths. Returns count updated.
        """
        if not self._workspace_dir:
            return 0
        updated = 0
        with get_session(self._db_path) as session:
            users = session.exec(
                select(UserRecord).where(UserRecord.workspace_path == None)  # noqa: E711
            ).all()
            for user in users:
                group = session.exec(
                    select(GroupRecord).where(GroupRecord.id == user.group_id)
                ).first()
                group_name = group.name if group else "default"
                user.workspace_path = f"{self._workspace_dir}/{group_name}/{user.username}"
                user.storage_path = f"{self._workspace_dir}/.storage/{user.id}"
                user.updated_at = datetime.utcnow()
                session.add(user)
                updated += 1
            if updated:
                session.commit()
        if updated:
            logger.info("Backfilled storage paths for %d user(s)", updated)
        return updated

    # ── Import / Export ───────────────────────────────────────────────

    def import_from_yaml(self, groups_data: dict) -> int:
        """Import groups and users from a parsed groups.yaml dict.

        Skips groups and users that already exist (idempotent).

        Returns the total number of users created.
        """
        groups_list = groups_data.get("groups", {})
        total_users = 0
        for group_name, group_data in groups_list.items():
            group_data = group_data or {}
            try:
                group = self.create_group(group_name)
            except DuplicateError:
                groups = self.list_groups()
                group = next((g for g in groups if g.name == group_name), None)
                if group is None:
                    continue
            for username in group_data.get("users", []):
                try:
                    self.create_user(group.id, username)
                    total_users += 1
                except (DuplicateError, ValueError):
                    continue
        logger.info("Imported %d groups, %d users from YAML", len(groups_list), total_users)
        return total_users

    def export_to_yaml(self) -> dict:
        """Export current groups/users to a groups.yaml-compatible dict."""
        groups: dict[str, dict] = {}
        for group in self.list_groups():
            users = getattr(group, "users", [])
            groups[group.name] = {"users": [u.username for u in users]}
        return {"groups": groups}
