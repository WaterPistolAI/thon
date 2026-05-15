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

"""THON CLI — unified entry point for install, config, and instance management.

Workflow:
    thon install    # System packages + ~/.sandbox.toml (run once)
    thon init       # Interactive config wizard → thon.yaml
    thon setup      # Apply thon.yaml to services (Lemonade, APISIX, .env)
    thon gateway    # Apply gateway config only (APISIX consumers + routes)
    thon run        # Start the API server
    thon launch     # Launch VS Code instances (batch mode)
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

from thon.config import DEFAULT_CONFIG_PATH, THON_DIR, ThonConfig  # noqa: E402


def _ensure_apisix_running() -> None:
    """Ensure APISIX and its dependencies (etcd, redis) are running."""
    for svc in ["etcd", "redis-server"]:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", svc], capture_output=True
        )
        if result.returncode != 0:
            print(f"  Starting {svc}...")
            subprocess.run(["sudo", "systemctl", "start", svc], check=False)

    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", "apisix"], capture_output=True
    )
    if result.returncode != 0:
        print("  Starting APISIX...")
        subprocess.run(["sudo", "systemctl", "reset-failed", "apisix"], check=False)
        subprocess.run(["sudo", "systemctl", "start", "apisix"], check=False)
        import time

        for _ in range(15):
            probe = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    "http://127.0.0.1:9180/apisix/admin/routes",
                    "-H",
                    "X-API-KEY: probe",
                ],
                capture_output=True,
                text=True,
            )
            if probe.stdout.strip() in ("200", "401"):
                print("  APISIX is ready")
                return
            time.sleep(1)
        print("  Warning: APISIX did not become ready within 15s")


def _load_config(path: Optional[str] = None) -> ThonConfig:
    """Load config from the given path, falling back to ~/.thon/thon.yaml."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.is_file():
        legacy = Path("thon.yaml")
        if legacy.is_file():
            print(f"Note: Found {legacy} — consider moving to {DEFAULT_CONFIG_PATH}")
            p = legacy
        else:
            print(f"Error: Config file not found at {p}")
            print("Run `python -m thon init` to create one.")
            sys.exit(1)
    return ThonConfig.from_yaml(p)


def cmd_install(args: argparse.Namespace) -> None:
    from thon.install import run_install

    run_install(
        non_interactive=getattr(args, "non_interactive", False),
        install_apisix_flag=getattr(args, "with_apisix", None),
        install_lemonade_flag=getattr(args, "with_lemonade", None),
        ssl_dir=getattr(args, "ssl_dir", "/etc/nginx/ssl"),
    )


def cmd_init(args: argparse.Namespace) -> None:
    from thon.interactive import run_interactive

    run_interactive(
        config_path=args.config,
        non_interactive=getattr(args, "non_interactive", False),
    )


def _run_gateway_setup(config: ThonConfig) -> None:
    """Run APISIX gateway setup from thon.yaml config."""
    _ensure_apisix_running()

    apisix_py = PROJECT_ROOT / "scripts" / "apisix_gateway.py"
    if not apisix_py.is_file():
        print("  Error: apisix_gateway.py not found")
        return

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
    ]
    if config.gateway.admin_key:
        cmd.extend(["--admin-key", config.gateway.admin_key])
    if config.gateway.redis_host:
        cmd.extend(["--redis-host", config.gateway.redis_host])
    if config.external_ip:
        cmd.extend(["--external-ip", config.external_ip])
    if config.gateway.mode == "per-group":
        cmd.append("--per-group")

    if config.lemonade.api_key:
        cmd.extend(["--lemonade-api-key", config.lemonade.api_key])

    lemonade_model = f"user.{config.lemonade.model_name}"
    cmd.extend(["--lemonade-model", lemonade_model])

    lemonade_embedding = f"user.{config.lemonade.embedding_model_name}"
    cmd.extend(["--embedding-model", lemonade_embedding])

    cmd.extend(
        [
            "--concurrency-limit",
            str(config.gateway.concurrency_limit),
            "--token-limit",
            str(config.gateway.token_limit),
            "--token-window",
            str(config.gateway.token_window),
        ]
    )

    if config.groups:
        groups_yaml = PROJECT_ROOT / "groups.yaml"
        if groups_yaml.is_file():
            cmd.extend(["--groups", str(groups_yaml)])

    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(
            "  Warning: APISIX gateway setup failed. "
            "Ensure APISIX is installed (thon install --with-apisix) "
            "and the admin key is configured."
        )


def cmd_setup(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    config.apply_env()

    print()
    print("=" * 60)
    print("  THON Setup — configuring services from thon.yaml")
    print("=" * 60)
    print()

    step = 0
    total = 4

    # 1. SSL directory & certs
    step += 1
    if config.nginx.enabled:
        print(f"\n[{step}/{total}] SSL setup...")
        ssl_dir = config.nginx.ssl_dir
        os.makedirs(ssl_dir, exist_ok=True)
        print(f"  SSL dir: {ssl_dir}")

        if config.nginx.domain and config.nginx.ssl_provider in ("auto", "certbot"):
            print(f"  Domain: {config.nginx.domain} (Let's Encrypt)")
            print("  Installing certbot if needed...")
            try:
                subprocess.run(
                    [
                        "sudo",
                        "apt-get",
                        "install",
                        "-y",
                        "certbot",
                        "python3-certbot-nginx",
                    ],
                    check=False,
                    capture_output=True,
                )
            except Exception:
                pass
            from scripts.ssl_cert import SSLCertificateGenerator

            ssl_gen = SSLCertificateGenerator(output_dir=ssl_dir)
            try:
                cert, key = ssl_gen.generate_server_cert(
                    domain=config.nginx.domain,
                    ssl_provider="certbot",
                    certbot_email=config.nginx.certbot_email or None,
                )
                print(f"  Cert: {cert}")
                print(f"  Key:  {key}")
            except Exception as e:
                print(f"  Certbot failed: {e}")
                print(
                    f"  You can retry manually: sudo certbot --nginx -d {config.nginx.domain}"
                )
                print("  Falling back to mkcert/openssl cert for nginx...")
                try:
                    cert, key = ssl_gen.generate_server_cert(
                        server_ip=config.external_ip or None,
                    )
                    print(f"  Fallback cert: {cert}")
                    print(f"  Fallback key:  {key}")
                except Exception as fallback_err:
                    print(f"  Fallback cert generation also failed: {fallback_err}")
        else:
            print("  Provider: mkcert/openssl (no domain configured)")
    else:
        print(f"\n[{step}/{total}] SSL — skipped (nginx disabled)")

    # 2. Lemonade server
    step += 1
    if config.lemonade.enabled:
        print(f"\n[{step}/{total}] Lemonade server...")
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
                "--ctx-size-per-user",
                str(config.lemonade.ctx_size_per_user),
                "--embedding-ctx-size-per-user",
                str(config.lemonade.embedding_ctx_size_per_user),
                "--prefer-system"
                if config.lemonade.prefer_system
                else "--no-prefer-system",
                "--llamacpp-bin",
                config.lemonade.llamacpp_bin,
                "--rocm-channel",
                config.lemonade.rocm_channel,
            ]

            llamacpp_args = config.lemonade.llamacpp.to_args(num_users)
            cmd.extend(["--llamacpp-args", llamacpp_args])

            embedding_args = config.lemonade.llamacpp.to_embedding_args(num_users)
            cmd.extend(["--embedding-llamacpp-args", embedding_args])
            if config.lemonade.generate_keys:
                cmd.append("--generate-keys")
            if config.external_ip:
                cmd.extend(["--external-ip", config.external_ip])
            if config.lemonade.api_key:
                cmd.extend(["--api-key", config.lemonade.api_key])
            if config.lemonade.admin_api_key:
                cmd.extend(["--admin-api-key", config.lemonade.admin_api_key])

            kilo_output = str(config.kilo.resolved_config_file)
            cmd.extend(["--kilo-config", kilo_output])

            skeleton = config.kilo.skeleton_file
            if skeleton:
                skeleton_path = PROJECT_ROOT / skeleton
                if skeleton_path.is_file():
                    cmd.extend(["--kilo-skeleton", str(skeleton_path)])

            print(f"  Running: {' '.join(cmd)}")
            subprocess.run(cmd, check=False)

            if config.lemonade.generate_keys and not config.lemonade.api_key:
                _sync_lemonade_keys(config)
        else:
            print("  Skipping (lemonade_server.py not found)")
    else:
        print(f"\n[{step}/{total}] Lemonade — skipped (disabled)")

    # 3. AI Gateway
    step += 1
    if config.gateway.enabled:
        print(f"\n[{step}/{total}] AI Gateway...")
        _run_gateway_setup(config)
    else:
        print(f"\n[{step}/{total}] AI Gateway — skipped (disabled)")

    # 4. Generate .env
    step += 1
    print(f"\n[{step}/{total}] Generating .env file...")
    env_path = PROJECT_ROOT / ".env"
    config.to_env_file(env_path)
    print(f"  Written: {env_path}")

    # Summary
    print()
    print("  Setup complete!")
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
    print("  Run `python -m thon run` to start the API server.")
    print("  Run `python -m thon launch` to launch VS Code instances.")


def _sync_lemonade_keys(config: ThonConfig) -> None:
    """Read API keys from lemonade systemd override and write into config + .env."""
    import re

    for service_name in ("lemonade-server", "lemond"):
        override_path = Path(
            f"/etc/systemd/system/{service_name}.service.d/override.conf"
        )
        if not override_path.is_file():
            continue

        content = override_path.read_text()
        api_match = re.search(r'LEMONADE_API_KEY="?([^"\s]+)"?', content)
        admin_match = re.search(r'LEMONADE_ADMIN_API_KEY="?([^"\s]+)"?', content)

        if api_match:
            config.lemonade.api_key = api_match.group(1)
        if admin_match:
            config.lemonade.admin_api_key = admin_match.group(1)

        if api_match or admin_match:
            env_path = PROJECT_ROOT / ".env"
            if env_path.is_file():
                lines = env_path.read_text().splitlines()
                updated: list[str] = []
                found_api = False
                found_admin = False
                for line in lines:
                    if line.startswith("LEMONADE_API_KEY="):
                        updated.append(f"LEMONADE_API_KEY={config.lemonade.api_key}")
                        found_api = True
                    elif line.startswith("LEMONADE_ADMIN_API_KEY="):
                        updated.append(
                            f"LEMONADE_ADMIN_API_KEY={config.lemonade.admin_api_key}"
                        )
                        found_admin = True
                    else:
                        updated.append(line)
                if not found_api and config.lemonade.api_key:
                    updated.append(f"LEMONADE_API_KEY={config.lemonade.api_key}")
                if not found_admin and config.lemonade.admin_api_key:
                    updated.append(
                        f"LEMONADE_ADMIN_API_KEY={config.lemonade.admin_api_key}"
                    )
                env_path.write_text("\n".join(updated) + "\n")
            print("  Synced Lemonade API keys to .env")
            return


def cmd_run(args: argparse.Namespace) -> None:
    THON_DIR.mkdir(parents=True, exist_ok=True)
    p = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
    if not p.is_file():
        legacy = Path("thon.yaml")
        if legacy.is_file():
            p = legacy
    if p.is_file():
        config = ThonConfig.from_yaml(p)
        config.apply_env()
    else:
        config = None

    log_level = getattr(args, "log_level", None)
    if config and config.log_level:
        log_level = log_level or config.log_level
    log_level = (log_level or "INFO").upper()
    os.environ.setdefault("THON_LOG_LEVEL", log_level)

    host = (config.dashboard.host if config else None) or "0.0.0.0"
    port = (config.dashboard.port if config else None) or 8100
    debug = config.dashboard.debug if config else False

    print()
    print("═" * 60)
    print("  THON API Server")
    print("═" * 60)
    print(f"  Host:      {host}")
    print(f"  Port:      {port}")
    print(f"  Log level: {log_level.upper()}")
    print(f"  Debug:     {'on' if debug else 'off'}")
    print(
        f"  API docs:  http://{host if host != '0.0.0.0' else 'localhost'}:{port}/docs"
    )
    print("═" * 60)
    print()

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=debug,
        log_level=log_level.lower(),
    )


def cmd_launch(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    if getattr(args, "demo", False):
        config.demo = True
    config.apply_env()

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from main import run_from_config  # pyright: ignore[reportMissingImports]

    group_filter = getattr(args, "group", None)
    asyncio.run(run_from_config(config, group_filter=group_filter))


def cmd_gateway(args: argparse.Namespace) -> None:
    config = _load_config(args.config)
    config.apply_env()

    print()
    print("=" * 60)
    print("  THON Gateway — APISIX setup from thon.yaml")
    print("=" * 60)
    print()

    if not config.gateway.enabled:
        print("  Gateway is disabled in thon.yaml. Enable it with thon init.")
        if not _yes_no("Run anyway?"):
            return

    _run_gateway_setup(config)

    print()
    print("  Gateway setup complete.")
    print()


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




def cmd_nginx(args: argparse.Namespace) -> None:
    """Manage nginx reverse proxy configs."""
    from app.config import AppConfig
    from app.services.sandbox_service import SandboxService

    cfg = AppConfig.from_env()
    print(f"[Nginx] Domain: {cfg.nginx.domain or '(none)'}")
    print(f"[Nginx] External IP: {cfg.nginx.external_ip or '(none)'}")
    print(f"[Nginx] SSL provider: {cfg.nginx.ssl_provider}")

    svc = SandboxService(cfg)

    if args.nginx_command == "sync":
        ports = svc.sync_nginx()
        if ports:
            print(f"[Nginx] Synced {len(ports)} port(s): {ports}")
        else:
            print("[Nginx] No active instance ports found")
            # Even with no ports, regenerate config with correct SSL
            ng = svc.nginx
            if ng:
                ng.cleanup_all()
                print("[Nginx] Cleaned up (no active instances)")
    elif args.nginx_command == "cleanup":
        ng = svc.nginx
        if ng:
            ng.cleanup_all()
            print("[Nginx] All THON configs removed")
        else:
            print("[Nginx] Not available (external_ip not configured)")


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


def _validate_config(config: ThonConfig) -> list[str]:
    """Return a list of validation error messages."""
    errors: list[str] = []

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


def _resolve_path(path_str: str) -> Path:
    """Resolve a path relative to PROJECT_ROOT or ~/.thon/ if not absolute."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    resolved = PROJECT_ROOT / p
    if resolved.exists():
        return resolved
    thon_resolved = THON_DIR / p
    if thon_resolved.exists():
        return thon_resolved
    return p


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
  thon install                  Install system prerequisites
  thon install --with-apisix    Install with APISIX AI Gateway
  thon init                     Interactive config wizard
  thon init --non-interactive   Generate config with defaults
  thon setup                    Configure services from thon.yaml
  thon gateway                  Apply APISIX gateway config only
  thon run                      Start the API server
  thon launch                   Launch VS Code instances (batch mode)
  thon config show              Display current config
  thon config env               Export config as .env file
  thon config validate          Validate thon.yaml
  thon cleanup                  Tear down all resources
        """,
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=f"Path to thon.yaml (default: {DEFAULT_CONFIG_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # install
    install_parser = subparsers.add_parser(
        "install", help="Install system prerequisites (run once)"
    )
    install_parser.add_argument(
        "--non-interactive",
        action="store_true",
        default=False,
        help="Install all optional components without prompting",
    )
    install_parser.add_argument(
        "--with-apisix",
        action="store_true",
        default=None,
        help="Install APISIX AI Gateway packages",
    )
    install_parser.add_argument(
        "--with-lemonade",
        action="store_true",
        default=None,
        help="Install Lemonade server packages",
    )
    install_parser.add_argument(
        "--ssl-dir",
        type=str,
        default="/etc/nginx/ssl",
        help="SSL certificate directory (default: /etc/nginx/ssl)",
    )

    # init
    init_parser = subparsers.add_parser("init", help="Interactive config wizard")
    init_parser.add_argument(
        "--non-interactive",
        action="store_true",
        default=False,
        help="Generate config with defaults (no prompts)",
    )

    # setup
    subparsers.add_parser(
        "setup", help="Configure services from thon.yaml (run after init)"
    )

    # gateway
    subparsers.add_parser(
        "gateway", help="Apply APISIX gateway config only (consumers + routes)"
    )

    # run
    run_parser = subparsers.add_parser(
        "run", help="Start the THON API server (default)"
    )
    run_parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: from thon.yaml or INFO)",
    )

    # launch
    launch_parser = subparsers.add_parser(
        "launch", help="Launch VS Code instances from thon.yaml (legacy batch mode)"
    )
    launch_parser.add_argument(
        "--group", type=str, default=None, help="Launch only this group"
    )
    launch_parser.add_argument(
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

    # nginx
    nginx_parser = subparsers.add_parser("nginx", help="Nginx management")
    nginx_sub = nginx_parser.add_subparsers(dest="nginx_command", help="Nginx sub-command")
    nginx_sub.add_parser("sync", help="Regenerate nginx config from active instances")
    nginx_sub.add_parser("cleanup", help="Remove all THON nginx configs")

    # cleanup
    subparsers.add_parser("cleanup", help="Tear down all resources")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "install":
        cmd_install(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "gateway":
        cmd_gateway(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "launch":
        cmd_launch(args)
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
    elif args.command == "nginx":
        if not args.nginx_command:
            print("Usage: thon nginx <sync|cleanup>")
            sys.exit(1)
        cmd_nginx(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)


if __name__ == "__main__":
    main()
