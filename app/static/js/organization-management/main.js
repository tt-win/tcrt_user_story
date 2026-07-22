// 「組織與系統設定」頁面（/organization-management）主要 JS。
// 內容承接自 team-management/main.js 內原本掛在 team_management.html
// 「組織與系統設定」modal 的人員管理／組織同步／Service 管理／MCP Token 分頁邏輯；
// 差異：這裡是獨立頁面而非 modal，故移除 bootstrap.Modal 開關與
// modal 開/關狀態相關的 localStorage 邏輯（saveSyncModalState/loadSyncModalState），
// 改為頁面載入時直接載入資料；分頁切換（Bootstrap tab）行為不變。

let teams = [];
let mcpTokenListLoaded = false;
let mcpTokenItems = [];

function toggleSyncTabVisibility(id, visible, isLi = false) {
    const el = document.getElementById(id);
    if (!el) return;
    if (isLi) {
        el.style.display = visible ? '' : 'none';
        return;
    }
    const li = el.closest('li');
    if (li) {
        li.style.display = visible ? '' : 'none';
        return;
    }
    el.style.display = visible ? '' : 'none';
}

function normalizeClientRole(role) {
    return String(role || '').trim().toLowerCase();
}

function applyOrganizationUiVisibilityByRoleFallback() {
    const role = normalizeClientRole(window.currentUser?.role);
    const isSuperAdmin = role === 'super_admin' || role === 'superadmin';
    const isAdmin = role === 'admin';

    toggleSyncTabVisibility('tab-personnel-li', isAdmin || isSuperAdmin, true);
    toggleSyncTabVisibility('tab-org', isSuperAdmin);
    toggleSyncTabVisibility('tab-service-management', isSuperAdmin);
    toggleSyncTabVisibility('tab-mcp-token', isSuperAdmin);
    toggleAssistantAdminLinkVisibility(isSuperAdmin);
}

// assistantAdminLink 是頁面工具列上的一顆連結按鈕，不是分頁，故直接切換
// 自身的 d-none，不透過 toggleSyncTabVisibility（後者假設目標在 <li> 內）。
function toggleAssistantAdminLinkVisibility(visible) {
    const link = document.getElementById('assistantAdminLink');
    if (!link) return;
    link.classList.toggle('d-none', !visible);
}

// 依據後端 UI 能力控制頁面分頁可視
async function applyOrganizationUiVisibility() {
    // 預設先隱藏需權限頁籤，避免權限配置尚未載入時誤顯示
    toggleSyncTabVisibility('tab-org', false);
    toggleSyncTabVisibility('tab-service-management', false);
    toggleSyncTabVisibility('tab-mcp-token', false);
    toggleAssistantAdminLinkVisibility(false);

    try {
        if (!window.AuthClient) {
            applyOrganizationUiVisibilityByRoleFallback();
            return;
        }
        const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=organization');
        if (!resp.ok) {
            applyOrganizationUiVisibilityByRoleFallback();
            return;
        }
        const json = await resp.json();
        const map = json.components || {};
        const hasMcpTokenRule = Object.prototype.hasOwnProperty.call(map, 'tab-mcp-token');
        const mcpTokenVisible = hasMcpTokenRule ? !!map['tab-mcp-token'] : !!map['tab-org'];
        // 人員管理分頁（Admin/SuperAdmin 應允許）
        toggleSyncTabVisibility('tab-personnel-li', !!map['tab-personnel-li'], true);
        // 進階分頁（僅 Super Admin）
        toggleSyncTabVisibility('tab-org', !!map['tab-org']);
        toggleSyncTabVisibility('tab-service-management', !!map['tab-service-management']);
        toggleSyncTabVisibility('tab-mcp-token', mcpTokenVisible);
        // AI 助手設定入口（僅 Super Admin；後端另以 require_super_admin 防護）
        toggleAssistantAdminLinkVisibility(!!map['assistantAdminLink']);
    } catch (_) {
        applyOrganizationUiVisibilityByRoleFallback();
    }
}

document.addEventListener('DOMContentLoaded', async function() {
    await applyOrganizationUiVisibility();
    await loadTeamsForMcpTokenScope();
    initMcpTokenTab();
    await loadPageData();

    // 套用翻譯至整個頁面內容（含所有分頁，即使是隱藏的）
    try {
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(document.getElementById('syncTabsContent'));
        }
    } catch (e) {
        console.error('[Translation] Error:', e);
    }

    document.getElementById('startSyncBtn').addEventListener('click', () => startSyncFromModal('full'));
    document.getElementById('startDeptSyncBtn').addEventListener('click', () => startSyncFromModal('departments'));
    document.getElementById('startUserSyncBtn').addEventListener('click', () => startSyncFromModal('users'));
    const refreshBtn = document.getElementById('refreshSyncDataBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', refreshPageData);
});

// 取得 team 清單，供 MCP Token 分頁的 team-scope 多選使用。
// （team CRUD 本身留在 /team-management，這裡只需要唯讀清單。）
async function loadTeamsForMcpTokenScope() {
    try {
        if (!window.AuthClient) return;
        const response = await window.AuthClient.fetch('/api/teams/');
        if (!response.ok) return;
        teams = await response.json();
    } catch (error) {
        console.error('載入團隊清單失敗:', error);
        teams = [];
    }
}

function initMcpTokenTab() {
    const form = document.getElementById('mcpTokenForm');
    if (form) {
        form.addEventListener('submit', createMcpMachineToken);
    }

    const allowAllCheckbox = document.getElementById('mcpAllowAllTeams');
    if (allowAllCheckbox) {
        allowAllCheckbox.addEventListener('change', syncMcpTokenTeamScopeState);
    }

    const resetBtn = document.getElementById('mcpResetTokenFormBtn');
    if (resetBtn) {
        resetBtn.addEventListener('click', resetMcpTokenForm);
    }

    const copyBtn = document.getElementById('mcpCopyTokenBtn');
    if (copyBtn) {
        copyBtn.addEventListener('click', copyMcpTokenToClipboard);
    }

    const tokenRefreshBtn = document.getElementById('mcpTokenRefreshBtn');
    if (tokenRefreshBtn) {
        tokenRefreshBtn.addEventListener('click', loadMcpTokens);
    }

    // 分頁首次顯示時才載入列表（lazy load）；Refresh 鈕則強制重載
    const mcpTokenTabTrigger = document.getElementById('tab-mcp-token');
    if (mcpTokenTabTrigger) {
        mcpTokenTabTrigger.addEventListener('shown.bs.tab', () => {
            if (!mcpTokenListLoaded) loadMcpTokens();
        });
    }

    // 核發 modal：比照本專案其他 modal（org-automation-infra.js）以 JS new bootstrap.Modal
    // 開啟，不依賴 data-bs-toggle data-API。
    const mcpTokenCreateModalEl = document.getElementById('mcpTokenCreateModal');
    let mcpTokenCreateModalInstance = null;
    if (mcpTokenCreateModalEl && window.bootstrap && bootstrap.Modal) {
        mcpTokenCreateModalInstance = new bootstrap.Modal(mcpTokenCreateModalEl);
        // 開啟時重整可選團隊並清空表單（避免殘留上一次的一次性 token）
        mcpTokenCreateModalEl.addEventListener('show.bs.modal', () => {
            refreshMcpTokenTeamScopeOptions();
            resetMcpTokenForm();
        });
    }
    const mcpTokenOpenCreateBtn = document.getElementById('mcpTokenOpenCreateBtn');
    if (mcpTokenOpenCreateBtn) {
        mcpTokenOpenCreateBtn.addEventListener('click', () => {
            if (mcpTokenCreateModalInstance) mcpTokenCreateModalInstance.show();
        });
    }

    refreshMcpTokenTeamScopeOptions();
    syncMcpTokenTeamScopeState();
}

function refreshMcpTokenTeamScopeOptions() {
    const scopeSelect = document.getElementById('mcpTeamScopeIds');
    if (!scopeSelect) return;

    const selected = new Set(Array.from(scopeSelect.selectedOptions).map((option) => option.value));
    const availableTeams = Array.isArray(teams) ? [...teams] : [];
    availableTeams.sort((a, b) => Number(a.id || 0) - Number(b.id || 0));

    if (availableTeams.length === 0) {
        const noOptionsText = getI18n('mcpToken.noTeamOptions', '目前沒有可選擇的團隊');
        scopeSelect.innerHTML = `<option value="" disabled>${escapeHtml(noOptionsText)}</option>`;
        scopeSelect.disabled = true;
        return;
    }

    scopeSelect.innerHTML = availableTeams
        .map((team) => `<option value="${team.id}">${escapeHtml(team.name || `Team ${team.id}`)} (#${team.id})</option>`)
        .join('');

    Array.from(scopeSelect.options).forEach((option) => {
        option.selected = selected.has(option.value);
    });

    syncMcpTokenTeamScopeState();
}

function syncMcpTokenTeamScopeState() {
    const allowAllCheckbox = document.getElementById('mcpAllowAllTeams');
    const scopeSelect = document.getElementById('mcpTeamScopeIds');
    const hintEl = document.getElementById('mcpTeamScopeHint');
    if (!allowAllCheckbox || !scopeSelect) return;

    const hasTeams = Array.isArray(teams) && teams.length > 0;
    scopeSelect.disabled = allowAllCheckbox.checked || !hasTeams;
    if (allowAllCheckbox.checked) {
        Array.from(scopeSelect.options).forEach((option) => {
            option.selected = false;
        });
    }

    if (hintEl) {
        const key = allowAllCheckbox.checked ? 'mcpToken.teamScopeIgnoredHint' : 'mcpToken.teamScopeHint';
        const fallback = allowAllCheckbox.checked
            ? '已啟用所有團隊，team scope 將被忽略。'
            : '未啟用「所有團隊」時，至少選擇一個團隊。';
        hintEl.textContent = getI18n(key, fallback);
    }
}

function resetMcpTokenForm() {
    const form = document.getElementById('mcpTokenForm');
    if (form) form.reset();
    syncMcpTokenTeamScopeState();
    hideMcpTokenResult();
}

function hideMcpTokenResult() {
    const resultBox = document.getElementById('mcpTokenResult');
    const tokenValue = document.getElementById('mcpTokenValue');
    const tokenMeta = document.getElementById('mcpTokenMeta');
    if (tokenValue) tokenValue.textContent = '';
    if (tokenMeta) tokenMeta.textContent = '';
    if (resultBox) resultBox.classList.add('d-none');
}

function showMcpTokenResult(data) {
    const resultBox = document.getElementById('mcpTokenResult');
    const tokenValue = document.getElementById('mcpTokenValue');
    const tokenMeta = document.getElementById('mcpTokenMeta');
    if (!resultBox || !tokenValue || !tokenMeta) return;

    tokenValue.textContent = data.raw_token || '';
    const createdLabel = getI18n('mcpToken.createdAt', '建立時間');
    const expiresLabel = getI18n('mcpToken.expiresAt', '到期時間');
    const neverExpires = getI18n('mcpToken.neverExpires', '永不過期');
    const createdText = formatIsoDatetime(data.created_at);
    const expiresText = data.expires_at ? formatIsoDatetime(data.expires_at) : neverExpires;
    tokenMeta.textContent = `${createdLabel}: ${createdText} | ${expiresLabel}: ${expiresText}`;

    resultBox.classList.remove('d-none');
}

function formatIsoDatetime(rawValue) {
    if (!rawValue) return '-';
    const parsed = new Date(rawValue);
    if (Number.isNaN(parsed.getTime())) return rawValue;
    return parsed.toLocaleString();
}

function extractApiErrorMessage(payload) {
    if (!payload) return '';
    if (typeof payload === 'string') return payload;
    if (typeof payload.message === 'string' && payload.message.trim()) return payload.message;

    const detail = payload.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object') {
        if (typeof detail.message === 'string' && detail.message.trim()) return detail.message;
        if (typeof detail.code === 'string' && detail.code.trim()) return detail.code;
    }
    return '';
}

async function createMcpMachineToken(event) {
    if (event) event.preventDefault();

    const nameInput = document.getElementById('mcpTokenName');
    const descInput = document.getElementById('mcpTokenDescription');
    const expiresInput = document.getElementById('mcpTokenExpiresDays');
    const allowAllCheckbox = document.getElementById('mcpAllowAllTeams');
    const scopeSelect = document.getElementById('mcpTeamScopeIds');
    const submitBtn = document.getElementById('mcpCreateTokenBtn');
    if (!nameInput || !submitBtn || !allowAllCheckbox || !scopeSelect || !expiresInput || !descInput) return;

    const name = (nameInput.value || '').trim();
    if (!name) {
        AppUtils.showError(getI18n('mcpToken.requiredName', '請先填寫 token 名稱'));
        return;
    }

    const allowAllTeams = !!allowAllCheckbox.checked;
    const teamScopeIds = Array.from(scopeSelect.selectedOptions)
        .map((option) => Number(option.value))
        .filter((value) => Number.isInteger(value) && value > 0);

    if (!allowAllTeams && teamScopeIds.length === 0) {
        AppUtils.showError(getI18n('mcpToken.scopeRequired', '請至少選擇一個可存取團隊'));
        return;
    }

    const expiresText = (expiresInput.value || '').trim();
    const expiresInDays = expiresText ? Number(expiresText) : null;
    if (expiresText && (!Number.isInteger(expiresInDays) || expiresInDays <= 0)) {
        AppUtils.showError(getI18n('mcpToken.invalidExpiresDays', '有效天數需為正整數'));
        return;
    }

    const originalHtml = submitBtn.innerHTML;
    submitBtn.disabled = true;
    const progressLabel = escapeHtml(getI18n('mcpToken.createInProgress', '產生中...'));
    submitBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i><span>${progressLabel}</span>`;

    try {
        const response = await window.AuthClient.fetch('/api/organization/mcp/machine-tokens', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({
                name,
                description: (descInput.value || '').trim() || null,
                allow_all_teams: allowAllTeams,
                team_scope_ids: teamScopeIds,
                expires_in_days: expiresInDays
            })
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.success || !payload.data) {
            const message = extractApiErrorMessage(payload) || `${response.status}`;
            throw new Error(message);
        }

        showMcpTokenResult(payload.data);
        AppUtils.showSuccess(getI18n('mcpToken.createSuccess', 'MCP machine token 已建立'));

        const resetForm = document.getElementById('mcpTokenForm');
        if (resetForm) resetForm.reset();
        syncMcpTokenTeamScopeState();
        loadMcpTokens();
    } catch (error) {
        console.error('建立 MCP machine token 失敗:', error);
        const prefix = getI18n('mcpToken.createFailedPrefix', '建立 token 失敗');
        AppUtils.showError(`${prefix}：${error.message}`);
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalHtml;
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(submitBtn);
        }
    }
}

async function copyMcpTokenToClipboard() {
    const tokenValue = document.getElementById('mcpTokenValue');
    const value = tokenValue ? (tokenValue.textContent || '').trim() : '';
    if (!value) return;

    try {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            await navigator.clipboard.writeText(value);
            AppUtils.showSuccess(getI18n('mcpToken.copySuccess', '已複製 token'));
            return;
        }
        throw new Error('Clipboard API unavailable');
    } catch (_) {
        if (AppUtils && typeof AppUtils.showCopyModal === 'function') {
            AppUtils.showCopyModal(value, {
                title: getI18n('mcpToken.copyModalTitle', '手動複製 Token'),
                instruction: getI18n('mcpToken.copyModalInstruction', '請使用 Ctrl/Cmd + C 進行複製'),
                urlLabel: getI18n('mcpToken.rawTokenLabel', 'Raw Token')
            });
            return;
        }
        AppUtils.showWarning(getI18n('mcpToken.copyFallback', '無法直接複製，請手動複製 token'));
    }
}

async function loadMcpTokens() {
    const loadingEl = document.getElementById('mcpTokenListLoading');
    const emptyEl = document.getElementById('mcpTokenListEmpty');
    const tableWrap = document.getElementById('mcpTokenTableWrap');
    const tbody = document.getElementById('mcpTokenTableBody');
    if (!tbody) return;

    mcpTokenListLoaded = true;

    if (loadingEl) loadingEl.classList.remove('d-none');
    if (emptyEl) emptyEl.classList.add('d-none');
    if (tableWrap) tableWrap.classList.add('d-none');

    try {
        if (!window.AuthClient) throw new Error('AuthClient 尚未初始化');
        const response = await window.AuthClient.fetch('/api/organization/mcp/machine-tokens');
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.success || !payload.data) {
            const message = extractApiErrorMessage(payload) || `${response.status}`;
            throw new Error(message);
        }

        mcpTokenItems = Array.isArray(payload.data.items) ? payload.data.items : [];
        tbody.innerHTML = mcpTokenItems.map(renderMcpTokenRow).join('');
        bindMcpTokenRowActions();

        if (loadingEl) loadingEl.classList.add('d-none');
        if (mcpTokenItems.length === 0) {
            if (emptyEl) emptyEl.classList.remove('d-none');
            if (tableWrap) tableWrap.classList.add('d-none');
        } else if (tableWrap) {
            tableWrap.classList.remove('d-none');
        }
    } catch (error) {
        console.error('載入 MCP machine token 列表失敗:', error);
        if (loadingEl) loadingEl.classList.add('d-none');
        if (tableWrap) tableWrap.classList.add('d-none');
        if (emptyEl) emptyEl.classList.add('d-none');
        const loadFailedLabel = getI18n('mcpToken.listLoadFailed', '載入 token 列表失敗');
        AppUtils.showError(`${loadFailedLabel}：${error.message}`);
    }
}

function deriveMcpTokenDisplayStatus(item) {
    if (String(item.status || '').toLowerCase() === 'revoked') return 'revoked';
    if (item.expires_at) {
        const expires = new Date(item.expires_at);
        if (!Number.isNaN(expires.getTime()) && expires.getTime() <= Date.now()) {
            return 'expired';
        }
    }
    return 'active';
}

function renderMcpTokenStatusBadge(status) {
    const map = {
        active: { cls: 'bg-success', key: 'mcpToken.statusActive', fallback: 'Active' },
        revoked: { cls: 'bg-secondary', key: 'mcpToken.statusRevoked', fallback: 'Revoked' },
        expired: { cls: 'bg-warning text-dark', key: 'mcpToken.statusExpired', fallback: 'Expired' }
    };
    const conf = map[status] || map.active;
    return `<span class="badge ${conf.cls}">${escapeHtml(getI18n(conf.key, conf.fallback))}</span>`;
}

function renderMcpTokenRow(item) {
    const status = deriveMcpTokenDisplayStatus(item);
    const name = escapeHtml(item.name || '');
    const scope = item.allow_all_teams
        ? escapeHtml(getI18n('mcpToken.scopeAllTeams', '所有團隊'))
        : (Array.isArray(item.team_scope_ids) && item.team_scope_ids.length
            ? escapeHtml(item.team_scope_ids.map((id) => `#${id}`).join(', '))
            : '-');
    const neverExpires = getI18n('mcpToken.neverExpires', '永不過期');
    const neverUsed = getI18n('mcpToken.neverUsed', '從未');
    const expires = item.expires_at ? escapeHtml(formatIsoDatetime(item.expires_at)) : escapeHtml(neverExpires);
    const lastUsed = item.last_used_at ? escapeHtml(formatIsoDatetime(item.last_used_at)) : escapeHtml(neverUsed);
    const created = escapeHtml(formatIsoDatetime(item.created_at));

    let actions = '';
    if (status !== 'revoked') {
        const revokeLabel = escapeHtml(getI18n('mcpToken.revokeButton', '撤銷'));
        actions = `<button type="button" class="btn btn-outline-danger btn-sm mcp-token-revoke-btn" data-credential-id="${item.credential_id}"><i class="fas fa-ban me-1"></i>${revokeLabel}</button>`;
    }

    return `<tr>
        <td>${name}</td>
        <td>${renderMcpTokenStatusBadge(status)}</td>
        <td>${scope}</td>
        <td>${expires}</td>
        <td>${lastUsed}</td>
        <td>${created}</td>
        <td class="text-end">${actions}</td>
    </tr>`;
}

function bindMcpTokenRowActions() {
    document.querySelectorAll('#mcpTokenTableBody .mcp-token-revoke-btn').forEach((btn) => {
        btn.addEventListener('click', () => revokeMcpToken(btn.getAttribute('data-credential-id')));
    });
}

async function revokeMcpToken(credentialId) {
    const item = mcpTokenItems.find((entry) => String(entry.credential_id) === String(credentialId));
    const name = item && item.name ? item.name : `#${credentialId}`;
    const confirmTpl = getI18n('mcpToken.revokeConfirm', '確定要撤銷 token「{name}」嗎？撤銷後該 token 將立即失效且無法復原。');
    if (!window.confirm(confirmTpl.replace('{name}', name))) return;

    try {
        if (!window.AuthClient) throw new Error('AuthClient 尚未初始化');
        const response = await window.AuthClient.fetch(`/api/organization/mcp/machine-tokens/${encodeURIComponent(credentialId)}`, {
            method: 'DELETE',
            headers: { 'Accept': 'application/json' }
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.success) {
            const message = extractApiErrorMessage(payload) || `${response.status}`;
            throw new Error(message);
        }
        AppUtils.showSuccess(getI18n('mcpToken.revokeSuccess', 'Token 已撤銷'));
        await loadMcpTokens();
    } catch (error) {
        console.error('撤銷 MCP machine token 失敗:', error);
        const prefix = getI18n('mcpToken.revokeFailedPrefix', '撤銷 token 失敗');
        AppUtils.showError(`${prefix}：${error.message}`);
    }
}

function escapeHtml(text) {
    // Coerce non-strings (ids are often numbers). Do not use !text — 0 is valid.
    if (text == null || text === '') return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, function(m) { return map[m]; });
}

// 更新頁面標題翻譯
function updatePageTitle() {
    const pageTitle = window.i18n ? window.i18n.t('orgSync.modalTitle') : '組織與系統設定';
    const siteTitle = window.i18n ? window.i18n.t('navigation.title') : 'Test Case Repository';
    document.title = `${pageTitle} - ${siteTitle} Web Tool`;
}

// 監聽 i18n 初始化和語言變更事件
document.addEventListener('i18nReady', updatePageTitle);
document.addEventListener('languageChanged', updatePageTitle);

// ===== 頁面資料載入（原「同步功能框」內容，改為頁面載入即執行） =====

let syncPollingInterval = null;
let scheduledServicesState = {
    services: [],
    loading: false,
};

async function loadPageData() {
    await Promise.all([
        loadSyncStatus(),
        loadOrgStats(),
        loadScheduledServices(),
    ]);
}

async function refreshPageData() {
    const refreshBtn = document.getElementById('refreshSyncDataBtn');
    const originalHtml = refreshBtn.innerHTML;

    refreshBtn.disabled = true;
    refreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>重新整理中...';

    try {
        await loadPageData();
    } finally {
        refreshBtn.disabled = false;
        refreshBtn.innerHTML = originalHtml;
    }
}

async function loadScheduledServices() {
    const tabBtn = document.getElementById('tab-service-management');
    if (!tabBtn || tabBtn.style.display === 'none' || tabBtn.offsetParent === null) {
        return;
    }

    const loading = document.getElementById('scheduledServicesLoading');
    const empty = document.getElementById('scheduledServicesEmpty');
    const list = document.getElementById('scheduledServicesList');
    const summary = document.getElementById('scheduledServicesSummary');
    const schedulerState = document.getElementById('scheduledSchedulerState');
    if (!loading || !empty || !list || !summary || !schedulerState) return;

    scheduledServicesState.loading = true;
    loading.classList.remove('d-none');
    empty.classList.add('d-none');
    list.innerHTML = '';
    setDynamicI18nText(summary, 'scheduledServices.summaryLoading', '正在載入排程服務...');
    setDynamicI18nText(schedulerState, 'scheduledServices.schedulerUnknown', '狀態未知');
    schedulerState.className = 'badge rounded-pill text-bg-secondary';

    try {
        const response = await window.AuthClient.fetch('/api/organization/scheduled-services');
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(extractApiErrorMessage(payload) || `HTTP ${response.status}`);
        }

        const services = Array.isArray(payload.data?.services) ? payload.data.services : [];
        scheduledServicesState.services = services;

        setDynamicI18nText(
            schedulerState,
            payload.data?.scheduler_running ? 'scheduledServices.schedulerRunning' : 'scheduledServices.schedulerStopped',
            payload.data?.scheduler_running ? 'Scheduler 運行中' : 'Scheduler 未啟動'
        );
        schedulerState.className = payload.data?.scheduler_running
            ? 'badge rounded-pill text-bg-success'
            : 'badge rounded-pill text-bg-secondary';

        if (services.length === 0) {
            empty.classList.remove('d-none');
            setDynamicI18nText(empty, 'scheduledServices.empty', '目前沒有可排程服務');
            setDynamicI18nText(summary, 'scheduledServices.summaryEmpty', '目前沒有可排程服務');
            return;
        }

        setDynamicI18nText(summary, 'scheduledServices.summaryReady', '可管理 {count} 個排程服務', { count: services.length });
        list.innerHTML = services.map(renderScheduledServiceCard).join('');
    } catch (error) {
        console.error('載入排程服務失敗:', error);
        empty.classList.remove('d-none');
        empty.removeAttribute('data-i18n');
        empty.removeAttribute('data-i18n-params');
        empty.innerHTML = `<i class="fas fa-exclamation-circle me-2 text-danger"></i>${escapeHtml(getI18n('scheduledServices.loadFailed', '載入排程服務失敗'))}`;
        setDynamicI18nText(summary, 'scheduledServices.summaryError', '無法取得排程服務資料');
        setDynamicI18nText(schedulerState, 'scheduledServices.schedulerUnknown', '狀態未知');
        schedulerState.className = 'badge rounded-pill text-bg-secondary';
    } finally {
        scheduledServicesState.loading = false;
        loading.classList.add('d-none');
    }
}

function renderScheduledServiceCard(service) {
    const statusClass = getScheduledServiceStatusClass(service.last_run_status, service.is_running);
    const statusText = getScheduledServiceStatusText(service.last_run_status, service.is_running);
    const enabledBadge = service.enabled
        ? `<span class="badge rounded-pill text-bg-primary-subtle text-primary-emphasis">${escapeHtml(getI18n('scheduledServices.enabled', '已啟用'))}</span>`
        : `<span class="badge rounded-pill text-bg-light text-secondary">${escapeHtml(getI18n('scheduledServices.disabled', '未啟用'))}</span>`;
    const runningBadge = service.is_running
        ? `<span class="badge rounded-pill text-bg-warning-subtle text-warning-emphasis">${escapeHtml(getI18n('scheduledServices.running', '執行中'))}</span>`
        : '';

    return `
        <section class="scheduled-service-card" data-service-key="${escapeHtml(service.service_key)}">
            <div class="scheduled-service-card__head">
                <div>
                    <div class="scheduled-service-card__eyebrow">${escapeHtml(service.service_key)}</div>
                    <h6 class="scheduled-service-card__title mb-1">${escapeHtml(service.display_name || service.service_key)}</h6>
                    <p class="scheduled-service-card__desc mb-0">${escapeHtml(service.description || getI18n('scheduledServices.noDescription', '尚未提供描述'))}</p>
                </div>
                <div class="scheduled-service-card__badges">
                    ${enabledBadge}
                    ${runningBadge}
                    <span class="badge rounded-pill ${statusClass}">${escapeHtml(statusText)}</span>
                </div>
            </div>
            <div class="scheduled-service-card__grid">
                <div class="scheduled-service-card__metric">
                    <span class="scheduled-service-card__label">${escapeHtml(getI18n('scheduledServices.nextRun', '下次執行'))}</span>
                    <strong>${escapeHtml(formatIsoDatetime(service.next_run || ''))}</strong>
                </div>
                <div class="scheduled-service-card__metric">
                    <span class="scheduled-service-card__label">${escapeHtml(getI18n('scheduledServices.lastRun', '上次執行'))}</span>
                    <strong>${escapeHtml(formatIsoDatetime(service.last_run_finished_at || service.last_run || ''))}</strong>
                </div>
                <div class="scheduled-service-card__metric">
                    <span class="scheduled-service-card__label">${escapeHtml(getI18n('scheduledServices.runTime', '每日時間'))}</span>
                    <strong>${escapeHtml(service.run_at_time || '--:--')}</strong>
                </div>
                <div class="scheduled-service-card__metric">
                    <span class="scheduled-service-card__label">${escapeHtml(getI18n('scheduledServices.lastMessage', '最近訊息'))}</span>
                    <strong>${escapeHtml(service.last_run_message || service.last_error || getI18n('scheduledServices.noRecentMessage', '尚無執行紀錄'))}</strong>
                </div>
            </div>
            <form class="scheduled-service-card__form" data-service-form="${escapeHtml(service.service_key)}">
                <label class="form-check form-switch mb-0">
                    <input class="form-check-input" type="checkbox" name="enabled" ${service.enabled ? 'checked' : ''}>
                    <span class="form-check-label">${escapeHtml(getI18n('scheduledServices.enableSchedule', '啟用每日排程'))}</span>
                </label>
                <div class="scheduled-service-card__timebox">
                    <label class="form-label mb-1" for="scheduled-time-${escapeHtml(service.service_key)}">${escapeHtml(getI18n('scheduledServices.timeLabel', '執行時間'))}</label>
                    <input type="time" class="form-control" id="scheduled-time-${escapeHtml(service.service_key)}" name="run_at_time" value="${escapeHtml(service.run_at_time || '02:00')}">
                </div>
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-clock me-2"></i><span>${escapeHtml(getI18n('scheduledServices.saveSchedule', '儲存排程'))}</span>
                </button>
            </form>
            <div class="scheduled-service-card__hint text-muted small">${escapeHtml(getI18n('scheduledServices.timeHint', '第一版支援每日固定時間排程；多副本部署需額外處理 leader lock。'))}</div>
        </section>
    `;
}

function getScheduledServiceStatusClass(status, isRunning) {
    if (isRunning) return 'text-bg-warning-subtle text-warning-emphasis';
    switch (String(status || '').toLowerCase()) {
        case 'completed':
            return 'text-bg-success-subtle text-success-emphasis';
        case 'failed':
            return 'text-bg-danger-subtle text-danger-emphasis';
        case 'interrupted':
            return 'text-bg-secondary';
        case 'running':
            return 'text-bg-warning-subtle text-warning-emphasis';
        default:
            return 'text-bg-light text-secondary';
    }
}

function getScheduledServiceStatusText(status, isRunning) {
    if (isRunning) return getI18n('scheduledServices.running', '執行中');
    switch (String(status || '').toLowerCase()) {
        case 'completed':
            return getI18n('scheduledServices.statusCompleted', '最近成功');
        case 'failed':
            return getI18n('scheduledServices.statusFailed', '最近失敗');
        case 'interrupted':
            return getI18n('scheduledServices.statusInterrupted', '啟動時回收');
        case 'running':
            return getI18n('scheduledServices.running', '執行中');
        default:
            return getI18n('scheduledServices.statusUnknown', '尚未執行');
    }
}

async function handleScheduledServiceSubmit(event) {
    event.preventDefault();
    const form = event.target;
    const card = form.closest('[data-service-key]');
    const serviceKey = card?.dataset?.serviceKey;
    if (!serviceKey) return;

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalHtml = submitBtn ? submitBtn.innerHTML : '';
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>${escapeHtml(getI18n('scheduledServices.saving', '儲存中...'))}`;
    }

    const enabled = !!form.querySelector('input[name="enabled"]')?.checked;
    const runAtTime = form.querySelector('input[name="run_at_time"]')?.value || '';

    try {
        const response = await window.AuthClient.fetch(`/api/organization/scheduled-services/${encodeURIComponent(serviceKey)}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                enabled,
                run_at_time: runAtTime,
            })
        });
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(extractApiErrorMessage(payload) || `HTTP ${response.status}`);
        }

        AppUtils.showSuccess(getI18n('scheduledServices.saveSuccess', '排程設定已更新'));
        await loadScheduledServices();
    } catch (error) {
        console.error('更新排程服務失敗:', error);
        AppUtils.showError(`${getI18n('scheduledServices.saveFailed', '更新排程設定失敗')}: ${error.message}`);
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalHtml;
        }
    }
}

// 載入同步狀態
async function loadSyncStatus() {
    // 比照 loadScheduledServices()：分頁對目前角色不可見時不發請求，避免無權限
    // 檢視此分頁的角色（例如一般 user 直接開啟本頁）在頁面載入時就打一輪本來看不到的 API。
    const orgTabBtn = document.getElementById('tab-org');
    if (!orgTabBtn || orgTabBtn.closest('li')?.style.display === 'none') {
        return;
    }

    const loadingDiv = document.getElementById('syncStatusLoading');
    const idleDiv = document.getElementById('syncStatusIdle');
    const runningDiv = document.getElementById('syncStatusRunning');

    loadingDiv.classList.remove('d-none');
    idleDiv.classList.add('d-none');
    runningDiv.classList.add('d-none');

    try {
        const response = await window.AuthClient.fetch('/api/organization/sync/status');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const result = await response.json();
        if (result.success && result.data) {
            const data = result.data;

            loadingDiv.classList.add('d-none');

            if (data.is_syncing) {
                setSyncStatus('running');
                startSyncPolling();
            } else {
                setSyncStatus('idle');

                if (data.last_sync_end) {
                    const lastSyncDiv = document.getElementById('lastSyncTime');
                    const lastPrefix = getI18n('orgSync.lastSyncPrefix', '最後同步:');
                    lastSyncDiv.textContent = `${lastPrefix} ${new Date(data.last_sync_end).toLocaleString()}`;
                }
            }
        }
    } catch (error) {
        console.error('載入同步狀態失敗:', error);
        loadingDiv.classList.add('d-none');
        setSyncStatus('idle');
    }
}

function setSyncStatus(mode) {
    const idleDiv = document.getElementById('syncStatusIdle');
    const runningDiv = document.getElementById('syncStatusRunning');
    const startBtn = document.getElementById('startSyncBtn');
    const deptBtn = document.getElementById('startDeptSyncBtn');
    const userBtn = document.getElementById('startUserSyncBtn');

    if (mode === 'running') {
        idleDiv.classList.add('d-none');
        runningDiv.classList.remove('d-none');
        if (startBtn) startBtn.disabled = true;
        if (deptBtn) deptBtn.disabled = true;
        if (userBtn) userBtn.disabled = true;
    } else if (mode === 'idle') {
        runningDiv.classList.add('d-none');
        idleDiv.classList.remove('d-none');
        if (startBtn) startBtn.disabled = false;
        if (deptBtn) deptBtn.disabled = false;
        if (userBtn) userBtn.disabled = false;
        // 在同步完成後恢復按鈕原始內容（避免仍然顯示「啟動中…」並丟失 i18n 標籤）
        restoreSyncActionButtons();
        try {
            if (window.i18n && window.i18n.isReady()) {
                window.i18n.retranslate(document.getElementById('tab-pane-org'));
            }
        } catch (_) {}
    } else {
        runningDiv.classList.add('d-none');
        idleDiv.classList.add('d-none');
        if (startBtn) startBtn.disabled = false;
        if (deptBtn) deptBtn.disabled = false;
        if (userBtn) userBtn.disabled = false;
    }
}

// 恢復同步操作按鈕的原始圖示與文字（含 i18n 標籤）
function restoreSyncActionButtons() {
    const deptBtn = document.getElementById('startDeptSyncBtn');
    const userBtn = document.getElementById('startUserSyncBtn');
    const startBtn = document.getElementById('startSyncBtn');

    if (deptBtn) {
        deptBtn.innerHTML = '<i class="fas fa-sitemap me-2"></i><span data-i18n="orgSync.departmentsSync">部門同步</span>';
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(deptBtn);
        }
    }
    if (userBtn) {
        userBtn.innerHTML = '<i class="fas fa-address-book me-2"></i><span data-i18n="orgSync.contactsSync">用戶同步</span>';
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(userBtn);
        }
    }
    if (startBtn) {
        startBtn.innerHTML = '<i class="fas fa-play me-2"></i><span data-i18n="orgSync.fullSync">完整同步</span>';
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(startBtn);
        }
    }
}

// 載入組織統計
async function loadOrgStats() {
    const orgTabBtn = document.getElementById('tab-org');
    if (!orgTabBtn || orgTabBtn.closest('li')?.style.display === 'none') {
        return;
    }

    const loadingDiv = document.getElementById('orgStatsLoading');
    const dataDiv = document.getElementById('orgStatsData');
    const errorDiv = document.getElementById('orgStatsError');

    loadingDiv.style.display = 'block';
    dataDiv.style.display = 'none';
    errorDiv.style.display = 'none';

    try {
        // 加上時間戳避免瀏覽器快取造成數字不更新
        const response = await window.AuthClient.fetch(`/api/organization/stats?t=${Date.now()}`);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const result = await response.json();
        if (result.success && result.data) {
            const data = result.data;

            document.getElementById('totalDepartments').textContent = data.departments?.total_departments || 0;
            document.getElementById('totalUsers').textContent = data.users?.total_users || 0;

            loadingDiv.style.display = 'none';
            dataDiv.style.display = 'block';
        } else {
            throw new Error('API 返回錯誤');
        }
    } catch (error) {
        console.error('載入組織統計失敗:', error);
        loadingDiv.style.display = 'none';
        errorDiv.style.display = 'block';
    }
}

// 觸發同步（部門/用戶/完整）
async function startSyncFromModal(syncType = 'full') {
    const startBtn = syncType === 'full' ? document.getElementById('startSyncBtn') :
        (syncType === 'departments' ? document.getElementById('startDeptSyncBtn') : document.getElementById('startUserSyncBtn'));
    const originalHtml = startBtn.innerHTML;

    startBtn.disabled = true;
    startBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>啟動中...';

    try {
        // Guard: ensure not already syncing
        try {
            const statusResp = await window.AuthClient.fetch('/api/organization/sync/status');
            if (statusResp.ok) {
                const statusJson = await statusResp.json();
                if (statusJson.success && statusJson.data && statusJson.data.is_syncing) {
                    AppUtils.showWarning(getI18n('orgSync.syncing', '同步進行中'));
                    startBtn.disabled = false;
                    startBtn.innerHTML = originalHtml;
                    return;
                }
            }
        } catch (_) {}

        const response = await window.AuthClient.fetch(`/api/organization/sync?sync_type=${syncType}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.success) {
            await loadSyncStatus();
            // 保存觸發用戶到localStorage，用於後續的Toast通知（僅在此頁面內有效，
            // 不再與 team_management 頁面共用同一份 modal 狀態）
            localStorage.setItem('sync_trigger_user', 'user-sync-modal');
            AppUtils.showSuccess(getI18n('orgSync.syncStarted', '組織架構同步已啟動'));
        } else {
            throw new Error(result.message || '同步啟動失敗');
        }
    } catch (error) {
        console.error('啟動同步失敗:', error);
        AppUtils.showError(getI18n('orgSync.startFailedPrefix', '啟動同步失敗') + '：' + error.message);

        startBtn.disabled = false;
        startBtn.innerHTML = originalHtml;
    }
}

// 開始同步狀態輪詢
function startSyncPolling() {
    if (syncPollingInterval) {
        clearInterval(syncPollingInterval);
    }

    let pollCount = 0;
    const maxPolls = 120; // 10分鐘最大輪詢時間

    const poll = async () => {
        try {
            const response = await window.AuthClient.fetch('/api/organization/sync/status');

            if (response.ok) {
                const result = await response.json();

                if (result.success && result.data) {
                    const data = result.data;

                    if (!data.is_syncing) {
                        clearInterval(syncPollingInterval);
                        syncPollingInterval = null;

                        await loadPageData();
                        try { await loadOrgStats(); } catch (_) {}

                        const triggerUser = localStorage.getItem('sync_trigger_user');
                        if (triggerUser === 'user-sync-modal') {
                            AppUtils.showSuccess(getI18n('orgSync.syncCompleted', '組織架構同步已完成！'));
                            localStorage.removeItem('sync_trigger_user');
                        }
                    } else {
                        setSyncStatus('running');
                    }
                }
            }

            pollCount++;
            if (pollCount >= maxPolls) {
                clearInterval(syncPollingInterval);
                syncPollingInterval = null;
                AppUtils.showWarning(getI18n('orgSync.statusTimeout', '同步狀態檢查超時，請手動刷新查看結果'));
                document.getElementById('startSyncBtn').disabled = false;
                const deptBtn = document.getElementById('startDeptSyncBtn');
                const userBtn = document.getElementById('startUserSyncBtn');
                if (deptBtn) deptBtn.disabled = false;
                if (userBtn) userBtn.disabled = false;
                try { await loadOrgStats(); } catch (_) {}
            }
        } catch (error) {
            console.error('輪詢同步狀態失敗:', error);
        }
    };

    // 每5秒輪詢一次
    syncPollingInterval = setInterval(poll, 5000);
}

// ===== 分頁切換時重新套用翻譯／延遲載入 =====
document.addEventListener('DOMContentLoaded', () => {
    const orgTabBtn = document.getElementById('tab-org');
    const orgPane = document.getElementById('tab-pane-org');
    if (orgTabBtn && orgPane) {
        orgTabBtn.addEventListener('shown.bs.tab', () => {
            try {
                if (window.i18n && window.i18n.isReady()) {
                    window.i18n.retranslate(orgPane);
                }
            } catch (_) {}
        });
    }

    const mcpTokenTabBtn = document.getElementById('tab-mcp-token');
    const mcpTokenPane = document.getElementById('tab-pane-mcp-token');
    if (mcpTokenTabBtn && mcpTokenPane) {
        mcpTokenTabBtn.addEventListener('shown.bs.tab', () => {
            refreshMcpTokenTeamScopeOptions();
            try {
                if (window.i18n && window.i18n.isReady()) {
                    window.i18n.retranslate(mcpTokenPane);
                }
            } catch (_) {}
        });
    }

    const scheduledTabBtn = document.getElementById('tab-service-management');
    const scheduledPane = document.getElementById('tab-pane-service-management');
    if (scheduledTabBtn && scheduledPane) {
        scheduledTabBtn.addEventListener('shown.bs.tab', async () => {
            await loadScheduledServices();
            try {
                if (window.i18n && window.i18n.isReady()) {
                    window.i18n.retranslate(scheduledPane);
                }
            } catch (_) {}
        });

        scheduledPane.addEventListener('submit', (event) => {
            const form = event.target.closest('[data-service-form]');
            if (!form) return;
            handleScheduledServiceSubmit(event);
        });
    }
});

// ===== i18n helper without calling window.i18n.t =====
function getI18n(key, fallback = '') {
    const container = document.getElementById('org-sync-i18n');
    if (!container) return fallback || key;
    const el = container.querySelector(`[data-i18n="${key}"]`);
    if (el && el.textContent && el.textContent.trim().length > 0) {
        return el.textContent.trim();
    }
    return fallback || key;
}

function setDynamicI18nText(element, key, fallback = '', params = null) {
    if (!element) return;

    if (key) {
        element.setAttribute('data-i18n', key);
    } else {
        element.removeAttribute('data-i18n');
    }

    if (params && Object.keys(params).length > 0) {
        element.setAttribute('data-i18n-params', JSON.stringify(params));
    } else {
        element.removeAttribute('data-i18n-params');
    }

    const translated = key ? getI18n(key, fallback) : (fallback || '');
    element.textContent = applyI18nParams(translated, params);
}

function applyI18nParams(template, params) {
    let output = String(template || '');
    if (!params) return output;

    Object.entries(params).forEach(([key, value]) => {
        output = output.split(`{${key}}`).join(String(value));
    });
    return output;
}
