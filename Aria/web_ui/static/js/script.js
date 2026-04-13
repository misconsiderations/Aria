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
        pageTitle.textContent = item.textContent.trim().replace('◈', '').trim();
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

function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val ?? '—';
}

// ── Status dot ───────────────────────────────────────────────────────────────
function setGlobalStatus(connected) {
    const dot = document.getElementById('globalStatus');
    const lbl = document.getElementById('globalStatusLabel');
    if (connected) {
        dot.className = 'status-dot online';
        lbl.textContent = 'Connected';
    } else {
        dot.className = 'status-dot offline';
        lbl.textContent = 'Disconnected';
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
}

// ── Analytics ─────────────────────────────────────────────────────────────────
async function loadAnalytics() {
    const res = await fetchJSON('/api/analytics');
    if (!res || !res.data) return;
    const d = res.data;
    setText('totalCommands', d.total_commands);
    setText('successRate', d.success_rate + '%');
    setText('avgResponseMs', d.avg_response_ms + 's');

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
    setText('historyTotal', d.total);

    const list = document.getElementById('historyList');
    if (!d.entries || d.entries.length === 0) {
        list.innerHTML = '<div class="empty-row">No history entries found</div>';
        return;
    }
    list.innerHTML = d.entries.map(e =>
        `<div class="history-entry">${esc(typeof e === 'object' ? JSON.stringify(e, null, 2) : String(e))}</div>`
    ).join('');
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

// ── Section router ────────────────────────────────────────────────────────────
function loadSection(name) {
    if (name === 'overview')  loadOverview();
    if (name === 'analytics') loadAnalytics();
    if (name === 'history')   loadHistory();
    if (name === 'boost')     loadBoost();
}

// ── Escape HTML ───────────────────────────────────────────────────────────────
function esc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
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
