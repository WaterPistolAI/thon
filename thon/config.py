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

"""Pydantic models for thon.yaml configuration — single source of truth.

All THON settings (groups, sandbox, lemonade, gateway, dashboard, auth,
nginx, vscode, kilo) are expressed in one thon.yaml file. The CLI reads
this file; the API/dashboard reads .env generated from it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


THON_DIR = Path.home() / ".thon"
DEFAULT_CONFIG_PATH = THON_DIR / "thon.yaml"


class SandboxSettings(BaseModel):
    """Sandbox server connection and instance settings."""

    domain: str = "localhost:8080"
    api_key: str = ""
    image: str = "waterpistol/thon:latest"
    starting_port: int = 8443
    timeout_minutes: int = 0


class VscodeSettings(BaseModel):
    """VS Code instance security and customization settings."""

    secure: bool = False
    settings_file: str = ""
    extensions_file: str = ""


class NginxSettings(BaseModel):
    """Nginx reverse proxy and SSL settings."""

    enabled: bool = True
    ssl_dir: str = "/etc/nginx/ssl"
    domain: str = ""
    ssl_provider: str = "auto"
    certbot_email: str = ""


class WorkspaceSettings(BaseModel):
    """Persistent workspace bind-mount settings."""

    dir: str = ""


class ModelOption(BaseModel):
    """A model available for selection as the default chat model."""

    name: str
    checkpoint: str
    context: int = 262144
    output: int = 4096


class LlamacppSettings(BaseModel):
    """llama.cpp inference tuning parameters.

    These map to llama-server CLI flags and are written into
    recipe_options.json ``llamacpp_args``.  They are independent of the
    Lemonade backend selection (auto/vulkan/cpu).
    """

    ctk: str = "q8_0"
    ctv: str = "q8_0"
    batch_size: int = 8192
    ubatch_size: int = 8192
    split_mode: str = ""
    main_gpu: int = -1
    cpu_moe: bool = False
    n_cpu_moe: int = 0
    min_p: float = 0.0
    presence_penalty: float = 0.0

    def to_args(self, num_users: int = 1, timeout: int = 3600) -> str:
        """Build the llamacpp_args string for recipe_options.json."""
        parts: list[str] = []
        parts.append(f"-b {self.batch_size}")
        parts.append(f"-ub {self.ubatch_size}")
        parts.append(f"-to {timeout}")
        parts.append(f"-ctk {self.ctk}")
        parts.append(f"-ctv {self.ctv}")
        if self.split_mode:
            parts.append(f"--split-mode {self.split_mode}")
        if self.main_gpu >= 0:
            parts.append(f"--main-gpu {self.main_gpu}")
        if self.cpu_moe:
            parts.append("--cpu-moe")
        if self.n_cpu_moe > 0:
            parts.append(f"--n-cpu-moe {self.n_cpu_moe}")
        parts.append("--temp 1.0 --top-k 64 --top-p 0.95")
        if self.min_p > 0:
            parts.append(f"--min-p {self.min_p}")
        parts.append("--repeat-penalty 1.0")
        if self.presence_penalty > 0:
            parts.append(f"--presence-penalty {self.presence_penalty}")
        parts.append("--no-webui")
        parts.append("--threads-http -1 --threads -1")
        parts.append(f"-np {num_users}")
        return " ".join(parts)

    def to_embedding_args(self, num_users: int = 1, timeout: int = 3600) -> str:
        """Build llamacpp_args for embedding models (no sampling params)."""
        parts: list[str] = []
        parts.append(f"-b {self.batch_size}")
        parts.append(f"-ub {self.ubatch_size}")
        parts.append(f"-to {timeout}")
        parts.append(f"-ctk {self.ctk}")
        parts.append(f"-ctv {self.ctv}")
        if self.split_mode:
            parts.append(f"--split-mode {self.split_mode}")
        if self.main_gpu >= 0:
            parts.append(f"--main-gpu {self.main_gpu}")
        parts.append("--no-webui")
        parts.append("--threads-http -1 --threads -1")
        parts.append(f"-np {num_users}")
        return " ".join(parts)


class LemonadeSettings(BaseModel):
    """Lemonade local LLM inference server settings."""

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 13305
    model: str = "unsloth/gemma-4-31B-it-GGUF:Q8_K_XL"
    model_name: str = "gemma-4-31b-it"
    mmproj: str = "mmproj-BF16.gguf"
    ctx_size_per_user: int = 262144
    embedding_model: str = (
        "SuperPauly/harrier-oss-v1-0.6b-gguf:harrier-oss-v1-0.6B-BF16"
    )
    embedding_model_name: str = "harrier-oss-v1-0.6b"
    embedding_ctx_size_per_user: int = 32768
    embedding_dimensions: int = 0
    llamacpp_backend: str = "auto"
    prefer_system: bool = True
    llamacpp_bin: str = "builtin"
    rocm_channel: str = "preview"
    generate_keys: bool = True
    api_key: str = ""
    admin_api_key: str = ""
    llamacpp: LlamacppSettings = Field(default_factory=LlamacppSettings)
    chat_models: list[ModelOption] = Field(
        default_factory=lambda: [
            ModelOption(
                name="gemma-4-31b-it",
                checkpoint="unsloth/gemma-4-31B-it-GGUF:Q8_K_XL",
                context=262144,
                output=4096,
            ),
            ModelOption(
                name="qwen3.6-27b",
                checkpoint="unsloth/Qwen3.6-27B-GGUF:Q8_K_XL",
                context=262144,
                output=4096,
            ),
        ]
    )

    def effective_chat_models(self) -> list[ModelOption]:
        """Return chat models with the primary model guaranteed first.

        If the primary ``model_name`` / ``model`` pair is not already in
        ``chat_models``, it is prepended.  Duplicate names (matched by
        ``name`` field) that conflict with the primary model are removed.
        """
        primary = ModelOption(
            name=self.model_name,
            checkpoint=self.model,
            context=self.ctx_size_per_user,
        )
        extras = [m for m in self.chat_models if m.name != self.model_name]
        return [primary] + extras


class LangfuseSettings(BaseModel):
    """Langfuse observability integration for Kilo Code."""

    enabled: bool = False
    public_key: str = ""
    secret_key: str = ""
    base_url: str = "https://cloud.langfuse.com"


class KiloSettings(BaseModel):
    """Kilo Code extension settings injected into sandboxes."""

    config_file: str = ""
    skeleton_file: str = "config/kilo.jsonc.skeleton"
    chat_model: str = "lemonade/user.gemma-4-31b-it"
    small_model: str = ""

    @property
    def resolved_config_file(self) -> Path:
        """Resolve config_file to a path, defaulting to ~/.thon/kilo.jsonc."""
        if self.config_file:
            return Path(self.config_file)
        return THON_DIR / "kilo.jsonc"


class ModelConcurrency(BaseModel):
    """Per-model rate limiting configuration for the AI Gateway.

    When ``rate_limit_scope`` is ``per-model``, each model gets its own
    concurrency and token limits.  Models are registered as instances in
    ``ai-proxy-multi`` and matched by name in ``ai-rate-limiting.instances``.
    """

    model: str = ""
    concurrency_limit: int = 1
    token_limit: int = 0
    token_window: int = 60
    priority: int = 0

    @property
    def prefixed_model(self) -> str:
        """Return the model name with 'user.' prefix for Lemonade/APISIX."""
        if self.model.startswith("user."):
            return self.model
        return f"user.{self.model}"

    @property
    def instance_name(self) -> str:
        """Return the APISIX instance name for this model.

        Instance names must match between ``ai-proxy-multi.instances[].name``
        and ``ai-rate-limiting.instances[].name``.
        """
        short = self.model.removeprefix("user.")
        return f"{short}-instance"


class GatewaySettings(BaseModel):
    """APISIX AI Gateway settings for concurrency control and per-consumer keys.

    ``rate_limit_scope`` controls whether limits are uniform across all models
    (``per-user``) or different per model (``per-model``).  When ``per-model``,
    the ``model_concurrency`` list provides per-model limits that are applied
    via ``ai-rate-limiting.instances`` on a single route with ``ai-proxy-multi``.
    """

    enabled: bool = False
    mode: str = "per-user"
    rate_limit_scope: str = "per-user"
    admin_key: str = ""
    redis_host: str = ""
    redis_port: int = 6379
    concurrency_limit: int = 1
    token_limit: int = 0
    token_window: int = 60
    model_concurrency: list[ModelConcurrency] = Field(default_factory=list)


class DashboardSettings(BaseModel):
    """Web dashboard settings."""

    host: str = "0.0.0.0"
    port: int = 8100
    debug: bool = False


class OAuthProviderSettings(BaseModel):
    """OAuth/OIDC provider credentials."""

    client_id: str = ""
    client_secret: str = ""


class AuthSettings(BaseModel):
    """Authentication / OIDC provider settings."""

    enabled: bool = False
    session_secret: str = ""
    github: OAuthProviderSettings = Field(default_factory=OAuthProviderSettings)
    gitlab: OAuthProviderSettings = Field(default_factory=OAuthProviderSettings)
    linkedin: OAuthProviderSettings = Field(default_factory=OAuthProviderSettings)


class ThonConfig(BaseModel):
    """Root configuration model — maps 1:1 to thon.yaml."""

    demo: bool = False
    external_ip: str = ""
    log_level: str = "INFO"
    groups: dict[str, list[str]] = Field(default_factory=dict)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    vscode: VscodeSettings = Field(default_factory=VscodeSettings)
    nginx: NginxSettings = Field(default_factory=NginxSettings)
    workspace: WorkspaceSettings = Field(default_factory=WorkspaceSettings)
    lemonade: LemonadeSettings = Field(default_factory=LemonadeSettings)
    kilo: KiloSettings = Field(default_factory=KiloSettings)
    gateway: GatewaySettings = Field(default_factory=GatewaySettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ThonConfig:
        """Load configuration from a thon.yaml file."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Config file not found: {p}")
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

    def to_yaml(self, path: str | Path) -> Path:
        """Write configuration to a YAML file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            f.write("# THON Configuration\n")
            f.write("# Generated by `python -m thon init`\n\n")
            yaml.dump(
                self.model_dump(exclude_defaults=False),
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        return p

    def to_env_dict(self) -> dict[str, str]:
        """Export configuration as a flat dict of environment variable names to values.

        Only non-empty / non-default values are included.
        """
        env: dict[str, str] = {}

        if self.external_ip:
            env["EXTERNAL_IP"] = self.external_ip

        if self.log_level and self.log_level.upper() != "INFO":
            env["THON_LOG_LEVEL"] = self.log_level.upper()

        if self.sandbox.domain:
            env["SANDBOX_DOMAIN"] = self.sandbox.domain
        if self.sandbox.api_key:
            env["SANDBOX_API_KEY"] = self.sandbox.api_key
        if self.sandbox.image:
            env["SANDBOX_IMAGE"] = self.sandbox.image

        if self.workspace.dir:
            env["THON_WORKSPACE_DIR"] = self.workspace.dir

        if self.lemonade.host:
            env["LEMONADE_HOST"] = self.lemonade.host
        if self.lemonade.port:
            env["LEMONADE_PORT"] = str(self.lemonade.port)
        if self.lemonade.api_key:
            env["LEMONADE_API_KEY"] = self.lemonade.api_key
        if self.lemonade.admin_api_key:
            env["LEMONADE_ADMIN_API_KEY"] = self.lemonade.admin_api_key

        if self.dashboard.host:
            env["DASHBOARD_HOST"] = self.dashboard.host
        if self.dashboard.port:
            env["DASHBOARD_PORT"] = str(self.dashboard.port)
        if self.dashboard.debug:
            env["DASHBOARD_DEBUG"] = "true"

        if self.auth.enabled:
            env["AUTH_ENABLED"] = "true"
        if self.auth.session_secret:
            env["AUTH_SESSION_SECRET"] = self.auth.session_secret
        if self.auth.github.client_id:
            env["AUTH_GITHUB_CLIENT_ID"] = self.auth.github.client_id
        if self.auth.github.client_secret:
            env["AUTH_GITHUB_CLIENT_SECRET"] = self.auth.github.client_secret
        if self.auth.gitlab.client_id:
            env["AUTH_GITLAB_CLIENT_ID"] = self.auth.gitlab.client_id
        if self.auth.gitlab.client_secret:
            env["AUTH_GITLAB_CLIENT_SECRET"] = self.auth.gitlab.client_secret
        if self.auth.linkedin.client_id:
            env["AUTH_LINKEDIN_CLIENT_ID"] = self.auth.linkedin.client_id
        if self.auth.linkedin.client_secret:
            env["AUTH_LINKEDIN_CLIENT_SECRET"] = self.auth.linkedin.client_secret

        if self.gateway.enabled:
            env["GATEWAY_ENABLED"] = "true"
        if self.gateway.admin_key:
            env["GATEWAY_ADMIN_KEY"] = self.gateway.admin_key
        if self.gateway.redis_host:
            env["GATEWAY_REDIS_HOST"] = self.gateway.redis_host
        if self.gateway.concurrency_limit > 0:
            env["GATEWAY_CONCURRENCY_LIMIT"] = str(self.gateway.concurrency_limit)
        if self.gateway.token_limit > 0:
            env["GATEWAY_TOKEN_LIMIT"] = str(self.gateway.token_limit)
            env["GATEWAY_TOKEN_WINDOW"] = str(self.gateway.token_window)
        if self.gateway.mode:
            env["GATEWAY_MODE"] = self.gateway.mode
        if (
            self.gateway.rate_limit_scope
            and self.gateway.rate_limit_scope != "per-user"
        ):
            env["GATEWAY_RATE_LIMIT_SCOPE"] = self.gateway.rate_limit_scope

        if self.langfuse.enabled:
            env["LANGFUSE_ENABLED"] = "true"
        if self.langfuse.public_key:
            env["LANGFUSE_PUBLIC_KEY"] = self.langfuse.public_key
        if self.langfuse.secret_key:
            env["LANGFUSE_SECRET_KEY"] = self.langfuse.secret_key
        if (
            self.langfuse.base_url
            and self.langfuse.base_url != "https://cloud.langfuse.com"
        ):
            env["LANGFUSE_BASEURL"] = self.langfuse.base_url

        if self.nginx.domain:
            env["THON_DOMAIN"] = self.nginx.domain
        if self.nginx.ssl_provider and self.nginx.ssl_provider != "auto":
            env["THON_SSL_PROVIDER"] = self.nginx.ssl_provider
        if self.nginx.certbot_email:
            env["THON_CERTBOT_EMAIL"] = self.nginx.certbot_email

        if self.kilo.config_file:
            env["THON_KILO_CONFIG"] = self.kilo.config_file
        if self.vscode.settings_file:
            env["THON_VSCODE_SETTINGS"] = self.vscode.settings_file

        return env

    def to_env_file(self, path: str | Path) -> Path:
        """Export configuration as a .env file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# THON Environment Configuration",
            "# Generated from thon.yaml by `python -m thon config env`",
            "",
        ]
        for key, value in sorted(self.to_env_dict().items()):
            lines.append(f"{key}={value}")
        lines.append("")
        p.write_text("\n".join(lines))
        return p

    def total_users(self, group_filter: Optional[str] = None) -> int:
        """Count total users across all groups (or a single group)."""
        total = 0
        for name, users in self.groups.items():
            if group_filter and name != group_filter:
                continue
            total += len(users)
        return total

    def get_users(self, group_filter: Optional[str] = None) -> list[tuple[str, str]]:
        """Return list of (group, username) tuples."""
        result: list[tuple[str, str]] = []
        for name, users in self.groups.items():
            if group_filter and name != group_filter:
                continue
            for username in users:
                result.append((name, username))
        return result

    def apply_env(self) -> None:
        """Push config values into os.environ.

        Values from thon.yaml are always written, even if an env var
        already exists.  This ensures the dashboard and API pick up
        settings like ``THON_DOMAIN`` that are never manually exported.
        """
        for key, value in self.to_env_dict().items():
            os.environ[key] = value
