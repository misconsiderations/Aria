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
        // strip emoji from title — take last text node
        const rawText = item.childNodes[item.childNodes.length - 1].textContent.trim();
        pageTitle.textContent = rawText;
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
    const badge = document.getElementById('cmdBadge');
    if (badge) badge.textContent = list.length + (list.length === 1 ? ' command' : ' commands');
    if (!tbody) return;
    if (!list || list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="empty-row">No commands found</td></tr>';
        return;
    }
    tbody.innerHTML = list.map(c =>
        `<tr>
            <td class="cmd-name">${esc(c.name)}</td>
            <td class="cmd-aliases">${c.aliases && c.aliases.length ? esc(c.aliases.join(', ')) : '<span style="color:var(--muted)">—</span>'}</td>
            <td style="color:var(--muted)">${esc(c.description || '—')}</td>
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

    const wrap = document.getElementById('topCommandsBody');
    if (!wrap) return;
    if (!d.top_commands || d.top_commands.length === 0) {
        wrap.innerHTML = '<div class="empty-row" style="padding:32px 20px">No command data yet</div>';
        return;
    }
    const maxCount = d.top_commands[0].count || 1;
    wrap.innerHTML = d.top_commands.map((c, i) => {
        const pct = Math.round((c.count / maxCount) * 100);
        const rankClass = i === 0 ? 'top-cmd-rank gold' : 'top-cmd-rank';
        return `<div class="top-cmd-row">
            <div class="${rankClass}">${i + 1}</div>
            <div class="top-cmd-name">${esc(c.name)}</div>
            <div class="top-cmd-bar-wrap"><div class="top-cmd-bar" style="width:${pct}%"></div></div>
            <div class="top-cmd-count">${c.count}</div>
        </div>`;
    }).join('');
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
    const res = await fetchJSON('/api/history');
    if (!res || !res.data) return;
    const d = res.data;
    const badge = document.getElementById('historyBadge');
    if (badge) badge.textContent = (d.total ?? 0) + ' entries';

    const feed = document.getElementById('historyFeed');
    if (!feed) return;
    if (!d.entries || d.entries.length === 0) {
        feed.innerHTML = '<div class="log-loading">No history entries yet</div>';
        return;
    }
    feed.innerHTML = d.entries.slice().reverse().map(e => {
        if (typeof e === 'object' && e !== null) {
            const cmd   = e.command || e.cmd || e.name || '';
            const guild = e.guild_id || e.server || '';
            const chan  = e.channel_id || e.channel || '';
            const ts    = e.timestamp || e.time || '';
            const status = e.status || e.result || '';
            const statusBadge = status === 'success' || status === 'ok'
                ? '<span class="badge badge-ok">ok</span>'
                : status ? `<span class="badge badge-warn">${esc(status)}</span>` : '';
            return `<div class="history-item">
                <div class="history-dot"></div>
                <div class="history-content">
                    <span class="history-cmd">${esc(cmd || '(unknown)')}</span>
                    ${statusBadge}
                    <div class="history-meta">${[
                        guild ? '🏠 ' + guild : '',
                        chan  ? '# ' + chan   : '',
                        ts   ? '🕐 ' + ts    : ''
                    ].filter(Boolean).join(' &nbsp;·&nbsp; ')}</div>
                </div>
            </div>`;
        }
        return `<div class="history-item"><div class="history-dot"></div><div class="history-content"><div class="history-raw">${esc(String(e))}</div></div></div>`;
    }).join('');
}

// ── Boost ─────────────────────────────────────────────────────────────────────
let _boostRawShown = false;

function toggleBoostRaw() {
    _boostRawShown = !_boostRawShown;
    const pre = document.getElementById('boostRawPre');
    const btn = document.getElementById('boostRawBtn');
    if (pre) pre.style.display = _boostRawShown ? 'block' : 'none';
    if (btn) btn.textContent = _boostRawShown ? 'Hide Raw JSON' : 'Show Raw JSON';
}

const BOOST_LABELS = {
    guild_id:        'Guild ID',
    guild_name:      'Guild',
    boost_count:     'Boosts Applied',
    slots_total:     'Total Slots',
    slots_remaining: 'Slots Remaining',
    nitro_type:      'Nitro Type',
    active:          'Active',
    started_at:      'Started',
    ends_at:         'Expires',
    token_count:     'Tokens Used',
};

async function loadBoost() {
    const res = await fetchJSON('/api/boost');
    const cards = document.getElementById('boostCards');
    const pre   = document.getElementById('boostRawPre');
    if (!res || !res.data || Object.keys(res.data).length === 0) {
        if (cards) cards.innerHTML = '<div class="log-loading" style="grid-column:1/-1">No boost state data available.</div>';
        return;
    }
    const data = res.data;
    // populate pretty cards
    if (cards) {
        const entries = Object.entries(data);
        cards.innerHTML = entries.map(([k, v]) => {
            const label = BOOST_LABELS[k] || k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            const display = v === null || v === undefined ? '—'
                          : typeof v === 'boolean' ? (v ? '✅ Yes' : '❌ No')
                          : typeof v === 'object'  ? JSON.stringify(v)
                          : String(v);
            return `<div class="boost-card">
                <div class="boost-key">${esc(label)}</div>
                <div class="boost-val">${esc(display)}</div>
            </div>`;
        }).join('');
    }
    // populate raw
    if (pre) pre.textContent = JSON.stringify(data, null, 2);
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
const RPC_TYPE_LABELS = ['Playing', 'Streaming', 'Listening to', 'Watching', '', 'Competing in'];

async function loadRpc() {
    const res = await fetchJSON('/api/rpc');
    if (!res) return;
    const active = res.active || false;
    const act    = res.activity || {};

    const badge = document.getElementById('rpcActiveBadge');
    if (badge) {
        badge.textContent = active ? 'Active' : 'Inactive';
        badge.className = 'badge ' + (active ? 'badge-ok' : 'badge-off');
    }
    const previewName = document.getElementById('rpcPreviewName');
    if (previewName) previewName.textContent = active ? (act.name || '—') : 'No RPC set';
    const previewDetails = document.getElementById('rpcPreviewDetails');
    if (previewDetails) previewDetails.textContent = act.details || (active ? '—' : '');
    const previewState = document.getElementById('rpcPreviewState');
    if (previewState) previewState.textContent = act.state || '';
    const previewType = document.getElementById('rpcPreviewType');
    if (previewType) {
        const typeNum = act.type != null ? act.type : -1;
        previewType.textContent = typeNum >= 0 ? (RPC_TYPE_LABELS[typeNum] || 'Activity') : 'inactive';
    }
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
const PRESENCE_BADGES = {
    online:    'badge-ok',
    idle:      'badge-warn',
    dnd:       'badge-pink',
    invisible: 'badge-off',
};

async function loadPresence() {
    const [presRes, afkRes] = await Promise.all([
        fetchJSON('/api/presence'),
        fetchJSON('/api/afk'),
    ]);
    if (presRes) {
        const status = presRes.status || 'unknown';
        const badge = document.getElementById('presenceBadge');
        if (badge) {
            badge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
            badge.className = 'badge ' + (PRESENCE_BADGES[status] || 'badge-off');
        }
    }
    if (afkRes) {
        const afkBadge = document.getElementById('afkBadge');
        if (afkBadge) {
            afkBadge.textContent = afkRes.active ? 'AFK' : 'Off';
            afkBadge.className = 'badge ' + (afkRes.active ? 'badge-warn' : 'badge-off');
        }
        const afkInput = document.getElementById('afkMessageInput');
        if (afkInput && afkRes.message) afkInput.placeholder = afkRes.message;
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
    const badge = document.getElementById('hostedBadge');
    if (badge) badge.textContent = res.total ?? 0;
    const tbody = document.getElementById('hostedBody');
    if (!tbody) return;
    if (!res.hosted || res.hosted.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-row">No hosted users found</td></tr>';
        return;
    }
    tbody.innerHTML = res.hosted.map(u =>
        `<tr>
            <td class="cmd-name" style="font-size:11px">${esc(u.token_id || '—')}</td>
            <td>${esc(u.username || '—')}</td>
            <td class="cmd-aliases">${esc(u.owner || '—')}</td>
            <td class="cmd-aliases">${esc(u.prefix || '—')}</td>
            <td><span class="badge ${u.active ? 'badge-ok' : 'badge-off'}">${u.active ? '● Active' : '○ Inactive'}</span></td>
        </tr>`
    ).join('');
}

// ── Dashboard Users (login management) ───────────────────────────────────────
async function loadDashUsers() {
    const res = await fetchJSON('/api/dash/users');
    if (!res) return;
    const count = res.total ?? 0;
    const el = document.getElementById('dashUsersTotal');
    if (el) el.textContent = count + (count === 1 ? ' account' : ' accounts');
    const tbody = document.getElementById('dashUsersBody');
    if (!tbody) return;
    if (!res.users || res.users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-row">No dashboard accounts yet</td></tr>';
        return;
    }
    tbody.innerHTML = res.users.map(u =>
        `<tr>
            <td class="cmd-aliases">${esc(u.user_id)}</td>
            <td style="font-weight:600">${esc(u.username)}</td>
            <td class="cmd-aliases">${esc(u.instance_id || '—')}</td>
            <td><button class="btn btn-danger-soft" onclick="removeDashUser('${esc(u.user_id)}')" style="padding:4px 12px;font-size:11px">Remove</button></td>
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
    const countEl   = document.getElementById('logLineCount');
    const cmdFeed   = document.getElementById('commandExecFeed');
    const sniperFeed = document.getElementById('sniperFeed');
    const gatewayFeed = document.getElementById('gatewayFeed');
    if (!container) return;
    container.innerHTML = '<div class="log-loading">Fetching logs…</div>';
    const res = await fetchJSON('/api/logs?lines=100');
    if (!res || !res.lines) {
        container.innerHTML = '<div class="log-loading">Failed to load logs.</div>';
        return;
    }

    const summary = res.summary || {};
    const connectedUser = summary.connected_user || {};
    setText('logsConnectedUser', connectedUser.username || '—');
    setText('logsConnectedUserId', connectedUser.user_id || '—');
    setText('logsCommandTotal', summary.command_total ?? 0);
    setText('logsCommandEvents', summary.command_events ?? 0);
    setText('logsSniperEvents', summary.sniper_events ?? 0);
    setText('logsGatewayEvents', summary.gateway_events ?? 0);
    setText('logsErrorEvents', summary.error_events ?? 0);

    const events = res.events || {};
    const commandEvents = events.commands || [];
    const sniperEvents = events.snipers || [];
    const gatewayEvents = events.gateway || [];
    const errorEvents = events.errors || [];

    if (cmdFeed) {
        if (!commandEvents.length) {
            cmdFeed.innerHTML = '<div class="log-loading">No command execution logs yet.</div>';
        } else {
            cmdFeed.innerHTML = commandEvents.slice().reverse().map(e => {
                const duration = e.duration_ms != null ? `${Math.round(e.duration_ms)}ms` : '—';
                return `<div class="history-item">
                    <div class="history-dot"></div>
                    <div class="history-content">
                        <span class="history-cmd">${esc(e.command || '(unknown)')}</span>
                        <span class="badge badge-ok">#${esc(String(e.number || '0'))}</span>
                        <div class="history-meta">${[
                            e.user ? '👤 ' + esc(e.user) : '',
                            e.guild ? '🏠 ' + esc(e.guild) : '',
                            e.time ? '🕐 ' + esc(e.time) : '',
                            '⚡ ' + esc(duration),
                        ].filter(Boolean).join(' &nbsp;·&nbsp; ')}</div>
                    </div>
                </div>`;
            }).join('');
        }
    }

    if (sniperFeed) {
        if (!sniperEvents.length) {
            sniperFeed.innerHTML = '<div class="log-loading">No sniper logs yet.</div>';
        } else {
            sniperFeed.innerHTML = sniperEvents.slice().reverse().map(e => `
                <div class="history-item">
                    <div class="history-dot"></div>
                    <div class="history-content">
                        <div class="history-raw">${esc(e.raw || '')}</div>
                    </div>
                </div>
            `).join('');
        }
    }

    if (gatewayFeed) {
        const merged = gatewayEvents.concat(errorEvents).slice(-100);
        if (!merged.length) {
            gatewayFeed.innerHTML = '<div class="log-loading">No gateway/error logs yet.</div>';
        } else {
            gatewayFeed.innerHTML = merged.slice().reverse().map(e => {
                const lo = String(e.raw || '').toLowerCase();
                const badge = (lo.includes('error') || lo.includes('exception') || lo.includes('failed'))
                    ? '<span class="badge badge-pink">error</span>'
                    : '<span class="badge badge-warn">gateway</span>';
                return `<div class="history-item">
                    <div class="history-dot"></div>
                    <div class="history-content">
                        ${badge}
                        <div class="history-raw">${esc(e.raw || '')}</div>
                    </div>
                </div>`;
            }).join('');
        }
    }

    if (res.lines.length === 0) {
        container.innerHTML = '<div class="log-loading">No log output yet.</div>';
        return;
    }
    if (countEl) countEl.textContent = res.lines.length + ' lines';
    container.innerHTML = res.lines.map(l => {
        const lo = l.toLowerCase();
        const cls = (lo.includes('[error]') || lo.includes('[auth-error]') || lo.includes('traceback') || lo.includes('exception'))
                  ? 'log-error'
                  : (lo.includes('[warning]') || lo.includes('[warn]'))
                  ? 'log-warn'
                  : lo.includes('[rpc]')
                  ? 'log-rpc'
                  : lo.includes('[gateway]')
                  ? 'log-gateway'
                  : (lo.includes('success') || lo.includes('connected') || lo.includes('ready'))
                  ? 'log-success'
                  : '';
        return `<div class="log-line ${cls}">${esc(l)}</div>`;
    }).join('');
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
