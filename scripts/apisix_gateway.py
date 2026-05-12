#!/usr/bin/env python3
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

"""APISIX AI Gateway management with rate limiting and per-consumer API keys.

Wraps APISIX Admin API to configure:
- ``ai-proxy-multi`` plugin for LLM upstream load balancing
- ``ai-rate-limiting`` plugin for token-based rate limiting
- ``key-auth`` plugin for individual consumer API keys
- Redis-backed rate limiting for multi-instance consistency

The admin API key is auto-detected from the APISIX config file
(``/usr/local/apisix/conf/config.yaml``). An explicit key can be passed
via the ``admin_key`` parameter or the ``GATEWAY_ADMIN_KEY`` env var,
but the default is always read from the installed config.

Usage:
    from apisix_gateway import ApisixGatewayManager

    mgr = ApisixGatewayManager()  # auto-detects key from APISIX config
    mgr.create_consumer(username="alice", api_key="alice-key-123", concurrency_limit=1)
    mgr.create_ai_route(lemonade_url="http://127.0.0.1:13305", lemonade_api_key="sk-xxx")
    mgr.setup_gateway(lemonade_url="http://127.0.0.1:13305", users=[...])
"""

import argparse
import json
import logging
import os
import secrets
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

APISIX_ADMIN_PORT_DEFAULT = 9180
APISIX_PROXY_PORT_DEFAULT = 9080
APISIX_CONFIG_PATH = Path("/usr/local/apisix/conf/config.yaml")
APISIX_ROUTE_ID = "ai-gateway-route"
APISIX_EMBEDDING_ROUTE_ID = "ai-gateway-embedding-route"
LEMONADE_INSTANCE_NAME = "lemonade-instance"
CONCURRENCY_LIMIT_DEFAULT = 1
TOKEN_LIMIT_DEFAULT = 0
TOKEN_WINDOW_DEFAULT = 60


@dataclass
class ConsumerConfig:
    username: str
    api_key: str
    concurrency_limit: int = CONCURRENCY_LIMIT_DEFAULT
    token_limit: int = TOKEN_LIMIT_DEFAULT
    token_window: int = TOKEN_WINDOW_DEFAULT


@dataclass
class ModelRouteConfig:
    model: str
    route_uri: str
    concurrency_limit: int = CONCURRENCY_LIMIT_DEFAULT
    route_id_suffix: str = ""


@dataclass
class GatewayStatus:
    running: bool = False
    admin_url: str = ""
    proxy_url: str = ""
    consumers_count: int = 0
    route_configured: bool = False
    redis_connected: bool = False


class ApisixGatewayManager:
    """Manages APISIX AI Gateway configuration via the Admin API.

    Provides high-level methods for:
    - Consumer CRUD with key-auth credentials
    - AI route creation with ai-proxy-multi and ai-rate-limiting
    - Gateway setup/teardown for the full lifecycle
    """

    def __init__(
        self,
        admin_url: str = "http://127.0.0.1:9180",
        admin_key: Optional[str] = None,
        proxy_port: int = APISIX_PROXY_PORT_DEFAULT,
        redis_host: Optional[str] = None,
        redis_port: int = 6379,
        redis_password: Optional[str] = None,
        lemonade_api_key: Optional[str] = None,
    ) -> None:
        self._admin_url = admin_url.rstrip("/")
        detected = self._detect_admin_key()
        resolved_key = admin_key or os.getenv("GATEWAY_ADMIN_KEY") or detected
        if not resolved_key:
            raise RuntimeError(
                "APISIX admin key not found. Either pass admin_key, "
                "set GATEWAY_ADMIN_KEY env var, or install APISIX "
                f"(config expected at {APISIX_CONFIG_PATH})"
            )
        self._admin_key = resolved_key
        self._proxy_port = proxy_port
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._redis_password = redis_password
        self._lemonade_api_key = lemonade_api_key

    @staticmethod
    def _detect_admin_key() -> Optional[str]:
        try:
            if APISIX_CONFIG_PATH.exists():
                with open(APISIX_CONFIG_PATH) as f:
                    data = yaml.safe_load(f)
                deployment = (
                    data.get("deployment", {}) if isinstance(data, dict) else {}
                )
                admin = (
                    deployment.get("admin", {}) if isinstance(deployment, dict) else {}
                )
                keys = admin.get("admin_key", []) if isinstance(admin, dict) else []
                for key_entry in keys:
                    if isinstance(key_entry, dict) and key_entry.get("role") == "admin":
                        detected = key_entry.get("key")
                        if detected:
                            return detected
        except Exception:
            pass
        return None

    @property
    def proxy_url(self) -> str:
        host = self._admin_url.split("//", 1)[1].split(":")[0]
        return f"http://{host}:{self._proxy_port}"

    @property
    def admin_url(self) -> str:
        return self._admin_url

    def _request(
        self,
        path: str,
        method: str = "GET",
        data: Optional[dict] = None,
    ) -> dict:
        url = f"{self._admin_url}/apisix/admin{path}"
        body = json.dumps(data).encode() if data else None

        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("X-API-KEY", self._admin_key)
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                response_data = resp.read().decode()
                return json.loads(response_data) if response_data else {}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise RuntimeError(
                f"APISIX Admin API error {e.code} for {method} {path}: {error_body}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot connect to APISIX Admin API at {self._admin_url}: {e}"
            ) from e

    def is_running(self) -> bool:
        try:
            self._request("/routes")
            return True
        except RuntimeError:
            return False

    def get_status(self) -> GatewayStatus:
        running = self.is_running()
        consumers_count = 0
        route_configured = False

        if running:
            try:
                result = self._request("/consumers")
                consumers_count = (
                    result.get("total", 0) if isinstance(result, dict) else 0
                )
            except RuntimeError:
                pass
            try:
                self._request(f"/routes/{APISIX_ROUTE_ID}")
                route_configured = True
            except RuntimeError:
                pass

        return GatewayStatus(
            running=running,
            admin_url=self._admin_url,
            proxy_url=self.proxy_url,
            consumers_count=consumers_count,
            route_configured=route_configured,
            redis_connected=self._redis_host is not None,
        )

    def create_consumer(
        self,
        username: str,
        api_key: Optional[str] = None,
        concurrency_limit: int = CONCURRENCY_LIMIT_DEFAULT,
        token_limit: int = TOKEN_LIMIT_DEFAULT,
        token_window: int = TOKEN_WINDOW_DEFAULT,
        lemonade_instance_name: str = LEMONADE_INSTANCE_NAME,
    ) -> ConsumerConfig:
        api_key = api_key or secrets.token_urlsafe(24)
        safe_username = username.replace("/", "-").replace(" ", "_")

        plugins: dict = {
            "key-auth": {"key": api_key},
        }

        if concurrency_limit > 0:
            limit_conn_config: dict = {
                "conn": concurrency_limit,
                "burst": 0,
                "default_conn_delay": 0.1,
                "key_type": "var",
                "key": "consumer_name",
                "rejected_code": 429,
                "rejected_msg": "Concurrency limit exceeded. Please wait for your current request to complete.",
            }
            if self._redis_host:
                limit_conn_config["policy"] = "redis"
                limit_conn_config["redis_host"] = self._redis_host
                limit_conn_config["redis_port"] = self._redis_port
                if self._redis_password:
                    limit_conn_config["redis_password"] = self._redis_password
            else:
                limit_conn_config["policy"] = "local"
            plugins["limit-conn"] = limit_conn_config

        if token_limit > 0:
            rate_limit_config: dict = {
                "policy": "redis" if self._redis_host else "local",
                "limit_strategy": "total_tokens",
                "instances": [
                    {
                        "name": lemonade_instance_name,
                        "limit": token_limit,
                        "time_window": token_window,
                    }
                ],
                "rejected_code": 429,
            }
            if self._redis_host:
                rate_limit_config["redis_host"] = self._redis_host
                rate_limit_config["redis_port"] = self._redis_port
                if self._redis_password:
                    rate_limit_config["redis_password"] = self._redis_password
            plugins["ai-rate-limiting"] = rate_limit_config

        consumer_data = {
            "username": safe_username,
            "plugins": plugins,
        }

        self._request("/consumers", method="PUT", data=consumer_data)

        limits_desc = []
        if concurrency_limit > 0:
            limits_desc.append(f"concurrency={concurrency_limit}")
        if token_limit > 0:
            limits_desc.append(f"tokens={token_limit}/{token_window}s")
        limits_str = ", ".join(limits_desc) if limits_desc else "no limits"
        print(f"[Gateway] Created consumer: {safe_username} ({limits_str})")

        return ConsumerConfig(
            username=safe_username,
            api_key=api_key,
            concurrency_limit=concurrency_limit,
            token_limit=token_limit,
            token_window=token_window,
        )

    def delete_consumer(self, username: str) -> None:
        safe_username = username.replace("/", "-").replace(" ", "_")
        self._request(f"/consumers/{safe_username}", method="DELETE")
        print(f"[Gateway] Deleted consumer: {safe_username}")

    def list_consumers(self) -> list[dict]:
        try:
            result = self._request("/consumers")
            if isinstance(result, dict) and "list" in result:
                return [
                    {
                        "username": item.get("value", {}).get("username", ""),
                        "plugins": item.get("value", {}).get("plugins", {}),
                    }
                    for item in result["list"]
                ]
            return []
        except RuntimeError:
            return []

    def create_ai_route(
        self,
        lemonade_url: str,
        lemonade_api_key: Optional[str] = None,
        lemonade_model: str = "user.gemma-4-31b-it",
        lemonade_instance_name: str = LEMONADE_INSTANCE_NAME,
        uri: str = "/v1/chat/completions",
        route_id: Optional[str] = None,
        concurrency_limit: int = 0,
    ) -> dict:
        effective_key = lemonade_api_key or self._lemonade_api_key
        auth_header: dict = {}
        if effective_key:
            auth_header["Authorization"] = f"Bearer {effective_key}"

        plugins: dict = {
            "key-auth": {},
            "ai-proxy-multi": {
                "instances": [
                    {
                        "name": lemonade_instance_name,
                        "provider": "openai-compatible",
                        "weight": 100,
                        "override": {
                            "endpoint": lemonade_url,
                        },
                        "auth": {
                            "header": auth_header,
                        },
                        "options": {
                            "model": lemonade_model,
                        },
                    }
                ]
            },
        }

        if concurrency_limit > 0:
            limit_conn_config: dict = {
                "conn": concurrency_limit,
                "burst": 0,
                "default_conn_delay": 0.1,
                "key_type": "var",
                "key": "consumer_name",
                "rejected_code": 429,
                "rejected_msg": f"Concurrency limit ({concurrency_limit}) exceeded for {lemonade_model}. Please wait for your current request to complete.",
            }
            if self._redis_host:
                limit_conn_config["policy"] = "redis"
                limit_conn_config["redis_host"] = self._redis_host
                limit_conn_config["redis_port"] = self._redis_port
                if self._redis_password:
                    limit_conn_config["redis_password"] = self._redis_password
            else:
                limit_conn_config["policy"] = "local"
            plugins["limit-conn"] = limit_conn_config

        route_data: dict = {
            "uri": uri,
            "methods": ["POST"],
            "plugins": plugins,
        }

        resolved_route_id = route_id or APISIX_ROUTE_ID
        result = self._request(
            f"/routes/{resolved_route_id}", method="PUT", data=route_data
        )
        limits_desc = f", concurrency={concurrency_limit}" if concurrency_limit > 0 else ""
        print(f"[Gateway] Created AI route: {uri} -> {lemonade_url} (model={lemonade_model}{limits_desc})")
        return result

    def delete_ai_route(self, route_id: Optional[str] = None) -> None:
        resolved_id = route_id or APISIX_ROUTE_ID
        try:
            self._request(f"/routes/{resolved_id}", method="DELETE")
            print(f"[Gateway] Deleted AI route: {resolved_id}")
        except RuntimeError as e:
            print(f"[Gateway] Warning: Could not delete route {resolved_id}: {e}")

    def create_embedding_route(
        self,
        lemonade_url: str,
        lemonade_api_key: Optional[str] = None,
        lemonade_embedding_model: str = "user.harrier-oss-v1-0.6b",
        concurrency_limit: int = 0,
    ) -> dict:
        """Create an APISIX route for /v1/embeddings with key-auth and rate limiting.

        Uses simple upstream proxying rather than ai-proxy-multi since
        embedding requests are straightforward proxy passthrough.

        Args:
            lemonade_url: Upstream Lemonade server URL.
            lemonade_api_key: API key for Lemonade authentication.
            lemonade_embedding_model: Default embedding model name.
            concurrency_limit: Max concurrent embedding requests per consumer (0=no limit).

        Returns:
            APISIX Admin API response dict.
        """
        from urllib.parse import urlparse

        parsed = urlparse(lemonade_url)
        upstream_host = parsed.hostname or "127.0.0.1"
        upstream_port = parsed.port or 13305

        effective_key = lemonade_api_key or self._lemonade_api_key

        plugins: dict = {"key-auth": {}}
        if effective_key:
            plugins["proxy-rewrite"] = {
                "headers": {
                    "set": {"Authorization": f"Bearer {effective_key}"},
                },
            }

        if concurrency_limit > 0:
            limit_conn_config: dict = {
                "conn": concurrency_limit,
                "burst": 0,
                "default_conn_delay": 0.1,
                "key_type": "var",
                "key": "consumer_name",
                "rejected_code": 429,
                "rejected_msg": f"Concurrency limit ({concurrency_limit}) exceeded for {lemonade_embedding_model}. Please wait.",
            }
            if self._redis_host:
                limit_conn_config["policy"] = "redis"
                limit_conn_config["redis_host"] = self._redis_host
                limit_conn_config["redis_port"] = self._redis_port
                if self._redis_password:
                    limit_conn_config["redis_password"] = self._redis_password
            else:
                limit_conn_config["policy"] = "local"
            plugins["limit-conn"] = limit_conn_config

        route_data: dict = {
            "uri": "/v1/embeddings",
            "methods": ["POST"],
            "plugins": plugins,
            "upstream": {
                "type": "roundrobin",
                "nodes": {
                    f"{upstream_host}:{upstream_port}": 1,
                },
            },
        }

        result = self._request(
            f"/routes/{APISIX_EMBEDDING_ROUTE_ID}", method="PUT", data=route_data
        )
        limits_desc = f", concurrency={concurrency_limit}" if concurrency_limit > 0 else ""
        print(f"[Gateway] Created embedding route: /v1/embeddings -> {lemonade_url} (model={lemonade_embedding_model}{limits_desc})")
        return result

    def delete_embedding_route(self) -> None:
        try:
            self._request(f"/routes/{APISIX_EMBEDDING_ROUTE_ID}", method="DELETE")
            print(f"[Gateway] Deleted embedding route: {APISIX_EMBEDDING_ROUTE_ID}")
        except RuntimeError as e:
            print(f"[Gateway] Warning: Could not delete embedding route: {e}")

    def cleanup(self) -> None:
        consumers = self.list_consumers()
        for consumer in consumers:
            username = consumer.get("username", "")
            if username:
                try:
                    self.delete_consumer(username)
                except RuntimeError as e:
                    print(
                        f"[Gateway] Warning: Could not delete consumer {username}: {e}"
                    )

        try:
            result = self._request("/routes")
            if isinstance(result, dict) and "list" in result:
                for item in result["list"]:
                    route_id = item.get("key", "")
                    if route_id.startswith("ai-gateway-"):
                        self.delete_ai_route(route_id)
        except RuntimeError:
            self.delete_ai_route()

        self.delete_embedding_route()
        print("[Gateway] Cleanup complete")

    def setup_gateway(
        self,
        lemonade_url: str,
        users: Optional[list[ConsumerConfig]] = None,
        lemonade_api_key: Optional[str] = None,
        lemonade_model: str = "user.gemma-4-31b-it",
        lemonade_embedding_model: str = "user.harrier-oss-v1-0.6b",
        route_uri: str = "/v1/chat/completions",
        enable_embedding: bool = True,
        model_routes: Optional[list[ModelRouteConfig]] = None,
    ) -> list[ConsumerConfig]:
        if model_routes:
            for mr in model_routes:
                route_id = f"ai-gateway-{mr.route_id_suffix}" if mr.route_id_suffix else APISIX_ROUTE_ID
                self.create_ai_route(
                    lemonade_url=lemonade_url,
                    lemonade_api_key=lemonade_api_key,
                    lemonade_model=mr.model,
                    uri=mr.route_uri,
                    route_id=route_id,
                    concurrency_limit=mr.concurrency_limit,
                )
        else:
            self.create_ai_route(
                lemonade_url=lemonade_url,
                lemonade_api_key=lemonade_api_key,
                lemonade_model=lemonade_model,
                uri=route_uri,
            )

        if enable_embedding and not any(
            mr.route_uri == "/v1/embeddings" for mr in (model_routes or [])
        ):
            embedding_concurrency = 0
            if model_routes:
                emb_short = lemonade_embedding_model.removeprefix("user.")
                emb_route = next(
                    (
                        mr
                        for mr in model_routes
                        if mr.model == lemonade_embedding_model
                        or mr.model == emb_short
                    ),
                    None,
                )
                if emb_route:
                    embedding_concurrency = emb_route.concurrency_limit
            self.create_embedding_route(
                lemonade_url=lemonade_url,
                lemonade_api_key=lemonade_api_key,
                lemonade_embedding_model=lemonade_embedding_model,
                concurrency_limit=embedding_concurrency,
            )

        created: list[ConsumerConfig] = []
        if users:
            for user_cfg in users:
                consumer = self.create_consumer(
                    username=user_cfg.username,
                    api_key=user_cfg.api_key,
                    concurrency_limit=user_cfg.concurrency_limit,
                    token_limit=user_cfg.token_limit,
                    token_window=user_cfg.token_window,
                )
                created.append(consumer)

        return created


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def generate_kilo_gateway_config(
    gateway_url: str,
    api_key: str,
    model: str = "user.gemma-4-31b-it",
    model_checkpoint: str = "unsloth/gemma-4-31B-it-GGUF:Q8_K_XL",
    model_context: int = 262144,
    embedding_model: str = "user.harrier-oss-v1-0.6b",
    enable_embedding: bool = True,
    skeleton_path: Optional[str] = None,
    gateway_mode: str = "per-user",
    chat_models: Optional[list[dict]] = None,
    default_model: Optional[str] = None,
) -> str:
    import sys

    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from app.kilo_config import KiloMode, generate_kilo_config

    kilo_mode = (
        KiloMode.GATEWAY_PER_GROUP
        if gateway_mode == "per-group"
        else KiloMode.GATEWAY_PER_USER
    )
    config = generate_kilo_config(
        mode=kilo_mode,
        base_url=f"{gateway_url}/v1",
        api_key=api_key,
        model_name=model,
        model_checkpoint=model_checkpoint,
        model_context=model_context,
        chat_models=chat_models,
        default_model=default_model,
        embedding_model=embedding_model if enable_embedding else None,
        skeleton_path=skeleton_path,
    )
    return json.dumps(config, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="APISIX AI Gateway manager with rate limiting and per-consumer API keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Setup gateway with users from groups.yaml
  python apisix_gateway.py setup --groups groups.yaml --lemonade-url http://127.0.0.1:13305

  # Setup with Redis-backed rate limiting
  python apisix_gateway.py setup --groups groups.yaml --lemonade-url http://127.0.0.1:13305 --redis-host 127.0.0.1

  # Create a single consumer
  python apisix_gateway.py create-consumer --username alice --concurrency-limit 1

  # Generate kilo.jsonc for a consumer
  python apisix_gateway.py generate-kilo --username alice --api-key alice-key

  # Cleanup all gateway resources
  python apisix_gateway.py cleanup
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    setup_parser = subparsers.add_parser("setup", help="Full gateway setup")
    setup_parser.add_argument("--groups", type=str, help="Path to groups.yaml")
    setup_parser.add_argument("--group", type=str, help="Filter to single group")
    setup_parser.add_argument(
        "--lemonade-url",
        type=str,
        default="http://127.0.0.1:13305",
        help="Lemonade server URL",
    )
    setup_parser.add_argument("--lemonade-api-key", type=str, help="Lemonade API key")
    setup_parser.add_argument(
        "--lemonade-model",
        type=str,
        default="user.gemma-4-31b-it",
        help="Lemonade model name",
    )
    setup_parser.add_argument(
        "--admin-key",
        type=str,
        default=None,
        help="APISIX Admin API key (auto-detected from config if not set)",
    )
    setup_parser.add_argument(
        "--admin-port",
        type=int,
        default=APISIX_ADMIN_PORT_DEFAULT,
        help="APISIX Admin API port",
    )
    setup_parser.add_argument(
        "--proxy-port",
        type=int,
        default=APISIX_PROXY_PORT_DEFAULT,
        help="APISIX proxy port",
    )
    setup_parser.add_argument(
        "--redis-host", type=str, help="Redis host for rate limiting"
    )
    setup_parser.add_argument("--redis-port", type=int, default=6379, help="Redis port")
    setup_parser.add_argument("--redis-password", type=str, help="Redis password")
    setup_parser.add_argument(
        "--concurrency-limit",
        type=int,
        default=CONCURRENCY_LIMIT_DEFAULT,
        help=f"Max concurrent requests per consumer (default: {CONCURRENCY_LIMIT_DEFAULT}, 0=no limit)",
    )
    setup_parser.add_argument(
        "--token-limit",
        type=int,
        default=TOKEN_LIMIT_DEFAULT,
        help=f"Token limit per consumer per time window (default: {TOKEN_LIMIT_DEFAULT} = no token limit)",
    )
    setup_parser.add_argument(
        "--token-window",
        type=int,
        default=TOKEN_WINDOW_DEFAULT,
        help=f"Token limit time window in seconds (default: {TOKEN_WINDOW_DEFAULT})",
    )
    setup_parser.add_argument(
        "--generate-kilo",
        action="store_true",
        help="Generate kilo.jsonc for each consumer",
    )
    setup_parser.add_argument(
        "--per-group",
        action="store_true",
        default=False,
        help="Create one consumer per group with shared API key instead of per user",
    )
    setup_parser.add_argument(
        "--external-ip",
        type=str,
        help="External IP for kilo.jsonc base URL",
    )
    setup_parser.add_argument(
        "--embedding-model",
        type=str,
        default="user.harrier-oss-v1-0.6b",
        help="Embedding model name for Lemonade (default: user.harrier-oss-v1-0.6b)",
    )
    setup_parser.add_argument(
        "--no-embedding",
        action="store_true",
        default=False,
        help="Disable embedding route creation",
    )
    setup_parser.add_argument(
        "--model-route",
        type=str,
        action="append",
        default=None,
        help=(
            "Per-model route with concurrency. Format: short_name:route_uri:concurrency "
            "(e.g. 'gemma-4-31b-it:/v1/chat/completions:1'). "
            "'user.' prefix is added automatically. May be specified multiple times."
        ),
    )

    consumer_parser = subparsers.add_parser(
        "create-consumer", help="Create a single consumer"
    )
    consumer_parser.add_argument("--username", type=str, required=True)
    consumer_parser.add_argument(
        "--api-key", type=str, help="API key (auto-generated if omitted)"
    )
    consumer_parser.add_argument(
        "--concurrency-limit",
        type=int,
        default=CONCURRENCY_LIMIT_DEFAULT,
        help=f"Max concurrent requests (default: {CONCURRENCY_LIMIT_DEFAULT}, 0=no limit)",
    )
    consumer_parser.add_argument(
        "--token-limit",
        type=int,
        default=TOKEN_LIMIT_DEFAULT,
        help=f"Token limit per time window (default: {TOKEN_LIMIT_DEFAULT} = no token limit)",
    )
    consumer_parser.add_argument(
        "--token-window",
        type=int,
        default=TOKEN_WINDOW_DEFAULT,
        help=f"Token limit time window in seconds (default: {TOKEN_WINDOW_DEFAULT})",
    )
    consumer_parser.add_argument("--admin-key", type=str, default=None)
    consumer_parser.add_argument(
        "--admin-port", type=int, default=APISIX_ADMIN_PORT_DEFAULT
    )
    consumer_parser.add_argument("--redis-host", type=str)
    consumer_parser.add_argument("--redis-port", type=int, default=6379)
    consumer_parser.add_argument("--redis-password", type=str)

    delete_parser = subparsers.add_parser("delete-consumer", help="Delete a consumer")
    delete_parser.add_argument("--username", type=str, required=True)
    delete_parser.add_argument("--admin-key", type=str, default=None)
    delete_parser.add_argument(
        "--admin-port", type=int, default=APISIX_ADMIN_PORT_DEFAULT
    )

    kilo_parser = subparsers.add_parser(
        "generate-kilo", help="Generate kilo.jsonc for a consumer"
    )
    kilo_parser.add_argument("--username", type=str, required=True)
    kilo_parser.add_argument("--api-key", type=str, required=True)
    kilo_parser.add_argument(
        "--proxy-port", type=int, default=APISIX_PROXY_PORT_DEFAULT
    )
    kilo_parser.add_argument("--external-ip", type=str, default="127.0.0.1")
    kilo_parser.add_argument("--model", type=str, default="user.gemma-4-31b-it")
    kilo_parser.add_argument(
        "--embedding-model",
        type=str,
        default="user.harrier-oss-v1-0.6b",
        help="Embedding model name for indexing config (default: user.harrier-oss-v1-0.6b)",
    )
    kilo_parser.add_argument(
        "--no-embedding",
        action="store_true",
        default=False,
        help="Omit indexing section from kilo.jsonc",
    )

    status_parser = subparsers.add_parser("status", help="Check gateway status")
    status_parser.add_argument("--admin-key", type=str, default=None)
    status_parser.add_argument(
        "--admin-port", type=int, default=APISIX_ADMIN_PORT_DEFAULT
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Remove all gateway resources"
    )
    cleanup_parser.add_argument("--admin-key", type=str, default=None)
    cleanup_parser.add_argument(
        "--admin-port", type=int, default=APISIX_ADMIN_PORT_DEFAULT
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    def _make_mgr(parsed_args) -> ApisixGatewayManager:
        admin_port = getattr(parsed_args, "admin_port", APISIX_ADMIN_PORT_DEFAULT)
        admin_key = getattr(parsed_args, "admin_key", None)
        return ApisixGatewayManager(
            admin_url=f"http://127.0.0.1:{admin_port}",
            admin_key=admin_key,
            proxy_port=getattr(parsed_args, "proxy_port", APISIX_PROXY_PORT_DEFAULT),
            redis_host=getattr(parsed_args, "redis_host", None),
            redis_port=getattr(parsed_args, "redis_port", 6379),
            redis_password=getattr(parsed_args, "redis_password", None),
        )

    if args.command == "setup":
        import yaml

        mgr = _make_mgr(args)

        users: list[ConsumerConfig] = []
        if args.groups:
            with open(args.groups) as f:
                data = yaml.safe_load(f)
            groups = data.get("groups", {})
        else:
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
                from app.db import get_groups, get_users

                db_path = str(Path.home() / ".thon" / "thon.db")
                db_groups = get_groups(db_path=db_path)
                groups = {}
                for g in db_groups:
                    group_users = get_users(g.id, db_path=db_path)
                    groups[g.name] = {"users": [u.username for u in group_users]}
                if groups:
                    print(f"  Loaded {len(db_groups)} group(s) from DB ({db_path})")
            except Exception as e:
                print(f"  Could not load groups from DB: {e}")
                groups = {}

        if groups:
            if args.per_group:
                for group_name, group_data in groups.items():
                    if args.group and group_name != args.group:
                        continue
                    group_users = group_data.get("users", [])
                    user_count = len(group_users)
                    group_token_limit = (
                        args.token_limit * user_count if args.token_limit > 0 else 0
                    )
                    group_concurrency = (
                        args.concurrency_limit * user_count
                        if args.concurrency_limit > 0
                        else 0
                    )
                    users.append(
                        ConsumerConfig(
                            username=f"group-{group_name}",
                            api_key=secrets.token_urlsafe(24),
                            concurrency_limit=group_concurrency,
                            token_limit=group_token_limit,
                            token_window=args.token_window,
                        )
                    )
            else:
                for group_name, group_data in groups.items():
                    if args.group and group_name != args.group:
                        continue
                    for username in group_data.get("users", []):
                        users.append(
                            ConsumerConfig(
                                username=f"{group_name}-{username}",
                                api_key=secrets.token_urlsafe(24),
                                concurrency_limit=args.concurrency_limit,
                                token_limit=args.token_limit,
                                token_window=args.token_window,
                            )
                        )
        else:
            users.append(
                ConsumerConfig(
                    username="default",
                    api_key=secrets.token_urlsafe(24),
                    concurrency_limit=args.concurrency_limit,
                    token_limit=args.token_limit,
                    token_window=args.token_window,
                )
            )

        mode_label = "per-group" if args.per_group else "per-user"
        print(
            f"[Gateway] Setting up AI gateway ({mode_label}) with {len(users)} consumer(s)..."
        )

        model_routes: Optional[list[ModelRouteConfig]] = None
        if args.model_route:
            model_routes = []
            for spec in args.model_route:
                parts = spec.split(":")
                if len(parts) < 3:
                    print(f"[Gateway] Warning: Ignoring invalid --model-route '{spec}' (expected short_name:uri:concurrency)")
                    continue
                short_name = parts[0]
                route_uri = parts[1]
                try:
                    concurrency = int(parts[2])
                except ValueError:
                    print(f"[Gateway] Warning: Invalid concurrency in --model-route '{spec}'")
                    continue
                prefixed_model = f"user.{short_name}" if not short_name.startswith("user.") else short_name
                suffix = short_name.replace(".", "-")
                if route_uri == "/v1/embeddings":
                    suffix = f"embedding-{suffix}"
                model_routes.append(
                    ModelRouteConfig(
                        model=prefixed_model,
                        route_uri=route_uri,
                        concurrency_limit=concurrency,
                        route_id_suffix=suffix,
                    )
                )

        created = mgr.setup_gateway(
            lemonade_url=args.lemonade_url,
            users=users,
            lemonade_api_key=args.lemonade_api_key,
            lemonade_model=args.lemonade_model,
            lemonade_embedding_model=args.embedding_model,
            enable_embedding=not args.no_embedding,
            model_routes=model_routes,
        )

        print("\n" + "=" * 70)
        print("AI Gateway - Consumer API Keys")
        print("=" * 70)

        ext_ip = args.external_ip or "127.0.0.1"
        gateway_base = f"http://{ext_ip}:{args.proxy_port}"

        for consumer in created:
            print(f"\n  Consumer: {consumer.username}")
            print(f"    API Key: {consumer.api_key}")
            limits_parts = []
            if consumer.concurrency_limit > 0:
                limits_parts.append(f"concurrency={consumer.concurrency_limit}")
            if consumer.token_limit > 0:
                limits_parts.append(
                    f"tokens={consumer.token_limit}/{consumer.token_window}s"
                )
            limits_str = ", ".join(limits_parts) if limits_parts else "no limits"
            print(f"    Limits: {limits_str}")
            print(f"    Chat Endpoint: {gateway_base}/v1/chat/completions")
            if not args.no_embedding:
                print(f"    Embedding Endpoint: {gateway_base}/v1/embeddings")

            if args.generate_kilo:
                kilo_config = generate_kilo_gateway_config(
                    gateway_url=gateway_base,
                    api_key=consumer.api_key,
                    model=args.lemonade_model,
                    embedding_model=args.embedding_model,
                    enable_embedding=not args.no_embedding,
                )
                kilo_path = f"kilo-{consumer.username}.json"
                Path(kilo_path).write_text(kilo_config)
                print(f"    Kilo Config: {kilo_path}")

        print()

    elif args.command == "create-consumer":
        mgr = _make_mgr(args)
        consumer = mgr.create_consumer(
            username=args.username,
            api_key=args.api_key,
            concurrency_limit=args.concurrency_limit,
            token_limit=args.token_limit,
            token_window=args.token_window,
        )
        print(f"\n  Consumer: {consumer.username}")
        print(f"  API Key: {consumer.api_key}")
        limits_parts = []
        if consumer.concurrency_limit > 0:
            limits_parts.append(f"concurrency={consumer.concurrency_limit}")
        if consumer.token_limit > 0:
            limits_parts.append(
                f"tokens={consumer.token_limit}/{consumer.token_window}s"
            )
        limits_str = ", ".join(limits_parts) if limits_parts else "no limits"
        print(f"  Limits: {limits_str}")

    elif args.command == "delete-consumer":
        mgr = _make_mgr(args)
        mgr.delete_consumer(args.username)

    elif args.command == "generate-kilo":
        gateway_url = f"http://{args.external_ip}:{args.proxy_port}"
        config = generate_kilo_gateway_config(
            gateway_url=gateway_url,
            api_key=args.api_key,
            model=args.model,
            embedding_model=args.embedding_model,
            enable_embedding=not args.no_embedding,
        )
        print(config)

    elif args.command == "status":
        mgr = _make_mgr(args)
        status = mgr.get_status()
        print(f"  Running: {status.running}")
        print(f"  Admin URL: {status.admin_url}")
        print(f"  Proxy URL: {status.proxy_url}")
        print(f"  Consumers: {status.consumers_count}")
        print(f"  Route configured: {status.route_configured}")
        print(f"  Redis: {'connected' if status.redis_connected else 'not configured'}")

    elif args.command == "cleanup":
        mgr = _make_mgr(args)
        mgr.cleanup()


if __name__ == "__main__":
    main()
