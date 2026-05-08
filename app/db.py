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
