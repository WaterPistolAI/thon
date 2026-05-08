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

"""Lemonade inference server service wrapper."""

import json
import logging
import re
import subprocess
import urllib.error
import urllib.request
from typing import Optional

from app.config import LemonadeConfig
from app.exceptions import LemonadeConnectionError
from app.models import LemonadeStatus

logger = logging.getLogger(__name__)

LEMONADE_DEFAULT_MODEL = "unsloth/gemma-4-31B-it-GGUF:Q8_K_XL"
LEMONADE_DEFAULT_MODEL_NAME = "gemma-4-31b-it"


class LemonadeService:
    """Manages interaction with the local Lemonade inference server.

    Provides status monitoring, model management, and configuration
    introspection.  Also proxies requests to the Lemonade REST and
    llama.cpp-specific APIs (health, stats, system-info, slots, pull,
    load, unload, etc.).
    """

    def __init__(self, config: LemonadeConfig) -> None:
        self._cfg = config

    @property
    def endpoint(self) -> str:
        host = "localhost" if self._cfg.host == "0.0.0.0" else self._cfg.host
        return f"http://{host}:{self._cfg.port}"

    def is_installed(self) -> bool:
        for cmd in ("lemonade-server", "lemonade"):
            try:
                result = subprocess.run(
                    ["which", cmd], capture_output=True, check=False
                )
                if result.returncode == 0:
                    return True
            except FileNotFoundError:
                continue
        return False

    def get_status(self) -> LemonadeStatus:
        """Return a snapshot of the Lemonade server status."""
        running = self._check_running()
        model = ""
        ctx_size = 0
        num_users = 0
        api_key_configured = bool(self._cfg.api_key or self._cfg.admin_api_key)

        if running:
            model_info = self._read_model_config()
            if model_info:
                model = model_info.get("model", LEMONADE_DEFAULT_MODEL_NAME)
                ctx_size = model_info.get("ctx_size", 0)
                num_users = model_info.get("num_users", 0)

        return LemonadeStatus(
            running=running,
            endpoint=self.endpoint,
            model=model,
            api_key_configured=api_key_configured,
            ctx_size=ctx_size,
            num_users=num_users,
        )

    def _check_running(self) -> bool:
        try:
            url = f"{self.endpoint}/v1/models"
            req = urllib.request.Request(url, method="GET")
            req.add_header("Content-Type", "application/json")
            key = self._cfg.admin_api_key or self._cfg.api_key
            if key:
                req.add_header("Authorization", f"Bearer {key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def _read_model_config(self) -> Optional[dict]:
        recipe_path = self._cfg.config_dir / "recipe_options.json"
        try:
            data = json.loads(recipe_path.read_text())
            for key, val in data.items():
                if key.startswith("user."):
                    llamacpp_args = val.get("llamacpp_args", "")
                    np_match = re.search(r"-np\s+(\d+)", llamacpp_args)
                    return {
                        "model": key.removeprefix("user."),
                        "ctx_size": val.get("ctx_size", 0),
                        "num_users": int(np_match.group(1)) if np_match else 1,
                    }
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            pass
        return None

    def list_models(self) -> list[dict]:
        """List available models from user_models.json."""
        models_path = self._cfg.config_dir / "user_models.json"
        try:
            data = json.loads(models_path.read_text())
            return [{"name": k, **v} for k, v in data.items()]
        except (FileNotFoundError, json.JSONDecodeError, PermissionError):
            return []

    def get_api_info(self) -> dict:
        """Return API endpoint info for dashboard display."""
        return {
            "endpoint": self.endpoint,
            "openai_compatible": f"{self.endpoint}/v1",
            "has_api_key": bool(self._cfg.api_key),
            "has_admin_key": bool(self._cfg.admin_api_key),
            "installed": self.is_installed(),
        }

    # ── Generic HTTP helpers ──────────────────────────────────────────

    def _build_request(
        self,
        path: str,
        method: str = "GET",
        body: Optional[bytes] = None,
        timeout: int = 30,
    ) -> urllib.request.Request:
        url = f"{self.endpoint}{path}"
        req = urllib.request.Request(url, method=method, data=body)
        req.add_header("Content-Type", "application/json")
        key = self._cfg.admin_api_key or self._cfg.api_key
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        return req

    def _proxy_get(self, path: str, timeout: int = 30) -> dict:
        req = self._build_request(path, method="GET", timeout=timeout)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode()
            except Exception:
                pass
            raise LemonadeConnectionError(
                f"Lemonade returned {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise LemonadeConnectionError(
                f"Cannot reach Lemonade at {self.endpoint}: {exc}"
            ) from exc

    def _proxy_post(
        self,
        path: str,
        payload: Optional[dict] = None,
        timeout: int = 120,
    ) -> dict:
        body = json.dumps(payload).encode() if payload else None
        req = self._build_request(path, method="POST", body=body, timeout=timeout)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode()
            except Exception:
                pass
            raise LemonadeConnectionError(
                f"Lemonade returned {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise LemonadeConnectionError(
                f"Cannot reach Lemonade at {self.endpoint}: {exc}"
            ) from exc

    # ── Lemonade REST API proxies ─────────────────────────────────────

    def health(self) -> dict:
        """GET /v1/health — server health, loaded models, max_models."""
        return self._proxy_get("/v1/health")

    def stats(self) -> dict:
        """GET /v1/stats — performance statistics from the last request."""
        return self._proxy_get("/v1/stats")

    def system_info(self) -> dict:
        """GET /v1/system-info — hardware details and device enumeration."""
        return self._proxy_get("/v1/system-info")

    def pull(self, body: dict) -> dict:
        """POST /v1/pull — install / register-and-install a model."""
        return self._proxy_post("/v1/pull", body, timeout=600)

    def pull_variants(self, checkpoint: str) -> dict:
        """GET /v1/pull/variants — enumerate GGUF variants for a checkpoint."""
        from urllib.parse import quote

        path = f"/v1/pull/variants?checkpoint={quote(checkpoint, safe='')}"
        return self._proxy_get(path)

    def delete(self, body: dict) -> dict:
        """POST /v1/delete — delete a model from local storage."""
        return self._proxy_post("/v1/delete", body)

    def load(self, body: dict) -> dict:
        """POST /v1/load — load a model into memory."""
        return self._proxy_post("/v1/load", body, timeout=300)

    def unload(self, body: Optional[dict] = None) -> dict:
        """POST /v1/unload — unload a model from memory."""
        return self._proxy_post("/v1/unload", body)

    def install_backend(self, body: dict) -> dict:
        """POST /v1/install — install or update a backend."""
        return self._proxy_post("/v1/install", body, timeout=600)

    def uninstall_backend(self, body: dict) -> dict:
        """POST /v1/uninstall — remove a backend."""
        return self._proxy_post("/v1/uninstall", body)

    def liveness(self) -> dict:
        """GET /live — lightweight liveness probe."""
        return self._proxy_get("/live")

    # ── llama.cpp-specific API proxies ────────────────────────────────

    def slots(self) -> list[dict]:
        """GET /v1/slots — current slots processing state."""
        result = self._proxy_get("/v1/slots")
        return result if isinstance(result, list) else [result]

    def slot_action(
        self, slot_id: int, action: str, body: Optional[dict] = None
    ) -> dict:
        """POST /v1/slots/{id}?action=save|restore|erase — slot cache ops."""
        path = f"/v1/slots/{slot_id}?action={action}"
        return self._proxy_post(path, body)
