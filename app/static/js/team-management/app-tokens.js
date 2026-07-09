/* App Token management UI for team management page */

let _appTokenCurrentTeamId = null;

function openAppTokenModal(teamId, teamName) {
    _appTokenCurrentTeamId = teamId;
    const nameEl = document.getElementById('appTokenTeamName');
    if (nameEl) nameEl.textContent = teamName || '';
    hideCreateAppTokenForm();
    document.getElementById('appTokenRawTokenDisplay').style.display = 'none';
    const modal = new bootstrap.Modal(document.getElementById('appTokenModal'));
    modal.show();
    loadAppTokens();
}

async function loadAppTokens() {
    if (!_appTokenCurrentTeamId) return;
    const tbody = document.getElementById('appTokenTableBody');
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading...</td></tr>';
    try {
        const resp = await fetch(`/api/teams/${_appTokenCurrentTeamId}/app-tokens`, {
            headers: { 'Authorization': `Bearer ${getJwtToken()}` }
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        renderAppTokenList(data.items || []);
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Failed to load tokens: ${escapeHtml(err.message)}</td></tr>`;
    }
}

function renderAppTokenList(tokens) {
    const tbody = document.getElementById('appTokenTableBody');
    if (!tokens.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">No app tokens</td></tr>';
        return;
    }
    tbody.innerHTML = tokens.map(t => {
        const isActive = t.status === 'active';
        const statusBadge = isActive
            ? '<span class="badge bg-success">active</span>'
            : '<span class="badge bg-secondary">revoked</span>';
        const prefixDisplay = t.token_prefix ? t.token_prefix.substring(0, 12) + '...' : '-';
        const scopesDisplay = (t.scopes || []).join(', ') || '-';
        const expiryDisplay = t.expires_at ? new Date(t.expires_at).toLocaleDateString() : 'Never';
        const lastUsedDisplay = t.last_used_at ? new Date(t.last_used_at).toLocaleString() : '-';
        const actions = isActive
            ? `<button class="btn btn-warning btn-sm me-1" onclick="rotateAppToken(${t.id})" title="Rotate"><i class="fas fa-sync-alt"></i></button>` +
              `<button class="btn btn-danger btn-sm" onclick="revokeAppToken(${t.id})" title="Revoke"><i class="fas fa-ban"></i></button>`
            : '<span class="text-muted">-</span>';
        return `<tr>
            <td>${escapeHtml(t.name)}</td>
            <td><code>${escapeHtml(prefixDisplay)}</code></td>
            <td>${statusBadge}</td>
            <td class="small">${escapeHtml(scopesDisplay)}</td>
            <td class="small">${escapeHtml(expiryDisplay)}</td>
            <td class="small">${escapeHtml(lastUsedDisplay)}</td>
            <td>${actions}</td>
        </tr>`;
    }).join('');

    const modal = document.getElementById('appTokenModal');
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(modal);
    }
}

function showCreateAppTokenForm() {
    document.getElementById('appTokenCreateForm').style.display = 'block';
    document.getElementById('appTokenName').value = '';
    document.getElementById('appTokenDescription').value = '';
    document.getElementById('appTokenExpiryDays').value = '90';
    document.getElementById('appTokenNoExpiry').checked = false;
    document.getElementById('appTokenExpiryDays').disabled = false;
    document.getElementById('appTokenNoExpiryWarning').style.display = 'none';
    document.querySelectorAll('.app-token-scope').forEach(cb => cb.checked = false);
}

function hideCreateAppTokenForm() {
    document.getElementById('appTokenCreateForm').style.display = 'none';
}

async function createAppToken() {
    if (!_appTokenCurrentTeamId) return;
    const name = document.getElementById('appTokenName').value.trim();
    if (!name) { alert('Token name is required'); return; }
    const description = document.getElementById('appTokenDescription').value.trim() || null;
    const scopes = Array.from(document.querySelectorAll('.app-token-scope:checked')).map(cb => cb.value);
    if (!scopes.length) { alert('At least one scope is required'); return; }
    const noExpiry = document.getElementById('appTokenNoExpiry').checked;
    const expiryDays = noExpiry ? 0 : parseInt(document.getElementById('appTokenExpiryDays').value, 10);
    const payload = { name, scopes, expires_in_days: noExpiry ? 0 : (isNaN(expiryDays) ? null : expiryDays) };
    if (description) payload.description = description;

    try {
        const resp = await fetch(`/api/teams/${_appTokenCurrentTeamId}/app-tokens`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${getJwtToken()}` },
            body: JSON.stringify(payload)
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail?.message || `HTTP ${resp.status}`);
        }
        const data = await resp.json();
        hideCreateAppTokenForm();
        document.getElementById('appTokenRawToken').textContent = data.raw_token;
        document.getElementById('appTokenRawTokenDisplay').style.display = 'block';
        loadAppTokens();
    } catch (err) {
        alert(`Failed to create token: ${err.message}`);
    }
}

async function revokeAppToken(tokenId) {
    if (!confirm('Revoke this token? This action cannot be undone.')) return;
    try {
        const resp = await fetch(`/api/teams/${_appTokenCurrentTeamId}/app-tokens/${tokenId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${getJwtToken()}` }
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        loadAppTokens();
    } catch (err) {
        alert(`Failed to revoke token: ${err.message}`);
    }
}

async function rotateAppToken(tokenId) {
    if (!confirm('Rotate this token? The old token will be immediately invalidated with no grace period. You must update any integrations using the old token.')) return;
    try {
        const resp = await fetch(`/api/teams/${_appTokenCurrentTeamId}/app-tokens/${tokenId}/rotate`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${getJwtToken()}` }
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail?.message || `HTTP ${resp.status}`);
        }
        const data = await resp.json();
        document.getElementById('appTokenRawToken').textContent = data.raw_token;
        document.getElementById('appTokenRawTokenDisplay').style.display = 'block';
        loadAppTokens();
    } catch (err) {
        alert(`Failed to rotate token: ${err.message}`);
    }
}

function copyAppTokenRawToken() {
    const text = document.getElementById('appTokenRawToken').textContent;
    navigator.clipboard.writeText(text).then(() => {
        const btn = event.target.closest('button');
        const original = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-check"></i>';
        setTimeout(() => { btn.innerHTML = original; }, 2000);
    });
}

function getJwtToken() {
    return localStorage.getItem('access_token') || sessionStorage.getItem('access_token') || '';
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
