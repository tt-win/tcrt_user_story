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
