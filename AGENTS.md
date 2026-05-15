# THON AGENTS

Use this file for all work in `./`. Reference template: `examples/vscode/`.
This is a hackathon-focused multi-instance THON development tool with nginx
reverse proxy (SSL via mkcert/openssl/certbot), groups support, persistent workspace
bind mounts and PVC volumes, and optional local LLM inference via Lemonade Server.

## Scope

- `./**` — all files in this directory
- Reference: `examples/vscode/main.py` — simple single-instance pattern

## Commands

```bash
# One-time prerequisite installation (python3, nginx, docker, mkcert, openssl)
# This also creates ~/.venv, installs opensandbox, and auto-generates
# ~/.sandbox.toml with a random API key (no manual init-config needed).
bash ./scripts/setup.sh

# Or use the unified CLI:
python -m thon install
python -m thon install --with-apisix --with-lemonade

# Activate the venv created by setup.sh (required for opensandbox CLI/server)
. ~/.venv/bin/activate

# Lint
pip run ruff check .

# Format
pip run ruff format .

# Type check
pip run pyright

# ── Unified CLI (recommended) ──────────────────────────────────────

# Interactive config wizard (creates ~/.thon/thon.yaml)
python -m thon init

# Non-interactive (CI-friendly defaults)
python -m thon init --non-interactive

# Install prerequisites + configure all components from thon.yaml
python -m thon setup

# Apply APISIX gateway config only
python -m thon gateway

# Start the API server (FastAPI on :8100)
python -m thon run

# Start API server with debug logging
python -m thon run --log-level DEBUG

# Launch VS Code instances (batch mode from thon.yaml)
python -m thon launch
python -m thon launch --group alpha
python -m thon launch --demo

# Config management
python -m thon config show
python -m thon config env --output .env
python -m thon config validate

# Nginx management
python -m thon nginx sync       # regenerate nginx config from active instances
python -m thon nginx cleanup    # remove all THON nginx configs

# Tear down all resources
python -m thon cleanup

# ── Legacy CLI (scripts/main.py) ──────────────────────────────────

# Run: all groups from groups.yaml with nginx + SSL (default)
python ./scripts/main.py --groups groups.yaml --external-ip 165.245.138.159

# Run: single group
python ./scripts/main.py --groups groups.yaml --group alpha --external-ip 1.2.3.4

# Run: from database (uses PVC workspace volumes)
python ./scripts/main.py --from-db --external-ip 1.2.3.4

# Run: with secure per-user passwords
python ./scripts/main.py --groups groups.yaml --secure --external-ip 1.2.3.4

# Run: with persistent workspace bind mounts
python ./scripts/main.py --groups groups.yaml --workspace-dir /thon-workspace

# Run: single instance without groups (like examples/vscode/main.py)
python ./scripts/main.py

# Run: direct HTTP without nginx
python ./scripts/main.py --no-nginx

# Cleanup all nginx configs
python ./scripts/main.py --cleanup

# Build Docker image
docker build -t waterpistol/thon:latest ./

# ── Lemonade Server ────────────────────────────────────────────────

# Full setup via shell (recommended — service manages its own lifecycle)
bash ./scripts/setup-lemonade.sh --groups groups.yaml --generate-keys --external-ip 1.2.3.4

# Full setup without embedding model
bash ./scripts/setup-lemonade.sh --groups groups.yaml --generate-keys --external-ip 1.2.3.4 --no-embedding

# Full setup via Python wrapper (alternative)
python ./scripts/lemonade_server.py run --groups groups.yaml --generate-keys --external-ip 1.2.3.4

# Full setup with custom embedding model
python ./scripts/lemonade_server.py run --groups groups.yaml --generate-keys --external-ip 1.2.3.4 --embedding-model SuperPauly/harrier-oss-v1-0.6b-gguf:harrier-oss-v1-0.6B-BF16

# Dynamic rescaling (adjust ctx_size and -np for different user counts)
python ./scripts/lemonade_server.py rescale --num-users 8

# Service management (systemd, no long-running process needed)
sudo systemctl status lemonade-server
sudo systemctl stop lemonade-server
sudo systemctl restart lemonade-server
sudo journalctl -u lemonade-server -f

# Pull / configure via CLI
lemonade pull unsloth/gemma-4-31B-it-GGUF:Q8_K_XL
lemonade config set llamacpp.backend=auto host=0.0.0.0

# Run VS Code instances with Lemonade inference (injects kilo.jsonc into each sandbox)
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --lemonade kilo.jsonc

# ── AI Gateway ─────────────────────────────────────────────────────

# One-time install (APISIX, etcd, Redis)
INSTALL_GATEWAY=true bash ./scripts/setup.sh
# or: bash ./scripts/setup-apisix.sh

# Setup with per-consumer API keys and rate limiting
python ./scripts/apisix_gateway.py setup --groups groups.yaml --lemonade-url http://127.0.0.1:13305

# Setup with Redis-backed rate limiting
python ./scripts/apisix_gateway.py setup --groups groups.yaml --lemonade-url http://127.0.0.1:13305 --redis-host 127.0.0.1

# Create a single consumer
python ./scripts/apisix_gateway.py create-consumer --username alice --rate-limit 500

# Delete a consumer
python ./scripts/apisix_gateway.py delete-consumer --username alice

# Check gateway status
python ./scripts/apisix_gateway.py status

# Cleanup all consumers and routes
python ./scripts/apisix_gateway.py cleanup

# Generate kilo.jsonc pointing to gateway
python ./scripts/apisix_gateway.py generate-kilo --username alice --api-key alice-key --external-ip 1.2.3.4
```

## Code Style

### Language & Formatting
- **Python 3.10+** (project minimum)
- **ruff** for lint and format; line-length = 88 (follows SDK convention)
- **pyright** with `typeCheckingMode = "standard"` for type checking
- **Apache 2.0 license header** required on every file

### Imports
Order: stdlib → third-party → local:
```python
import argparse
import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import yaml

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.sandboxes import Host, Volume

from nginx_config import NginxConfigGenerator
from ssl_cert import SSLCertificateGenerator
```

### Type Hints
Required on all function signatures. Use `Optional[T]`, `list[T]`, `tuple[str, ...]` syntax (Python 3.10+).

### Naming Conventions
- Functions/methods: `snake_case`
- Classes: `PascalCase`
- Constants / class attrs: `UPPER_SNAKE_CASE`
- Private internals: `_leading_underscore`
- CLI flags: `--kebab-case`

### Docstrings
Google-style on public classes/functions. Module docstring at top of every file.

### Error Handling
- Raise with descriptive messages; chain with `raise ... from e`
- Validate inputs early at function entry

### Async Patterns
- All sandbox operations are async — use `await`
- Use `asyncio.gather()` for concurrent instance creation
- Use `RunCommandOpts(background=True)` for long-running processes (code-server)
- Always use `try/finally` for cleanup (kill sandboxes, remove nginx configs)

### Logging (CLI Tools)
Use `print()` with prefixed labels: `[{group}/{username}]`, `[Nginx]`, `[SSL]`

## Architecture

### Core Models
- **`UserInfo` dataclass**: group, username, email, workspace (`{group}/{username}`), label
- **`InstanceInfo` Pydantic model**: id, user, state, port, endpoint, public_url, domain_url,
  local_url, password, image, created_at, expires_at, metadata
  - Computed `url` property: `domain_url` > `public_url` > `local_url` > `http://{endpoint}/`
- **`InstanceState` enum**: Pending, Running, Pausing, Paused, Stopping, Terminated, Failed
- **`GroupConfig` dataclass**: name, users, title, event_id
- **`EventInfo` dataclass**: event_id, title
- **`NginxStatus` dataclass**: available, external_ip, ssl_configured, ports, config_path

### Key Classes
- **`NginxConfigGenerator`** (two implementations):
  1. **`scripts/nginx_config.py`** (legacy, per-port): generates per-port individual nginx
     config files in `/etc/nginx/sites-available/`, named `sandbox-thon-{port}`.
     Used by `main.py` for batch instance launching.
  2. **`app/nginx_service.py`** (API, combined): generates a single combined config
     `sandbox-thon` with location blocks for all active ports. Used by the API server
     and `thon nginx sync`.
  - Both: `cleanup_all()` removes all `sandbox-thon*` configs and reloads nginx
  - Both support domain-based `server_name` and Let's Encrypt certs
- **`SSLCertificateGenerator`**: generates SSL certs with 4 provider options:
  - **`auto`** (default): tries mkcert → certbot → openssl in order
  - **`certbot`**: Let's Encrypt via certbot (requires domain + port 80)
  - **`mkcert`**: CA-trusted certs (preferred for dev). Filename includes IP hash.
  - **`openssl`**: Self-signed certs with IP/domain in SAN
  - `generate_server_cert(server_ip, domain, ssl_provider, certbot_email)` — returns (cert_path, key_path)
  - `get_mkcert_ca_root()` — returns mkcert CA root dir path (or None)

### thon.yaml Configuration Schema

Single source of truth — all settings in one YAML file. Loaded by `thon/config.py`
(`ThonConfig` Pydantic model). The `.env` file is generated from it.

```yaml
# Root fields
demo: false                    # Demo mode (default workspace when no groups)
external_ip: ""                # External IP for SSL and URLs (auto-detect if empty)
log_level: "INFO"              # Logging level: DEBUG, INFO, WARNING, ERROR
groups:                        # Inline groups definition
  alpha:
    - alice
    - bob

# Sandbox server connection
sandbox:
  domain: "localhost:8080"     # Sandbox server address
  api_key: ""                  # Sandbox API key
  image: "waterpistol/thon:latest"
  starting_port: 8443
  timeout_minutes: 0           # 0 = no timeout

# VS Code instance settings
vscode:
  secure: false                # Enable per-user passwords
  settings_file: ""            # Path to VS Code settings JSON to inject
  extensions_file: ""          # Path to extensions list

# Nginx reverse proxy and SSL
nginx:
  enabled: true
  ssl_dir: "/etc/nginx/ssl"
  domain: ""                   # Domain name for server_name (enables Let's Encrypt)
  ssl_provider: "auto"         # auto, certbot, mkcert, openssl
  certbot_email: ""            # Email for Let's Encrypt registration

# Persistent workspace
workspace:
  dir: ""                      # Host directory for bind mounts (empty = ephemeral)

# Lemonade LLM inference server
lemonade:
  enabled: false
  host: "0.0.0.0"
  port: 13305
  model: "unsloth/gemma-4-31B-it-GGUF:Q8_K_XL"
  model_name: "gemma-4-31b-it"
  mmproj: "mmproj-BF16.gguf"
  ctx_size_per_user: 262144
  embedding_model: "SuperPauly/harrier-oss-v1-0.6b-gguf:harrier-oss-v1-0.6B-BF16"
  embedding_model_name: "harrier-oss-v1-0.6b"
  embedding_ctx_size_per_user: 32768
  embedding_dimensions: 0
  llamacpp_backend: "auto"     # auto, vulkan, cpu
  prefer_system: true          # Use system llama-server over bundled
  llamacpp_bin: "builtin"      # Path to llama-server or "builtin"
  rocm_channel: "preview"      # ROCm channel for AMD GPU support
  generate_keys: true          # Auto-generate API keys on setup
  api_key: ""                  # Regular API key (populated after setup)
  admin_api_key: ""            # Admin API key (populated after setup)
  llamacpp:                    # Inference tuning parameters
    ctk: "q8_0"               # Cache type K
    ctv: "q8_0"               # Cache type V
    batch_size: 8192
    ubatch_size: 8192
    split_mode: ""             # Multi-GPU split mode
    main_gpu: -1               # Primary GPU index
    cpu_moe: false             # Offload MoE to CPU
    n_cpu_moe: 0               # Number of CPU MoE experts
    min_p: 0.0                 # Minimum P sampling
    presence_penalty: 0.0      # Presence penalty
  chat_models:                 # Additional models available for selection
    - name: "gemma-4-31b-it"
      checkpoint: "unsloth/gemma-4-31B-it-GGUF:Q8_K_XL"
      context: 262144
      output: 4096
    - name: "qwen3.6-27b"
      checkpoint: "unsloth/Qwen3.6-27B-GGUF:Q8_K_XL"
      context: 262144
      output: 4096

# Kilo Code extension settings
kilo:
  config_file: ""              # Output path for kilo.jsonc (default: ~/.thon/kilo.jsonc)
  skeleton_file: "config/kilo.jsonc.skeleton"
  chat_model: "lemonade/user.gemma-4-31b-it"
  small_model: ""              # Smaller model for quick tasks

# AI Gateway (APISIX)
gateway:
  enabled: false
  mode: "per-user"             # per-user or per-group
  rate_limit_scope: "per-user" # per-user or per-model
  admin_key: ""                # APISIX admin API key
  redis_host: ""               # Redis host for rate limiting
  redis_port: 6379
  concurrency_limit: 1         # Max concurrent requests per consumer
  token_limit: 0               # Token limit per time window (0 = unlimited)
  token_window: 60             # Time window in seconds
  model_concurrency:           # Per-model rate limits (when rate_limit_scope=per-model)
    - model: "gemma-4-31b-it"
      concurrency_limit: 1
      token_limit: 0
      token_window: 60
      priority: 0

# Langfuse observability
langfuse:
  enabled: false
  public_key: ""
  secret_key: ""
  base_url: "https://cloud.langfuse.com"

# Dashboard
dashboard:
  host: "0.0.0.0"
  port: 8100
  debug: false

# Authentication
auth:
  enabled: false
  session_secret: ""
  github:
    client_id: ""
    client_secret: ""
  gitlab:
    client_id: ""
    client_secret: ""
  linkedin:
    client_id: ""
    client_secret: ""
```

### SQLite Database (`app/db.py`)

SQLite persistence via SQLModel at `~/.thon/thon.db`. Five tables:

| Table | Purpose |
|-------|---------|
| `sandbox_records` | Maps sandbox_id → group, username, port, endpoint, external_ip, image, password |
| `app_settings` | Key-value store for global settings (config files, external IP) |
| `event_records` | Events (hackathons, workshops) that own groups |
| `group_records` | Named groups with optional event_id linkage |
| `user_records` | Users within groups, with workspace_path, storage_path, email, sandbox_id |

**Key functions:**
- `upsert_record()`, `get_record()`, `mark_terminated()`, `mark_orphaned_terminated()`
- `get_setting()`, `set_setting()`, `delete_setting()`, `get_settings_by_prefix()`
- `create_group()`, `get_groups()`, `rename_group()`, `delete_group()`
- `create_user()`, `get_users()`, `update_user()`, `delete_user()`, `transfer_user()`
- `link_user_sandbox()`, `unlink_user_sandbox()`, `find_user_by_sandbox()`
- `load_groups_from_yaml()` — idempotent import from groups.yaml
- `get_or_create_event()`, `get_events()`

**Config file keys stored in `app_settings`:**
- `config_groups_yaml` — Groups and users definition
- `config_kilo_json` — Kilo Code provider config
- `config_vscode_settings` — VS Code settings for each sandbox

### Groups YAML

```yaml
groups:
  alpha:
    users:
      - alice
      - bob
  beta:
    users:
      - dave
```

Each user gets: sandbox instance → workspace at `/workspace/{group}/{username}` → URL at `https://{ip}/{endpoint_path}/`

Groups can also be managed via the dashboard and stored in the SQLite database. When
`main.py` runs with `--from-db`, groups/users are read from the database instead of a
YAML file.

### Network Modes (auto-detected from endpoint format)

| Mode | Server Endpoint Format | Nginx proxy_pass | Detected By |
|------|----------------------|------------------|-------------|
| **Host** | `127.0.0.1:8443` | `http://127.0.0.1:{port}/` | No `/` after port |
| **Bridge** | `127.0.0.1:52322/proxy/8443` | `http://127.0.0.1:{port}/` | `/proxy/` in endpoint |

Bridge/host mode is **auto-detected** from the server-returned endpoint format — NOT a CLI flag.
The server's `~/.sandbox.toml` determines `docker.network_mode`.

**Critical**: `proxy_pass` must NOT include upstream path. `proxy_pass http://127.0.0.1:{port}/;`
is correct. The browser sends the full endpoint path (e.g., `/51111/proxy/8448/`), nginx strips
`/{endpoint_port}/`, and the remainder reaches execd correctly.

### Persistent Workspaces

Three workspace persistence modes:

| Mode | Storage | Lifecycle | How |
|------|---------|-----------|-----|
| **PVC Volume** | Docker named volume (`thon-workspace-{group}-{user}`) | Persists across instance recreations | Automatic when using DB groups |
| **Bind Mount** | Host directory (`--workspace-dir` or `workspace.dir`) | Persists on host filesystem | Via SDK `Volume(host=Host(path=...))` |
| **Ephemeral** | Inside container | Lost when container is removed | Default (no persistence) |

PVC volumes are created automatically via `docker volume create` when users are imported
via the dashboard or `thon.yaml`. When a sandbox is recreated, the same PVC volume is
reattached. Host directories are created with `os.makedirs()` before sandbox creation.

### Security Modes

**Sandbox instances (code-server):**

| Flag | code-server auth | Password |
|------|-----------------|----------|
| (default) | `--auth none` | None |
| `--secure` | `--auth password` | Auto-generated per-user (24-char token) |

**Streamlit dashboard:**

| Env Variable | Auth Mode | Description |
|-------------|-----------|-------------|
| (unset) | None | No authentication |
| `AUTH_LOCAL_PASSWORD` | Single password | Password gate on dashboard access |

**FastAPI REST API:**

| Env Variable | Auth Mode | Description |
|-------------|-----------|-------------|
| `AUTH_ENABLED=false` | None | All endpoints open |
| `AUTH_ENABLED=true` | OIDC/OAuth2 | GitHub, GitLab, or LinkedIn via PKCE flow |

### Certificate Flow

Four SSL providers, selected via `nginx.ssl_provider` in `thon.yaml` or `THON_SSL_PROVIDER`:

1. **auto** (default): Tries mkcert → certbot → openssl in order
2. **certbot**: Let's Encrypt certificates (requires domain + port 80 accessible).
   Email via `nginx.certbot_email` or `THON_CERTBOT_EMAIL`.
3. **mkcert**: CA-trusted certs. Filename includes IP hash.
   - CA root must be installed on client browsers for trust
   - CA cert served at `https://{ip}/ca.crt` for download
4. **openssl** (fallback): Self-signed certs with IP/domain in SAN
5. Single shared cert for all instances on port 443
6. code-server always runs **HTTP** inside containers; nginx terminates SSL externally
7. Domain-based certs: when `nginx.domain` is set, `server_name` uses the domain and
   Let's Encrypt is preferred for CA-trusted certs

### Nginx Template Features

**Per-port config** (`scripts/nginx_config.py`, used by `main.py`):
- Individual server block per port, `server_name _;` (or domain if configured)
- `listen 80;` and `listen 443 ssl;`
- TLSv1.2 + TLSv1.3, `HIGH:!aNULL:!MD5` ciphers
- WebSocket upgrade headers (`Upgrade`, `Connection "upgrade"`)
- `X-Forwarded-For`, `X-Forwarded-Proto https`, `proxy_redirect off`
- `add_header Service-Worker-Allowed /;` (fixes SW scope errors)
- `proxy_read/send_timeout 86400` (24h for long-lived WS connections)
- `proxy_buffering off; proxy_request_buffering off;` (real-time data)
- Conditional `location = /ca.crt` block (only when mkcert CA root exists)

**Combined config** (`app/nginx_service.py`, used by API server):
- Single server block with location blocks for all active ports
- Same SSL, WebSocket, and proxy features
- Generated by `thon nginx sync` and API endpoints

### URL Display
- **Domain URL** (preferred): `https://{domain}/{endpoint_path}/` — when domain is configured
- **Public URL**: `https://{ip}/{endpoint_path}/` — via external IP
- **Local URL**: `http://127.0.0.1:{port}/` — for local access
- `InstanceInfo.url` computed property: `domain_url` > `public_url` > `local_url`
- Example: endpoint `127.0.0.1:51111/proxy/8448` → URL `https://165.245.131.172/51111/proxy/8448/`

### Startup Reconciliation

When `main.py` starts with `--from-db`, it reconciles running instances:
1. Queries the sandbox API for all active sandboxes
2. Marks orphaned DB records (sandbox_id not in API response) as terminated
3. Syncs nginx configs with actual running endpoints
4. Creates Docker named volumes for any DB users missing them

### Kilo Code Integration

Three deployment modes for kilo.jsonc, handled by `app/kilo_config.py`:

| Mode | Config Source | Kilo Points To |
|------|--------------|----------------|
| **lemonade-direct** | `--lemonade kilo.jsonc` | Lemonade server directly |
| **gateway-per-user** | `--gateway` | APISIX gateway (per-user API key) |
| **gateway-per-group** | `--gateway --gateway-per-group` | APISIX gateway (shared group API key) |

**Skeleton merging:** The `kilo.jsonc.skeleton` file provides a base config. Dynamic fields
(provider, apiKey, model, indexing) are deep-merged on top. Template variables are
substituted per-user:
- `$THON_USERNAME` → user's username
- `$THON_USER_EMAIL` → user's email or `{username}@thon.local`
- `$WORKSPACE` → user's workspace path

### Lemonade Server (Local LLM Inference)

A local Lemonade inference server provides OpenAI-compatible LLM endpoints that VS Code
extensions (Kilo Code, Continue, Cline) inside sandbox containers can connect to. The
server runs as a **systemd service** and manages its own lifecycle — no long-running
Python process needed.

**Two ways to set up:**
1. **`setup-lemonade.sh`** (recommended) — Shell script that uses the `lemonade` CLI
   and `systemctl` directly. One command does everything: install, configure, generate
   API keys, pull model, generate kilo.jsonc.
2. **`lemonade_server.py`** — Python wrapper with `LemonadeServerManager` class.
   Provides subcommands (`install`, `configure`, `start`, `stop`, `pull`, `run`, `rescale`,
   etc.) and programmatic access to the same operations. Useful for scripted automation.

**Service management (once installed):**
```bash
sudo systemctl start|stop|restart lemonade-server
sudo systemctl status lemonade-server
sudo journalctl -u lemonade-server -f
lemonade config set key=value
lemonade pull <model>
```

**Configuration:**
- Config file: `/var/lib/lemonade/.cache/lemonade/config.json`
- API keys stored in `/etc/systemd/system/lemonade-server.service.d/override.conf`
- Default port: `13305`, default host: `0.0.0.0`
- Default backend: `auto` (Lemonade auto-detects GPU; can be overridden with `--llamacpp-backend`)
- Custom models: `user_models.json`, `server_models.json`, and `recipe_options.json` in the cache directory

**Default Model:**
- Checkpoint: `unsloth/gemma-4-31B-it-GGUF:Q8_K_XL`
- Short name: `gemma-4-31b-it` (registered as `user.gemma-4-31b-it`; the `user.` prefix is required in API requests)
- Recipe: `llamacpp` with auto-detected backend

**Default Embedding Model:**
- Checkpoint: `SuperPauly/harrier-oss-v1-0.6b-gguf:harrier-oss-v1-0.6B-BF16`
- Short name: `harrier-oss-v1-0.6b` (registered as `user.harrier-oss-v1-0.6b`)
- Recipe: `llamacpp` with `--embedding` flag (managed by Lemonade, NOT in `llamacpp_args`)
- Labels: `["custom", "embedding"]`
- Enabled by default; disable with `--no-embedding`
- `max_loaded_models` is automatically set to `2` when embedding is enabled (1 chat + 1 embedding)

**Per-User Scaling:**
When `--groups groups.yaml` is passed, the number of users is counted automatically and
scales the llama.cpp args in `recipe_options.json`:

| Parameter | Chat Model | Embedding Model |
|-----------|-----------|-----------------|
| `ctx_size` | `262144` per user | `32768` per user |
| `-np` | `num_users` | `num_users` |
| Per-slot `ctx_size` | `262144` | `32768` |

**Dynamic Rescaling:** Use `python ./scripts/lemonade_server.py rescale --num-users N`
or `POST /api/lemonade/rescale?num_users=N` to adjust context size and parallel slots
without restarting the server. This rewrites `recipe_options.json` and reloads models.

**Llamacpp Tuning Parameters** (via `thon.yaml` `lemonade.llamacpp` or `--llamacpp-args`):
```
-b 8192 -ub 8192 -to 3600 -ctk q8_0 -ctv q8_0
--split-mode <mode> --main-gpu <idx>
--cpu-moe --n-cpu-moe <n>
--temp 1.0 --top-k 64 --top-p 0.95 --min-p 0.0
--repeat-penalty 1.0 --presence-penalty 0.0
--no-webui --threads-http -1 --threads -1
-np <num_users>
```

Lemonade-managed args (reserved, must NOT be in `llamacpp_args`):
`--ctx-size`, `-c`, `-ngl`, `--gpu-layers`, `--n-gpu-layers`, `--jinja`, `--no-jinja`,
`--model`, `-m`, `--port`, `--embedding`, `--embeddings`, `--mmproj*`, `--rerank*`

**user_models.json example:**
```json
{
    "gemma-4-31b-it": {
        "model_name": "gemma-4-31b-it",
        "checkpoint": "unsloth/gemma-4-31B-it-GGUF:Q8_K_XL",
        "recipe": "llamacpp",
        "suggested": true,
        "labels": ["custom", "vision"],
        "mmproj": "mmproj-BF16.gguf"
    },
    "harrier-oss-v1-0.6b": {
        "model_name": "harrier-oss-v1-0.6b",
        "checkpoint": "SuperPauly/harrier-oss-v1-0.6b-gguf:harrier-oss-v1-0.6B-BF16",
        "recipe": "llamacpp",
        "suggested": true,
        "labels": ["custom", "embedding"]
    }
}
```

**recipe_options.json example (4 users):**
```json
{
    "user.gemma-4-31b-it": {
        "ctx_size": 262144,
        "llamacpp_backend": "auto",
        "llamacpp_args": "-b 8192 -ub 8192 -to 3600 -ctk q8_0 -ctv q8_0 --temp 1.0 --top-k 64 --top-p 0.95 --min-p 0.0 --repeat-penalty 1.0 --no-webui --threads-http -1 --threads -1 -np 4"
    },
    "user.harrier-oss-v1-0.6b": {
        "ctx_size": 32768,
        "llamacpp_backend": "auto",
        "llamacpp_args": "-b 8192 -ub 8192 -to 3600 -ctk q8_0 -ctv q8_0 --no-webui --threads-http -1 --threads -1 -np 4"
    }
}
```

**API Key Security:**
| Env Variable | Access Level |
|---|---|
| `LEMONADE_API_KEY` | Regular endpoints (`/api/*`, `/v0/*`, `/v1/*`) |
| `LEMONADE_ADMIN_API_KEY` | All endpoints including `/internal/*` |

When both are set, either key is accepted for regular endpoints; admin key is required for internal.

**Full Workflow:**
```bash
# Terminal 1: Start Lemonade server with groups-based user count (generates kilo.jsonc)
python ./scripts/lemonade_server.py run --groups groups.yaml --generate-keys --external-ip 1.2.3.4

# Terminal 2: Start VS Code sandboxes with Lemonade inference
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --lemonade kilo.jsonc
```

### AI Gateway (APISIX Rate Limiting & Per-Consumer Keys)

An optional APISIX API Gateway provides token-based rate limiting and per-consumer API keys
for LLM endpoints. Creates two routes: `/v1/chat/completions` (ai-proxy-multi) and
`/v1/embeddings` (upstream proxy for semantic indexing). Supports two consumer modes:

- **per-user** (default): Each user gets their own API key and rate limit
- **per-group**: Each group shares one API key with a combined rate limit
  (`rate_limit_per_user * num_users_in_group`)

**Rate limit scopes** (via `gateway.rate_limit_scope`):
- **per-user**: Uniform limits across all models
- **per-model**: Different concurrency/token limits per model via `model_concurrency` list

Redis-backed rate limiting ensures consistency across multiple gateway instances.

**Components:**
- **APISIX** — API gateway with `ai-proxy-multi` (LLM load balancing), `ai-rate-limiting`
  (token-based rate limiting), `limit-conn` (concurrency control), and `key-auth`
  (per-consumer API keys) plugins
- **etcd** — APISIX configuration store
- **Redis** — Optional shared rate limit counter store (local policy used if not configured)

**Installation:**
```bash
# Option 1: During initial setup
INSTALL_GATEWAY=true bash ./scripts/setup.sh

# Option 2: Standalone install script
bash ./scripts/setup-apisix.sh

# Option 3: Via unified CLI
python -m thon install --with-apisix
```

This installs `etcd-server`, `redis-server`, and `apisix` apt packages, starts services,
and configures the APISIX admin key.

**CLI Usage (`scripts/apisix_gateway.py`):**
```bash
# Full setup: create route + consumers from groups.yaml
python scripts/apisix_gateway.py setup \
  --groups groups.yaml \
  --lemonade-url http://127.0.0.1:13305 \
  --redis-host 127.0.0.1

# Create a single consumer
python scripts/apisix_gateway.py create-consumer --username alice --rate-limit 500

# Delete a consumer
python scripts/apisix_gateway.py delete-consumer --username alice

# Check gateway status
python scripts/apisix_gateway.py status

# Remove all consumers and routes
python scripts/apisix_gateway.py cleanup

# Generate kilo.jsonc pointing to gateway
python scripts/apisix_gateway.py generate-kilo --username alice --api-key alice-key --external-ip 1.2.3.4
```

**Integration with `main.py`:**
```bash
# Run with gateway enabled — per-user (auto-creates consumers from groups.yaml)
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway

# Per-group: one consumer per group with shared API key
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway --gateway-per-group

# With Redis-backed rate limiting
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway --gateway-redis-host 127.0.0.1

# Custom rate limits
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 \
  --gateway --gateway-rate-limit 1000 --gateway-time-window 120
```

When `--gateway` is enabled:
1. Gateway consumers are created BEFORE sandbox instances
2. Each consumer gets `key-auth` credential + `ai-rate-limiting` plugin config
3. In per-group mode, all users in a group share the same API key; rate limit is `per_user_limit * num_users`
4. A gateway-aware `kilo.jsonc` is injected into each sandbox, pointing to the gateway
   instead of directly to Lemonade
5. Gateway cleanup runs in the `finally` block alongside nginx and sandbox cleanup

**Rate Limiting Modes:**

| Mode | `--gateway-redis-host` | Policy | Scope |
|------|----------------------|--------|-------|
| Local | (not set) | `local` | Per-gateway-instance counters |
| Redis | `127.0.0.1` | `redis` | Shared across all gateway instances |

**Consumer Configuration (APISIX Admin API):**

Each consumer gets:
- `key-auth` plugin with auto-generated 24-char API key
- `ai-rate-limiting` plugin with `total_tokens` strategy per Lemonade instance
- `limit-conn` plugin for concurrency control

**Dashboard API Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/gateway/status` | Gateway status (running, consumers, route, redis) |
| `GET` | `/api/gateway/consumers` | List consumers with API keys and rate limits |
| `POST` | `/api/gateway/consumers` | Create consumer |
| `DELETE` | `/api/gateway/consumers/{username}` | Delete consumer |
| `POST` | `/api/gateway/setup` | Full setup (route + consumers from DB groups) |
| `POST` | `/api/gateway/route` | Create/update AI proxy route |
| `DELETE` | `/api/gateway/route` | Delete AI proxy route |
| `POST` | `/api/gateway/cleanup` | Remove all consumers and routes |

**Environment Variables (Gateway):**

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_ENABLED` | `false` | Enable AI Gateway features in dashboard |
| `GATEWAY_ADMIN_URL` | `http://127.0.0.1:9180` | APISIX Admin API URL |
| `GATEWAY_ADMIN_KEY` | (auto-detected) | APISIX Admin API key (auto-detected from `/usr/local/apisix/conf/config.yaml` if not set) |
| `GATEWAY_PROXY_PORT` | `9080` | APISIX proxy port |
| `GATEWAY_REDIS_HOST` | (none) | Redis host for rate limiting |
| `GATEWAY_REDIS_PORT` | `6379` | Redis port |
| `GATEWAY_REDIS_PASSWORD` | (none) | Redis password |
| `GATEWAY_RATE_LIMIT_TOKENS` | `500` | Default token limit per consumer per time window |
| `GATEWAY_RATE_LIMIT_WINDOW` | `60` | Rate limit time window in seconds |
| `GATEWAY_MODE` | `per-user` | Consumer mode: `per-user` or `per-group` |
| `GATEWAY_RATE_LIMIT_SCOPE` | `per-user` | Rate limit scope: `per-user` or `per-model` |
| `GATEWAY_CONCURRENCY_LIMIT` | `1` | Concurrency limit per consumer |

### Langfuse Observability (LLM Tracing)

Langfuse integration adds automatic LLM observability to Kilo Code via the
`opencode-plugin-langfuse` package. It captures OpenTelemetry spans for sessions,
messages, tool calls, costs, and performance, sending them to your Langfuse dashboard.

**Setup:**

1. Sign up at [cloud.langfuse.com](https://cloud.langfuse.com) (or self-host)
2. Get your API keys from the project settings
3. Enable via CLI flag or `thon.yaml`

**CLI Usage:**

```bash
# Enable Langfuse with env vars
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_BASEURL="https://cloud.langfuse.com"  # optional, defaults to cloud
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --langfuse

# Or pass keys as CLI flags
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 \
  --langfuse \
  --langfuse-public-key "pk-lf-..." \
  --langfuse-secret-key "sk-lf-..." \
  --langfuse-base-url "https://cloud.langfuse.com"

# With Lemonade + Langfuse
bash ./scripts/setup-lemonade.sh --groups groups.yaml --generate-keys --external-ip 1.2.3.4 --langfuse
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --lemonade kilo.jsonc --langfuse

# With AI Gateway + Langfuse
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway --langfuse
```

**thon.yaml Configuration:**

```yaml
langfuse:
  enabled: true
  public_key: "pk-lf-..."
  secret_key: "sk-lf-..."
  base_url: "https://cloud.langfuse.com"  # optional, defaults to cloud
```

**What happens when Langfuse is enabled:**

1. `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASEURL` are injected as
   environment variables into each sandbox container
2. `"plugin": ["opencode-plugin-langfuse"]` is added to the generated `kilo.jsonc`
3. `experimental.openTelemetry` is set to `true` in the kilo config (already in skeleton)
4. `opencode-plugin-langfuse` npm package is preinstalled globally in the Docker image
5. All LLM traces are automatically sent to your Langfuse dashboard

**Environment Variables (Langfuse):**

| Variable | Default | Description |
|----------|---------|-------------|
| `LANGFUSE_ENABLED` | `false` | Enable Langfuse observability |
| `LANGFUSE_PUBLIC_KEY` | (none) | Langfuse public key (required for tracing) |
| `LANGFUSE_SECRET_KEY` | (none) | Langfuse secret key (required for tracing) |
| `LANGFUSE_BASEURL` | `https://cloud.langfuse.com` | Langfuse API base URL (self-hosted or cloud) |

**kilo.jsonc Plugin Configuration:**

When `langfuse.enabled` is true or `--langfuse` is passed, the generated `kilo.jsonc`
includes:

```jsonc
{
  "experimental": {
    "openTelemetry": true  // required for plugin to work
  },
  "plugin": ["opencode-plugin-langfuse"]
}
```

## Guardrails

### Must Always
- Generate SSL certs on the **host** via mkcert/openssl/certbot, never inside containers
- Clean up nginx configs + kill sandboxes in `finally` blocks
- Include Apache 2.0 header on every new file
- Use `--external-ip` when accessing via IP address (prevents SW SSL errors)
- Auto-detect network mode from endpoint format, NOT from a CLI flag
- Use `pip install` (not `uv`) — user's intentional choice
- Use image `waterpistol/thon:latest` for Docker builds
- Use `thon.yaml` as the single source of truth for configuration

### Must Never
- Commit secrets, API keys, or `.key` files to the repository
- Generate certs inside sandbox containers
- Mix unrelated changes in one PR
- Use `--base-path` on code-server — it breaks the proxy chain (causes bad gateway)
- Include upstream path in `proxy_pass` (causes path doubling)
- Use `uv` for package management

### Known Gotchas

**Service Worker SSL Error**:
```
SecurityError: Failed to register a ServiceWorker for scope ('https://{ip}/{path}/.../pre/')
An SSL certificate error occurred when fetching the script.
```
- **Root cause**: Self-signed certs cause SW registration to fail
- **Fix**: mkcert CA-trusted certs fix this on the host. Remote clients must download
  and import the CA root from `https://{ip}/ca.crt`. For production, use certbot/Let's Encrypt.

**proxy_pass path doubling**: `proxy_pass http://127.0.0.1:45960/proxy/8447/;` causes
nginx to strip the location prefix then prepend the proxy_pass URI, doubling the path.
Correct: `proxy_pass http://127.0.0.1:45960/;`

**--base-path breaks proxy chain**: In bridge mode, execd strips `/proxy/{port}` before
forwarding to code-server. If code-server has `--base-path /{port}/`, it expects `/8443/`
but receives `/`, causing bad gateway. Do NOT use `--base-path`.

**listen 80 default_server conflicts**: nginx's default site uses `default_server`.
Must remove default site and use `listen 80;` without `default_server`.

**GitHub cookie warnings**: `_gh_sess`, `_octo`, `logged_in` cookies are from VS Code
extensions making cross-site requests to github.com — cannot be fixed server-side.

**Nginx dual approach**: `scripts/nginx_config.py` generates per-port configs (used by
`main.py` batch launcher), while `app/nginx_service.py` generates a single combined
config (used by API server and `thon nginx sync`). Both coexist; the API server approach
is preferred for dashboard-driven workflows.

**Environment Variables**:
- `SANDBOX_DOMAIN` — server address (default: `localhost:8080`)
- `SANDBOX_API_KEY` — optional API key
- `SANDBOX_IMAGE` — Docker image (default: `waterpistol/thon:latest`)
- `THON_DB_PATH` — SQLite database path (default: `~/.thon/thon.db`)
- `THON_WORKSPACE_DIR` — workspace directory for groups (default: `~/.thon/workspace`)
- `THON_DOMAIN` — domain name for nginx server_name and Let's Encrypt
- `THON_SSL_PROVIDER` — SSL provider: auto, certbot, mkcert, openssl
- `THON_CERTBOT_EMAIL` — email for Let's Encrypt registration
- `THON_KILO_CONFIG` — path to kilo.jsonc
- `THON_VSCODE_SETTINGS` — path to VS Code settings file
- `THON_LOG_LEVEL` — logging level (default: `INFO`)
- `PYTHON_VERSION` — Python version in sandbox (default: `3.12`)
- `LEMONADE_API_KEY` — Lemonade server API key for regular endpoints
- `LEMONADE_ADMIN_API_KEY` — Lemonade server admin key (elevated access)
- `LANGFUSE_PUBLIC_KEY` — Langfuse public key for LLM observability
- `LANGFUSE_SECRET_KEY` — Langfuse secret key for LLM observability
- `LANGFUSE_BASEURL` — Langfuse API base URL (default: `https://cloud.langfuse.com`)

## File Map

### Unified CLI (`thon/`)

| File | Purpose |
|------|---------|
| `thon/__main__.py` | Entry point: delegates to `thon.cli.main()` |
| `thon/cli.py` | Unified CLI: `install`, `init`, `setup`, `gateway`, `run`, `launch`, `config`, `nginx`, `cleanup` |
| `thon/config.py` | `ThonConfig` + 14 Pydantic settings models (thon.yaml schema) |
| `thon/install.py` | System package installer (config-free phase) |
| `thon/interactive.py` | Init wizard with 12 interactive steps |

### Legacy CLI (`main.py`, `scripts/`)

| File | Purpose |
|------|---------|
| `main.py` | Legacy batch launcher; argparse CLI; groups loading; instance orchestration; kilo.jsonc injection |
| `scripts/setup.sh` | One-time install: python3, nginx, docker.io, mkcert, openssl |
| `scripts/nginx_config.py` | `NginxConfigGenerator`; per-port individual configs in sites-available |
| `scripts/ssl_cert.py` | `SSLCertificateGenerator`; 4 providers (auto, certbot, mkcert, openssl) |
| `scripts/generate-certs.py` | Legacy mkcert helper (preserved for local dev) |
| `scripts/lemonade_server.py` | `LemonadeServerManager`; Python wrapper with 13 subcommands including rescale |
| `scripts/setup-lemonade.sh` | All-in-one shell script: install, configure, generate API keys, pull model, generate kilo.jsonc (recommended) |
| `scripts/apisix_gateway.py` | APISIX AI Gateway manager; 6 subcommands with per-model concurrency |
| `scripts/build.sh` | Build helper script |
| `scripts/build-amd-mi300x-llama-server.sh` | Build llama.cpp from source for AMD MI300X (gfx942) with ROCm |
| `scripts/prerequisite-script.sh` | Prerequisite installation |
| `config/groups.yaml.example` | Groups and users configuration template |
| `config/kilo.jsonc.example` | Kilo Code config template for Lemonade OpenAI-compatible provider |
| `config/kilo.jsonc.skeleton` | Base kilo.jsonc with experimental flags, permissions, MCP, indexing |
| `config/vscode-settings.jsonc.example` | VS Code settings template injected into each sandbox's code-server |
| `config/extensions.txt` | VS Code extensions list for Docker image |
| `reference/kilo.config.schema.json` | Kilo config JSON schema |
| `reference/template.portnumber.available.md` | Nginx template reference |
| `Dockerfile` | Sandbox image: ubuntu:24.04 + code-server + Node.js 24 + JRE + .NET 10 + Chromium |

### Dashboard Application (`app/`)

| File | Purpose |
|------|---------|
| `app/__init__.py` | Package init |
| `app/main.py` | FastAPI application entry point; lifespan; static file serving; route mounting |
| `app/config.py` | `AppConfig` and sub-configs; loaded from env vars (`SANDBOX_*`, `LEMONADE_*`, `DASHBOARD_*`, `AUTH_*`) |
| `app/models.py` | Pydantic domain models: `InstanceInfo`, `InstanceState`, `UserInfo`, `LemonadeStatus`, `GroupConfig`, `EventInfo`, `NginxStatus`, `GatewayStatus` |
| `app/db.py` | SQLite database layer: 5 tables (sandbox_records, app_settings, event_records, group_records, user_records) |
| `app/nginx_service.py` | Combined nginx config generator for API server (single config, all ports) |
| `app/kilo_config.py` | Kilo config generation: skeleton merging, 3 deployment modes, template var substitution |
| `app/exceptions.py` | Custom exceptions: `VSCRemoteError`, `SandboxCreateError`, `LemonadeConnectionError`, `AuthError`, etc. |
| `app/services/sandbox_service.py` | `SandboxService` — wraps sandbox SDK for fleet CRUD, URL building, reconciliation, nginx sync |
| `app/services/lemonade_service.py` | `LemonadeService` — status monitoring, model listing, API info, dynamic rescaling |
| `app/services/groups_service.py` | `GroupsService` — group/user CRUD with Docker volume management |
| `app/services/apisix_service.py` | `ApisixService` — APISIX Admin API wrapper |
| `app/api/routes/instances.py` | REST API: `GET/POST /api/instances`, `POST pause/resume/kill/renew`, `POST bulk/*` |
| `app/api/routes/lemonade.py` | REST API: Lemonade status, models, health, stats, slots, pull, load, unload, rescale |
| `app/api/routes/groups.py` | REST API: groups CRUD, users, events, export |
| `app/api/routes/users.py` | REST API: users CRUD, launch/stop per-user instances |
| `app/api/routes/gateway.py` | REST API: gateway status, consumers, setup, cleanup |
| `app/api/routes/config_files.py` | REST API: config file CRUD (groups YAML, kilo.jsonc, VS Code settings) |
| `app/api/routes/nginx.py` | REST API: nginx sync, cleanup, status |
| `app/api/routes/auth.py` | REST API: `GET /api/auth/providers`, `/login/{provider}`, `/callback/{provider}`, `/logout`, `/me` |
| `app/auth/providers.py` | OIDC/OAuth2 provider implementations: `GitHubProvider`, `GitLabProvider`, `LinkedInProvider`; PKCE support |
| `app/auth/sessions.py` | `SessionStore` — in-memory session management with HMAC-signed tokens |
| `app/auth/deps.py` | FastAPI dependencies: `get_current_user`, `optional_user` |

### Dashboard Frontend (`dashboard/`)

| File | Purpose |
|------|---------|
| `dashboard/streamlit_app.py` | Streamlit dashboard: 7 pages with sidebar navigation |
| `dashboard/streamlit_styles.py` | Dark theme CSS injection for Streamlit (matches original JS dashboard theme) |
| `dashboard/index.html` | Legacy single-page HTML shell (superseded by Streamlit) |
| `dashboard/static/style.css` | Legacy dark theme CSS (superseded by Streamlit) |
| `dashboard/static/app.js` | Legacy frontend JS (superseded by Streamlit) |

### Documentation Site (`fumadocs/`)

| File | Purpose |
|------|---------|
| `fumadocs/` | Next.js + Fumadocs documentation site (MDX content) |
| `fumadocs/app/docs/` | Documentation layout and pages |

### Development Tools (`development-tools/`)

| File | Purpose |
|------|---------|
| `development-tools/azure/bootstrap-ephemeral.sh` | NVMe disk discovery, formatting, and mounting for Azure ephemeral storage |
| `development-tools/azure/ephemeral-setup.service` | systemd unit for boot-time NVMe setup (runs before Docker/Lemonade) |
| `development-tools/azure/README.md` | Azure ephemeral NVMe orchestration documentation |

### Config

| File | Purpose |
|------|---------|
| `config/groups.yaml.example` | Groups and users configuration template |
| `config/kilo.jsonc.example` | Kilo Code config template |
| `config/kilo.jsonc.skeleton` | Base kilo.jsonc with experimental flags, permissions, MCP, indexing |
| `config/vscode-settings.jsonc.example` | VS Code settings template |
| `config/extensions.txt` | VS Code extensions list for Docker image |
| `Dockerfile` | Sandbox image: ubuntu:24.04 + Node.js 24 + JRE + .NET 10 + Chromium + Open VSX |

## Dashboard Architecture

### Backend (FastAPI)

```
app/main.py          → FastAPI app, lifespan, redirects / to /docs
app/api/routes/      → REST API route handlers (9 route modules)
app/services/        → Business logic layer (wraps sandbox SDK + Lemonade + Groups + APISIX)
app/auth/            → OIDC providers, session store, FastAPI deps
app/config.py        → Environment-driven configuration
app/models.py        → Pydantic domain models
app/db.py            → SQLite persistence (5 tables)
app/nginx_service.py → Nginx config management for API server
app/kilo_config.py   → Kilo config generation with skeleton merging
```

**Key design decisions:**
- `SandboxService` wraps `opensandbox.SandboxManager` for fleet ops and `opensandbox.Sandbox` for single-instance ops
- `LemonadeService` supports dynamic rescaling via subprocess call to `lemonade_server.py rescale`
- `GroupsService` manages groups/users with automatic Docker named volume creation
- Auth is optional — when `AUTH_ENABLED` is false, all endpoints are open
- Session tokens are HMAC-signed; replace with Redis/DB for production
- FastAPI no longer serves the dashboard UI — it only provides the REST API
- `/` redirects to `/docs` (Swagger UI) since the dashboard is served by Streamlit
- SQLite at `~/.thon/thon.db` stores sandbox records, groups, users, events, and settings
- Simple auto-migration: `_migrate()` adds missing columns on startup

### Frontend (Streamlit)

```
dashboard/streamlit_app.py     → Main Streamlit app with sidebar nav and 7 pages
dashboard/streamlit_styles.py  → Dark theme CSS injection (matches original JS theme)
dashboard/index.html           → Legacy HTML shell (superseded by Streamlit)
dashboard/static/style.css     → Legacy dark theme CSS (superseded by Streamlit)
dashboard/static/app.js        → Legacy frontend JS (superseded by Streamlit)
```

**Architecture:**
- Streamlit calls services directly (`SandboxService`, `LemonadeService`, `GroupsService`, `app.db`)
  — no HTTP API calls needed between frontend and backend
- FastAPI REST API on port 8100 still available for programmatic/scripted access
- Streamlit runs as a separate process on port 8501
- Both processes share the same `AppConfig` loaded from environment variables

**Pages:**
| Page | Features |
|------|----------|
| Instances | List, search/filter by state, create, pause/resume/kill, bulk actions, recreate with PVC volume |
| Groups | CRUD groups/users, transfer users, start per-user/group instances with PVC workspaces |
| Users | List, search, create/edit users with email, launch/stop per-user instances |
| Workspaces | Overview of workspace volumes and mount status |
| Lemonade Server | Status, API info, health, performance stats, slots, system info, available models, dynamic rescale |
| AI Gateway | Configure, setup, manage consumers, cleanup, mode/rate limit settings |
| Settings | External IP, configuration file management (upload/edit/delete from DB) |

**Key implementation details:**
- Async service calls are bridged via `_run_async()` which uses `asyncio.run()` in a
  `ThreadPoolExecutor` when called from within an existing event loop
- Service instances are cached in `st.session_state` to avoid re-creation on rerun
- Dialog patterns use `st.container(border=True)` with session state flags
  (e.g., `st.session_state.show_create_instance`) for open/close toggling
- `st.dataframe(on_select="rerun", selection_mode="multi-row")` enables multi-instance
  selection for bulk pause/resume/kill actions
- Dark theme is injected once at app startup via `inject_dark_theme()` which writes
  CSS variables matching the original JS dashboard's color scheme
- `_safe_proxy()` catches `LemonadeConnectionError` for non-critical Lemonade API calls
  so the page still renders when the server is offline

### REST API Endpoints

#### Instances

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/instances` | List instances (filter by state, paginate) |
| `POST` | `/api/instances` | Create new instance |
| `GET` | `/api/instances/{id}` | Get instance details |
| `POST` | `/api/instances/{id}/pause` | Pause instance |
| `POST` | `/api/instances/{id}/resume` | Resume instance |
| `DELETE` | `/api/instances/{id}` | Terminate instance |
| `POST` | `/api/instances/{id}/renew` | Extend TTL |
| `POST` | `/api/instances/bulk/pause` | Bulk pause |
| `POST` | `/api/instances/bulk/resume` | Bulk resume |
| `POST` | `/api/instances/bulk/kill` | Bulk terminate |

#### Groups

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

#### Users

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/users` | List all users |
| `POST` | `/api/users` | Create a user |
| `GET` | `/api/users/{user_id}` | Get user details |
| `PUT` | `/api/users/{user_id}` | Update user |
| `DELETE` | `/api/users/{user_id}` | Delete user |
| `POST` | `/api/users/{user_id}/launch` | Launch sandbox instance for user |
| `POST` | `/api/users/{user_id}/stop` | Stop user's sandbox instance |

#### Config Files

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config-files` | List all config file slots |
| `GET` | `/api/config-files/{key}` | Get config file content |
| `PUT` | `/api/config-files/{key}` | Update config file content |
| `POST` | `/api/config-files/{key}/upload` | Upload a config file |
| `DELETE` | `/api/config-files/{key}` | Delete a config file |

#### Lemonade

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/lemonade/status` | Server status |
| `GET` | `/api/lemonade/models` | Available models |
| `GET` | `/api/lemonade/api-info` | API endpoint info |
| `GET` | `/api/lemonade/health` | Proxy: server health |
| `GET` | `/api/lemonade/stats` | Proxy: performance stats |
| `GET` | `/api/lemonade/system-info` | Proxy: hardware details |
| `GET` | `/api/lemonade/live` | Proxy: liveness probe |
| `GET` | `/api/lemonade/slots` | Proxy: slot states |
| `POST` | `/api/lemonade/slots/{id}/save` | Proxy: save slot cache |
| `POST` | `/api/lemonade/slots/{id}/restore` | Proxy: restore slot cache |
| `POST` | `/api/lemonade/slots/{id}/erase` | Proxy: erase slot cache |
| `POST` | `/api/lemonade/pull` | Proxy: pull a model |
| `GET` | `/api/lemonade/pull/variants` | Proxy: GGUF variants for a checkpoint |
| `POST` | `/api/lemonade/delete` | Proxy: delete a model |
| `POST` | `/api/lemonade/load` | Proxy: load a model |
| `POST` | `/api/lemonade/unload` | Proxy: unload a model |
| `POST` | `/api/lemonade/install` | Proxy: install a backend |
| `POST` | `/api/lemonade/uninstall` | Proxy: remove a backend |
| `POST` | `/api/lemonade/rescale` | Dynamic rescale (adjust ctx_size/np for user count) |

#### Gateway

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/gateway/status` | Gateway status |
| `GET` | `/api/gateway/consumers` | List consumers |
| `POST` | `/api/gateway/consumers` | Create consumer |
| `DELETE` | `/api/gateway/consumers/{username}` | Delete consumer |
| `POST` | `/api/gateway/setup` | Full setup |
| `POST` | `/api/gateway/route` | Create/update AI proxy route |
| `DELETE` | `/api/gateway/route` | Delete AI proxy route |
| `POST` | `/api/gateway/cleanup` | Remove all consumers and routes |

#### Nginx

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/nginx/status` | Nginx status |
| `POST` | `/api/nginx/sync` | Regenerate nginx config from active instances |
| `POST` | `/api/nginx/cleanup` | Remove all THON nginx configs |

#### Auth

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/auth/providers` | List enabled OIDC/OAuth providers |
| `GET` | `/api/auth/login/{provider}` | Start OAuth flow |
| `GET` | `/api/auth/callback/{provider}` | OAuth callback |
| `POST` | `/api/auth/logout` | End session |
| `GET` | `/api/auth/me` | Current user info |

### Environment Variables (Dashboard)

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_DOMAIN` | `localhost:8080` | Sandbox server address |
| `SANDBOX_API_KEY` | (none) | Sandbox API key |
| `SANDBOX_IMAGE` | `waterpistol/thon:latest` | Docker image for sandboxes |
| `LEMONADE_HOST` | `0.0.0.0` | Lemonade server bind address |
| `LEMONADE_PORT` | `13305` | Lemonade server port |
| `LEMONADE_API_KEY` | (none) | Lemonade API key |
| `LEMONADE_ADMIN_API_KEY` | (none) | Lemonade admin API key |
| `DASHBOARD_HOST` | `0.0.0.0` | Dashboard bind address |
| `DASHBOARD_PORT` | `8100` | Dashboard port |
| `DASHBOARD_SECRET_KEY` | (none) | FastAPI secret key |
| `DASHBOARD_DEBUG` | `false` | Enable debug/reload mode |
| `THON_DB_PATH` | `~/.thon/thon.db` | SQLite database path |
| `THON_WORKSPACE_DIR` | `~/.thon/workspace` | Workspace directory for groups |
| `THON_DOMAIN` | (none) | Domain name for nginx and Let's Encrypt |
| `THON_SSL_PROVIDER` | `auto` | SSL provider: auto, certbot, mkcert, openssl |
| `THON_CERTBOT_EMAIL` | (none) | Email for Let's Encrypt registration |
| `THON_KILO_CONFIG` | (none) | Path to kilo.jsonc |
| `THON_VSCODE_SETTINGS` | (none) | Path to VS Code settings file |
| `THON_LOG_LEVEL` | `INFO` | Logging level |
| `AUTH_ENABLED` | `false` | Enable OIDC authentication |
| `AUTH_SESSION_SECRET` | (none) | HMAC secret for session tokens |
| `AUTH_GITHUB_CLIENT_ID` | (none) | GitHub OAuth app client ID |
| `AUTH_GITHUB_CLIENT_SECRET` | (none) | GitHub OAuth app client secret |
| `AUTH_GITLAB_CLIENT_ID` | (none) | GitLab OAuth app client ID |
| `AUTH_GITLAB_CLIENT_SECRET` | (none) | GitLab OAuth app client secret |
| `AUTH_LINKEDIN_CLIENT_ID` | (none) | LinkedIn OIDC client ID |
| `AUTH_LINKEDIN_CLIENT_SECRET` | (none) | LinkedIn OIDC client secret |
| `AUTH_LOCAL_PASSWORD` | (none) | Single-password auth for Streamlit dashboard; unset = no auth |
| `GATEWAY_ENABLED` | `false` | Enable AI Gateway features in dashboard |
| `GATEWAY_ADMIN_URL` | `http://127.0.0.1:9180` | APISIX Admin API URL |
| `GATEWAY_ADMIN_KEY` | (auto-detected) | APISIX Admin API key |
| `GATEWAY_PROXY_PORT` | `9080` | APISIX proxy port |
| `GATEWAY_REDIS_HOST` | (none) | Redis host for rate limiting |
| `GATEWAY_REDIS_PORT` | `6379` | Redis port |
| `GATEWAY_REDIS_PASSWORD` | (none) | Redis password |
| `GATEWAY_RATE_LIMIT_TOKENS` | `500` | Default token limit per consumer per time window |
| `GATEWAY_RATE_LIMIT_WINDOW` | `60` | Rate limit time window in seconds |
| `GATEWAY_MODE` | `per-user` | Consumer mode: `per-user` or `per-group` |
| `GATEWAY_RATE_LIMIT_SCOPE` | `per-user` | Rate limit scope: `per-user` or `per-model` |
| `GATEWAY_CONCURRENCY_LIMIT` | `1` | Concurrency limit per consumer |
| `LANGFUSE_ENABLED` | `false` | Enable Langfuse observability |
| `LANGFUSE_PUBLIC_KEY` | (none) | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | (none) | Langfuse secret key |
| `LANGFUSE_BASEURL` | `https://cloud.langfuse.com` | Langfuse API base URL |

### Running the Dashboard

The dashboard is a Streamlit application that calls the backend services directly.
The FastAPI server still provides the REST API on port 8100 for programmatic access.

```bash
# Install dashboard dependencies
pip install streamlit pandas fastapi uvicorn pydantic sqlmodel sqlalchemy

# Run via unified CLI (starts FastAPI API server)
python -m thon run
# API docs at http://localhost:8100/docs

# Run the Streamlit dashboard separately
streamlit run dashboard/streamlit_app.py --server.port 8501
# Dashboard at http://localhost:8501

# Run with auth enabled (FastAPI only — Streamlit uses services directly)
AUTH_ENABLED=true AUTH_SESSION_SECRET=my-secret \
AUTH_GITHUB_CLIENT_ID=xxx AUTH_GITHUB_CLIENT_SECRET=xxx \
python -m thon run

# Run with local password auth for Streamlit dashboard
AUTH_LOCAL_PASSWORD=mysecret streamlit run dashboard/streamlit_app.py --server.port 8501
```

### Future Roadmap

- **Luma invites** — invite codes for onboarding new users
- **WebSocket real-time updates** — live instance state changes pushed to dashboard
- **Instance templates** — pre-configured sandbox setups (image, extensions, env)
- **Usage analytics** — per-user resource usage, token consumption
- **Multi-server support** — manage sandboxes across multiple servers
- **Kubernetes native** — deploy dashboard as a Kubernetes resource
