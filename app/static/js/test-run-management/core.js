/* ============================================================
   TEST RUN MANAGEMENT - CORE
   ============================================================ */

// Test Run 配置管理
let testRunConfigs = [];
let testCaseSets = [];
let testRunSets = [];
let unassignedTestRuns = [];
let currentTeamId = null;
let configDetailModalInstance = null;
let configFormModalInstance = null;
let testRunSetFormModalInstance = null;
let testRunSetDetailModalInstance = null;
let addExistingToSetModalInstance = null;
let addExistingRunToSetModalInstance = null;
let currentAddToSetConfigId = null;
let currentSetContext = null;
let pendingSetIdForNewConfig = null;
// delete config modal is handled via bootstrap instance on demand

let testRunPermissions = {
    role: 'viewer',
    isViewer: true,
    canCreate: false,
    canUpdate: false,
    canDelete: false,
    canChangeStatus: false,
};

let currentStatusFilter = 'all';
let currentSetTpTickets = [];
let currentSetAutomationSuiteIds = [];
let currentSetAutomationSuiteOptions = [];
let currentSetAutomationSuiteSearch = '';
// Automation environment catalog for the current team (manage-automation-environment-configs).
// Cached per detail/form render; option "" sends nothing (team default).
let currentSetEnvironmentOptions = [];
let setTpInputInitialized = false;
let reopenSetDetailAfterForm = false;
let suppressSetDetailReopen = false;
let reopenSetDetailAfterCaseModal = false;
let preserveSetContextOnHide = false;

async function applyTestRunManagementPermissions() {
    const defaults = {
        role: 'viewer',
        isViewer: true,
        canCreate: false,
        canUpdate: false,
        canDelete: false,
        canChangeStatus: false,
    };

    if (!window.AuthClient) {
        testRunPermissions = defaults;
        window._testRunPermissions = defaults;
        return defaults;
    }

    let components = {};
    try {
        const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=test_run_management');
        if (resp && resp.ok) {
            const payload = await resp.json();
            if (payload && payload.components) {
                components = payload.components;
            }
        }
    } catch (error) {
        console.warn('Failed to fetch Test Run UI permissions:', error);
    }

    let role = 'viewer';
    try {
        const info = await window.AuthClient.getUserInfo();
        if (info && info.role) {
            role = String(info.role).toLowerCase();
        }
    } catch (error) {
        console.warn('Failed to resolve user role, fallback to viewer:', error);
    }

    const resolved = {
        role,
        isViewer: role === 'viewer',
        canCreate: !!(components.addConfigCard || components.saveConfigBtn),
        canUpdate: !!(components.editConfigBtn || components.saveConfigBtn),
        canDelete: !!components.deleteConfigBtn,
        canChangeStatus: !!(components.changeStatusBtn || components.editConfigBtn),
    };

    if (!resolved.isViewer) {
        resolved.canCreate = true;
        resolved.canUpdate = true;
        resolved.canDelete = true;
        resolved.canChangeStatus = true;
    }

    testRunPermissions = resolved;
    window._testRunPermissions = resolved;

    setElementVisibility('saveConfigBtn', resolved.canCreate || resolved.canUpdate);
    setElementVisibility('confirmCreateItemsBtn', resolved.canCreate || resolved.canUpdate);
    setElementVisibility('editConfigBtn', resolved.canUpdate);
    setElementVisibility('deleteConfigBtn', resolved.canDelete);

    return resolved;
}

function setElementVisibility(elementId, isVisible) {
    const element = document.getElementById(elementId);
    if (!element) return;

    if (!element.dataset.defaultDisplay || element.dataset.defaultDisplay === 'none') {
        let defaultDisplay = '';
        if (element.classList.contains('d-flex')) {
            defaultDisplay = 'flex';
        } else if (element.classList.contains('btn-group')) {
            defaultDisplay = 'inline-flex';
        } else if (element.tagName === 'BUTTON' || element.classList.contains('btn')) {
            defaultDisplay = 'inline-block';
        } else if (element.tagName === 'INPUT' || element.tagName === 'SELECT' || element.tagName === 'TEXTAREA') {
            defaultDisplay = 'block';
        } else {
            const computed = window.getComputedStyle(element).display;
            if (computed && computed !== 'none') {
                defaultDisplay = computed;
            }
        }
        element.dataset.defaultDisplay = defaultDisplay || '';
    }

    if (isVisible) {
        element.classList.remove('d-none');
        const displayValue = element.dataset.defaultDisplay;
        if (displayValue) {
            element.style.setProperty('display', displayValue, 'important');
        } else {
            element.style.removeProperty('display');
        }
    } else {
        element.classList.add('d-none');
        element.style.setProperty('display', 'none', 'important');
    }
}

function showPermissionDenied() {
    const message = window.i18n && window.i18n.isReady()
        ? window.i18n.t('messages.permissionDenied')
        : 'No permission to perform this action';
    if (window.AppUtils && typeof window.AppUtils.showWarning === 'function') {
        window.AppUtils.showWarning(message);
    } else {
        alert(message);
    }
}

// 頁面狀態旗標，避免競態與重複綁定
let teamIdReady = false;      // 取得有效 teamId 後才為 true
let dataLoadedOnce = false;   // 成功載入過資料後為 true
let eventsBound = false;      // 避免重複綁定 i18n/page 事件

// 檢視模式切換 (卡片 / 精簡列表)，套用至 Test Run Set / Ad-hoc / 未歸組三個區塊
let trmViewMode = 'card'; // 'card' | 'compact'
const TRM_VIEW_MODE_STORAGE_PREFIX = 'testRunManagement.viewMode.';

function trmViewModeStorageKey() {
    return currentTeamId ? `${TRM_VIEW_MODE_STORAGE_PREFIX}${currentTeamId}` : null;
}

function loadTrmViewModePreference() {
    const key = trmViewModeStorageKey();
    if (!key) return 'card';
    try {
        return window.localStorage.getItem(key) === 'compact' ? 'compact' : 'card';
    } catch (_e) {
        return 'card';
    }
}

function persistTrmViewModePreference(mode) {
    const key = trmViewModeStorageKey();
    if (!key) return;
    try {
        window.localStorage.setItem(key, mode);
    } catch (_e) {
        /* localStorage may be disabled; non-fatal */
    }
}

function applyTrmViewToggleVisual() {
    const cardBtn = document.getElementById('trmViewToggleCard');
    const compactBtn = document.getElementById('trmViewToggleCompact');
    if (cardBtn) cardBtn.classList.toggle('active', trmViewMode === 'card');
    if (compactBtn) compactBtn.classList.toggle('active', trmViewMode === 'compact');

    const pairs = [
        ['test-run-sets-container', 'test-run-sets-compact'],
        ['adhoc-runs-container', 'adhoc-runs-compact'],
        ['unassigned-test-runs-container', 'unassigned-test-runs-compact']
    ];
    pairs.forEach(([cardId, compactId]) => {
        const cardEl = document.getElementById(cardId);
        const compactEl = document.getElementById(compactId);
        if (cardEl) cardEl.classList.toggle('d-none', trmViewMode !== 'card');
        if (compactEl) compactEl.classList.toggle('d-none', trmViewMode !== 'compact');
    });
}

function switchTrmViewMode(mode) {
    if (mode !== 'card' && mode !== 'compact') return;
    if (trmViewMode === mode) return;
    trmViewMode = mode;
    persistTrmViewModePreference(mode);
    applyTrmViewToggleVisual();
}

function bindTrmViewToggleEvents() {
    const cardBtn = document.getElementById('trmViewToggleCard');
    const compactBtn = document.getElementById('trmViewToggleCompact');
    if (cardBtn && cardBtn.dataset.bound !== '1') {
        cardBtn.dataset.bound = '1';
        cardBtn.addEventListener('click', () => switchTrmViewMode('card'));
    }
    if (compactBtn && compactBtn.dataset.bound !== '1') {
        compactBtn.dataset.bound = '1';
        compactBtn.addEventListener('click', () => switchTrmViewMode('compact'));
    }
}
