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
LEMONADE_PY="${SCRIPT_DIR}/lemonade_server.py"

PORT="${LEMONADE_PORT:-13305}"
HOST="${LEMONADE_HOST:-0.0.0.0}"
BACKEND="${LEMONADE_BACKEND:-auto}"
CTX_SIZE="${LEMONADE_CTX_SIZE:-262144}"
MODEL="${LEMONADE_MODEL:-unsloth/gemma-4-31B-it-GGUF:Q8_K_XL}"
MODEL_NAME="${LEMONADE_MODEL_NAME:-gemma-4-31b-it}"
MMPROJ="${LEMONADE_MMPROJ:-mmproj-BF16.gguf}"
EMBEDDING="${LEMONADE_EMBEDDING:-true}"
EMBEDDING_MODEL="${LEMONADE_EMBEDDING_MODEL:-SuperPauly/harrier-oss-v1-0.6b-gguf:harrier-oss-v1-0.6B-BF16}"
EMBEDDING_MODEL_NAME="${LEMONADE_EMBEDDING_MODEL_NAME:-harrier-oss-v1-0.6b}"
EXTERNAL_IP="${LEMONADE_EXTERNAL_IP:-}"
GENERATE_KEYS="${LEMONADE_GENERATE_KEYS:-false}"
THON_DIR="${HOME}/.thon"
KILO_CONFIG_OUTPUT="${LEMONADE_KILO_CONFIG:-${THON_DIR}/kilo.jsonc}"
GROUPS_FILE=""
GROUP_FILTER=""
NUM_USERS="${LEMONADE_NUM_USERS:-1}"
PREFER_SYSTEM="${LEMONADE_PREFER_SYSTEM:-true}"
LLAMACPP_BIN="${LEMONADE_LLMACPP_BIN:-builtin}"
PER_USER_CTX=262144
EMBEDDING_PER_USER_CTX=32768
CONFIG_DIR="/var/lib/lemonade/.cache/lemonade"

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Install, configure, and start the Lemonade inference server as a systemd
service.  Generates user_models.json, recipe_options.json, and kilo.jsonc
for Kilo Code so sandbox VS Code instances can connect to the local LLM.

The --groups flag reads a groups.yaml to determine the number of parallel
users, which scales the llama.cpp context size and parallel slots.

Options:
  --groups FILE         Path to groups.yaml; user count scales ctx-size and -np
  --group GROUP         Filter to a single group from groups.yaml
  --num-users N         Override number of parallel users (default: 1, or auto from --groups)
  --port PORT           Server port (default: ${PORT})
  --host HOST           Bind address (default: ${HOST})
  --backend BACKEND     llama.cpp backend: auto, vulkan, cpu (default: ${BACKEND})
  --ctx-size SIZE       Per-user context size (default: ${CTX_SIZE})
  --model MODEL         HuggingFace checkpoint (default: ${MODEL})
  --model-name NAME     Short model name for user_models.json (default: ${MODEL_NAME})
  --mmproj FILE         Multimodal projection model filename (default: ${MMPROJ})
  --embedding           Enable embedding model for semantic indexing (default)
  --no-embedding        Disable embedding model
  --embedding-model MODEL   HuggingFace checkpoint for embedding model (default: ${EMBEDDING_MODEL})
  --embedding-model-name NAME  Short name for embedding model (default: ${EMBEDDING_MODEL_NAME})
  --external-ip IP      External IP for kilo.jsonc base URL
  --generate-keys       Generate API key and admin key in systemd override
  --no-prefer-system    Use bundled llama.cpp instead of system-installed
  --llamacpp-bin PATH   Path to system llama-server binary (default: builtin)
  --kilo-config PATH    Output path for kilo.jsonc (default: ${KILO_CONFIG_OUTPUT})
  -h, --help            Show this help

Environment variables (override defaults):
  LEMONADE_PORT, LEMONADE_HOST, LEMONADE_BACKEND, LEMONADE_CTX_SIZE,
  LEMONADE_MODEL, LEMONADE_MODEL_NAME, LEMONADE_EXTERNAL_IP,
  LEMONADE_GENERATE_KEYS, LEMONADE_NUM_USERS, LEMONADE_KILO_CONFIG,
  LEMONADE_PREFER_SYSTEM, LEMONADE_LLMACPP_BIN, LEMONADE_MMPROJ,
  LEMONADE_EMBEDDING, LEMONADE_EMBEDDING_MODEL, LEMONADE_EMBEDDING_MODEL_NAME

Examples:
  # Full setup with groups.yaml for user count
  $(basename "$0") --groups groups.yaml --generate-keys --external-ip 1.2.3.4

  # Single group with API keys
  $(basename "$0") --groups groups.yaml --group alpha --generate-keys --external-ip 1.2.3.4

  # Override user count directly
  $(basename "$0") --num-users 8 --generate-keys --external-ip 1.2.3.4
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --groups)              GROUPS_FILE="$2"; shift 2 ;;
        --group)               GROUP_FILTER="$2"; shift 2 ;;
        --num-users)           NUM_USERS="$2"; shift 2 ;;
        --port)                PORT="$2"; shift 2 ;;
        --host)                HOST="$2"; shift 2 ;;
        --backend)             BACKEND="$2"; shift 2 ;;
        --ctx-size)            CTX_SIZE="$2"; shift 2 ;;
        --model)               MODEL="$2"; shift 2 ;;
        --model-name)          MODEL_NAME="$2"; shift 2 ;;
        --mmproj)              MMPROJ="$2"; shift 2 ;;
        --embedding)           EMBEDDING="true"; shift ;;
        --no-embedding)        EMBEDDING="false"; shift ;;
        --embedding-model)     EMBEDDING_MODEL="$2"; shift 2 ;;
        --embedding-model-name) EMBEDDING_MODEL_NAME="$2"; shift 2 ;;
        --external-ip)         EXTERNAL_IP="$2"; shift 2 ;;
        --generate-keys)       GENERATE_KEYS="true"; shift ;;
        --no-prefer-system)    PREFER_SYSTEM="false"; shift ;;
        --llamacpp-bin)        LLAMACPP_BIN="$2"; shift 2 ;;
        --kilo-config)         KILO_CONFIG_OUTPUT="$2"; shift 2 ;;
        -h|--help)             usage; exit 0 ;;
        *)                     echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ -n "${GROUPS_FILE}" ]]; then
    if command -v python3 &>/dev/null; then
        COUNT_ARGS="--groups ${GROUPS_FILE}"
        if [[ -n "${GROUP_FILTER}" ]]; then
            COUNT_ARGS="${COUNT_ARGS} --group ${GROUP_FILTER}"
        fi
        NUM_USERS="$(python3 "${LEMONADE_PY}" count-users ${COUNT_ARGS})"
        echo "[Lemonade] ${NUM_USERS} user(s) from ${GROUPS_FILE}"
    else
        echo "[Lemonade] Warning: python3 not available, using --num-users=${NUM_USERS}"
    fi
fi

if [[ "${NUM_USERS}" -lt 1 ]]; then
    NUM_USERS=1
fi

TOTAL_CTX=$((PER_USER_CTX * NUM_USERS))

echo "[Lemonade] Installing lemonade-server via PPA..."
sudo add-apt-repository -y ppa:lemonade-team/stable
sudo apt-get update
sudo apt-get install -y lemonade-server
sudo update-pciids 2>/dev/null || true

if [[ "${LLAMACPP_BIN}" != "builtin" ]] && ! command -v "${LLAMACPP_BIN}" &>/dev/null && [[ ! -x "${LLAMACPP_BIN}" ]]; then
    if command -v llama-server &>/dev/null; then
        LLAMACPP_BIN="$(command -v llama-server)"
        echo "[Lemonade] Found system llama-server: ${LLAMACPP_BIN}"
    else
        LLAMACPP_BIN="builtin"
        echo "[Lemonade] No system llama-server found, using builtin"
    fi
fi

echo "[Lemonade] Stopping server for direct config..."
sudo systemctl stop lemonade-server 2>/dev/null || true

echo "[Lemonade] Configuring server..."
PREFER_SYSTEM_FLAG=""
if [[ "${PREFER_SYSTEM}" == "true" ]]; then
    PREFER_SYSTEM_FLAG="--prefer-system"
else
    PREFER_SYSTEM_FLAG="--no-prefer-system"
fi
MAX_LOADED_MODELS=1
if [[ "${EMBEDDING}" == "true" ]]; then
    MAX_LOADED_MODELS=2
fi
python3 "${LEMONADE_PY}" configure \
    --port "${PORT}" \
    --host "${HOST}" \
    --llamacpp-backend "${BACKEND}" \
    --ctx-size "${CTX_SIZE}" \
    --max-loaded-models "${MAX_LOADED_MODELS}" \
    ${PREFER_SYSTEM_FLAG} \
    --llamacpp-bin "${LLAMACPP_BIN}"

echo "[Lemonade] Writing model configs (user_models.json + recipe_options.json)..."
EMBEDDING_FLAG=""
if [[ "${EMBEDDING}" == "true" ]]; then
    EMBEDDING_FLAG="--embedding --embedding-model ${EMBEDDING_MODEL} --embedding-model-name ${EMBEDDING_MODEL_NAME}"
else
    EMBEDDING_FLAG="--no-embedding"
fi
python3 "${LEMONADE_PY}" write-model-configs \
    --model "${MODEL}" \
    --model-name "${MODEL_NAME}" \
    --num-users "${NUM_USERS}" \
    --llamacpp-backend "${BACKEND}" \
    --mmproj "${MMPROJ}" \
    ${EMBEDDING_FLAG}
LEMONADE_USER="$(systemctl show lemonade-server -p User --value 2>/dev/null || echo lemonade)"
sudo chown -R "${LEMONADE_USER}:${LEMONADE_USER}" "${CONFIG_DIR}"

API_KEY=""
ADMIN_KEY=""

if [[ "${GENERATE_KEYS}" == "true" ]]; then
    API_KEY="$(openssl rand -base64 32 | tr -d '/+=\n' | head -c 32)"
    ADMIN_KEY="$(openssl rand -base64 32 | tr -d '/+=\n' | head -c 32)"

    OVERRIDE_DIR="/etc/systemd/system/lemonade-server.service.d"
    sudo mkdir -p "${OVERRIDE_DIR}"
    sudo tee "${OVERRIDE_DIR}/override.conf" > /dev/null <<EOF
[Service]
Environment="LEMONADE_API_KEY=${API_KEY}"
Environment="LEMONADE_ADMIN_API_KEY=${ADMIN_KEY}"
EOF
    sudo systemctl daemon-reload

    echo "[Lemonade] API keys configured in systemd override"
    echo "[Lemonade]   API Key:       ${API_KEY}"
    echo "[Lemonade]   Admin API Key: ${ADMIN_KEY}"
fi

echo "[Lemonade] Restarting service..."
sudo systemctl restart lemonade-server

echo "[Lemonade] Waiting for server to be ready..."
sleep 3

if sudo systemctl is-active --quiet lemonade-server; then
    echo "[Lemonade] Server is running"
else
    echo "[Lemonade] Error: Server failed to start"
    sudo systemctl status lemonade-server --no-pager || true
    exit 1
fi

PREFIXED_NAME="user.${MODEL_NAME}"
PREFIXED_EMB_NAME="user.${EMBEDDING_MODEL_NAME}"

echo "[Lemonade] Pulling model: ${PREFIXED_NAME}"
PULL_ENV=""
if [[ -n "${ADMIN_KEY}" ]]; then
    PULL_ENV="LEMONADE_ADMIN_API_KEY=${ADMIN_KEY} LEMONADE_API_KEY=${ADMIN_KEY}"
elif [[ -n "${API_KEY}" ]]; then
    PULL_ENV="LEMONADE_API_KEY=${API_KEY}"
fi

if python3 "${LEMONADE_PY}" status &>/dev/null && lemonade list 2>/dev/null | grep -q "${PREFIXED_NAME}.*Yes"; then
    echo "[Lemonade] Model already downloaded: ${PREFIXED_NAME}"
else
    eval ${PULL_ENV} lemonade pull "${PREFIXED_NAME}" --checkpoint main "${MODEL}" --recipe llamacpp || \
        echo "[Lemonade] WARNING: Chat model pull failed — check disk space or network"
fi

if [[ "${EMBEDDING}" == "true" ]]; then
    echo "[Lemonade] Pulling embedding model: ${PREFIXED_EMB_NAME}"
    if eval ${PULL_ENV} lemonade list 2>/dev/null | grep -q "${PREFIXED_EMB_NAME}.*Yes"; then
        echo "[Lemonade] Embedding model already downloaded: ${PREFIXED_EMB_NAME}"
    else
        eval ${PULL_ENV} lemonade pull "${PREFIXED_EMB_NAME}" --checkpoint main "${EMBEDDING_MODEL}" --recipe llamacpp || \
            echo "[Lemonade] WARNING: Embedding model pull failed — check disk space or network"
    fi
fi

echo "[Lemonade] Loading model via API..."

LOCAL_HOST="localhost"
if [[ "${HOST}" != "0.0.0.0" ]]; then
    LOCAL_HOST="${HOST}"
fi

CURL_ARGS=(-sf -X POST "http://${LOCAL_HOST}:${PORT}/api/v1/load"
    -H "Content-Type: application/json")
if [[ -n "${ADMIN_KEY}" ]]; then
    CURL_ARGS+=(-H "Authorization: Bearer ${ADMIN_KEY}")
elif [[ -n "${API_KEY}" ]]; then
    CURL_ARGS+=(-H "Authorization: Bearer ${API_KEY}")
fi
CURL_ARGS+=(-d "{\"model\": \"${PREFIXED_NAME}\", \"recipe\": \"llamacpp\"}")

curl "${CURL_ARGS[@]}" && echo "[Lemonade] Model loaded: ${PREFIXED_NAME}" || \
    echo "[Lemonade] Warning: Model load request failed (model may still be loading)"

if [[ "${EMBEDDING}" == "true" ]]; then
    echo "[Lemonade] Loading embedding model via API..."
    EMB_CURL_ARGS=(-sf -X POST "http://${LOCAL_HOST}:${PORT}/api/v1/load"
        -H "Content-Type: application/json")
    if [[ -n "${ADMIN_KEY}" ]]; then
        EMB_CURL_ARGS+=(-H "Authorization: Bearer ${ADMIN_KEY}")
    elif [[ -n "${API_KEY}" ]]; then
        EMB_CURL_ARGS+=(-H "Authorization: Bearer ${API_KEY}")
    fi
    EMB_CURL_ARGS+=(-d "{\"model\": \"${PREFIXED_EMB_NAME}\", \"recipe\": \"llamacpp\"}")

    curl "${EMB_CURL_ARGS[@]}" && echo "[Lemonade] Embedding model loaded: ${PREFIXED_EMB_NAME}" || \
        echo "[Lemonade] Warning: Embedding model load request failed (model may still be loading)"
fi

echo "[Lemonade] Generating kilo.jsonc at ${KILO_CONFIG_OUTPUT}"
KILO_ARGS=(
    --model "${MODEL}"
    --model-name "${MODEL_NAME}"
    --output "${KILO_CONFIG_OUTPUT}"
)
if [[ "${EMBEDDING}" == "true" ]]; then
    KILO_ARGS+=(--embedding-model-name "${EMBEDDING_MODEL_NAME}")
else
    KILO_ARGS+=(--no-embedding)
fi
if [[ -n "${EXTERNAL_IP}" ]]; then
    KILO_ARGS+=(--external-ip "${EXTERNAL_IP}")
fi
if [[ -n "${ADMIN_KEY}" ]]; then
    KILO_ARGS+=(--admin-api-key "${ADMIN_KEY}")
elif [[ -n "${API_KEY}" ]]; then
    KILO_ARGS+=(--api-key "${API_KEY}")
fi
python3 "${LEMONADE_PY}" generate-kilo-config "${KILO_ARGS[@]}"

if [[ -n "${EXTERNAL_IP}" ]]; then
    BASE_HOST="${EXTERNAL_IP}"
else
    DOCKER_GW="$(docker network inspect bridge -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null || true)"
    if [[ -n "${DOCKER_GW}" ]]; then
        BASE_HOST="${DOCKER_GW}"
    else
        BASE_HOST="localhost"
    fi
fi

BASE_URL="http://${BASE_HOST}:${PORT}/v1"
AUTH_VAL="${ADMIN_KEY:-${API_KEY:-none}}"

echo ""
echo "========================================================================"
echo "Lemonade Inference Server"
echo "========================================================================"
echo "  Local endpoint: http://${LOCAL_HOST}:${PORT}"
echo "  OpenAI API:     http://${LOCAL_HOST}:${PORT}/v1/"
if [[ -n "${EXTERNAL_IP}" ]]; then
    echo "  External API:   http://${EXTERNAL_IP}:${PORT}/v1/"
fi
echo "  Model:          ${MODEL}"
echo "  Model name:     ${PREFIXED_NAME}"
if [[ "${EMBEDDING}" == "true" ]]; then
echo "  Embedding:      ${EMBEDDING_MODEL}"
echo "  Embedding name: ${PREFIXED_EMB_NAME}"
fi
echo "  Parallel users: ${NUM_USERS}"
echo "  Total ctx-size: ${TOTAL_CTX} (${PER_USER_CTX} x ${NUM_USERS})"
if [[ -n "${API_KEY}" ]]; then
    echo "  API Key:        ${API_KEY}"
fi
if [[ -n "${ADMIN_KEY}" ]]; then
    echo "  Admin API Key:  ${ADMIN_KEY}"
fi
echo ""
echo "  Kilo Code config: ${KILO_CONFIG_OUTPUT}"
echo "  Base URL:  ${BASE_URL}"
echo "  API Key:   ${AUTH_VAL}"
echo "  Model:     lemonade/${PREFIXED_NAME}"
echo ""
echo "  Service manages its own lifecycle (systemd)."
echo "  Status:   sudo systemctl status lemonade-server"
echo "  Stop:     sudo systemctl stop lemonade-server"
echo "  Restart:  sudo systemctl restart lemonade-server"
echo "  Logs:     sudo journalctl -u lemonade-server -f"
echo ""
echo "  To use with VS Code sandboxes:"
echo "    python ${SCRIPT_DIR}/main.py --groups groups.yaml --external-ip ${EXTERNAL_IP:-<IP>} --lemonade ${KILO_CONFIG_OUTPUT}"
