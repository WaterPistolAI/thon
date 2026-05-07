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

# THON - The Hackathon Organizer Node Sandbox Image
# This Dockerfile builds a sandbox image with code-server pre-installed
# for multi-instance VS Code remote hackathon environments.
#
# HTTPS Support:
#   - By default, code-server runs over HTTP
#   - For HTTPS, mount certificates and use: code-server --cert /certs/server.pem --cert-key /certs/server-key.pem
#   - mkcert certificates can be generated on host and mounted into container

# Use the official Ubuntu 24.04 LTS base image
FROM ubuntu:24.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1



# Install dependencies
RUN apt update && apt install -y --no-install-recommends \
    curl \
    wget \
    git \
    openssh-client \
    gnupg \
    lsb-release \
    openssl \
    ca-certificates \
    vim \
    nano \
    sudo \
    python3-full \
    python3-m2crypto \
    python3-gunicorn \
    python3-djoser \
    python3-jwt \
    python3-dev \
    python3-venv\
    python3-pip \
    python-is-python3 \
    python3-pyro5 \
    nodejs \
    npm \
    default-jre \
    && rm -rf /var/lib/apt/lists/*

# Dotnet
RUN wget https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb -O packages-microsoft-prod.deb
RUN dpkg -i packages-microsoft-prod.deb
RUN apt update

RUN npm install -g pnpm npx
# Install code-server
RUN curl -fsSL https://code-server.dev/install.sh | sh \
    && code-server --version

# Create non-root user for security
RUN useradd -m -s /bin/bash vscode \
    && mkdir -p /workspace \
    && mkdir -p /certs \
    && chown -R vscode:vscode /workspace \
    && chown -R vscode:vscode /certs

# Set working directory
WORKDIR /workspace

# Switch to non-root user before installing extensions
# so they land in /home/vscode/.local/share/code-server/extensions/
USER vscode

# Install VS Code extensions from extensions.txt
COPY --chown=vscode:vscode config/extensions.txt.example /tmp/extensions.txt
RUN while IFS= read -r ext; do \
      ext="$(echo "$ext" | tr -d '\r')"; \
      [ -z "$ext" ] && continue; \
    code-server --install-extension "$ext" --force || echo "WARNING: Failed to install $ext"; \
    done < /tmp/extensions.txt \
    && rm /tmp/extensions.txt

# Default command (HTTP mode by default)
# For HTTPS mode, mount certificates and run:
#   code-server --cert /certs/server.pem --cert-key /certs/server-key.pem --bind-addr 0.0.0.0:44772 /workspace
CMD ["code-server", "--bind-addr", "0.0.0.0:8443", "--auth", "none", "--disable-telemetry", "/workspace"]