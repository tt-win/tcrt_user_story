/* Test Run Execution - Core */

// Test Run 執行頁面
let currentConfigId = null;
let currentTeamId = null; // 由 AppUtils 取得，無則退回 1
let testRunConfig = null;
let testRunItems = [];
const EXECUTION_STATUS_VALUES = ['Passed', 'Failed', 'Retest', 'Not Available', 'Pending', 'Not Required', 'Skip', 'Not Executed'];
const executionFilterState = {
    statuses: new Set(['ALL']),
    searchNumber: '',
    searchTitle: '',
    priority: 'ALL',
    assignees: []
};

// Section 篩選
let treSections = [];
let sectionIndexById = new Map(); // id -> { name, parentId }
let sectionDisplayNameCache = new Map();
let sectionHydrationInFlight = false;
let treSectionFilterId = null;
let treSectionFilterIds = null; // Set of allowed section ids (string)，含子節點，'unassigned' 為未指派
let executionFilterInitialized = false;
let executionFilterAssigneeSelector = null;
let executionFilterPanelEl = null;
let executionFilterToggleBtn = null;
let executionFilterIsOpen = false;
let executionFilterResizeHandler = null;
let executionFilterI18nBound = false;
let executionFilterOriginalSelectTexts = new Map();
const debounceExecutionFilter = (fn, delay = 250) => {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(null, args), delay);
    };
};

const TRE_PERMISSION_DEFAULTS = {
    role: 'viewer',
    isViewer: true,
    canStart: false,
    canComplete: false,
    canRestart: false,
    canUpdateResults: false,
    canAssign: false,
    canBatchModify: false,
    canBatchDelete: false,
    canUploadResults: false,
    canManageBugTickets: false,
};

let testRunExecutionPermissions = { ...TRE_PERMISSION_DEFAULTS };

function getTrePermissions() {
    return window._testRunExecutionPermissions || testRunExecutionPermissions || TRE_PERMISSION_DEFAULTS;
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
        if (typeof element.disabled !== 'undefined') {
            element.disabled = false;
        }
    } else {
        element.classList.add('d-none');
        element.style.setProperty('display', 'none', 'important');
        if (typeof element.disabled !== 'undefined') {
            element.disabled = true;
        }
    }
}

function showExecutionPermissionDenied() {
    const message = (window.i18n && window.i18n.isReady())
        ? window.i18n.t('messages.permissionDenied')
        : 'No permission to perform this action';
    if (window.AppUtils && typeof window.AppUtils.showWarning === 'function') {
        window.AppUtils.showWarning(message);
    } else {
        alert(message);
    }
}

async function applyTestRunExecutionPermissions() {
    const defaults = { ...TRE_PERMISSION_DEFAULTS };

    if (!window.AuthClient) {
        testRunExecutionPermissions = defaults;
        window._testRunExecutionPermissions = defaults;
        return defaults;
    }

    let components = {};
    try {
        const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=test_run_execution');
        if (resp && resp.ok) {
            const payload = await resp.json();
            if (payload && payload.components) {
                components = payload.components;
            }
        }
    } catch (error) {
        console.warn('Failed to fetch Test Run Execution UI permissions:', error);
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
        canStart: !!components.startBtn,
        canComplete: !!components.completeBtn,
        canRestart: !!components.restartBtn,
        canBatchModify: !!components.batchModifyBtn,
        canBatchDelete: !!components.batchDeleteBtn,
        canUpdateResults: !!components.resultEditor,
        canAssign: !!components.assigneeEditor,
        canUploadResults: !!components.uploadTestResultsBtn,
        canManageBugTickets: !!components.addBugTicketBtn,
    };

    if (!resolved.isViewer) {
        resolved.canStart = true;
        resolved.canComplete = true;
        resolved.canRestart = true;
        resolved.canBatchModify = resolved.canBatchModify || true;
        resolved.canBatchDelete = resolved.canBatchDelete || true;
        resolved.canUpdateResults = true;
        resolved.canAssign = true;
        resolved.canUploadResults = true;
        resolved.canManageBugTickets = true;
    }

    testRunExecutionPermissions = resolved;
    window._testRunExecutionPermissions = resolved;

    setElementVisibility('batchOperationsToolbar', resolved.canBatchModify || resolved.canBatchDelete);
    setElementVisibility('batchModifyBtn', resolved.canBatchModify);
    setElementVisibility('batchDeleteBtn', resolved.canBatchDelete);

    const uploadBtn = document.getElementById('uploadTestResultsBtn');
    if (uploadBtn) {
        if (resolved.canUploadResults) {
            uploadBtn.style.display = '';
            uploadBtn.disabled = false;
            uploadBtn.classList.remove('disabled');
            uploadBtn.removeAttribute('aria-disabled');
        } else {
            uploadBtn.style.display = 'none';
            uploadBtn.disabled = true;
            uploadBtn.classList.add('disabled');
            uploadBtn.setAttribute('aria-disabled', 'true');
        }
    }
    const uploadArea = document.getElementById('testResultsUploadArea');
    if (uploadArea && !resolved.canUploadResults) {
        uploadArea.style.display = 'none';
    }

    const addBugTicketBtn = document.getElementById('addBugTicketBtn');
    if (addBugTicketBtn) {
        if (resolved.canManageBugTickets) {
            addBugTicketBtn.style.display = '';
            addBugTicketBtn.disabled = false;
            addBugTicketBtn.classList.remove('disabled');
        } else {
            addBugTicketBtn.style.display = 'none';
            addBugTicketBtn.disabled = true;
            addBugTicketBtn.classList.add('disabled');
        }
    }
    const confirmAddBugTicketBtn = document.getElementById('confirmAddBugTicket');
    if (confirmAddBugTicketBtn) {
        confirmAddBugTicketBtn.disabled = !resolved.canManageBugTickets;
    }
    const confirmDeleteBugTicketBtn = document.getElementById('confirmDeleteBugTicket');
    if (confirmDeleteBugTicketBtn) {
        confirmDeleteBugTicketBtn.disabled = !resolved.canManageBugTickets;
    }
    const bugTicketNumberInput = document.getElementById('bugTicketNumber');
    if (bugTicketNumberInput) {
        if (resolved.canManageBugTickets) {
            bugTicketNumberInput.removeAttribute('disabled');
        } else {
            bugTicketNumberInput.setAttribute('disabled', 'true');
        }
    }

    try {
        updateItemSelectionUI();
    } catch (_) {}

    return resolved;
}

/**
 * 通用的 Markdown 格式化函數
 * 為 textarea 中的選中文本添加 Markdown 格式
 *
 * @param {HTMLTextAreaElement} textarea - 目標 textarea 元素
 * @param {string} format - 格式類型: 'bold' | 'italic' | 'underline'
 */
function applyMarkdownFormat(textarea, format) {
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const selectedText = textarea.value.substring(start, end);
    const beforeText = textarea.value.substring(0, start);
    const afterText = textarea.value.substring(end);

    let formattedText;
    let newCursorPos;

    if (!selectedText) {
        // 如果沒有選中文本，只插入格式標記
        switch(format) {
            case 'bold':
                formattedText = '**文字**';
                newCursorPos = start + 2;
                break;
            case 'italic':
                formattedText = '_文字_';
                newCursorPos = start + 1;
                break;
            case 'underline':
                formattedText = '<u>文字</u>';
                newCursorPos = start + 3;
                break;
            default:
                return;
        }
    } else {
        // 有選中文本時，使用選中的文本
        switch(format) {
            case 'bold':
                formattedText = `**${selectedText}**`;
                newCursorPos = end + 4;
                break;
            case 'italic':
                formattedText = `_${selectedText}_`;
                newCursorPos = end + 2;
                break;
            case 'underline':
                formattedText = `<u>${selectedText}</u>`;
                newCursorPos = end + 7;
                break;
            default:
                return;
        }
    }

    // 更新 textarea 內容
    textarea.value = beforeText + formattedText + afterText;

    // 恢復光標位置
    setTimeout(() => {
        textarea.selectionStart = newCursorPos;
        textarea.selectionEnd = newCursorPos;
        textarea.focus();
    }, 0);

    // 觸發 input 事件以通知變更
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * 為 textarea 添加 Markdown 快捷鍵監聽
 * Ctrl/Cmd + B -> Bold
 * Ctrl/Cmd + I -> Italic
 * Ctrl/Cmd + U -> Underline
 *
 * @param {HTMLTextAreaElement} textarea - 目標 textarea 元素
 */
function setupMarkdownHotkeys(textarea) {
    if (!textarea) return;

    textarea.addEventListener('keydown', (e) => {
        const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
        const isCtrlOrCmd = isMac ? e.metaKey : e.ctrlKey;

        if (!isCtrlOrCmd) return;

        switch(e.key.toLowerCase()) {
            case 'b':
                e.preventDefault();
                applyMarkdownFormat(textarea, 'bold');
                break;
            case 'i':
                e.preventDefault();
                applyMarkdownFormat(textarea, 'italic');
                break;
            case 'u':
                e.preventDefault();
                applyMarkdownFormat(textarea, 'underline');
                break;
        }
    });
}

// Configure marked to treat single newlines as <br> so previews show line breaks
if (window.marked && typeof window.marked.setOptions === 'function') {
    window.marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
    });
}
