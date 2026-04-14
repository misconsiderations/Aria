// ── User Profile Loader ──
async function loadUserProfile() {
    fetchJSON('/api/max/user-profile').then(data => {
        if (!data || !data.ok) return;
        setText('profileUsername', data.username || '—');
        setText('profileUserId', data.user_id || '—');
        setText('profileStatus', data.status || '—');
        setText('profileCustomStatus', data.custom_status || '');
        setText('profileRPC', data.rpc || '');
        const avatar = document.getElementById('profileAvatar');
        if (avatar && data.avatar_url) avatar.src = data.avatar_url;
        // Badges
        const badgeWrap = document.getElementById('profileBadges');
        if (badgeWrap) {
            badgeWrap.innerHTML = '';
            (data.badges || []).forEach(badge => {
                const span = document.createElement('span');
                span.className = 'profile-badge';
                span.title = badge.name;
                span.innerHTML = badge.icon;
                badgeWrap.appendChild(span);
            });
        }
    });
}

window.addEventListener('DOMContentLoaded', () => {
    loadUserProfile();
});
// ── Sidebar Toggle (Mobile) ──
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebar = document.querySelector('.sidebar');
const mainContent = document.querySelector('.main-content');
if (sidebarToggle && sidebar && mainContent) {
    sidebarToggle.addEventListener('change', () => {
        if (sidebarToggle.checked) {
            sidebar.style.left = '-240px';
            mainContent.style.marginLeft = '0';
        } else {
            sidebar.style.left = '';
            mainContent.style.marginLeft = '';
        }
    });
}

// ── Overview Quick Stats Loader ──
async function loadOverviewQuick() {
    // Version info
    fetchJSON('/api/max/version-info').then(data => {
        setText('quickBotVersion', data?.version || '—');
        setText('quickGit', data?.git || '—');
    });
    // Python env
    fetchJSON('/api/max/python-env').then(data => {
        setText('quickPython', data?.python || '—');
        setText('quickPlatform', data?.platform || '—');
    });
    // MOTD
    fetchJSON('/api/max/motd').then(data => {
        setText('quickMotd', data?.motd || '—');
    });
    // Quote
    fetchJSON('/api/max/quote').then(data => {
        setText('quickQuote', data?.quote || '—');
    });
}

window.addEventListener('DOMContentLoaded', () => {
    loadOverviewQuick();
});
// ── Navigation ────────────────────────────────────────────────────────────────
const navItems = document.querySelectorAll('.nav-item');
const sections = document.querySelectorAll('.section');
const pageTitle = document.getElementById('pageTitle');
let _meProfile = null;
const _liveOverviewState = { lastCount: null, lastTs: null };

navItems.forEach(item => {
    item.addEventListener('click', () => {
        if (item.dataset.hiddenByRole === 'true') return;
        const target = item.dataset.section;
        navItems.forEach(n => n.classList.remove('active'));
        sections.forEach(s => s.classList.remove('active'));
        item.classList.add('active');
        const targetSection = document.getElementById('section-' + target);
        if (!targetSection) return;
        targetSection.classList.add('active');
        // strip emoji from title — take last text node
        const rawText = item.childNodes[item.childNodes.length - 1].textContent.trim();
        pageTitle.textContent = rawText;
        loadSection(target);
        trackDashboardAction('navigate', `Opened ${target}`);
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

function fmtTs(ts) {
    const n = Number(ts || 0);
    if (!n) return '—';
    const d = new Date(n * 1000);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString();
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
    updateUptimeRing(d.uptime);
    setText('commandCount', d.command_count);
    setText('commandsRegistered', d.commands_registered);
    setText('connectionStatus', d.connected ? 'Online' : 'Offline');
    setText('botStatus', d.status || 'online');
    setText('clientType', d.client_type || 'mobile');
    setText('clientOptions', (d.available_clients || []).join(', ') || 'web, desktop, mobile, vr');
    setText('uiVersion', d.ui_version || 'v2');
    updateLiveOverviewMetrics(d);

    const avatar = document.getElementById('userAvatar');
    if (avatar) {
        avatar.onerror = () => {
            avatar.onerror = null;
            avatar.src = '/static/images/aria-favicon.svg';
        };
        avatar.src = d.avatar_url || '/static/images/aria-favicon.svg';
    }
    const profileHint = document.getElementById('profileHint');
    if (profileHint) profileHint.textContent = d.user_id && d.user_id !== '—' ? `UID ${d.user_id}` : 'Profile';

    await loadClientSwitcher(d);

    // Fetch and render sparkline
    updateSparkline();

    // Fetch and render activity toasts
    updateToastFeed();
}

// ── Uptime Ring ────────────────────────────────────────────────────────────
function updateUptimeRing(uptimeStr) {
    // Parse uptime string like "1h 23m 45s"
    let total = 0;
    if (typeof uptimeStr === 'string') {
        const m = uptimeStr.match(/(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?/);
        if (m) {
            total += (parseInt(m[1]||'0',10)||0) * 3600;
            total += (parseInt(m[2]||'0',10)||0) * 60;
            total += (parseInt(m[3]||'0',10)||0);
        }
    }
    // Animate ring: 24h = full circle
    const max = 24*3600;
    const pct = Math.min(1, total / max);
    const offset = 151 - Math.round(151 * pct);
    const fg = document.querySelector('.uptime-fg');
    if (fg) fg.setAttribute('stroke-dashoffset', offset);
}

// ── Sparkline Chart ─────────────────────────────────────────────────────---
async function updateSparkline() {
    const canvas = document.getElementById('sparkline');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0,0,canvas.width,canvas.height);
    // Fetch history
    const res = await fetchJSON('/api/history');
    let entries = (res && res.data && res.data.entries) || [];
    // Group by minute
    const now = Date.now();
    const buckets = Array(20).fill(0);
    entries.forEach(e => {
        let ts = Number(e.timestamp || 0);
        if (!ts || ts > 1e12) ts = Math.floor(ts/1000); // handle ms
        const minAgo = Math.floor((now/1000 - ts)/60);
        if (minAgo >= 0 && minAgo < 20) buckets[19-minAgo]++;
    });
    // Draw sparkline
    const maxVal = Math.max(1, ...buckets);
    ctx.beginPath();
    for (let i=0; i<buckets.length; ++i) {
        const x = 7 + i*6.5;
        const y = 32 - (buckets[i]/maxVal)*28;
        if (i===0) ctx.moveTo(x,y);
        else ctx.lineTo(x,y);
    }
    ctx.strokeStyle = '#8b5cf6';
    ctx.lineWidth = 2.2;
    ctx.shadowColor = '#ec4899';
    ctx.shadowBlur = 4;
    ctx.stroke();
    ctx.shadowBlur = 0;
    // Fill area
    ctx.lineTo(7+19*6.5,32);
    ctx.lineTo(7,32);
    ctx.closePath();
    ctx.globalAlpha = 0.18;
    ctx.fillStyle = '#8b5cf6';
    ctx.fill();
    ctx.globalAlpha = 1;
}

// ── Toast Feed ─────────────────────────────────────────────────────────---
async function updateToastFeed() {
    const feed = document.getElementById('toastFeed');
    if (!feed) return;
    const res = await fetchJSON('/api/dash/activity');
    let timeline = (res && res.timeline) || [];
    feed.innerHTML = '';
    timeline.slice(-8).reverse().forEach(ev => {
        const t = document.createElement('div');
        t.className = 'toast';
        t.textContent = `[${fmtTs(ev.ts)}] ${ev.action}${ev.details ? ': '+ev.details : ''}`;
        feed.appendChild(t);
    });
}

// ── Live Metrics Refresh ─────────────────────────────────────────────────-
setInterval(() => {
    if (document.getElementById('section-overview')?.classList.contains('active')) {
        updateSparkline();
        updateToastFeed();
        // Optionally, update uptime ring
        const uptime = document.getElementById('uptime');
        if (uptime) updateUptimeRing(uptime.textContent);
    }
}, 7000);

function animateMetricValue(id, newVal, decimals = 0) {
    const el = document.getElementById(id);
    if (!el) return;
    const prev = Number(el.dataset.value || 0);
    const next = Number(newVal || 0);
    const duration = 420;
    const start = performance.now();
    const isInt = decimals === 0;

    function tick(now) {
        const p = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        const cur = prev + (next - prev) * eased;
        el.textContent = isInt ? String(Math.round(cur)) : cur.toFixed(decimals);
        if (p < 1) requestAnimationFrame(tick);
        else el.dataset.value = String(next);
    }
    requestAnimationFrame(tick);
}

function updateLiveOverviewMetrics(botData) {
    const cmdCount = Number(botData.command_count || 0);
    const now = Date.now();

    let delta = 0;
    let perMin = 0;
    if (_liveOverviewState.lastCount != null && _liveOverviewState.lastTs != null) {
        delta = Math.max(0, cmdCount - _liveOverviewState.lastCount);
        const mins = Math.max((now - _liveOverviewState.lastTs) / 60000, 0.001);
        perMin = delta / mins;
    }

    _liveOverviewState.lastCount = cmdCount;
    _liveOverviewState.lastTs = now;

    animateMetricValue('liveCmdRate', perMin, 1);
    animateMetricValue('liveCmdDelta', delta, 0);

    const rateBar = document.getElementById('liveCmdRateBar');
    const deltaBar = document.getElementById('liveCmdDeltaBar');
    if (rateBar) rateBar.style.width = Math.min(100, Math.round(perMin * 8)) + '%';
    if (deltaBar) deltaBar.style.width = Math.min(100, Math.round(delta * 12)) + '%';

    const pulse = document.getElementById('livePulse');
    const pulseLabel = document.getElementById('livePulseLabel');
    if (pulse) pulse.classList.toggle('live', !!botData.connected);
    if (pulseLabel) pulseLabel.textContent = botData.connected ? 'live stream' : 'offline';

    const clock = document.getElementById('liveClock');
    if (clock) {
        const d = new Date();
        const hh = String(d.getHours()).padStart(2, '0');
        const mm = String(d.getMinutes()).padStart(2, '0');
        const ss = String(d.getSeconds()).padStart(2, '0');
        clock.textContent = `${hh}:${mm}:${ss}`;
    }
}

async function loadClientSwitcher(overviewData = null) {
    const select = document.getElementById('clientTypeSelect');
    if (!select) return;

    let data = overviewData;
    if (!data) {
        const res = await fetchJSON('/api/client');
        if (!res || !res.ok) return;
        data = res;
    }

    const current = String(data.client_type || 'mobile');
    const available = Array.isArray(data.available_clients) && data.available_clients.length
        ? data.available_clients
        : ['web', 'desktop', 'mobile', 'vr'];

    select.innerHTML = available.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
    select.value = available.includes(current) ? current : available[0];
}

function showClientMsg(msg, ok) {
    const el = document.getElementById('clientMsg');
    if (!el) return;
    el.textContent = msg;
    el.className = 'settings-msg ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; el.className = 'settings-msg'; }, 2800);
}

async function applyClientType() {
    const select = document.getElementById('clientTypeSelect');
    if (!select) return;
    const clientType = String(select.value || '').trim();
    if (!clientType) return;

    const res = await postJSON('/api/client', { client_type: clientType });
    if (res && res.ok) {
        showClientMsg(`Client switched to ${res.client_type}`, true);
        trackDashboardAction('client_switch', `Switched client to ${res.client_type}`);
        loadOverview();
    } else {
        showClientMsg((res && res.error) || 'Failed to switch client', false);
    }
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
            const user  = e.user || e.author || e.author_id || '';
            const guild = e.guild_id || e.server || '';
            const chan  = e.channel_id || e.channel || '';
            const ts    = e.timestamp || e.time || '';
            const status = e.status || e.result || '';
            const dur = e.duration_ms != null ? `${Math.round(Number(e.duration_ms) || 0)}ms` : '';
            const statusBadge = status === 'success' || status === 'ok'
                ? '<span class="badge badge-ok">ok</span>'
                : status ? `<span class="badge badge-warn">${esc(status)}</span>` : '';
            return `<div class="history-item">
                <div class="history-dot"></div>
                <div class="history-content">
                    <span class="history-cmd">${esc(cmd || '(unknown)')}</span>
                    ${statusBadge}
                    <div class="history-meta">${[
                        user  ? '👤 ' + user : '',
                        guild ? '🏠 ' + guild : '',
                        chan  ? '# ' + chan   : '',
                        ts   ? '🕐 ' + ts    : '',
                        dur  ? '⚡ ' + dur   : ''
                    ].filter(Boolean).join(' &nbsp;·&nbsp; ')}</div>
                </div>
            </div>`;
        }
        return `<div class="history-item"><div class="history-dot"></div><div class="history-content"><div class="history-raw">${esc(String(e))}</div></div></div>`;
    }).join('');
}

// ── Boost ─────────────────────────────────────────────────────────────────────

const BOOST_LABELS = {
    boost_status:    'Boost Status',
    tracked_servers: 'Tracked Servers',
    boosted_servers: 'Boosted Servers',
    total_boosts:    'Total Boosts',
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
    if (!res || !res.data || Object.keys(res.data).length === 0) {
        if (cards) cards.innerHTML = '<div class="log-loading" style="grid-column:1/-1">No boost state data available.</div>';
        return;
    }
    const data = res.data;
    const live = data.live || {};
    const serverBoosts = data.server_boosts || {};
    const boostValues = Object.values(serverBoosts).map(v => Number(v) || 0);
    const trackedServers = Number(live.tracked_servers ?? boostValues.length);
    const boostedServers = Number(live.boosted_servers ?? boostValues.filter(v => v > 0).length);
    const totalBoosts = Number(live.total_boosts ?? boostValues.reduce((a, b) => a + b, 0));
    const status = String(live.status || (totalBoosts > 0 ? 'active' : 'idle'));

    // populate pretty cards
    if (cards) {
        const entries = [
            ['boost_status', status.toUpperCase()],
            ['tracked_servers', trackedServers],
            ['boosted_servers', boostedServers],
            ['total_boosts', totalBoosts],
            ['total_slots', live.total_slots ?? '—'],
            ['slots_available', live.slots_available ?? '—'],
            ['slots_used', live.slots_used ?? '—'],
            ['slots_cooldown', live.slots_cooldown ?? '—'],
            ...Object.entries(data),
        ].filter(([k]) => k !== 'server_boosts' && k !== 'live');
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
        trackDashboardAction('config_prefix', `Updated prefix to ${res.data.prefix}`);
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
        trackDashboardAction('config_delay', `Updated auto-delete delay to ${res.data.auto_delete_delay}s`);
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
        trackDashboardAction('config_autodelete', `Set auto-delete ${val ? 'enabled' : 'disabled'}`);
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
    if (name === 'system')    loadSystemStats();
    if (name === 'cmdbreakdown') loadCommandBreakdown();
    if (name === 'errors')    loadErrorLogs();
    if (name === 'leaderboard') loadLeaderboard();
    if (name === 'serverinfo') loadServerInfo();
    if (name === 'activitymap') loadActivityMap();
    if (name === 'notifications') loadNotifications();
    if (name === 'advanced-analytics') loadAdvancedAnalytics();
    if (name === 'widgets')   loadWidgets();
}

// ── Maximalist Dashboard Panel Loaders ─────────────────────────────────────
async function loadSystemStats() {
    const res = await fetchJSON('/api/max/system-stats');
    setText('cpuUsage', res && res.cpu != null ? res.cpu + '%' : '—');
    setText('ramUsage', res && res.ram != null ? res.ram + '%' : '—');
    setText('diskUsage', res && res.disk != null ? res.disk + '%' : '—');
    setText('netUsage', res && res.net ? `↑${Math.round(res.net.sent/1024)}KB ↓${Math.round(res.net.recv/1024)}KB` : '—');
    // Timeline chart (placeholder: random walk)
    const canvas = document.getElementById('resourceTimeline');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0,0,canvas.width,canvas.height);
        ctx.beginPath();
        for (let i=0; i<56; ++i) {
            const y = 50 + 8*Math.sin(i/3 + Date.now()/4000);
            ctx.lineTo(10+i*10, y);
        }
        ctx.strokeStyle = '#06b6d4';
        ctx.lineWidth = 2.2;
        ctx.stroke();
    }
}

async function loadCommandBreakdown() {
    const res = await fetchJSON('/api/max/command-breakdown');
    // Pie chart
    const pie = document.getElementById('cmdPie');
    if (pie && res && res.pie) {
        const ctx = pie.getContext('2d');
        ctx.clearRect(0,0,pie.width,pie.height);
        const data = res.pie;
        const total = data.reduce((a,b)=>a+b.count,0)||1;
        let start = 0;
        data.forEach((c,i) => {
            const val = c.count/total;
            ctx.beginPath();
            ctx.moveTo(130,90);
            ctx.arc(130,90,80,start,start+val*2*Math.PI);
            ctx.closePath();
            ctx.fillStyle = ['#8b5cf6','#ec4899','#06b6d4','#10b981','#f59e0b','#ef4444'][i%6];
            ctx.fill();
            start += val*2*Math.PI;
        });
    }
    // Bar chart
    const bar = document.getElementById('cmdBar');
    if (bar && res && res.bar) {
        const ctx = bar.getContext('2d');
        ctx.clearRect(0,0,bar.width,bar.height);
        const cats = Object.entries(res.bar);
        const max = Math.max(1, ...cats.map(c=>c[1]));
        cats.forEach((c,i) => {
            ctx.fillStyle = ['#8b5cf6','#ec4899','#06b6d4','#10b981','#f59e0b','#ef4444'][i%6];
            ctx.fillRect(30+i*50, 170-(c[1]/max)*140, 36, (c[1]/max)*140);
            ctx.fillStyle = '#fff';
            ctx.font = '13px sans-serif';
            ctx.fillText(c[0], 30+i*50, 175);
        });
    }
}

async function loadErrorLogs() {
    const res = await fetchJSON('/api/max/errors');
    const feed = document.getElementById('errorFeed');
    if (!feed) return;
    if (!res || !res.errors || res.errors.length === 0) {
        feed.innerHTML = '<div class="log-loading">No errors found.</div>';
        return;
    }
    feed.innerHTML = res.errors.slice().reverse().map(e => `<div class="history-item"><div class="history-dot"></div><div class="history-content"><div class="history-raw">${esc(e)}</div></div></div>`).join('');
}

async function loadLeaderboard() {
    const res = await fetchJSON('/api/max/leaderboard');
    const tbody = document.getElementById('leaderboardBody');
    if (!tbody) return;
    if (!res || !res.leaderboard || res.leaderboard.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3">No data</td></tr>';
        return;
    }
    tbody.innerHTML = res.leaderboard.map(u => `<tr><td>${esc(u.username)}</td><td>${u.count}</td><td>${fmtTs(u.last_seen_at)}</td></tr>`).join('');
}

async function loadServerInfo() {
    const res = await fetchJSON('/api/max/server-info');
    const g = res && res.guild || {};
    setText('guildName', g.name || '—');
    setText('guildId', g.id || '—');
    setText('guildMembers', g.members || '—');
    setText('guildRegion', g.region || '—');
}

async function loadActivityMap() {
    const res = await fetchJSON('/api/max/activity-map');
    // Timeline
    const timeline = res && res.timeline || [];
    const tcanvas = document.getElementById('activityTimeline');
    if (tcanvas) {
        const ctx = tcanvas.getContext('2d');
        ctx.clearRect(0,0,tcanvas.width,tcanvas.height);
        ctx.beginPath();
        timeline.forEach((v,i) => {
            const x = 20+i*24;
            const y = 50-(v/Math.max(1,...timeline))*40;
            if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
        });
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 2.2;
        ctx.stroke();
    }
    // Heatmap
    const heatmap = res && res.heatmap || [];
    const hcanvas = document.getElementById('activityHeatmap');
    if (hcanvas) {
        const ctx = hcanvas.getContext('2d');
        ctx.clearRect(0,0,hcanvas.width,hcanvas.height);
        for (let h=0; h<24; ++h) for (let d=0; d<7; ++d) {
            const v = heatmap[h] && heatmap[h][d] || 0;
            ctx.fillStyle = `rgba(139,92,246,${0.08+0.7*(v/Math.max(1,...heatmap.flat()))})`;
            ctx.fillRect(20+d*80, 5+h*5, 70, 4);
        }
    }
}

async function loadNotifications() {
    const res = await fetchJSON('/api/max/notifications');
    const feed = document.getElementById('notificationFeed');
    if (!feed) return;
    if (!res || !res.events || res.events.length === 0) {
        feed.innerHTML = '<div class="log-loading">No notifications.</div>';
        return;
    }
    feed.innerHTML = res.events.map(ev => `<div class="history-item"><div class="history-dot"></div><div class="history-content"><span class="history-cmd">${esc(ev.action||'event')}</span><div class="history-meta">${esc(ev.user||'')} · ${fmtTs(ev.ts)}</div><div class="history-raw">${esc(ev.details||'')}</div></div></div>`).join('');
}

async function loadAdvancedAnalytics() {
    const res = await fetchJSON('/api/max/advanced-analytics');
    setText('advSuccessRate', res && res.success_rate != null ? res.success_rate+'%' : '—');
    setText('advAvgLatency', res && res.avg_latency != null ? res.avg_latency+'ms' : '—');
    setText('advFailures', res && res.failures != null ? res.failures : '—');
    setText('advLongestCmd', res && res.longest_cmd != null ? res.longest_cmd+'ms' : '—');
}

async function loadWidgets() {
    const grid = document.getElementById('widgetGrid');
    if (!grid) return;
    const res = await fetchJSON('/api/max/widgets');
    if (!res || !res.widgets) {
        grid.innerHTML = '<div class="log-loading">No widgets found.</div>';
        return;
    }
    grid.innerHTML = res.widgets.map(w => `<div class="widget-card">${esc(w.name)}</div>`).join('');
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
    const typeNum = act.type != null ? act.type : -1;
    if (previewType) {
        previewType.textContent = typeNum >= 0 ? (RPC_TYPE_LABELS[typeNum] || 'Activity') : 'inactive';
    }
    setText('rpcPreviewTypeId', typeNum >= 0 ? typeNum : '—');
    setText('rpcPreviewMode', res.mode || 'none');
    setText('rpcPreviewAppId', act.application_id || '—');
    setText('rpcPreviewButtons', Array.isArray(act.buttons) ? act.buttons.length : 0);
    const versionBadge = document.getElementById('rpcVersionBadge');
    if (versionBadge) {
        const mode = res.mode ? String(res.mode).toLowerCase() : 'none';
        versionBadge.textContent = `Preview ${String(res.version || 'v2').toUpperCase()} · ${mode}`;
    }
}

function applyRpcPreset(preset) {
    const presets = {
        spotify: { type: 2, name: 'Spotify', details: 'Listening to music', state: 'Premium Session' },
        twitch: { type: 1, name: 'Twitch', details: 'Streaming live', state: 'Just Chatting' },
        netflix: { type: 3, name: 'Netflix', details: 'Watching series', state: 'Episode marathon' },
        youtube: { type: 3, name: 'YouTube', details: 'Watching videos', state: 'Subscriptions feed' },
        valorant: { type: 0, name: 'VALORANT', details: 'In queue', state: 'Competitive' },
        custom: { type: 0, name: '', details: '', state: '' },
    };
    const p = presets[preset] || presets.custom;
    const typeEl = document.getElementById('rpcType');
    const nameEl = document.getElementById('rpcNameInput');
    const detailsEl = document.getElementById('rpcDetailsInput');
    const stateEl = document.getElementById('rpcStateInput');
    if (typeEl) typeEl.value = String(p.type);
    if (nameEl) nameEl.value = p.name;
    if (detailsEl) detailsEl.value = p.details;
    if (stateEl) stateEl.value = p.state;
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
        trackDashboardAction('rpc_set', `Set RPC ${name}`);
        loadRpc();
    } else {
        showRpcMsg((res && res.error) || 'Failed to set RPC.', false);
    }
}

async function clearRpc() {
    const res = await postJSON('/api/rpc', { action: 'stop' });
    if (res && res.ok) {
        showRpcMsg('RPC cleared.', true);
        trackDashboardAction('rpc_clear', 'Stopped RPC activity');
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
        trackDashboardAction('presence_set', `Set status to ${status}`);
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
        trackDashboardAction('afk_toggle', res.active ? 'Enabled AFK' : 'Disabled AFK');
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
        tbody.innerHTML = '<tr><td colspan="6" class="empty-row">No hosted users found</td></tr>';
        return;
    }
    tbody.innerHTML = res.hosted.map(u =>
        `<tr>
            <td class="cmd-name" style="font-size:11px">${esc(u.token_id || '—')}</td>
            <td>${esc(u.username || '—')}</td>
            <td class="cmd-aliases">${esc(u.owner || '—')}</td>
            <td class="cmd-aliases">${esc(u.prefix || '—')}</td>
            <td class="cmd-aliases">${esc(u.client_type || 'unknown')}</td>
            <td><span class="badge ${u.active ? 'badge-ok' : 'badge-off'}">${u.active ? '● Active' : '○ Inactive'}</span></td>
        </tr>`
    ).join('');
}

// ── Dashboard Users (login management) ───────────────────────────────────────
async function loadDashUsers() {
    await loadDashProfile();
    await loadMyActivityTimeline();
    const res = await fetchJSON('/api/dash/users');
    if (!res) {
        const tbody = document.getElementById('dashUsersBody');
        if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="empty-row">Admin only</td></tr>';
        return;
    }
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

    await loadAccessRequests();
}

function showDashAccountMsg(msg, ok) {
    const el = document.getElementById('dashAccountMsg');
    if (!el) return;
    el.textContent = msg;
    el.className = 'settings-msg ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; el.className = 'settings-msg'; }, 4000);
}

function showAccessReqBulkMsg(msg, ok) {
    const el = document.getElementById('accessReqBulkMsg');
    if (!el) return;
    el.textContent = msg;
    el.className = 'settings-msg ' + (ok ? 'ok' : 'err');
    setTimeout(() => { el.textContent = ''; el.className = 'settings-msg'; }, 5000);
}

function applyRoleVisibility(profile) {
    const isAdmin = !!(profile && profile.is_admin);
    const adminOnly = document.querySelectorAll('[data-admin-only="true"], .admin-only');
    adminOnly.forEach(el => {
        if (isAdmin) {
            el.style.display = '';
            if (el.classList.contains('nav-item')) el.dataset.hiddenByRole = 'false';
        } else {
            el.style.display = 'none';
            if (el.classList.contains('nav-item')) el.dataset.hiddenByRole = 'true';
        }
    });

    const usersTitle = document.getElementById('dashUsersTotal');
    if (usersTitle && !isAdmin) usersTitle.textContent = 'My account';

    const active = document.querySelector('.nav-item.active');
    if (active && active.dataset.hiddenByRole === 'true') {
        const fallback = document.querySelector('.nav-item[data-section="overview"]');
        if (fallback) fallback.click();
    }
}

async function loadDashProfile() {
    const res = await fetchJSON('/api/dash/me');
    if (!res || !res.ok) {
        setText('meUsername', '—');
        setText('meUserId', '—');
        setText('meRole', '—');
        setText('meInstance', '—');
        setText('pendingRequests', 0);
        setText('meLastLogin', '—');
        setText('meLastSeen', '—');
        return;
    }

    const p = res.profile || {};
    _meProfile = p;
    const s = res.summary || {};
    setText('meUsername', p.username || '—');
    setText('meUserId', p.user_id || '—');
    setText('meRole', p.role || 'user');
    setText('meInstance', p.instance_id || '—');
    setText('pendingRequests', s.pending_requests ?? 0);
    setText('meLastLogin', fmtTs(p.last_login_at));
    setText('meLastSeen', fmtTs(p.last_seen_at));

    const card = document.getElementById('accessRequestsCard');
    if (card) card.style.display = p.is_admin ? 'block' : 'none';
    applyRoleVisibility(p);
}

async function loadMyActivityTimeline() {
    const feed = document.getElementById('activityTimelineFeed');
    const badge = document.getElementById('activityTimelineBadge');
    if (!feed || !badge) return;

    const res = await fetchJSON('/api/dash/activity');
    if (!res || !res.ok) {
        badge.textContent = '0';
        feed.innerHTML = '<div class="log-loading">Unable to load timeline.</div>';
        return;
    }

    const timeline = Array.isArray(res.timeline) ? res.timeline : [];
    badge.textContent = String(timeline.length);
    if (!timeline.length) {
        feed.innerHTML = '<div class="log-loading">No recent account actions yet.</div>';
        return;
    }

    feed.innerHTML = timeline.slice().reverse().map(t => {
        const action = esc(t.action || 'activity');
        const details = esc(t.details || '');
        const ts = fmtTs(t.ts);
        return `<div class="history-item">
            <div class="history-dot"></div>
            <div class="history-content">
                <span class="history-cmd">${action}</span>
                <div class="history-meta">🕐 ${esc(ts)}</div>
                ${details ? `<div class="history-raw">${details}</div>` : ''}
            </div>
        </div>`;
    }).join('');
}

async function changeMyPassword() {
    const oldPassword = document.getElementById('oldPasswordInput').value;
    const newPassword = document.getElementById('newPasswordInput').value;
    if (!oldPassword || !newPassword) {
        showDashAccountMsg('Enter both current and new password.', false);
        return;
    }
    const res = await postJSON('/api/dash/change-password', {
        old_password: oldPassword,
        new_password: newPassword,
    });
    if (res && res.ok) {
        showDashAccountMsg('Password updated.', true);
        trackDashboardAction('password_change', 'Updated dashboard password');
        document.getElementById('oldPasswordInput').value = '';
        document.getElementById('newPasswordInput').value = '';
        loadMyActivityTimeline();
    } else {
        showDashAccountMsg((res && res.error) || 'Failed to update password.', false);
    }
}

async function loadAccessRequests() {
    const card = document.getElementById('accessRequestsCard');
    const body = document.getElementById('accessReqBody');
    const badge = document.getElementById('accessReqBadge');
    if (!card || !body || !badge) return;

    const res = await fetchJSON('/api/dash/requests');
    if (!res || !res.ok) {
        body.innerHTML = '<tr><td colspan="4" class="empty-row">Admin only</td></tr>';
        return;
    }

    const reqs = res.requests || [];
    badge.textContent = String(reqs.length);
    if (!reqs.length) {
        body.innerHTML = '<tr><td colspan="4" class="empty-row">No access requests</td></tr>';
        return;
    }

    body.innerHTML = reqs.slice().reverse().map(r => {
        const id = esc(r.id || '');
        const status = String(r.status || 'pending').toLowerCase();
        const statusClass = status === 'approved' ? 'badge-ok' : status === 'denied' ? 'badge-pink' : 'badge-warn';
        const actions = status === 'pending'
            ? `<button class="btn btn-primary" style="padding:4px 10px;font-size:11px" onclick="approveAccessRequest('${id}')">Approve</button>
               <button class="btn btn-danger-soft" style="padding:4px 10px;font-size:11px" onclick="denyAccessRequest('${id}')">Deny</button>`
            : '<span style="color:var(--muted);font-size:12px">Complete</span>';

        return `<tr>
            <td style="font-weight:600">${esc(r.username || '—')}</td>
            <td style="color:var(--muted)">${esc(r.reason || '—')}</td>
            <td><span class="badge ${statusClass}">${esc(status)}</span></td>
            <td>${actions}</td>
        </tr>`;
    }).join('');
}

async function approveAccessRequest(reqId) {
    const customUserId = prompt('Optional: set custom user_id (leave empty for auto)') || '';
    const customPassword = prompt('Optional: set custom password (leave empty for auto)') || '';
    const body = {};
    if (customUserId.trim()) body.user_id = customUserId.trim();
    if (customPassword.trim()) body.password = customPassword.trim();

    try {
        const r = await fetch(`/api/dash/requests/${encodeURIComponent(reqId)}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const res = await r.json();
        if (res && res.ok) {
            showDashUsersMsg(`Approved: ${res.user_id} (pw: ${res.password})`, true);
            trackDashboardAction('request_approve', `Approved request ${reqId}`);
            loadAccessRequests();
            loadDashUsers();
        } else {
            showDashUsersMsg((res && res.error) || 'Approve failed.', false);
        }
    } catch {
        showDashUsersMsg('Approve request failed.', false);
    }
}

async function denyAccessRequest(reqId) {
    try {
        const r = await fetch(`/api/dash/requests/${encodeURIComponent(reqId)}/deny`, { method: 'POST' });
        const res = await r.json();
        if (res && res.ok) {
            showDashUsersMsg('Request denied.', true);
            trackDashboardAction('request_deny', `Denied request ${reqId}`);
            loadAccessRequests();
            loadDashUsers();
        } else {
            showDashUsersMsg((res && res.error) || 'Deny failed.', false);
        }
    } catch {
        showDashUsersMsg('Deny request failed.', false);
    }
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
        trackDashboardAction('account_create', `Created account ${uid}`);
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
        if (res && res.ok) { showDashUsersMsg(`Removed ${uid}`, true); trackDashboardAction('account_remove', `Removed account ${uid}`); loadDashUsers(); }
        else showDashUsersMsg((res && res.error) || 'Failed.', false);
    } catch(e) { showDashUsersMsg('Request failed.', false); }
}

async function approveAllPendingRequests() {
    const res = await postJSON('/api/dash/requests/approve-all-pending', {});
    if (res && res.ok) {
        const count = Number(res.approved_count || 0);
        const sample = Array.isArray(res.approved) && res.approved.length
            ? ` First: ${res.approved[0].user_id}/${res.approved[0].password}`
            : '';
        showAccessReqBulkMsg(`Approved ${count} pending request(s).${sample}`, true);
        trackDashboardAction('request_bulk_approve', `Bulk approved ${count} requests`);
        loadAccessRequests();
        loadDashUsers();
    } else {
        showAccessReqBulkMsg((res && res.error) || 'Bulk approve failed.', false);
    }
}

async function denyAllPendingRequests() {
    const res = await postJSON('/api/dash/requests/deny-all-pending', {});
    if (res && res.ok) {
        const count = Number(res.denied_count || 0);
        showAccessReqBulkMsg(`Denied ${count} pending request(s).`, true);
        trackDashboardAction('request_bulk_deny', `Bulk denied ${count} requests`);
        loadAccessRequests();
        loadDashUsers();
    } else {
        showAccessReqBulkMsg((res && res.error) || 'Bulk deny failed.', false);
    }
}

async function trackDashboardAction(action, details = '') {
    if (!_meProfile) return;
    if (!action) return;
    await postJSON('/api/dash/activity', { action, details });
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

// Faster overview heartbeat for more "live" feeling metrics.
setInterval(() => {
    const active = document.querySelector('.nav-item.active');
    if (active && active.dataset.section === 'overview') loadOverview();
}, 7000);

// ── Initial load ──────────────────────────────────────────────────────────────
loadOverview();
loadDashProfile();
