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

"""Unified kilo.jsonc generator for all deployment modes.

Three modes determine how kilo.jsonc is built and injected per-user:

  lemonade-direct   Single shared API key, Lemonade server endpoint
  gateway-per-user  APISIX gateway with individual API keys per user
  gateway-per-group APISIX gateway with one shared key per group

The skeleton file (config/kilo.jsonc.skeleton) provides static base
settings (experimental flags, MCP servers, indexing defaults).  Dynamic
fields (provider, model, apiKey, baseURL) are generated based on the
active mode and deep-merged on top of the skeleton.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional


class KiloMode(str, Enum):
    LEMONADE_DIRECT = "lemonade-direct"
    GATEWAY_PER_USER = "gateway-per-user"
    GATEWAY_PER_GROUP = "gateway-per-group"


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_skeleton(skeleton_path: Optional[str | Path] = None) -> dict:
    if skeleton_path is None:
        default = Path(__file__).resolve().parent.parent / "config" / "kilo.jsonc.skeleton"
        if default.is_file():
            skeleton_path = default
    if skeleton_path and Path(skeleton_path).is_file():
        try:
            return json.loads(Path(skeleton_path).read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[Kilo] Warning: failed to load skeleton {skeleton_path}: {exc}")
    return {}


def generate_kilo_config(
    mode: KiloMode,
    base_url: str,
    api_key: str,
    model_name: str = "user.gemma-4-31b-it",
    model_context: int = 262144,
    model_output: int = 4096,
    chat_models: Optional[list[dict]] = None,
    default_model: str = "",
    small_model: str = "",
    embedding_base_url: Optional[str] = None,
    embedding_api_key: Optional[str] = None,
    embedding_model: Optional[str] = None,
    embedding_dimension: int = 1024,
    langfuse_enabled: bool = False,
    skeleton_path: Optional[str | Path] = None,
) -> dict:
    """Generate a kilo.jsonc config dict for the given deployment mode.

    Args:
        mode: Deployment mode (lemonade-direct, gateway-per-user, gateway-per-group).
        base_url: Chat completions base URL (Lemonade or APISIX gateway).
        api_key: API key for the chat endpoint.
        model_name: Short model ID (e.g. ``user.gemma-4-31b-it``).
        model_context: Context window limit.
        model_output: Max output tokens.
        chat_models: Additional model options ``[{name, context, output}]``.
        default_model: Override for the top-level ``model`` field (e.g. ``lemonade/user.gemma-4-31b-it``).
        small_model: Small model for agentic tool calling (e.g. ``lemonade/user.gemma-4-E2B-it``).
        embedding_base_url: Separate URL for embedding API (defaults to base_url).
        embedding_api_key: Separate API key for embedding (defaults to api_key).
        embedding_model: Embedding model name (e.g. ``user.harrier-oss-v1-0.6b``).
        langfuse_enabled: Enable Langfuse observability plugin (adds ``plugin`` field).
        skeleton_path: Path to kilo.jsonc.skeleton for base overrides.

    Returns:
        Complete kilo.jsonc as a dict.
    """
    provider_name = "lemonade" if mode == KiloMode.LEMONADE_DIRECT else "lemonade-gateway"
    provider_prefix = "lemonade" if mode == KiloMode.LEMONADE_DIRECT else "lemonade-gateway"

    models_entry: dict[str, dict] = {
        model_name: {
            "limit": {
                "context": model_context,
                "output": model_output,
            },
        },
    }
    if chat_models:
        for m in chat_models:
            m_name = m.get("name", "")
            if m_name and m_name not in models_entry:
                models_entry[m_name] = {
                    "limit": {
                        "context": m.get("context", 262144),
                        "output": m.get("output", 4096),
                    },
                }

    resolved_default = default_model or f"{provider_prefix}/{model_name}"

    emb_url = embedding_base_url or base_url
    emb_key = embedding_api_key or api_key

    generated: dict = {
        "model": resolved_default,
        "provider": {
            provider_name: {
                "models": models_entry,
                "options": {
                    "apiKey": api_key,
                    "baseURL": base_url,
                },
            },
        },
        "indexing": {
            "enabled": True,
            "provider": "openai-compatible",
            "vectorStore": "lancedb",
            "openai-compatible": {
                "baseUrl": emb_url,
                "apiKey": emb_key,
            },
        },
    }
    if small_model:
        generated["small_model"] = small_model
    if embedding_model:
        generated["indexing"]["model"] = embedding_model
    if embedding_dimension > 0:
        generated["indexing"]["dimension"] = embedding_dimension

    if langfuse_enabled:
        generated["plugin"] = ["opencode-plugin-langfuse"]

    skeleton = _load_skeleton(skeleton_path)
    return _deep_merge(skeleton, generated)


def generate_kilo_config_for_user(
    mode: KiloMode,
    base_url: str,
    api_key: str,
    username: str = "",
    group: str = "",
    **kwargs,
) -> str:
    """Generate a per-user kilo.jsonc string with template variables resolved.

    After generating the config dict, substitutes ``$THON_USERNAME``,
    ``$THON_USER_EMAIL``, and ``$WORKSPACE`` with user-specific values.

    Accepts all keyword arguments of :func:`generate_kilo_config`, including
    ``langfuse_enabled``.
    """
    config = generate_kilo_config(mode=mode, base_url=base_url, api_key=api_key, **kwargs)
    content = json.dumps(config, indent=2)

    content = content.replace("$THON_USERNAME", username)
    content = content.replace("$THON_USER_EMAIL", f"{username}@thon.local")
    workspace = f"/workspace/{group}/{username}" if group and username else "/workspace"
    content = content.replace("$WORKSPACE", workspace)

    return content


def resolve_mode(
    lemonade_enabled: bool = False,
    gateway_enabled: bool = False,
    gateway_mode: str = "per-user",
) -> KiloMode:
    """Determine the Kilo deployment mode from configuration."""
    if gateway_enabled:
        if gateway_mode == "per-group":
            return KiloMode.GATEWAY_PER_GROUP
        return KiloMode.GATEWAY_PER_USER
    if lemonade_enabled:
        return KiloMode.LEMONADE_DIRECT
    return KiloMode.LEMONADE_DIRECT
