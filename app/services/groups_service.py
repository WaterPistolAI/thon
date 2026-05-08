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
import os
import subprocess
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import select

from app.db import (
    EventRecord,
    GroupRecord,
    GroupRecordWithUsers,
    UserRecord,
    create_group as db_create_group,
    create_user as db_create_user,
    delete_group as db_delete_group,
    delete_user as db_delete_user,
    get_event as db_get_event,
    get_events as db_get_events,
    get_group as db_get_group,
    get_groups as db_get_groups,
    get_or_create_event as db_get_or_create_event,
    get_session,
    get_users as db_get_users,
    rename_group as db_rename_group,
    transfer_user as db_transfer_user,
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
        self._workspace_dir = os.path.expanduser(workspace_dir) if workspace_dir else None

    @staticmethod
    def _ensure_volume(volume_name: str) -> None:
        """Create a Docker named volume if it does not already exist."""
        try:
            subprocess.run(
                ["docker", "volume", "create", volume_name],
                capture_output=True,
                check=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning("Failed to create Docker volume '%s': %s", volume_name, e)

    def _with_users(self, group: GroupRecord) -> GroupRecordWithUsers:
        users = db_get_users(group.id, db_path=self._db_path)
        return GroupRecordWithUsers(
            id=group.id,
            name=group.name,
            event_id=group.event_id,
            title=group.title,
            created_at=group.created_at,
            updated_at=group.updated_at,
            users=users,
        )

    # ── Groups ────────────────────────────────────────────────────────

    def list_groups(self) -> list[GroupRecordWithUsers]:
        """Return all groups with their users populated."""
        groups = db_get_groups(db_path=self._db_path)
        return [self._with_users(g) for g in groups]

    def get_group(self, group_id: str) -> GroupRecordWithUsers:
        """Fetch a single group by UUID."""
        group = db_get_group(group_id, db_path=self._db_path)
        if group is None:
            raise GroupNotFoundError(f"Group {group_id} not found")
        return self._with_users(group)

    def create_group(self, name: str) -> GroupRecordWithUsers:
        """Create a new group with an auto-generated UUID."""
        try:
            group = db_create_group(name, db_path=self._db_path)
        except ValueError as e:
            raise DuplicateError(str(e)) from e
        logger.info("Created group '%s' (id=%s)", name, group.id)
        return GroupRecordWithUsers(
            id=group.id,
            name=group.name,
            created_at=group.created_at,
            updated_at=group.updated_at,
            users=[],
        )

    def update_group(self, group_id: str, name: str) -> GroupRecordWithUsers:
        """Rename an existing group."""
        group = db_rename_group(group_id, name, db_path=self._db_path)
        if group is None:
            raise GroupNotFoundError(f"Group {group_id} not found")
        return self._with_users(group)

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

        Raises ``DuplicateError`` if this username already exists in the group.
        Derives ``workspace_path`` and ``storage_path`` as Docker named
        volume names (PVC claimName) used by the OpenSandbox ``pvc`` backend:
          - workspace_path: ``thon-workspace-{group_name}-{username}``
          - storage_path:   ``thon-storage-{user_uuid}``
        """
        group = db_get_group(group_id, db_path=self._db_path)
        if group is None:
            raise GroupNotFoundError(f"Group {group_id} not found")

        user_id = str(uuid.uuid4())
        workspace_path = f"thon-workspace-{group.name}-{username}"
        storage_path = f"thon-storage-{user_id}"

        try:
            user = db_create_user(
                group_id=group_id,
                username=username,
                workspace_path=workspace_path,
                storage_path=storage_path,
                db_path=self._db_path,
            )
        except ValueError as e:
            raise DuplicateError(str(e)) from e
        self._ensure_volume(workspace_path)
        self._ensure_volume(storage_path)
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

    def transfer_user(self, user_id: str, target_group_id: str) -> UserRecord:
        """Move a user to a different group.

        Raises ``UserNotFoundError`` if the user does not exist.
        Raises ``GroupNotFoundError`` if the target group does not exist.
        Raises ``DuplicateError`` if the username already exists in the target group.
        """
        target_group = db_get_group(target_group_id, db_path=self._db_path)
        if target_group is None:
            raise GroupNotFoundError(f"Target group {target_group_id} not found")
        try:
            user = db_transfer_user(user_id, target_group_id, db_path=self._db_path)
        except ValueError as e:
            raise DuplicateError(str(e)) from e
        if user is None:
            raise UserNotFoundError(f"User {user_id} not found")
        new_workspace = f"thon-workspace-{target_group.name}-{user.username}"
        self._ensure_volume(new_workspace)
        logger.info(
            "Transferred user '%s' to group '%s' (id=%s)",
            user.username, target_group.name, user.id,
        )
        return user

    # ── Storage path backfill ─────────────────────────────────────────

    def backfill_storage_paths(self) -> int:
        """Populate workspace_path and storage_path for users missing them.

        Derives Docker named volume names (PVC claimName) and creates the
        volumes. Returns count updated.
        """
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
                user.workspace_path = f"thon-workspace-{group_name}-{user.username}"
                user.storage_path = f"thon-storage-{user.id}"
                user.updated_at = datetime.utcnow()
                session.add(user)
                self._ensure_volume(user.workspace_path)
                self._ensure_volume(user.storage_path)
                updated += 1
            if updated:
                session.commit()
        if updated:
            logger.info("Backfilled storage paths for %d user(s)", updated)
        return updated

    # ── Import / Export ───────────────────────────────────────────────

    def import_from_yaml(
        self, groups_data: dict, event_id: Optional[str] = None
    ) -> int:
        """Import groups and users from a parsed groups.yaml dict.

        Idempotent: skips groups and users that already exist.
        Links all imported groups to the given event_id.
        Reads event_id and title from the YAML if not provided.

        Returns the total number of users created.
        """
        yaml_event_id = groups_data.get("event_id") or event_id
        title = groups_data.get("title")

        if yaml_event_id:
            db_get_or_create_event(
                yaml_event_id, title=title, db_path=self._db_path
            )

        groups_list = groups_data.get("groups", {})
        total_users = 0
        for group_name, group_data in groups_list.items():
            group_data = group_data or {}
            group_title = group_data.get("title")
            try:
                group = self.create_group(group_name)
            except DuplicateError:
                groups = self.list_groups()
                group = next((g for g in groups if g.name == group_name), None)
                if group is None:
                    continue
            if yaml_event_id and not group.event_id:
                with get_session(self._db_path) as session:
                    db_group = session.exec(
                        select(GroupRecord).where(GroupRecord.id == group.id)
                    ).first()
                    if db_group:
                        db_group.event_id = yaml_event_id
                        if group_title and not db_group.title:
                            db_group.title = group_title
                        elif title and not db_group.title:
                            db_group.title = title
                        db_group.updated_at = datetime.utcnow()
                        session.add(db_group)
                        session.commit()
            for username in group_data.get("users", []):
                try:
                    self.create_user(group.id, username)
                    total_users += 1
                except DuplicateError:
                    continue
        logger.info("Imported %d groups, %d users from YAML", len(groups_list), total_users)
        return total_users

    def export_to_yaml(self) -> dict:
        """Export current groups/users to a groups.yaml-compatible dict."""
        groups: dict[str, dict] = {}
        event_id: Optional[str] = None
        title: Optional[str] = None
        events = db_get_events(db_path=self._db_path)
        if events:
            event_id = events[0].event_id
            title = events[0].title
        for group in self.list_groups():
            group_data: dict[str, object] = {"users": [u.username for u in group.users]}
            if group.title:
                group_data["title"] = group.title
            groups[group.name] = group_data
        result: dict[str, object] = {"groups": groups}
        if event_id:
            result["event_id"] = event_id
        if title:
            result["title"] = title
        return result

    # ── Events ────────────────────────────────────────────────────────

    def list_events(self) -> list[EventRecord]:
        """Return all events."""
        return db_get_events(db_path=self._db_path)

    def get_event(self, event_id: str) -> EventRecord:
        """Get an event by its event_id string."""
        event = db_get_event(event_id, db_path=self._db_path)
        if event is None:
            raise GroupNotFoundError(f"Event '{event_id}' not found")
        return event
