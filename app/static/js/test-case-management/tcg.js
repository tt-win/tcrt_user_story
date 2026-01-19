/* ============================================================
   TEST CASE MANAGEMENT - TCG EDITOR
   ============================================================ */

/* ============================================================
   13. TCG 編輯器 (TCG Editor)
   ============================================================ */

/* ------------------------------------------------------------
   13.1 Modal TCG 編輯器
   ------------------------------------------------------------ */

// NOTE: currentModalTCGEditor, modalTCGSearchTimeout, modalTCGSelected 已統一定義於 Section 2

/**
 * 開始編輯 Modal 中的 TCG
 */
async function editModalTCG() {
    const container = document.getElementById('modalTcgContainer');
    if (!container) return;

    // 如果已經有編輯器在運行，先關閉
    if (currentModalTCGEditor) {
        await finishModalTCGEdit();
    }

    // 獲取當前 TCG
    const currentTCGs = Array.isArray(modalTCGSelected) ? [...modalTCGSelected] : [];

    // 設置編輯器狀態
    currentModalTCGEditor = {
        container: container,
        originalTCGs: [...currentTCGs],
        currentTCGs: [...currentTCGs],
        originalContent: container.innerHTML,
        mode: 'search'
    };

    // 直接進入搜尋模式
    startModalTCGSearch();
}

async function startModalTCGSearch() {
    if (!currentModalTCGEditor) return;

    const { container, currentTCGs } = currentModalTCGEditor;

    console.log('🟢 startModalTCGSearch 開始，currentTCGs:', currentTCGs);

    // 清空容器內容但不改變容器本身的配置
    // 保存原始內容以備需要恢復
    const originalContent = container.innerHTML;
    container.innerHTML = '';

    // 確保容器有相對定位
    container.style.position = 'relative';
    container.style.display = 'flex';
    container.style.alignItems = 'center';
    container.style.minHeight = '32px';
    container.style.height = '32px';

    // 創建浮層輸入框 - 使用絕對定位，不會影響版面
    const editorHtml = `
        <div class="tcg-inline-editor" style="position: absolute; top: 0; left: 0; right: 0; bottom: 0; z-index: 1000; display: flex; align-items: center; padding: 4px 8px;" onclick="event.stopPropagation()">
            <input type="text" class="form-control form-control-sm tcg-search-input"
                   placeholder="輸入 TCG 單號，以逗號分隔 (例: TCG-123, TCG-456)"
                   autocomplete="off"
                   onkeydown="handleModalTCGSearchKeydown(event)"
                   style="height: 28px; width: 100%; font-size: 0.75rem; padding: 0.25rem 0.375rem; margin: 0; border: 1px solid #dee2e6; box-sizing: border-box;">
        </div>
    `;

    // 在 container 中插入編輯器
    container.insertAdjacentHTML('beforeend', editorHtml);
    container.classList.add('editing');

    // 更新全域狀態：填入現有 TCG
    modalTCGSelected = [...currentTCGs];

    // 設定輸入框初始值
    const searchInput = container.querySelector('.tcg-search-input');
    if (searchInput) {
        console.log('📝 設置輸入框初始值:', modalTCGSelected.join(', '));
        searchInput.value = modalTCGSelected.join(', ');
        searchInput.focus();
        searchInput.select();
    } else {
        console.warn('⚠️ 找不到輸入框元素');
    }

    // 添加點擊外部結束編輯的監聽器
    setTimeout(() => {
        document.addEventListener('click', handleModalTCGOutsideClick, true);
    }, 100);
}

function handleModalTCGOutsideClick(event) {
    if (!currentModalTCGEditor) return;

    const { container } = currentModalTCGEditor;

    // 檢查點擊是否在編輯區域外
    const dropdown = container.querySelector('.tcg-dropdown');
    if (!container.contains(event.target) && (!dropdown || !dropdown.contains(event.target))) {
        finishModalTCGEdit();
    }
}

async function finishModalTCGEdit() {
    if (!currentModalTCGEditor) return;

    const { container } = currentModalTCGEditor;

    // 移除全域點擊監聽器
    document.removeEventListener('click', handleModalTCGOutsideClick, true);

    // 從輸入框讀取值並解析
    const searchInput = container.querySelector('.tcg-search-input');
    if (searchInput) {
        const inputValue = searchInput.value.trim();
        if (inputValue) {
            // 解析逗號分隔的 TCG 單號
            modalTCGSelected = inputValue
                .split(',')
                .map(t => t.trim())
                .filter(t => t);  // 移除空字符串
        } else {
            modalTCGSelected = [];
        }
        console.log('💾 finishModalTCGEdit: 儲存值:', modalTCGSelected);
    }

    // 清除浮層編輯器和容器內容
    container.innerHTML = '';
    container.classList.remove('editing');

    // 立即更新 UI 顯示
    renderModalTCGDisplay();

    // 更新隱藏 input 值
    const hidden = document.getElementById('tcg');
    if (hidden) hidden.value = modalTCGSelected.join(', ');

    // 清除編輯器狀態
    currentModalTCGEditor = null;
}

function renderModalTCGDisplay() {
    const container = document.getElementById('modalTcgContainer');
    if (!container) return;

    if (!Array.isArray(modalTCGSelected) || modalTCGSelected.length === 0) {
        // 清除後留白，但保留點擊事件
        container.innerHTML = '<span class="text-muted" style="font-size: 0.875rem;">點擊填寫 TCG 單號</span>';
    } else {
        // 顯示 TCG 標籤，保留點擊事件
        const tcgHtml = modalTCGSelected.map(tcg =>
            `<span class="tcg-tag">${tcg}</span>`
        ).join('');
        container.innerHTML = tcgHtml;
    }
}

function handleModalTCGSearchKeydown(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        finishModalTCGEdit();
    } else if (event.key === 'Escape') {
        event.preventDefault();
        // 取消變更
        if (currentModalTCGEditor) {
            modalTCGSelected = [...currentModalTCGEditor.originalTCGs];
        }
        finishModalTCGEdit();
    }
}

// TCG 快取管理函數
async function loadTCGCacheFromStorage() {
    try {
        const cached = await TRCache.getTCG(TCG_CACHE_EXPIRY);
        if (cached && Array.isArray(cached.data)) {
            const cacheSize = cached.data.length;
            console.log(`[TCG 快取] 從 IndexedDB 讀取: ${cacheSize} 筆記錄`);

            // 驗證快取完整性：如果快取過小（< 10000），視為損壞
            const MIN_VALID_CACHE = 10000;
            if (cacheSize < MIN_VALID_CACHE) {
                console.warn(`[TCG 快取] ⚠️ 快取記錄過少 (${cacheSize} < ${MIN_VALID_CACHE})，視為損壞快取，將清除並重新加載`);
                try {
                    await TRCache.clearAll();
                    console.log('[TCG 快取] ✅ 已清除損壞的 IndexedDB 快取');
                } catch (clearError) {
                    console.error('[TCG 快取] ❌ 清除快取失敗:', clearError);
                }
                return false;  // 強制重新加載
            }

            tcgCache = cached.data;
            tcgCacheTimestamp = cached.ts || Date.now();
            console.log(`[TCG 快取] ✅ 快取驗證通過，使用本地快取`);
            return true;
        }
    } catch (error) {
        console.error('[TCG 快取] ❌ IndexedDB 讀取出錯:', error);
        // 如果讀取失敗，清除損壞的快取
        try {
            console.log('[TCG 快取] 嘗試清除損壞的 IndexedDB...');
            await TRCache.clearAll();
        } catch (e) {
            console.error('[TCG 快取] 清除失敗:', e);
        }
    }
    return false;
}

async function saveTCGCacheToStorage() {
    try {
        // 僅保存必要欄位，並以 TRCache（IndexedDB + gzip）存放
        const compact = Array.isArray(tcgCache)
            ? tcgCache.map(item => ({ tcg_number: item.tcg_number, title: item.title }))
            : [];

        console.log(`[TCG 保存] 準備保存 ${compact.length} 筆記錄到 IndexedDB`);

        // 驗證數據：不能為空且必須達到最小要求
        if (compact.length < 10000) {
            console.error(`[TCG 保存] ❌ 數據不完整，只有 ${compact.length} 筆 (期望 >= 10000)`);
            console.log('[TCG 保存] 不保存不完整的數據，等待下次同步');
            return false;
        }

        const success = await TRCache.setTCG(compact);
        console.log(`[TCG 保存] IndexedDB 保存結果: ${success ? '✅ 成功' : '❌ 失敗'}`);

        if (!success) {
            console.error('[TCG 保存] ❌ IndexedDB 保存失敗，可能原因:');
            console.log('  - pako 库:', typeof pako !== 'undefined' ? '✅ 已加載' : '❌ 未加載');
            console.log('  - IndexedDB 配額已滿');
            console.log('  - 瀏覽器不支持 IndexedDB');
        }

        adjustTestCasesScrollHeight();
        return success;
    } catch (error) {
        console.error('[TCG 保存] ❌ 出錯:', error);
        return false;
    }
}


function shouldUpdateTCGCache() {
    // 檢查是否需要更新快取
    if (!tcgCache || tcgCache.length === 0) {
        console.log('[TCG 快取] 檢查: 沒有快取，需要加載');
        return true;
    }

    // 如果快取太小，視為不完整
    const MIN_VALID_CACHE = 10000;
    if (tcgCache.length < MIN_VALID_CACHE) {
        console.warn(`[TCG 快取] 檢查: 快取過小 (${tcgCache.length} < ${MIN_VALID_CACHE})，需要重新加載`);
        return true;
    }

    // 檢查是否過期
    if (tcgCacheTimestamp && (Date.now() - tcgCacheTimestamp) > TCG_CACHE_EXPIRY) {
        console.log('[TCG 快取] 檢查: 快取已過期，需要更新');
        return true;
    }

    console.log(`[TCG 快取] 檢查: 使用有效快取 (${tcgCache.length} 筆記錄，年齡: ${((Date.now() - tcgCacheTimestamp) / 1000 / 60).toFixed(1)} 分鐘)`);
    return false;
}

async function loadTCGCache(updateProgress = null) {
    try {
        if (updateProgress) updateProgress(0, '開始載入 TCG 單號...');

        if (updateProgress) updateProgress(30, '從本地資料庫載入...');

        // 一次性從本地 SQLite 載入所有資料（極快）
        const response = await window.AuthClient.fetch('/api/tcg/search?keyword=&limit=50000', { timeout: 30000 });
        if (!response.ok) {
            throw new Error(`載入 TCG 失敗: ${response.status} ${response.statusText}`);
        }

        if (updateProgress) updateProgress(70, '解析 TCG 資料...');

        const data = await response.json();
        tcgCache = data.results || [];
        tcgCacheTimestamp = Date.now();

        const expectedCount = data.total;
        const actualCount = tcgCache.length;

        console.log(`[TCG 加載] API 返回 ${expectedCount} 筆，實際接收 ${actualCount} 筆`);

        // 驗證數據完整性
        const MIN_VALID_LOAD = 10000;
        if (actualCount < MIN_VALID_LOAD) {
            console.error(`[TCG 加載] ❌ 加載數據不完整: ${actualCount} < ${MIN_VALID_LOAD}`);
            tcgCache = [];  // 清空不完整的數據
            throw new Error(`加載的 TCG 數據過少 (${actualCount} < ${MIN_VALID_LOAD})`);
        }

        if (actualCount !== expectedCount) {
            console.warn(`[TCG 加載] ⚠️ 警告：期望 ${expectedCount} 筆但只獲得 ${actualCount} 筆`);
        }

        if (updateProgress) updateProgress(90, '儲存快取...');
        const saveSuccess = await saveTCGCacheToStorage();

        if (!saveSuccess) {
            console.warn(`[TCG 加載] ⚠️ IndexedDB 保存失敗，但記憶體快取已加載可用`);
            // 即使 IndexedDB 失敗，記憶體快取也能用，只是下次需要重新加載
        } else {
            console.log(`[TCG 加載] ✅ IndexedDB 保存成功`);
        }

        if (updateProgress) {
            const tcgCompletedMsg = window.i18n ? window.i18n.t('loading.completedWithCount', {count: tcgCache.length}) : `載入完成 (${tcgCache.length} 筆)`;
            updateProgress(100, tcgCompletedMsg);
        }

        console.log(`[TCG 加載] ✅ TCG 快取更新完成: ${tcgCache.length} 筆記錄`);
        return true;

    } catch (error) {
        console.error('[TCG 加載] ❌ 載入 TCG 快取失敗:', error);
        tcgCache = [];  // 清空無效數據
        tcgCacheTimestamp = 0;
        if (updateProgress) {
            updateProgress(0, '載入失敗: ' + error.message);
        }
        return false;
    } finally {
        // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
        adjustTestCasesScrollHeight();
    }
}
