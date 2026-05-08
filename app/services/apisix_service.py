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

"""APISIX AI Gateway service for the dashboard.

Wraps the APISIX Admin API to provide gateway status monitoring,
consumer management, and rate limit configuration.
"""

import json
import logging
import secrets
import subprocess
import urllib.error
import urllib.request
from typing import Optional

from app.config import GatewayConfig
from app.exceptions import GatewayConnectionError, GatewayNotEnabledError
from app.models import ConsumerInfo, GatewayMode, GatewayStatus

logger = logging.getLogger(__name__)

APISIX_ROUTE_ID = "ai-gateway-route"
LEMONADE_INSTANCE_NAME = "lemonade-instance"


class ApisixService:
    """Service for interacting with the APISIX AI Gateway.

    Provides read/write access to APISIX Admin API for:
    - Gateway status monitoring
    - Consumer CRUD with key-auth and ai-rate-limiting
    - AI route management with ai-proxy-multi
    """

    def __init__(self, config: GatewayConfig) -> None:
        self._cfg = config

    @property
    def _admin_url(self) -> str:
        return self._cfg.admin_url.rstrip("/")

    @property
    def proxy_url(self) -> str:
        host = self._cfg.admin_url.split("//", 1)[1].split(":")[0]
        return f"http://{host}:{self._cfg.proxy_port}"

    def _check_enabled(self) -> None:
        if not self._cfg.enabled:
            raise GatewayNotEnabledError(
                "AI Gateway is not enabled. Set GATEWAY_ENABLED=true to enable."
            )

    def _request(
        self,
        path: str,
        method: str = "GET",
        data: Optional[dict] = None,
    ) -> dict:
        url = f"{self._admin_url}/apisix/admin{path}"
        body = json.dumps(data).encode() if data else None

        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("X-API-KEY", self._cfg.admin_key)
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                response_data = resp.read().decode()
                return json.loads(response_data) if response_data else {}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise GatewayConnectionError(
                f"APISIX Admin API error {e.code} for {method} {path}: {error_body}"
            ) from e
        except urllib.error.URLError as e:
            raise GatewayConnectionError(
                f"Cannot connect to APISIX Admin API at {self._admin_url}: {e}"
            ) from e

    def is_running(self) -> bool:
        if not self._cfg.enabled:
            return False
        try:
            self._request("/routes")
            return True
        except GatewayConnectionError:
            return False

    def is_installed(self) -> bool:
        try:
            result = subprocess.run(
                ["which", "apisix"],
                capture_output=True,
                check=False,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def get_status(self) -> GatewayStatus:
        enabled = self._cfg.enabled
        if not enabled:
            return GatewayStatus(
                enabled=False,
                admin_url=self._admin_url,
                proxy_url=self.proxy_url,
            )

        running = False
        consumers_count = 0
        route_configured = False

        try:
            running = self.is_running()
        except Exception:
            pass

        if running:
            try:
                result = self._request("/consumers")
                consumers_count = (
                    result.get("total", 0) if isinstance(result, dict) else 0
                )
            except GatewayConnectionError:
                pass
            try:
                self._request(f"/routes/{APISIX_ROUTE_ID}")
                route_configured = True
            except GatewayConnectionError:
                pass

        mode = (
            GatewayMode.PER_GROUP
            if self._cfg.gateway_mode == "per-group"
            else GatewayMode.PER_USER
        )

        return GatewayStatus(
            running=running,
            admin_url=self._admin_url,
            proxy_url=self.proxy_url,
            consumers_count=consumers_count,
            route_configured=route_configured,
            redis_connected=self._cfg.redis_host is not None,
            enabled=True,
            mode=mode,
        )

    def list_consumers(self) -> list[ConsumerInfo]:
        self._check_enabled()
        try:
            result = self._request("/consumers")
            if isinstance(result, dict) and "list" in result:
                consumers = []
                for item in result["list"]:
                    value = item.get("value", {})
                    username = value.get("username", "")
                    plugins = value.get("plugins", {})
                    key_auth = plugins.get("key-auth", {})
                    rate_limiting = plugins.get("ai-rate-limiting", {})
                    instances = rate_limiting.get("instances", [])

                    rate_limit = 0
                    time_window = 0
                    if instances:
                        rate_limit = instances[0].get("limit", 0)
                        time_window = instances[0].get("time_window", 0)

                    consumers.append(
                        ConsumerInfo(
                            username=username,
                            api_key=key_auth.get("key", ""),
                            rate_limit=rate_limit,
                            time_window=time_window,
                        )
                    )
                return consumers
            return []
        except GatewayConnectionError:
            return []

    def create_consumer(
        self,
        username: str,
        api_key: Optional[str] = None,
        rate_limit: Optional[int] = None,
        time_window: Optional[int] = None,
    ) -> ConsumerInfo:
        self._check_enabled()
        api_key = api_key or secrets.token_urlsafe(24)
        rate_limit = rate_limit or self._cfg.rate_limit_tokens
        time_window = time_window or self._cfg.rate_limit_window

        rate_limit_config: dict = {
            "policy": "redis" if self._cfg.redis_host else "local",
            "limit_strategy": "total_tokens",
            "instances": [
                {
                    "name": LEMONADE_INSTANCE_NAME,
                    "limit": rate_limit,
                    "time_window": time_window,
                }
            ],
            "rejected_code": 429,
        }

        if self._cfg.redis_host:
            rate_limit_config["redis_host"] = self._cfg.redis_host
            rate_limit_config["redis_port"] = self._cfg.redis_port
            if self._cfg.redis_password:
                rate_limit_config["redis_password"] = self._cfg.redis_password

        consumer_data = {
            "username": username,
            "plugins": {
                "key-auth": {"key": api_key},
                "ai-rate-limiting": rate_limit_config,
            },
        }

        self._request("/consumers", method="PUT", data=consumer_data)
        logger.info("Created gateway consumer: %s", username)

        return ConsumerInfo(
            username=username,
            api_key=api_key,
            rate_limit=rate_limit,
            time_window=time_window,
        )

    def delete_consumer(self, username: str) -> None:
        self._check_enabled()
        self._request(f"/consumers/{username}", method="DELETE")
        logger.info("Deleted gateway consumer: %s", username)

    def create_ai_route(
        self,
        lemonade_url: str,
        lemonade_api_key: Optional[str] = None,
        lemonade_model: str = "user.gemma-4-31b-it",
        uri: str = "/v1/chat/completions",
    ) -> dict:
        self._check_enabled()

        instance_config: dict = {
            "name": LEMONADE_INSTANCE_NAME,
            "provider": "openai-compatible",
            "weight": 100,
            "override": {"endpoint": lemonade_url},
            "options": {"model": lemonade_model},
        }
        if lemonade_api_key:
            instance_config["auth"] = {
                "header": {"Authorization": f"Bearer {lemonade_api_key}"}
            }

        route_data: dict = {
            "uri": uri,
            "methods": ["POST"],
            "plugins": {
                "key-auth": {},
                "ai-proxy-multi": {"instances": [instance_config]},
            },
        }

        result = self._request(
            f"/routes/{APISIX_ROUTE_ID}", method="PUT", data=route_data
        )
        logger.info("Created AI route: %s -> %s", uri, lemonade_url)
        return result

    def delete_ai_route(self) -> None:
        self._check_enabled()
        try:
            self._request(f"/routes/{APISIX_ROUTE_ID}", method="DELETE")
            logger.info("Deleted AI route: %s", APISIX_ROUTE_ID)
        except GatewayConnectionError as e:
            logger.warning("Could not delete AI route: %s", e)

    def setup_gateway(
        self,
        lemonade_url: str,
        lemonade_api_key: Optional[str] = None,
        lemonade_model: str = "user.gemma-4-31b-it",
        usernames: Optional[list[str]] = None,
        rate_limit: Optional[int] = None,
        time_window: Optional[int] = None,
    ) -> list[ConsumerInfo]:
        self._check_enabled()

        self.create_ai_route(
            lemonade_url=lemonade_url,
            lemonade_api_key=lemonade_api_key,
            lemonade_model=lemonade_model,
        )

        consumers: list[ConsumerInfo] = []
        if usernames:
            for username in usernames:
                consumer = self.create_consumer(
                    username=username,
                    rate_limit=rate_limit,
                    time_window=time_window,
                )
                consumers.append(consumer)

        return consumers

    def setup_gateway_groups(
        self,
        lemonade_url: str,
        lemonade_api_key: Optional[str] = None,
        lemonade_model: str = "user.gemma-4-31b-it",
        groups: Optional[list[tuple[str, int]]] = None,
        rate_limit_per_user: Optional[int] = None,
        time_window: Optional[int] = None,
    ) -> list[ConsumerInfo]:
        self._check_enabled()

        self.create_ai_route(
            lemonade_url=lemonade_url,
            lemonade_api_key=lemonade_api_key,
            lemonade_model=lemonade_model,
        )

        consumers: list[ConsumerInfo] = []
        if groups:
            for group_name, user_count in groups:
                effective_rate_limit = (
                    rate_limit_per_user or self._cfg.rate_limit_tokens
                ) * user_count
                effective_time_window = time_window or self._cfg.rate_limit_window
                consumer = self.create_consumer(
                    username=f"group-{group_name}",
                    rate_limit=effective_rate_limit,
                    time_window=effective_time_window,
                )
                consumers.append(
                    ConsumerInfo(
                        username=consumer.username,
                        api_key=consumer.api_key,
                        rate_limit=effective_rate_limit,
                        time_window=effective_time_window,
                        group_name=group_name,
                        user_count=user_count,
                    )
                )

        return consumers

    def cleanup(self) -> None:
        if not self._cfg.enabled:
            return
        try:
            consumers = self.list_consumers()
            for consumer in consumers:
                try:
                    self.delete_consumer(consumer.username)
                except GatewayConnectionError as e:
                    logger.warning(
                        "Could not delete consumer %s: %s", consumer.username, e
                    )
            self.delete_ai_route()
            logger.info("Gateway cleanup complete")
        except GatewayConnectionError as e:
            logger.warning("Gateway cleanup failed: %s", e)
