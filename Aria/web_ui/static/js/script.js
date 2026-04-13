// ── Navigation ────────────────────────────────────────────────────────────────
const navItems = document.querySelectorAll('.nav-item');
const sections = document.querySelectorAll('.section');
const pageTitle = document.getElementById('pageTitle');

navItems.forEach(item => {
    item.addEventListener('click', () => {
        const target = item.dataset.section;
        navItems.forEach(n => n.classList.remove('active'));
        sections.forEach(s => s.classList.remove('active'));
        item.classList.add('active');
        document.getElementById('section-' + target).classList.add('active');
        pageTitle.textContent = item.textContent.trim();
        loadSection(target);
    });
});

// ── API helpers ───────────────────────────────────────────────────────────────
async function fetchJSON(url) {
    try {
        const r = await fetch(url);
        if (!r.ok) throw new Error(r.status);
        return await r.json();
    } catch (e) {
        console.warn('Fetch failed:', url, e);
        return null;
    }
}

async function postJSON(url, body) {
    try {
        const r = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return await r.json();
    } catch (e) {
        console.warn('Post failed:', url, e);
        return null;
    }
}

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val != null ? val : '—';
}

function esc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ── Status dot ───────────────────────────────────────────────────────────────
function setGlobalStatus(connected) {
    const dot = document.getElementById('globalStatus');
    const lbl = document.getElementById('globalStatusLabel');
    if (dot && lbl) {
        dot.className = 'status-dot ' + (connected ? 'online' : 'offline');
        lbl.textContent = connected ? 'Connected' : 'Disconnected';
    }
}

// ── Overview ──────────────────────────────────────────────────────────────────
async function loadOverview() {
    const res = await fetchJSON('/api/bot');
    if (!res || !res.data) { setGlobalStatus(false); return; }
    const d = res.data;
    setGlobalStatus(d.connected);
    setText('username', d.username);
    setText('userId', d.user_id);
    setText('prefix', d.prefix);
    setText('uptime', d.uptime);
    setText('commandCount', d.command_count);
    setText('commandsRegistered', d.commands_registered);
    setText('connectionStatus', d.connected ? 'Online' : 'Offline');
    setText('botStatus', d.status || 'online');
}

// ── Commands ─────────────────────────────────────────────────────────────────
let _allCommands = [];

async function loadCommands() {
    const res = await fetchJSON('/api/commands');
    if (!res || !res.data) return;
    _allCommands = res.data.commands || [];
    setText('cmdCountLabel', _allCommands.length + ' commands');
    renderCommands(_allCommands);
}

function renderCommands(list) {
    const tbody = document.getElementById('commandsBody');
    if (!tbody) return;
    if (!list || list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="empty-row">No commands found</td></tr>';
        return;
    }
    tbody.innerHTML = list.map(c =>
        `<tr>
            <td class="cmd-name">${esc(c.name)}</td>
            <td class="cmd-aliases">${c.aliases && c.aliases.length ? esc(c.aliases.join(', ')) : '<span style="color:var(--text-muted)">—</span>'}</td>
            <td>${esc(c.description || '—')}</td>
        </tr>`
    ).join('');
}

// live search
document.addEventListener('DOMContentLoaded', () => {
    const searchEl = document.getElementById('cmdSearch');
    if (searchEl) {
        searchEl.addEventListener('input', () => {
            const q = searchEl.value.toLowerCase().trim();
            if (!q) { renderCommands(_allCommands); return; }
            renderCommands(_allCommands.filter(c =>
                c.name.toLowerCase().includes(q) ||
                (c.aliases || []).some(a => a.toLowerCase().includes(q)) ||
                (c.description || '').toLowerCase().includes(q)
            ));
        });
    }
});

// ── Analytics ─────────────────────────────────────────────────────────────────
async function loadAnalytics() {
    const res = await fetchJSON('/api/analytics');
    if (!res || !res.data) return;
    const d = res.data;
    setText('totalCommands', d.total_commands ?? 0);
    setText('successRate', (d.success_rate ?? 100) + '%');
    setText('avgResponseMs', (d.avg_response_ms ?? 0) + 's');

    const tbody = document.getElementById('topCommandsBody');
    if (!d.top_commands || d.top_commands.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="empty-row">No command data yet</td></tr>';
        return;
    }
    tbody.innerHTML = d.top_commands.map((c, i) =>
        `<tr><td>${i + 1}</td><td>${esc(c.name)}</td><td>${c.count}</td></tr>`
    ).join('');
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
    const res = await fetchJSON('/api/history');
    if (!res || !res.data) return;
    const d = res.data;
    setText('historyTotal', d.total ?? 0);

    const list = document.getElementById('historyList');
    if (!d.entries || d.entries.length === 0) {
        list.innerHTML = '<div class="empty-row">No history entries found</div>';
        return;
    }
    list.innerHTML = d.entries.map(e => {
        const txt = typeof e === 'object' ? JSON.stringify(e, null, 2) : String(e);
        return `<div class="history-entry">${esc(txt)}</div>`;
    }).join('');
}

// ── Boost ─────────────────────────────────────────────────────────────────────
async function loadBoost() {
    const res = await fetchJSON('/api/boost');
    const el = document.getElementById('boostRaw');
    if (!res || !res.data || Object.keys(res.data).length === 0) {
        el.textContent = 'No boost state data available.';
        return;
    }
    el.textContent = JSON.stringify(res.data, null, 2);
}

// ── Settings ─────────────────────────────────────────────────────────────────
async function loadSettings() {
    const res = await fetchJSON('/api/config');
    if (!res || !res.data) return;
    const d = res.data;
    setText('cfgPrefix', d.prefix);
    setText('cfgAutoDelete', d.auto_delete_enabled ? 'Enabled' : 'Disabled');
    setText('cfgDelay', d.auto_delete_delay + 's');
    setText('cfgStatus', d.status || 'online');

    const tog = document.getElementById('newAutoDeleteToggle');
    if (tog) tog.value = d.auto_delete_enabled ? 'true' : 'false';
}

function showSettingsMsg(msg, ok) {
    const el = document.getElementById('settingsMsg');
    if (!el) return;
    el.textContent = msg;
    el.className = 'settings-msg ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; el.className = 'settings-msg'; }, 3000);
}

async function applyPrefix() {
    const val = document.getElementById('newPrefixInput').value.trim();
    if (!val) { showSettingsMsg('Enter a prefix first.', false); return; }
    const res = await postJSON('/api/config', { prefix: val });
    if (res && res.ok) {
        showSettingsMsg('Prefix updated to: ' + res.data.prefix, true);
        loadSettings();
        loadOverview();
    } else {
        showSettingsMsg('Failed to update prefix.', false);
    }
}

async function applyDelay() {
    const val = parseInt(document.getElementById('newDelayInput').value);
    if (isNaN(val) || val < 1) { showSettingsMsg('Enter a valid delay (1–600).', false); return; }
    const res = await postJSON('/api/config', { auto_delete_delay: val });
    if (res && res.ok) {
        showSettingsMsg('Delay updated to: ' + res.data.auto_delete_delay + 's', true);
        loadSettings();
    } else {
        showSettingsMsg('Failed to update delay.', false);
    }
}

async function applyAutoDelete() {
    const val = document.getElementById('newAutoDeleteToggle').value === 'true';
    const res = await postJSON('/api/config', { auto_delete_enabled: val });
    if (res && res.ok) {
        showSettingsMsg('Auto-delete ' + (val ? 'enabled' : 'disabled'), true);
        loadSettings();
    } else {
        showSettingsMsg('Failed to update.', false);
    }
}

// ── Section router ────────────────────────────────────────────────────────────
function loadSection(name) {
    if (name === 'overview')  loadOverview();
    if (name === 'commands')  loadCommands();
    if (name === 'analytics') loadAnalytics();
    if (name === 'history')   loadHistory();
    if (name === 'boost')     loadBoost();
    if (name === 'rpc')       loadRpc();
    if (name === 'presence')  loadPresence();
    if (name === 'hosted')    loadHosted();
    if (name === 'logs')      loadLogs();
    if (name === 'users')     loadDashUsers();
    if (name === 'settings')  loadSettings();
}

// ── RPC ───────────────────────────────────────────────────────────────────────
async function loadRpc() {
    const res = await fetchJSON('/api/rpc');
    if (!res) return;
    setText('rpcActive', res.active ? 'Yes' : 'No');
    setText('rpcMode', res.mode || 'none');
    const act = res.activity || {};
    setText('rpcName', act.name || '—');
    setText('rpcDetails', act.details || '—');
}

function showRpcMsg(msg, ok) {
    const el = document.getElementById('rpcMsg');
    if (!el) return;
    el.textContent = msg;
    el.className = 'settings-msg ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; el.className = 'settings-msg'; }, 3000);
}

async function applyRpc() {
    const type = parseInt(document.getElementById('rpcType').value) || 0;
    const name = document.getElementById('rpcNameInput').value.trim();
    const details = document.getElementById('rpcDetailsInput').value.trim();
    const state = document.getElementById('rpcStateInput').value.trim();
    if (!name) { showRpcMsg('Name is required.', false); return; }
    const activity = { type, name };
    if (details) activity.details = details;
    if (state) activity.state = state;
    const res = await postJSON('/api/rpc', { action: 'set', activity });
    if (res && res.ok) {
        showRpcMsg('RPC set.', true);
        loadRpc();
    } else {
        showRpcMsg((res && res.error) || 'Failed to set RPC.', false);
    }
}

async function clearRpc() {
    const res = await postJSON('/api/rpc', { action: 'stop' });
    if (res && res.ok) {
        showRpcMsg('RPC cleared.', true);
        loadRpc();
    } else {
        showRpcMsg('Failed to stop RPC.', false);
    }
}

// ── Presence ───────────────────────────────────────────────────────────────────
async function loadPresence() {
    const [presRes, afkRes] = await Promise.all([
        fetchJSON('/api/presence'),
        fetchJSON('/api/afk'),
    ]);
    if (presRes) setText('presenceStatus', presRes.status || '—');
    if (afkRes) {
        setText('afkStatus', afkRes.active ? ('AFK — ' + (afkRes.message || '')) : 'Not AFK');
    }
}

function showPresenceMsg(id, msg, ok) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg;
    el.className = 'settings-msg ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; el.className = 'settings-msg'; }, 3000);
}

async function setPresence(status) {
    const res = await postJSON('/api/presence', { status });
    if (res && res.ok) {
        showPresenceMsg('presenceMsg', 'Status set to: ' + status, true);
        loadPresence();
        loadOverview();
    } else {
        showPresenceMsg('presenceMsg', (res && res.error) || 'Failed to set status.', false);
    }
}

async function toggleAfk(action) {
    const message = document.getElementById('afkMessageInput').value.trim() || 'AFK';
    const res = await postJSON('/api/afk', { action, message });
    if (res && res.ok) {
        showPresenceMsg('afkMsg', res.active ? ('AFK enabled: ' + (res.message || '')) : 'AFK cleared.', true);
        loadPresence();
    } else {
        showPresenceMsg('afkMsg', (res && res.error) || 'AFK system unavailable.', false);
    }
}

// ── Hosted ────────────────────────────────────────────────────────────────────
async function loadHosted() {
    const res = await fetchJSON('/api/hosted');
    if (!res) return;
    setText('hostedTotal', res.total ?? 0);
    setText('hostedActive', res.active_count ?? 0);
    const tbody = document.getElementById('hostedBody');
    if (!tbody) return;
    if (!res.hosted || res.hosted.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No hosted users</td></tr>';
        return;
    }
    tbody.innerHTML = res.hosted.map(u =>
        `<tr>
            <td class="mono">${esc(u.token_id)}</td>
            <td>${esc(u.username)}</td>
            <td class="mono">${esc(u.owner)}</td>
            <td class="mono">${esc(u.prefix)}</td>
            <td><span class="badge ${u.active ? 'badge-ok' : 'badge-off'}">${u.active ? 'Active' : 'Inactive'}</span></td>
        </tr>`
    ).join('');
}

// ── Dashboard Users (login management) ───────────────────────────────────────
async function loadDashUsers() {
    const res = await fetchJSON('/api/dash/users');
    if (!res) return;
    setText('dashUsersTotal', res.total ?? 0);
    const tbody = document.getElementById('dashUsersBody');
    if (!tbody) return;
    if (!res.users || res.users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-row">No dashboard users registered</td></tr>';
        return;
    }
    tbody.innerHTML = res.users.map(u =>
        `<tr>
            <td class="mono">${esc(u.user_id)}</td>
            <td>${esc(u.username)}</td>
            <td class="mono">${esc(u.instance_id)}</td>
            <td><button class="btn-action btn-danger" onclick="removeDashUser('${esc(u.user_id)}')" style="padding:4px 10px;font-size:11px">Remove</button></td>
        </tr>`
    ).join('');
}

function showDashUsersMsg(msg, ok) {
    const el = document.getElementById('dashUsersMsg');
    if (!el) return;
    el.textContent = msg;
    el.className = 'settings-msg ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; el.className = 'settings-msg'; }, 4000);
}

async function addDashUser() {
    const uid = document.getElementById('newDashUserId').value.trim();
    const uname = document.getElementById('newDashUsername').value.trim();
    const pw = document.getElementById('newDashPassword').value;
    if (!uid || !pw) { showDashUsersMsg('User ID and password required.', false); return; }
    const res = await postJSON('/api/dash/register', { user_id: uid, username: uname || uid, password: pw });
    if (res && res.ok) {
        showDashUsersMsg(`Login created for ${uid}`, true);
        document.getElementById('newDashPassword').value = '';
        loadDashUsers();
    } else {
        showDashUsersMsg((res && res.error) || 'Failed.', false);
    }
}

async function removeDashUser(uid) {
    try {
        const r = await fetch(`/api/dash/register/${uid}`, { method: 'DELETE' });
        const res = await r.json();
        if (res && res.ok) { showDashUsersMsg(`Removed ${uid}`, true); loadDashUsers(); }
        else showDashUsersMsg((res && res.error) || 'Failed.', false);
    } catch(e) { showDashUsersMsg('Request failed.', false); }
}

// ── Logs ──────────────────────────────────────────────────────────────────────
async function loadLogs() {
    const container = document.getElementById('logContainer');
    if (!container) return;
    container.innerHTML = '<div class="log-loading">Loading...</div>';
    const res = await fetchJSON('/api/logs?lines=100');
    if (!res || !res.lines) {
        container.innerHTML = '<div class="log-loading">Failed to load logs.</div>';
        return;
    }
    if (res.lines.length === 0) {
        container.innerHTML = '<div class="log-loading">No log entries found.</div>';
        return;
    }
    container.innerHTML = res.lines.map(l => {
        const cls = l.includes('[ERROR]') || l.includes('[AUTH-ERROR]') ? 'log-error'
                  : l.includes('[WARNING]') ? 'log-warn'
                  : l.includes('[RPC]') ? 'log-rpc'
                  : l.includes('[GATEWAY]') ? 'log-gateway'
                  : '';
        return `<div class="log-line ${cls}">${esc(l)}</div>`;
    }).join('');
    // scroll to bottom
    container.scrollTop = container.scrollHeight;
}

// ── Refresh button ────────────────────────────────────────────────────────────
document.getElementById('refreshBtn').addEventListener('click', () => {
    const active = document.querySelector('.nav-item.active');
    if (active) loadSection(active.dataset.section);
});

// ── Auto-refresh every 30s ────────────────────────────────────────────────────
setInterval(() => {
    const active = document.querySelector('.nav-item.active');
    if (active) loadSection(active.dataset.section);
}, 30000);

// ── Initial load ──────────────────────────────────────────────────────────────
loadOverview();
