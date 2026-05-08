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

Usage:
    from apisix_gateway import ApisixGatewayManager

    mgr = ApisixGatewayManager(admin_url="http://127.0.0.1:9180", admin_key="edd1c9f034335f136f87ad84b625c8f1")
    mgr.create_consumer(username="alice", api_key="alice-key-123", rate_limit=500, time_window=60)
    mgr.create_ai_route(lemonade_url="http://127.0.0.1:13305", lemonade_api_key="sk-xxx")
    mgr.setup_gateway(lemonade_url="http://127.0.0.1:13305", users=[...])
"""

import argparse
import json
import logging
import secrets
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

APISIX_ADMIN_API_KEY_DEFAULT = "edd1c9f034335f136f87ad84b625c8f1"
APISIX_ADMIN_PORT_DEFAULT = 9180
APISIX_PROXY_PORT_DEFAULT = 9080
APISIX_ROUTE_ID = "ai-gateway-route"
LEMONADE_INSTANCE_NAME = "lemonade-instance"
RATE_LIMIT_TOKENS_DEFAULT = 500
RATE_LIMIT_WINDOW_DEFAULT = 60


@dataclass
class ConsumerConfig:
    username: str
    api_key: str
    rate_limit: int = RATE_LIMIT_TOKENS_DEFAULT
    time_window: int = RATE_LIMIT_WINDOW_DEFAULT


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
        admin_key: str = APISIX_ADMIN_API_KEY_DEFAULT,
        proxy_port: int = APISIX_PROXY_PORT_DEFAULT,
        redis_host: Optional[str] = None,
        redis_port: int = 6379,
        redis_password: Optional[str] = None,
        lemonade_api_key: Optional[str] = None,
    ) -> None:
        self._admin_url = admin_url.rstrip("/")
        self._admin_key = admin_key
        self._proxy_port = proxy_port
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._redis_password = redis_password
        self._lemonade_api_key = lemonade_api_key

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
        rate_limit: int = RATE_LIMIT_TOKENS_DEFAULT,
        time_window: int = RATE_LIMIT_WINDOW_DEFAULT,
        lemonade_instance_name: str = LEMONADE_INSTANCE_NAME,
    ) -> ConsumerConfig:
        api_key = api_key or secrets.token_urlsafe(24)

        rate_limit_config: dict = {
            "policy": "redis" if self._redis_host else "local",
            "limit_strategy": "total_tokens",
            "instances": [
                {
                    "name": lemonade_instance_name,
                    "limit": rate_limit,
                    "time_window": time_window,
                }
            ],
            "rejected_code": 429,
        }

        if self._redis_host:
            rate_limit_config["redis_host"] = self._redis_host
            rate_limit_config["redis_port"] = self._redis_port
            if self._redis_password:
                rate_limit_config["redis_password"] = self._redis_password

        consumer_data = {
            "username": username,
            "plugins": {
                "key-auth": {"key": api_key},
                "ai-rate-limiting": rate_limit_config,
            },
        }

        self._request("/consumers", method="PUT", data=consumer_data)
        print(
            f"[Gateway] Created consumer: {username} (rate limit: {rate_limit} tokens/{time_window}s)"
        )

        return ConsumerConfig(
            username=username,
            api_key=api_key,
            rate_limit=rate_limit,
            time_window=time_window,
        )

    def delete_consumer(self, username: str) -> None:
        self._request(f"/consumers/{username}", method="DELETE")
        print(f"[Gateway] Deleted consumer: {username}")

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
    ) -> dict:
        effective_key = lemonade_api_key or self._lemonade_api_key
        route_data: dict = {
            "uri": uri,
            "methods": ["POST"],
            "plugins": {
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
                                "header": {
                                    "Authorization": f"Bearer {effective_key}",
                                }
                            }
                            if effective_key
                            else {},
                            "options": {
                                "model": lemonade_model,
                            },
                        }
                    ]
                },
            },
        }

        result = self._request(
            f"/routes/{APISIX_ROUTE_ID}", method="PUT", data=route_data
        )
        print(f"[Gateway] Created AI route: {uri} -> {lemonade_url}")
        return result

    def delete_ai_route(self) -> None:
        try:
            self._request(f"/routes/{APISIX_ROUTE_ID}", method="DELETE")
            print(f"[Gateway] Deleted AI route: {APISIX_ROUTE_ID}")
        except RuntimeError as e:
            print(f"[Gateway] Warning: Could not delete route: {e}")

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

        self.delete_ai_route()
        print("[Gateway] Cleanup complete")

    def setup_gateway(
        self,
        lemonade_url: str,
        users: Optional[list[ConsumerConfig]] = None,
        lemonade_api_key: Optional[str] = None,
        lemonade_model: str = "user.gemma-4-31b-it",
        route_uri: str = "/v1/chat/completions",
    ) -> list[ConsumerConfig]:
        self.create_ai_route(
            lemonade_url=lemonade_url,
            lemonade_api_key=lemonade_api_key,
            lemonade_model=lemonade_model,
            uri=route_uri,
        )

        created: list[ConsumerConfig] = []
        if users:
            for user_cfg in users:
                consumer = self.create_consumer(
                    username=user_cfg.username,
                    api_key=user_cfg.api_key,
                    rate_limit=user_cfg.rate_limit,
                    time_window=user_cfg.time_window,
                )
                created.append(consumer)

        return created


def generate_kilo_gateway_config(
    gateway_url: str,
    api_key: str,
    model: str = "user.gemma-4-31b-it",
) -> str:
    config = {
        "providers": {
            "lemonade-gateway": {
                "baseUrl": gateway_url,
                "apiKey": api_key,
            }
        },
        "models": {
            "gemma-4-31b-it": {
                "provider": "lemonade-gateway",
                "modelId": model,
            }
        },
    }
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
  python apisix_gateway.py create-consumer --username alice --rate-limit 500

  # Generate kilo.json for a consumer
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
        default=APISIX_ADMIN_API_KEY_DEFAULT,
        help="APISIX Admin API key",
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
        "--rate-limit",
        type=int,
        default=RATE_LIMIT_TOKENS_DEFAULT,
        help=f"Token limit per consumer per time window (default: {RATE_LIMIT_TOKENS_DEFAULT})",
    )
    setup_parser.add_argument(
        "--time-window",
        type=int,
        default=RATE_LIMIT_WINDOW_DEFAULT,
        help=f"Rate limit time window in seconds (default: {RATE_LIMIT_WINDOW_DEFAULT})",
    )
    setup_parser.add_argument(
        "--generate-kilo",
        action="store_true",
        help="Generate kilo.json for each consumer",
    )
    setup_parser.add_argument(
        "--external-ip",
        type=str,
        help="External IP for kilo.json base URL",
    )

    consumer_parser = subparsers.add_parser(
        "create-consumer", help="Create a single consumer"
    )
    consumer_parser.add_argument("--username", type=str, required=True)
    consumer_parser.add_argument(
        "--api-key", type=str, help="API key (auto-generated if omitted)"
    )
    consumer_parser.add_argument(
        "--rate-limit", type=int, default=RATE_LIMIT_TOKENS_DEFAULT
    )
    consumer_parser.add_argument(
        "--time-window", type=int, default=RATE_LIMIT_WINDOW_DEFAULT
    )
    consumer_parser.add_argument(
        "--admin-key", type=str, default=APISIX_ADMIN_API_KEY_DEFAULT
    )
    consumer_parser.add_argument(
        "--admin-port", type=int, default=APISIX_ADMIN_PORT_DEFAULT
    )
    consumer_parser.add_argument("--redis-host", type=str)
    consumer_parser.add_argument("--redis-port", type=int, default=6379)
    consumer_parser.add_argument("--redis-password", type=str)

    delete_parser = subparsers.add_parser("delete-consumer", help="Delete a consumer")
    delete_parser.add_argument("--username", type=str, required=True)
    delete_parser.add_argument(
        "--admin-key", type=str, default=APISIX_ADMIN_API_KEY_DEFAULT
    )
    delete_parser.add_argument(
        "--admin-port", type=int, default=APISIX_ADMIN_PORT_DEFAULT
    )

    kilo_parser = subparsers.add_parser(
        "generate-kilo", help="Generate kilo.json for a consumer"
    )
    kilo_parser.add_argument("--username", type=str, required=True)
    kilo_parser.add_argument("--api-key", type=str, required=True)
    kilo_parser.add_argument(
        "--proxy-port", type=int, default=APISIX_PROXY_PORT_DEFAULT
    )
    kilo_parser.add_argument("--external-ip", type=str, default="127.0.0.1")
    kilo_parser.add_argument("--model", type=str, default="user.gemma-4-31b-it")

    status_parser = subparsers.add_parser("status", help="Check gateway status")
    status_parser.add_argument(
        "--admin-key", type=str, default=APISIX_ADMIN_API_KEY_DEFAULT
    )
    status_parser.add_argument(
        "--admin-port", type=int, default=APISIX_ADMIN_PORT_DEFAULT
    )

    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Remove all gateway resources"
    )
    cleanup_parser.add_argument(
        "--admin-key", type=str, default=APISIX_ADMIN_API_KEY_DEFAULT
    )
    cleanup_parser.add_argument(
        "--admin-port", type=int, default=APISIX_ADMIN_PORT_DEFAULT
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    def _make_mgr(parsed_args) -> ApisixGatewayManager:
        admin_port = getattr(parsed_args, "admin_port", APISIX_ADMIN_PORT_DEFAULT)
        admin_key = getattr(parsed_args, "admin_key", APISIX_ADMIN_API_KEY_DEFAULT)
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
            for group_name, group_data in groups.items():
                if args.group and group_name != args.group:
                    continue
                for username in group_data.get("users", []):
                    users.append(
                        ConsumerConfig(
                            username=f"{group_name}-{username}",
                            api_key=secrets.token_urlsafe(24),
                            rate_limit=args.rate_limit,
                            time_window=args.time_window,
                        )
                    )
        else:
            users.append(
                ConsumerConfig(
                    username="default",
                    api_key=secrets.token_urlsafe(24),
                    rate_limit=args.rate_limit,
                    time_window=args.time_window,
                )
            )

        print(f"[Gateway] Setting up AI gateway with {len(users)} consumer(s)...")
        created = mgr.setup_gateway(
            lemonade_url=args.lemonade_url,
            users=users,
            lemonade_api_key=args.lemonade_api_key,
            lemonade_model=args.lemonade_model,
        )

        print("\n" + "=" * 70)
        print("AI Gateway - Consumer API Keys")
        print("=" * 70)

        ext_ip = args.external_ip or "127.0.0.1"
        gateway_base = f"http://{ext_ip}:{args.proxy_port}"

        for consumer in created:
            print(f"\n  Consumer: {consumer.username}")
            print(f"    API Key: {consumer.api_key}")
            print(
                f"    Rate Limit: {consumer.rate_limit} tokens / {consumer.time_window}s"
            )
            print(f"    Endpoint: {gateway_base}/v1/chat/completions")

            if args.generate_kilo:
                kilo_config = generate_kilo_gateway_config(
                    gateway_url=gateway_base,
                    api_key=consumer.api_key,
                    model=args.lemonade_model,
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
            rate_limit=args.rate_limit,
            time_window=args.time_window,
        )
        print(f"\n  Consumer: {consumer.username}")
        print(f"  API Key: {consumer.api_key}")
        print(f"  Rate Limit: {consumer.rate_limit} tokens / {consumer.time_window}s")

    elif args.command == "delete-consumer":
        mgr = _make_mgr(args)
        mgr.delete_consumer(args.username)

    elif args.command == "generate-kilo":
        gateway_url = f"http://{args.external_ip}:{args.proxy_port}"
        config = generate_kilo_gateway_config(
            gateway_url=gateway_url,
            api_key=args.api_key,
            model=args.model,
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
