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

"""Application configuration loaded from environment variables and config files."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.env import load_env

load_env()


@dataclass
class SandboxConfig:
    """Sandbox server connection settings."""

    domain: str = field(
        default_factory=lambda: os.getenv("SANDBOX_DOMAIN", "localhost:8080")
    )
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("SANDBOX_API_KEY"))
    image: str = field(
        default_factory=lambda: os.getenv("SANDBOX_IMAGE", "waterpistol/thon:latest")
    )
    request_timeout_seconds: int = 60


@dataclass
class LemonadeConfig:
    """Lemonade inference server settings."""

    host: str = field(default_factory=lambda: os.getenv("LEMONADE_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("LEMONADE_PORT", "13305")))
    api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("LEMONADE_API_KEY")
    )
    admin_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("LEMONADE_ADMIN_API_KEY")
    )
    config_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("LEMONADE_CONFIG_DIR", "/var/lib/lemonade/.cache/lemonade")
        )
    )


@dataclass
class DashboardConfig:
    """Web dashboard settings."""

    host: str = field(default_factory=lambda: os.getenv("DASHBOARD_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("DASHBOARD_PORT", "8100")))
    secret_key: str = field(
        default_factory=lambda: os.getenv("DASHBOARD_SECRET_KEY", "")
    )
    debug: bool = field(
        default_factory=lambda: (
            os.getenv("DASHBOARD_DEBUG", "").lower() in ("1", "true", "yes")
        )
    )


@dataclass
class AuthConfig:
    """Authentication / OIDC provider settings."""

    enabled: bool = field(
        default_factory=lambda: (
            os.getenv("AUTH_ENABLED", "").lower() in ("1", "true", "yes")
        )
    )
    session_secret: str = field(
        default_factory=lambda: os.getenv("AUTH_SESSION_SECRET", "")
    )
    github_client_id: Optional[str] = field(
        default_factory=lambda: os.getenv("AUTH_GITHUB_CLIENT_ID")
    )
    github_client_secret: Optional[str] = field(
        default_factory=lambda: os.getenv("AUTH_GITHUB_CLIENT_SECRET")
    )
    gitlab_client_id: Optional[str] = field(
        default_factory=lambda: os.getenv("AUTH_GITLAB_CLIENT_ID")
    )
    gitlab_client_secret: Optional[str] = field(
        default_factory=lambda: os.getenv("AUTH_GITLAB_CLIENT_SECRET")
    )
    linkedin_client_id: Optional[str] = field(
        default_factory=lambda: os.getenv("AUTH_LINKEDIN_CLIENT_ID")
    )
    linkedin_client_secret: Optional[str] = field(
        default_factory=lambda: os.getenv("AUTH_LINKEDIN_CLIENT_SECRET")
    )
    local_password: Optional[str] = field(
        default_factory=lambda: os.getenv("AUTH_LOCAL_PASSWORD")
    )


@dataclass
class NginxConfig:
    """Nginx reverse proxy settings."""

    ssl_dir: str = "/etc/nginx/ssl"
    external_ip: Optional[str] = field(default_factory=lambda: os.getenv("EXTERNAL_IP"))


@dataclass
class DatabaseConfig:
    """SQLite database settings."""

    path: str = field(
        default_factory=lambda: os.getenv(
            "THON_DB_PATH", str(Path.home() / ".thon" / "thon.db")
        )
    )


@dataclass
class LogConfig:
    """Logging configuration."""

    level: str = field(default_factory=lambda: os.getenv("THON_LOG_LEVEL", "INFO"))
    format: str = field(
        default_factory=lambda: os.getenv(
            "THON_LOG_FORMAT",
            "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        )
    )


@dataclass
class EventConfig:
    """Event (hackathon) identity settings."""

    event_id: Optional[str] = field(default_factory=lambda: os.getenv("THON_EVENT_ID"))
    title: Optional[str] = field(default_factory=lambda: os.getenv("THON_EVENT_TITLE"))


@dataclass
class GatewayConfig:
    """APISIX AI Gateway settings."""

    enabled: bool = field(
        default_factory=lambda: (
            os.getenv("GATEWAY_ENABLED", "").lower() in ("1", "true", "yes")
        )
    )
    admin_url: str = field(
        default_factory=lambda: os.getenv("GATEWAY_ADMIN_URL", "http://127.0.0.1:9180")
    )
    admin_key: str = field(default_factory=lambda: os.getenv("GATEWAY_ADMIN_KEY", ""))
    proxy_port: int = field(
        default_factory=lambda: int(os.getenv("GATEWAY_PROXY_PORT", "9080"))
    )
    redis_host: Optional[str] = field(
        default_factory=lambda: os.getenv("GATEWAY_REDIS_HOST")
    )
    redis_port: int = field(
        default_factory=lambda: int(os.getenv("GATEWAY_REDIS_PORT", "6379"))
    )
    redis_password: Optional[str] = field(
        default_factory=lambda: os.getenv("GATEWAY_REDIS_PASSWORD")
    )
    concurrency_limit: int = field(
        default_factory=lambda: int(os.getenv("GATEWAY_CONCURRENCY_LIMIT", "1"))
    )
    token_limit: int = field(
        default_factory=lambda: int(os.getenv("GATEWAY_TOKEN_LIMIT", "0"))
    )
    token_window: int = field(
        default_factory=lambda: int(os.getenv("GATEWAY_TOKEN_WINDOW", "60"))
    )
    gateway_mode: str = field(
        default_factory=lambda: os.getenv("GATEWAY_MODE", "per-user")
    )


@dataclass
class AppConfig:
    """Root application configuration aggregating all sub-configs."""

    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    lemonade: LemonadeConfig = field(default_factory=LemonadeConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    nginx: NginxConfig = field(default_factory=NginxConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    event: EventConfig = field(default_factory=EventConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    log: LogConfig = field(default_factory=LogConfig)
    groups_file: Optional[Path] = None
    workspace_dir: str = field(
        default_factory=lambda: os.getenv(
            "THON_WORKSPACE_DIR", str(Path.home() / ".thon" / "workspace")
        )
    )

    @classmethod
    def from_env(cls, groups_file: Optional[str] = None) -> "AppConfig":
        cfg = cls()
        if groups_file:
            p = Path(groups_file)
            cfg.groups_file = p if p.exists() else None
        return cfg
