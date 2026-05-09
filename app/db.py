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

"""SQLite database layer using SQLModel for sandbox-to-user mapping."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Session, SQLModel, create_engine, select


class SandboxRecord(SQLModel, table=True):
    """Persistent record mapping a sandbox instance to its user/workspace."""

    __tablename__ = "sandbox_records"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    sandbox_id: str = Field(index=True, unique=True)
    group_name: str = Field(default="default")
    username: str = Field(default="workspace")
    port: int = Field(default=8443)
    endpoint: Optional[str] = Field(default=None)
    external_ip: Optional[str] = Field(default=None)
    image: Optional[str] = Field(default=None)
    password: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    terminated_at: Optional[datetime] = Field(default=None)

    @property
    def workspace(self) -> str:
        return f"{self.group_name}/{self.username}"

    @property
    def label(self) -> str:
        return f"{self.group_name}/{self.username}"


class AppSetting(SQLModel, table=True):
    """Global application settings stored as key-value pairs."""

    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: str = Field(default="")


class EventRecord(SQLModel, table=True):
    """An event (hackathon, workshop) that owns a collection of groups."""

    __tablename__ = "event_records"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    event_id: str = Field(unique=True, index=True)
    title: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GroupRecord(SQLModel, table=True):
    """A named group containing users."""

    __tablename__ = "group_records"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(unique=True, index=True)
    event_id: Optional[str] = Field(default=None, index=True)
    title: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GroupRecordWithUsers(SQLModel):
    """GroupRecord with users populated for API responses."""

    id: str
    name: str
    event_id: Optional[str] = None
    title: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    users: list["UserRecord"] = []


class UserRecord(SQLModel, table=True):
    """A user within a group, with workspace and storage paths."""

    __tablename__ = "user_records"
    __table_args__ = (
        UniqueConstraint("group_id", "username", name="uq_user_group_username"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    group_id: str = Field(index=True)
    username: str = Field(index=True)
    workspace_path: Optional[str] = Field(default=None)
    storage_path: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def workspace(self) -> str:
        if self.workspace_path:
            return self.workspace_path
        return f"/workspace/{self.username}"


_default_db_path = Path.home() / ".thon" / "thon.db"
_engine = None


def get_engine(db_path: Optional[str] = None):
    """Get or create the singleton SQLAlchemy engine."""
    global _engine
    if _engine is not None:
        return _engine
    path = Path(db_path) if db_path else _default_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"sqlite:///{path}"
    _engine = create_engine(url, echo=False, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(_engine)
    _migrate(_engine)
    return _engine


def _migrate(engine) -> None:
    """Add missing columns to existing tables (simple alter-table migration)."""
    import sqlalchemy
    with engine.connect() as conn:
        for table in SQLModel.metadata.tables.values():
            for col in table.columns:
                try:
                    conn.execute(sqlalchemy.text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type}"))
                except Exception:
                    pass
        try:
            conn.execute(sqlalchemy.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_group_username ON user_records (group_id, username)"
            ))
        except Exception:
            pass
        conn.commit()


def get_session(db_path: Optional[str] = None) -> Session:
    """Create a new database session."""
    return Session(get_engine(db_path))


def upsert_record(
    sandbox_id: str,
    group_name: str = "default",
    username: str = "workspace",
    port: int = 8443,
    endpoint: Optional[str] = None,
    external_ip: Optional[str] = None,
    image: Optional[str] = None,
    password: Optional[str] = None,
    db_path: Optional[str] = None,
) -> SandboxRecord:
    """Insert or update a sandbox record."""
    with get_session(db_path) as session:
        existing = session.exec(
            select(SandboxRecord).where(SandboxRecord.sandbox_id == sandbox_id)
        ).first()
        if existing:
            existing.group_name = group_name
            existing.username = username
            existing.port = port
            if endpoint is not None:
                existing.endpoint = endpoint
            if external_ip is not None:
                existing.external_ip = external_ip
            if image is not None:
                existing.image = image
            if password is not None:
                existing.password = password
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
        record = SandboxRecord(
            sandbox_id=sandbox_id,
            group_name=group_name,
            username=username,
            port=port,
            endpoint=endpoint,
            external_ip=external_ip,
            image=image,
            password=password,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def get_record(sandbox_id: str, db_path: Optional[str] = None) -> Optional[SandboxRecord]:
    """Look up a sandbox record by sandbox_id."""
    with get_session(db_path) as session:
        return session.exec(
            select(SandboxRecord).where(SandboxRecord.sandbox_id == sandbox_id)
        ).first()


def get_records(
    sandbox_ids: Optional[list[str]] = None,
    db_path: Optional[str] = None,
) -> dict[str, SandboxRecord]:
    """Look up multiple sandbox records, returning a dict keyed by sandbox_id."""
    with get_session(db_path) as session:
        if sandbox_ids:
            records = session.exec(
                select(SandboxRecord).where(SandboxRecord.sandbox_id.in_(sandbox_ids))
            ).all()
        else:
            records = session.exec(select(SandboxRecord)).all()
        return {r.sandbox_id: r for r in records}


def mark_terminated(sandbox_id: str, db_path: Optional[str] = None) -> None:
    """Mark a sandbox record as terminated."""
    with get_session(db_path) as session:
        record = session.exec(
            select(SandboxRecord).where(SandboxRecord.sandbox_id == sandbox_id)
        ).first()
        if record and record.terminated_at is None:
            record.terminated_at = datetime.utcnow()
            session.add(record)
            session.commit()


def update_endpoint(sandbox_id: str, endpoint: str, db_path: Optional[str] = None) -> None:
    """Update the endpoint for a sandbox record."""
    with get_session(db_path) as session:
        record = session.exec(
            select(SandboxRecord).where(SandboxRecord.sandbox_id == sandbox_id)
        ).first()
        if record:
            record.endpoint = endpoint
            session.add(record)
            session.commit()


def get_setting(key: str, db_path: Optional[str] = None) -> Optional[str]:
    """Retrieve a global setting value by key."""
    with get_session(db_path) as session:
        setting = session.exec(
            select(AppSetting).where(AppSetting.key == key)
        ).first()
        return setting.value if setting else None


def set_setting(key: str, value: str, db_path: Optional[str] = None) -> None:
    """Set a global setting value."""
    with get_session(db_path) as session:
        setting = session.exec(
            select(AppSetting).where(AppSetting.key == key)
        ).first()
        if setting:
            setting.value = value
        else:
            setting = AppSetting(key=key, value=value)
        session.add(setting)
        session.commit()


def get_settings_by_prefix(prefix: str, db_path: Optional[str] = None) -> dict[str, str]:
    """Retrieve all settings whose key starts with prefix."""
    with get_session(db_path) as session:
        settings = session.exec(
            select(AppSetting).where(AppSetting.key.startswith(prefix))
        ).all()
        return {s.key: s.value for s in settings}


def delete_setting(key: str, db_path: Optional[str] = None) -> bool:
    """Delete a global setting by key."""
    with get_session(db_path) as session:
        setting = session.exec(
            select(AppSetting).where(AppSetting.key == key)
        ).first()
        if not setting:
            return False
        session.delete(setting)
        session.commit()
        return True


CONFIG_FILE_KEYS = (
    "config_groups_yaml",
    "config_kilo_json",
    "config_vscode_settings",
)


# ── Event CRUD ──────────────────────────────────────────────────────


def get_or_create_event(
    event_id: str, title: Optional[str] = None, db_path: Optional[str] = None
) -> EventRecord:
    """Return an existing event by event_id or create a new one."""
    with get_session(db_path) as session:
        existing = session.exec(
            select(EventRecord).where(EventRecord.event_id == event_id)
        ).first()
        if existing:
            if title is not None and existing.title != title:
                existing.title = title
                existing.updated_at = datetime.utcnow()
                session.add(existing)
                session.commit()
                session.refresh(existing)
            return existing
        event = EventRecord(event_id=event_id, title=title)
        session.add(event)
        session.commit()
        session.refresh(event)
        return event


def get_events(db_path: Optional[str] = None) -> list[EventRecord]:
    """List all events."""
    with get_session(db_path) as session:
        return list(session.exec(select(EventRecord)).all())


def get_event(event_id: str, db_path: Optional[str] = None) -> Optional[EventRecord]:
    """Get an event by its event_id string."""
    with get_session(db_path) as session:
        return session.exec(
            select(EventRecord).where(EventRecord.event_id == event_id)
        ).first()


# ── Group CRUD ──────────────────────────────────────────────────────


def create_group(name: str, db_path: Optional[str] = None) -> GroupRecord:
    """Create a new group."""
    with get_session(db_path) as session:
        existing = session.exec(
            select(GroupRecord).where(GroupRecord.name == name)
        ).first()
        if existing:
            raise ValueError(f"Group '{name}' already exists")
        group = GroupRecord(name=name)
        session.add(group)
        session.commit()
        session.refresh(group)
        return group


def get_groups(db_path: Optional[str] = None) -> list[GroupRecord]:
    """List all groups."""
    with get_session(db_path) as session:
        return list(session.exec(select(GroupRecord)).all())


def get_group(group_id: str, db_path: Optional[str] = None) -> Optional[GroupRecord]:
    """Get a group by ID."""
    with get_session(db_path) as session:
        return session.exec(
            select(GroupRecord).where(GroupRecord.id == group_id)
        ).first()


def rename_group(group_id: str, new_name: str, db_path: Optional[str] = None) -> Optional[GroupRecord]:
    """Rename a group."""
    with get_session(db_path) as session:
        group = session.exec(
            select(GroupRecord).where(GroupRecord.id == group_id)
        ).first()
        if not group:
            return None
        group.name = new_name
        session.add(group)
        session.commit()
        session.refresh(group)
        return group


def delete_group(group_id: str, db_path: Optional[str] = None) -> bool:
    """Delete a group and all its users."""
    with get_session(db_path) as session:
        group = session.exec(
            select(GroupRecord).where(GroupRecord.id == group_id)
        ).first()
        if not group:
            return False
        users = session.exec(
            select(UserRecord).where(UserRecord.group_id == group_id)
        ).all()
        for u in users:
            session.delete(u)
        session.delete(group)
        session.commit()
        return True


# ── User CRUD ───────────────────────────────────────────────────────


def create_user(
    group_id: str,
    username: str,
    workspace_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> UserRecord:
    """Add a user to a group. Raises ValueError if (group_id, username) already exists."""
    with get_session(db_path) as session:
        existing = session.exec(
            select(UserRecord).where(
                UserRecord.group_id == group_id,
                UserRecord.username == username,
            )
        ).first()
        if existing:
            raise ValueError(
                f"User '{username}' already exists in group '{group_id}'"
            )
        user = UserRecord(
            group_id=group_id,
            username=username,
            workspace_path=workspace_path,
            storage_path=storage_path,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def get_users(group_id: str, db_path: Optional[str] = None) -> list[UserRecord]:
    """List all users in a group."""
    with get_session(db_path) as session:
        return list(session.exec(
            select(UserRecord).where(UserRecord.group_id == group_id)
        ).all())


def get_user(user_id: str, db_path: Optional[str] = None) -> Optional[UserRecord]:
    """Get a user by ID."""
    with get_session(db_path) as session:
        return session.exec(
            select(UserRecord).where(UserRecord.id == user_id)
        ).first()


def update_user(
    user_id: str,
    username: Optional[str] = None,
    workspace_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[UserRecord]:
    """Update a user's fields."""
    with get_session(db_path) as session:
        user = session.exec(
            select(UserRecord).where(UserRecord.id == user_id)
        ).first()
        if not user:
            return None
        if username is not None:
            user.username = username
        if workspace_path is not None:
            user.workspace_path = workspace_path
        if storage_path is not None:
            user.storage_path = storage_path
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def delete_user(user_id: str, db_path: Optional[str] = None) -> bool:
    """Remove a user."""
    with get_session(db_path) as session:
        user = session.exec(
            select(UserRecord).where(UserRecord.id == user_id)
        ).first()
        if not user:
            return False
        session.delete(user)
        session.commit()
        return True


def transfer_user(
    user_id: str, target_group_id: str, db_path: Optional[str] = None
) -> Optional[UserRecord]:
    """Move a user to a different group. Raises ValueError on name conflict."""
    with get_session(db_path) as session:
        user = session.exec(
            select(UserRecord).where(UserRecord.id == user_id)
        ).first()
        if not user:
            return None
        conflict = session.exec(
            select(UserRecord).where(
                UserRecord.group_id == target_group_id,
                UserRecord.username == user.username,
            )
        ).first()
        if conflict:
            raise ValueError(
                f"User '{user.username}' already exists in target group '{target_group_id}'"
            )
        user.group_id = target_group_id
        group = session.exec(
            select(GroupRecord).where(GroupRecord.id == target_group_id)
        ).first()
        if group:
            user.workspace_path = f"thon-workspace-{group.name}-{user.username}"
        user.updated_at = datetime.utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def load_groups_from_yaml(
    yaml_path: str,
    event_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[GroupRecord]:
    """Import groups and users from a groups.yaml file, creating DB records.

    Idempotent: skips groups and users that already exist.
    If event_id is provided, links all groups to that event.
    """
    import yaml
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    groups = data.get("groups", {})
    if event_id is None:
        event_id = data.get("event_id")
    title = data.get("title")
    if event_id:
        get_or_create_event(event_id, title=title, db_path=db_path)
    result = []
    for group_name, group_data in groups.items():
        group_data = group_data or {}
        existing_groups = get_groups(db_path=db_path)
        group = next((g for g in existing_groups if g.name == group_name), None)
        if group is None:
            try:
                group = create_group(group_name, db_path=db_path)
            except ValueError:
                existing_groups = get_groups(db_path=db_path)
                group = next((g for g in existing_groups if g.name == group_name), None)
        if not group:
            continue
        if event_id and not group.event_id:
            with get_session(db_path) as session:
                db_group = session.exec(
                    select(GroupRecord).where(GroupRecord.id == group.id)
                ).first()
                if db_group:
                    db_group.event_id = event_id
                    if title and not db_group.title:
                        db_group.title = title
                    db_group.updated_at = datetime.utcnow()
                    session.add(db_group)
                    session.commit()
        for username in group_data.get("users", []):
            existing = find_user_by_group_and_name(group.id, username, db_path=db_path)
            if not existing:
                create_user(group.id, username, db_path=db_path)
        result.append(group)
    return result


def find_user_by_group_and_name(
    group_id: str, username: str, db_path: Optional[str] = None
) -> Optional[UserRecord]:
    """Find a user by group ID and username."""
    with get_session(db_path) as session:
        return session.exec(
            select(UserRecord).where(
                UserRecord.group_id == group_id,
                UserRecord.username == username,
            )
        ).first()
