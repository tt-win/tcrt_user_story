/* ============================================================
   TEST CASE MANAGEMENT - QUICK SEARCH
   ============================================================ */

/* ============================================================
   17. 快速搜尋 (Quick Search)
   ============================================================ */

/**
 * 設定快速搜尋功能
 */
function setupQuickSearch_TCM() {
    if (!document.getElementById('quickSearchOverlay')) {
        const overlay = document.createElement('div');
        overlay.id = 'quickSearchOverlay';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:1060;display:none;background:rgba(0,0,0,0.35)';
        const searchPlaceholder = window.i18n ? window.i18n.t('testCase.searchPlaceholder') : '搜尋測試案例...';
        overlay.innerHTML = `
          <div class="position-fixed" style="top:34vh; left:50%; transform: translateX(-50%); width:min(720px, 92vw);">
            <div class="card shadow">
              <div class="card-body p-2">
                 <input id="quickSearchInput" type="text" class="form-control form-control-lg" placeholder="${escapeHtml(searchPlaceholder)}" autocomplete="off" />
                <div id=\"quickSearchResults\" class=\"list-group list-group-flush\" style=\"max-height:30vh; overflow:auto;\"></div>
              </div>
            </div>
          </div>`;
        document.body.appendChild(overlay);
        try {
            const input = overlay.querySelector('#quickSearchInput');
            if (input && window.i18n && window.i18n.isReady()) {
                input.placeholder = window.i18n.t('testCase.searchPlaceholder');
            }
            document.addEventListener('languageChanged', () => {
                if (input && window.i18n && window.i18n.isReady()) {
                    input.placeholder = window.i18n.t('testCase.searchPlaceholder');
                }
            });
        } catch (_) {}
        overlay.addEventListener('click', (e)=>{ if(e.target===overlay) closeQuickSearch(); });
    }

    document.addEventListener('keydown', function(e){
        const tag = (e.target && e.target.tagName || '').toLowerCase();
        const isTyping = ['input','textarea','select'].includes(tag) || (e.target && e.target.isContentEditable);
        if (!isTyping && e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            openQuickSearch_TCM();
        }
    });
}

// 底部左側提示
document.addEventListener('DOMContentLoaded', function(){
    if (document.getElementById('quickSearchHint')) return;
    const hint = document.createElement('div');
    hint.id = 'quickSearchHint';
    hint.className = 'position-fixed';
    hint.style.cssText = 'left:12px; bottom:12px; z-index:1040; opacity:0.85; pointer-events:none;';
    const label = window.i18n && window.i18n.isReady() ? window.i18n.t('hotkeys.quickSearch') : '按 / 開啟快速搜尋';
    hint.innerHTML = `<span class="badge bg-secondary-subtle text-secondary border" style="--bs-bg-opacity:.65;">${escapeHtml(label)}</span>`;
    document.body.appendChild(hint);
    // i18n 準備完成時也同步更新
    document.addEventListener('i18nReady', () => {
        const text = window.i18n ? window.i18n.t('hotkeys.quickSearch') : '按 / 開啟快速搜尋';
        const badge = document.querySelector('#quickSearchHint .badge');
        if (badge) badge.textContent = text;
    });
    document.addEventListener('languageChanged', () => {
        const text = window.i18n ? window.i18n.t('hotkeys.quickSearch') : '按 / 開啟快速搜尋';
        const badge = document.querySelector('#quickSearchHint .badge');
        if (badge) badge.textContent = text;
    });
});

function openQuickSearch_TCM() {
    const overlay = document.getElementById('quickSearchOverlay');
    const input = document.getElementById('quickSearchInput');
    const results = document.getElementById('quickSearchResults');
    if (!overlay || !input || !results) return;
    overlay.style.display = 'block';
    input.value = '';
    results.innerHTML = '';
    input.focus();

    const handleKey = (e) => {
        if (e.key === 'Escape') { closeQuickSearch(); return; }
        if (e.key === 'Enter') {
            const active = results.querySelector('.active');
            if (active) { active.click(); }
        } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const items = Array.from(results.querySelectorAll('.list-group-item'));
            if (items.length === 0) return;
            let idx = items.findIndex(li => li.classList.contains('active'));
            if (idx < 0) idx = 0;
            idx = (e.key === 'ArrowDown') ? Math.min(idx+1, items.length-1) : Math.max(idx-1, 0);
            items.forEach(li => li.classList.remove('active'));
            items[idx].classList.add('active');
            items[idx].scrollIntoView({ block:'nearest' });
        }
    };
    input.onkeydown = handleKey;
    
    // T030: 使用 debounce 優化搜尋，300ms 延遲減少重繪
    const debouncedSearch = debounce(() => quickSearchRender_TCM(input.value, results), 300);
    input.oninput = debouncedSearch;
}

function closeQuickSearch() {
    const overlay = document.getElementById('quickSearchOverlay');
    if (overlay) overlay.style.display = 'none';
}

function quickSearchRender_TCM(query, container) {
    const q = (query || '').trim().toLowerCase();
    let matches = [];
    if (q.length > 0) {
        matches = (testCases || []).filter(tc => {
            const num = (tc.test_case_number || '').toLowerCase();
            const title = (tc.title || '').toLowerCase();
            return num.includes(q) || title.includes(q);
        }).slice(0, 100);
    }
    if (matches.length === 0) {
        const noMatchesText = window.i18n ? window.i18n.t('errors.noMatchingTestCases') : '沒有找到符合條件的測試案例';
        container.innerHTML = `<div class="list-group-item text-muted">${escapeHtml(noMatchesText)}</div>`;
        return;
    }
    container.innerHTML = matches.map((tc, idx) => `
      <button type="button" class="list-group-item list-group-item-action ${idx===0?'active':''}" data-id="${escapeHtml(tc.record_id)}">\n        <div class="d-flex justify-content-between align-items-center">\n          <code class="small me-2">${escapeHtml(tc.test_case_number || '')}</code>\n          <span class="text-truncate">${escapeHtml(tc.title || '')}</span>\n        </div>\n      </button>`).join('');
    container.querySelectorAll('.list-group-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.getAttribute('data-id');
            closeQuickSearch();
            if (id) viewTestCase(id);
        });
    });
}

// 快速編輯功能
function quickEdit(recordId, field) {
    const testCase = testCases.find(tc => tc.record_id === recordId);
    if (!testCase) return;

    const cell = Array.from(document.querySelectorAll('[data-record-id][data-field]')).find(element =>
        element.dataset.recordId === String(recordId) && element.dataset.field === String(field)
    );
    if (!cell) return;

    // 獲取當前值
    const currentValue = testCase[field] || '';

    // 建立輸入框
    const input = document.createElement('input');
    input.type = 'text';
    input.value = currentValue;
    input.className = 'form-control quick-edit-input';
    input.style.width = '100%';
    input.style.height = 'auto';
    input.style.minHeight = '1.5rem';
    input.style.lineHeight = '1.5';
    input.style.fontSize = '0.875rem';
    input.style.padding = '0.25rem 0.5rem';
    input.style.border = '1px solid #007bff';
    input.style.borderRadius = '4px';
    input.style.margin = '0';

    // 儲存原始內容
    const originalContent = cell.innerHTML;

    // 替換內容
    cell.innerHTML = '';
    cell.appendChild(input);
    input.focus();
    input.select();

    // 處理儲存
    const saveEdit = async () => {
        const newValue = input.value.trim();

        if (newValue === currentValue) {
            // 值沒有變更，恢復原始內容
            cell.innerHTML = originalContent;
            return;
        }

        // 立即更新本地資料和 UI
        testCase[field] = newValue;
        
        // 優化：直接更新 DOM 而不重繪整個表格
        const valueElement = document.createElement(field === 'test_case_number' ? 'code' : 'div');
        valueElement.className = 'hover-editable';
        valueElement.append(document.createTextNode(`${newValue} `));
        const editIcon = document.createElement('i');
        editIcon.className = 'fas fa-pencil-alt hover-edit-btn';
        valueElement.appendChild(editIcon);
        valueElement.addEventListener('click', () => quickEdit(recordId, field));
        cell.replaceChildren(valueElement);

        // 在背景處理儲存
        try {
            // 獲取當前團隊
            const currentTeam = AppUtils.getCurrentTeam();
            if (!currentTeam || !currentTeam.id) {
                throw new Error('請先選擇團隊');
            }

            // 構建更新資料
            const updateData = {};
            updateData[field] = newValue;

            // 背景發送更新請求，不等待響應
            window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${recordId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(updateData)
            }).then(async response => {
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || '更新失敗');
                }
                // 成功後顯示提示，但不重新渲染（已經手動更新 DOM 了）
                const fieldName = field === 'test_case_number' ? 'Test Case Number' :
                    (window.i18n ? window.i18n.t('common.title') : '標題');
                const updateSuccessMessage = window.i18n ? window.i18n.t('messages.fieldUpdated') : '更新成功';
                showSuccess(`${fieldName} ${updateSuccessMessage}`);
            }).catch(error => {
                console.error('快速編輯失敗:', error);
                const updateFailedMessage = window.i18n ? window.i18n.t('errors.updateFailed') : '更新失敗';
                showError(updateFailedMessage + '：' + error.message);

                // 如果儲存失敗，恢復原值並恢復 DOM
                testCase[field] = currentValue;
                cell.innerHTML = originalContent;
            });

        } catch (error) {
            console.error('快速編輯失敗:', error);
            const updateFailedMessage = window.i18n ? window.i18n.t('errors.updateFailed') : '更新失敗';
            showError(updateFailedMessage + '：' + error.message);

            // 恢復原值並恢復 DOM
            testCase[field] = currentValue;
            cell.innerHTML = originalContent;
        }
    };

    // 處理取消
    const cancelEdit = () => {
        cell.innerHTML = originalContent;
    };

    // 綁定事件
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            saveEdit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancelEdit();
        }
    });

    input.addEventListener('blur', saveEdit);
}

// NOTE: currentTCGEditor 已統一定義於 Section 2

async function editTCG(recordId) {
    console.log('🟢 editTCG 被呼叫，recordId:', recordId);

    // 先強制重置可能殘留的編輯器狀態/DOM（避免上一輪外部事件阻斷）
    resetTCGEditorState();

    // 檢查權限
    if (!hasTestCasePermission('tcgEditContainer')) {
        console.log('⛔ editTCG: 沒有編輯權限');
        return; // Viewer 無權編輯 TCG
    }

    const testCase = testCases.find(tc => tc.record_id === recordId);
    if (!testCase) {
        console.log('⚠️ editTCG: 找不到 testCase:', recordId);
        return;
    }

    const cell = document.querySelector(`[data-record-id="${recordId}"][data-field="tcg"]`);
    if (!cell) {
        console.log('⚠️ editTCG: 找不到 cell 元素，selector:', `[data-record-id="${recordId}"][data-field="tcg"]`);
        return;
    }
    console.log('✅ editTCG: cell 找到');

    // 確保無殘留 DOM（例如外部點擊未觸發/提前阻斷）
    forceCloseTCGInlineEditor(cell);

    // 獲取當前 TCG - tcg 就是一個字串陣列
    const currentTCGs = testCase.tcg && Array.isArray(testCase.tcg) ? [...testCase.tcg] : [];
    console.log('✏️ editTCG 開始，找到的 TCG 值:', currentTCGs, ', testCase.tcg:', testCase.tcg);

    // 設置編輯器狀態
    currentTCGEditor = {
        recordId: recordId,
        cell: cell,
        originalTCGs: [...currentTCGs],
        currentTCGs: [...currentTCGs],
        originalContent: cell.innerHTML,
        mode: 'search'
    };
    console.log('✏️ currentTCGEditor 已設置:', currentTCGEditor);

    // 直接進入搜尋模式
    startTCGSearch();
}

// 依 recordId 取得當前 TCG 陣列（優先使用快取的 testCases）
function getCurrentTCGsByRecordId(recordId) {
    const tc = testCases.find(t => t.record_id === recordId);
    if (!tc || !Array.isArray(tc.tcg)) return [];
    return [...tc.tcg];
}

// 全域重置 TCG 編輯狀態與殘留 DOM
function resetTCGEditorState() {
    // 清除外部點擊監聽
    document.removeEventListener('click', handleTCGOutsideClick, true);

    // 移除任何殘留的 inline 編輯器
    document.querySelectorAll('.tcg-inline-editor').forEach((el) => el.remove());

    // 移除 editing 樣式
    document.querySelectorAll('[data-field="tcg"].editing').forEach((cell) => cell.classList.remove('editing'));
    document.querySelectorAll('.tcg-edit-area.editing').forEach((el) => el.classList.remove('editing'));

    // 清空狀態
    currentTCGEditor = null;
}

// 強制清理殘留的 TCG Inline 編輯 DOM（當 state 已清空但 DOM 尚在時）
function forceCloseTCGInlineEditor(cell) {
    if (!cell) return;

    // 移除殘留編輯器
    const editor = cell.querySelector('.tcg-inline-editor');
    if (editor) {
        editor.remove();
    }

    // 移除 editing 樣式
    cell.classList.remove('editing');

    // 清理全域監聽
    document.removeEventListener('click', handleTCGOutsideClick, true);

    // 還原顯示 DOM（保留點擊事件）
    const recordId = cell.getAttribute('data-record-id');
    if (recordId) {
        updateTCGCellDisplay(cell, getCurrentTCGsByRecordId(recordId));
    }
}

async function startTCGSearch() {
    if (!currentTCGEditor) return;

    const { cell, currentTCGs, recordId } = currentTCGEditor;

    console.log('🟢 startTCGSearch 開始，currentTCGs:', currentTCGs);

    // 隱藏原內容但保持高度（使用 visibility 而不是移除）
    const originalContent = cell.querySelector('.tcg-edit-area');
    if (originalContent) {
        originalContent.style.visibility = 'hidden';
        originalContent.style.height = '24px';
        originalContent.style.position = 'relative';
    }

    // 創建浮層輸入框 - 使用絕對定位，不會影響版面
    const editorHtml = `
        <div class="tcg-inline-editor" style="position: absolute; top: 0; left: 0; right: 0; bottom: 0; z-index: 1000; display: flex; align-items: center;">
            <input type="text" class="form-control form-control-sm tcg-search-input"
                   placeholder="${escapeHtml(window.i18n ? window.i18n.t('testCase.tcgBatchInputPlaceholder') : '輸入 TCG 單號，以逗號分隔 (例: TCG-123, TCG-456)')}"
                   autocomplete="off"
                   onkeydown="handleTCGSearchKeydown(event)"
                   oninput="handleTCGSearchInput(event)"
                   style="height: 24px; font-size: 0.75rem; padding: 0.25rem 0.375rem; margin: 0;">
        </div>
    `;

    // 在 cell 中插入編輯器（保持相對定位的父容器）
    cell.insertAdjacentHTML('beforeend', editorHtml);
    cell.style.position = 'relative';
    cell.classList.add('editing');

    // 聚焦搜尋框
    const searchInput = cell.querySelector('.tcg-search-input');
    searchInput.focus();

    // 如果有原始的 TCG 值，填入搜尋框
    if (currentTCGs && currentTCGs.length > 0) {
        console.log('📝 正在載入現有 TCG 值:', currentTCGs);
        searchInput.value = currentTCGs.join(', ');
        // 觸發 oninput 事件以更新狀態
        handleTCGSearchInput({ target: searchInput });
    } else {
        console.log('ℹ️ 沒有現有的 TCG 值');
    }

    // 添加點擊外部結束編輯的監聽器
    setTimeout(() => {
        document.addEventListener('click', handleTCGOutsideClick, true);
    }, 100);
}

function handleTCGOutsideClick(event) {
    if (!currentTCGEditor) {
        console.log('🔵 handleTCGOutsideClick: currentTCGEditor is null, ignore');
        return;
    }

    const { cell } = currentTCGEditor;

    // 檢查點擊是否在編輯區域外
    console.log('🔶 handleTCGOutsideClick 觸發，event.target:', event.target, 'cell:', cell, 'contains:', cell.contains(event.target));
    if (!cell.contains(event.target)) {
        console.log('🔴 handleTCGOutsideClick: 點擊在編輯區域外，結束編輯');
        finishTCGEdit();
    } else {
        console.log('🟡 handleTCGOutsideClick: 點擊在編輯區域內，保留編輯');
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

async function finishTCGEdit() {
    if (!currentTCGEditor) {
        console.log('⚠️ finishTCGEdit: 沒有當前編輯器');
        return;
    }

    const { recordId, currentTCGs, originalTCGs, cell } = currentTCGEditor;

    console.log('=== finishTCGEdit 開始 ===');
    console.log('recordId:', recordId);
    console.log('currentTCGs:', currentTCGs);
    console.log('originalTCGs:', originalTCGs);

    // 移除全域點擊監聽器
    document.removeEventListener('click', handleTCGOutsideClick, true);

    // 清除浮層編輯器
    const editor = cell.querySelector('.tcg-inline-editor');
    if (editor) {
        editor.remove();
    }

    // 恢復原內容的可見性
    const originalContent = cell.querySelector('.tcg-edit-area');
    if (originalContent) {
        originalContent.style.visibility = 'visible';
        originalContent.style.height = 'auto';
        originalContent.style.position = 'static';
    }

    // 檢查是否有變更
    const hasChanges = JSON.stringify(currentTCGs.sort()) !== JSON.stringify(originalTCGs.sort());
    console.log('hasChanges:', hasChanges);

    // 立即更新 UI 顯示
    cell.classList.remove('editing');
    updateTCGCellDisplay(cell, currentTCGs);

    // 清除編輯器狀態
    currentTCGEditor = null;

    // 如果有變更，在背景處理儲存
    if (hasChanges) {
        console.log('💾 準備儲存 TCG 變更...');
        // 非同步背景儲存，不等待完成
        saveTCGChanges(recordId, currentTCGs).catch(error => {
            console.error('❌ TCG 儲存失敗:', error);
            // 如果儲存失敗，可以考慮顯示錯誤訊息或恢復原值
        });
    } else {
        console.log('ℹ️ 沒有變更，不需要儲存');
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

function updateTCGCellDisplay(cell, tcgNumbers) {
    // 更新單個 TCG 欄位的顯示，不重新渲染整個表格
    const recordId = cell.getAttribute('data-record-id');
    const editable = hasTestCasePermission('tcgEditContainer');
    const baseClass = editable ? 'tcg-edit-area tcg-editable' : 'tcg-edit-area tcg-readonly';
    const baseStyle = 'display: flex; flex-wrap: wrap; gap: 2px; justify-content: center; align-items: center; min-height: 24px; padding: 2px;'
        + (editable ? ' cursor: pointer;' : ' cursor: default;');
    const display = document.createElement('div');
    display.className = baseClass;
    display.dataset.i18nTitle = 'tooltips.clickEditTcg';
    display.style.cssText = baseStyle;
    tcgNumbers.forEach(tcg => {
        const tag = document.createElement('span');
        tag.className = 'tcg-tag';
        tag.textContent = tcg;
        display.appendChild(tag);
    });
    if (editable) display.addEventListener('click', () => editTCG(recordId));
    cell.replaceChildren(display);

    // 重新應用翻譯到新生成的內容
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(cell);
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

function restoreTCGDisplay() {
    if (!currentTCGEditor) return;

    const { cell } = currentTCGEditor;
    cell.classList.remove('editing');
    renderTestCasesTable(); // 重新渲染以恢復正常顯示
}

// NOTE: tcgSearchTimeout 已統一定義於 Section 2

function handleTCGSearchInput(event) {
    // 即時更新顯示的 badge，支援 comma 分隔
    if (!currentTCGEditor) return;

    const input = event.target.value.trim();
    // 解析 comma 分隔的單號
    const tcgNumbers = input
        .split(/[,，]/)  // 支援中文逗號和英文逗號
        .map(s => s.trim())
        .filter(s => s.length > 0);

    // 更新當前選擇的 TCG
    currentTCGEditor.currentTCGs = tcgNumbers;

    // 即時更新下方 preview 顯示
    updateTCGPreview(tcgNumbers);
}

function updateTCGPreview(tcgNumbers) {
    // 更新編輯區域下方的 badge 預覽顯示
    if (!currentTCGEditor) return;

    const container = currentTCGEditor.cell.querySelector('.tcg-tags-container');
    if (!container) return;

    if (tcgNumbers.length === 0) {
        const emptyText = window.i18n ? window.i18n.t('userStoryMap.noJiraTickets', {}, '未輸入任何單號') : '未輸入任何單號';
        container.innerHTML = `<div class="text-muted small">${escapeHtml(emptyText)}</div>`;
    } else {
        const badgesHtml = tcgNumbers
            .map(tcg => `<span class="tcg-tag">${escapeHtml(tcg)}</span>`)
            .join('');
        container.innerHTML = badgesHtml;
    }
}

function handleTCGSearchKeydown(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        finishTCGEdit();
    } else if (event.key === 'Escape') {
        event.preventDefault();
        // 取消變更
        if (currentTCGEditor) {
            currentTCGEditor.currentTCGs = [...currentTCGEditor.originalTCGs];
        }
        finishTCGEdit();
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

// 下拉式選單函數已移除 - 改為文字輸入 + badge 模式
async function saveTCGChanges(recordId, tcgNumbers) {
    try {
        // 獲取當前團隊
        const currentTeam = AppUtils.getCurrentTeam();
        if (!currentTeam || !currentTeam.id) {
            throw new Error('請先選擇團隊');
        }

        // 後端 API 支援字串格式（逗號分隔），不需要轉換為 LarkRecord 陣列
        const tcgString = tcgNumbers.join(', ');

        console.log('儲存 TCG 變更:', { recordId, tcgString });

        // 構建更新資料：使用字串格式
        const updateData = {
            tcg: tcgString
        };

        console.log('Request body:', JSON.stringify(updateData));

        // 發送更新請求
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${recordId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(updateData)
        });

        console.log('TCG 更新 Response status:', response.status);

        if (!response.ok) {
            const errorData = await response.json();
            console.error('TCG 更新失敗:', errorData);
            throw new Error(errorData.detail || '更新失敗');
        }

        // 從 API 返回的資料更新本地資料
        const updatedTestCase = await response.json();
        console.log('API 返回的更新後資料:', updatedTestCase);
        console.log('API 返回的 tcg 欄位:', updatedTestCase.tcg);
        console.log('tcg 類型:', typeof updatedTestCase.tcg);
        console.log('tcg 是否為陣列:', Array.isArray(updatedTestCase.tcg));

        const testCase = testCases.find(tc => tc.record_id === recordId);
        if (testCase) {
            console.log('找到 testCase, 原本的 tcg:', testCase.tcg);
            // 保留原本的 record_id，但更新 tcg 欄位
            testCase.tcg = updatedTestCase.tcg;
            console.log('✅ 已更新 testCase.tcg:', testCase.tcg);
        } else {
            console.error('⚠️ 找不到 testCase, recordId:', recordId);
        }

        // 更新快取
        if (updatedTestCase.test_case_number) {
            updateTestCaseInCache(updatedTestCase);
        }

        // 重新渲染表格 -> 移除以優化效能 (DOM 已由 finishTCGEdit 更新)
        // renderTestCasesTable();

        showSuccess(window.i18n ? window.i18n.t('messages.tcgUpdated') : 'TCG 更新成功');
        console.log('✅ TCG 儲存完成');

    } catch (error) {
        console.error('更新 TCG 失敗:', error);
        const updateFailedMessage = window.i18n ? window.i18n.t('errors.updateFailed') : '更新失敗';
        showError(updateFailedMessage + '：' + error.message);

        // 恢復原始內容 (從尚未更新的 testCases 資料中恢復)
        const testCase = testCases.find(tc => tc.record_id === recordId);
        if (testCase) {
             const cell = document.querySelector(`[data-record-id="${recordId}"][data-field="tcg"]`);
             if (cell) updateTCGCellDisplay(cell, testCase.tcg || []);
        }
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}
