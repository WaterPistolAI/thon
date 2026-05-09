# THON - The Hackathon Organizer Node

> Migrated to https://github.com/WaterPistolAI/thon.git

Run multiple VS Code sandbox instances concurrently with nginx SSL reverse proxy,
groups-based user management, persistent workspaces, and optional local LLM inference
via Lemonade Server.

## Features

- **Unified CLI**: `thon init`, `thon setup`, `thon run` — one config file (`thon.yaml`) for everything
- **Multi-Instance**: Multiple concurrent VS Code sandboxes from a single command
- **Groups-Based**: Define users and groups in YAML or manage via dashboard
- **Web Dashboard**: Streamlit dashboard for instance, group, Lemonade, and gateway management
- **REST API**: FastAPI REST API with Swagger UI for programmatic access
- **SSL/TLS**: Automatic nginx reverse proxy with mkcert or openssl certificates
- **Persistent Workspaces**: PVC Docker volumes or host bind mounts for workspace persistence
- **Local LLM**: Optional Lemonade Server integration for local inference (chat + embedding)
- **Semantic Indexing**: Embedding model for Kilo Code's semantic code search
- **AI Gateway**: Optional APISIX gateway with per-user or per-group rate limiting and API keys
- **Authentication**: Local password for dashboard; OIDC/OAuth2 (GitHub, GitLab, LinkedIn) for REST API
- **Config Files**: Store and manage groups YAML, kilo.json, and VS Code settings in the database
- **Kilo Code Ready**: Auto-generated config with experimental flags and indexing for Kilo Code

## Video Guide

https://youtu.be/YptAQQf_4dg

## Quick Start

### 1. One-time Setup

```bash
bash ./setup.sh
```

Installs python3, nginx, docker.io, mkcert, and openssl.

### 2. Build the Docker Image

```bash
docker build -t waterpistol/thon:latest ./
```

### 3. Initialize Configuration

```bash
# Interactive setup wizard (recommended)
thon init

# Or non-interactive (CI-friendly)
thon init --non-interactive
```

This creates a `thon.yaml` config file with all settings.

### 4. Setup and Run

```bash
# Install prerequisites and configure all components
thon setup

# Start VS Code instances
thon run
```

Alternatively, use `main.py` directly:

```bash
python ./main.py --groups groups.yaml --external-ip 1.2.3.4
```

Each user gets their own VS Code sandbox at `https://<ip>/<endpoint_path>/`.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Host Machine                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                    nginx (443)                       │    │
│  │         SSL termination + WebSocket proxy           │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │                                    │
│  ┌──────────────────────┼──────────────────────────────┐    │
│  │                Docker Network                        │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │    │
│  │  │  Sandbox 1  │  │  Sandbox 2  │  │  Sandbox 3  │ │    │
│  │  │ code-server │  │ code-server │  │ code-server │ │    │
│  │  │   :8443     │  │   :8444     │  │   :8445     │ │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘ │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           Lemonade Server (Optional)                 │    │
│  │    Chat model + Embedding model (semantic search)    │    │
│  │                   :13305                             │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         APISIX AI Gateway (Optional)                 │    │
│  │    Rate limiting + per-user/group API keys           │    │
│  │    Chat route + Embedding route                      │    │
│  │                   :9080                              │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Components

| Component | Role |
|-----------|------|
| **thon CLI** | Unified entry point: `thon init`, `thon setup`, `thon run`, `thon config` |
| **main.py** | Orchestrates sandbox creation, nginx configs, workspace setup |
| **Streamlit Dashboard** | Web UI for instance, group, Lemonade, and gateway management (:8501) |
| **FastAPI REST API** | Programmatic API for instances, groups, Lemonade, gateway, auth (:8100) |
| **nginx** | SSL termination + WebSocket proxy (per-port server blocks) |
| **code-server** | VS Code in the browser, runs HTTP inside each sandbox |
| **Lemonade Server** | Optional local LLM inference (chat + embedding models) |
| **APISIX Gateway** | Optional rate limiting with per-user or per-group API keys |

### Network Modes (auto-detected)

| Mode | Endpoint Format | Detection |
|------|----------------|-----------|
| **Host** | `127.0.0.1:8443` | No `/` after port |
| **Bridge** | `127.0.0.1:52322/proxy/8443` | `/proxy/` in endpoint |

Auto-detected from the server-returned endpoint — not a CLI flag.

### Workspace Persistence

| Mode | Storage | Lifecycle |
|------|---------|-----------|
| **PVC Volume** | Docker named volume (`thon-workspace-*`) | Persists across instance recreations |
| **Bind Mount** | Host directory (`--workspace-dir`) | Persists on host filesystem |
| **Ephemeral** | Inside container | Lost when container is removed |

PVC volumes are created automatically when users are imported via the dashboard
or `thon.yaml`. When a sandbox is recreated, the same PVC volume is reattached.

### SSL/TLS

- **mkcert** (preferred): CA-trusted certs, filename includes IP hash
- **openssl** (fallback): Self-signed certs with IP in SAN
- Single shared cert for all instances on port 443
- CA cert served at `https://<ip>/ca.crt` for remote clients

## thon CLI Reference

```bash
thon COMMAND [OPTIONS]
```

| Command | Description |
|---------|-------------|
| `thon init` | Interactive setup wizard (creates `thon.yaml`) |
| `thon setup` | Install prerequisites + configure from `thon.yaml` |
| `thon run` | Start VS Code instances from `thon.yaml` |
| `thon config show` | Display current config |
| `thon config env` | Export config as `.env` file |
| `thon config validate` | Validate `thon.yaml` |
| `thon cleanup` | Tear down all resources |

| Global Option | Default | Description |
|--------------|---------|-------------|
| `--config PATH` | ./thon.yaml | Path to config file |

### Examples

```bash
thon init                          # Interactive setup wizard
thon init --non-interactive        # CI-friendly defaults
thon setup                         # Install + configure
thon run                           # Start instances
thon run --group alpha             # Start one group
thon config validate               # Check config
thon config env --output .env      # Export .env
thon cleanup                       # Tear down
```

## main.py CLI Reference

```
python main.py [OPTIONS]
```

### Core Options

| Option | Description | Default |
|--------|-------------|---------|
| `--groups FILE` | Path to groups.yaml file | (none, single instance) |
| `--group GROUP` | Run only this group | (all groups) |
| `--from-db` | Read groups/users from database | `false` |
| `--port PORT` | Starting port for code-server | `8443` |
| `--timeout MIN` | Sandbox timeout in minutes | `0` (no timeout) |

### Server Connection

| Option | Description | Default |
|--------|-------------|---------|
| `--domain DOMAIN` | Sandbox server domain | `localhost:8080` |
| `--api-key KEY` | Sandbox API key | (none) |

### Docker Options

| Option | Description | Default |
|--------|-------------|---------|
| `--image IMAGE` | Docker image | `waterpistol/thon:latest` |
| `--python-version VER` | Python version in sandbox | `3.11` |

### Security

| Option | Description | Default |
|--------|-------------|---------|
| `--secure` | Enable per-user passwords | `false` |

### Network

| Option | Description | Default |
|--------|-------------|---------|
| `--external-ip IP` | External IP for SSL and URLs | auto-detected |
| `--ssl-dir DIR` | SSL cert storage directory | `/etc/nginx/ssl` |
| `--no-nginx` | Disable nginx, use direct HTTP | `false` |

### Workspace

| Option | Description | Default |
|--------|-------------|---------|
| `--workspace-dir DIR` | Host dir for persistent bind mounts | (none) |

### Lemonade Integration

| Option | Description | Default |
|--------|-------------|---------|
| `--lemonade KILO_JSON` | kilo.json path for LLM config injection | (none) |
| `--vscode-settings JSON` | VS Code settings file to inject | (none) |

### AI Gateway

| Option | Description | Default |
|--------|-------------|---------|
| `--gateway` | Enable APISIX AI Gateway with rate limiting | `false` |
| `--gateway-per-group` | One consumer per group (shared API key) | `false` |
| `--gateway-redis-host HOST` | Redis host for shared rate limiting | (none) |
| `--gateway-rate-limit N` | Token limit per consumer per time window | `500` |
| `--gateway-time-window N` | Rate limit time window in seconds | `60` |

### Maintenance

| Option | Description | Default |
|--------|-------------|---------|
| `--cleanup` | Remove all nginx configs and exit | `false` |

### Examples

```bash
# All groups with nginx SSL (default)
python main.py --groups groups.yaml --external-ip 1.2.3.4

# Single group
python main.py --groups groups.yaml --group alpha --external-ip 1.2.3.4

# From database (uses PVC workspace volumes)
python main.py --from-db --external-ip 1.2.3.4

# Per-user passwords
python main.py --groups groups.yaml --secure --external-ip 1.2.3.4

# Persistent workspaces
python main.py --groups groups.yaml --workspace-dir /vs-code-remote --external-ip 1.2.3.4

# Direct HTTP (no nginx)
python main.py --groups groups.yaml --no-nginx

# Single instance (no groups)
python main.py

# With Lemonade LLM inference
python main.py --groups groups.yaml --external-ip 1.2.3.4 --lemonade kilo.json

# With AI Gateway (per-user rate limiting)
python main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway

# With AI Gateway (per-group shared API keys)
python main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway --gateway-per-group

# With AI Gateway + Redis rate limiting
python main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway --gateway-redis-host 127.0.0.1

# With custom VS Code settings
python main.py --groups groups.yaml --external-ip 1.2.3.4 --vscode-settings vscode-settings.jsonc

# Cleanup nginx configs
python main.py --cleanup
```

## Dashboard

THON includes a Streamlit-based web dashboard for managing VS Code sandbox instances,
groups, Lemonade Server, and AI Gateway. The FastAPI REST API provides Swagger UI
for programmatic access.

### Quick Start

```bash
# Install dependencies
pip install streamlit pandas

# Run the dashboard
streamlit run dashboard/streamlit_app.py --server.port 8501

# Dashboard at http://localhost:8501
```

Optionally run the FastAPI REST API for programmatic access:

```bash
python -m app.main
# API docs at http://localhost:8100/docs
```

### Pages

| Page | Features |
|------|----------|
| **Instances** | List, search/filter, create, pause/resume/kill, bulk actions, recreate with PVC volume |
| **Groups** | CRUD groups/users, transfer users, start per-user/group instances with PVC workspaces |
| **Lemonade Server** | Status, health, performance, slots, system info, available models |
| **AI Gateway** | Configure, setup, manage consumers, cleanup, mode/rate limit settings |
| **Settings** | External IP, configuration file management (upload/edit/delete from DB) |

### Configuration Files in Database

The Settings page stores config files in the database. When `main.py` runs without
CLI flags, it reads these from the database. Priority: CLI flag > database > none.

| Config Key | Description |
|------------|-------------|
| `config_groups_yaml` | Groups and users definition |
| `config_kilo_json` | Kilo Code provider config |
| `config_vscode_settings` | VS Code settings for each sandbox |

## Lemonade Server (Local LLM Inference)

Provides an OpenAI-compatible API endpoint for VS Code extensions (Kilo Code, Continue, Cline)
inside sandbox containers. Runs as a **systemd service** on the host. Supports both chat
and embedding models for semantic code search.

### Setup

```bash
# Full setup (install + configure + API keys + pull model + kilo.json)
bash ./setup-lemonade.sh \
    --groups groups.yaml --generate-keys --external-ip 1.2.3.4
```

Or use the Python wrapper:

```bash
python ./lemonade_server.py run \
    --groups groups.yaml --generate-keys --external-ip 1.2.3.4
```

### Without Embedding Model

```bash
bash ./setup-lemonade.sh --groups groups.yaml --generate-keys \
    --external-ip 1.2.3.4 --no-embedding
```

### Service Management

```bash
sudo systemctl status lemonade-server
sudo systemctl stop lemonade-server
sudo systemctl restart lemonade-server
sudo journalctl -u lemonade-server -f
```

### Configuration

| File | Location | Purpose |
|------|----------|---------|
| config.json | `/var/lib/lemonade/.cache/lemonade/config.json` | Server settings (port, host, backend) |
| user_models.json | Same directory | User-registered custom models |
| server_models.json | Same directory | Server-suggested models |
| recipe_options.json | Same directory | Per-model runtime settings (ctx_size, backend, args) |
| API keys | `/etc/systemd/system/lemonade-server.service.d/override.conf` | LEMONADE_API_KEY, LEMONADE_ADMIN_API_KEY |

### Default Models

| Model | Checkpoint | Short Name (API) | Labels |
|-------|-----------|------------------|--------|
| Chat | `unsloth/gemma-4-31B-it-GGUF:Q8_K_XL` | `user.gemma-4-31b-it` | custom, vision |
| Embedding | `SuperPauly/harrier-oss-v1-0.6b-gguf:harrier-oss-v1-0.6B-BF16` | `user.harrier-oss-v1-0.6b` | custom, embedding |

The embedding model enables Kilo Code's semantic code search. Enabled by default;
disable with `--no-embedding`. When enabled, `max_loaded_models` is automatically
set to `2` (1 chat + 1 embedding).

### Per-User Scaling

When `--groups groups.yaml` is passed, context size and parallel slots scale automatically:

| Parameter | Chat Model | Embedding Model |
|-----------|-----------|-----------------|
| `ctx_size` | `262144` per user | `32768` per user |
| `-np` | `num_users` | `num_users` |

Lemonade-managed args (reserved, must NOT appear in `llamacpp_args`):
`--ctx-size`, `-c`, `-ngl`, `--gpu-layers`, `--n-gpu-layers`, `--jinja`, `--no-jinja`,
`--model`, `-m`, `--port`, `--embedding`, `--embeddings`, `--mmproj*`, `--rerank*`

### setup-lemonade.sh Options

| Option | Description | Default |
|--------|-------------|---------|
| `--groups FILE` | groups.yaml for user count | (none) |
| `--group GROUP` | Filter to single group | (all) |
| `--num-users N` | Override parallel user count | `1` |
| `--port PORT` | Server port | `13305` |
| `--host HOST` | Bind address | `0.0.0.0` |
| `--backend BACKEND` | llama.cpp backend: auto, vulkan, cpu | `auto` |
| `--ctx-size SIZE` | Per-user context size | `262144` |
| `--model MODEL` | HuggingFace checkpoint | `unsloth/gemma-4-31B-it-GGUF:Q8_K_XL` |
| `--model-name NAME` | Short model name | `gemma-4-31b-it` |
| `--mmproj FILE` | Vision mmproj filename | `mmproj-BF16.gguf` |
| `--external-ip IP` | External IP for kilo.json | (auto-detect) |
| `--generate-keys` | Generate API keys | `false` |
| `--no-prefer-system` | Use bundled llama.cpp | (system preferred) |
| `--llamacpp-bin PATH` | Path to system llama-server | `/usr/local/bin/llama-server` |
| `--kilo-config PATH` | Output path for kilo.json | `./kilo.json` |
| `--no-embedding` | Disable embedding model | `false` |
| `--embedding-model MODEL` | Embedding model checkpoint | `SuperPauly/harrier-oss-v1-0.6b-gguf:harrier-oss-v1-0.6B-BF16` |
| `--embedding-model-name NAME` | Short name for embedding model | `harrier-oss-v1-0.6b` |

### Building llama.cpp from Source (AMD MI300X)

```bash
bash ./build-amd-mi300x-llama-server.sh
```

Builds llama.cpp with ROCm/HIP for `gfx942` and installs to `/usr/local`. The Lemonade
config uses `prefer_system: true` with `rocm_bin: /usr/local/bin/llama-server` by default.

### Kilo Code Integration

1. `setup-lemonade.sh --generate-keys` creates API keys and writes `kilo.json`
2. `kilo.json` contains: provider (`lemonade`), base URL, API key, model ID (`user.gemma-4-31b-it`),
   `experimental` flags, and `indexing` config for semantic code search
3. Base URL resolution: `--external-ip` > Docker bridge gateway > `localhost`
4. `main.py --lemonade kilo.json` injects config into each sandbox at `/home/vscode/.config/kilo/config.json`
5. Kilo Code reads the config and connects to the Lemonade server

### Full Workflow

```bash
# Terminal 1: Set up Lemonade server with groups-based scaling
bash setup-lemonade.sh --groups groups.yaml --generate-keys --external-ip 1.2.3.4

# Terminal 2: Start VS Code sandboxes with Lemonade inference
python main.py --groups groups.yaml --external-ip 1.2.3.4 --lemonade kilo.json
```

## AI Gateway (APISIX Rate Limiting)

An optional APISIX API Gateway provides token-based rate limiting and per-consumer API keys
for LLM endpoints. Creates two routes: `/v1/chat/completions` (ai-proxy-multi) and
`/v1/embeddings` (upstream proxy for semantic indexing).

### Consumer Modes

| Mode | Description | Best For |
|------|-------------|----------|
| **per-user** (default) | Each user gets own API key and rate limit | Individual accountability |
| **per-group** | Each group shares one API key with combined limit (`rate_limit × num_users`) | Team-based, shared capacity |

### Setup

```bash
# Install APISIX (or use INSTALL_GATEWAY=true during initial setup)
INSTALL_GATEWAY=true bash ./setup.sh

# Per-user mode
python scripts/apisix_gateway.py setup --groups groups.yaml \
    --lemonade-url http://127.0.0.1:13305

# Per-group mode
python scripts/apisix_gateway.py setup --groups groups.yaml \
    --lemonade-url http://127.0.0.1:13305 --per-group

# With Redis-backed rate limiting
python scripts/apisix_gateway.py setup --groups groups.yaml \
    --lemonade-url http://127.0.0.1:13305 --redis-host 127.0.0.1
```

### Running with main.py

```bash
# Per-user: each user gets their own API key and rate limit
python main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway

# Per-group: shared API key per group
python main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway --gateway-per-group

# With Redis-backed rate limiting
python main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway --gateway-redis-host 127.0.0.1
```

### Rate Limiting Modes

| Mode | Redis Host | Policy | Scope |
|------|-----------|--------|-------|
| **Local** | (not set) | `local` | Per-gateway-instance counters |
| **Redis** | `127.0.0.1` | `redis` | Shared across all gateway instances |

When enabled, `main.py` generates a gateway-aware `kilo.json` that points to the
gateway instead of directly to Lemonade. In per-group mode, all users in the same
group receive the same `kilo.json` with the shared group API key.

## Security

### Sandbox Instances

| Flag | code-server auth | Password |
|------|-----------------|----------|
| (default) | `--auth none` | None |
| `--secure` | `--auth password` | Auto-generated per-user (24-char token) |

### Dashboard Authentication

Two independent mechanisms:

| Method | Scope | Mechanism |
|--------|-------|-----------|
| **Local Password** | Streamlit dashboard | `AUTH_LOCAL_PASSWORD=mysecret` — single shared password |
| **OIDC/OAuth2** | FastAPI REST API | GitHub, GitLab, or LinkedIn via PKCE flow |

```bash
# Local password for dashboard
AUTH_LOCAL_PASSWORD=mysecret streamlit run dashboard/streamlit_app.py --server.port 8501

# OIDC for REST API
AUTH_ENABLED=true \
AUTH_SESSION_SECRET=$(openssl rand -hex 32) \
AUTH_GITHUB_CLIENT_ID=xxx \
AUTH_GITHUB_CLIENT_SECRET=xxx \
python -m app.main
```

## REST API Endpoints

The FastAPI REST API on port 8100 provides Swagger UI at `/docs`.

### Instances

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/instances` | List instances (filter by state, paginate) |
| `POST` | `/api/instances` | Create new instance |
| `POST` | `/api/instances/{id}/pause` | Pause instance |
| `POST` | `/api/instances/{id}/resume` | Resume instance |
| `DELETE` | `/api/instances/{id}` | Terminate instance |
| `POST` | `/api/instances/{id}/renew` | Extend TTL |
| `POST` | `/api/instances/bulk/pause` | Bulk pause |
| `POST` | `/api/instances/bulk/resume` | Bulk resume |
| `POST` | `/api/instances/bulk/kill` | Bulk terminate |

### Groups

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/groups` | List all groups with users |
| `POST` | `/api/groups` | Create a new group |
| `GET` | `/api/groups/export` | Export groups as YAML dict |
| `PUT` | `/api/groups/{group_id}` | Rename a group |
| `DELETE` | `/api/groups/{group_id}` | Delete a group and its users |
| `POST` | `/api/groups/{group_id}/users` | Add a user to a group |
| `DELETE` | `/api/groups/{group_id}/users/{user_id}` | Delete a user |
| `POST` | `/api/groups/{group_id}/users/{user_id}/transfer` | Transfer user to another group |

### Config Files

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config-files` | List all config file slots |
| `GET` | `/api/config-files/{key}` | Get config file content |
| `PUT` | `/api/config-files/{key}` | Update config file content |
| `POST` | `/api/config-files/{key}/upload` | Upload a config file |
| `DELETE` | `/api/config-files/{key}` | Delete a config file |

### Lemonade

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/lemonade/status` | Server status |
| `GET` | `/api/lemonade/models` | Available models |
| `GET` | `/api/lemonade/health` | Proxy: server health |
| `GET` | `/api/lemonade/stats` | Proxy: performance stats |
| `GET` | `/api/lemonade/slots` | Proxy: slot states |
| `POST` | `/api/lemonade/pull` | Proxy: pull a model |
| `POST` | `/api/lemonade/load` | Proxy: load a model |
| `POST` | `/api/lemonade/unload` | Proxy: unload a model |

### Gateway

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/gateway/status` | Gateway status |
| `GET` | `/api/gateway/consumers` | List consumers |
| `POST` | `/api/gateway/consumers` | Create consumer |
| `DELETE` | `/api/gateway/consumers/{username}` | Delete consumer |
| `POST` | `/api/gateway/setup` | Full setup |
| `POST` | `/api/gateway/cleanup` | Remove all consumers and routes |

### Auth

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/auth/providers` | List enabled OIDC/OAuth providers |
| `GET` | `/api/auth/login/{provider}` | Start OAuth flow |
| `GET` | `/api/auth/callback/{provider}` | OAuth callback |
| `POST` | `/api/auth/logout` | End session |
| `GET` | `/api/auth/me` | Current user info |

## Troubleshooting

### Service Worker SSL Error

```
SecurityError: Failed to register a ServiceWorker — An SSL certificate error occurred
```

**Fix**: Use mkcert CA-trusted certs. Remote clients must download and import the
CA root from `https://<ip>/ca.crt`.

### Bad Gateway (502)

Caused by `--base-path` on code-server or including upstream path in `proxy_pass`.
Do NOT use `--base-path` and ensure `proxy_pass` ends with `/` only.

### Model Not Found (404)

The `user.` prefix is required for user-registered models. Kilo Code should send
`user.gemma-4-31b-it` as the model name, not `gemma-4-31b-it`.

### Reserved llama.cpp Arguments

Lemonade manages these arguments internally and rejects them in `llamacpp_args`:
`-ngl`, `--jinja`, `--ctx-size`, `-c`, `-m`, `--port`, `--mmproj*`, `--rerank*`

### Embedding Model Not Loading

1. Check `max_loaded_models` is at least `2` in `config.json`
2. Verify GPU memory can support both models
3. Try disabling: `--no-embedding` flag

## Environment Variables

### Sandbox Server

| Variable | Description | Default |
|----------|-------------|---------|
| `SANDBOX_DOMAIN` | Sandbox server address | `localhost:8080` |
| `SANDBOX_API_KEY` | Sandbox API key | (none) |
| `SANDBOX_IMAGE` | Docker image | `waterpistol/thon:latest` |
| `PYTHON_VERSION` | Python version in sandbox | `3.11` |

### Lemonade Server

| Variable | Description | Default |
|----------|-------------|---------|
| `LEMONADE_HOST` | Lemonade server bind address | `0.0.0.0` |
| `LEMONADE_PORT` | Lemonade server port | `13305` |
| `LEMONADE_API_KEY` | Lemonade API key (regular) | (none) |
| `LEMONADE_ADMIN_API_KEY` | Lemonade admin key (elevated) | (none) |

### AI Gateway

| Variable | Description | Default |
|----------|-------------|---------|
| `GATEWAY_ENABLED` | Enable AI Gateway | `false` |
| `GATEWAY_ADMIN_URL` | APISIX Admin API URL | `http://127.0.0.1:9180` |
| `GATEWAY_PROXY_PORT` | APISIX proxy port | `9080` |
| `GATEWAY_REDIS_HOST` | Redis host for rate limiting | (none) |
| `GATEWAY_RATE_LIMIT_TOKENS` | Token limit per consumer per window | `500` |
| `GATEWAY_RATE_LIMIT_WINDOW` | Rate limit time window in seconds | `60` |
| `GATEWAY_MODE` | Consumer mode: `per-user` or `per-group` | `per-user` |

### Dashboard & Database

| Variable | Description | Default |
|----------|-------------|---------|
| `DASHBOARD_HOST` | FastAPI bind address | `0.0.0.0` |
| `DASHBOARD_PORT` | FastAPI port | `8100` |
| `THON_DB_PATH` | SQLite database path | `~/.thon/thon.db` |
| `THON_WORKSPACE_DIR` | Workspace directory for groups | `~/.thon/workspace` |

### Authentication

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTH_LOCAL_PASSWORD` | Single password for Streamlit dashboard | (none) |
| `AUTH_ENABLED` | Enable OIDC authentication on REST API | `false` |
| `AUTH_SESSION_SECRET` | HMAC secret for session tokens | (none) |
| `AUTH_GITHUB_CLIENT_ID` | GitHub OAuth App client ID | (none) |
| `AUTH_GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret | (none) |
| `AUTH_GITLAB_CLIENT_ID` | GitLab OAuth App client ID | (none) |
| `AUTH_GITLAB_CLIENT_SECRET` | GitLab OAuth App client secret | (none) |
| `AUTH_LINKEDIN_CLIENT_ID` | LinkedIn OIDC client ID | (none) |
| `AUTH_LINKEDIN_CLIENT_SECRET` | LinkedIn OIDC client secret | (none) |

## File Map

### Legacy CLI

| File | Purpose |
|------|---------|
| `main.py` | Entry point; CLI; groups; sandbox orchestration; kilo.json injection |
| `scripts/setup.sh` | One-time host prerequisite installation |
| `scripts/nginx_config.py` | Per-port nginx config generation |
| `scripts/ssl_cert.py` | SSL certificate generation (mkcert/openssl) |
| `scripts/lemonade_server.py` | Lemonade server manager (Python CLI) |
| `scripts/setup-lemonade.sh` | All-in-one Lemonade setup (shell, recommended) |
| `scripts/apisix_gateway.py` | APISIX AI Gateway manager |
| `scripts/build-amd-mi300x-llama-server.sh` | Build llama.cpp for AMD MI300X (gfx942) |

### Unified CLI

| File | Purpose |
|------|---------|
| `thon/` | Unified `thon` CLI package (`thon init`, `thon setup`, `thon run`, `thon config`) |

### Dashboard Application

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI application entry point; lifespan; route mounting |
| `app/config.py` | `AppConfig` — loaded from environment variables |
| `app/models.py` | Pydantic domain models |
| `app/services/sandbox_service.py` | `SandboxService` — fleet CRUD operations |
| `app/services/lemonade_service.py` | `LemonadeService` — server status monitoring |
| `app/api/routes/instances.py` | REST API: instance endpoints |
| `app/api/routes/lemonade.py` | REST API: Lemonade endpoints |
| `app/api/routes/auth.py` | REST API: OIDC/OAuth2 endpoints |
| `app/auth/providers.py` | OIDC/OAuth2 provider implementations |
| `app/auth/sessions.py` | `SessionStore` — HMAC-signed session management |

### Dashboard Frontend

| File | Purpose |
|------|---------|
| `dashboard/streamlit_app.py` | Streamlit dashboard: 5 pages with sidebar navigation |
| `dashboard/streamlit_styles.py` | Dark theme CSS injection |

### Config

| File | Purpose |
|------|---------|
| `config/groups.yaml.example` | Groups and users configuration template |
| `config/kilo.json.example` | Kilo Code config template |
| `config/vscode-settings.jsonc.example` | VS Code settings template |
| `Dockerfile` | Sandbox image: python:3.12-slim + code-server |
