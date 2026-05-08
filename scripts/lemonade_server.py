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

"""
Lemonade Server Manager forTHON Example

Installs, configures, and manages a local Lemonade inference server
that provides LLM endpoints for VS Code extensions in sandbox instances.

The server runs on the host machine and exposes an OpenAI-compatible API
that VS Code extensions (Continue, Cline, etc.) inside sandbox containers
can connect to. Bridge/host networking is handled by the separate main.py
orchestrator; this script only manages the Lemonade server lifecycle.

Usage:
    # One-time installation
    python lemonade_server.py install

    # Configure server settings
    python lemonade_server.py configure --host 0.0.0.0 --port 13305 --generate-keys

    # Start the server
    python lemonade_server.py start

    # Pull a model
    python lemonade_server.py pull --model Gemma-3-4b-it-GGUF

    # Full setup (install + configure + start + pull model)
    python lemonade_server.py run --num-users 4 --external-ip 1.2.3.4

    # Check server status
    python lemonade_server.py status

    # Stop the server
    python lemonade_server.py stop

    # Cleanup
    python lemonade_server.py cleanup
"""

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import yaml

LEMONADE_CONFIG_DIR = Path("/var/lib/lemonade/.cache/lemonade")
LEMONADE_CONFIG_PATH = LEMONADE_CONFIG_DIR / "config.json"
SYSTEMD_SERVICE_NAME = "lemonade-server"
SYSTEMD_OVERRIDE_DIR = Path(
    f"/etc/systemd/system/{SYSTEMD_SERVICE_NAME}.service.d"
)
DEFAULT_MODEL = "unsloth/gemma-4-31B-it-GGUF:Q8_K_XL"
DEFAULT_MODEL_NAME = "gemma-4-31b-it"
DEFAULT_MMPROJ = "mmproj-BF16.gguf"
DEFAULT_PORT = 13305
DEFAULT_HOST = "0.0.0.0"
PER_USER_CTX = 262144

DEFAULT_LLMACPP_BIN = "/usr/local/bin/llama-server"

LLAMACPP_DEFAULTS: dict = {
    "backend": "auto",
    "args": "",
    "prefer_system": True,
    "rocm_bin": DEFAULT_LLMACPP_BIN,
    "vulkan_bin": DEFAULT_LLMACPP_BIN,
    "cpu_bin": DEFAULT_LLMACPP_BIN,
}
WHISPERCPP_DEFAULTS: dict = {
    "backend": "auto",
    "args": "",
    "cpu_bin": "builtin",
    "npu_bin": "builtin",
}
SDCPP_DEFAULTS: dict = {
    "backend": "auto",
    "args": "",
    "steps": 20,
    "cfg_scale": 7.0,
    "width": 512,
    "height": 512,
    "cpu_bin": "builtin",
    "rocm_bin": "builtin",
    "vulkan_bin": "builtin",
}


def generate_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)


def _needs_sudo() -> bool:
    try:
        return os.geteuid() != 0
    except AttributeError:
        return False


def _run_cmd(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    sudo: bool = False,
) -> subprocess.CompletedProcess[str]:
    if sudo and _needs_sudo():
        cmd = ["sudo", *cmd]
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        check=check,
    )


def _sudo_write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    except PermissionError:
        _run_cmd(["mkdir", "-p", str(path.parent)], sudo=True)
        tmp_path = Path(f"/tmp/{path.name}")
        tmp_path.write_text(content)
        _run_cmd(["cp", str(tmp_path), str(path)], sudo=True)
        service_user = _get_lemonade_user()
        _run_cmd(["chown", f"{service_user}:{service_user}", str(path)], sudo=True)
        tmp_path.unlink(missing_ok=True)


def _get_lemonade_user() -> str:
    try:
        result = _run_cmd(
            ["systemctl", "show", SYSTEMD_SERVICE_NAME, "-p", "User", "--value"],
            check=False,
        )
        user = result.stdout.strip()
        if user:
            return user
    except Exception:
        pass
    return "lemonade"


def _sudo_read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        try:
            result = _run_cmd(["cat", str(path)], sudo=True)
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return None


def detect_docker_host_ip() -> Optional[str]:
    """Detect the host IP reachable from Docker containers via the bridge network."""
    try:
        result = _run_cmd(
            ["docker", "network", "inspect", "bridge"],
            check=False,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data:
                gateway = (
                    data[0]
                    .get("IPAM", {})
                    .get("Config", [{}])[0]
                    .get("Gateway")
                )
                if gateway:
                    return gateway
    except Exception:
        pass
    return None


def load_user_count(groups_file: str, group_filter: Optional[str] = None) -> int:
    """Count total users from a groups.yaml file."""
    with open(groups_file) as f:
        data = yaml.safe_load(f)

    groups = data.get("groups", {})
    count = 0
    for group_name, group_data in groups.items():
        if group_filter and group_name != group_filter:
            continue
        count += len(group_data.get("users", []))
    return count


class LemonadeServerManager:
    """Manages installation, configuration, and lifecycle of the Lemonade inference server."""

    def __init__(
        self,
        config_dir: Path = LEMONADE_CONFIG_DIR,
        api_key: Optional[str] = None,
        admin_api_key: Optional[str] = None,
    ):
        self.config_dir = config_dir
        self.config_path = config_dir / "config.json"
        self._api_key = api_key
        self._admin_api_key = admin_api_key

    @property
    def api_key(self) -> str:
        if self._api_key:
            return self._api_key
        return os.getenv("LEMONADE_API_KEY", "")

    @property
    def admin_api_key(self) -> str:
        if self._admin_api_key:
            return self._admin_api_key
        return os.getenv("LEMONADE_ADMIN_API_KEY", "")

    def is_installed(self) -> bool:
        for cmd in ("lemonade-server", "lemonade"):
            result = _run_cmd(["which", cmd], check=False)
            if result.returncode == 0:
                return True
        return False

    def install(self) -> None:
        """Install lemonade-server via PPA and update PCI IDs for GPU detection."""
        if self.is_installed():
            print("[Lemonade] Already installed")
            return

        print("[Lemonade] Installing lemonade-server via PPA...")
        _run_cmd(
            ["add-apt-repository", "-y", "ppa:lemonade-team/stable"], sudo=True
        )
        _run_cmd(["apt-get", "update"], sudo=True)
        _run_cmd(["apt-get", "install", "-y", "lemonade-server"], sudo=True)
        _run_cmd(["update-pciids"], sudo=True, check=False)
        print("[Lemonade] Installation complete")

    def configure(
        self,
        port: int = DEFAULT_PORT,
        host: str = DEFAULT_HOST,
        llamacpp_backend: str = "auto",
        ctx_size: int = 4096,
        max_loaded_models: int = 1,
        generate_keys: bool = False,
        prefer_system: bool = True,
        llamacpp_bin: str = DEFAULT_LLMACPP_BIN,
    ) -> None:
        """Write config.json and optionally set API keys in systemd override."""
        existing = _sudo_read_json(self.config_path) or {}

        config: dict = {
            "config_version": existing.get("config_version", 1),
            "port": port,
            "host": host,
            "log_level": existing.get("log_level", "info"),
            "global_timeout": existing.get("global_timeout", 300),
            "max_loaded_models": max_loaded_models,
            "no_broadcast": existing.get("no_broadcast", False),
            "extra_models_dir": existing.get("extra_models_dir", ""),
            "models_dir": existing.get("models_dir", "auto"),
            "ctx_size": ctx_size,
            "offline": existing.get("offline", False),
            "disable_model_filtering": existing.get(
                "disable_model_filtering", False
            ),
            "enable_dgpu_gtt": existing.get("enable_dgpu_gtt", False),
            "llamacpp": {
                **LLAMACPP_DEFAULTS,
                **existing.get("llamacpp", {}),
                "backend": llamacpp_backend,
                "prefer_system": prefer_system,
                "rocm_bin": llamacpp_bin if prefer_system else "builtin",
                "vulkan_bin": llamacpp_bin if prefer_system else "builtin",
                "cpu_bin": llamacpp_bin if prefer_system else "builtin",
            },
            "whispercpp": {
                **WHISPERCPP_DEFAULTS,
                **existing.get("whispercpp", {}),
            },
            "sdcpp": {
                **SDCPP_DEFAULTS,
                **existing.get("sdcpp", {}),
            },
            "flm": {**{"args": ""}, **existing.get("flm", {})},
            "ryzenai": {
                **{"server_bin": "builtin"},
                **existing.get("ryzenai", {}),
            },
            "kokoro": {**{"cpu_bin": "builtin"}, **existing.get("kokoro", {})},
        }

        _sudo_write_json(self.config_path, config)
        print(f"[Lemonade] Configuration written to {self.config_path}")

        if generate_keys:
            self._configure_api_keys()

    def _configure_api_keys(self) -> tuple[str, str]:
        """Generate API keys and persist them in a systemd override file."""
        api_key = self.api_key or generate_password()
        admin_api_key = self.admin_api_key or generate_password()

        try:
            SYSTEMD_OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            _run_cmd(["mkdir", "-p", str(SYSTEMD_OVERRIDE_DIR)], sudo=True)

        override_path = SYSTEMD_OVERRIDE_DIR / "override.conf"
        content = (
            "[Service]\n"
            f'Environment="LEMONADE_API_KEY={api_key}"\n'
            f'Environment="LEMONADE_ADMIN_API_KEY={admin_api_key}"\n'
        )
        try:
            override_path.write_text(content)
        except PermissionError:
            tmp_path = Path(f"/tmp/{SYSTEMD_SERVICE_NAME}-override.conf")
            tmp_path.write_text(content)
            _run_cmd(["cp", str(tmp_path), str(override_path)], sudo=True)
            tmp_path.unlink(missing_ok=True)

        _run_cmd(["systemctl", "daemon-reload"], sudo=True)

        self._api_key = api_key
        self._admin_api_key = admin_api_key

        print("[Lemonade] API keys configured in systemd override")
        print(f"[Lemonade]   API Key:       {api_key}")
        print(f"[Lemonade]   Admin API Key: {admin_api_key}")
        return api_key, admin_api_key

    def start(self) -> None:
        _run_cmd(["systemctl", "start", SYSTEMD_SERVICE_NAME], sudo=True)
        print("[Lemonade] Server started")

    def stop(self) -> None:
        _run_cmd(["systemctl", "stop", SYSTEMD_SERVICE_NAME], sudo=True)
        print("[Lemonade] Server stopped")

    def restart(self) -> None:
        _run_cmd(["systemctl", "restart", SYSTEMD_SERVICE_NAME], sudo=True)
        print("[Lemonade] Server restarted")

    def status(self) -> bool:
        result = _run_cmd(
            ["systemctl", "is-active", SYSTEMD_SERVICE_NAME],
            check=False,
        )
        active = result.stdout.strip() == "active"
        if active:
            print("[Lemonade] Server is running")
        else:
            print(f"[Lemonade] Server status: {result.stdout.strip()}")
        return active

    def pull_model(
        self,
        model: str,
        checkpoint: Optional[str] = None,
    ) -> None:
        """Download a model to the local cache via the lemonade CLI.

        Args:
            model: Model name (e.g. "user.gemma-4-31b-it") or HuggingFace
                checkpoint (e.g. "unsloth/gemma-4-31B-it-GGUF:Q8_K_XL").
            checkpoint: HuggingFace checkpoint when pulling a user model by
                name.  Required when model starts with "user.".
        """
        if self._is_model_downloaded(model):
            print(f"[Lemonade] Model already downloaded: {model}")
            return

        print(f"[Lemonade] Pulling model: {model}")
        env = os.environ.copy()
        auth_key = self.admin_api_key or self.api_key
        if auth_key:
            env["LEMONADE_API_KEY"] = auth_key
        if self.admin_api_key:
            env["LEMONADE_ADMIN_API_KEY"] = self.admin_api_key

        cmd: list[str] = ["lemonade", "pull", model]
        if checkpoint and model.startswith("user."):
            cmd += ["--checkpoint", "main", checkpoint, "--recipe", "llamacpp"]

        subprocess.run(cmd, check=False, env=env)
        print(f"[Lemonade] Model pull completed: {model}")

    def _is_model_downloaded(self, model: str) -> bool:
        """Check if a model is already downloaded by checking the HF cache."""
        bare_name = model.removeprefix("user.")
        models = _sudo_read_json(self.config_dir / "user_models.json") or {}
        entry = models.get(bare_name, {})
        checkpoint = entry.get("checkpoint", "")
        if not checkpoint:
            return False
        repo_id = checkpoint.split(":")[0]
        model_dir_name = "models--" + repo_id.replace("/", "--")

        cache_roots = [
            Path("/var/lib/lemonade/.cache/huggingface"),
            Path(os.getenv(
                "HF_HOME",
                os.getenv("HF_HUB_CACHE", str(Path.home() / ".cache" / "huggingface")),
            )),
        ]

        for cache_root in cache_roots:
            hub_dir = cache_root / "hub"
            if not hub_dir.exists():
                continue
            model_cache = hub_dir / model_dir_name
            if model_cache.exists():
                snapshots = model_cache / "snapshots"
                if snapshots.exists():
                    for snap in snapshots.iterdir():
                        if snap.is_dir() and any(snap.glob("*.gguf")):
                            return True
        return False

    def load_model(self, model: str, timeout: int = 120) -> bool:
        """Load a model via the Lemonade HTTP API so it is ready for inference."""
        endpoint = self.get_endpoint()
        url = f"{endpoint}/api/v1/load"
        payload = json.dumps(
            {"model": model, "recipe": "llamacpp"}
        ).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        auth_key = self.admin_api_key or self.api_key
        if auth_key:
            req.add_header("Authorization", f"Bearer {auth_key}")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    print(f"[Lemonade] Model loaded: {model}")
                    return True
                print(f"[Lemonade] Load failed with status {resp.status}")
                return False
        except urllib.error.URLError as e:
            print(f"[Lemonade] Model load error: {e}")
            return False

    def get_endpoint(self) -> str:
        config = _sudo_read_json(self.config_path)
        if config:
            host = config.get("host", DEFAULT_HOST)
            port = config.get("port", DEFAULT_PORT)
            if host == "0.0.0.0":
                host = "localhost"
            return f"http://{host}:{port}"
        return f"http://localhost:{DEFAULT_PORT}"

    def get_port(self) -> int:
        config = _sudo_read_json(self.config_path)
        if config:
            return config.get("port", DEFAULT_PORT)
        return DEFAULT_PORT

    def write_model_configs(
        self,
        model: str = DEFAULT_MODEL,
        model_name: str = DEFAULT_MODEL_NAME,
        num_users: int = 1,
        llamacpp_backend: str = "auto",
        mmproj: Optional[str] = None,
    ) -> None:
        """Write user_models.json, server_models.json, and recipe_options.json.

        Args:
            model: HuggingFace checkpoint (org/repo:variant format).
            model_name: Short model name for model configs (no user. prefix).
            num_users: Number of parallel users; scales ctx-size and -np.
            llamacpp_backend: llama.cpp backend (auto, vulkan, cpu).
            mmproj: Multimodal projection model filename (e.g. "mmproj-BF16.gguf").
        """
        user_models_path = self.config_dir / "user_models.json"
        server_models_path = self.config_dir / "server_models.json"
        recipe_options_path = self.config_dir / "recipe_options.json"

        existing_models = _sudo_read_json(user_models_path) or {}

        auto_name = model.split("/")[-1].split(":")[0]
        auto_name_key = auto_name

        if auto_name_key in existing_models and auto_name_key != model_name:
            auto_entry = existing_models[auto_name_key]
            if not mmproj and "mmproj" in auto_entry:
                mmproj = auto_entry["mmproj"]
                print(f"[Lemonade] Inherited mmproj from auto-generated entry: {mmproj}")
            del existing_models[auto_name_key]
            print(f"[Lemonade] Removed auto-generated entry: {auto_name_key}")

        labels = ["custom"]
        if mmproj:
            labels.append("vision")

        model_entry: dict = {
            "model_name": model_name,
            "checkpoint": model,
            "recipe": "llamacpp",
            "suggested": True,
            "labels": labels,
        }
        if mmproj:
            model_entry["mmproj"] = mmproj
        existing_models[model_name] = model_entry
        _sudo_write_json(user_models_path, existing_models)
        print(f"[Lemonade] user_models.json updated with {model_name}")

        server_models = _sudo_read_json(server_models_path) or {}
        if auto_name_key in server_models and auto_name_key != model_name:
            del server_models[auto_name_key]
        server_models[model_name] = model_entry
        _sudo_write_json(server_models_path, server_models)
        print(f"[Lemonade] server_models.json updated with {model_name}")

        total_ctx = PER_USER_CTX * num_users
        llamacpp_args = (
            f"-b 8192 -ub 8192 "
            f"-to 3600 "
            f"-ctk q8_0 -ctv q8_0 "
            f"--temp 1.0 --top-k 64 --top-p 0.95 --min-p 0.0 "
            f"--repeat-penalty 1.0 "
            f"--no-webui "
            f"--threads-http -1 --threads -1 "
            f"-np {num_users}"
        )

        existing_options = _sudo_read_json(recipe_options_path) or {}

        prefixed_auto_name = f"user.{auto_name}"
        if prefixed_auto_name in existing_options and prefixed_auto_name != prefixed_name:
            del existing_options[prefixed_auto_name]
            print(f"[Lemonade] Removed auto-generated recipe options: {prefixed_auto_name}")

        prefixed_name = f"user.{model_name}"
        existing_options[prefixed_name] = {
            "ctx_size": total_ctx,
            "llamacpp_backend": llamacpp_backend,
            "llamacpp_args": llamacpp_args,
        }
        _sudo_write_json(recipe_options_path, existing_options)
        print(f"[Lemonade] recipe_options.json updated for {prefixed_name}")
        print(f"[Lemonade]   ctx-size: {total_ctx} ({PER_USER_CTX} x {num_users} users)")
        print(f"[Lemonade]   -np: {num_users}")
        print(f"[Lemonade]   llamacpp_args: {llamacpp_args}")

    def generate_kilo_config(
        self,
        model: str = DEFAULT_MODEL,
        model_name: str = DEFAULT_MODEL_NAME,
        external_ip: Optional[str] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Generate a kilo.json config for Kilo Code pointing at this Lemonade server.

        The base URL is resolved to the best reachable address from inside
        sandbox containers: external_ip > Docker bridge gateway > localhost.

        Args:
            model: HuggingFace checkpoint for display name.
            model_name: Short model name used as kilo.json model ID.
            external_ip: External IP for sandbox access.
            output_path: Path to write kilo.json. Defaults to ./kilo.json.

        Returns:
            Path to the generated kilo.json file.
        """
        port = self.get_port()
        docker_ip = detect_docker_host_ip()

        if external_ip:
            base_host = external_ip
        elif docker_ip:
            base_host = docker_ip
        else:
            base_host = "localhost"

        base_url = f"http://{base_host}:{port}/v1"
        auth_key = self.admin_api_key or self.api_key or "none"

        prefixed_model_name = f"user.{model_name}"
        config: dict = {
            "provider": {
                "lemonade": {
                    "models": {
                        prefixed_model_name: {
                            "name": model,
                            "limit": {
                                "context": self._get_ctx_size(),
                                "output": 4096,
                            },
                        },
                    },
                    "options": {
                        "apiKey": auth_key,
                        "baseURL": base_url,
                    },
                },
            },
            "model": f"lemonade/{prefixed_model_name}",
        }

        target = output_path or Path("kilo.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(config, indent=2))

        print(f"[Lemonade] Kilo Code config written to {target}")
        print(f"[Lemonade]   Provider:  lemonade")
        print(f"[Lemonade]   Base URL:  {base_url}")
        print(f"[Lemonade]   Model:     lemonade/{prefixed_model_name}")
        if auth_key != "none":
            print(f"[Lemonade]   API Key:   {auth_key}")
        return target

    def _get_ctx_size(self) -> int:
        config = _sudo_read_json(self.config_path)
        if config:
            return config.get("ctx_size", 4096)
        return 4096

    def cleanup(self) -> None:
        self.stop()
        print("[Lemonade] Cleanup complete")


def _print_endpoint_info(
    manager: LemonadeServerManager,
    model: str,
    port: int,
    external_ip: Optional[str] = None,
) -> None:
    endpoint = manager.get_endpoint()
    docker_ip = detect_docker_host_ip()
    auth_key = manager.admin_api_key or manager.api_key

    print("\n" + "=" * 70)
    print("Lemonade Inference Server")
    print("=" * 70)
    print(f"  Local endpoint: {endpoint}")
    print(f"  OpenAI API:     {endpoint}/v1/")
    if external_ip:
        print(f"  External API:   http://{external_ip}:{port}/v1/")
    print(f"  Model:          {model}")
    if manager.api_key:
        print(f"  API Key:        {manager.api_key}")
    if manager.admin_api_key:
        print(f"  Admin API Key:  {manager.admin_api_key}")

    print()
    print("VS Code Extension Configuration (for sandbox instances):")
    if docker_ip:
        print(f"  Base URL:  http://{docker_ip}:{port}/v1")
    if external_ip:
        print(f"  Base URL:  http://{external_ip}:{port}/v1")
    elif not docker_ip:
        print(f"  Base URL:  http://localhost:{port}/v1")
    print(f"  API Key:   {auth_key or '(none)'}")
    print(f"  Model:     {model}")
    print()


async def cmd_run(
    model: str = DEFAULT_MODEL,
    model_name: str = DEFAULT_MODEL_NAME,
    port: int = DEFAULT_PORT,
    host: str = DEFAULT_HOST,
    llamacpp_backend: str = "auto",
    ctx_size: int = 4096,
    max_loaded_models: int = 1,
    mmproj: Optional[str] = DEFAULT_MMPROJ,
    groups_file: Optional[str] = None,
    group_filter: Optional[str] = None,
    num_users: int = 1,
    generate_keys: bool = False,
    skip_install: bool = False,
    external_ip: Optional[str] = None,
    api_key: Optional[str] = None,
    admin_api_key: Optional[str] = None,
    kilo_config: Optional[str] = None,
    prefer_system: bool = True,
    llamacpp_bin: str = DEFAULT_LLMACPP_BIN,
) -> None:
    if groups_file:
        num_users = load_user_count(groups_file, group_filter)
        if num_users == 0:
            print("[Lemonade] Error: No users found in groups config")
            sys.exit(1)
        print(f"[Lemonade] {num_users} user(s) from {groups_file}")
    elif num_users < 1:
        num_users = 1

    total_ctx = PER_USER_CTX * num_users

    manager = LemonadeServerManager(
        api_key=api_key,
        admin_api_key=admin_api_key,
    )

    if not skip_install and not manager.is_installed():
        manager.install()

    manager.write_model_configs(
        model=model,
        model_name=model_name,
        num_users=num_users,
        llamacpp_backend=llamacpp_backend,
        mmproj=mmproj,
    )

    manager.configure(
        port=port,
        host=host,
        llamacpp_backend=llamacpp_backend,
        ctx_size=total_ctx,
        max_loaded_models=max_loaded_models,
        generate_keys=generate_keys,
        prefer_system=prefer_system,
        llamacpp_bin=llamacpp_bin,
    )

    manager.restart()

    print("[Lemonade] Waiting for server to be ready...")
    await asyncio.sleep(3)

    if not manager.status():
        print("[Lemonade] Error: Server failed to start")
        sys.exit(1)

    prefixed_model = f"user.{model_name}"
    manager.pull_model(prefixed_model, checkpoint=model)

    await asyncio.sleep(2)
    manager.load_model(prefixed_model)

    _print_endpoint_info(manager, model, port, external_ip)

    if generate_keys or kilo_config:
        output = Path(kilo_config) if kilo_config else Path("kilo.json")
        manager.generate_kilo_config(
            model=model,
            model_name=model_name,
            external_ip=external_ip,
            output_path=output,
        )

    print("Keeping server alive. Press Ctrl+C to exit.")

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n[Lemonade] Stopping...")
    finally:
        manager.stop()
        print("[Lemonade] Stopped")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Lemonade inference server forTHON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # One-time installation
  python lemonade_server.py install

  # Configure with API keys
  python lemonade_server.py configure --generate-keys --host 0.0.0.0

  # Start the server
  python lemonade_server.py start

  # Pull a model
  python lemonade_server.py pull --model Gemma-3-4b-it-GGUF

  # Full setup (install + configure + start + pull model)
  python lemonade_server.py run --model Gemma-3-4b-it-GGUF --generate-keys --external-ip 1.2.3.4

  # Check server status
  python lemonade_server.py status

  # Stop the server
  python lemonade_server.py stop

  # Cleanup
  python lemonade_server.py cleanup
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("install", help="Install lemonade-server via PPA")

    config_parser = subparsers.add_parser(
        "configure", help="Configure server settings"
    )
    config_parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})"
    )
    config_parser.add_argument(
        "--host", type=str, default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})"
    )
    config_parser.add_argument(
        "--llamacpp-backend",
        type=str,
        default="auto",
        help="llama.cpp backend: auto, vulkan, cpu (default: auto)",
    )
    config_parser.add_argument(
        "--prefer-system",
        action="store_true",
        default=True,
        help="Prefer system-installed llama.cpp over bundled (default: True)",
    )
    config_parser.add_argument(
        "--no-prefer-system",
        action="store_false",
        dest="prefer_system",
        help="Use bundled llama.cpp instead of system-installed",
    )
    config_parser.add_argument(
        "--llamacpp-bin",
        type=str,
        default=DEFAULT_LLMACPP_BIN,
        help=f"Path to system llama-server binary (default: {DEFAULT_LLMACPP_BIN})",
    )
    config_parser.add_argument(
        "--ctx-size", type=int, default=4096, help="Default context size (default: 4096)"
    )
    config_parser.add_argument(
        "--max-loaded-models",
        type=int,
        default=1,
        help="Max models per type slot (default: 1)",
    )
    config_parser.add_argument(
        "--generate-keys",
        action="store_true",
        default=False,
        help="Generate API key and admin API key, store in systemd override",
    )
    config_parser.add_argument(
        "--api-key", type=str, default=None, help="Set a specific API key (overrides generate)"
    )
    config_parser.add_argument(
        "--admin-api-key",
        type=str,
        default=None,
        help="Set a specific admin API key (overrides generate)",
    )
    config_parser.add_argument(
        "--kilo-config",
        type=str,
        default=None,
        help="Generate kilo.json for Kilo Code at this path (requires --generate-keys or --api-key)",
    )
    config_parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Model ID for kilo.json (default: {DEFAULT_MODEL})",
    )
    config_parser.add_argument(
        "--external-ip",
        type=str,
        default=None,
        help="External IP for kilo.json base URL (auto-detect Docker gateway if omitted)",
    )

    subparsers.add_parser("start", help="Start the server")
    subparsers.add_parser("stop", help="Stop the server")
    subparsers.add_parser("restart", help="Restart the server")
    subparsers.add_parser("status", help="Check server status")

    pull_parser = subparsers.add_parser("pull", help="Pull a model to local cache")
    pull_parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Model to pull (default: {DEFAULT_MODEL})",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Full setup: install + configure + start + pull model + keep alive",
    )
    run_parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"HuggingFace checkpoint to pull (default: {DEFAULT_MODEL})",
    )
    run_parser.add_argument(
        "--model-name",
        type=str,
        default=DEFAULT_MODEL_NAME,
        help=f"Short model name for user_models.json (default: {DEFAULT_MODEL_NAME})",
    )
    run_parser.add_argument(
        "--groups",
        type=str,
        default=None,
        help="Path to groups.yaml; user count scales ctx-size and parallel slots",
    )
    run_parser.add_argument(
        "--group",
        type=str,
        default=None,
        help="Filter to a single group from groups.yaml for user count",
    )
    run_parser.add_argument(
        "--num-users",
        type=int,
        default=1,
        help="Override number of parallel users (default: 1, or auto from --groups)",
    )
    run_parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})"
    )
    run_parser.add_argument(
        "--host", type=str, default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})"
    )
    run_parser.add_argument(
        "--llamacpp-backend",
        type=str,
        default="auto",
        help="llama.cpp backend: auto, vulkan, cpu (default: auto)",
    )
    run_parser.add_argument(
        "--prefer-system",
        action="store_true",
        default=True,
        help="Prefer system-installed llama.cpp over bundled (default: True)",
    )
    run_parser.add_argument(
        "--no-prefer-system",
        action="store_false",
        dest="prefer_system",
        help="Use bundled llama.cpp instead of system-installed",
    )
    run_parser.add_argument(
        "--llamacpp-bin",
        type=str,
        default=DEFAULT_LLMACPP_BIN,
        help=f"Path to system llama-server binary (default: {DEFAULT_LLMACPP_BIN})",
    )
    run_parser.add_argument(
        "--ctx-size", type=int, default=4096, help="Default context size (default: 4096)"
    )
    run_parser.add_argument(
        "--max-loaded-models",
        type=int,
        default=1,
        help="Max models per type slot (default: 1)",
    )
    run_parser.add_argument(
        "--generate-keys",
        action="store_true",
        default=False,
        help="Generate API key and admin API key",
    )
    run_parser.add_argument(
        "--api-key", type=str, default=None, help="Set a specific API key"
    )
    run_parser.add_argument(
        "--admin-api-key",
        type=str,
        default=None,
        help="Set a specific admin API key",
    )
    run_parser.add_argument(
        "--skip-install",
        action="store_true",
        default=False,
        help="Skip installation check (server already installed)",
    )
    run_parser.add_argument(
        "--mmproj",
        type=str,
        default=DEFAULT_MMPROJ,
        help=f"Multimodal projection model filename (default: {DEFAULT_MMPROJ})",
    )
    run_parser.add_argument(
        "--external-ip",
        type=str,
        default=None,
        help="External IP for sandbox access URLs (auto-detect Docker gateway if omitted)",
    )
    run_parser.add_argument(
        "--kilo-config",
        type=str,
        default=None,
        help="Generate kilo.json for Kilo Code at this path (default: ./kilo.json when --generate-keys is set)",
    )

    count_users_parser = subparsers.add_parser(
        "count-users",
        help="Print number of users from a groups.yaml file",
    )
    count_users_parser.add_argument(
        "--groups",
        type=str,
        required=True,
        help="Path to groups.yaml file",
    )
    count_users_parser.add_argument(
        "--group",
        type=str,
        default=None,
        help="Filter to a single group from groups.yaml",
    )

    write_model_configs_parser = subparsers.add_parser(
        "write-model-configs",
        help="Write user_models.json and recipe_options.json",
    )
    write_model_configs_parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"HuggingFace checkpoint (default: {DEFAULT_MODEL})",
    )
    write_model_configs_parser.add_argument(
        "--model-name",
        type=str,
        default=DEFAULT_MODEL_NAME,
        help=f"Short model name (default: {DEFAULT_MODEL_NAME})",
    )
    write_model_configs_parser.add_argument(
        "--num-users",
        type=int,
        default=1,
        help="Number of parallel users; scales ctx-size and -np (default: 1)",
    )
    write_model_configs_parser.add_argument(
        "--llamacpp-backend",
        type=str,
        default="auto",
        help="llama.cpp backend (default: auto)",
    )
    write_model_configs_parser.add_argument(
        "--mmproj",
        type=str,
        default=DEFAULT_MMPROJ,
        help=f"Multimodal projection model filename (default: {DEFAULT_MMPROJ})",
    )

    generate_kilo_parser = subparsers.add_parser(
        "generate-kilo-config",
        help="Generate kilo.json for Kilo Code",
    )
    generate_kilo_parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"HuggingFace checkpoint (default: {DEFAULT_MODEL})",
    )
    generate_kilo_parser.add_argument(
        "--model-name",
        type=str,
        default=DEFAULT_MODEL_NAME,
        help=f"Short model name (default: {DEFAULT_MODEL_NAME})",
    )
    generate_kilo_parser.add_argument(
        "--external-ip",
        type=str,
        default=None,
        help="External IP for sandbox access URL",
    )
    generate_kilo_parser.add_argument(
        "--output",
        type=str,
        default="kilo.json",
        help="Output path for kilo.json (default: kilo.json)",
    )
    generate_kilo_parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key to include in kilo.json",
    )
    generate_kilo_parser.add_argument(
        "--admin-api-key",
        type=str,
        default=None,
        help="Admin API key (preferred over --api-key)",
    )

    subparsers.add_parser("cleanup", help="Stop server and clean up")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    manager = LemonadeServerManager(
        api_key=getattr(args, "api_key", None),
        admin_api_key=getattr(args, "admin_api_key", None),
    )

    if args.command == "install":
        manager.install()
    elif args.command == "configure":
        manager.configure(
            port=args.port,
            host=args.host,
            llamacpp_backend=args.llamacpp_backend,
            ctx_size=args.ctx_size,
            max_loaded_models=args.max_loaded_models,
            generate_keys=args.generate_keys,
            prefer_system=args.prefer_system,
            llamacpp_bin=args.llamacpp_bin,
        )
        if args.kilo_config and (manager.api_key or manager.admin_api_key):
            manager.generate_kilo_config(
                model=getattr(args, "model", DEFAULT_MODEL),
                model_name=getattr(args, "model_name", DEFAULT_MODEL_NAME),
                external_ip=args.external_ip,
                output_path=Path(args.kilo_config) if args.kilo_config else None,
            )
        elif args.kilo_config:
            print("[Lemonade] Warning: --kilo-config requires --generate-keys or --api-key to set authentication")
    elif args.command == "start":
        manager.start()
    elif args.command == "stop":
        manager.stop()
    elif args.command == "restart":
        manager.restart()
    elif args.command == "status":
        manager.status()
    elif args.command == "pull":
        manager.pull_model(args.model)
    elif args.command == "run":
        asyncio.run(
            cmd_run(
                model=args.model,
                model_name=args.model_name,
                port=args.port,
                host=args.host,
                llamacpp_backend=args.llamacpp_backend,
                ctx_size=args.ctx_size,
                max_loaded_models=args.max_loaded_models,
                groups_file=args.groups,
                group_filter=args.group,
                num_users=args.num_users,
                generate_keys=args.generate_keys,
                skip_install=args.skip_install,
                external_ip=args.external_ip,
                api_key=args.api_key,
                admin_api_key=args.admin_api_key,
                kilo_config=args.kilo_config,
                prefer_system=args.prefer_system,
                llamacpp_bin=args.llamacpp_bin,
                mmproj=args.mmproj,
            )
        )
    elif args.command == "count-users":
        count = load_user_count(args.groups, args.group)
        print(count)
    elif args.command == "write-model-configs":
        manager.write_model_configs(
            model=args.model,
            model_name=args.model_name,
            num_users=args.num_users,
            llamacpp_backend=args.llamacpp_backend,
            mmproj=args.mmproj,
        )
    elif args.command == "generate-kilo-config":
        mgr = LemonadeServerManager(
            api_key=args.api_key,
            admin_api_key=args.admin_api_key,
        )
        mgr.generate_kilo_config(
            model=args.model,
            model_name=args.model_name,
            external_ip=args.external_ip,
            output_path=Path(args.output),
        )
    elif args.command == "cleanup":
        manager.cleanup()


if __name__ == "__main__":
    main()
