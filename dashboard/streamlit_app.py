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

"""Streamlit dashboard for THON — replaces the vanilla JS frontend."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import AppConfig
from app.db import GroupRecordWithUsers, UserRecord, get_setting, set_setting
from app.exceptions import (
    GatewayAuthError,
    GatewayConnectionError,
    GatewayNotEnabledError,
    LemonadeConnectionError,
)
from app.models import GatewayMode, InstanceState, UserInfo
from app.services.apisix_service import ApisixService
from app.services.groups_service import DuplicateError, GroupsService
from app.services.lemonade_service import LemonadeService
from app.services.sandbox_service import SandboxService

from dashboard.streamlit_styles import inject_custom_styles


class _AsyncRunner:
    _lock = threading.Lock()
    _loop: Optional[asyncio.AbstractEventLoop] = None
    _thread: Optional[threading.Thread] = None

    @classmethod
    def _ensure_loop(cls) -> asyncio.AbstractEventLoop:
        with cls._lock:
            loop = getattr(st.session_state, "_async_loop", None)
            if loop is not None and loop.is_running():
                cls._loop = loop
            if cls._loop is None or not cls._loop.is_running():
                cls._loop = asyncio.new_event_loop()
                cls._thread = threading.Thread(
                    target=cls._loop.run_forever, daemon=True
                )
                cls._thread.start()
                st.session_state._async_loop = cls._loop
                _invalidate_async_services()
            return cls._loop

    @classmethod
    def run(cls, coro):
        loop = cls._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()


def _invalidate_async_services() -> None:
    for key in ("sandbox_service", "lemonade_service", "apisix_service"):
        st.session_state.pop(key, None)


def _run_async(coro):
    return _AsyncRunner.run(coro)


def _get_config() -> AppConfig:
    if "app_config" not in st.session_state:
        st.session_state.app_config = AppConfig.from_env()
    return st.session_state.app_config


async def _init_sandbox_service(cfg: AppConfig) -> SandboxService:
    svc = SandboxService(cfg)
    await svc._get_manager()
    return svc


def _get_sandbox_service() -> SandboxService:
    if "sandbox_service" not in st.session_state:
        st.session_state.sandbox_service = _run_async(
            _init_sandbox_service(_get_config())
        )
    return st.session_state.sandbox_service


def _get_lemonade_service() -> LemonadeService:
    if "lemonade_service" not in st.session_state:
        st.session_state.lemonade_service = LemonadeService(_get_config().lemonade)
    return st.session_state.lemonade_service


def _get_groups_service() -> GroupsService:
    if "groups_service" not in st.session_state:
        cfg = _get_config()
        st.session_state.groups_service = GroupsService(
            db_path=cfg.database.path,
            workspace_dir=cfg.workspace_dir,
        )
    return st.session_state.groups_service


def _get_apisix_service() -> ApisixService:
    if "apisix_service" not in st.session_state:
        cfg = _get_config()
        st.session_state.apisix_service = ApisixService(cfg.gateway)
    return st.session_state.apisix_service


def _state_badge(state: str) -> str:
    colors = {
        "running": "🟢",
        "paused": "🟡",
        "pending": "🔵",
        "terminated": "⚫",
        "failed": "🔴",
        "pausing": "🟡",
        "stopping": "🟠",
    }
    icon = colors.get(state.lower(), "⚪")
    return f"{icon} {state}"


def _trunc_id(id_str: Optional[str], length: int = 12) -> str:
    if not id_str:
        return "-"
    return id_str[:length] + "..." if len(id_str) > length else id_str


def _dialog_container(title: str):
    return st.container(border=True)


def page_instances() -> None:
    st.header("Instances")

    svc = _get_sandbox_service()

    with st.spinner("Loading instances..."):
        try:
            instances, total = _run_async(svc.list_instances())
        except Exception as e:
            st.error(f"Failed to load instances: {e}")
            return

    if not instances:
        st.info("No instances found.")
        if st.button("+ New Instance", type="primary"):
            st.session_state.show_create_instance = True
        _create_instance_dialog()
        return

    running = sum(1 for i in instances if i.state == InstanceState.RUNNING)
    paused = sum(1 for i in instances if i.state == InstanceState.PAUSED)

    c1, c2, c3 = st.columns(3)
    c1.metric("Running", running)
    c2.metric("Paused", paused)
    c3.metric("Total", total)

    st.divider()

    col_search, col_filter = st.columns([3, 1])
    with col_search:
        search = st.text_input(
            "Search", placeholder="Search instances...", label_visibility="collapsed"
        )
    with col_filter:
        state_filter = st.selectbox(
            "State",
            options=["All"] + [s.value for s in InstanceState],
            label_visibility="collapsed",
        )

    filtered = instances
    if search:
        s = search.lower()
        filtered = [
            i
            for i in filtered
            if s in (i.user.group + "/" + i.user.username).lower()
            or s in (i.id or "").lower()
        ]
    if state_filter != "All":
        filtered = [i for i in filtered if i.state.value == state_filter]

    if st.button("🔄 Refresh"):
        st.rerun()

    if st.button("+ New Instance", type="primary"):
        st.session_state.show_create_instance = True

    _create_instance_dialog()

    if not filtered:
        st.info("No instances match the filter.")
        return

    rows = []
    for inst in filtered:
        label = f"{inst.user.group}/{inst.user.username}"
        endpoint = inst.public_url or inst.endpoint or "-"
        rows.append(
            {
                "User": label,
                "Instance ID": _trunc_id(inst.id),
                "Full ID": inst.id or "",
                "State": inst.state.value,
                "Endpoint": endpoint,
                "Password": inst.password or "",
            }
        )

    df = pd.DataFrame(rows)

    event = st.dataframe(
        df[["User", "Instance ID", "State", "Endpoint"]],
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
    )

    selected_rows = event["selection"].get("rows", [])  # type: ignore[index]
    selected_ids = (
        [df.iloc[r]["Full ID"] for r in selected_rows] if selected_rows else []
    )

    if selected_ids:
        st.warning(f"{len(selected_ids)} instance(s) selected")
        bc1, bc2, bc3 = st.columns(3)
        with bc1:
            if st.button("⏸ Pause Selected"):
                _bulk_action(svc, "pause", selected_ids)
        with bc2:
            if st.button("▶ Resume Selected"):
                _bulk_action(svc, "resume", selected_ids)
        with bc3:
            if st.button("💀 Kill Selected"):
                _bulk_action(svc, "kill", selected_ids)

    st.divider()

    for inst in filtered:
        label = f"{inst.user.group}/{inst.user.username}"
        with st.expander(
            f"{_state_badge(inst.state.value)} {label} — {_trunc_id(inst.id)}"
        ):
            _instance_detail(svc, inst)


def _create_instance_dialog() -> None:
    if not st.session_state.get("show_create_instance"):
        return

    with _dialog_container("Create Instance"):
        st.subheader("Create Instance")
        group = st.text_input("Group", value="default")
        username = st.text_input("Username", value="workspace")
        port = st.number_input("Port", min_value=1024, max_value=65535, value=8443)
        secure = st.checkbox("Enable password authentication")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Create", type="primary"):
                svc = _get_sandbox_service()
                user = UserInfo(group=group, username=username)
                try:
                    _run_async(
                        svc.create_instance(user=user, port=int(port), secure=secure)
                    )
                    st.success(f"Instance created: {group}/{username}")
                    st.session_state.show_create_instance = False
                    st.rerun()
                except Exception as e:
                    st.error(f"Create failed: {e}")
        with c2:
            if st.button("Cancel"):
                st.session_state.show_create_instance = False
                st.rerun()


def _instance_detail(svc: SandboxService, inst) -> None:
    st.write(f"**ID:** `{inst.id}`")
    st.write(f"**State:** {_state_badge(inst.state.value)}")
    st.write(f"**Port:** {inst.port}")
    if inst.public_url:
        st.write(f"**URL:** [{inst.public_url}]({inst.public_url})")
    elif inst.endpoint:
        st.write(f"**Endpoint:** `{inst.endpoint}`")
    if inst.password:
        st.write(f"**Password:** `{inst.password}`")
    if inst.image:
        st.write(f"**Image:** `{inst.image}`")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if inst.state == InstanceState.RUNNING:
            if st.button("⏸ Pause", key=f"pause-{inst.id}"):
                _instance_action(svc, "pause", inst.id)
    with c2:
        if inst.state == InstanceState.PAUSED:
            if st.button("▶ Resume", key=f"resume-{inst.id}"):
                _instance_action(svc, "resume", inst.id)
    with c3:
        if inst.state in (InstanceState.TERMINATED, InstanceState.FAILED):
            if st.button("🔄 Restart", key=f"recreate-{inst.id}"):
                _instance_action(svc, "recreate", inst.id)
    with c4:
        if st.button("💀 Kill", key=f"kill-{inst.id}"):
            _instance_action(svc, "kill", inst.id)


def _instance_action(svc: SandboxService, action: str, instance_id: str) -> None:
    try:
        if action == "kill":
            _run_async(svc.kill_instance(instance_id))
            st.toast("Instance terminated", icon="💀")
        elif action == "recreate":
            _run_async(svc.recreate_instance(instance_id))
            st.toast("Instance recreated", icon="🔄")
        elif action == "pause":
            _run_async(svc.pause_instance(instance_id))
            st.toast("Instance paused", icon="⏸")
        elif action == "resume":
            _run_async(svc.resume_instance(instance_id))
            st.toast("Instance resumed", icon="▶")
        st.rerun()
    except Exception as e:
        st.error(f"Action failed: {e}")


def _bulk_action(svc: SandboxService, action: str, instance_ids: list[str]) -> None:
    results = {"ok": 0, "fail": 0}
    for sid in instance_ids:
        try:
            if action == "pause":
                _run_async(svc.pause_instance(sid))
            elif action == "resume":
                _run_async(svc.resume_instance(sid))
            elif action == "kill":
                _run_async(svc.kill_instance(sid))
            results["ok"] += 1
        except Exception:
            results["fail"] += 1
    msg = f"{action.capitalize()}d {results['ok']} instance(s)"
    if results["fail"]:
        msg += f", {results['fail']} failed"
    st.toast(msg)
    st.rerun()


def page_groups() -> None:
    st.header("Groups")

    svc = _get_groups_service()

    try:
        groups = svc.list_groups()
    except Exception as e:
        st.error(f"Failed to load groups: {e}")
        return

    events = svc.list_events()
    if events:
        for ev in events:
            ev_title = ev.title or ev.event_id
            st.caption(f"Event: **{ev_title}** (`{ev.event_id}`)")

    total_users = sum(len(g.users) for g in groups)
    c1, c2 = st.columns(2)
    c1.metric("Groups", len(groups))
    c2.metric("Total Users", total_users)

    st.divider()

    col_search, col_create = st.columns([4, 1])
    with col_search:
        search = st.text_input(
            "Search", placeholder="Search groups...", label_visibility="collapsed"
        )
    with col_create:
        if st.button("+ New Group", type="primary"):
            st.session_state.show_create_group = True

    _create_group_dialog()

    if search:
        s = search.lower()
        groups = [
            g
            for g in groups
            if s in g.name.lower() or any(s in u.username.lower() for u in g.users)
        ]

    if not groups:
        st.info("No groups configured.")
        return

    group_id_map = {g.id: g for g in groups}

    for group in groups:
        display_name = group.title or group.name
        with st.expander(
            f"📁 {display_name} ({len(group.users)} user(s)) — `{_trunc_id(group.id, 8)}`"
        ):
            st.write(f"**ID:** `{group.id}`")
            if group.title and group.title != group.name:
                st.write(f"**Title:** {group.title}")
            if group.event_id:
                st.write(f"**Event:** `{group.event_id}`")
            st.write(f"**Created:** {group.created_at}")

            if group.users:
                user_rows = []
                for u in group.users:
                    user_rows.append(
                        {
                            "UUID": _trunc_id(u.id, 8),
                            "Username": u.username,
                            "Workspace Path": u.workspace_path or "-",
                            "Full ID": u.id,
                        }
                    )
                df = pd.DataFrame(user_rows)
                st.dataframe(
                    df[["UUID", "Username", "Workspace Path"]],
                    hide_index=True,
                    width="stretch",
                )

                st.markdown("**Start Instances**")
                su_cols = st.columns(min(len(group.users), 4))
                for idx, u in enumerate(group.users):
                    with su_cols[idx % len(su_cols)]:
                        if st.button(
                            f"▶ {u.username}",
                            key=f"start-user-{u.id}",
                            help=f"Start sandbox for {u.username} with PVC workspace",
                        ):
                            _start_user_instance(u, group)
            else:
                st.info("No users in this group.")

            bc1, bc2, bc3, bc4, bc5 = st.columns(5)
            with bc1:
                if st.button("+ User", key=f"add-user-{group.id}"):
                    st.session_state.add_user_group_id = group.id
                    st.session_state.show_add_user = True
            with bc2:
                if st.button("▶ Start All", key=f"start-group-{group.id}"):
                    _start_group_instances(group)
            with bc3:
                if st.button("✏️ Rename", key=f"rename-group-{group.id}"):
                    st.session_state.rename_group_id = group.id
                    st.session_state.rename_group_name = group.name
                    st.session_state.show_rename_group = True
            with bc4:
                if st.button("🔄 Transfer", key=f"transfer-group-{group.id}"):
                    st.session_state.transfer_source_group_id = group.id
                    st.session_state.show_transfer_user = True
            with bc5:
                if st.button("🗑 Delete", key=f"delete-group-{group.id}"):
                    try:
                        svc.delete_group(group.id)
                        st.toast(f"Group '{group.name}' deleted")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to delete group: {e}")

    _add_user_dialog(svc)
    _rename_group_dialog(svc)
    _transfer_user_dialog(svc, group_id_map)


def _check_existing_instance(sandbox_svc: SandboxService, user: UserInfo) -> bool:
    """Return True if user already has a running or paused instance."""
    try:
        instances, _ = _run_async(
            sandbox_svc.list_instances(
                metadata_filter={"group": user.group, "username": user.username}
            )
        )
        return any(
            i.state in (InstanceState.RUNNING, InstanceState.PAUSED) for i in instances
        )
    except Exception:
        return False


def _start_user_instance(
    user_record: UserRecord, group_record: GroupRecordWithUsers
) -> None:
    """Start a sandbox instance for a single DB user with PVC workspace volume."""
    sandbox_svc = _get_sandbox_service()
    cfg = _get_config()
    user = UserInfo(group=group_record.name, username=user_record.username)
    if _check_existing_instance(sandbox_svc, user):
        st.warning(f"User {user.label} already has a running instance")
        return
    workspace_volume = None
    if user_record.workspace_path and user_record.workspace_path.startswith("thon-"):
        workspace_volume = user_record.workspace_path
    try:
        _run_async(
            sandbox_svc.create_instance(
                user=user,
                workspace_volume=workspace_volume,
                workspace_dir=cfg.workspace_dir if not workspace_volume else None,
            )
        )
        st.toast(f"Instance started: {user.label}")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to start instance for {user.label}: {e}")


def _start_group_instances(group_record: GroupRecordWithUsers) -> None:
    """Start sandbox instances for all users in a group with PVC workspace volumes."""
    sandbox_svc = _get_sandbox_service()
    cfg = _get_config()
    users = []
    user_volumes: dict[str, str] = {}
    for u in group_record.users:
        user = UserInfo(group=group_record.name, username=u.username)
        users.append(user)
        if u.workspace_path and u.workspace_path.startswith("thon-"):
            user_volumes[user.label] = u.workspace_path
    if not users:
        st.warning("No users in this group.")
        return
    existing = [u for u in users if _check_existing_instance(sandbox_svc, u)]
    if existing:
        labels = ", ".join(u.label for u in existing)
        st.warning(f"Users already have running instances: {labels}")
        return
    try:
        results = _run_async(
            sandbox_svc.create_instances_for_group(
                users=users,
                workspace_dir=cfg.workspace_dir,
                user_volumes=user_volumes if user_volumes else None,
            )
        )
        st.toast(f"Started {len(results)} instance(s) for group '{group_record.name}'")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to start instances for group '{group_record.name}': {e}")


def _create_group_dialog() -> None:
    if not st.session_state.get("show_create_group"):
        return
    with _dialog_container("Create Group"):
        st.subheader("Create Group")
        name = st.text_input("Group Name", placeholder="e.g. alpha")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Create", type="primary"):
                if not name.strip():
                    st.error("Group name is required")
                    return
                svc = _get_groups_service()
                try:
                    svc.create_group(name.strip())
                    st.session_state.show_create_group = False
                    st.toast("Group created")
                    st.rerun()
                except DuplicateError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Failed to create group: {e}")
        with c2:
            if st.button("Cancel"):
                st.session_state.show_create_group = False
                st.rerun()


def _add_user_dialog(svc: GroupsService) -> None:
    if not st.session_state.get("show_add_user"):
        return
    with _dialog_container("Add User"):
        st.subheader("Add User")
        group_id: str = str(st.session_state.get("add_user_group_id", ""))
        username = st.text_input("Username", placeholder="e.g. alice")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Add", type="primary"):
                if not username.strip():
                    st.error("Username is required")
                    return
                try:
                    svc.create_user(group_id, username.strip())
                    st.session_state.show_add_user = False
                    st.toast("User added")
                    st.rerun()
                except DuplicateError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Failed to add user: {e}")
        with c2:
            if st.button("Cancel"):
                st.session_state.show_add_user = False
                st.rerun()


def _rename_group_dialog(svc: GroupsService) -> None:
    if not st.session_state.get("show_rename_group"):
        return
    with _dialog_container("Rename Group"):
        st.subheader("Rename Group")
        group_id: str = str(st.session_state.get("rename_group_id", ""))
        current: str = str(st.session_state.get("rename_group_name", ""))
        name = st.text_input("Group Name", value=current)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Save", type="primary"):
                if not name.strip():
                    st.error("Group name is required")
                    return
                try:
                    svc.update_group(group_id, name.strip())
                    st.session_state.show_rename_group = False
                    st.toast("Group renamed")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to rename group: {e}")
        with c2:
            if st.button("Cancel"):
                st.session_state.show_rename_group = False
                st.rerun()


def _transfer_user_dialog(svc: GroupsService, group_id_map: dict) -> None:
    if not st.session_state.get("show_transfer_user"):
        return
    source_group_id: str = str(st.session_state.get("transfer_source_group_id", ""))
    source_group = group_id_map.get(source_group_id)
    if not source_group or not source_group.users:
        st.session_state.show_transfer_user = False
        return
    with _dialog_container("Transfer User"):
        st.subheader("Transfer User to Another Group")
        user_options = {
            f"{u.username} ({_trunc_id(u.id, 8)})": u for u in source_group.users
        }
        selected_label = st.selectbox("User", options=list(user_options.keys()))
        selected_user = user_options.get(selected_label)
        other_groups = {
            g.id: g.name for g in group_id_map.values() if g.id != source_group_id
        }
        if not other_groups:
            st.warning("No other groups to transfer to. Create a new group first.")
        target_group_id = st.selectbox(
            "Target Group",
            options=list(other_groups.keys()),
            format_func=lambda gid: other_groups[gid],
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Transfer", type="primary"):
                if selected_user and target_group_id:
                    try:
                        svc.transfer_user(selected_user.id, target_group_id)
                        st.session_state.show_transfer_user = False
                        st.toast(
                            f"Transferred {selected_user.username} to {other_groups[target_group_id]}"
                        )
                        st.rerun()
                    except DuplicateError as e:
                        st.error(str(e))
                    except Exception as e:
                        st.error(f"Transfer failed: {e}")
        with c2:
            if st.button("Cancel"):
                st.session_state.show_transfer_user = False
                st.rerun()


def page_lemonade() -> None:
    st.header("Lemonade Server")

    svc = _get_lemonade_service()

    if st.button("🔄 Refresh"):
        st.rerun()

    try:
        status = svc.get_status()
    except Exception as e:
        st.error(f"Failed to load Lemonade status: {e}")
        return

    status_text = "🟢 Online" if status.running else "🔴 Offline"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", status_text)
    c2.metric("Model", status.model or "-")
    c3.metric("Context", f"{status.ctx_size:,}" if status.ctx_size else "-")
    c4.metric("Users", status.num_users or "-")

    st.divider()

    try:
        api_info = svc.get_api_info()
    except Exception:
        api_info = {}

    st.subheader("API Information")
    ai1, ai2 = st.columns(2)
    with ai1:
        st.write(f"**Endpoint:** `{api_info.get('endpoint', '-')}`")
        st.write(f"**OpenAI Compatible:** `{api_info.get('openai_compatible', '-')}`")
    with ai2:
        key_status = "✅ Configured" if api_info.get("has_api_key") else "❌ Not set"
        admin_status = (
            "✅ Configured" if api_info.get("has_admin_key") else "❌ Not set"
        )
        st.write(f"**API Key:** {key_status}")
        st.write(f"**Admin Key:** {admin_status}")

    if not status.running:
        st.info("Lemonade server is offline. Server info unavailable.")
        _lemonade_models_section(svc)
        return

    st.divider()

    with st.spinner("Loading server info..."):
        health = _safe_proxy(svc.health)
        stats = _safe_proxy(svc.stats)
        slots = _safe_proxy(svc.slots)
        sys_info = _safe_proxy(svc.system_info)

    if health:
        st.subheader("Server Health")
        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Version", health.get("version", "-"))
        h2.metric("Active Model", health.get("model_loaded", "-"))
        h3.metric("WS Port", health.get("websocket_port", "-"))
        max_llm = health.get("max_models", {}).get("llm", "-")
        h4.metric("Max LLM Models", max_llm)

        loaded = health.get("all_models_loaded", [])
        if loaded:
            rows = []
            for m in loaded:
                last_use = "-"
                if m.get("last_use"):
                    try:
                        last_use = datetime.fromtimestamp(m["last_use"]).strftime(
                            "%H:%M:%S"
                        )
                    except (OSError, ValueError):
                        pass
                rows.append(
                    {
                        "Model": m.get("model_name", "-"),
                        "Type": m.get("type", "-"),
                        "Device": m.get("device", "-"),
                        "Recipe": m.get("recipe", "-"),
                        "PID": m.get("pid", "-"),
                        "Last Use": last_use,
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.info("No models loaded.")

    if stats:
        st.subheader("Performance Stats")
        s1, s2, s3, s4 = st.columns(4)
        ttft = stats.get("time_to_first_token")
        tps = stats.get("tokens_per_second")
        s1.metric("TTFT", f"{ttft:.2f}s" if ttft is not None else "-")
        s2.metric("Tokens/sec", f"{tps:.2f}" if tps is not None else "-")
        s3.metric("Input Tokens", stats.get("input_tokens", "-"))
        s4.metric("Output Tokens", stats.get("output_tokens", "-"))

    if slots and isinstance(slots, list) and len(slots) > 0:
        st.subheader("Slots")
        slot_rows = []
        for s in slots:
            nt = s.get("next_token", {})
            slot_rows.append(
                {
                    "ID": s.get("id", "-"),
                    "State": _state_badge(s.get("state", "-")),
                    "Task ID": s.get("task_id", "-"),
                    "Cache Tokens": f"{s.get('cache_tokens', 0):,}"
                    if s.get("cache_tokens") is not None
                    else "-",
                    "Decoded": nt.get("n_decoded", "-"),
                    "Remaining": nt.get("n_remain", "-"),
                }
            )
        st.dataframe(pd.DataFrame(slot_rows), hide_index=True, width="stretch")
    else:
        st.info("No slots available (model may not be loaded).")

    if sys_info:
        st.subheader("System Info")
        si1, si2, si3 = st.columns(3)
        si1.metric("OS", sys_info.get("OS Version", "-"))
        si2.metric("Processor", sys_info.get("Processor", "-"))
        si3.metric("Memory", sys_info.get("Physical Memory", "-"))

        devices = sys_info.get("devices", {})
        dev_rows = []
        if devices.get("cpu"):
            d = devices["cpu"]
            dev_rows.append(
                {
                    "Device": "CPU",
                    "Name": d.get("name", "-"),
                    "Details": f"{d.get('cores', '?')} cores / {d.get('threads', '?')} threads",
                    "Available": "✅" if d.get("available") else "❌",
                }
            )
        for i, d in enumerate(devices.get("amd_gpu", [])):
            dev_rows.append(
                {
                    "Device": f"AMD GPU {i}",
                    "Name": d.get("name", "-"),
                    "Details": f"{d.get('vram_gb', '?')} GB VRAM, {d.get('family', '-')}",
                    "Available": "✅" if d.get("available") else "❌",
                }
            )
        for i, d in enumerate(devices.get("nvidia_gpu", [])):
            dev_rows.append(
                {
                    "Device": f"NVIDIA GPU {i}",
                    "Name": d.get("name", "-"),
                    "Details": f"{d.get('vram_gb', '?')} GB VRAM",
                    "Available": "✅" if d.get("available") else "❌",
                }
            )
        if devices.get("amd_npu"):
            d = devices["amd_npu"]
            dev_rows.append(
                {
                    "Device": "AMD NPU",
                    "Name": d.get("name", "-"),
                    "Details": d.get("family", "-"),
                    "Available": "✅" if d.get("available") else "❌",
                }
            )
        if dev_rows:
            st.dataframe(pd.DataFrame(dev_rows), hide_index=True, width="stretch")
        else:
            st.info("No device information available.")

    _lemonade_models_section(svc)


def _lemonade_models_section(svc: LemonadeService) -> None:
    try:
        models = svc.list_models()
    except Exception:
        models = []

    st.subheader("Available Models")
    if models:
        model_rows = []
        for m in models:
            labels = m.get("labels", [])
            model_rows.append(
                {
                    "Name": m.get("name", m.get("model_name", "-")),
                    "Checkpoint": m.get("checkpoint", "-"),
                    "Recipe": m.get("recipe", "-"),
                    "Labels": ", ".join(labels) if labels else "-",
                }
            )
        st.dataframe(pd.DataFrame(model_rows), hide_index=True, width="stretch")
    else:
        st.info("No models configured.")


def _safe_proxy(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LemonadeConnectionError:
        return None
    except (GatewayConnectionError, GatewayNotEnabledError, GatewayAuthError):
        return None
    except Exception:
        return None


def _load_gateway_config_from_db(cfg: AppConfig) -> None:
    """Overlay SQLite-persisted gateway settings onto the config object."""
    db_path = cfg.database.path
    mapping = {
        "gateway_enabled": ("enabled", lambda v: v in ("true", "1", "yes")),
        "gateway_mode": ("gateway_mode", str),
        "gateway_rate_limit": ("rate_limit_tokens", int),
        "gateway_time_window": ("rate_limit_window", int),
        "gateway_redis_host": ("redis_host", lambda v: v or None),
        "gateway_redis_port": ("redis_port", int),
        "gateway_admin_url": ("admin_url", str),
        "gateway_admin_key": ("admin_key", str),
        "gateway_proxy_port": ("proxy_port", int),
    }
    for db_key, (attr, converter) in mapping.items():
        val = get_setting(db_key, db_path=db_path)
        if val is not None:
            setattr(cfg.gateway, attr, converter(val))


def page_gateway() -> None:
    st.header("AI Gateway")

    cfg = _get_config()
    _load_gateway_config_from_db(cfg)
    svc = _get_apisix_service()

    if st.button("🔄 Refresh"):
        st.rerun()

    st.subheader("Configuration")

    enabled = st.checkbox(
        "Enable Gateway",
        value=cfg.gateway.enabled,
        help="Toggle APISIX AI Gateway on/off. Requires APISIX to be installed and running.",
    )

    c_mode, c_rate, c_window = st.columns(3)
    with c_mode:
        mode = st.selectbox(
            "Mode",
            options=["per-user", "per-group"],
            index=0 if cfg.gateway.gateway_mode == "per-user" else 1,
            help="per-user: each user gets their own API key. per-group: all users in a group share one API key with combined rate limit.",
        )
    with c_rate:
        rate_limit = st.number_input(
            "Rate Limit (tokens)",
            min_value=1,
            max_value=100000,
            value=cfg.gateway.rate_limit_tokens,
            help="Token limit per consumer (per-user mode) or per-user within group (per-group mode)",
        )
    with c_window:
        time_window = st.number_input(
            "Time Window (sec)",
            min_value=1,
            max_value=86400,
            value=cfg.gateway.rate_limit_window,
            help="Rate limit time window in seconds",
        )

    c_redis, c_redis_port = st.columns(2)
    with c_redis:
        redis_host = st.text_input(
            "Redis Host",
            value=cfg.gateway.redis_host or "",
            placeholder="Leave empty for local policy",
            help="Redis host for shared rate limiting. Empty = local policy.",
        )
    with c_redis_port:
        redis_port = st.number_input(
            "Redis Port",
            min_value=1,
            max_value=65535,
            value=cfg.gateway.redis_port,
        )

    lemonade_host = cfg.lemonade.host if cfg.lemonade.host != "0.0.0.0" else "127.0.0.1"
    lemonade_url = st.text_input(
        "Lemonade URL",
        value=f"http://{lemonade_host}:{cfg.lemonade.port}",
    )
    lemonade_model = st.text_input(
        "Lemonade Model",
        value="user.gemma-4-31b-it",
    )

    if st.button("Save Gateway Settings", type="primary"):
        db_path = cfg.database.path
        set_setting("gateway_enabled", "true" if enabled else "false", db_path=db_path)
        set_setting("gateway_mode", mode, db_path=db_path)
        set_setting("gateway_rate_limit", str(rate_limit), db_path=db_path)
        set_setting("gateway_time_window", str(time_window), db_path=db_path)
        set_setting("gateway_redis_host", redis_host, db_path=db_path)
        set_setting("gateway_redis_port", str(redis_port), db_path=db_path)
        cfg.gateway.enabled = enabled
        cfg.gateway.gateway_mode = mode
        cfg.gateway.rate_limit_tokens = rate_limit
        cfg.gateway.rate_limit_window = time_window
        cfg.gateway.redis_host = redis_host or None
        cfg.gateway.redis_port = redis_port
        st.session_state.pop("apisix_service", None)
        st.toast("Gateway settings saved")
        st.rerun()

    st.divider()

    st.subheader("Status")
    status = _safe_proxy(svc.get_status)
    if status is None:
        st.warning("Gateway not reachable — ensure APISIX is installed and running.")
        return

    mode_label = "per-group" if status.mode == GatewayMode.PER_GROUP else "per-user"
    if status.running:
        status_text = "Running"
        status_icon = "🟢"
    elif status.installed:
        status_text = "Installed"
        status_icon = "🟡"
    else:
        status_text = "Not Installed"
        status_icon = "🔴"

    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Status", f"{status_icon} {status_text}")
    s2.metric("Enabled", "Yes" if status.enabled else "No")
    s3.metric("Consumers", status.consumers_count)
    s4.metric("Route", "Set" if status.route_configured else "Not set")
    s5.metric("Mode", mode_label)

    if not status.installed:
        st.info("APISIX is not installed. Run: `INSTALL_GATEWAY=true bash ./setup.sh`")
        return

    if not status.running:
        st.warning(
            "APISIX is installed but not running. Start: `sudo systemctl start apisix`"
        )
        return

    if not status.enabled:
        st.info(
            "APISIX is running but the gateway feature is not enabled. "
            "Check **Enable Gateway** above and click **Save** to activate."
        )
        return

    st.divider()

    st.subheader("Consumers")
    consumers = _safe_proxy(svc.list_consumers)
    if consumers:
        is_per_group = status.mode == GatewayMode.PER_GROUP
        consumer_rows = []
        for c in consumers:
            is_group = c.username.startswith("group-")
            row: dict = {
                "Username": c.username,
                "API Key": c.api_key[:12] + "..." if len(c.api_key) > 12 else c.api_key,
                "Full API Key": c.api_key,
                "Rate Limit": f"{c.rate_limit} tokens/{c.time_window}s",
                "Type": "Group" if is_group else "User",
            }
            if is_per_group:
                row["Group"] = c.group_name or "-"
                row["Users"] = c.user_count if is_group else ""
            consumer_rows.append(row)
        display_cols = ["Username", "API Key", "Rate Limit", "Type"]
        if is_per_group:
            display_cols += ["Group", "Users"]
        df = pd.DataFrame(consumer_rows)
        st.dataframe(
            df[display_cols],
            hide_index=True,
            width="stretch",
        )

        st.markdown("**Delete Consumer**")
        consumer_names = [c.username for c in consumers]
        selected = st.selectbox(
            "Select consumer to delete",
            options=[""] + consumer_names,
            label_visibility="collapsed",
        )
        if selected:
            st.warning(f"Will delete consumer: **{selected}**")
            if st.button("🗑 Confirm Delete"):
                try:
                    svc.delete_consumer(selected)
                    st.toast(f"Deleted consumer: {selected}")
                    st.rerun()
                except (GatewayNotEnabledError, GatewayConnectionError) as e:
                    st.error(str(e))
    else:
        st.info("No consumers configured.")

    st.divider()

    st.subheader("Actions")
    a1, a2 = st.columns(2)
    with a1:
        if st.button(
            "⚡ Setup Gateway",
            type="primary",
            help="Create route + consumers from DB groups",
        ):
            try:
                from app.db import get_groups, get_users

                db_groups = get_groups(db_path=cfg.database.path)
                if mode == "per-group":
                    group_data = []
                    for g in db_groups:
                        group_users = get_users(g.id, db_path=cfg.database.path)
                        group_data.append((g.name, len(group_users)))
                    created = svc.setup_gateway_groups(
                        lemonade_url=lemonade_url,
                        lemonade_api_key=cfg.lemonade.api_key,
                        lemonade_model=lemonade_model,
                        groups=group_data,
                        rate_limit_per_user=rate_limit,
                        time_window=time_window,
                    )
                else:
                    usernames = []
                    for g in db_groups:
                        group_users = get_users(g.id, db_path=cfg.database.path)
                        for u in group_users:
                            usernames.append(f"{g.name}-{u.username}")
                    created = svc.setup_gateway(
                        lemonade_url=lemonade_url,
                        lemonade_api_key=cfg.lemonade.api_key,
                        lemonade_model=lemonade_model,
                        usernames=usernames,
                        rate_limit=rate_limit,
                        time_window=time_window,
                    )
                st.success(f"Created {len(created)} consumer(s)")
                st.rerun()
            except (GatewayNotEnabledError, GatewayConnectionError) as e:
                st.error(str(e))
    with a2:
        if st.button("🧹 Cleanup Gateway", help="Remove all consumers and routes"):
            try:
                svc.cleanup()
                st.toast("Gateway cleaned up")
                st.rerun()
            except (GatewayNotEnabledError, GatewayConnectionError) as e:
                st.error(str(e))


def page_settings() -> None:
    st.header("Settings")

    cfg = _get_config()
    db_path = cfg.database.path

    st.subheader("Network")
    current_ip = get_setting("external_ip", db_path=db_path) or ""
    new_ip = st.text_input(
        "External IP", value=current_ip, placeholder="e.g. 52.162.90.16"
    )

    if st.button("Save", type="primary"):
        set_setting("external_ip", new_ip.strip(), db_path=db_path)
        st.toast("External IP saved")
        st.rerun()

    st.divider()

    _config_files_section(db_path)


def _config_files_section(db_path: str) -> None:
    st.subheader("Configuration Files")
    st.caption(
        "Upload or edit config files here. When `main.py` runs without flags, "
        "it reads these from the database."
    )

    from app.db import CONFIG_FILE_KEYS

    labels = {
        "config_groups_yaml": "Groups YAML",
        "config_kilo_json": "Kilo Code Config (kilo.json)",
        "config_vscode_settings": "VS Code Settings",
    }
    descriptions = {
        "config_groups_yaml": "Groups and users definition. Used by `main.py --groups` and `--from-db`.",
        "config_kilo_json": "Kilo Code provider config injected into each sandbox for LLM inference.",
        "config_vscode_settings": "VS Code settings injected into each sandbox's code-server.",
    }
    extensions = {
        "config_groups_yaml": ["yaml", "yml"],
        "config_kilo_json": ["json", "jsonc"],
        "config_vscode_settings": ["json", "jsonc"],
    }

    for key in CONFIG_FILE_KEYS:
        label = labels.get(key, key)
        current = get_setting(key, db_path=db_path) or ""
        has_content = current.strip() != ""
        status = "✅ Configured" if has_content else "❌ Not set"

        with st.expander(f"{label} — {status}"):
            st.caption(descriptions.get(key, ""))

            tab_upload, tab_edit = st.tabs(["Upload File", "Edit"])

            with tab_upload:
                uploaded = st.file_uploader(
                    f"Upload {label}",
                    type=extensions.get(key, []),
                    key=f"upload-{key}",
                    label_visibility="collapsed",
                )
                if uploaded is not None:
                    content = uploaded.read().decode("utf-8", errors="replace")
                    if st.button("Save Upload", key=f"save-upload-{key}"):
                        set_setting(key, content, db_path=db_path)
                        st.toast(f"{label} saved from upload")
                        st.rerun()

            with tab_edit:
                editor_height = min(max(current.count("\n") + 5, 10), 40)
                edited = st.text_area(
                    "Content",
                    value=current,
                    height=editor_height * 25,
                    key=f"edit-{key}",
                    label_visibility="collapsed",
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Save", key=f"save-edit-{key}"):
                        set_setting(key, edited, db_path=db_path)
                        st.toast(f"{label} saved")
                        st.rerun()
                with c2:
                    if has_content and st.button("Delete", key=f"delete-{key}"):
                        from app.db import delete_setting

                        delete_setting(key, db_path=db_path)
                        st.toast(f"{label} removed")
                        st.rerun()


def _get_git_version() -> str:
    try:
        describe = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            check=False,
        )
        rev = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        dirty = subprocess.run(
            ["git", "diff", "--quiet"],
            capture_output=True,
            text=True,
            check=False,
        )
        tag = describe.stdout.strip() if describe.returncode == 0 else None
        sha = rev.stdout.strip() if rev.returncode == 0 else None
        if not tag and not sha:
            return "0.1.0"
        parts: list[str] = [tag or sha or "0.1.0"]
        if sha and tag and not tag.startswith(sha):
            parts.append(sha)
        if dirty.returncode != 0:
            parts.append("dirty")
        return "-".join(parts)
    except FileNotFoundError:
        return "0.1.0"


def _check_auth(cfg: AppConfig) -> None:
    if not cfg.auth.local_password:
        return
    if st.session_state.get("authenticated"):
        return
    st.markdown(
        '<div style="display:flex;justify-content:center;align-items:center;'
        'min-height:60vh"><div style="text-align:center">'
        "<h2>THON Dashboard</h2></div></div>",
        unsafe_allow_html=True,
    )
    with st.form("login"):
        pwd = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            if pwd == cfg.auth.local_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password")
    st.stop()


def main() -> None:
    inject_custom_styles()
    cfg = _get_config()
    _check_auth(cfg)

    st.sidebar.title("◆ THON")
    st.sidebar.caption(_get_git_version())

    page = st.sidebar.radio(
        "Navigation",
        options=["Instances", "Groups", "Lemonade Server", "AI Gateway", "Settings"],
        label_visibility="collapsed",
    )

    if page == "Instances":
        page_instances()
    elif page == "Groups":
        page_groups()
    elif page == "Lemonade Server":
        page_lemonade()
    elif page == "AI Gateway":
        page_gateway()
    elif page == "Settings":
        page_settings()

    if cfg.auth.local_password and st.session_state.get("authenticated"):
        st.sidebar.divider()
        if st.sidebar.button("Logout"):
            st.session_state.authenticated = False
            st.rerun()


if __name__ == "__main__":
    main()
