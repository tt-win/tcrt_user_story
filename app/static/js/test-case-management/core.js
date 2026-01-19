/* ============================================================
   TEST CASE MANAGEMENT - CORE
   ============================================================ */

// Markdown config and formatting helpers
// Configure marked to treat single newlines as <br> so previews show line breaks
if (window.marked && typeof window.marked.setOptions === 'function') {
    window.marked.setOptions({
        gfm: true,
        breaks: true
    });
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

/* ============================================================
   TEST CASE MANAGEMENT - JAVASCRIPT
   ============================================================

   目錄 (Table of Contents):
   ──────────────────────────────────────────────────────────────
   1.  常數定義 (Constants)                         ~Line 30
   2.  全域變數 (Global Variables)                  ~Line 60
   3.  事件監聽器 (Event Listeners)                 ~Line 100
   4.  快取管理 (Cache Management)                  ~Line 200
       - 執行快取 (Exec Cache)
       - 測試案例快取 (Test Cases Cache)
       - TCG 快取 (TCG Cache)
       - 篩選器儲存 (Filters Storage)
   5.  團隊管理 (Team Management)                   ~Line 500
   6.  權限管理 (Permissions)                       ~Line 600
   7.  排序與分組 (Sorting & Grouping)              ~Line 800
       - 欄位排序
       - Section 分組
   8.  渲染函數 (Rendering)                         ~Line 1000
       - 表格渲染
       - Section 渲染
   9.  篩選器 (Filters)                             ~Line 1400
   10. 初始化 (Initialization)                      ~Line 1600
   11. 測試案例載入 (Loading)                       ~Line 1800
   12. 測試案例 Modal (Test Case Modal)             ~Line 2200
       - 顯示/隱藏
       - 表單處理
       - 儲存/刪除
   13. TCG 編輯器 (TCG Editor)                      ~Line 3000
       - Modal TCG 編輯
       - 行內 TCG 編輯
   14. 批次操作 (Batch Operations)                  ~Line 3500
       - 批次複製
       - 批次修改
       - 批次刪除
   15. 大量新增 (Bulk Create)                       ~Line 4200
   16. 複製/克隆 (Copy/Clone)                       ~Line 5000
   17. 快速搜尋 (Quick Search)                      ~Line 5400
   18. Markdown 編輯器 (Markdown Editor)            ~Line 5700
   19. 附件處理 (Attachments)                       ~Line 6200
   20. 導航功能 (Navigation)                        ~Line 6600
   21. Section 管理 (Section Management)            ~Line 6900
   22. TCG Tooltip (TCG Hover)                      ~Line 7200
   23. 參考測試案例 (Reference Test Case)           ~Line 7600
   24. 大量編輯 (Bulk Edit)                         ~Line 7800
   25. 拖移選取 (Drag Selection)                    ~Line 9000
   26. 工具函數 (Utilities)                         ~Line 9200

   ============================================================ */


/* ============================================================
   1. 常數定義 (Constants)
   ============================================================ */

// ─────────────────────────────────────────────────────────────
// 1.1 快取相關常數 (Cache Constants)
// ─────────────────────────────────────────────────────────────

// 執行快取設定（與執行頁共用）
const EXEC_TC_CACHE_PREFIX = 'tr_exec_tc_cache_v1';
const EXEC_TC_CACHE_TTL_MS = 60 * 60 * 1000; // 1 小時

// TCG 快取設定
const TCG_CACHE_KEY = 'tcg_cache';
const TCG_CACHE_TIMESTAMP_KEY = 'tcg_cache_timestamp';
const TCG_CACHE_EXPIRY = 24 * 60 * 60 * 1000; // 24小時過期

// 測試案例快取設定
const TEST_CASES_CACHE_KEY = 'test_cases_list_cache_v1';
const TEST_CASES_CACHE_TTL = 60 * 60 * 1000; // 1小時

// 團隊快取設定
const TEAMS_CACHE_TTL = 60 * 1000; // 1分鐘

// 篩選器儲存設定
const TCM_FILTERS_STORAGE_PREFIX = 'tcm_filters_v1';

// ─────────────────────────────────────────────────────────────
// 1.2 UI 與格式常數 (UI & Format Constants)
// ─────────────────────────────────────────────────────────────

// 優先級排序權重
const PRIORITY_RANK = { High: 3, Medium: 2, Low: 1 };

// 未分配 Section 識別碼
const UNASSIGNED_SECTION_ID = '__section_unassigned__';

// 大量新增允許的優先級值
const BULK_PRIORITY_ALLOWED = ['High', 'Medium', 'Low'];

// ─────────────────────────────────────────────────────────────
// 1.3 事件與通訊常數 (Event & Communication Constants)
// ─────────────────────────────────────────────────────────────

// 事件廣播 Key
const TEST_CASE_UPDATE_EVENT_KEY = 'testCaseUpdatedEvent';


/* ============================================================
   2. 全域變數 (Global Variables)
   ============================================================ */

// ─────────────────────────────────────────────────────────────
// 2.1 快取狀態 (Cache State)
// ─────────────────────────────────────────────────────────────

// TCG 快取
let tcgCache = null;
let tcgCacheTimestamp = null;

// 團隊快取（在 Section 5 使用）
let teamContextPromise = null;
let teamsCache = null;
let teamsCacheLastLoaded = 0;

// ─────────────────────────────────────────────────────────────
// 2.2 測試案例資料 (Test Cases Data)
// ─────────────────────────────────────────────────────────────

let testCases = [];
let filteredTestCases = [];
let selectedTestCases = new Set();
let currentSetId = null; // 當前選擇的 Test Case Set ID

// 篩選器狀態
let tcmCurrentFilters = { testCaseNumberSearch: '', searchInput: '', tcgFilter: '', priorityFilter: '' };
const TCM_RENDER_BATCH = 200;
let tcmRenderQueue = [];
let tcmRenderedCount = 0;

// ─────────────────────────────────────────────────────────────
// 2.3 排序與 Section 狀態 (Sorting & Section State)
// ─────────────────────────────────────────────────────────────

// 排序狀態
let tcmSortField = 'number'; // number|title|tcg|priority|created|updated
let tcmSortOrder = 'asc';    // asc|desc

// Section 狀態
const sectionSortStates = new Map();
const sectionCollapsedState = new Set();        // 已收合的 section IDs
const savedChildrenCollapseState = new Map();   // 記錄子 section 收合狀態

// 區段資料（供批次設定使用）
let tcmSectionsTree = [];
let tcmSectionMetaMap = new Map();
let tcmSectionOrder = [];
let tcmUnassignedSectionIds = new Set();

// ─────────────────────────────────────────────────────────────
// 2.4 分頁與導航 (Pagination & Navigation)
// ─────────────────────────────────────────────────────────────

let lastCaseCheckboxIndex = null;  // Shift 連續多選錨點
let currentPage = 1;
let currentTestCaseIndex = -1;
let tcmNavigationTestCases = [];
let pageSize = 50;

// ─────────────────────────────────────────────────────────────
// 2.5 Modal 實例與編輯器狀態 (Modal Instances & Editor State)
// ─────────────────────────────────────────────────────────────

// Markdown 編輯器
let markdownEditor = null;
let currentEditorMode = 'preview'; // preview|edit|split
let markdownPreviewTimeout;
let activeTextarea = null;
let aiAssistModalInstance = null;
let aiAssistInitialized = false;
let aiAssistHasResponse = false;

// 測試案例 Modal
let testCaseModalInstance = null;
let originalFormData = {};
let isFormChanged = false;

// Modal TCG 編輯器
let currentModalTCGEditor = null;
let modalTCGSearchTimeout = null;
let modalTCGSelected = [];

// 批次複製 Modal
let batchCopyModalInstance = null;
let batchCopyPreviewModalInstance = null;
let batchCopyItems = [];
let lastBatchCopyCheckboxIndex = null;

// 大量新增 Modal
let bulkModalInstance = null;
let bulkPreviewModalInstance = null;
let bulkTextParsedItems = [];

// 批次修改 TCG 編輯器
let batchTCGSearchTimeout;
let batchTCGEditing = false;
let batchTCGSelected = [];

// 行內 TCG 編輯器
let currentTCGEditor = null;
let tcgSearchTimeout;

// 大量編輯 Modal
let bulkEditModalInstance = null;
let bulkEditSearchModalInstance = null;
let bulkEditData = [];
let bulkEditChanges = new Map();
let bulkEditSelectedCells = new Set();
let bulkEditClipboard = { content: '', column: '', cells: [] };
let bulkEditUndoStack = [];
let bulkEditCurrentOperation = null;
let bulkEditCurrentCell = null;
let bulkEditDragState = null;
let bulkEditSelectDragState = null;
let bulkEditSearchResults = [];
let bulkEditCheckedResults = new Set();

// ─────────────────────────────────────────────────────────────
// 2.6 附件與上傳 (Attachments & Upload)
// ─────────────────────────────────────────────────────────────

let uploadedAttachments = [];
let currentTempUploadId = null;

// ─────────────────────────────────────────────────────────────
// 2.7 TCG Tooltip 狀態 (TCG Tooltip State)
// ─────────────────────────────────────────────────────────────

let currentTooltip = null;
let tooltipTimeout = null;
let currentHoveredElement = null;
let isHoveringTooltip = false;
let isInitialized = false;

// ─────────────────────────────────────────────────────────────
// 2.8 調試開關 (Debug Flags)
// ─────────────────────────────────────────────────────────────

window.DEBUG_SECTIONS = false;


/* ============================================================
   3. 事件監聽器 (Event Listeners)
   ============================================================ */

// 測試案例集載入事件
window.addEventListener('testCaseSetLoaded', (event) => {
    try {
        const sections = event?.detail?.sections;
        if (Array.isArray(sections)) {
            tcmSectionsTree = sections;
            rebuildBatchSectionMeta();
            populateBatchSectionSelect();
            if (Array.isArray(testCases) && testCases.length > 0) {
                applyCurrentFiltersAndRender();
            }
        }
    } catch (err) {
        console.warn('Failed to handle testCaseSetLoaded for batch section select:', err);
    }
});

// Section 列表更新事件
window.addEventListener('sectionListUpdated', async (event) => {
    try {
        const detail = event?.detail;
        const updatedSections = detail?.sections;
        const updatedSetId = detail?.setId;

        console.log('[TCM] sectionListUpdated event received:', {
            sectionsCount: updatedSections?.length,
            setId: updatedSetId,
            reloadTestCases: detail?.reloadTestCases
        });

        if (!updatedSections || !Array.isArray(updatedSections)) return;

        if (typeof testCaseSectionList !== 'undefined' && testCaseSectionList?.setId && updatedSetId) {
            if (updatedSetId !== testCaseSectionList.setId) {
                console.log('[TCM] Ignoring sectionListUpdated: set ID mismatch');
                return;
            }
        }

        tcmSectionsTree = updatedSections;
        console.log('[TCM] Updated tcmSectionsTree with', tcmSectionsTree.length, 'sections');

        rebuildBatchSectionMeta();
        populateBatchSectionSelect();

        // 強制重新渲染測試案例列表（使用新的 section 樹）
        applyCurrentFiltersAndRender();

        if (detail?.reloadTestCases) {
            console.log('[TCM] Reloading test cases...');
            await loadTestCases(false, null, true);
        }
    } catch (err) {
        console.warn('Failed to handle sectionListUpdated:', err);
    }
});
