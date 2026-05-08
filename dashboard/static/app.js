const API = '';
let allInstances = [];
let selectedIds = new Set();

// ── Navigation ──────────────────────────────────────────────────────

let allGroups = [];

document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
    document.getElementById('page-' + btn.dataset.page).classList.add('active');
    if (btn.dataset.page === 'instances') refreshInstances();
    if (btn.dataset.page === 'groups') refreshGroups();
    if (btn.dataset.page === 'lemonade') refreshLemonade();
    if (btn.dataset.page === 'settings') loadSettings();
  });
});

// ── Toast ───────────────────────────────────────────────────────────

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ── API helpers ─────────────────────────────────────────────────────

async function api(path, options = {}) {
  const resp = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.detail || resp.statusText);
  }
  return resp.json();
}

// ── Instances ───────────────────────────────────────────────────────

async function refreshInstances() {
  const loading = document.getElementById('instances-loading');
  const empty = document.getElementById('instances-empty');
  const tbody = document.getElementById('instances-body');
  loading.style.display = '';
  empty.style.display = 'none';
  tbody.innerHTML = '';

  try {
    const data = await api('/api/instances');
    allInstances = data.instances || [];
    loading.style.display = 'none';
    updateStats();
    renderInstances(allInstances);
  } catch (e) {
    loading.style.display = 'none';
    showToast('Failed to load instances: ' + e.message, 'error');
    empty.style.display = '';
  }
}

function updateStats() {
  const running = allInstances.filter(i => i.state === 'Running').length;
  const paused = allInstances.filter(i => i.state === 'Paused').length;
  document.getElementById('stat-running').textContent = running;
  document.getElementById('stat-paused').textContent = paused;
  document.getElementById('stat-total').textContent = allInstances.length;
}

function stateBadge(state) {
  const cls = state.toLowerCase();
  return '<span class="badge badge-' + cls + '"><span class="badge-dot"></span>' + state + '</span>';
}

function truncId(id) {
  if (!id) return '-';
  return id.length > 12 ? id.slice(0, 12) + '...' : id;
}

function fullId(id) {
  return id || '';
}

function renderInstances(instances) {
  const tbody = document.getElementById('instances-body');
  const empty = document.getElementById('instances-empty');

  if (instances.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = '';
    return;
  }

  empty.style.display = 'none';
  tbody.innerHTML = instances.map(inst => {
    const checked = selectedIds.has(inst.id) ? 'checked' : '';
    const label = inst.user ? inst.user.group + '/' + inst.user.username : '-';
    const endpointParts = [];
    if (inst.public_url) {
      endpointParts.push('<a href="' + inst.public_url + '" target="_blank" class="endpoint-link">' + inst.public_url + '</a>');
    }
    if (inst.endpoint) {
      const isDup = inst.public_url && inst.public_url.replace('https://', '').replace(/\/$/, '').endsWith(inst.endpoint);
      if (!isDup) endpointParts.push('<span class="endpoint-internal">' + inst.endpoint + '</span>');
    }
    const endpoint = endpointParts.length ? endpointParts.join('<br>') : '-';
    const isRunning = inst.state === 'Running';
    const isPaused = inst.state === 'Paused';
    const isStopped = inst.state === 'Terminated' || inst.state === 'Failed';

    return '<tr data-id="' + inst.id + '">'
      + '<td><input type="checkbox" ' + checked + ' onchange="toggleSelect(\'' + inst.id + '\', this.checked)"></td>'
      + '<td>' + label + '</td>'
      + '<td class="instance-id" title="' + (inst.id || '') + '">' + truncId(inst.id) + '</td>'
      + '<td>' + stateBadge(inst.state) + '</td>'
      + '<td>' + endpoint + '</td>'
      + '<td>'
      + (isRunning ? '<button class="btn btn-warning btn-sm" onclick="actionInstance(\'' + inst.id + '\',\'pause\')">Pause</button> ' : '')
      + (isPaused ? '<button class="btn btn-success btn-sm" onclick="actionInstance(\'' + inst.id + '\',\'resume\')">Resume</button> ' : '')
      + (isStopped ? '<button class="btn btn-primary btn-sm" onclick="actionInstance(\'' + inst.id + '\',\'recreate\')">Restart</button> ' : '')
      + '<button class="btn btn-danger btn-sm" onclick="actionInstance(\'' + inst.id + '\',\'kill\')">Kill</button>'
      + '</td>'
      + '</tr>';
  }).join('');
}

function filterInstances() {
  const search = document.getElementById('search-input').value.toLowerCase();
  const stateFilter = document.getElementById('state-filter').value;
  const filtered = allInstances.filter(inst => {
    const label = inst.user ? inst.user.group + '/' + inst.user.username : '';
    const matchesSearch = !search || label.toLowerCase().includes(search) || (inst.id || '').toLowerCase().includes(search);
    const matchesState = !stateFilter || inst.state === stateFilter;
    return matchesSearch && matchesState;
  });
  renderInstances(filtered);
}

function toggleSelect(id, checked) {
  if (checked) selectedIds.add(id);
  else selectedIds.delete(id);
  updateBulkButtons();
}

function toggleSelectAll() {
  const all = document.getElementById('select-all').checked;
  selectedIds.clear();
  if (all) allInstances.forEach(i => selectedIds.add(i.id));
  updateBulkButtons();
  renderInstances(allInstances);
}

function updateBulkButtons() {
  const has = selectedIds.size > 0;
  document.getElementById('bulk-pause-btn').disabled = !has;
  document.getElementById('bulk-resume-btn').disabled = !has;
  document.getElementById('bulk-kill-btn').disabled = !has;
}

async function actionInstance(id, action) {
  try {
    if (action === 'kill') {
      await api('/api/instances/' + id, { method: 'DELETE' });
      showToast('Instance terminated', 'info');
    } else if (action === 'recreate') {
      await api('/api/instances/' + id + '/recreate', { method: 'POST' });
      showToast('Instance recreated', 'success');
    } else {
      await api('/api/instances/' + id + '/' + action, { method: 'POST' });
      showToast('Instance ' + action + 'd', 'success');
    }
    setTimeout(refreshInstances, 500);
  } catch (e) {
    showToast('Action failed: ' + e.message, 'error');
  }
}

async function bulkAction(action) {
  if (selectedIds.size === 0) return;
  const ids = Array.from(selectedIds);
  try {
    const endpoint = action === 'kill' ? 'bulk/kill' : 'bulk/' + action;
    const data = await api('/api/instances/' + endpoint, {
      method: 'POST',
      body: JSON.stringify({ instance_ids: ids }),
    });
    const succeeded = data.results.filter(r => r.status !== 'error').length;
    const failed = data.results.filter(r => r.status === 'error').length;
    showToast(action.charAt(0).toUpperCase() + action.slice(1) + 'd ' + succeeded + ' instance(s)' + (failed ? ', ' + failed + ' failed' : ''), succeeded ? 'success' : 'error');
    selectedIds.clear();
    updateBulkButtons();
    setTimeout(refreshInstances, 500);
  } catch (e) {
    showToast('Bulk action failed: ' + e.message, 'error');
  }
}

// ── Create Modal ────────────────────────────────────────────────────

function openCreateModal() {
  document.getElementById('create-modal').classList.add('active');
}

function closeCreateModal() {
  document.getElementById('create-modal').classList.remove('active');
}

async function createInstance() {
  const group = document.getElementById('create-group').value || 'default';
  const username = document.getElementById('create-username').value || 'workspace';
  const port = parseInt(document.getElementById('create-port').value, 10) || 8443;
  const secure = document.getElementById('create-secure').checked;

  try {
    await api('/api/instances', {
      method: 'POST',
      body: JSON.stringify({ group, username, port, secure }),
    });
    closeCreateModal();
    showToast('Instance created: ' + group + '/' + username, 'success');
    setTimeout(refreshInstances, 1000);
  } catch (e) {
    showToast('Create failed: ' + e.message, 'error');
  }
}

// ── Groups ──────────────────────────────────────────────────────────

let allGroups = [];

async function refreshGroups() {
  const loading = document.getElementById('groups-loading');
  const empty = document.getElementById('groups-empty');
  const list = document.getElementById('groups-list');
  loading.style.display = '';
  empty.style.display = 'none';
  list.innerHTML = '';

  try {
    const data = await api('/api/groups');
    allGroups = data || [];
    loading.style.display = 'none';
    document.getElementById('stat-groups').textContent = allGroups.length;
    const totalUsers = allGroups.reduce((sum, g) => sum + g.user_count, 0);
    document.getElementById('stat-total-users').textContent = totalUsers;
    renderGroups(allGroups);
  } catch (e) {
    loading.style.display = 'none';
    showToast('Failed to load groups: ' + e.message, 'error');
  }
}

function filterGroups() {
  const search = document.getElementById('group-search-input').value.toLowerCase();
  const filtered = allGroups.filter(g => g.name.toLowerCase().includes(search));
  renderGroups(filtered);
}

function truncUuid(id) {
  if (!id) return '-';
  return id.length > 8 ? id.slice(0, 8) : id;
}

function renderGroups(groups) {
  const list = document.getElementById('groups-list');
  const empty = document.getElementById('groups-empty');

  if (groups.length === 0) {
    list.innerHTML = '';
    empty.style.display = '';
    return;
  }

  empty.style.display = 'none';
  list.innerHTML = groups.map(g => {
    const detail = g.users ? g : null;
    const users = detail ? detail.users : [];
    const userRows = users.map(u =>
      '<tr>'
      + '<td class="instance-id" title="' + u.id + '">' + truncUuid(u.id) + '</td>'
      + '<td>' + u.username + '</td>'
      + '<td class="instance-id">' + (u.workspace_path || '-') + '</td>'
      + '<td class="instance-id">' + (u.storage_path || '-') + '</td>'
      + '<td>'
      + '<button class="btn btn-sm" onclick="openEditUserModal(\'' + g.id + '\',\'' + u.id + '\',\'' + u.username + '\',\'' + (u.workspace_path || '') + '\',\'' + (u.storage_path || '') + '\')">Edit</button> '
      + '<button class="btn btn-danger btn-sm" onclick="removeUser(\'' + g.id + '\',\'' + u.id + '\',\'' + u.username + '\')">Remove</button>'
      + '</td>'
      + '</tr>'
    ).join('');

    return '<div class="card" style="margin-bottom:16px">'
      + '<div class="card-header" style="display:flex;align-items:center;justify-content:space-between">'
      + '<div class="card-title">' + g.name + ' <span style="color:var(--text-muted);font-size:12px;font-weight:normal">(' + truncUuid(g.id) + ')</span></div>'
      + '<div>'
      + '<button class="btn btn-sm" onclick="openAddUserModal(\'' + g.id + '\')">+ User</button> '
      + '<button class="btn btn-sm" onclick="renameGroupPrompt(\'' + g.id + '\',\'' + g.name + '\')">Rename</button> '
      + '<button class="btn btn-danger btn-sm" onclick="deleteGroupConfirm(\'' + g.id + '\',\'' + g.name + '\')">Delete</button>'
      + '</div>'
      + '</div>'
      + '<div class="table-container"><table>'
      + '<thead><tr><th>UUID</th><th>Username</th><th>Workspace Path</th><th>Storage Path</th><th>Actions</th></tr></thead>'
      + '<tbody>' + userRows + '</tbody>'
      + '</table></div>'
      + '</div>';
  }).join('');
}

function openCreateGroupModal() {
  document.getElementById('create-group-modal').classList.add('active');
  document.getElementById('new-group-name').value = '';
}

function closeCreateGroupModal() {
  document.getElementById('create-group-modal').classList.remove('active');
}

async function createGroup() {
  const name = document.getElementById('new-group-name').value.trim();
  if (!name) return;
  try {
    await api('/api/groups', { method: 'POST', body: JSON.stringify({ name }) });
    closeCreateGroupModal();
    showToast('Group created: ' + name, 'success');
    refreshGroups();
  } catch (e) {
    showToast('Failed to create group: ' + e.message, 'error');
  }
}

function renameGroupPrompt(groupId, currentName) {
  const newName = prompt('Rename group:', currentName);
  if (!newName || newName === currentName) return;
  api('/api/groups/' + groupId, { method: 'PUT', body: JSON.stringify({ name: newName }) })
    .then(() => { showToast('Group renamed', 'success'); refreshGroups(); })
    .catch(e => showToast('Rename failed: ' + e.message, 'error'));
}

function deleteGroupConfirm(groupId, name) {
  if (!confirm('Delete group "' + name + '" and all its users?')) return;
  api('/api/groups/' + groupId, { method: 'DELETE' })
    .then(() => { showToast('Group deleted', 'info'); refreshGroups(); })
    .catch(e => showToast('Delete failed: ' + e.message, 'error'));
}

function openAddUserModal(groupId) {
  document.getElementById('add-user-modal').classList.add('active');
  document.getElementById('add-user-group-id').value = groupId;
  document.getElementById('new-user-username').value = '';
  document.getElementById('new-user-workspace').value = '';
  document.getElementById('new-user-storage').value = '';
}

function closeAddUserModal() {
  document.getElementById('add-user-modal').classList.remove('active');
}

async function addUser() {
  const groupId = document.getElementById('add-user-group-id').value;
  const username = document.getElementById('new-user-username').value.trim();
  if (!username) return;
  const workspace = document.getElementById('new-user-workspace').value.trim() || null;
  const storage = document.getElementById('new-user-storage').value.trim() || null;
  try {
    await api('/api/groups/' + groupId + '/users', {
      method: 'POST',
      body: JSON.stringify({ username, workspace_path: workspace, storage_path: storage }),
    });
    closeAddUserModal();
    showToast('User added: ' + username, 'success');
    refreshGroups();
  } catch (e) {
    showToast('Failed to add user: ' + e.message, 'error');
  }
}

function openEditUserModal(groupId, userId, username, workspace, storage) {
  document.getElementById('edit-user-modal').classList.add('active');
  document.getElementById('edit-user-id').value = userId;
  document.getElementById('edit-user-group-id').value = groupId;
  document.getElementById('edit-user-username').value = username;
  document.getElementById('edit-user-workspace').value = workspace || '';
  document.getElementById('edit-user-storage').value = storage || '';
}

function closeEditUserModal() {
  document.getElementById('edit-user-modal').classList.remove('active');
}

async function saveEditUser() {
  const userId = document.getElementById('edit-user-id').value;
  const groupId = document.getElementById('edit-user-group-id').value;
  const username = document.getElementById('edit-user-username').value.trim();
  const workspace = document.getElementById('edit-user-workspace').value.trim() || null;
  const storage = document.getElementById('edit-user-storage').value.trim() || null;
  try {
    await api('/api/groups/' + groupId + '/users/' + userId, {
      method: 'PUT',
      body: JSON.stringify({ username, workspace_path: workspace, storage_path: storage }),
    });
    closeEditUserModal();
    showToast('User updated', 'success');
    refreshGroups();
  } catch (e) {
    showToast('Failed to update user: ' + e.message, 'error');
  }
}

function removeUser(groupId, userId, username) {
  if (!confirm('Remove user "' + username + '"?')) return;
  api('/api/groups/' + groupId + '/users/' + userId, { method: 'DELETE' })
    .then(() => { showToast('User removed', 'info'); refreshGroups(); })
    .catch(e => showToast('Remove failed: ' + e.message, 'error'));
}

// ── Lemonade ────────────────────────────────────────────────────────

async function refreshLemonade() {
  try {
    const [status, apiInfo, models] = await Promise.all([
      api('/api/lemonade/status'),
      api('/api/lemonade/api-info'),
      api('/api/lemonade/models'),
    ]);

    const statusEl = document.getElementById('lemonade-status');
    statusEl.textContent = status.running ? 'Online' : 'Offline';
    statusEl.className = 'stat-value ' + (status.running ? 'text-success' : 'text-danger');

    document.getElementById('lemonade-model').textContent = status.model || '-';
    document.getElementById('lemonade-ctx').textContent = status.ctx_size ? status.ctx_size.toLocaleString() : '-';
    document.getElementById('lemonade-users').textContent = status.num_users || '-';

    document.getElementById('lemonade-endpoint').textContent = apiInfo.endpoint || '-';
    document.getElementById('lemonade-openai').textContent = apiInfo.openai_compatible || '-';
    document.getElementById('lemonade-key').textContent = apiInfo.has_api_key ? 'Configured' : 'Not set';
    document.getElementById('lemonade-admin-key').textContent = apiInfo.has_admin_key ? 'Configured' : 'Not set';

    const tbody = document.getElementById('lemonade-models-body');
    const empty = document.getElementById('lemonade-models-empty');
    const modelList = models.models || [];

    if (modelList.length === 0) {
      tbody.innerHTML = '';
      empty.style.display = '';
    } else {
      empty.style.display = 'none';
      tbody.innerHTML = modelList.map(m => {
        return '<tr>'
          + '<td class="instance-id">' + (m.name || m.model_name || '-') + '</td>'
          + '<td class="instance-id">' + (m.checkpoint || '-') + '</td>'
          + '<td>' + (m.recipe || '-') + '</td>'
          + '<td>' + (m.labels ? m.labels.join(', ') : '-') + '</td>'
          + '</tr>';
      }).join('');
    }

    if (status.running) {
      refreshLemonadeServerInfo();
    } else {
      clearLemonadeServerInfo();
    }
  } catch (e) {
    showToast('Failed to load Lemonade data: ' + e.message, 'error');
  }
}

// ── Settings ──────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const data = await api('/api/instances/settings/external_ip');
    document.getElementById('setting-external-ip').value = data.value || '';
  } catch (e) {
    // ignore
  }
}

async function saveExternalIp() {
  const value = document.getElementById('setting-external-ip').value.trim();
  try {
    await api('/api/instances/settings/external_ip', {
      method: 'PUT',
      body: JSON.stringify({ key: 'external_ip', value: value }),
    });
    showToast('External IP saved', 'success');
    setTimeout(refreshInstances, 300);
  } catch (e) {
    showToast('Failed to save: ' + e.message, 'error');
  }
}

async function refreshLemonadeServerInfo() {
  try {
    const [health, stats, slots, sysInfo] = await Promise.all([
      api('/api/lemonade/health').catch(() => null),
      api('/api/lemonade/stats').catch(() => null),
      api('/api/lemonade/slots').catch(() => null),
      api('/api/lemonade/system-info').catch(() => null),
    ]);

    renderHealth(health);
    renderStats(stats);
    renderSlots(slots);
    renderSystemInfo(sysInfo);
  } catch (e) {
    // non-fatal: server info is supplementary
  }
}

function clearLemonadeServerInfo() {
  document.getElementById('lemonade-version').textContent = '-';
  document.getElementById('lemonade-health-model').textContent = '-';
  document.getElementById('lemonade-ws-port').textContent = '-';
  document.getElementById('lemonade-max-llm').textContent = '-';
  document.getElementById('lemonade-loaded-body').innerHTML = '';
  document.getElementById('lemonade-loaded-empty').style.display = '';
  document.getElementById('lemonade-ttft').textContent = '-';
  document.getElementById('lemonade-tps').textContent = '-';
  document.getElementById('lemonade-input-tokens').textContent = '-';
  document.getElementById('lemonade-output-tokens').textContent = '-';
  document.getElementById('lemonade-slots-body').innerHTML = '';
  document.getElementById('lemonade-slots-empty').style.display = '';
  document.getElementById('lemonade-sys-os').textContent = '-';
  document.getElementById('lemonade-sys-cpu').textContent = '-';
  document.getElementById('lemonade-sys-mem').textContent = '-';
  document.getElementById('lemonade-devices-body').innerHTML = '';
  document.getElementById('lemonade-devices-empty').style.display = '';
}

function renderHealth(health) {
  if (!health) return;
  document.getElementById('lemonade-version').textContent = health.version || '-';
  document.getElementById('lemonade-health-model').textContent = health.model_loaded || '-';
  document.getElementById('lemonade-ws-port').textContent = health.websocket_port != null ? health.websocket_port : '-';
  const maxM = health.max_models || {};
  document.getElementById('lemonade-max-llm').textContent = maxM.llm != null ? maxM.llm : '-';

  const loadedTbody = document.getElementById('lemonade-loaded-body');
  const loadedEmpty = document.getElementById('lemonade-loaded-empty');
  const loaded = health.all_models_loaded || [];
  if (loaded.length === 0) {
    loadedTbody.innerHTML = '';
    loadedEmpty.style.display = '';
  } else {
    loadedEmpty.style.display = 'none';
    loadedTbody.innerHTML = loaded.map(m => {
      const lastUse = m.last_use ? new Date(m.last_use * 1000).toLocaleTimeString() : '-';
      return '<tr>'
        + '<td class="instance-id">' + (m.model_name || '-') + '</td>'
        + '<td>' + (m.type || '-') + '</td>'
        + '<td>' + (m.device || '-') + '</td>'
        + '<td>' + (m.recipe || '-') + '</td>'
        + '<td>' + (m.pid != null ? m.pid : '-') + '</td>'
        + '<td>' + lastUse + '</td>'
        + '</tr>';
    }).join('');
  }
}

function renderStats(stats) {
  if (!stats) return;
  document.getElementById('lemonade-ttft').textContent = stats.time_to_first_token != null ? stats.time_to_first_token.toFixed(2) + 's' : '-';
  document.getElementById('lemonade-tps').textContent = stats.tokens_per_second != null ? stats.tokens_per_second.toFixed(2) : '-';
  document.getElementById('lemonade-input-tokens').textContent = stats.input_tokens != null ? stats.input_tokens : '-';
  document.getElementById('lemonade-output-tokens').textContent = stats.output_tokens != null ? stats.output_tokens : '-';
}

function renderSlots(slots) {
  const tbody = document.getElementById('lemonade-slots-body');
  const empty = document.getElementById('lemonade-slots-empty');
  if (!slots || !Array.isArray(slots) || slots.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  tbody.innerHTML = slots.map(s => {
    const nt = s.next_token || {};
    const stateCls = (s.state || '').toLowerCase();
    return '<tr>'
      + '<td>' + (s.id != null ? s.id : '-') + '</td>'
      + '<td><span class="badge badge-' + stateCls + '"><span class="badge-dot"></span>' + (s.state || '-') + '</span></td>'
      + '<td>' + (s.task_id != null ? s.task_id : '-') + '</td>'
      + '<td>' + (s.cache_tokens != null ? s.cache_tokens.toLocaleString() : '-') + '</td>'
      + '<td>' + (nt.n_decoded != null ? nt.n_decoded : '-') + '</td>'
      + '<td>' + (nt.n_remain != null ? nt.n_remain : '-') + '</td>'
      + '</tr>';
  }).join('');
}

function renderSystemInfo(sysInfo) {
  if (!sysInfo) return;
  document.getElementById('lemonade-sys-os').textContent = sysInfo['OS Version'] || '-';
  document.getElementById('lemonade-sys-cpu').textContent = sysInfo['Processor'] || '-';
  document.getElementById('lemonade-sys-mem').textContent = sysInfo['Physical Memory'] || '-';

  const tbody = document.getElementById('lemonade-devices-body');
  const empty = document.getElementById('lemonade-devices-empty');
  const devices = sysInfo.devices || {};
  const rows = [];
  if (devices.cpu) {
    const d = devices.cpu;
    rows.push({ kind: 'CPU', name: d.name || '-', details: d.cores + ' cores / ' + d.threads + ' threads', available: d.available });
  }
  if (Array.isArray(devices.amd_gpu)) {
    devices.amd_gpu.forEach((d, i) => {
      rows.push({ kind: 'AMD GPU ' + i, name: d.name || '-', details: (d.vram_gb || '?') + ' GB VRAM, ' + (d.family || '-'), available: d.available });
    });
  }
  if (Array.isArray(devices.nvidia_gpu)) {
    devices.nvidia_gpu.forEach((d, i) => {
      rows.push({ kind: 'NVIDIA GPU ' + i, name: d.name || '-', details: (d.vram_gb || '?') + ' GB VRAM', available: d.available });
    });
  }
  if (devices.amd_npu) {
    const d = devices.amd_npu;
    rows.push({ kind: 'AMD NPU', name: d.name || '-', details: d.family || '-', available: d.available });
  }

  if (rows.length === 0) {
    tbody.innerHTML = '';
    empty.style.display = '';
  } else {
    empty.style.display = 'none';
    tbody.innerHTML = rows.map(r => {
      const avail = r.available ? '<span class="text-success">Yes</span>' : '<span class="text-danger">No</span>';
      return '<tr>'
        + '<td>' + r.kind + '</td>'
        + '<td class="instance-id">' + r.name + '</td>'
        + '<td>' + r.details + '</td>'
        + '<td>' + avail + '</td>'
        + '</tr>';
    }).join('');
  }
}

// ── Groups ──────────────────────────────────────────────────────────

async function refreshGroups() {
  const loading = document.getElementById('groups-loading');
  const empty = document.getElementById('groups-empty');
  const container = document.getElementById('groups-container');
  loading.style.display = '';
  empty.style.display = 'none';
  container.innerHTML = '';

  try {
    const data = await api('/api/groups');
    allGroups = data || [];
    loading.style.display = 'none';
    updateGroupStats();
    renderGroups(allGroups);
  } catch (e) {
    loading.style.display = 'none';
    showToast('Failed to load groups: ' + e.message, 'error');
    empty.style.display = '';
  }
}

function updateGroupStats() {
  const totalUsers = allGroups.reduce((sum, g) => sum + (g.users ? g.users.length : 0), 0);
  document.getElementById('stat-groups').textContent = allGroups.length;
  document.getElementById('stat-users').textContent = totalUsers;
}

function truncUuid(id) {
  if (!id) return '-';
  return id.length > 8 ? id.slice(0, 8) : id;
}

function renderGroups(groups) {
  const container = document.getElementById('groups-container');
  const empty = document.getElementById('groups-empty');

  if (groups.length === 0) {
    container.innerHTML = '';
    empty.style.display = '';
    return;
  }

  empty.style.display = 'none';
  container.innerHTML = groups.map(group => {
    const users = group.users || [];
    const usersHtml = users.length > 0
      ? users.map(u => {
          return '<tr>'
            + '<td class="instance-id" title="' + u.id + '">' + truncUuid(u.id) + '</td>'
            + '<td>' + escapeHtml(u.username) + '</td>'
            + '<td class="instance-id">' + (u.workspace_path || '-') + '</td>'
            + '<td class="instance-id">' + (u.storage_path || '-') + '</td>'
            + '<td>'
            + '<button class="btn btn-sm" onclick="openEditUserModal(\'' + group.id + '\',\'' + u.id + '\',\'' + escapeHtml(u.username) + '\')">Edit</button> '
            + '<button class="btn btn-danger btn-sm" onclick="deleteUser(\'' + group.id + '\',\'' + u.id + '\',\'' + escapeHtml(u.username) + '\')">Remove</button>'
            + '</td>'
            + '</tr>';
        }).join('')
      : '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:24px;">No users</td></tr>';

    return '<div class="group-card">'
      + '<div class="group-header">'
      + '<div class="group-title">'
      + '<span class="group-name">' + escapeHtml(group.name) + '</span>'
      + '<span class="instance-id" title="' + group.id + '">(' + truncUuid(group.id) + ')</span>'
      + '</div>'
      + '<div class="group-actions">'
      + '<button class="btn btn-sm" onclick="openAddUserModal(\'' + group.id + '\')">+ User</button> '
      + '<button class="btn btn-sm" onclick="openEditGroupModal(\'' + group.id + '\',\'' + escapeHtml(group.name) + '\')">Rename</button> '
      + '<button class="btn btn-danger btn-sm" onclick="deleteGroup(\'' + group.id + '\',\'' + escapeHtml(group.name) + '\')">Delete</button>'
      + '</div>'
      + '</div>'
      + '<table>'
      + '<thead><tr>'
      + '<th>UUID</th>'
      + '<th>Username</th>'
      + '<th>Workspace Path</th>'
      + '<th>Storage Path</th>'
      + '<th>Actions</th>'
      + '</tr></thead>'
      + '<tbody>' + usersHtml + '</tbody>'
      + '</table>'
      + '</div>';
  }).join('');
}

function filterGroups() {
  const search = document.getElementById('groups-search-input').value.toLowerCase();
  const filtered = allGroups.filter(g => {
    const userNames = (g.users || []).map(u => u.username).join(' ');
    return g.name.toLowerCase().includes(search) || userNames.toLowerCase().includes(search);
  });
  renderGroups(filtered);
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function openCreateGroupModal() {
  document.getElementById('create-group-name').value = '';
  document.getElementById('create-group-modal').classList.add('active');
}

function closeCreateGroupModal() {
  document.getElementById('create-group-modal').classList.remove('active');
}

async function createGroup() {
  const name = document.getElementById('create-group-name').value.trim();
  if (!name) { showToast('Group name is required', 'error'); return; }
  try {
    await api('/api/groups', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
    closeCreateGroupModal();
    showToast('Group created', 'success');
    refreshGroups();
  } catch (e) {
    showToast('Failed to create group: ' + e.message, 'error');
  }
}

function openEditGroupModal(groupId, groupName) {
  document.getElementById('edit-group-id').value = groupId;
  document.getElementById('edit-group-name').value = groupName;
  document.getElementById('edit-group-modal').classList.add('active');
}

function closeEditGroupModal() {
  document.getElementById('edit-group-modal').classList.remove('active');
}

async function saveGroup() {
  const id = document.getElementById('edit-group-id').value;
  const name = document.getElementById('edit-group-name').value.trim();
  if (!name) { showToast('Group name is required', 'error'); return; }
  try {
    await api('/api/groups/' + id, {
      method: 'PUT',
      body: JSON.stringify({ name }),
    });
    closeEditGroupModal();
    showToast('Group renamed', 'success');
    refreshGroups();
  } catch (e) {
    showToast('Failed to rename group: ' + e.message, 'error');
  }
}

async function deleteGroup(groupId, groupName) {
  if (!confirm('Delete group "' + groupName + '" and all its users?')) return;
  try {
    await api('/api/groups/' + groupId, { method: 'DELETE' });
    showToast('Group deleted', 'info');
    refreshGroups();
  } catch (e) {
    showToast('Failed to delete group: ' + e.message, 'error');
  }
}

function openAddUserModal(groupId) {
  document.getElementById('add-user-group-id').value = groupId;
  document.getElementById('add-user-username').value = '';
  document.getElementById('add-user-modal').classList.add('active');
}

function closeAddUserModal() {
  document.getElementById('add-user-modal').classList.remove('active');
}

async function addUser() {
  const groupId = document.getElementById('add-user-group-id').value;
  const username = document.getElementById('add-user-username').value.trim();
  if (!username) { showToast('Username is required', 'error'); return; }
  try {
    await api('/api/groups/' + groupId + '/users', {
      method: 'POST',
      body: JSON.stringify({ username }),
    });
    closeAddUserModal();
    showToast('User added', 'success');
    refreshGroups();
  } catch (e) {
    showToast('Failed to add user: ' + e.message, 'error');
  }
}

function openEditUserModal(groupId, userId, username) {
  document.getElementById('edit-user-group-id').value = groupId;
  document.getElementById('edit-user-id').value = userId;
  document.getElementById('edit-user-username').value = username;
  document.getElementById('edit-user-modal').classList.add('active');
}

function closeEditUserModal() {
  document.getElementById('edit-user-modal').classList.remove('active');
}

async function saveUser() {
  const groupId = document.getElementById('edit-user-group-id').value;
  const userId = document.getElementById('edit-user-id').value;
  const username = document.getElementById('edit-user-username').value.trim();
  if (!username) { showToast('Username is required', 'error'); return; }
  try {
    await api('/api/groups/' + groupId + '/users/' + userId, {
      method: 'PUT',
      body: JSON.stringify({ username }),
    });
    closeEditUserModal();
    showToast('User renamed', 'success');
    refreshGroups();
  } catch (e) {
    showToast('Failed to rename user: ' + e.message, 'error');
  }
}

async function deleteUser(groupId, userId, username) {
  if (!confirm('Remove user "' + username + '"?')) return;
  try {
    await api('/api/groups/' + groupId + '/users/' + userId, { method: 'DELETE' });
    showToast('User removed', 'info');
    refreshGroups();
  } catch (e) {
    showToast('Failed to remove user: ' + e.message, 'error');
  }
}

// ── Init ────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  refreshInstances();
});
