/* Shared App Token management controller for Dashboard and Team Management. */

(() => {
    'use strict';

    const state = {
        initialized: false,
        requestVersion: 0,
        teamId: null,
        teamName: '',
    };

    function byId(id) {
        return document.getElementById(id);
    }

    function translate(key, params, fallback) {
        return window.i18n && typeof window.i18n.t === 'function'
            ? window.i18n.t(key, params || {}, fallback)
            : fallback;
    }

    function escapeHtml(value) {
        const element = document.createElement('div');
        element.textContent = value == null ? '' : String(value);
        return element.innerHTML;
    }

    function validTeamId(value) {
        const parsed = Number(value);
        return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
    }

    function setHidden(element, hidden) {
        if (element) element.classList.toggle('d-none', hidden);
    }

    function setTableMessage(message, className = 'text-muted') {
        const tbody = byId('appTokenTableBody');
        if (!tbody) return;
        tbody.innerHTML = `<tr><td colspan="7" class="text-center ${className}">${escapeHtml(message)}</td></tr>`;
    }

    function setCurrentTeam(teamId, teamName) {
        state.teamId = validTeamId(teamId);
        state.teamName = state.teamId ? String(teamName || '') : '';
        const name = byId('appTokenTeamName');
        if (name) name.textContent = state.teamName;
        const createButton = byId('btnCreateAppToken');
        if (createButton) createButton.disabled = !state.teamId;
    }

    async function authenticatedFetch(url, options) {
        if (!window.AuthClient || typeof window.AuthClient.fetch !== 'function') {
            throw new Error('Authentication client unavailable');
        }
        return window.AuthClient.fetch(url, options || {});
    }

    function hideCreateForm() {
        setHidden(byId('appTokenCreateForm'), true);
    }

    function hideRawToken() {
        setHidden(byId('appTokenRawTokenDisplay'), true);
        const rawToken = byId('appTokenRawToken');
        if (rawToken) rawToken.textContent = '';
    }

    function updateNoExpiryState() {
        const noExpiry = byId('appTokenNoExpiry');
        const expiry = byId('appTokenExpiryDays');
        if (!noExpiry || !expiry) return;
        expiry.disabled = noExpiry.checked;
        if (noExpiry.checked) expiry.value = '0';
        setHidden(byId('appTokenNoExpiryWarning'), !noExpiry.checked);
    }

    function showCreateForm() {
        if (!state.teamId) return;
        setHidden(byId('appTokenCreateForm'), false);
        byId('appTokenName').value = '';
        byId('appTokenDescription').value = '';
        byId('appTokenExpiryDays').value = '90';
        byId('appTokenNoExpiry').checked = false;
        document.querySelectorAll('#appTokenModal .app-token-scope').forEach((checkbox) => {
            checkbox.checked = false;
        });
        updateNoExpiryState();
        byId('appTokenName').focus();
    }

    function renderTokenList(tokens) {
        const tbody = byId('appTokenTableBody');
        if (!tbody) return;
        if (!tokens.length) {
            setTableMessage(translate('appToken.noTokens', {}, '無 App Token'));
            return;
        }

        tbody.innerHTML = tokens.map((token) => {
            const tokenId = Number(token.id);
            const isActive = token.status === 'active';
            const activeLabel = escapeHtml(
                translate('appToken.statusActive', {}, '啟用中')
            );
            const revokedLabel = escapeHtml(
                translate('appToken.statusRevoked', {}, '已撤銷')
            );
            const rotateLabel = escapeHtml(
                translate('appToken.rotateAction', {}, '輪替')
            );
            const revokeLabel = escapeHtml(
                translate('appToken.revokeAction', {}, '撤銷')
            );
            const statusBadge = isActive
                ? `<span class="badge bg-success">${activeLabel}</span>`
                : `<span class="badge bg-secondary">${revokedLabel}</span>`;
            const prefix = token.token_prefix
                ? `${String(token.token_prefix).substring(0, 12)}...`
                : '-';
            const scopes = (token.scopes || []).join(', ') || '-';
            const expires = token.expires_at
                ? new Date(token.expires_at).toLocaleDateString()
                : translate('appToken.neverExpires', {}, '永不過期');
            const lastUsed = token.last_used_at
                ? new Date(token.last_used_at).toLocaleString()
                : '-';
            const actions = isActive && Number.isInteger(tokenId) && tokenId > 0
                ? `<button type="button" class="btn btn-warning btn-sm me-1" data-app-token-action="rotate" data-token-id="${tokenId}" aria-label="${rotateLabel}" title="${rotateLabel}"><i class="fas fa-sync-alt"></i></button>` +
                  `<button type="button" class="btn btn-danger btn-sm" data-app-token-action="revoke" data-token-id="${tokenId}" aria-label="${revokeLabel}" title="${revokeLabel}"><i class="fas fa-ban"></i></button>`
                : '<span class="text-muted">-</span>';
            return `<tr>
                <td>${escapeHtml(token.name)}</td>
                <td><code>${escapeHtml(prefix)}</code></td>
                <td>${statusBadge}</td>
                <td class="small">${escapeHtml(scopes)}</td>
                <td class="small">${escapeHtml(expires)}</td>
                <td class="small">${escapeHtml(lastUsed)}</td>
                <td>${actions}</td>
            </tr>`;
        }).join('');

        const modal = byId('appTokenModal');
        if (window.i18n && typeof window.i18n.retranslate === 'function') {
            window.i18n.retranslate(modal);
        }
    }

    async function loadTokens() {
        const teamId = state.teamId;
        if (!teamId) return;
        const requestVersion = ++state.requestVersion;
        setTableMessage(translate('appToken.loading', {}, '載入中...'));

        try {
            const response = await authenticatedFetch(
                `/api/teams/${teamId}/app-tokens`
            );
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (requestVersion !== state.requestVersion || teamId !== state.teamId) return;
            renderTokenList(Array.isArray(data.items) ? data.items : []);
        } catch (error) {
            if (requestVersion !== state.requestVersion || teamId !== state.teamId) return;
            setTableMessage(
                translate(
                    'appToken.loadFailedWithReason',
                    { reason: error.message },
                    `載入權杖失敗：${error.message}`
                ),
                'text-danger'
            );
        }
    }

    function resetTeamPicker() {
        const picker = byId('appTokenTeamPicker');
        const select = byId('appTokenTeamSelect');
        const error = byId('appTokenTeamError');
        setHidden(picker, false);
        setHidden(error, true);
        if (error) error.textContent = '';
        if (!select) return;
        select.replaceChildren();
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = translate(
            'appToken.selectTeamPlaceholder',
            {},
            '請選擇要管理的團隊'
        );
        placeholder.selected = true;
        select.append(placeholder);
        select.disabled = true;
    }

    async function loadAvailableTeams() {
        resetTeamPicker();
        const select = byId('appTokenTeamSelect');
        const error = byId('appTokenTeamError');
        const requestVersion = ++state.requestVersion;

        try {
            const response = await authenticatedFetch('/api/teams/');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const teams = await response.json();
            if (requestVersion !== state.requestVersion) return;
            const available = Array.isArray(teams)
                ? teams.filter((team) => validTeamId(team.id))
                : [];
            if (!available.length) {
                const empty = document.createElement('option');
                empty.value = '';
                empty.textContent = translate(
                    'appToken.noTeamsAvailable',
                    {},
                    '目前沒有可管理的團隊'
                );
                select.replaceChildren(empty);
                setTableMessage(
                    translate(
                        'appToken.noTeamsAvailable',
                        {},
                        '目前沒有可管理的團隊'
                    )
                );
                return;
            }
            available.forEach((team) => {
                const option = document.createElement('option');
                option.value = String(team.id);
                option.textContent = String(team.name || team.id);
                select.append(option);
            });
            select.disabled = false;
        } catch (errorValue) {
            if (requestVersion !== state.requestVersion) return;
            const message = translate(
                'appToken.loadTeamsFailedWithReason',
                { reason: errorValue.message },
                `載入團隊失敗：${errorValue.message}`
            );
            if (error) {
                error.textContent = message;
                setHidden(error, false);
            }
            setTableMessage(message, 'text-danger');
        }
    }

    function selectTeam(eventValue) {
        const select = eventValue.currentTarget;
        const teamId = validTeamId(select.value);
        if (!teamId) return;
        const teamName = select.selectedOptions[0]?.textContent || String(teamId);
        setCurrentTeam(teamId, teamName);
        setHidden(byId('appTokenTeamPicker'), true);
        hideCreateForm();
        hideRawToken();
        loadTokens();
    }

    async function createToken() {
        const teamId = state.teamId;
        if (!teamId) return;
        const name = byId('appTokenName').value.trim();
        if (!name) {
            alert(translate('appToken.nameRequired', {}, '權杖名稱為必填項'));
            return;
        }
        const description = byId('appTokenDescription').value.trim() || null;
        const scopes = Array.from(
            document.querySelectorAll('#appTokenModal .app-token-scope:checked')
        ).map((checkbox) => checkbox.value);
        if (!scopes.length) {
            alert(translate('appToken.scopeRequired', {}, '至少需要選擇一個權限範圍'));
            return;
        }
        const noExpiry = byId('appTokenNoExpiry').checked;
        const expiryDays = noExpiry
            ? 0
            : Number.parseInt(byId('appTokenExpiryDays').value, 10);
        const payload = {
            name,
            scopes,
            expires_in_days: noExpiry
                ? 0
                : (Number.isNaN(expiryDays) ? null : expiryDays),
        };
        if (description) payload.description = description;

        const confirmButton = byId('appTokenCreateConfirm');
        confirmButton.disabled = true;
        try {
            const response = await authenticatedFetch(
                `/api/teams/${teamId}/app-tokens`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                }
            );
            if (!response.ok) {
                const errorBody = await response.json().catch(() => ({}));
                throw new Error(errorBody.detail?.message || `HTTP ${response.status}`);
            }
            const data = await response.json();
            hideCreateForm();
            byId('appTokenRawToken').textContent = data.raw_token;
            setHidden(byId('appTokenRawTokenDisplay'), false);
            await loadTokens();
        } catch (error) {
            alert(translate(
                'appToken.createFailedWithReason',
                { reason: error.message },
                `建立權杖失敗：${error.message}`
            ));
        } finally {
            confirmButton.disabled = false;
        }
    }

    async function revokeToken(tokenId) {
        const teamId = state.teamId;
        if (!teamId) return;
        if (!confirm(translate(
            'appToken.revokeConfirm',
            {},
            '撤銷此權杖？此操作無法復原。'
        ))) return;

        try {
            const response = await authenticatedFetch(
                `/api/teams/${teamId}/app-tokens/${tokenId}`,
                { method: 'DELETE' }
            );
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            await loadTokens();
        } catch (error) {
            alert(translate(
                'appToken.revokeFailedWithReason',
                { reason: error.message },
                `撤銷權杖失敗：${error.message}`
            ));
        }
    }

    async function rotateToken(tokenId) {
        const teamId = state.teamId;
        if (!teamId) return;
        if (!confirm(translate(
            'appToken.rotateConfirm',
            {},
            '輪替此權杖？舊權杖將立即失效，沒有寬限期。'
        ))) return;

        try {
            const response = await authenticatedFetch(
                `/api/teams/${teamId}/app-tokens/${tokenId}/rotate`,
                { method: 'POST' }
            );
            if (!response.ok) {
                const errorBody = await response.json().catch(() => ({}));
                throw new Error(errorBody.detail?.message || `HTTP ${response.status}`);
            }
            const data = await response.json();
            byId('appTokenRawToken').textContent = data.raw_token;
            setHidden(byId('appTokenRawTokenDisplay'), false);
            await loadTokens();
        } catch (error) {
            alert(translate(
                'appToken.rotateFailedWithReason',
                { reason: error.message },
                `輪替權杖失敗：${error.message}`
            ));
        }
    }

    async function copyRawToken() {
        const button = byId('appTokenCopy');
        const value = byId('appTokenRawToken').textContent;
        if (!button || !value) return;
        const original = button.innerHTML;
        await navigator.clipboard.writeText(value);
        button.innerHTML = '<i class="fas fa-check"></i>';
        window.setTimeout(() => {
            button.innerHTML = original;
        }, 2000);
    }

    function handleTokenAction(eventValue) {
        const button = eventValue.target.closest('[data-app-token-action]');
        if (!button || !eventValue.currentTarget.contains(button)) return;
        const tokenId = Number(button.dataset.tokenId);
        if (!Number.isInteger(tokenId) || tokenId <= 0) return;
        if (button.dataset.appTokenAction === 'rotate') {
            rotateToken(tokenId);
        } else if (button.dataset.appTokenAction === 'revoke') {
            revokeToken(tokenId);
        }
    }

    function resetModal() {
        state.requestVersion += 1;
        setCurrentTeam(null, '');
        hideCreateForm();
        hideRawToken();
        setHidden(byId('appTokenTeamPicker'), true);
        setTableMessage(
            translate(
                'appToken.selectTeamHelp',
                {},
                '選擇團隊後才會載入 App Token。'
            )
        );
    }

    function initialize() {
        if (state.initialized) return;
        const modal = byId('appTokenModal');
        if (!modal) return;
        state.initialized = true;
        byId('btnCreateAppToken').addEventListener('click', showCreateForm);
        byId('appTokenCreateConfirm').addEventListener('click', createToken);
        byId('appTokenCreateCancel').addEventListener('click', hideCreateForm);
        byId('appTokenNoExpiry').addEventListener('change', updateNoExpiryState);
        byId('appTokenCopy').addEventListener('click', copyRawToken);
        byId('appTokenTeamSelect').addEventListener('change', selectTeam);
        byId('appTokenTableBody').addEventListener('click', handleTokenAction);
        modal.addEventListener('hidden.bs.modal', resetModal);
    }

    async function open(options = {}) {
        initialize();
        const modal = byId('appTokenModal');
        if (!modal || !window.bootstrap) return;
        state.requestVersion += 1;
        hideCreateForm();
        hideRawToken();

        const teamId = validTeamId(options.teamId);
        if (teamId) {
            setCurrentTeam(teamId, options.teamName);
            setHidden(byId('appTokenTeamPicker'), true);
        } else {
            setCurrentTeam(null, '');
            setTableMessage(
                translate(
                    'appToken.selectTeamHelp',
                    {},
                    '選擇團隊後才會載入 App Token。'
                )
            );
        }

        window.bootstrap.Modal.getOrCreateInstance(modal).show();
        if (window.i18n && typeof window.i18n.retranslate === 'function') {
            window.i18n.retranslate(modal);
        }
        if (teamId) {
            await loadTokens();
        } else if (options.allowTeamSelection === true) {
            await loadAvailableTeams();
        }
    }

    window.AppTokenModal = { open };
    window.openAppTokenModal = (teamId, teamName) => open({ teamId, teamName });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }
})();
