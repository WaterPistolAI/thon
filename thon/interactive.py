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
from pathlib import Path
from typing import Optional

from thon.config import (
    AuthSettings,
    DashboardSettings,
    GatewaySettings,
    KiloSettings,
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
    target = Path(config_path) if config_path else Path("thon.yaml")

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
    sandbox = SandboxSettings()
    if not non_interactive:
        sandbox.domain = _prompt("Sandbox server domain", default=sandbox.domain)
        sandbox.api_key = _prompt("Sandbox API key (leave empty if none)", default="")
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

    # ── Lemonade ─────────────────────────────────────────────
    _section("Lemonade Server (Local LLM Inference)")
    lemonade = LemonadeSettings()
    if not non_interactive:
        lemonade.enabled = _yes_no("Enable Lemonade inference server?", default=True)
        if lemonade.enabled:
            lemonade.host = _prompt("Bind address", default=lemonade.host)
            lemonade.port = int(_prompt("Port", default=str(lemonade.port)))
            lemonade.model = _prompt(
                "HuggingFace model checkpoint", default=lemonade.model
            )
            lemonade.model_name = _prompt(
                "Short model name", default=lemonade.model_name
            )
            lemonade.embedding_model = _prompt(
                "Embedding model checkpoint", default=lemonade.embedding_model
            )
            lemonade.embedding_model_name = _prompt(
                "Embedding model short name", default=lemonade.embedding_model_name
            )
            lemonade.llamacpp_backend = _prompt(
                "llama.cpp backend",
                default=lemonade.llamacpp_backend,
                choices=["auto", "vulkan", "cpu"],
            )
            lemonade.generate_keys = _yes_no(
                "Generate API keys automatically?", default=True
            )

    # ── Kilo Code ────────────────────────────────────────────
    _section("Kilo Code")
    kilo = KiloSettings()
    if not non_interactive:
        if lemonade.enabled:
            _info("Kilo Code config will be auto-generated from Lemonade settings")
            kilo.config_file = "kilo.jsonc"
            if _yes_no("Use a kilo.jsonc skeleton for custom overrides?", default=True):
                kilo.skeleton_file = _prompt(
                    "Path to skeleton file",
                    default=kilo.skeleton_file,
                )
        elif _yes_no("Use a custom Kilo Code config?", default=False):
            kilo.config_file = _prompt("Path to kilo.jsonc", default="kilo.jsonc")

    # ── AI Gateway ───────────────────────────────────────────
    _section("AI Gateway (APISIX Rate Limiting)")
    gateway = GatewaySettings()
    if not non_interactive:
        gateway.enabled = _yes_no(
            "Enable APISIX AI Gateway with rate limiting?", default=False
        )
        if gateway.enabled:
            gateway.mode = _prompt(
                "Consumer mode",
                default=gateway.mode,
                choices=["per-user", "per-group"],
            )
            gateway.concurrency_limit = int(
                _prompt(
                    "Max concurrent requests per consumer",
                    default=str(gateway.concurrency_limit),
                )
            )
            gateway.token_limit = int(
                _prompt(
                    "Token limit per consumer (0 = no limit)",
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

    # ── Dashboard ────────────────────────────────────────────
    _section("Dashboard")
    dashboard = DashboardSettings()
    if not non_interactive:
        dashboard.host = _prompt("Dashboard bind address", default=dashboard.host)
        dashboard.port = int(_prompt("Dashboard port", default=str(dashboard.port)))
        dashboard.debug = _yes_no("Enable debug mode?", default=False)

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
        workspace=WorkspaceSettings(),
        lemonade=lemonade,
        kilo=kilo,
        gateway=gateway,
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
    print()

    return config
