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

"""Custom exceptions for THON."""


class VSCRemoteError(Exception):
    """Base exception for all thon errors."""


class ConfigError(VSCRemoteError):
    """Configuration is missing or invalid."""


class SandboxCreateError(VSCRemoteError):
    """Failed to create a sandbox instance."""


class SandboxNotFoundError(VSCRemoteError):
    """Requested sandbox instance does not exist."""


class SandboxOperationError(VSCRemoteError):
    """Failed to perform an operation on a sandbox (pause/resume/kill)."""


class LemonadeNotInstalledError(VSCRemoteError):
    """Lemonade server is not installed on this system."""


class LemonadeConnectionError(VSCRemoteError):
    """Cannot connect to the Lemonade server."""


class GroupsLoadError(VSCRemoteError):
    """Failed to load or parse groups.yaml."""


class AuthError(VSCRemoteError):
    """Authentication or authorization failure."""


class GatewayNotEnabledError(VSCRemoteError):
    """AI Gateway feature is not enabled."""


class GatewayConnectionError(VSCRemoteError):
    """Cannot connect to the APISIX Admin API."""


class GatewayAuthError(VSCRemoteError):
    """APISIX Admin API authentication failed (wrong API key)."""


class GatewayConfigError(VSCRemoteError):
    """Gateway configuration is invalid or incomplete."""
