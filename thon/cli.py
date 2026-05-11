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

"""THON CLI — unified entry point for interactive setup, config, and instance management.

Usage:
    thon init                  # Interactive guided setup wizard
    thon setup                 # Install prerequisites + configure from thon.yaml
    thon run                   # Start VS Code instances from thon.yaml
    thon config show           # Display current config
    thon config env            # Export config as .env file
    thon config validate       # Validate thon.yaml
    thon cleanup               # Tear down all resources
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))  # noqa: E402

from thon.config import DEFAULT_CONFIG_PATH, ThonConfig  # noqa: E402


def _load_config(path: Optional[str] = None) -> ThonConfig:
    """Load config from the given path, falling back to ./thon.yaml."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.is_file():
        print(f"Error: Config file not found at {p}")
        print("Run `python -m thon init` to create one.")
        sys.exit(1)
    return ThonConfig.from_yaml(p)


def cmd_init(args: argparse.Namespace) -> None:
    from thon.interactive import run_interactive

    run_interactive(
        config_path=args.config,
        non_interactive=getattr(args, "non_interactive", False),
    )


def cmd_setup(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    config.apply_env()

    print("=" * 60)
    print("  THON Setup — installing prerequisites and configuring")
    print("=" * 60)
    print()

    # 1. System prerequisites
    print("[1/6] System prerequisites...")
    setup_sh = PROJECT_ROOT / "scripts" / "setup.sh"
    if setup_sh.is_file():
        env = os.environ.copy()
        if config.gateway.enabled:
            env["INSTALL_GATEWAY"] = "true"
        subprocess.run(["bash", str(setup_sh)], env=env, check=False)
    else:
        print("  Skipping (setup.sh not found)")

    # 2. Nginx SSL directory
    if config.nginx.enabled:
        print("\n[2/6] SSL directory...")
        ssl_dir = config.nginx.ssl_dir
        os.makedirs(ssl_dir, exist_ok=True)
        print(f"  SSL dir: {ssl_dir}")
    else:
        print("\n[2/6] SSL — skipped (nginx disabled)")

    # 3. Lemonade server
    if config.lemonade.enabled:
        print("\n[3/6] Lemonade server...")
        lemonade_py = PROJECT_ROOT / "scripts" / "lemonade_server.py"
        if lemonade_py.is_file():
            num_users = config.total_users()
            if num_users < 1:
                num_users = 1

            cmd = [
                sys.executable,
                str(lemonade_py),
                "run",
                "--model",
                config.lemonade.model,
                "--model-name",
                config.lemonade.model_name,
                "--embedding-model",
                config.lemonade.embedding_model,
                "--embedding-model-name",
                config.lemonade.embedding_model_name,
                "--num-users",
                str(num_users),
                "--port",
                str(config.lemonade.port),
                "--host",
                config.lemonade.host,
                "--llamacpp-backend",
                config.lemonade.llamacpp_backend,
                "--skip-install",
            ]
            if config.lemonade.generate_keys:
                cmd.append("--generate-keys")
            if config.external_ip:
                cmd.extend(["--external-ip", config.external_ip])
            if config.lemonade.api_key:
                cmd.extend(["--api-key", config.lemonade.api_key])
            if config.lemonade.admin_api_key:
                cmd.extend(["--admin-api-key", config.lemonade.admin_api_key])

            kilo_output = config.kilo.config_file or "kilo.jsonc"
            cmd.extend(["--kilo-config", kilo_output])

            skeleton = config.kilo.skeleton_file
            if skeleton:
                skeleton_path = PROJECT_ROOT / skeleton
                if skeleton_path.is_file():
                    cmd.extend(["--kilo-skeleton", str(skeleton_path)])

            print(f"  Running: {' '.join(cmd)}")
            subprocess.run(cmd, check=False)
        else:
            print("  Skipping (lemonade_server.py not found)")
    else:
        print("\n[3/6] Lemonade — skipped (disabled)")

    # 4. AI Gateway
    if config.gateway.enabled:
        print("\n[4/6] AI Gateway...")
        apisix_py = PROJECT_ROOT / "scripts" / "apisix_gateway.py"
        if apisix_py.is_file():
            lemonade_host = config.lemonade.host
            if lemonade_host == "0.0.0.0":
                lemonade_host = "127.0.0.1"
            lemonade_url = f"http://{lemonade_host}:{config.lemonade.port}"

            cmd = [
                sys.executable,
                str(apisix_py),
                "setup",
                "--lemonade-url",
                lemonade_url,
                "--concurrency-limit",
                str(config.gateway.concurrency_limit),
                "--token-limit",
                str(config.gateway.token_limit),
                "--token-window",
                str(config.gateway.token_window),
            ]
            if config.gateway.admin_key:
                cmd.extend(["--admin-key", config.gateway.admin_key])
            if config.gateway.redis_host:
                cmd.extend(["--redis-host", config.gateway.redis_host])
            if config.external_ip:
                cmd.extend(["--external-ip", config.external_ip])
            if config.gateway.mode == "per-group":
                cmd.append("--per-group")

            groups_yaml = PROJECT_ROOT / "groups.yaml"
            if groups_yaml.is_file():
                cmd.extend(["--groups", str(groups_yaml)])

            print(f"  Running: {' '.join(cmd)}")
            subprocess.run(cmd, check=False)
        else:
            print("  Skipping (apisix_gateway.py not found)")
    else:
        print("\n[4/6] AI Gateway — skipped (disabled)")

    # 5. Generate .env
    print("\n[5/6] Generating .env file...")
    env_path = PROJECT_ROOT / ".env"
    config.to_env_file(env_path)
    print(f"  Written: {env_path}")

    # 6. Summary
    print("\n[6/6] Setup complete!")
    print()
    print("  Configuration summary:")
    print(f"    External IP:  {config.external_ip or '(auto-detect)'}")
    print(f"    Groups:        {len(config.groups)} ({config.total_users()} users)")
    print(f"    Nginx/SSL:     {'enabled' if config.nginx.enabled else 'disabled'}")
    print(f"    Secure VS Code:{'enabled' if config.vscode.secure else 'disabled'}")
    print(f"    Lemonade:      {'enabled' if config.lemonade.enabled else 'disabled'}")
    print(f"    AI Gateway:    {'enabled' if config.gateway.enabled else 'disabled'}")
    print(f"    Dashboard:     {config.dashboard.host}:{config.dashboard.port}")
    print()
    print("  Run `python -m thon run` to start instances.")


def cmd_run(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    if getattr(args, "demo", False):
        config.demo = True
    config.apply_env()

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from main import run_from_config  # pyright: ignore[reportMissingImports]

    group_filter = getattr(args, "group", None)
    asyncio.run(run_from_config(config, group_filter=group_filter))


def cmd_config_show(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    import yaml

    print(
        yaml.dump(
            config.model_dump(exclude_defaults=False),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    )


def cmd_config_env(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    env_path = args.output or str(PROJECT_ROOT / ".env")
    result = config.to_env_file(env_path)
    print(f"Written to {result}")
    print()
    for key, value in sorted(config.to_env_dict().items()):
        display_val = value if "KEY" not in key and "SECRET" not in key else "***"
        print(f"  {key}={display_val}")


def cmd_config_validate(args: argparse.Namespace) -> None:
    try:
        config = _load_config(args.config)
        errors = _validate_config(config)
        if errors:
            print("Validation errors:")
            for err in errors:
                print(f"  ✗ {err}")
            sys.exit(1)
        print("✓ Config is valid")
        print(f"  Groups:  {len(config.groups)} ({config.total_users()} users)")
        print(f"  Nginx:   {'enabled' if config.nginx.enabled else 'disabled'}")
        print(f"  Lemonade:{'enabled' if config.lemonade.enabled else 'disabled'}")
        print(f"  Gateway: {'enabled' if config.gateway.enabled else 'disabled'}")
    except Exception as e:
        print(f"✗ Config parse error: {e}")
        sys.exit(1)


def cmd_cleanup(args: argparse.Namespace) -> None:
    main_py = PROJECT_ROOT / "scripts" / "main.py"
    if main_py.is_file():
        subprocess.run([sys.executable, str(main_py), "--cleanup"], check=False)

    if _yes_no("Stop Lemonade server?"):
        lemonade_py = PROJECT_ROOT / "scripts" / "lemonade_server.py"
        if lemonade_py.is_file():
            subprocess.run([sys.executable, str(lemonade_py), "stop"], check=False)

    if _yes_no("Clean up AI Gateway?"):
        apisix_py = PROJECT_ROOT / "scripts" / "apisix_gateway.py"
        if apisix_py.is_file():
            subprocess.run([sys.executable, str(apisix_py), "cleanup"], check=False)

    print("Cleanup complete.")


def _write_temp_groups(config: ThonConfig) -> None:
    """Write groups from config to a temp YAML for scripts/main.py."""
    import yaml

    data = {"groups": {name: {"users": users} for name, users in config.groups.items()}}
    target = PROJECT_ROOT / ".thon-groups.yaml"
    target.write_text(yaml.dump(data, default_flow_style=False))
    print(f"  Wrote groups to {target}")


def _resolve_path(path_str: str) -> Path:
    """Resolve a path relative to PROJECT_ROOT if not absolute."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    resolved = PROJECT_ROOT / p
    if resolved.exists():
        return resolved
    return p


def _validate_config(config: ThonConfig) -> list[str]:
    """Return a list of validation error messages."""
    errors: list[str] = []

    if not config.groups:
        errors.append("No groups defined")

    for group_name, users in config.groups.items():
        if not users:
            errors.append(f"Group '{group_name}' has no users")

    if config.gateway.enabled and not config.lemonade.enabled:
        if not config.gateway.admin_key:
            errors.append(
                "Gateway enabled but no Lemonade server — set lemonade.enabled=true"
            )

    if config.auth.enabled:
        has_provider = any(
            [
                config.auth.github.client_id,
                config.auth.gitlab.client_id,
                config.auth.linkedin.client_id,
            ]
        )
        if not has_provider:
            errors.append("Auth enabled but no OAuth provider configured")

    if config.vscode.settings_file:
        p = _resolve_path(config.vscode.settings_file)
        if not p.is_file():
            errors.append(f"VS Code settings file not found: {p}")

    if (
        config.kilo.config_file
        and not config.lemonade.enabled
        and not config.gateway.enabled
    ):
        p = _resolve_path(config.kilo.config_file)
        if not p.is_file():
            errors.append(f"Kilo config file not found: {p}")

    return errors


def _yes_no(label: str, default: bool = False) -> bool:
    d = "Y/n" if default else "y/N"
    raw = input(f"  {label} [{d}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "1", "true")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="thon",
        description="THON — The Hackathon Organizer Node",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  thon init                    Interactive setup wizard
  thon init --non-interactive  Generate config with defaults
  thon setup                   Install prerequisites + configure
  thon run                     Start VS Code instances
  thon config show             Display current config
  thon config env              Export config as .env file
  thon config validate         Validate thon.yaml
  thon cleanup                 Tear down all resources
        """,
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to thon.yaml (default: ./thon.yaml)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # init
    init_parser = subparsers.add_parser("init", help="Interactive setup wizard")
    init_parser.add_argument(
        "--non-interactive",
        action="store_true",
        default=False,
        help="Generate config with defaults (no prompts)",
    )

    # setup
    subparsers.add_parser(
        "setup", help="Install prerequisites and configure from thon.yaml"
    )

    # run
    run_parser = subparsers.add_parser(
        "run", help="Start VS Code instances from thon.yaml"
    )
    run_parser.add_argument(
        "--group", type=str, default=None, help="Run only this group"
    )
    run_parser.add_argument(
        "--demo",
        action="store_true",
        default=False,
        help="Create a default workspace when no users/groups are configured",
    )

    # config
    config_parser = subparsers.add_parser("config", help="Configuration management")
    config_sub = config_parser.add_subparsers(
        dest="config_command", help="Config sub-command"
    )
    config_sub.add_parser("show", help="Display current config")
    env_sub = config_sub.add_parser("env", help="Export config as .env file")
    env_sub.add_argument("--output", type=str, default=None, help="Output .env path")
    config_sub.add_parser("validate", help="Validate thon.yaml")

    # cleanup
    subparsers.add_parser("cleanup", help="Tear down all resources")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        cmd_init(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "config":
        if not args.config_command:
            config_parser.print_help()
            sys.exit(1)
        if args.config_command == "show":
            cmd_config_show(args)
        elif args.config_command == "env":
            cmd_config_env(args)
        elif args.config_command == "validate":
            cmd_config_validate(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)


if __name__ == "__main__":
    main()
