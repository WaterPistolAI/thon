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

echo "[APISIX] Installing APISIX AI Gateway prerequisites..."

sudo apt-get update

sudo apt-get install -y --no-install-recommends \
    etcd-server \
    redis

echo "[APISIX] Adding APISIX repository..."
wget -q -O - http://repos.apiseven.com/pubkey.gpg | sudo apt-key add - 2>/dev/null || {
    echo "[APISIX] Warning: apt-key add failed, trying alternative method..."
    wget -q -O /tmp/apisix-gpg.key http://repos.apiseven.com/pubkey.gpg
    sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/apisix.gpg /tmp/apisix-gpg.key 2>/dev/null || true
    rm -f /tmp/apisix-gpg.key
}

echo "deb http://repos.apiseven.com/packages/debian bullseye main" | \
    sudo tee /etc/apt/sources.list.d/apisix.list

sudo apt-get update

echo "[APISIX] Installing APISIX..."
sudo apt-get install -y --no-install-recommends apisix

echo "[APISIX] Starting etcd..."
sudo systemctl enable etcd
sudo systemctl start etcd

echo "[APISIX] Starting Redis..."
sudo systemctl enable redis
sudo systemctl start redis

echo "[APISIX] Configuring APISIX admin key..."
APISIX_CONFIG="/usr/local/apisix/conf/config.yaml"

if [ -f "$APISIX_CONFIG" ]; then
    ADMIN_KEY="${APISIX_ADMIN_KEY:-edd1c9f034335f136f87ad84b625c8f1}"

    if ! grep -q "admin_key" "$APISIX_CONFIG" 2>/dev/null; then
        sudo bash -c "cat >> '$APISIX_CONFIG'" <<EOF

deployment:
  admin:
    admin_key:
      - name: admin
        key: ${ADMIN_KEY}
        role: admin
    admin_listen:
      ip: 0.0.0.0
      port: 9180
EOF
        echo "[APISIX] Admin key configured"
    else
        echo "[APISIX] Admin key already configured"
    fi
else
    echo "[APISIX] Warning: config.yaml not found at $APISIX_CONFIG"
fi

echo "[APISIX] Starting APISIX..."
sudo systemctl enable apisix 
sudo systemctl start apisix 

echo "[APISIX] Waiting for APISIX to be ready..."
for i in $(seq 1 30); do
    if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:9180/apisix/admin/routes" \
        -H "X-API-KEY: ${APISIX_ADMIN_KEY:-edd1c9f034335f136f87ad84b625c8f1}" 2>/dev/null | grep -q "200"; then
        echo "[APISIX] APISIX is ready"
        break
    fi
    sleep 1
done

echo ""
echo "[APISIX] Installation complete."
echo "[APISIX] Admin API: http://127.0.0.1:9180/apisix/admin"
echo "[APISIX] Proxy: http://127.0.0.1:9080"
echo ""
echo "[APISIX] Next steps:"
echo "  python ${SCRIPT_DIR}/apisix_gateway.py setup --groups ${SCRIPT_DIR}/groups.yaml --lemonade-url http://127.0.0.1:13305"
echo ""
