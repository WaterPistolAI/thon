const API = '';
let allInstances = [];
let selectedIds = new Set();

// ── Navigation ──────────────────────────────────────────────────────

document.querySelectorAll('.nav-item[data-page]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
    document.getElementById('page-' + btn.dataset.page).classList.add('active');
    if (btn.dataset.page === 'instances') refreshInstances();
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

// ── Init ────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  refreshInstances();
});
