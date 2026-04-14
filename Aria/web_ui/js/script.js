// Add hosted user disconnect logic to dashboard
function loadHostedUsers() {
    fetch('/api/hosted')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById('hostedBody');
            tbody.innerHTML = '';
            if (!data.ok || !Array.isArray(data.hosted) || data.hosted.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="empty-row">No hosted users.</td></tr>';
                return;
            }
            data.hosted.forEach(user => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${user.token_id}</td>
                    <td>${user.username}</td>
                    <td>${user.owner}</td>
                    <td>${user.prefix}</td>
                    <td>${user.client_type}</td>
                    <td>${user.active ? '<span class="badge badge-ok">Active</span>' : '<span class="badge badge-off">Inactive</span>'}
                        <button class="btn btn-danger-soft" onclick="disconnectHostedUser('${user.token_id}')">Disconnect</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
            document.getElementById('hostedTotal').textContent = data.total;
            document.getElementById('hostedActive').textContent = data.active_count;
            document.getElementById('hostedBadge').textContent = data.total;
        });
}

function disconnectHostedUser(tokenId) {
    if (!confirm('Disconnect this hosted user?')) return;
    fetch('/api/hosted/disconnect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token_id: tokenId })
    })
    .then(r => r.json())
    .then(data => {
        if (data.ok) {
            loadHostedUsers();
        } else {
            alert('Failed to disconnect: ' + (data.error || 'Unknown error'));
        }
    });
}

document.addEventListener('DOMContentLoaded', function() {
    loadHostedUsers();
});
