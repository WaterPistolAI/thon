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
Certificate Generation Script forTHON Example

This script generates self-signed certificates using mkcert for local development.
It creates:
1. A local CA (if not exists)
2. A wildcard certificate (*.localhost) for all sandbox instances
3. Optional per-sandbox certificates

Usage:
    python ./scripts/generate-certs.py [--per-sandbox]

Requirements:
    - mkcert installed (https://github.com/FiloSottile/mkcert)
    - On Windows: mkcert --install first to install the local CA
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_mkcert() -> str:
    """Find mkcert executable in PATH."""
    mkcert = shutil.which("mkcert")
    if not mkcert:
        print("Error: mkcert not found in PATH")
        print("Install mkcert from: https://github.com/FiloSottile/mkcert")
        print()
        print("Windows:")
        print("  winget install FiloSottile.mkcert")
        print("  or: choco install mkcert")
        print()
        print("macOS:")
        print("  brew install mkcert")
        print()
        print("Linux:")
        print('  curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"')
        print("  sudo install mkcert -v /usr/local/bin/")
        sys.exit(1)
    return mkcert


def check_mkcert_installed() -> bool:
    """Check if mkcert CA is installed."""
    try:
        result = subprocess.run(
            [find_mkcert(), "-caroot"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def install_mkcert_ca() -> bool:
    """Install mkcert local CA."""
    print("Installing mkcert local CA...")
    try:
        subprocess.run(
            [find_mkcert(), "--install"],
            check=True,
            capture_output=True,
        )
        print("mkcert CA installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error installing mkcert CA: {e}")
        return False


def generate_wildcard_cert(cert_dir: Path) -> tuple[Path, Path]:
    """Generate wildcard certificate for *.localhost."""
    print("Generating wildcard certificate (*.localhost)...")

    cert_file = cert_dir / "localhost.pem"
    key_file = cert_dir / "localhost-key.pem"

    try:
        subprocess.run(
            [
                find_mkcert(),
                "-cert-file",
                str(cert_file),
                "-key-file",
                str(key_file),
                "*.localhost",
                "localhost",
                "127.0.0.1",
            ],
            check=True,
            capture_output=True,
        )
        print(f"Wildcard certificate generated: {cert_file}")
        return cert_file, key_file
    except subprocess.CalledProcessError as e:
        print(f"Error generating wildcard certificate: {e}")
        return None, None


def generate_per_sandbox_cert(cert_dir: Path, sandbox_id: str) -> tuple[Path, Path]:
    """Generate certificate for a specific sandbox."""
    print(f"Generating certificate for sandbox: {sandbox_id}")

    cert_file = cert_dir / f"{sandbox_id}.pem"
    key_file = cert_dir / f"{sandbox_id}-key.pem"

    try:
        subprocess.run(
            [
                find_mkcert(),
                "-cert-file",
                str(cert_file),
                "-key-file",
                str(key_file),
                f"{sandbox_id}.localhost",
                sandbox_id,
            ],
            check=True,
            capture_output=True,
        )
        print(f"Certificate generated: {cert_file}")
        return cert_file, key_file
    except subprocess.CalledProcessError as e:
        print(f"Error generating certificate for {sandbox_id}: {e}")
        return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Generate mkcert certificates forTHON example",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Install mkcert CA and generate wildcard cert
  python ./scripts/generate-certs.py

  # Generate per-sandbox certificates
  python ./scripts/generate-certs.py --per-sandbox

  # Generate certs for specific sandbox IDs
  python ./scripts/generate-certs.py --sandbox sandbox1 --sandbox sandbox2
        """,
    )

    parser.add_argument(
        "--per-sandbox",
        action="store_true",
        help="Generate per-sandbox certificates instead of wildcard",
    )
    parser.add_argument(
        "--sandbox",
        action="append",
        help="Sandbox ID for per-sandbox certificate (can be specified multiple times)",
    )
    parser.add_argument(
        "--cert-dir",
        type=Path,
        default=Path(__file__).parent / "certs",
        help="Directory to store certificates (default: ./certs)",
    )
    parser.add_argument(
        "--install-ca",
        action="store_true",
        help="Install mkcert CA before generating certificates",
    )

    args = parser.parse_args()

    # Create cert directory
    args.cert_dir.mkdir(parents=True, exist_ok=True)
    print(f"Certificate directory: {args.cert_dir.absolute()}")

    # Check/install mkcert CA
    if not check_mkcert_installed() or args.install_ca:
        if not install_mkcert_ca():
            sys.exit(1)

    # Generate certificates
    if args.per_sandbox:
        # Generate per-sandbox certificates
        sandbox_ids = args.sandbox or []
        if not sandbox_ids:
            print("Error: --sandbox required when using --per-sandbox")
            print("Example: --sandbox sandbox1 --sandbox sandbox2")
            sys.exit(1)

        for sandbox_id in sandbox_ids:
            cert_file, key_file = generate_per_sandbox_cert(args.cert_dir, sandbox_id)
            if cert_file and key_file:
                print(f"  Sandbox {sandbox_id}:")
                print(f"    Certificate: {cert_file}")
                print(f"    Key: {key_file}")
    else:
        # Generate wildcard certificate
        cert_file, key_file = generate_wildcard_cert(args.cert_dir)
        if cert_file and key_file:
            print()
            print("Certificate files:")
            print(f"  Certificate: {cert_file}")
            print(f"  Key: {key_file}")
            print()
            print("Usage in code-server:")
            print(
                f"  code-server --cert {cert_file} --cert-key {key_file} --bind-addr 0.0.0.0:44772"
            )


if __name__ == "__main__":
    main()
