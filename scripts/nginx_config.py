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
Nginx Configuration Generator forTHON Example

Generates a single combined nginx config with all location blocks in one
server block. Multiple server blocks with ``server_name _;`` on the same
port cause nginx to route all requests to only the first loaded block,
making per-port configs unworkable.

A single combined config avoids this: one ``server`` block listening on
80/443 with one ``location /{port}/`` block per instance.

  host mode:   endpoint 127.0.0.1:8443             -> location /8443/ -> proxy_pass http://127.0.0.1:8443/
  bridge mode: endpoint 127.0.0.1:55002/proxy/8443  -> location /55002/ -> proxy_pass http://127.0.0.1:55002/

Usage:
    from nginx_config import NginxConfigGenerator

    generator = NginxConfigGenerator()
    generator.generate_combined_config(
        ports=[55002, 47724],
        cert_path="/etc/nginx/ssl/thon.crt",
        key_path="/etc/nginx/ssl/thon.key",
    )
    generator.reload_nginx()
"""

import subprocess
from pathlib import Path


def _sudo_mkdir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        subprocess.run(
            ["sudo", "mkdir", "-p", str(path)],
            check=True,
        )
        subprocess.run(
            ["sudo", "chmod", "777", str(path)],
            check=True,
        )


LOCATION_BLOCK = """    location /{port}/ {{
        proxy_pass http://127.0.0.1:{port}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header Accept-Encoding gzip;
        proxy_redirect default;
        add_header Service-Worker-Allowed /;
        proxy_ssl_verify off;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering off;
        proxy_request_buffering off;
    }}

"""

# LOCATION_BLOCK = """    location /{port}/ {{
#         # 1. Force Nginx to recognize JavaScript and WASM correctly
#         include /etc/nginx/mime.types;
#         types {{
#             application/javascript js;
#             application/wasm wasm;
#             text/css css;
#         }}
#         default_type application/octet-stream;

#         proxy_pass http://127.0.0.1:{port}/;
#         proxy_http_version 1.1;
#         proxy_set_header Upgrade $http_upgrade;
#         proxy_set_header Connection "upgrade";
#         proxy_set_header Host $http_host;

#         # 2. Specific block for Service Worker to ensure headers are sent
#         location ~* service-worker\\.js$ {{
#             proxy_pass http://127.0.0.1:{port};
#             add_header Service-Worker-Allowed /;
#             add_header Content-Type application/javascript;
#             add_header X-Content-Type-Options nosniff;
#         }}

#         # 3. Security headers to enable Clipboard and Service Workers
#         proxy_set_header X-Real-IP $remote_addr;
#         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#         proxy_set_header X-Forwarded-Proto $scheme;

#         add_header Service-Worker-Allowed /;
#         add_header X-Content-Type-Options nosniff;

#         # Buffer sizes for long VS Code URIs
#         proxy_buffer_size 128k;
#         proxy_buffers 4 256k;
#         proxy_busy_buffers_size 256k;
#     }}
# """

CA_LOCATION_BLOCK = """    location = /ca.crt {{
        alias {ca_cert_path};
        default_type application/x-x509-ca-cert;
        add_header Content-Disposition 'attachment; filename="rootCA.crt"';
    }}

"""

COMBINED_CONFIG_TEMPLATE = """server {{
    listen 80;
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name _;

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

{ca_location}{location_blocks}}}
"""

CONFIG_NAME = "sandbox-thon"


class NginxConfigGenerator:

    def __init__(
        self,
        sites_available_dir: str = "/etc/nginx/sites-available",
        sites_enabled_dir: str = "/etc/nginx/sites-enabled",
        reload_command: str = "sudo nginx -s reload",
        test_command: str = "sudo nginx -t",
    ):
        self.sites_available_dir = Path(sites_available_dir)
        self.sites_enabled_dir = Path(sites_enabled_dir)
        self.reload_command = reload_command
        self.test_command = test_command

        _sudo_mkdir(self.sites_available_dir)
        _sudo_mkdir(self.sites_enabled_dir)

    @staticmethod
    def _sudo_unlink(path: Path) -> None:
        try:
            path.unlink()
        except PermissionError:
            subprocess.run(["sudo", "rm", "-f", str(path)], check=True)

    def _remove_default_site(self) -> None:
        default_symlink = self.sites_enabled_dir / "default"
        if default_symlink.exists() or default_symlink.is_symlink():
            try:
                self._sudo_unlink(default_symlink)
                print("[Nginx] Removed default site to avoid conflict")
            except OSError as e:
                print(f"[Nginx] Warning: Could not remove default site: {e}")

    def generate_combined_config(
        self,
        ports: list[int],
        cert_path: str,
        key_path: str,
        ca_cert_path: str = "",
    ) -> str:
        """Generate a single combined nginx config with all port locations.

        Args:
            ports: List of endpoint ports to create location blocks for.
            cert_path: Path to SSL certificate file.
            key_path: Path to SSL private key file.
            ca_cert_path: Optional path to CA cert for /ca.crt download.

        Returns:
            Path to the generated config file.
        """
        location_blocks = ""
        for port in ports:
            location_blocks += LOCATION_BLOCK.format(port=port)

        ca_location = ""
        if ca_cert_path:
            ca_location = CA_LOCATION_BLOCK.format(ca_cert_path=ca_cert_path)

        config_content = COMBINED_CONFIG_TEMPLATE.format(
            cert_path=cert_path,
            key_path=key_path,
            ca_location=ca_location,
            location_blocks=location_blocks,
        )

        config_path = self.sites_available_dir / CONFIG_NAME

        try:
            try:
                config_path.write_text(config_content)
            except PermissionError:
                tmp_path = Path(f"/tmp/{CONFIG_NAME}")
                tmp_path.write_text(config_content)
                subprocess.run(
                    ["sudo", "cp", str(tmp_path), str(config_path)],
                    check=True,
                )
                tmp_path.unlink(missing_ok=True)
            print(f"[Nginx] Combined config created: {config_path} ({len(ports)} locations)")
        except IOError as e:
            raise RuntimeError(f"Failed to write nginx config: {e}") from e

        self._enable_config(str(config_path))
        return str(config_path)

    def _enable_config(self, config_path: str) -> None:
        config_filename = Path(config_path).name
        symlink_path = self.sites_enabled_dir / config_filename

        try:
            if symlink_path.exists() or symlink_path.is_symlink():
                self._sudo_unlink(symlink_path)

            try:
                symlink_path.symlink_to(config_path)
            except PermissionError:
                subprocess.run(
                    ["sudo", "ln", "-s", config_path, str(symlink_path)],
                    check=True,
                )
            print(f"[Nginx] Config enabled: {symlink_path}")
        except OSError as e:
            raise RuntimeError(f"Failed to enable nginx config: {e}") from e

    def reload_nginx(self) -> None:
        try:
            subprocess.run(
                self.reload_command,
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )
            print("[Nginx] Reloaded successfully")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to reload nginx: {e.stderr or e.stdout}"
            ) from e

    def test_config(self) -> bool:
        try:
            subprocess.run(
                self.test_command,
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            print("[Nginx] Config test failed:")
            print(f"[Nginx] stderr: {e.stderr}")
            print(f"[Nginx] stdout: {e.stdout}")
            return False

    def cleanup_all(self) -> None:
        cleaned = False

        for config_path in self.sites_available_dir.glob(f"{CONFIG_NAME}*"):
            self._delete_config(str(config_path))
            cleaned = True

        for symlink_path in self.sites_enabled_dir.glob(f"{CONFIG_NAME}*"):
            if symlink_path.is_symlink():
                try:
                    self._sudo_unlink(symlink_path)
                    print(f"[Nginx] Removed symlink: {symlink_path}")
                    cleaned = True
                except OSError as e:
                    print(f"[Nginx] Warning: Failed to remove symlink: {e}")

        if not cleaned:
            print("[Nginx] No sandbox configs to clean up")
            return

        try:
            self.reload_nginx()
        except RuntimeError as e:
            print(f"[Nginx] Warning: Reload after cleanup failed: {e}")

    def _delete_config(self, config_path: str) -> None:
        config_file = Path(config_path)

        try:
            if config_file.exists():
                self._sudo_unlink(config_file)
                print(f"[Nginx] Config deleted: {config_file}")
        except OSError as e:
            print(f"[Nginx] Warning: Failed to delete config: {e}")
