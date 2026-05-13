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

"""Interactive guided setup for thon.yaml — `python -m thon init`.

Walks the user through every THON feature with sensible defaults,
validates choices, and writes a thon.yaml config file.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Optional

from thon.config import (
    THON_DIR,
    AuthSettings,
    DashboardSettings,
    GatewaySettings,
    KiloSettings,
    LangfuseSettings,
    LemonadeSettings,
    NginxSettings,
    SandboxSettings,
    ThonConfig,
    VscodeSettings,
    WorkspaceSettings,
)


def _prompt(
    label: str,
    default: str = "",
    choices: Optional[list[str]] = None,
    allow_empty: bool = True,
) -> str:
    """Display a prompt and return user input."""
    if choices:
        choice_str = " / ".join(f"{i + 1}.{c}" for i, c in enumerate(choices))
        suffix = f" [{choice_str}]"
        if default:
            suffix += f" (default: {default})"
        prompt_text = f"  {label}{suffix}: "
    else:
        prompt_text = f"  {label}"
        if default:
            prompt_text += f" [{default}]"
        prompt_text += ": "

    while True:
        raw = input(prompt_text).strip()
        if not raw:
            if default or allow_empty:
                return default
            print("    Please enter a value.")
            continue

        if choices and raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
            print(f"    Invalid choice. Enter 1-{len(choices)}.")
            continue

        if choices and raw not in choices:
            print(f"    Invalid choice. Choose from: {', '.join(choices)}")
            continue

        return raw


def _yes_no(label: str, default: bool = False) -> bool:
    """Prompt for a yes/no answer."""
    d = "Y/n" if default else "y/N"
    raw = input(f"  {label} [{d}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def _detect_external_ip() -> Optional[str]:
    """Try to detect the external IP from hostname -I."""
    try:
        result = subprocess.run(
            ["hostname", "-I"],
            capture_output=True,
            text=True,
            check=True,
        )
        ips = result.stdout.strip().split()
        for ip in ips:
            if ip.startswith(("10.", "172.", "127.", "192.168.")):
                continue
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                return ip
    except Exception:
        pass
    return None


def _read_sandbox_toml() -> dict[str, str]:
    """Read ~/.sandbox.toml and return relevant sandbox server settings.

    Returns a dict with keys: ``domain``, ``api_key``.  Missing values
    default to empty strings so callers can fall back gracefully.
    """
    toml_path = Path.home() / ".sandbox.toml"
    result: dict[str, str] = {"domain": "", "api_key": ""}
    if not toml_path.is_file():
        return result
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return result
    server = data.get("server", {})
    if not isinstance(server, dict):
        return result
    host = server.get("host", "")
    port = server.get("port", "")
    if host and port:
        result["domain"] = f"{host}:{port}"
    elif host:
        result["domain"] = host
    api_key = server.get("api_key", "")
    if isinstance(api_key, str) and api_key:
        result["api_key"] = api_key
    return result


def _detect_apisix_admin_key() -> str:
    """Read the APISIX admin key from /usr/local/apisix/conf/config.yaml."""
    import re

    config_path = Path("/usr/local/apisix/conf/config.yaml")
    if not config_path.is_file():
        return ""
    try:
        content = config_path.read_text()
        key_match = re.search(
            r"^\s*key:\s*['\"]?(\S+?)['\"]?\s*$", content, re.MULTILINE
        )
        if key_match and key_match.group(1):
            return key_match.group(1)
    except Exception:
        pass
    return ""


def _detect_lemonade_keys() -> dict[str, str]:
    """Read Lemonade API keys from systemd override files.

    Returns a dict with keys: ``api_key``, ``admin_api_key``.
    """
    import re

    result: dict[str, str] = {"api_key": "", "admin_api_key": ""}
    for service_name in ("lemonade-server", "lemond"):
        override_path = Path(
            f"/etc/systemd/system/{service_name}.service.d/override.conf"
        )
        if not override_path.is_file():
            continue
        try:
            content = override_path.read_text()
            api_match = re.search(r'LEMONADE_API_KEY="?([^"\s]+)"?', content)
            admin_match = re.search(r'LEMONADE_ADMIN_API_KEY="?([^"\s]+)"?', content)
            if api_match:
                result["api_key"] = api_match.group(1)
            if admin_match:
                result["admin_api_key"] = admin_match.group(1)
            if result["api_key"] or result["admin_api_key"]:
                return result
        except Exception:
            continue
    return result


def _is_installed(package: str) -> bool:
    """Check if a dpkg package is installed."""
    try:
        result = subprocess.run(
            ["dpkg", "-s", package],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _info(msg: str) -> None:
    print(f"  ℹ  {msg}")


def run_interactive(
    config_path: Optional[str] = None,
    non_interactive: bool = False,
) -> ThonConfig:
    """Run the interactive setup wizard and return a ThonConfig.

    Args:
        config_path: Path to write thon.yaml. Defaults to ./thon.yaml.
        non_interactive: If True, generate a config with defaults without
            prompting (useful for CI or scripted setup).
    """
    target = Path(config_path) if config_path else THON_DIR / "thon.yaml"

    if target.exists():
        print(f"Found existing config at {target}")
        if not non_interactive and not _yes_no("Overwrite?", default=False):
            print(f"Loading existing config from {target}")
            return ThonConfig.from_yaml(target)
        print(f"Re-initializing {target}...")

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║            THON — Interactive Setup Wizard              ║")
    print("║                                                         ║")
    print("║  This wizard creates a thon.yaml config file.           ║")
    print("║  Press Enter to accept defaults.                        ║")
    print("╚══════════════════════════════════════════════════════════╝")

    detected_ip = _detect_external_ip()

    # ── External IP ──────────────────────────────────────────
    _section("Network")
    if detected_ip:
        _info(f"Detected external IP: {detected_ip}")
    external_ip = (
        detected_ip or ""
        if non_interactive
        else _prompt("External IP for SSL certs and URLs", default=detected_ip or "")
    )

    # ── Groups ───────────────────────────────────────────────
    _section("Groups & Users")
    _info("Define groups and users. Each user gets their own VS Code sandbox.")

    groups: dict[str, list[str]] = {}
    if non_interactive:
        groups = {"alpha": ["alice", "bob"]}
    else:
        while True:
            group_name = _prompt("Group name (or empty to finish)", allow_empty=True)
            if not group_name:
                break
            users_str = _prompt(
                f"Users for '{group_name}' (comma-separated)",
                default="workspace",
            )
            users = [u.strip() for u in users_str.split(",") if u.strip()]
            groups[group_name] = users

            if not _yes_no("Add another group?", default=False):
                break

    if not groups:
        _info(
            "No groups defined. Instances will not start unless you add groups "
            "via the dashboard, or run with --demo for a default workspace."
        )

    # ── Sandbox ──────────────────────────────────────────────
    _section("Sandbox")
    sandbox_toml = _read_sandbox_toml()
    sandbox = SandboxSettings()
    if sandbox_toml["domain"]:
        sandbox.domain = sandbox_toml["domain"]
        _info(f"Read domain from ~/.sandbox.toml: {sandbox.domain}")
    if sandbox_toml["api_key"]:
        sandbox.api_key = sandbox_toml["api_key"]
        _info("Read API key from ~/.sandbox.toml")
    if not non_interactive:
        sandbox.domain = _prompt("Sandbox server domain", default=sandbox.domain)
        if sandbox.api_key:
            _info("API key loaded from ~/.sandbox.toml (press Enter to keep)")
            raw_key = _prompt(
                "Sandbox API key (leave empty to keep current)", default=""
            )
            if raw_key:
                sandbox.api_key = raw_key
        else:
            sandbox.api_key = _prompt(
                "Sandbox API key (leave empty if none)", default=""
            )
        sandbox.image = _prompt("Docker image", default=sandbox.image)
        sandbox.starting_port = int(
            _prompt("Starting port", default=str(sandbox.starting_port))
        )
        sandbox.timeout_minutes = int(
            _prompt("Timeout in minutes (0 = no timeout)", default="0")
        )

    # ── VS Code ──────────────────────────────────────────────
    _section("VS Code Instances")
    vscode = VscodeSettings()
    if not non_interactive:
        vscode.secure = _yes_no(
            "Enable per-user password authentication?", default=False
        )
        if _yes_no("Inject custom VS Code settings?", default=False):
            vscode.settings_file = _prompt(
                "Path to VS Code settings JSON",
                default="config/vscode-settings.jsonc",
            )

    # ── Nginx / SSL ──────────────────────────────────────────
    _section("Nginx & SSL")
    nginx = NginxSettings()
    if not non_interactive:
        nginx.enabled = _yes_no("Enable nginx reverse proxy with SSL?", default=True)
        if nginx.enabled:
            nginx.ssl_dir = _prompt("SSL cert directory", default=nginx.ssl_dir)

    # ── Workspace ────────────────────────────────────────────
    _section("Workspace Persistence")
    workspace = WorkspaceSettings()
    if not non_interactive:
        _info(
            "Without a workspace dir, data is ephemeral (lost when instances are killed)."
        )
        _info(
            "With a workspace dir, each user gets a persistent bind mount at "
            "{dir}/{group}/{username}."
        )
        if _yes_no("Enable persistent workspaces?", default=False):
            workspace.dir = _prompt(
                "Host directory for workspace bind mounts",
                default="/thon-workspace",
            )

    # ── Lemonade ─────────────────────────────────────────────
    _section("Lemonade Server (Local LLM Inference)")
    lemonade = LemonadeSettings()
    lemonade_installed = _is_installed("lemonade-server")
    if lemonade_installed:
        _info("Lemonade server is installed")
    lemonade_keys = _detect_lemonade_keys()
    if lemonade_keys["api_key"]:
        lemonade.api_key = lemonade_keys["api_key"]
        _info("Read API key from Lemonade systemd override")
    if lemonade_keys["admin_api_key"]:
        lemonade.admin_api_key = lemonade_keys["admin_api_key"]
        _info("Read admin API key from Lemonade systemd override")
    if not non_interactive:
        lemonade.enabled = _yes_no(
            "Enable Lemonade inference server?",
            default=lemonade_installed,
        )
        if lemonade.enabled:
            lemonade.host = _prompt("Bind address", default=lemonade.host)
            lemonade.port = int(_prompt("Port", default=str(lemonade.port)))
            lemonade.model = _prompt(
                "HuggingFace model checkpoint", default=lemonade.model
            )
            lemonade.model_name = _prompt(
                "Short model name", default=lemonade.model_name
            )
            lemonade.ctx_size_per_user = int(
                _prompt(
                    "Context length per user for chat model",
                    default=str(lemonade.ctx_size_per_user),
                )
            )
            lemonade.embedding_model = _prompt(
                "Embedding model checkpoint", default=lemonade.embedding_model
            )
            lemonade.embedding_model_name = _prompt(
                "Embedding model short name", default=lemonade.embedding_model_name
            )
            lemonade.embedding_ctx_size_per_user = int(
                _prompt(
                    "Context length per user for embedding model",
                    default=str(lemonade.embedding_ctx_size_per_user),
                )
            )
            lemonade.embedding_dimensions = int(
                _prompt(
                    "Embedding model dimensions (0 = auto-detect)",
                    default=str(lemonade.embedding_dimensions),
                )
            )
            lemonade.llamacpp_backend = _prompt(
                "llama.cpp backend",
                default=lemonade.llamacpp_backend,
                choices=["auto", "vulkan", "cpu"],
            )
            if lemonade.api_key:
                _info("API key already loaded from systemd (press Enter to keep)")
                if not _yes_no("Regenerate API keys?", default=False):
                    lemonade.generate_keys = False
                else:
                    lemonade.generate_keys = True
            else:
                lemonade.generate_keys = _yes_no(
                    "Generate API keys automatically?", default=True
                )
    else:
        if lemonade_installed:
            lemonade.enabled = True
            lemonade.generate_keys = not bool(lemonade.api_key)

    # ── Kilo Code ────────────────────────────────────────────
    _section("Kilo Code")
    kilo = KiloSettings()
    if not non_interactive:
        if lemonade.enabled:
            _info("Kilo Code config will be auto-generated during setup")
            kilo.config_file = str(THON_DIR / "kilo.jsonc")
            if _yes_no("Use a kilo.jsonc skeleton for custom overrides?", default=True):
                kilo.skeleton_file = _prompt(
                    "Path to skeleton file",
                    default=kilo.skeleton_file,
                )
            all_models = lemonade.effective_chat_models()
            if all_models:
                _info(
                    f"Available models (Lemonade uses user.<name> prefix): "
                    f"{', '.join(m.name for m in all_models)}"
                )
                default_model = f"lemonade/user.{all_models[0].name}"
                kilo.chat_model = _prompt(
                    "Default chat model",
                    default=default_model,
                )
                kilo.small_model = _prompt(
                    "Small model for agentic tool calling (leave empty to skip)",
                    default="",
                )
        elif _yes_no("Use a custom Kilo Code config?", default=False):
            kilo.config_file = _prompt(
                "Path to kilo.jsonc", default=str(THON_DIR / "kilo.jsonc")
            )

    # ── AI Gateway ───────────────────────────────────────────
    _section("AI Gateway (APISIX Rate Limiting)")
    gateway = GatewaySettings()
    apisix_installed = _is_installed("apisix")
    detected_admin_key = _detect_apisix_admin_key()
    if apisix_installed:
        _info("APISIX is installed")
    if detected_admin_key:
        gateway.admin_key = detected_admin_key
        _info("Read admin key from APISIX config")
    if not non_interactive:
        gateway.enabled = _yes_no(
            "Enable APISIX AI Gateway with rate limiting?",
            default=apisix_installed,
        )
        if gateway.enabled:
            gateway.mode = _prompt(
                "Consumer mode",
                default=gateway.mode,
                choices=["per-user", "per-group"],
            )
            gateway.rate_limit_scope = _prompt(
                "Rate limit scope",
                default=gateway.rate_limit_scope,
                choices=["per-user", "per-model"],
            )

            if gateway.rate_limit_scope == "per-model":
                _info(
                    "Per-model rate limiting is stored in config for future use. "
                    "APISIX currently applies uniform per-consumer limits; "
                    "per-model enforcement requires a custom plugin."
                )

            gateway.concurrency_limit = int(
                _prompt(
                    "Max concurrent requests per consumer",
                    default=str(gateway.concurrency_limit),
                )
            )
            gateway.token_limit = int(
                _prompt(
                    "Token limit per consumer per time window (0 = no limit)",
                    default=str(gateway.token_limit),
                )
            )
            gateway.token_window = int(
                _prompt(
                    "Token limit time window (seconds)",
                    default=str(gateway.token_window),
                )
            )

            if _yes_no("Use Redis for distributed rate limiting?", default=False):
                gateway.redis_host = _prompt("Redis host", default="127.0.0.1")
    else:
        if apisix_installed and detected_admin_key:
            gateway.enabled = True

    # ── Dashboard ────────────────────────────────────────────
    _section("Dashboard")
    dashboard = DashboardSettings()
    if not non_interactive:
        dashboard.host = _prompt("Dashboard bind address", default=dashboard.host)
        dashboard.port = int(_prompt("Dashboard port", default=str(dashboard.port)))
        dashboard.debug = _yes_no("Enable debug mode?", default=False)

    # ── Langfuse ─────────────────────────────────────────────
    _section("Langfuse Observability")
    langfuse = LangfuseSettings()
    if not non_interactive:
        langfuse.enabled = _yes_no(
            "Enable Langfuse LLM observability?", default=False
        )
        if langfuse.enabled:
            langfuse.public_key = _prompt("Langfuse public key")
            langfuse.secret_key = _prompt("Langfuse secret key")
            langfuse.base_url = _prompt(
                "Langfuse base URL", default=langfuse.base_url
            )

    # ── Auth ─────────────────────────────────────────────────
    _section("Authentication (OIDC)")
    auth = AuthSettings()
    if not non_interactive:
        auth.enabled = _yes_no("Enable OIDC authentication?", default=False)
        if auth.enabled:
            if _yes_no("Configure GitHub OAuth?", default=False):
                auth.github.client_id = _prompt("GitHub Client ID")
                auth.github.client_secret = _prompt("GitHub Client Secret")
            if _yes_no("Configure GitLab OAuth?", default=False):
                auth.gitlab.client_id = _prompt("GitLab Client ID")
                auth.gitlab.client_secret = _prompt("GitLab Client Secret")
            if _yes_no("Configure LinkedIn OIDC?", default=False):
                auth.linkedin.client_id = _prompt("LinkedIn Client ID")
                auth.linkedin.client_secret = _prompt("LinkedIn Client Secret")

    # ── Assemble ─────────────────────────────────────────────
    config = ThonConfig(
        external_ip=external_ip,
        groups=groups,
        sandbox=sandbox,
        vscode=vscode,
        nginx=nginx,
        workspace=workspace,
        lemonade=lemonade,
        kilo=kilo,
        gateway=gateway,
        langfuse=langfuse,
        dashboard=dashboard,
        auth=auth,
    )

    # ── Write ────────────────────────────────────────────────
    config.to_yaml(target)
    print(f"\n  ✓  Config written to {target}")
    print()
    print("  Next steps:")
    print(f"    1. Review: cat {target}")
    print("    2. Setup:  python -m thon setup")
    print("    3. Run:    python -m thon run")
    print("    4. Launch: python -m thon launch  (batch instance creation)")
    print()

    return config
