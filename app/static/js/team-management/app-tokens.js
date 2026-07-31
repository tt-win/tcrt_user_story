/* Shared App Token management controller for Dashboard and Team Management. */

(() => {
    'use strict';

    const state = {
        initialized: false,
        requestVersion: 0,
        contextVersion: 0,
        mutationVersion: 0,
        pendingMutation: null,
        authContext: null,
        teamId: null,
        teamName: '',
        globalMode: false,
        availableTeams: [],
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

    function authIdentityFromToken(token) {
        if (!token || typeof window.atob !== 'function') return null;
        const parts = String(token).split('.');
        if (parts.length < 2) return null;
        try {
            const encoded = parts[1].replace(/-/g, '+').replace(/_/g, '/');
            const padded = encoded.padEnd(encoded.length + ((4 - encoded.length % 4) % 4), '=');
            const payload = JSON.parse(window.atob(padded));
            const identity = payload.user_id ?? payload.sub;
            return identity == null ? null : String(identity);
        } catch (error) {
            return null;
        }
    }

    function captureAuthContext() {
        const token = typeof window.AuthClient?.getToken === 'function'
            ? window.AuthClient.getToken()
            : null;
        return {
            token: typeof token === 'string' ? token : null,
            identity: authIdentityFromToken(token),
        };
    }

    function sameAuthOwner(expected, current) {
        if (!expected?.token || !current?.token) return false;
        if (expected.identity && current.identity) {
            return expected.identity === current.identity;
        }
        return expected.token === current.token;
    }

    function captureContext() {
        return {
            contextVersion: state.contextVersion,
            globalMode: state.globalMode,
            teamId: state.teamId,
            authContext: captureAuthContext(),
        };
    }

    function isCurrentContext(context) {
        return context.contextVersion === state.contextVersion
            && context.globalMode === state.globalMode
            && context.teamId === state.teamId
            && sameAuthOwner(context.authContext, captureAuthContext());
    }

    function beginMutation(context) {
        if (state.pendingMutation || !isCurrentContext(context)) return null;
        state.mutationVersion += 1;
        const mutation = {
            ...context,
            mutationVersion: state.mutationVersion,
        };
        state.pendingMutation = mutation;
        return mutation;
    }

    function isCurrentMutation(mutation) {
        return isCurrentContext(mutation)
            && mutation.mutationVersion === state.mutationVersion;
    }

    function finishMutation(mutation) {
        if (state.pendingMutation?.mutationVersion !== mutation.mutationVersion) return;
        state.pendingMutation = null;
    }



    function setHidden(element, hidden) {
        if (element) element.classList.toggle('d-none', hidden);
    }

    function setTableMessage(message, className = 'text-muted') {
        const tbody = byId('appTokenTableBody');
        if (!tbody) return;
        tbody.innerHTML = `<tr><td colspan="8" class="text-center ${className}">${escapeHtml(message)}</td></tr>`;
    }

    function setCurrentTeam(teamId, teamName) {
        state.teamId = validTeamId(teamId);
        state.teamName = state.teamId ? String(teamName || '') : '';
        const name = byId('appTokenTeamName');
        if (name) {
            name.textContent = state.globalMode
                ? translate('appToken.allTeams', {}, 'All teams')
                : state.teamName;
        }
        const createButton = byId('btnCreateAppToken');
        if (createButton) {
            createButton.disabled = state.globalMode
                ? state.availableTeams.length === 0
                : !state.teamId;
        }
    }

    async function authenticatedFetch(url, options) {
        if (!window.AuthClient || typeof window.AuthClient.fetch !== 'function') {
            throw new Error('Authentication client unavailable');
        }
        return window.AuthClient.fetch(url, options || {});
    }

    function hideCreateForm() {
        setHidden(byId('appTokenCreateForm'), true);
        setHidden(byId('appTokenOwnerTeamPicker'), true);
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
        if (!state.globalMode && !state.teamId) return;
        const ownerPicker = byId('appTokenOwnerTeamPicker');
        const ownerSelect = byId('appTokenOwnerTeamSelect');
        if (state.globalMode) {
            if (!ownerSelect || ownerSelect.disabled) return;
            ownerSelect.value = '';
            setHidden(ownerPicker, false);
        } else {
            setHidden(ownerPicker, true);
        }
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
            const ownerTeamId = validTeamId(token.owner_team_id);
            const ownerTeam = state.availableTeams.find(
                (team) => validTeamId(team.id) === ownerTeamId
            );
            const ownerTeamName = token.owner_team_name
                || ownerTeam?.name
                || (ownerTeamId
                    ? translate(
                        'appToken.teamFallback',
                        { id: ownerTeamId },
                        `Team #${ownerTeamId}`
                    )
                    : '-');
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
            const canRotate = isActive
                && Number.isInteger(tokenId)
                && tokenId > 0
                && (!state.globalMode || Boolean(ownerTeamId));
            const rotateButton = canRotate
                ? `<button type="button" class="btn btn-warning btn-sm me-1" data-app-token-action="rotate" data-token-id="${tokenId}" data-team-id="${ownerTeamId || ''}" aria-label="${rotateLabel}" title="${rotateLabel}"><i class="fas fa-sync-alt"></i></button>`
                : '';
            const revokeButton = isActive && Number.isInteger(tokenId) && tokenId > 0
                ? `<button type="button" class="btn btn-danger btn-sm" data-app-token-action="revoke" data-token-id="${tokenId}" aria-label="${revokeLabel}" title="${revokeLabel}"><i class="fas fa-ban"></i></button>`
                : '<span class="text-muted">-</span>';
            const actions = `${rotateButton}${revokeButton}`;
            return `<tr>
                <td>${escapeHtml(token.name)}</td>
                <td>${escapeHtml(ownerTeamName)}</td>
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
        const globalMode = state.globalMode;
        if (!globalMode && !teamId) return;
        const context = captureContext();
        const requestVersion = ++state.requestVersion;
        setTableMessage(translate('appToken.loading', {}, '載入中...'));

        try {
            const endpoint = globalMode
                ? '/api/app-tokens'
                : `/api/teams/${teamId}/app-tokens`;
            const response = await authenticatedFetch(endpoint);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (
                requestVersion !== state.requestVersion
                || !isCurrentContext(context)
            ) return;
            renderTokenList(Array.isArray(data.items) ? data.items : []);
        } catch (error) {
            if (
                requestVersion !== state.requestVersion
                || !isCurrentContext(context)
            ) return;
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

    async function loadAvailableTeams() {
        const select = byId('appTokenOwnerTeamSelect');
        const context = captureContext();
        const requestVersion = ++state.requestVersion;
        state.availableTeams = [];
        if (select) {
            select.replaceChildren();
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = translate(
                'appToken.selectOwnerTeamPlaceholder',
                {},
                'Select an owner team'
            );
            placeholder.selected = true;
            select.append(placeholder);
            select.disabled = true;
        }

        try {
            const response = await authenticatedFetch('/api/teams/');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const teams = await response.json();
            if (requestVersion !== state.requestVersion || !isCurrentContext(context)) return;
            const available = Array.isArray(teams)
                ? teams.filter((team) => validTeamId(team.id))
                : [];
            state.availableTeams = available;
            if (!available.length) {
                setTableMessage(
                    translate(
                        'appToken.noTeamsAvailable',
                        {},
                        '目前沒有可管理的團隊'
                    )
                );
                setCurrentTeam(null, '');
                return;
            }
            available.forEach((team) => {
                const option = document.createElement('option');
                option.value = String(team.id);
                option.textContent = String(team.name || team.id);
                select?.append(option);
            });
            if (select) select.disabled = false;
            setCurrentTeam(null, '');
        } catch (errorValue) {
            if (requestVersion !== state.requestVersion || !isCurrentContext(context)) return;
            setTableMessage(
                translate(
                    'appToken.loadTeamsFailedWithReason',
                    { reason: errorValue.message },
                    `載入團隊失敗：${errorValue.message}`
                ),
                'text-danger'
            );
            setCurrentTeam(null, '');
        }
    }

    async function createToken() {
        const context = captureContext();
        const teamId = context.globalMode
            ? validTeamId(byId('appTokenOwnerTeamSelect')?.value)
            : context.teamId;
        if (!teamId) {
            AppUtils.notify(translate(
                'appToken.ownerTeamRequired',
                {},
                'Please select an owner team'
            ));
            return;
        }
        const name = byId('appTokenName').value.trim();
        if (!name) {
            AppUtils.notify(translate('appToken.nameRequired', {}, '權杖名稱為必填項'));
            return;
        }
        const description = byId('appTokenDescription').value.trim() || null;
        const scopes = Array.from(
            document.querySelectorAll('#appTokenModal .app-token-scope:checked')
        ).map((checkbox) => checkbox.value);
        if (!scopes.length) {
            AppUtils.notify(translate('appToken.scopeRequired', {}, '至少需要選擇一個權限範圍'));
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
        if (context.globalMode) payload.owner_team_id = teamId;

        const mutation = beginMutation(context);
        if (!mutation) return;
        const confirmButton = byId('appTokenCreateConfirm');
        confirmButton.disabled = true;
        try {
            const endpoint = mutation.globalMode
                ? '/api/app-tokens'
                : `/api/teams/${mutation.teamId}/app-tokens`;
            const response = await authenticatedFetch(
                endpoint,
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
            if (!isCurrentMutation(mutation)) return;
            hideCreateForm();
            byId('appTokenRawToken').textContent = data.raw_token;
            setHidden(byId('appTokenRawTokenDisplay'), false);
            await loadTokens();
        } catch (error) {
            if (!isCurrentMutation(mutation)) return;
            AppUtils.notify(translate(
                'appToken.createFailedWithReason',
                { reason: error.message },
                `建立權杖失敗：${error.message}`
            ), 'danger');
        } finally {
            finishMutation(mutation);
            confirmButton.disabled = false;
        }
    }

    async function revokeToken(tokenId) {
        const context = captureContext();
        if (!context.globalMode && !context.teamId) return;
        if (!await AppUtils.confirm(translate(
            'appToken.revokeConfirm',
            {},
            '撤銷此權杖？此操作無法復原。'
        ))) return;
        const mutation = beginMutation(context);
        if (!mutation) return;

        try {
            const endpoint = mutation.globalMode
                ? `/api/app-tokens/${tokenId}`
                : `/api/teams/${mutation.teamId}/app-tokens/${tokenId}`;
            const response = await authenticatedFetch(
                endpoint,
                { method: 'DELETE' }
            );
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            if (!isCurrentMutation(mutation)) return;
            await loadTokens();
        } catch (error) {
            if (!isCurrentMutation(mutation)) return;
            AppUtils.notify(translate(
                'appToken.revokeFailedWithReason',
                { reason: error.message },
                `撤銷權杖失敗：${error.message}`
            ), 'danger');
        } finally {
            finishMutation(mutation);
        }
    }

    async function rotateToken(tokenId, ownerTeamId = null) {
        const context = captureContext();
        const teamId = context.globalMode
            ? validTeamId(ownerTeamId)
            : context.teamId;
        if (!context.globalMode && !teamId) return;
        if (context.globalMode && !teamId) return;
        if (!await AppUtils.confirm(translate(
            'appToken.rotateConfirm',
            {},
            '輪替此權杖？舊權杖將立即失效，沒有寬限期。'
        ))) return;
        const mutation = beginMutation(context);
        if (!mutation) return;

        try {
            const endpoint = mutation.globalMode
                ? `/api/app-tokens/${tokenId}/rotate`
                : `/api/teams/${mutation.teamId}/app-tokens/${tokenId}/rotate`;
            const response = await authenticatedFetch(
                endpoint,
                { method: 'POST' }
            );
            if (!response.ok) {
                const errorBody = await response.json().catch(() => ({}));
                throw new Error(errorBody.detail?.message || `HTTP ${response.status}`);
            }
            const data = await response.json();
            if (!isCurrentMutation(mutation)) return;
            byId('appTokenRawToken').textContent = data.raw_token;
            setHidden(byId('appTokenRawTokenDisplay'), false);
            await loadTokens();
        } catch (error) {
            if (!isCurrentMutation(mutation)) return;
            AppUtils.notify(translate(
                'appToken.rotateFailedWithReason',
                { reason: error.message },
                `輪替權杖失敗：${error.message}`
            ), 'danger');
        } finally {
            finishMutation(mutation);
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
        const ownerTeamId = validTeamId(button.dataset.teamId);
        if (button.dataset.appTokenAction === 'rotate') {
            rotateToken(tokenId, ownerTeamId);
        } else if (button.dataset.appTokenAction === 'revoke') {
            revokeToken(tokenId);
        }
    }

    function resetModal() {
        state.requestVersion += 1;
        state.contextVersion += 1;
        state.mutationVersion += 1;
        state.pendingMutation = null;
        state.authContext = captureAuthContext();
        state.globalMode = false;
        state.availableTeams = [];
        setCurrentTeam(null, '');
        hideCreateForm();
        hideRawToken();
        setTableMessage(
            translate(
                'appToken.teamContextRequired',
                {},
                'Select a team context to load App Tokens.'
            )
        );
    }

    function handleAuthChange(forceReset = false) {
        const nextAuthContext = captureAuthContext();
        if (!forceReset && !state.authContext) {
            state.authContext = nextAuthContext;
            return;
        }
        if (!forceReset && sameAuthOwner(state.authContext, nextAuthContext)) {
            state.authContext = nextAuthContext;
            return;
        }
        state.authContext = nextAuthContext;
        const modal = byId('appTokenModal');
        resetModal();
        if (modal && window.bootstrap?.Modal) {
            window.bootstrap.Modal.getInstance(modal)?.hide();
        }
    }

    function initialize() {
        if (state.initialized) return;
        const modal = byId('appTokenModal');
        if (!modal) return;
        state.initialized = true;
        state.authContext = captureAuthContext();
        byId('btnCreateAppToken').addEventListener('click', showCreateForm);
        byId('appTokenCreateConfirm').addEventListener('click', createToken);
        byId('appTokenCreateCancel').addEventListener('click', hideCreateForm);
        byId('appTokenNoExpiry').addEventListener('change', updateNoExpiryState);
        byId('appTokenCopy').addEventListener('click', copyRawToken);
        byId('appTokenTableBody').addEventListener('click', handleTokenAction);
        modal.addEventListener('hide.bs.modal', (event) => {
            if (!state.pendingMutation) return;
            event.preventDefault();
            AppUtils.notify(translate(
                'appToken.operationInProgress',
                {},
                'Please wait for the current App Token operation to finish.'
            ), 'warning');
        });
        modal.addEventListener('hidden.bs.modal', resetModal);
    }

    async function open(options = {}) {
        initialize();
        const modal = byId('appTokenModal');
        if (!modal || !window.bootstrap) return;
        if (state.pendingMutation) return;
        state.authContext = captureAuthContext();
        state.requestVersion += 1;
        state.contextVersion += 1;
        state.mutationVersion += 1;
        state.globalMode = options.allowAllTeams === true;
        state.availableTeams = [];
        hideCreateForm();
        hideRawToken();

        const teamId = validTeamId(options.teamId);
        if (state.globalMode) {
            setCurrentTeam(null, '');
            setTableMessage(translate('appToken.loading', {}, '載入中...'));
        } else if (teamId) {
            setCurrentTeam(teamId, options.teamName);
        } else {
            setCurrentTeam(null, '');
            setTableMessage(
                translate(
                    'appToken.teamContextRequired',
                    {},
                    'Select a team context to load App Tokens.'
                )
            );
        }

        window.bootstrap.Modal.getOrCreateInstance(modal).show();
        if (window.i18n && typeof window.i18n.retranslate === 'function') {
            window.i18n.retranslate(modal);
        }
        if (state.globalMode) {
            await loadAvailableTeams();
            await loadTokens();
        } else if (teamId) {
            await loadTokens();
        }
    }

    window.AppTokenModal = { open };
    window.openAppTokenModal = (teamId, teamName) => open({ teamId, teamName });
    ['authReady', 'tokenSet', 'tokenRefreshed', 'tokenCleared', 'logout'].forEach(
        (eventName) => document.addEventListener(eventName, () => handleAuthChange(false))
    );
    window.addEventListener('authStateChanged', () => handleAuthChange(false));
    window.addEventListener('storage', (eventValue) => {
        if (eventValue.key === 'access_token' || eventValue.key === 'token_expiry') {
            handleAuthChange(
                eventValue.key === 'access_token' && !eventValue.newValue
            );
        }
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }
})();
