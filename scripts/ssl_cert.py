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
SSL Certificate Generator for THON

Uses mkcert (preferred) to generate CA-trusted certificates that browsers
accept without warnings. Falls back to openssl if mkcert is not installed.

The external IP is encoded in the cert filename so changing --external-ip
triggers regeneration with the new IP in the SAN.

For remote access, clients must trust the mkcert CA. After generation,
the CA root path is printed so users can copy it to client machines.

Usage:
    from ssl_cert import SSLCertificateGenerator

    gen = SSLCertificateGenerator(output_dir="/etc/nginx/ssl")
    cert, key = gen.generate_server_cert(server_ip="165.245.138.159")
"""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


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


def _sudo_chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except PermissionError:
        subprocess.run(["sudo", "chmod", oct(mode)[2:], str(path)], check=True)


def _sudo_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        subprocess.run(["sudo", "rm", "-f", str(path)], check=True)


def _sudo_write_text(path: Path, content: str) -> None:
    try:
        path.write_text(content)
    except PermissionError:
        tmp_path = Path(f"/tmp/{path.name}")
        tmp_path.write_text(content)
        subprocess.run(["sudo", "cp", str(tmp_path), str(path)], check=True)
        tmp_path.unlink(missing_ok=True)


class SSLCertificateGenerator:

    def __init__(self, output_dir: str = "/etc/nginx/ssl"):
        self.output_dir = Path(output_dir)
        _sudo_mkdir(self.output_dir)
        self._mkcert_path: Optional[str] = None

    def _find_mkcert(self) -> Optional[str]:
        if self._mkcert_path is not None:
            return self._mkcert_path

        mkcert = shutil.which("mkcert")
        if mkcert:
            self._mkcert_path = mkcert
            return mkcert

        return None

    def _check_mkcert_ca(self) -> bool:
        mkcert = self._find_mkcert()
        if not mkcert:
            return False
        try:
            result = subprocess.run(
                [mkcert, "-CAROOT"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return True
        except Exception:
            pass
        return self._find_ca_root_fallback() is not None

    def _get_mkcert_ca_root(self) -> Optional[str]:
        mkcert = self._find_mkcert()
        if not mkcert:
            return None
        try:
            result = subprocess.run(
                [mkcert, "-CAROOT"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            if result.stderr.strip():
                print(f"[SSL] mkcert -CAROOT failed (rc={result.returncode}): {result.stderr.strip()}")
        except Exception as e:
            print(f"[SSL] mkcert -CAROOT error: {e}")
        return self._find_ca_root_fallback()

    def get_mkcert_ca_root(self) -> Optional[str]:
        return self._get_mkcert_ca_root()

    @staticmethod
    def _find_ca_root_fallback() -> Optional[str]:
        """Find mkcert CA root by checking common locations."""
        caroot_env = os.environ.get("CAROOT")
        if caroot_env and Path(caroot_env, "rootCA.pem").exists():
            return caroot_env

        home = Path.home()
        candidates = [
            home / ".local" / "share" / "mkcert",
            Path("/root/.local/share/mkcert"),
            home / "Library" / "Application Support" / "mkcert",
        ]
        for candidate in candidates:
            if (candidate / "rootCA.pem").exists():
                return str(candidate)

        return None

    def _install_mkcert_ca(self) -> bool:
        mkcert = self._find_mkcert()
        if not mkcert:
            return False
        try:
            subprocess.run(
                [mkcert, "-install"],
                check=True,
                capture_output=True,
            )
            print("[SSL] mkcert CA installed")
            return True
        except subprocess.CalledProcessError as e:
            print(f"[SSL] Warning: Failed to install mkcert CA: {e}")
            return False

    @staticmethod
    def _cert_name(server_ip: Optional[str] = None) -> str:
        if server_ip:
            san_hash = hashlib.sha256(server_ip.encode()).hexdigest()[:8]
            return f"thon-{san_hash}"
        return "thon"

    def _cert_has_san(self, cert_path: Path, server_ip: str) -> bool:
        """Check if existing cert contains the requested IP in its SAN extension."""
        try:
            result = subprocess.run(
                ["openssl", "x509", "-in", str(cert_path), "-noout", "-ext", "subjectAltName"],
                capture_output=True,
                text=True,
                check=True,
            )
            return server_ip in result.stdout
        except Exception:
            return False

    def _find_existing_cert(self, name: str) -> tuple[Optional[Path], Optional[Path]]:
        cert_file = None
        key_file = None
        for ext in (".pem", ".crt"):
            p = self.output_dir / f"{name}{ext}"
            if p.exists():
                cert_file = p
                break
        for ext in ("-key.pem", ".key"):
            p = self.output_dir / f"{name}{ext}"
            if p.exists():
                key_file = p
                break
        return cert_file, key_file

    def generate_server_cert(
        self,
        server_ip: Optional[str] = None,
    ) -> tuple[str, str]:
        """Generate a single shared cert for the whole instance.

        Uses mkcert if available (CA-trusted, no browser warnings).
        Falls back to openssl self-signed.

        The cert filename includes a hash of server_ip so changing
        the IP triggers regeneration with the new SAN.

        Args:
            server_ip: External IP for SAN (fixes Service Worker SSL errors)

        Returns:
            Tuple of (cert_path, key_path)
        """
        name = self._cert_name(server_ip)

        cert_file, key_file = self._find_existing_cert(name)

        if cert_file and key_file:
            if server_ip and not self._cert_has_san(cert_file, server_ip):
                print(f"[SSL] Existing cert missing IP={server_ip} in SAN, regenerating")
                _sudo_unlink(cert_file)
                _sudo_unlink(key_file)
            else:
                print(f"[SSL] Reusing existing cert: {cert_file}")
                return str(cert_file), str(key_file)

        cert_file = cert_file or self.output_dir / f"{name}.pem"
        key_file = key_file or self.output_dir / f"{name}-key.pem"

        mkcert = self._find_mkcert()
        if mkcert:
            if not self._check_mkcert_ca():
                if not self._install_mkcert_ca():
                    print("[SSL] mkcert CA not available, falling back to openssl")
                    return self._generate_openssl_cert(name, server_ip)

            cert_path, key_path = self._generate_mkcert_cert(
                cert_file, key_file, server_ip
            )
            self._print_ca_root()
            return cert_path, key_path

        print("[SSL] mkcert not found, falling back to openssl")
        return self._generate_openssl_cert(name, server_ip)

    def _print_ca_root(self) -> None:
        ca_root = self._get_mkcert_ca_root()
        if ca_root:
            print(f"[SSL] mkcert CA root: {ca_root}")
            print("[SSL] Install this CA on client machines for browser trust:")
            print(f"[SSL]   Copy {ca_root}/rootCA.pem to client, then:")
            print("[SSL]   - Chrome: Settings > Security > Manage certificates > Authorities > Import")
            print("[SSL]   - Firefox: Preferences > Privacy > View Certificates > Authorities > Import")
            print("[SSL]   - Linux: sudo cp rootCA.pem /usr/local/share/ca-certificates/ && sudo update-ca-certificates")

    def _copy_ca_root(self) -> None:
        """Copy mkcert CA root to SSL output dir for /ca.crt download endpoint."""
        ca_root = self._get_mkcert_ca_root()
        if not ca_root:
            return
        src = Path(ca_root) / "rootCA.pem"
        dst = self.output_dir / "rootCA.crt"
        if not src.is_file():
            return
        if dst.is_file():
            return
        try:
            shutil.copy2(str(src), str(dst))
            print(f"[SSL] CA root copied to {dst} (served at /ca.crt)")
        except PermissionError:
            tmp_path = Path("/tmp/rootCA.crt")
            shutil.copy2(str(src), str(tmp_path))
            subprocess.run(["sudo", "cp", str(tmp_path), str(dst)], check=True)
            tmp_path.unlink(missing_ok=True)
            print(f"[SSL] CA root copied to {dst} (served at /ca.crt)")

    def _generate_mkcert_cert(
        self,
        cert_file: Path,
        key_file: Path,
        server_ip: Optional[str] = None,
    ) -> tuple[str, str]:
        san_names = ["localhost", "127.0.0.1"]
        if server_ip:
            san_names.insert(0, server_ip)

        mkcert = self._find_mkcert()
        print(f"[SSL] Generating CA-trusted cert via mkcert for: {', '.join(san_names)}")

        try:
            subprocess.run(
                [
                    mkcert,
                    "-cert-file", str(cert_file),
                    "-key-file", str(key_file),
                ] + san_names,
                check=True,
                capture_output=True,
                text=True,
            )
            _sudo_chmod(key_file, 0o600)
            self._copy_ca_root()
            print(f"[SSL] Certificate saved: {cert_file}")
            print(f"[SSL] Key saved: {key_file}")
            return str(cert_file), str(key_file)
        except subprocess.CalledProcessError as e:
            print(f"[SSL] mkcert failed: {e.stderr}")
            print("[SSL] Falling back to openssl")
            name = self._cert_name(server_ip)
            return self._generate_openssl_cert(name, server_ip)

    def _generate_openssl_cert(
        self,
        name: str,
        server_ip: Optional[str] = None,
    ) -> tuple[str, str]:
        cert_file = self.output_dir / f"{name}.crt"
        key_file = self.output_dir / f"{name}.key"

        if cert_file.exists() and key_file.exists():
            if server_ip and not self._cert_has_san(cert_file, server_ip):
                print(f"[SSL] Existing openssl cert missing IP={server_ip} in SAN, regenerating")
                cert_file.unlink()
                key_file.unlink(missing_ok=True)
            else:
                print(f"[SSL] Reusing existing cert: {cert_file}")
                return str(cert_file), str(key_file)

        print("[SSL] Generating self-signed cert via openssl...")

        key_size = 2048
        san_parts = ["DNS:localhost"]
        if server_ip:
            san_parts.insert(0, f"IP:{server_ip}")
        san_str = ",".join(san_parts)

        conf_content = f"""[req]
default_bits = {key_size}
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = thon

[v3_req]
subjectAltName = {san_str}
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
"""

        conf_file = self.output_dir / f"{name}.conf"
        _sudo_write_text(conf_file, conf_content)

        try:
            subprocess.run(
                [
                    "openssl", "req", "-x509", "-nodes",
                    "-days", "365",
                    "-newkey", f"rsa:{key_size}",
                    "-keyout", str(key_file),
                    "-out", str(cert_file),
                    "-config", str(conf_file),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            _sudo_chmod(key_file, 0o600)
            print(f"[SSL] Certificate saved: {cert_file}")
            print(f"[SSL] Key saved: {key_file}")
            return str(cert_file), str(key_file)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to generate SSL cert: {e.stderr}"
            ) from e
        finally:
            _sudo_unlink(conf_file)

    def delete_certs(self) -> None:
        for p in sorted(self.output_dir.glob("thon*")):
            if p.suffix in (".pem", ".key", ".crt", ".conf"):
                _sudo_unlink(p)
                print(f"[SSL] Deleted: {p}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate SSL certs forTHON")
    parser.add_argument("--ip", type=str, help="External IP for SAN")
    parser.add_argument("--output-dir", type=str, default="/etc/nginx/ssl")
    args = parser.parse_args()

    gen = SSLCertificateGenerator(output_dir=args.output_dir)
    cert, key = gen.generate_server_cert(server_ip=args.ip)

    print(f"\n  ssl_certificate {cert};")
    print(f"  ssl_certificate_key {key};")


if __name__ == "__main__":
    main()
