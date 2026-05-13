#!/usr/bin/env bash
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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSL_DIR="${SSL_DIR:-/etc/nginx/ssl}"

echo "[Setup] Installing prerequisites for THON hackathon environment..."

sudo apt-get update
sudo apt-get upgrade -y

sudo apt-get install -y --no-install-recommends \
    python3-full \
    python3-venv \
    python3-pip \
    python-is-python3 \
    nginx \
    mkcert \
    docker.io \
    docker-buildx \
    openssl \
    ca-certificates \
    curl \
    libnss3-tools \
    software-properties-common

INSTALL_GATEWAY="${INSTALL_GATEWAY:-false}"

if [ "$INSTALL_GATEWAY" = "true" ] || [ "$INSTALL_GATEWAY" = "1" ]; then
    echo "[Setup] Installing AI Gateway prerequisites (APISIX, etcd, Redis)..."

    sudo apt-get install -y --no-install-recommends \
        etcd-server \
        redis

    echo "[Setup] Adding APISIX repository..."
    wget -q -O - http://repos.apiseven.com/pubkey.gpg | sudo apt-key add - 2>/dev/null || {
        wget -q -O /tmp/apisix-gpg.key http://repos.apiseven.com/pubkey.gpg
        sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/apisix.gpg /tmp/apisix-gpg.key 2>/dev/null || true
        rm -f /tmp/apisix-gpg.key
    }
    echo "deb http://repos.apiseven.com/packages/debian bullseye main" | \
        sudo tee /etc/apt/sources.list.d/apisix.list

    sudo apt-get update
    sudo apt-get install -y --no-install-recommends apisix

    echo "[Setup] Starting etcd and Redis..."
    sudo systemctl enable etcd
    sudo systemctl start etcd
    sudo systemctl enable redis-server
    sudo systemctl start redis

    echo "[Setup] AI Gateway packages installed."
    echo "[Setup] Run 'bash ${SCRIPT_DIR}/setup-apisix.sh' to configure and start APISIX."
fi

echo "[Setup] Installing lemonade-server via PPA..."
sudo add-apt-repository -y ppa:lemonade-team/stable
sudo apt-get update
sudo apt-get install -y lemonade-server
sudo update-pciids 2>/dev/null || true

echo "[Setup] Creating SSL directory at ${SSL_DIR}..."
sudo mkdir -p "${SSL_DIR}"
sudo chown -R "$(whoami)":"$(whoami)" "${SSL_DIR}" 2>/dev/null || true

echo "[Setup] Creating nginx sites directories..."
sudo mkdir -p /etc/nginx/sites-available
sudo mkdir -p /etc/nginx/sites-enabled
sudo chown -R "$(whoami)":"$(whoami)" /etc/nginx/sites-available 2>/dev/null || true
sudo chown -R "$(whoami)":"$(whoami)" /etc/nginx/sites-enabled 2>/dev/null || true

# Ensure sites-enabled is included in nginx.conf
if ! grep -q "sites-enabled" /etc/nginx/nginx.conf 2>/dev/null; then
    echo "[Setup] Adding sites-enabled include to nginx.conf..."
    sudo sed -i '/http {/a \\tinclude /etc/nginx/sites-enabled/*;' /etc/nginx/nginx.conf
fi

# Remove default site to avoid default_server conflict
sudo rm -f /etc/nginx/sites-enabled/default

echo "[Setup] Installing mkcert CA..."
sudo mkcert -install 2>/dev/null || mkcert -install 2>/dev/null || {
    echo "[Setup] Warning: mkcert CA install failed (may need sudo)"
}

CAROOT=$(mkcert -caroot 2>/dev/null || true)
REPO_DIR="${SCRIPT_DIR}/.."
# # Clone and build if running standalone (not from inside the repo)

# REPO_DIR="$(cd "${REPO_DIR}" && pwd)"
# if [[ ! -f "${REPO_DIR}/server/pyproject.toml" ]]; then
#     echo "[Setup] Cloning OpenSandbox repository..."
#     git clone https://github.com/unclemusclez/OpenSandbox.git ~/OpenSandbox
#     REPO_DIR=~/OpenSandbox
# fi

echo "[Setup] Adding user to docker group..."
if ! groups "$USER" | grep -q '\bdocker\b'; then
    sudo usermod -aG docker "$USER"
    echo "[Setup] Added $USER to docker group."
    echo "[Setup] Activating docker group for current session..."
    exec sg docker "$0 $*" 2>/dev/null || {
        echo "[Setup] Could not auto-activate docker group."
        echo "[Setup] Run 'newgrp docker' or log out/in, then re-run this script."
        exit 1
    }
else
    echo "[Setup] User $USER is already in the docker group."
fi

echo "[Setup] Building Docker image..."
docker build -t waterpistol/thon:latest -f "${REPO_DIR}/Dockerfile" "${REPO_DIR}"

echo "[Setup] Installing OpenSandbox server and CLI..."
python3 -m venv ~/.venv
. ~/.venv/bin/activate
pip install opensandbox opensandbox-cli

echo "[Setup] Initializing OpenSandbox server configuration..."
opensandbox-server init-config "$HOME/.sandbox.toml" --example docker

SANDBOX_API_KEY="$(openssl rand -hex 24)"
if command -v python3 &>/dev/null; then
    SANDBOX_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
fi

# Write API key to ~/.sandbox.toml (handles commented, empty, or missing api_key)
if [ -f "$HOME/.sandbox.toml" ]; then
    # Uncomment the api_key line and set the generated key
    sed -i "s/^# api_key = .*/api_key = \"${SANDBOX_API_KEY}\"/" "$HOME/.sandbox.toml"
    # If api_key is uncommented but empty, update it
    sed -i "s/^api_key = \"\"/api_key = \"${SANDBOX_API_KEY}\"/" "$HOME/.sandbox.toml"
    # If still no api_key line, add one after [server]
    if ! grep -q "^api_key = " "$HOME/.sandbox.toml"; then
        sed -i "/^\[server\]/a api_key = \"${SANDBOX_API_KEY}\"" "$HOME/.sandbox.toml"
    fi
fi

echo "[Setup] Generated sandbox API key: ${SANDBOX_API_KEY}"

echo ""
echo "[Setup] Prerequisites installed successfully."
echo "[Setup] SSL certs will be generated at: ${SSL_DIR}"
echo ""
echo "[Setup] Next steps:"
echo "  1. Start the OpenSandbox server (with Python environment already activated):"
echo "     opensandbox-server"
echo ""
echo "  2. In another terminal, start the Lemonade inference server:"
echo "     bash ${SCRIPT_DIR}/setup-lemonade.sh --groups ${SCRIPT_DIR}/groups.yaml --generate-keys --external-ip <YOUR_IP>"
echo ""
echo "  3. In another terminal, start the VS Code sandboxes:"
echo "     . ~/.venv/bin/activate"
echo "     python ${REPO_DIR}/main.py --groups ${REPO_DIR}config/groups.yaml --external-ip <YOUR_IP> --lemonade kilo.jsonc --vscode-settings ${SCRIPT_DIR}/vscode-settings.jsonc"
echo ""
if [ -n "$CAROOT" ]; then
    echo "[Setup] For client browsers: install the mkcert CA root from:"
    echo "  ${CAROOT}/rootCA.pem"
    echo ""
fi
echo "[Setup] Note: If docker commands fail in new shells, run 'newgrp docker' or log out/in."
