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

"""Core domain models for THON."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class InstanceState(str, Enum):
    """Lifecycle state of a sandbox instance."""

    PENDING = "Pending"
    RUNNING = "Running"
    PAUSING = "Pausing"
    PAUSED = "Paused"
    STOPPING = "Stopping"
    TERMINATED = "Terminated"
    FAILED = "Failed"


class InstanceAction(str, Enum):
    """Actions that can be performed on an instance."""

    CREATE = "create"
    PAUSE = "pause"
    RESUME = "resume"
    KILL = "kill"
    RENEW = "renew"


@dataclass
class UserInfo:
    """A user within a group."""

    group: str
    username: str

    @property
    def workspace(self) -> str:
        return f"{self.group}/{self.username}"

    @property
    def label(self) -> str:
        return f"{self.group}/{self.username}"


class InstanceInfo(BaseModel):
    """Runtime information about a sandbox instance."""

    id: str
    user: UserInfo
    state: InstanceState
    port: int
    endpoint: Optional[str] = None
    public_url: Optional[str] = None
    password: Optional[str] = None
    image: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    metadata: dict = Field(default_factory=dict)

    @computed_field
    @property
    def url(self) -> Optional[str]:
        if self.public_url:
            return self.public_url
        if self.endpoint:
            return f"http://{self.endpoint}/"
        return None


@dataclass
class GroupConfig:
    """A group definition from groups.yaml."""

    name: str
    users: list[str] = field(default_factory=list)


@dataclass
class LemonadeStatus:
    """Status snapshot of the Lemonade inference server."""

    running: bool = False
    endpoint: str = ""
    model: str = ""
    api_key_configured: bool = False
    ctx_size: int = 0
    num_users: int = 0


@dataclass
class DashboardSession:
    """Authenticated dashboard session."""

    user_id: str
    display_name: str
    email: str
    provider: str
    created_at: datetime = field(default_factory=datetime.utcnow)
