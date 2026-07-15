/* App Token management UI for team management page */

let _appTokenCurrentTeamId = null;

function translateAppToken(key, params, fallback) {
    return window.i18n && window.i18n.t
        ? window.i18n.t(key, params || {}, fallback)
        : fallback;
}

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
    const loadingMessage = escapeHtml(translateAppToken('appToken.loading', {}, '載入中...'));
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">${loadingMessage}</td></tr>`;
    try {
        const resp = await fetch(`/api/teams/${_appTokenCurrentTeamId}/app-tokens`, {
            headers: { 'Authorization': `Bearer ${getJwtToken()}` }
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        renderAppTokenList(data.items || []);
    } catch (err) {
        const failureMessage = escapeHtml(translateAppToken(
            'appToken.loadFailedWithReason',
            { reason: err.message },
            `載入權杖失敗: ${err.message}`
        ));
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">${failureMessage}</td></tr>`;
    }
}

function renderAppTokenList(tokens) {
    const tbody = document.getElementById('appTokenTableBody');
    if (!tokens.length) {
        const emptyMessage = escapeHtml(translateAppToken('appToken.noTokens', {}, '無 App Token'));
        tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">${emptyMessage}</td></tr>`;
        return;
    }
    tbody.innerHTML = tokens.map(t => {
        const isActive = t.status === 'active';
        const statusBadge = isActive
            ? `<span class="badge bg-success">${translateAppToken('appToken.statusActive', {}, '啟用中')}</span>`
            : `<span class="badge bg-secondary">${translateAppToken('appToken.statusRevoked', {}, '已撤銷')}</span>`;
        const prefixDisplay = t.token_prefix ? t.token_prefix.substring(0, 12) + '...' : '-';
        const scopesDisplay = (t.scopes || []).join(', ') || '-';
        const expiryDisplay = t.expires_at
            ? new Date(t.expires_at).toLocaleDateString()
            : translateAppToken('appToken.neverExpires', {}, '永不過期');
        const lastUsedDisplay = t.last_used_at ? new Date(t.last_used_at).toLocaleString() : '-';
        const actions = isActive
            ? `<button class="btn btn-warning btn-sm me-1" onclick="rotateAppToken(${t.id})" data-i18n-title="appToken.rotateAction" title="輪替"><i class="fas fa-sync-alt"></i></button>` +
              `<button class="btn btn-danger btn-sm" onclick="revokeAppToken(${t.id})" data-i18n-title="appToken.revokeAction" title="撤銷"><i class="fas fa-ban"></i></button>`
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
    if (!name) { alert(translateAppToken('appToken.nameRequired', {}, '權杖名稱為必填項')); return; }
    const description = document.getElementById('appTokenDescription').value.trim() || null;
    const scopes = Array.from(document.querySelectorAll('.app-token-scope:checked')).map(cb => cb.value);
    if (!scopes.length) { alert(translateAppToken('appToken.scopeRequired', {}, '至少需要選擇一個權限範圍')); return; }
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
        alert(translateAppToken(
            'appToken.createFailedWithReason',
            { reason: err.message },
            `建立權杖失敗: ${err.message}`
        ));
    }
}

async function revokeAppToken(tokenId) {
    if (!confirm(translateAppToken('appToken.revokeConfirm', {}, '撤銷此權杖？此操作無法復原。'))) return;
    try {
        const resp = await fetch(`/api/teams/${_appTokenCurrentTeamId}/app-tokens/${tokenId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${getJwtToken()}` }
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        loadAppTokens();
    } catch (err) {
        alert(translateAppToken(
            'appToken.revokeFailedWithReason',
            { reason: err.message },
            `撤銷權杖失敗: ${err.message}`
        ));
    }
}

async function rotateAppToken(tokenId) {
    if (!confirm(translateAppToken(
        'appToken.rotateConfirm',
        {},
        '輪替此權杖？舊權杖將立即失效，沒有寬限期。您必須更新使用舊權杖的任何整合。'
    ))) return;
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
        alert(translateAppToken(
            'appToken.rotateFailedWithReason',
            { reason: err.message },
            `輪替權杖失敗: ${err.message}`
        ));
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
