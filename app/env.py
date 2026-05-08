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

"""Shared environment loading from .env files."""

from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def find_env_file(start: Optional[Path] = None) -> Optional[Path]:
    """Walk up from *start* to find a ``.env`` file in the project root.

    Returns ``None`` when no ``.env`` is found.
    """
    dir_path = start or Path.cwd()
    for parent in [dir_path, *dir_path.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_env(env_path: Optional[str | Path] = None) -> Optional[Path]:
    """Load a ``.env`` file into ``os.environ`` (does not overwrite existing).

    Resolution order:
      1. Explicit *env_path* argument
      2. ``THON_ENV_FILE`` environment variable
      3. Walk up from CWD to find ``.env``
      4. ``config/.env`` relative to project root

    Returns the resolved path, or ``None`` if no file was found.
    """
    import os

    if env_path:
        p = Path(env_path)
        if p.is_file():
            load_dotenv(p, override=False)
            return p
        return None

    explicit = os.getenv("THON_ENV_FILE")
    if explicit:
        p = Path(explicit)
        if p.is_file():
            load_dotenv(p, override=False)
            return p

    found = find_env_file()
    if found:
        load_dotenv(found, override=False)
        return found

    config_env = Path(__file__).resolve().parent.parent / "config" / ".env"
    if config_env.is_file():
        load_dotenv(config_env, override=False)
        return config_env

    return None
