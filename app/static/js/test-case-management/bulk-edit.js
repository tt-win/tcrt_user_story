/* ============================================================
   TEST CASE MANAGEMENT - BULK EDIT
   ============================================================ */

/* ============================================================
   24. 大量編輯 (Bulk Edit)
   ============================================================ */

// NOTE: bulkEdit* 相關變數已統一定義於 Section 2 (全域變數)

// 欄位對應表
const bulkEditColumns = [
    { key: 'index', title: '#', width: '40px', editable: false },
    { key: 'test_case_number', title: '測試案例編號', width: '180px', editable: false },
    { key: 'title', title: '標題', width: '200px', editable: true },
    { key: 'priority', title: '優先級', width: '100px', editable: true, type: 'select', options: ['High', 'Medium', 'Low'] },
    { key: 'precondition', title: '前置條件', width: '200px', editable: true, type: 'textarea' },
    { key: 'steps', title: '測試步驟', width: '250px', editable: true, type: 'textarea' },
    { key: 'expected_result', title: '預期結果', width: '200px', editable: true, type: 'textarea' }
];

function openBulkEditModal() {
    try {
        // 取得過濾後的測試案例或全部測試案例
        const dataToEdit = filteredTestCases && filteredTestCases.length > 0 ? filteredTestCases : testCases;

        if (!dataToEdit || dataToEdit.length === 0) {
            const noDataMsg = window.i18n ? window.i18n.t('errors.noTestCasesToEdit', {}, '沒有可編輯的測試案例') : '沒有可編輯的測試案例';
            AppUtils.showError(noDataMsg);
            return;
        }

        // 初始化編輯資料
        bulkEditData = dataToEdit.map((tc, index) => ({
            index: index + 1,
            record_id: tc.record_id,
            test_case_number: tc.test_case_number,
            title: tc.title || '',
            priority: tc.priority || 'Medium',
            precondition: tc.precondition || '',
            steps: tc.steps || '',
            expected_result: tc.expected_result || ''
        }));

        // 清除變更記錄
        bulkEditChanges.clear();
        bulkEditSelectedCells.clear();

        // 渲染表格
        renderBulkEditGrid();

        // 打開 Modal
        const modalEl = document.getElementById('bulkEditModal');
        if (!bulkEditModalInstance) {
            bulkEditModalInstance = new bootstrap.Modal(modalEl);
        }
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(modalEl);
        }
        bulkEditModalInstance.show();

        // 更新狀態
        updateBulkEditStatus();

    } catch (error) {
        console.error('openBulkEditModal error:', error);
        AppUtils.showError('開啟大量編輯失敗');
    }
}

function renderBulkEditGrid() {
    const tbody = document.getElementById('bulkEditGridBody');
    if (!tbody) return;

    tbody.innerHTML = bulkEditData.map(row => {
        const cells = bulkEditColumns.map(col => {
            const value = row[col.key];
            const cellId = `${row.record_id}_${col.key}`;
            const isEditable = col.editable;
            const cellClass = isEditable ? 'editable-cell' : '';

            let displayValue = value;
            if (col.type === 'textarea' && value && value.length > 50) {
                displayValue = value.substring(0, 47) + '...';
            }

            let inputHTML = '';
            if (isEditable) {
                // Escape HTML to prevent XSS and preserve formatting
                const escapedValue = (value || '').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

                if (col.type === 'select') {
                    const options = col.options.map(opt =>
                        `<option value="${opt}" ${opt === value ? 'selected' : ''}>${opt}</option>`
                    ).join('');
                    inputHTML = `<select class="cell-input form-select">${options}</select>`;
                } else if (col.type === 'textarea') {
                    // Use proper closing tag to avoid whitespace issue
                    inputHTML = `<textarea class="cell-input form-control">${escapedValue}</textarea>`;
                } else {
                    inputHTML = `<input type="text" class="cell-input form-control" value="${escapedValue}">`;
                }
            }

            // 對於 textarea，在顯示時去除前後空白
            const sanitizedDisplay = col.type === 'textarea' ? (displayValue || '').trim() : (displayValue || '');

            return `
                <td class="${cellClass}" data-record-id="${row.record_id}" data-column="${col.key}" data-cell-id="${cellId}">
                    <div class="cell-content ${col.type === 'textarea' ? 'multiline' : ''}" title="${value || ''}">${sanitizedDisplay}</div>${inputHTML}${isEditable ? '<div class="drag-handle"></div>' : ''}
                </td>
            `;
        }).join('');

        return `<tr data-record-id="${row.record_id}">${cells}</tr>`;
    }).join('');

    // 綁定事件
    bindBulkEditEvents();
}

function bindBulkEditEvents() {
    const grid = document.getElementById('bulkEditGrid');
    if (!grid) return;

    // 避免重複綁定事件：先移除舊的監聽器
    const oldMouseDown = grid._bulkEditMouseDown;
    const oldMouseMove = grid._bulkEditMouseMove;
    const oldMouseUp = grid._bulkEditMouseUp;
    const oldDblClick = grid._bulkEditDblClick;

    if (oldMouseDown) grid.removeEventListener('mousedown', oldMouseDown);
    if (oldMouseMove) grid.removeEventListener('mousemove', oldMouseMove);
    if (oldMouseUp) grid.removeEventListener('mouseup', oldMouseUp);
    if (oldDblClick) grid.removeEventListener('dblclick', oldDblClick);

    // 儲存格點擊事件
    const mouseDownHandler = function(e) {
        // 先處理 drag handle
        if (e.target.classList.contains('drag-handle')) {
            handleDragStart(e);
            return;
        }

        const cell = e.target.closest('td.editable-cell');
        if (cell) {
            handleCellClick(cell, e);
        }
    };
    grid.addEventListener('mousedown', mouseDownHandler);
    grid._bulkEditMouseDown = mouseDownHandler;

    // 拖移選取事件
    const mouseMoveHandler = function(e) {
        if (bulkEditSelectDragState) {
            handleSelectDragMove(e);
        } else if (bulkEditDragState) {
            handleDragMove(e);
        }
    };
    grid.addEventListener('mousemove', mouseMoveHandler);
    grid._bulkEditMouseMove = mouseMoveHandler;

    const mouseUpHandler = function(e) {
        if (bulkEditSelectDragState) {
            handleSelectDragEnd(e);
        } else if (bulkEditDragState) {
            handleDragEnd(e);
        }
    };
    grid.addEventListener('mouseup', mouseUpHandler);
    grid._bulkEditMouseUp = mouseUpHandler;

    // 儲存格雙擊編輯
    const dblClickHandler = function(e) {
        const cell = e.target.closest('td.editable-cell');
        if (cell) {
            startCellEdit(cell);
        }
    };
    grid.addEventListener('dblclick', dblClickHandler);
    grid._bulkEditDblClick = dblClickHandler;

    // 鍵盤事件
    document.addEventListener('keydown', handleBulkEditKeydown);

    // 工具列事件
    const openSearchBtn = document.getElementById('bulkEditOpenSearchBtn');
    if (openSearchBtn) {
        openSearchBtn.onclick = openSearchReplaceModal;
    }

    const saveBtn = document.getElementById('saveBulkEditBtn');
    if (saveBtn) {
        saveBtn.onclick = saveBulkEditChanges;
    }
}

function handleCellClick(cell, event) {
    const cellId = cell.dataset.cellId;

    if (event.ctrlKey || event.metaKey) {
        // Ctrl/Cmd + 點擊: 多選切換
        if (bulkEditSelectedCells.has(cellId)) {
            bulkEditSelectedCells.delete(cellId);
            cell.classList.remove('selected');
        } else {
            bulkEditSelectedCells.add(cellId);
            cell.classList.add('selected');
        }
    } else if (event.shiftKey && bulkEditSelectedCells.size > 0) {
        // Shift + 點擊: 範圍選取
        selectCellRange(cell);
    } else {
        // 一般點擊: 單選
        clearCellSelection();
        bulkEditSelectedCells.add(cellId);
        cell.classList.add('selected');

        // 開始拖移選取
        bulkEditSelectDragState = {
            startCell: cell,
            isSelecting: false
        };
    }
}

function selectCellRange(targetCell) {
    // 簡化實現: 選取同一欄位的範圍
    const targetColumn = targetCell.dataset.column;
    const allCellsInColumn = Array.from(document.querySelectorAll(`td[data-column="${targetColumn}"]`));
    const targetIndex = allCellsInColumn.indexOf(targetCell);

    // 找到當前選中的同欄位儲存格
    let lastSelectedIndex = -1;
    for (let i = 0; i < allCellsInColumn.length; i++) {
        const cell = allCellsInColumn[i];
        if (bulkEditSelectedCells.has(cell.dataset.cellId)) {
            lastSelectedIndex = i;
            break;
        }
    }

    if (lastSelectedIndex !== -1) {
        const startIndex = Math.min(lastSelectedIndex, targetIndex);
        const endIndex = Math.max(lastSelectedIndex, targetIndex);

        clearCellSelection();
        for (let i = startIndex; i <= endIndex; i++) {
            const cell = allCellsInColumn[i];
            if (cell && cell.classList.contains('editable-cell')) {
                bulkEditSelectedCells.add(cell.dataset.cellId);
                cell.classList.add('selected');
            }
        }
    }
}

function clearCellSelection() {
    bulkEditSelectedCells.clear();
    document.querySelectorAll('.bulk-edit-grid td.selected').forEach(cell => {
        cell.classList.remove('selected');
    });
}

function startCellEdit(cell) {
    if (cell.classList.contains('editing')) return;
    if (bulkEditCurrentCell) {
        finishCellEdit(bulkEditCurrentCell);
    }

    const recordId = cell.dataset.recordId;
    const column = cell.dataset.column;
    const colInfo = bulkEditColumns.find(c => c.key === column);

    if (!colInfo || !colInfo.editable) return;

    bulkEditCurrentCell = cell;
    cell.classList.add('editing');

    const input = cell.querySelector('.cell-input');
    if (input) {
        input.focus();
        if (input.tagName === 'INPUT' || input.tagName === 'TEXTAREA') {
            input.select();
        }

        // 為 textarea 設置 Markdown 快捷鍵
        if (input.tagName === 'TEXTAREA') {
            setupMarkdownHotkeys(input);
        }

        // 綁定事件
        input.onblur = () => finishCellEdit(cell);
        input.onkeydown = (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                finishCellEdit(cell);
            } else if (e.key === 'Escape') {
                e.preventDefault();
                cancelCellEdit(cell);
            } else if (e.key === 'Tab') {
                e.preventDefault();
                finishCellEdit(cell);
                // 移到下一個可編輯儲存格
                const nextCell = getNextEditableCell(cell, !e.shiftKey);
                if (nextCell) {
                    setTimeout(() => startCellEdit(nextCell), 10);
                }
            }
        };
    }
}

function finishCellEdit(cell) {
    if (!cell || !cell.classList.contains('editing')) return;

    const recordId = cell.dataset.recordId;
    const column = cell.dataset.column;
    const input = cell.querySelector('.cell-input');
    const cellContent = cell.querySelector('.cell-content');

    if (input) {
        const newValue = input.value.trim();
        const currentValue = getCellValue(recordId, column);

        if (newValue !== currentValue) {
            // 儲存到 undo 堆疊
            pushUndoState(recordId, column, currentValue, newValue);
            setCellValue(recordId, column, newValue);
            updateBulkEditStatus();
        }

        // 更新顯示
        let displayValue = newValue;
        if (newValue.length > 50) {
            displayValue = newValue.substring(0, 47) + '...';
        }
        cellContent.textContent = displayValue;
        cellContent.title = newValue;
    }

    cell.classList.remove('editing');
    bulkEditCurrentCell = null;
}

function cancelCellEdit(cell) {
    if (!cell || !cell.classList.contains('editing')) return;
    cell.classList.remove('editing');
    bulkEditCurrentCell = null;
}

function getNextEditableCell(currentCell, forward = true) {
    const allCells = Array.from(document.querySelectorAll('.bulk-edit-grid td.editable-cell'));
    const currentIndex = allCells.indexOf(currentCell);
    if (currentIndex === -1) return null;

    const nextIndex = forward ? currentIndex + 1 : currentIndex - 1;
    if (nextIndex >= 0 && nextIndex < allCells.length) {
        return allCells[nextIndex];
    }
    return null;
}

function getCellValue(recordId, column) {
    // 優先從變更記錄中取值
    const changes = bulkEditChanges.get(recordId);
    if (changes && changes.hasOwnProperty(column)) {
        return changes[column];
    }

    // 從原始資料中取值
    const row = bulkEditData.find(r => r.record_id === recordId);
    return row ? (row[column] || '') : '';
}

function setCellValue(recordId, column, value) {
    if (!bulkEditChanges.has(recordId)) {
        bulkEditChanges.set(recordId, {});
    }
    bulkEditChanges.get(recordId)[column] = value;

    // 同時更新本地資料以便显示
    const row = bulkEditData.find(r => r.record_id === recordId);
    if (row) {
        row[column] = value;
    }
}

function handleBulkEditKeydown(event) {
    // 只在 bulk edit modal 打開時處理
    const modal = document.getElementById('bulkEditModal');
    if (!modal || !modal.classList.contains('show')) return;

    // 如果搜尋替換 Modal 打開，不處理快捷鍵（讓 Modal 中的輸入框正常工作）
    const searchModal = document.getElementById('bulkEditSearchModal');
    if (searchModal && searchModal.classList.contains('show')) return;

    // 如果正在編輯儲存格，不處理快捷鍵
    if (bulkEditCurrentCell) return;

    if ((event.ctrlKey || event.metaKey) && event.key === 'z') {
        // Ctrl+Z: 復原
        performUndo();
        event.preventDefault();
    } else if ((event.ctrlKey || event.metaKey) && event.key === 'c') {
        // Ctrl+C: 複製
        console.log('複製快捷鍵觸發');
        copySelectedCells().catch(err => {
            console.error('複製失敗 (caught in keydown):', err);
        });
        event.preventDefault();
    } else if ((event.ctrlKey || event.metaKey) && event.key === 'v') {
        // Ctrl+V: 貼上
        // console.log('貼上快捷鍵觸發');
        pasteToSelectedCells().catch(err => {
            console.error('貼上失敗 (caught in keydown):', err);
        });
        event.preventDefault();
    }
}

// 開始一個新的 undo 操作
function beginUndoOperation(operationType = 'edit') {
    bulkEditCurrentOperation = {
        type: operationType, // 'edit', 'paste', 'drag-fill', etc.
        changes: [],
        timestamp: Date.now()
    };
}

// 將單個儲存格變更加入當前操作組
function addToCurrentOperation(recordId, column, oldValue, newValue) {
    if (!bulkEditCurrentOperation) {
        console.warn('No current operation, auto-creating one');
        beginUndoOperation('edit');
    }

    bulkEditCurrentOperation.changes.push({
        recordId,
        column,
        oldValue,
        newValue
    });
}

// 向後兼容：立即提交的單個變更（使用於單個儲存格編輯）
function pushUndoState(recordId, column, oldValue, newValue) {
    // 如果沒有當前操作，自動建立一個
    if (!bulkEditCurrentOperation) {
        beginUndoOperation('edit');
    }

    bulkEditCurrentOperation.changes.push({
        recordId,
        column,
        oldValue,
        newValue
    });
}

// 完成當前操作，加入 undo 堆疊
function commitUndoOperation() {
    if (!bulkEditCurrentOperation || bulkEditCurrentOperation.changes.length === 0) {
        bulkEditCurrentOperation = null;
        return;
    }

    bulkEditUndoStack.push(bulkEditCurrentOperation);
    bulkEditCurrentOperation = null;

    // 限制 undo 堆疊大小
    if (bulkEditUndoStack.length > 50) {
        bulkEditUndoStack.shift();
    }

    // 啟用 undo 按鈕
    const undoBtn = document.getElementById('bulkEditUndoBtn');
    if (undoBtn) undoBtn.disabled = false;
}

function performUndo() {
    if (bulkEditUndoStack.length === 0) return;

    // 取出最後一個操作
    const operation = bulkEditUndoStack.pop();
    const changesCount = operation.changes.length;

    console.log(`復原操作：${operation.type}，共 ${changesCount} 個變更`);

    // 批次恢復所有變更
    operation.changes.forEach(change => {
        const { recordId, column, oldValue } = change;

        // 恢復舊值
        if (!bulkEditChanges.has(recordId)) {
            bulkEditChanges.set(recordId, {});
        }
        bulkEditChanges.get(recordId)[column] = oldValue;

        // 更新本地資料
        const row = bulkEditData.find(r => r.record_id === recordId);
        if (row) {
            row[column] = oldValue;
        }

        // 更新顯示
        const cell = document.querySelector(`td[data-record-id="${recordId}"][data-column="${column}"]`);
        if (cell) {
            const cellContent = cell.querySelector('.cell-content');
            const cellInput = cell.querySelector('.cell-input');

            // 檢查是否為 textarea 類型
            const colInfo = bulkEditColumns.find(c => c.key === column);
            const isTextarea = colInfo && colInfo.type === 'textarea';

            let displayValue = oldValue;
            if (isTextarea) {
                displayValue = oldValue.trim();
            }
            if (displayValue.length > 50) {
                displayValue = displayValue.substring(0, 47) + '...';
            }

            if (cellContent) {
                cellContent.textContent = displayValue;
                cellContent.title = oldValue;
            }
            if (cellInput) {
                if (cellInput.tagName === 'TEXTAREA') {
                    cellInput.textContent = oldValue;
                } else {
                    cellInput.value = oldValue;
                }
            }
        }
    });

    updateBulkEditStatus();

    // 顯示提示
    const toast = document.createElement('div');
    toast.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #17a2b8; color: white; padding: 12px 24px; border-radius: 4px; z-index: 10000; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);';
    toast.textContent = `↺ 已復原 ${changesCount} 個儲存格`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2000);

    // 如果 undo 堆疊空了，停用按鈕
    const undoBtn = document.getElementById('bulkEditUndoBtn');
    if (undoBtn) {
        undoBtn.disabled = bulkEditUndoStack.length === 0;
    }
}

async function copySelectedCells() {
    if (bulkEditSelectedCells.size === 0) {
        console.warn('⚠️ 沒有選中任何儲存格');

        // 顯示提示
        const toast = document.createElement('div');
        toast.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #dc3545; color: white; padding: 12px 24px; border-radius: 4px; z-index: 10000; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);';
        toast.textContent = '⚠️ 請先選取儲存格';
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2000);
        return;
    }

    // 收集所有選中儲存格的資料
    const selectedData = [];
    const cellsArray = Array.from(bulkEditSelectedCells);

    // console.log('複製開始，選中', cellsArray.length, '個儲存格');

    // 按行和列排序
    const cellsWithPosition = cellsArray.map(cellId => {
        // 從 DOM 元素直接取得 recordId 和 column，避免 split 問題
        const cell = document.querySelector(`td[data-cell-id="${cellId}"]`);
        if (!cell) {
            console.warn('找不到儲存格:', cellId);
            return null;
        }

        const recordId = cell.dataset.recordId;
        const column = cell.dataset.column;
        const row = cell.closest('tr');
        const allRows = Array.from(document.querySelectorAll('.bulk-edit-grid tbody tr'));
        const rowIndex = allRows.indexOf(row);
        const colIndex = bulkEditColumns.findIndex(c => c.key === column);
        const value = getCellValue(recordId, column);

        // console.log(`儲存格 ${cellId}: row=${rowIndex}, col=${colIndex}, column=${column}, value=${value}`);

        return {
            cellId,
            recordId,
            column,
            rowIndex,
            colIndex,
            value
        };
    }).filter(c => c !== null && c.rowIndex >= 0 && c.colIndex >= 0);

    // console.log('有效儲存格數量:', cellsWithPosition.length);

    // 排序: 先按行再按列
    cellsWithPosition.sort((a, b) => {
        if (a.rowIndex !== b.rowIndex) return a.rowIndex - b.rowIndex;
        return a.colIndex - b.colIndex;
    });

    // 建立二維表格結構
    const grid = {};
    cellsWithPosition.forEach(cell => {
        if (!grid[cell.rowIndex]) grid[cell.rowIndex] = {};
        grid[cell.rowIndex][cell.colIndex] = cell.value;
    });

    // 轉換為 TSV 格式 (類似 Excel)
    // 處理特殊字元：如果值包含 \n, \t 或 " 則需要用引號包裹
    function escapeTsvValue(value) {
        if (value === null || value === undefined) return '';
        const strValue = String(value);
        // 如果包含換行、Tab 或引號，需要用雙引號包裹
        if (strValue.includes('\n') || strValue.includes('\t') || strValue.includes('"')) {
            // 將內部的引號轉義為兩個引號
            return '"' + strValue.replace(/"/g, '""') + '"';
        }
        return strValue;
    }

    const rows = Object.keys(grid).sort((a, b) => parseInt(a) - parseInt(b));
    const tsvData = rows.map(rowIdx => {
        const rowData = grid[rowIdx];
        const cols = Object.keys(rowData).sort((a, b) => parseInt(a) - parseInt(b));
        return cols.map(colIdx => escapeTsvValue(rowData[colIdx] || '')).join('\t');
    }).join('\n');

    // console.log('TSV 資料:', tsvData.substring(0, 100), '...');
    // console.log('TSV 長度:', tsvData.length, '字符');

    // 儲存到內部剪貼簿（作為備用）
    bulkEditClipboard.content = tsvData;
    bulkEditClipboard.cellsData = cellsWithPosition;
    bulkEditClipboard.cells = cellsArray;
    // console.log('✅ 已儲存到內部剪貼簿');

    // 複製到系統剪貼簿
    let clipboardSuccess = false;

    // 檢查當前環境
    const isSecureContext = window.isSecureContext;
    const hasClipboardAPI = navigator.clipboard && navigator.clipboard.writeText;

    // 方法1：嘗試使用 Clipboard API（僅在安全上下文下可用）
    if (hasClipboardAPI && isSecureContext) {
        try {
        await navigator.clipboard.writeText(tsvData);
            // console.log('✅ 系統剪貼簿寫入成功 (Clipboard API)');
            clipboardSuccess = true;
        } catch (err) {
            // console.warn('⚠️ Clipboard API 失敗:', err.name, err.message);
        }
    }

    // 方法2：如果 Clipboard API 失敗，嘗試使用 execCommand
    if (!clipboardSuccess) {
        // console.log('嘗試使用 execCommand 方式...');
        try {
            const textarea = document.createElement('textarea');
            textarea.value = tsvData;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            const success = document.execCommand('copy');
            document.body.removeChild(textarea);

            if (success) {
                // console.log('✅ 系統剪貼簿寫入成功 (execCommand)');
                clipboardSuccess = true;
            } else {
                // console.warn('⚠️ execCommand 返回 false');
            }
        } catch (err) {
            console.error('❌ execCommand 失敗:', err);
        }
    }

    // console.log('=== 複製結束 ===');

    // 顯示視覺回饋
    const toast = document.createElement('div');
    toast.style.cssText = 'position: fixed; top: 20px; right: 20px; padding: 12px 24px; border-radius: 4px; z-index: 10000; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);';

    if (clipboardSuccess) {
        toast.style.background = '#28a745';
        toast.style.color = 'white';
        toast.textContent = `✅ 已複製 ${cellsWithPosition.length} 個儲存格`;
    } else {
        toast.style.background = '#ffc107';
        toast.style.color = 'black';
        toast.textContent = `⚠️ 已儲存到內部剪貼簿（${cellsWithPosition.length} 個儲存格）`;
    }

    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2000);
}

async function pasteToSelectedCells() {
    // console.log('貼上函數被呼叫, 選中', bulkEditSelectedCells.size, '個儲存格');

    if (bulkEditSelectedCells.size === 0) {
        console.warn('⚠️ 沒有選中任何儲存格');

        const toast = document.createElement('div');
        toast.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #dc3545; color: white; padding: 12px 24px; border-radius: 4px; z-index: 10000; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);';
        toast.textContent = '⚠️ 請先選取儲存格';
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 2000);
        return;
    }

    // 開始新的 undo 操作組
    beginUndoOperation();

    try {
        // 嘗試從系統剪貼簿讀取
        let clipboardText = '';
        try {
            clipboardText = await navigator.clipboard.readText();
        } catch (err) {
            // 如果無法讀取系統剪貼簿，使用內部剪貼簿
            clipboardText = bulkEditClipboard.content || '';
        }

        if (!clipboardText) {
            console.warn('⚠️ 剪貼簿空白');
            return;
        }

        // 解析 TSV 資料 (支援 Excel 複製貼上和包含換行的儲存格)
        function parseTsvRow(row) {
            const result = [];
            let current = '';
            let inQuotes = false;
            let i = 0;

            while (i < row.length) {
                const char = row[i];

                if (inQuotes) {
                    if (char === '"') {
                        // 檢查下一個字元
                        if (i + 1 < row.length && row[i + 1] === '"') {
                            // 兩個連續的引號代表一個引號字元
                            current += '"';
                            i += 2;
                            continue;
                        } else {
                            // 單個引號代表引號結束
                            inQuotes = false;
                            i++;
                            continue;
                        }
                    } else {
                        // 在引號內，所有字元（包括 \n 和 \t）都是值的一部分
                        current += char;
                        i++;
                    }
                } else {
                    if (char === '"') {
                        // 開始引號
                        inQuotes = true;
                        i++;
                    } else if (char === '\t') {
                        // Tab 分隔符，儲存當前值並開始新值
                        result.push(current);
                        current = '';
                        i++;
                    } else {
                        // 普通字元
                        current += char;
                        i++;
                    }
                }
            }

            // 加入最後一個值
            result.push(current);
            return result;
        }

        // 分割行時要考慮引號內的換行
        const rows = [];
        let currentRow = '';
        let inQuotes = false;

        for (let i = 0; i < clipboardText.length; i++) {
            const char = clipboardText[i];

            if (char === '"') {
                currentRow += char;
                // 檢查是否為轉義的引號
                if (i + 1 < clipboardText.length && clipboardText[i + 1] === '"') {
                    currentRow += clipboardText[i + 1];
                    i++;
                } else {
                    inQuotes = !inQuotes;
                }
            } else if (char === '\n' && !inQuotes) {
                // 只有在引號外的換行才是行分隔符
                if (currentRow.trim()) {
                    rows.push(currentRow);
                }
                currentRow = '';
            } else {
                currentRow += char;
            }
        }

        // 加入最後一行
        if (currentRow.trim()) {
            rows.push(currentRow);
        }

        const data = rows.map(row => parseTsvRow(row));

        // console.log('解析後的資料:', data.length, '行 x', data[0]?.length || 0, '列');

        const selectedCellsArray = Array.from(bulkEditSelectedCells);

        const cellsWithPosition = selectedCellsArray.map(cellId => {
            const cell = document.querySelector(`td[data-cell-id="${cellId}"]`);
            if (!cell) {
                console.warn('找不到儲存格:', cellId);
                return null;
            }

            const row = cell.closest('tr');
            const allRows = Array.from(document.querySelectorAll('.bulk-edit-grid tbody tr'));
            const rowIndex = allRows.indexOf(row);
            const colIndex = bulkEditColumns.findIndex(c => c.key === cell.dataset.column);

            return { cellId, cell, rowIndex, colIndex, column: cell.dataset.column };
        }).filter(c => c !== null);

        if (cellsWithPosition.length === 0) return;

        // 排序找到起始儲存格（最左上角）
        cellsWithPosition.sort((a, b) => {
            if (a.rowIndex !== b.rowIndex) return a.rowIndex - b.rowIndex;
            return a.colIndex - b.colIndex;
        });

        const firstCellPos = cellsWithPosition[0];
        const startRowIndex = firstCellPos.rowIndex;
        const startColIndex = firstCellPos.colIndex;
        const allRows = Array.from(document.querySelectorAll('.bulk-edit-grid tbody tr'));

        // 計算選取範圍的大小
        const lastCellPos = cellsWithPosition[cellsWithPosition.length - 1];
        const selectedRowCount = lastCellPos.rowIndex - startRowIndex + 1;
        const selectedColCount = lastCellPos.colIndex - startColIndex + 1;

        const dataRowCount = data.length;
        const dataColCount = data[0]?.length || 0;

        let pasteCount = 0;

        // 智能貼上：根據選取範圍和資料範圍決定貼上策略
        // 如果選取範圍比資料範圍大，則重複貼上（類似 Excel）
        const targetRowCount = Math.max(selectedRowCount, dataRowCount);
        const targetColCount = Math.max(selectedColCount, dataColCount);

        for (let i = 0; i < targetRowCount; i++) {
            const targetRowIndex = startRowIndex + i;
            if (targetRowIndex >= allRows.length) break;

            const targetRow = allRows[targetRowIndex];
            const recordId = targetRow.dataset.recordId;

            // 使用 modulo 運算實現重複貼上
            const dataRowIndex = i % dataRowCount;

            for (let j = 0; j < targetColCount; j++) {
                const targetColIndex = startColIndex + j;
                if (targetColIndex >= bulkEditColumns.length) break;

                const column = bulkEditColumns[targetColIndex];
                if (!column.editable) continue;

                // 使用 modulo 運算實現重複貼上
                const dataColIndex = j % dataColCount;
                const value = data[dataRowIndex][dataColIndex] || '';

                const cellId = `${recordId}_${column.key}`;
                const currentValue = getCellValue(recordId, column.key);

                if (value !== currentValue) {
                    addToCurrentOperation(recordId, column.key, currentValue, value);
                    setCellValue(recordId, column.key, value);

                    // 更新顯示
                    const cell = document.querySelector(`td[data-cell-id="${cellId}"]`);
                    if (cell) {
                        const cellContent = cell.querySelector('.cell-content');
                        const cellInput = cell.querySelector('.cell-input');

                        let displayValue = value;
                        // 檢查是否為 textarea 類型
                        const isTextarea = column.type === 'textarea';
                        if (isTextarea) {
                            displayValue = value.trim();
                        }
                        if (displayValue.length > 50) {
                            displayValue = displayValue.substring(0, 47) + '...';
                        }

                        if (cellContent) {
                            cellContent.textContent = displayValue;
                            cellContent.title = value;
                        }
                        if (cellInput) {
                            if (cellInput.tagName === 'TEXTAREA') {
                                cellInput.textContent = value;
                            } else {
                                cellInput.value = value;
                            }
                        }
                    }

                    pasteCount++;
                }
            }
        }

        updateBulkEditStatus();

        // 提交 undo 操作（只有在有改變時才提交）
        if (pasteCount > 0) {
            commitUndoOperation();

            // 顯示成功提示
            const toast = document.createElement('div');
            toast.style.cssText = 'position: fixed; top: 20px; right: 20px; background: #28a745; color: white; padding: 12px 24px; border-radius: 4px; z-index: 10000; font-size: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);';
            toast.textContent = `✅ 已貼上 ${pasteCount} 個儲存格`;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 2000);
        } else {
            // 如果沒有任何改變，取消操作組
            bulkEditCurrentOperation = null;
        }

    } catch (err) {
        console.error('貼上失敗:', err);
        AppUtils.showError('貼上失敗');
        // 發生錯誤時取消當前操作組
        bulkEditCurrentOperation = null;
    }
}

function handleDragStart(event) {
    const dragHandle = event.target;
    if (!dragHandle || !dragHandle.classList.contains('drag-handle')) return;

    event.preventDefault();

    const cell = dragHandle.closest('td');
    if (!cell) return;

    const recordId = cell.dataset.recordId;
    const column = cell.dataset.column;
    const sourceValue = getCellValue(recordId, column);

    bulkEditDragState = {
        startCell: cell,
        column: column,
        sourceValue: sourceValue,
        affectedCells: new Set([cell])
    };

    // 添加視覺回饋
    cell.style.opacity = '0.7';
}

function handleDragMove(event) {
    if (!bulkEditDragState) return;

    event.preventDefault();

    const targetElement = document.elementFromPoint(event.clientX, event.clientY);
    const targetCell = targetElement ? targetElement.closest('td.editable-cell') : null;

    if (targetCell && targetCell.dataset.column === bulkEditDragState.column) {
        // 添加預覽效果
        if (!bulkEditDragState.affectedCells.has(targetCell)) {
            bulkEditDragState.affectedCells.add(targetCell);
            targetCell.style.backgroundColor = '#d0e8ff';
        }
    }
}

function handleDragEnd(event) {
    if (!bulkEditDragState) return;

    event.preventDefault();

    const { startCell, column, sourceValue, affectedCells } = bulkEditDragState;

    // 移除視覺效果
    startCell.style.opacity = '';

    // 開始新的 undo 操作組
    beginUndoOperation();
    let changeCount = 0;

    // 應用變更
    affectedCells.forEach(cell => {
        if (cell === startCell) return; // 跳過來源儲存格

        const targetRecordId = cell.dataset.recordId;
        const currentValue = getCellValue(targetRecordId, column);

        if (currentValue !== sourceValue) {
            addToCurrentOperation(targetRecordId, column, currentValue, sourceValue);
            setCellValue(targetRecordId, column, sourceValue);
            changeCount++;

            // 更新顯示
            const cellContent = cell.querySelector('.cell-content');
            const cellInput = cell.querySelector('.cell-input');

            let displayValue = sourceValue;
            if (sourceValue.length > 50) {
                displayValue = sourceValue.substring(0, 47) + '...';
            }

            if (cellContent) {
                cellContent.textContent = displayValue;
                cellContent.title = sourceValue;
            }
            if (cellInput) {
                cellInput.value = sourceValue;
            }
        }

        // 移除預覽效果
        cell.style.backgroundColor = '';
    });

    // 提交 undo 操作（只有在有改變時才提交）
    if (changeCount > 0) {
        commitUndoOperation();
    } else {
        bulkEditCurrentOperation = null;
    }

    updateBulkEditStatus();
    bulkEditDragState = null;
}

function updateBulkEditStatus() {
    const statusEl = document.getElementById('bulkEditStatus');
    const changeCountEl = document.getElementById('bulkEditChangeCount');

    if (statusEl) {
        const count = bulkEditData.length;
        const statusText = window.i18n ?
            window.i18n.t('testCase.bulkEdit.editingCount', {count}, `編輯 ${count} 筆資料`) :
            `編輯 ${count} 筆資料`;
        statusEl.innerHTML = `<span>${statusText}</span>`;
    }

    if (changeCountEl) {
        const changeCount = bulkEditChanges.size;
        const changeText = window.i18n ?
            window.i18n.t('testCase.bulkEdit.changedCount', {count: changeCount}, `已修改 ${changeCount} 筆`) :
            `已修改 ${changeCount} 筆`;
        changeCountEl.innerHTML = `<span>${changeText}</span>`;

        // 啟用/停用儲存按鈕
        const saveBtn = document.getElementById('saveBulkEditBtn');
        if (saveBtn) {
            saveBtn.disabled = changeCount === 0;
        }
    }
}

function openSearchReplaceModal() {
    const modalEl = document.getElementById('bulkEditSearchModal');
    if (!bulkEditSearchModalInstance) {
        bulkEditSearchModalInstance = new bootstrap.Modal(modalEl);
    }

    // 清除之前的搜尋結果
    bulkEditSearchResults = [];
    bulkEditCheckedResults = new Set();

    // 綁定事件
    const searchBtn = document.getElementById('bulkEditSearchBtn');
    const replaceBtn = document.getElementById('bulkEditReplaceBtn');
    const selectAllBtn = document.getElementById('bulkEditSelectAllBtn');
    const deselectAllBtn = document.getElementById('bulkEditDeselectAllBtn');

    if (searchBtn) searchBtn.onclick = performSearch;
    if (replaceBtn) replaceBtn.onclick = performSearchReplace;
    if (selectAllBtn) selectAllBtn.onclick = selectAllSearchResults;
    if (deselectAllBtn) deselectAllBtn.onclick = deselectAllSearchResults;

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(modalEl);
    }
    bulkEditSearchModalInstance.show();
}

function performSearch() {
    const searchText = document.getElementById('bulkEditSearchText').value.trim();
    const searchColumn = document.getElementById('bulkEditSearchColumn').value;

    if (!searchText) {
        AppUtils.showError('請輸入搜尋內容');
        return;
    }

    // 清除之前的搜尋結果
    bulkEditSearchResults = [];
    bulkEditCheckedResults = new Set();

    // 確定要搜尋的欄位
    const columnsToSearch = searchColumn === 'all' ?
        ['title', 'precondition', 'steps', 'expected_result'] : [searchColumn];

    let resultId = 0;

    // 搜尋數據
    bulkEditData.forEach((row, rowIndex) => {
        columnsToSearch.forEach(column => {
            const currentValue = String(getCellValue(row.record_id, column) || '');
            let searchIndex = 0;
            let matchIndex;

            // 找出所有匹配項
            while ((matchIndex = currentValue.indexOf(searchText, searchIndex)) !== -1) {
                const contextStartIndex = Math.max(0, matchIndex - 30);
                const contextEndIndex = Math.min(currentValue.length, matchIndex + searchText.length + 30);

                bulkEditSearchResults.push({
                    resultId: resultId++,
                    recordId: row.record_id,
                    rowIndex: rowIndex,
                    testCaseNumber: row.test_case_number,
                    column: column,
                    columnTitle: getColumnTitle(column),
                    matchText: searchText,
                    fullValue: currentValue,
                    matchIndex: matchIndex,
                    contextBefore: currentValue.substring(contextStartIndex, matchIndex),
                    contextMatch: searchText,
                    contextAfter: currentValue.substring(matchIndex + searchText.length, contextEndIndex),
                    checked: true // 默認勾選所有結果
                });

                // 將此結果加入勾選集合
                bulkEditCheckedResults.add(resultId - 1);

                searchIndex = matchIndex + searchText.length;
            }
        });
    });

    // 顯示搜尋結果
    displaySearchResults();
}

function displaySearchResults() {
    const searchResultsDiv = document.getElementById('bulkEditSearchResults');
    const resultsList = document.getElementById('bulkEditResultsList');
    const resultCount = document.getElementById('bulkEditResultCount');
    const searchBtn = document.getElementById('bulkEditSearchBtn');
    const replaceBtn = document.getElementById('bulkEditReplaceBtn');

    if (bulkEditSearchResults.length === 0) {
        AppUtils.showInfo('未找到符合項目');
        searchResultsDiv.style.display = 'none';
        searchBtn.style.display = 'inline-block';
        replaceBtn.style.display = 'none';
        return;
    }

    resultCount.textContent = bulkEditSearchResults.length;
    resultsList.innerHTML = '';

    bulkEditSearchResults.forEach((result) => {
        const itemDiv = document.createElement('div');
        itemDiv.className = 'list-group-item';
        itemDiv.style.cursor = 'pointer';

        const isChecked = bulkEditCheckedResults.has(result.resultId);

        let truncatedContext = (result.contextBefore + result.contextMatch + result.contextAfter);
        if (truncatedContext.length > 100) {
            truncatedContext = truncatedContext.substring(0, 97) + '...';
        }

        itemDiv.innerHTML = `
            <div class="d-flex align-items-start gap-2">
                <input type="checkbox" class="form-check-input search-result-checkbox"
                       data-result-id="${result.resultId}"
                       ${isChecked ? 'checked' : ''}
                       style="margin-top: 0.3rem;">
                <div style="flex: 1; min-width: 0;">
                    <small class="text-muted">
                        <strong>${result.testCaseNumber}</strong> · ${result.columnTitle}
                    </small>
                    <div class="text-break small mt-1" style="word-break: break-word;">
                        <span class="text-muted">${escapeHtml(result.contextBefore)}</span><mark>${escapeHtml(result.contextMatch)}</mark><span class="text-muted">${escapeHtml(result.contextAfter)}</span>
                    </div>
                </div>
            </div>
        `;

        itemDiv.addEventListener('click', (e) => {
            if (e.target.classList.contains('search-result-checkbox')) {
                const checkbox = e.target;
                const resultId = parseInt(checkbox.dataset.resultId);
                if (checkbox.checked) {
                    bulkEditCheckedResults.add(resultId);
                } else {
                    bulkEditCheckedResults.delete(resultId);
                }
            } else {
                const checkbox = itemDiv.querySelector('.search-result-checkbox');
                checkbox.checked = !checkbox.checked;
                const resultId = parseInt(checkbox.dataset.resultId);
                if (checkbox.checked) {
                    bulkEditCheckedResults.add(resultId);
                } else {
                    bulkEditCheckedResults.delete(resultId);
                }
            }
        });

        resultsList.appendChild(itemDiv);
    });

    // 顯示搜尋結果區域，保留搜尋按鈕供修改條件後重新搜尋
    searchResultsDiv.style.display = 'block';
    searchBtn.style.display = 'inline-block';
    replaceBtn.style.display = 'inline-block';
}

function selectAllSearchResults() {
    bulkEditSearchResults.forEach((result) => {
        bulkEditCheckedResults.add(result.resultId);
    });

    // 更新所有 checkbox
    document.querySelectorAll('.search-result-checkbox').forEach(checkbox => {
        checkbox.checked = true;
    });
}

function deselectAllSearchResults() {
    bulkEditCheckedResults.clear();

    // 更新所有 checkbox
    document.querySelectorAll('.search-result-checkbox').forEach(checkbox => {
        checkbox.checked = false;
    });
}

function getColumnTitle(column) {
    const columnMap = {
        'title': '標題',
        'precondition': '前置條件',
        'steps': '測試步驟',
        'expected_result': '預期結果'
    };
    return columnMap[column] || column;
}

function performSearchReplace() {
    const searchText = document.getElementById('bulkEditSearchText').value.trim();
    const replaceText = document.getElementById('bulkEditReplaceText').value;

    if (!searchText) {
        AppUtils.showError('請輸入搜尋內容');
        return;
    }

    // 檢查是否有搜尋結果和勾選的結果
    if (bulkEditSearchResults.length === 0) {
        AppUtils.showError('請先執行搜尋');
        return;
    }

    if (bulkEditCheckedResults.size === 0) {
        AppUtils.showError('請選擇至少一個結果進行取代');
        return;
    }

    // 開始新的 undo 操作組
    beginUndoOperation();

    let replaceCount = 0;
    const updatedRecords = new Map(); // 記錄每個記錄的更新情況

    // 按記錄和列分組被勾選的搜尋結果
    const groupedResults = new Map();
    bulkEditCheckedResults.forEach(resultId => {
        const result = bulkEditSearchResults[resultId];
        if (!result) return;

        if (!groupedResults.has(result.recordId)) {
            groupedResults.set(result.recordId, new Map());
        }
        const columnMap = groupedResults.get(result.recordId);
        if (!columnMap.has(result.column)) {
            columnMap.set(result.column, []);
        }
        columnMap.get(result.column).push(result);
    });

    // 對每個單元格進行替換
    groupedResults.forEach((columnMap, recordId) => {
        columnMap.forEach((cellResults, column) => {
            let currentValue = getCellValue(recordId, column);

            // 將搜尋結果按匹配位置從後往前排序，避免替換後位置錯位
            cellResults.sort((a, b) => b.matchIndex - a.matchIndex);

            // 逐個替換
            cellResults.forEach(result => {
                const beforeValue = currentValue;
                // 找出當前值中匹配的位置並替換
                const matchIndex = currentValue.indexOf(searchText);
                if (matchIndex !== -1) {
                    currentValue = currentValue.substring(0, matchIndex) + replaceText + currentValue.substring(matchIndex + searchText.length);
                    replaceCount++;
                }
            });

            // 如果有改變，保存新值
            const originalValue = getCellValue(recordId, column);
            if (currentValue !== originalValue) {
                addToCurrentOperation(recordId, column, originalValue, currentValue);
                setCellValue(recordId, column, currentValue);

                // 更新顯示
                const cell = document.querySelector(`td[data-record-id="${recordId}"][data-column="${column}"]`);
                if (cell) {
                    const cellContent = cell.querySelector('.cell-content');
                    if (cellContent) {
                        let displayValue = currentValue;
                        if (currentValue.length > 50) {
                            displayValue = currentValue.substring(0, 47) + '...';
                        }
                        cellContent.textContent = displayValue;
                        cellContent.title = currentValue;
                    }

                    // 同時更新 cell-input，以便編輯時顯示最新的值
                    const cellInput = cell.querySelector('.cell-input');
                    if (cellInput) {
                        cellInput.value = currentValue;
                    }
                }

                // 記錄更新過的記錄
                if (!updatedRecords.has(recordId)) {
                    updatedRecords.set(recordId, []);
                }
                updatedRecords.get(recordId).push(column);
            }
        });
    });

    // 提交 undo 操作（只有在有改變時才提交）
    if (replaceCount > 0) {
        commitUndoOperation();
    } else {
        bulkEditCurrentOperation = null;
    }

    updateBulkEditStatus();
    bulkEditSearchModalInstance.hide();

    const successMsg = `取代完成，共取代 ${replaceCount} 個位置，更新 ${updatedRecords.size} 筆資料`;
    AppUtils.showSuccess(successMsg);
}
