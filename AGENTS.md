#THON Example AGENTS

Use this file for all work in `./`. Reference template: `examples/vscode/`.
This is a hackathon-focused multi-instanceTHON development tool with nginx
reverse proxy (SSL via mkcert/openssl), groups support, persistent workspace bind mounts,
and optional local LLM inference via Lemonade Server.

## Scope

- `./**` — all files in this directory
- Reference: `examples/vscode/main.py` — simple single-instance pattern

## Commands

```bash
# One-time prerequisite installation (python3, nginx, docker, mkcert, openssl)
bash ./scripts/setup.sh

# Lint
pip run ruff check .

# Format
pip run ruff format .

# Type check
pip run pyright

# Run: all groups from groups.yaml with nginx + SSL (default)
python ./scripts/main.py --groups groups.yaml --external-ip 165.245.138.159

# Run: single group
python ./scripts/main.py --groups groups.yaml --group alpha --external-ip 1.2.3.4

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

# Lemonade Server: full setup via shell (recommended — service manages its own lifecycle)
bash ./scripts/setup-lemonade.sh --groups groups.yaml --generate-keys --external-ip 1.2.3.4

# Lemonade Server: full setup without embedding model
bash ./scripts/setup-lemonade.sh --groups groups.yaml --generate-keys --external-ip 1.2.3.4 --no-embedding

# Lemonade Server: full setup via Python wrapper (alternative)
python ./lemonade_server.py run --groups groups.yaml --generate-keys --external-ip 1.2.3.4

# Lemonade Server: full setup with custom embedding model
python ./lemonade_server.py run --groups groups.yaml --generate-keys --external-ip 1.2.3.4 --embedding-model SuperPauly/harrier-oss-v1-0.6b-gguf:harrier-oss-v1-0.6B-BF16

# Lemonade Server: service management (it runs as systemd, no long-running process needed)
sudo systemctl status lemonade-server
sudo systemctl stop lemonade-server
sudo systemctl restart lemonade-server
sudo journalctl -u lemonade-server -f

# Lemonade Server: pull / configure via CLI
lemonade pull unsloth/gemma-4-31B-it-GGUF:Q8_K_XL
lemonade config set llamacpp.backend=auto host=0.0.0.0

# Run VS Code instances with Lemonade inference (injects kilo.jsonc into each sandbox)
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --lemonade kilo.jsonc

# AI Gateway: one-time install (APISIX, etcd, Redis)
INSTALL_GATEWAY=true bash ./scripts/setup.sh
# or: bash ./scripts/setup-apisix.sh

# AI Gateway: setup with per-consumer API keys and rate limiting
python ./scripts/apisix_gateway.py setup --groups groups.yaml --lemonade-url http://127.0.0.1:13305

# AI Gateway: setup with Redis-backed rate limiting
python ./scripts/apisix_gateway.py setup --groups groups.yaml --lemonade-url http://127.0.0.1:13305 --redis-host 127.0.0.1

# AI Gateway: create a single consumer
python ./scripts/apisix_gateway.py create-consumer --username alice --rate-limit 500

# AI Gateway: check status
python ./scripts/apisix_gateway.py status

# AI Gateway: cleanup all consumers and routes
python ./scripts/apisix_gateway.py cleanup

# Run VS Code instances with AI Gateway (per-user rate limiting)
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway --gateway-redis-host 127.0.0.1

# Run VS Code instances with AI Gateway (per-group shared API keys)
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --gateway --gateway-per-group
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
- **`UserInfo` dataclass**: group, username, workspace (`{group}/{username}`), label
- **`SandboxInstance` dataclass**: user, port, sandbox, endpoint, password (if secure)

### Key Classes
- **`NginxConfigGenerator`**: generates **per-port individual** nginx config files in
  `/etc/nginx/sites-available/`, symlinked to `/etc/nginx/sites-enabled/`, named
  `sandbox-thon-{port}`. Each config has its own server block.
  - `generate_port_config(port, cert_path, key_path, ca_cert_path)` — one file per port
  - `enable_config(config_path)` — symlink to sites-enabled
  - `cleanup_all()` — remove all `sandbox-thon-*` configs and reload
- **`SSLCertificateGenerator`**: generates SSL certs via **mkcert** (preferred, CA-trusted)
  with **openssl** fallback. Single shared cert for all instances. Filename includes hash
  of IP so changing `--external-ip` triggers regeneration.
  - `generate_server_cert(server_ip)` — returns (cert_path, key_path)
  - `get_mkcert_ca_root()` — returns mkcert CA root dir path (or None)

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

With `--workspace-dir /thon-workspace`, each user gets a host bind mount:
- Host path: `/thon-workspace/{group}/{username}`
- Container mount: `/workspace/{group}/{username}`
- Implemented via SDK `Volume(name="workspace", host=Host(path=host_path), mount_path=workspace_path)`
- Host directories are created with `os.makedirs()` before sandbox creation
- Without `--workspace-dir`, workspace is created inside the container via `mkdir -p` (ephemeral)

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

### Certificate Flow

1. **mkcert** (preferred): Generates CA-trusted certs. Filename includes IP hash.
   - CA root must be installed on client browsers for trust
   - CA cert served at `https://{ip}/ca.crt` for download
2. **openssl** (fallback): Self-signed certs with IP in SAN
3. Single shared cert for all instances on port 443
4. code-server always runs **HTTP** inside containers; nginx terminates SSL externally

### Nginx Template Features (per-port config)
- Individual server block per port, `server_name _;`
- `listen 80;` and `listen 443 ssl;`
- TLSv1.2 + TLSv1.3, `HIGH:!aNULL:!MD5` ciphers
- WebSocket upgrade headers (`Upgrade`, `Connection "upgrade"`)
- `X-Forwarded-For`, `X-Forwarded-Proto https`, `proxy_redirect off`
- `add_header Service-Worker-Allowed /;` (fixes SW scope errors)
- `proxy_read/send_timeout 86400` (24h for long-lived WS connections)
- `proxy_buffering off; proxy_request_buffering off;` (real-time data)
- Conditional `location = /ca.crt` block (only when mkcert CA root exists)

### URL Display
- HTTPS URL includes full endpoint path: `https://{ip}/{endpoint_path}/`
  where endpoint_path strips `127.0.0.1:` prefix from the endpoint string
- Example: endpoint `127.0.0.1:51111/proxy/8448` → URL `https://165.245.131.172/51111/proxy/8448/`

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
   Provides subcommands (`install`, `configure`, `start`, `stop`, `pull`, `run`, etc.)
   and programmatic access to the same operations. Useful for scripted automation.

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

Lemonade-managed args (reserved, must NOT be in `llamacpp_args`):
`--ctx-size`, `-c`, `-ngl`, `--gpu-layers`, `--n-gpu-layers`, `--jinja`, `--no-jinja`,
`--model`, `-m`, `--port`, `--embedding`, `--embeddings`, `--mmproj*`, `--rerank*`

Custom llama.cpp args (safe to override):
```
-b 8192 -ub 8192 -to 3600 -ctk q8_0 -ctv q8_0
--temp 1.0 --top-k 64 --top-p 0.95 --min-p 0.0
--repeat-penalty 1.0 --no-webui --threads-http -1 --threads -1
-np <num_users>
```

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

**Kilo Code Integration:**
1. `setup-lemonade.sh --groups groups.yaml --generate-keys` generates API keys and writes `kilo.jsonc`
2. `kilo.jsonc` contains: provider name (`lemonade`), base URL (auto-detected), API key, model ID (`user.gemma-4-31b-it`), `experimental` flags, and `indexing` config for semantic code search
3. Base URL resolution order: `--external-ip` > Docker bridge gateway > `localhost`
4. `main.py --lemonade kilo.jsonc` injects the config into each sandbox at `/workspace/.kilo/kilo.jsonc`
5. Kilo Code extension in the sandbox reads the config and connects to the Lemonade server
6. The `indexing` section configures semantic code search using the embedding model (`user.harrier-oss-v1-0.6b`)

**Full Workflow:**
```bash
# Terminal 1: Start Lemonade server with groups-based user count (generates kilo.jsonc)
python lemonade_server.py run --groups groups.yaml --generate-keys --external-ip 1.2.3.4

# Terminal 2: Start VS Code sandboxes with Lemonade inference
python ./scripts/main.py --groups groups.yaml --external-ip 1.2.3.4 --lemonade kilo.jsonc
```

### AI Gateway (APISIX Rate Limiting & Per-Consumer Keys)

An optional APISIX API Gateway provides token-based rate limiting and per-consumer API keys
for LLM endpoints. Supports two modes:

- **per-user** (default): Each user gets their own API key and rate limit
- **per-group**: Each group shares one API key with a combined rate limit
  (`rate_limit_per_user * num_users_in_group`)

Redis-backed rate limiting ensures consistency across multiple gateway instances.

**Components:**
- **APISIX** — API gateway with `ai-proxy-multi` (LLM load balancing), `ai-rate-limiting`
  (token-based rate limiting), and `key-auth` (per-consumer API keys) plugins
- **etcd** — APISIX configuration store
- **Redis** — Optional shared rate limit counter store (local policy used if not configured)

**Installation:**
```bash
# Option 1: During initial setup
INSTALL_GATEWAY=true bash ./scripts/setup.sh

# Option 2: Standalone install script
bash ./scripts/setup-apisix.sh
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
4. `opencode-plugin-langfuse` npm package is installed globally in the container
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
- Generate SSL certs on the **host** via mkcert/openssl, never inside containers
- Clean up nginx configs + kill sandboxes in `finally` blocks
- Include Apache 2.0 header on every new file
- Use `--external-ip` when accessing via IP address (prevents SW SSL errors)
- Auto-detect network mode from endpoint format, NOT from a CLI flag
- Use `pip install` (not `uv`) — user's intentional choice
- Use image `waterpistol/thon:latest` for Docker builds

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
  and import the CA root from `https://{ip}/ca.crt`

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

**Environment Variables**:
- `SANDBOX_DOMAIN` — server address (default: `localhost:8080`)
- `SANDBOX_API_KEY` — optional API key
- `SANDBOX_IMAGE` — Docker image (default: `waterpistol/thon:latest`)
- `PYTHON_VERSION` — Python version in sandbox (default: `3.11`)
- `LEMONADE_API_KEY` — Lemonade server API key for regular endpoints
- `LEMONADE_ADMIN_API_KEY` — Lemonade server admin key (elevated access)
- `LANGFUSE_PUBLIC_KEY` — Langfuse public key for LLM observability
- `LANGFUSE_SECRET_KEY` — Langfuse secret key for LLM observability
- `LANGFUSE_BASEURL` — Langfuse API base URL (default: `https://cloud.langfuse.com`)

## File Map

### Legacy CLI (`main.py`, `scripts/`)

| File | Purpose |
|------|---------|
| `main.py` | Entry point; argparse CLI; groups loading; instance orchestration; persistent workspaces; Lemonade kilo.jsonc injection |
| `scripts/setup.sh` | One-time install: python3, nginx, docker.io, mkcert, openssl |
| `scripts/nginx_config.py` | `NginxConfigGenerator`; per-port individual configs in sites-available |
| `scripts/ssl_cert.py` | `SSLCertificateGenerator`; mkcert primary with openssl fallback |
| `scripts/generate-certs.py` | Legacy mkcert helper (preserved for local dev) |
| `scripts/lemonade_server.py` | `LemonadeServerManager`; Python wrapper for install, configure, start/stop, pull/load models, generate kilo.jsonc |
| `scripts/setup-lemonade.sh` | All-in-one shell script: install, configure, generate API keys, pull model, generate kilo.jsonc (recommended) |
| `scripts/build.sh` | Build helper script |
| `scripts/build-amd-mi300x-llama-server.sh` | Build llama.cpp from source for AMD MI300X (gfx942) with ROCm |
| `scripts/prerequisite-script.sh` | Prerequisite installation |
| `config/groups.yaml.example` | Groups and users configuration template |
| `config/kilo.jsonc.example` | Kilo Code config template for Lemonade OpenAI-compatible provider |
| `config/vscode-settings.jsonc.example` | VS Code settings template injected into each sandbox's code-server |
| `config/extensions.txt.example` | VS Code extensions list for Docker image |
| `reference/kilo.config.schema.json` | Kilo config JSON schema |
| `reference/template.portnumber.available.md` | Nginx template reference |
| `Dockerfile` | Sandbox image: python:3.12-slim + code-server + non-root vscode user |

### Dashboard Application (`app/`)

| File | Purpose |
|------|---------|
| `app/__init__.py` | Package init |
| `app/main.py` | FastAPI application entry point; lifespan; static file serving; route mounting |
| `app/config.py` | `AppConfig` and sub-configs; loaded from env vars (`SANDBOX_*`, `LEMONADE_*`, `DASHBOARD_*`, `AUTH_*`) |
| `app/models.py` | Pydantic domain models: `InstanceInfo`, `InstanceState`, `UserInfo`, `LemonadeStatus`, `GroupConfig` |
| `app/exceptions.py` | Custom exceptions: `VSCRemoteError`, `SandboxCreateError`, `LemonadeConnectionError`, `AuthError`, etc. |
| `app/services/sandbox_service.py` | `SandboxService` — wraps sandbox SDK `SandboxManager` for fleet CRUD (list, create, pause, resume, kill, renew) |
| `app/services/lemonade_service.py` | `LemonadeService` — Lemonade server status monitoring, model listing, API info |
| `app/api/routes/instances.py` | REST API: `GET/POST /api/instances`, `POST pause/resume`, `DELETE`, `POST bulk/*` |
| `app/api/routes/lemonade.py` | REST API: `GET /api/lemonade/status`, `/models`, `/api-info` |
| `app/api/routes/auth.py` | REST API: `GET /api/auth/providers`, `/login/{provider}`, `/callback/{provider}`, `/logout`, `/me` |
| `app/auth/providers.py` | OIDC/OAuth2 provider implementations: `GitHubProvider`, `GitLabProvider`, `LinkedInProvider`; PKCE support |
| `app/auth/sessions.py` | `SessionStore` — in-memory session management with HMAC-signed tokens |
| `app/auth/deps.py` | FastAPI dependencies: `get_current_user`, `optional_user` |

### Dashboard Frontend (`dashboard/`)

| File | Purpose |
|------|---------|
| `dashboard/streamlit_app.py` | Streamlit dashboard: instance CRUD, groups management, lemonade status, settings |
| `dashboard/streamlit_styles.py` | Dark theme CSS injection for Streamlit (matches original JS dashboard theme) |
| `dashboard/index.html` | Legacy single-page HTML shell (superseded by Streamlit) |
| `dashboard/static/style.css` | Legacy dark theme CSS (superseded by Streamlit) |
| `dashboard/static/app.js` | Legacy frontend JS (superseded by Streamlit) |

## Dashboard Architecture

### Backend (FastAPI)

```
app/main.py          → FastAPI app, lifespan, redirects / to /docs
app/api/routes/      → REST API route handlers
app/services/        → Business logic layer (wraps sandbox SDK + Lemonade)
app/auth/            → OIDC providers, session store, FastAPI deps
app/config.py        → Environment-driven configuration
app/models.py        → Pydantic domain models
```

**Key design decisions:**
- `SandboxService` wraps `opensandbox.SandboxManager` for fleet ops and `opensandbox.Sandbox` for single-instance ops
- `LemonadeService` is read-only (HTTP API calls, no systemd privilege needed)
- Auth is optional — when `AUTH_ENABLED` is false, all endpoints are open
- Session tokens are HMAC-signed; replace with Redis/DB for production
- FastAPI no longer serves the dashboard UI — it only provides the REST API
- `/` redirects to `/docs` (Swagger UI) since the dashboard is served by Streamlit

### Frontend (Streamlit)

```
dashboard/streamlit_app.py     → Main Streamlit app with sidebar nav and 4 pages
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
| Instances | List, search/filter by state, create, pause/resume/kill, bulk actions, detail expanders |
| Groups | List, search, create/rename/delete groups, add/remove/rename users |
| Lemonade Server | Status, API info, health, performance stats, slots, system info, available models |
| Settings | External IP configuration (persisted to SQLite) |

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
| `GET` | `/api/lemonade/status` | Lemonade server status |
| `GET` | `/api/lemonade/models` | Available models |
| `GET` | `/api/lemonade/api-info` | API endpoint info |
| `GET` | `/api/lemonade/health` | Proxy: server health, loaded models, max_models |
| `GET` | `/api/lemonade/stats` | Proxy: performance statistics from last request |
| `GET` | `/api/lemonade/system-info` | Proxy: hardware details and device enumeration |
| `GET` | `/api/lemonade/live` | Proxy: lightweight liveness probe |
| `GET` | `/api/lemonade/slots` | Proxy: llama.cpp slots processing state |
| `POST` | `/api/lemonade/slots/{id}/save` | Proxy: save slot prompt cache |
| `POST` | `/api/lemonade/slots/{id}/restore` | Proxy: restore slot prompt cache |
| `POST` | `/api/lemonade/slots/{id}/erase` | Proxy: erase slot prompt cache |
| `POST` | `/api/lemonade/pull` | Proxy: install or register-and-install a model |
| `GET` | `/api/lemonade/pull/variants` | Proxy: enumerate GGUF variants for a checkpoint |
| `POST` | `/api/lemonade/delete` | Proxy: delete a model |
| `POST` | `/api/lemonade/load` | Proxy: load a model into memory |
| `POST` | `/api/lemonade/unload` | Proxy: unload a model from memory |
| `POST` | `/api/lemonade/install` | Proxy: install or update a backend |
| `POST` | `/api/lemonade/uninstall` | Proxy: remove a backend |
| `GET` | `/api/auth/providers` | List auth providers |
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
| `AUTH_ENABLED` | `false` | Enable OIDC authentication |
| `AUTH_SESSION_SECRET` | (none) | HMAC secret for session tokens |
| `AUTH_GITHUB_CLIENT_ID` | (none) | GitHub OAuth app client ID |
| `AUTH_GITHUB_CLIENT_SECRET` | (none) | GitHub OAuth app client secret |
| `AUTH_GITLAB_CLIENT_ID` | (none) | GitLab OAuth app client ID |
| `AUTH_GITLAB_CLIENT_SECRET` | (none) | GitLab OAuth app client secret |
| `AUTH_LINKEDIN_CLIENT_ID` | (none) | LinkedIn OIDC client ID |
| `AUTH_LINKEDIN_CLIENT_SECRET` | (none) | LinkedIn OIDC client secret |
| `AUTH_LOCAL_PASSWORD` | (none) | Single-password auth for Streamlit dashboard; unset = no auth |

### Running the Dashboard

The dashboard is a Streamlit application that calls the backend services directly.
The FastAPI server still provides the REST API on port 8100 for programmatic access.

```bash
# Install dashboard dependencies
pip install streamlit pandas fastapi uvicorn pydantic

# Run the Streamlit dashboard
streamlit run dashboard/streamlit_app.py --server.port 8501

# Dashboard available at http://localhost:8501

# Run the REST API server separately (optional, for API access)
python -m app.main
# API docs at http://localhost:8100/docs

# Run with auth enabled (FastAPI only — Streamlit uses services directly)
AUTH_ENABLED=true AUTH_SESSION_SECRET=my-secret \
AUTH_GITHUB_CLIENT_ID=xxx AUTH_GITHUB_CLIENT_SECRET=xxx \
python -m app.main

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
