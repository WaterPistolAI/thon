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

"""Nginx config management for THON sandbox instances.

Wraps the script-level ``NginxConfigGenerator`` for use by the API server.
Generates a single combined nginx config with location blocks for all
active sandbox endpoint ports.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SITES_AVAILABLE = Path("/etc/nginx/sites-available")
SITES_ENABLED = Path("/etc/nginx/sites-enabled")
SSL_DIR = Path("/etc/nginx/ssl")
CONFIG_NAME = "sandbox-thon"

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
    server_name {server_name};

    ssl_certificate {cert_path};
    ssl_certificate_key {key_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

{ca_location}{location_blocks}}}
"""


class NginxConfigGenerator:
    """Generates combined nginx reverse-proxy config for sandbox instances."""

    def __init__(
        self,
        sites_available_dir: str | Path = SITES_AVAILABLE,
        sites_enabled_dir: str | Path = SITES_ENABLED,
        ssl_dir: str | Path = SSL_DIR,
        domain: str = "",
    ) -> None:
        self.sites_available_dir = Path(sites_available_dir)
        self.sites_enabled_dir = Path(sites_enabled_dir)
        self.ssl_dir = Path(ssl_dir)
        self.domain = domain

    def _find_cert_pair(self) -> tuple[str, str]:
        """Find SSL cert/key. Prefers Let's Encrypt if domain is configured."""
        if self.domain:
            le_cert = Path(f"/etc/letsencrypt/live/{self.domain}/fullchain.pem")
            le_key = Path(f"/etc/letsencrypt/live/{self.domain}/privkey.pem")
            if le_cert.exists() and le_key.exists():
                return str(le_cert), str(le_key)
            result = subprocess.run(
                ["sudo", "test", "-r", str(le_cert)],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                return str(le_cert), str(le_key)
        for cert_path in sorted(self.ssl_dir.iterdir()):
            name = cert_path.name
            if name.endswith("-key.pem") or name.endswith(".key"):
                continue
            if name.endswith(".crt") or name.endswith(".pem"):
                stem = name.rsplit(".", 1)[0]
                for key_suffix in ("-key.pem", ".key"):
                    key_path = self.ssl_dir / f"{stem}{key_suffix}"
                    if key_path.exists():
                        return str(cert_path), str(key_path)
        raise FileNotFoundError(f"No SSL cert/key pair found in {self.ssl_dir}")

    def _find_ca_cert(self) -> str:
        """Find CA cert for /ca.crt download endpoint."""
        for name in ("rootCA.crt", "ca.crt"):
            p = self.ssl_dir / name
            if p.exists():
                return str(p)
        return ""

    def _remove_default_site(self) -> None:
        default = self.sites_enabled_dir / "default"
        if default.exists() or default.is_symlink():
            try:
                default.unlink()
            except PermissionError:
                subprocess.run(["sudo", "rm", "-f", str(default)], check=False)

    def generate_combined_config(self, ports: list[int]) -> str:
        """Generate combined nginx config with location blocks for all ports."""
        if not ports:
            self.cleanup_all()
            return ""

        cert_path, key_path = self._find_cert_pair()
        ca_cert_path = self._find_ca_cert()

        location_blocks = ""
        for port in ports:
            location_blocks += LOCATION_BLOCK.format(port=port)

        ca_location = ""
        if ca_cert_path:
            ca_location = CA_LOCATION_BLOCK.format(ca_cert_path=ca_cert_path)

        config_content = COMBINED_CONFIG_TEMPLATE.format(
            cert_path=cert_path,
            key_path=key_path,
            server_name=self.domain or "_",
            ca_location=ca_location,
            location_blocks=location_blocks,
        )

        config_path = self.sites_available_dir / CONFIG_NAME
        try:
            config_path.write_text(config_content)
        except PermissionError:
            tmp_path = Path(f"/tmp/{CONFIG_NAME}")
            tmp_path.write_text(config_content)
            subprocess.run(["sudo", "cp", str(tmp_path), str(config_path)], check=True)
            tmp_path.unlink(missing_ok=True)

        self._enable_config(config_path)
        self._remove_default_site()
        self.reload_nginx()

        logger.info("Nginx config updated: %d location(s)", len(ports))
        return str(config_path)

    def _enable_config(self, config_path: Path) -> None:
        symlink_path = self.sites_enabled_dir / config_path.name
        if symlink_path.exists() or symlink_path.is_symlink():
            try:
                symlink_path.unlink()
            except PermissionError:
                subprocess.run(["sudo", "rm", "-f", str(symlink_path)], check=False)
        try:
            symlink_path.symlink_to(str(config_path))
        except PermissionError:
            subprocess.run(
                ["sudo", "ln", "-s", str(config_path), str(symlink_path)],
                check=True,
            )

    def reload_nginx(self) -> None:
        try:
            subprocess.run(
                ["sudo", "nginx", "-s", "reload"],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.debug("Nginx reloaded")
        except subprocess.CalledProcessError as exc:
            logger.error("Nginx reload failed: %s", exc.stderr or exc.stdout)

    def cleanup_all(self) -> None:
        for path in self.sites_available_dir.glob(f"{CONFIG_NAME}*"):
            try:
                path.unlink()
            except PermissionError:
                subprocess.run(["sudo", "rm", "-f", str(path)], check=False)
        for path in self.sites_enabled_dir.glob(f"{CONFIG_NAME}*"):
            if path.is_symlink():
                try:
                    path.unlink()
                except PermissionError:
                    subprocess.run(["sudo", "rm", "-f", str(path)], check=False)
        try:
            self.reload_nginx()
        except Exception:
            pass
        logger.info("Nginx sandbox configs cleaned up")

    def sync_from_endpoints(self, endpoints: list[str]) -> None:
        """Extract ports from endpoint strings and regenerate nginx config.

        Endpoint format: ``127.0.0.1:PORT/proxy/8443`` (bridge)
        or ``127.0.0.1:PORT`` (host).
        """
        ports: set[int] = set()
        for ep in endpoints:
            try:
                host_port = ep.split("/")[0]
                port_str = host_port.split(":")[1]
                ports.add(int(port_str))
            except (IndexError, ValueError):
                continue
        self.generate_combined_config(sorted(ports))
