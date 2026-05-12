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

"""REST API routes for managing configuration file contents stored in the database."""

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.db import CONFIG_FILE_KEYS, delete_setting, get_setting, set_setting

router = APIRouter(prefix="/api/config-files", tags=["config-files"])

CONFIG_LABELS = {
    "config_groups_yaml": "Groups YAML",
    "config_kilo_json": "Kilo Code Config (kilo.jsonc)",
    "config_vscode_settings": "VS Code Settings",
}


class ConfigFileContent(BaseModel):
    key: str
    content: str
    label: str


class ConfigFileListEntry(BaseModel):
    key: str
    label: str
    has_content: bool


class ConfigFileUpdateRequest(BaseModel):
    content: str


@router.get("", response_model=list[ConfigFileListEntry])
async def list_config_files() -> list[ConfigFileListEntry]:
    """List all configurable file slots with their current state."""
    entries = []
    for key in CONFIG_FILE_KEYS:
        val = get_setting(key)
        entries.append(
            ConfigFileListEntry(
                key=key,
                label=CONFIG_LABELS.get(key, key),
                has_content=val is not None and val.strip() != "",
            )
        )
    return entries


@router.get("/{key}", response_model=ConfigFileContent)
async def get_config_file(key: str) -> ConfigFileContent:
    """Get the content of a stored config file."""
    if key not in CONFIG_FILE_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}")
    content = get_setting(key) or ""
    return ConfigFileContent(
        key=key, content=content, label=CONFIG_LABELS.get(key, key)
    )


@router.put("/{key}", response_model=ConfigFileContent)
async def update_config_file(key: str, req: ConfigFileUpdateRequest) -> ConfigFileContent:
    """Store config file content by key."""
    if key not in CONFIG_FILE_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}")
    set_setting(key, req.content)
    return ConfigFileContent(
        key=key, content=req.content, label=CONFIG_LABELS.get(key, key)
    )


@router.post("/{key}/upload", response_model=ConfigFileContent)
async def upload_config_file(key: str, file: UploadFile = File(...)) -> ConfigFileContent:
    """Upload a config file by key."""
    if key not in CONFIG_FILE_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}")
    content = (await file.read()).decode("utf-8", errors="replace")
    set_setting(key, content)
    return ConfigFileContent(
        key=key, content=content, label=CONFIG_LABELS.get(key, key)
    )


@router.delete("/{key}")
async def delete_config_file(key: str) -> dict:
    """Remove a stored config file."""
    if key not in CONFIG_FILE_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown config key: {key}")
    deleted = delete_setting(key)
    return {"status": "deleted" if deleted else "not_found", "key": key}
