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
