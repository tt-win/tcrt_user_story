/* ============================================================
   TEST CASE MANAGEMENT - DRAG SELECTION
   ============================================================ */

/* ============================================================
   25. 拖移選取功能 (Drag Selection)
   ============================================================ */

/**
 * 處理拖移選取移動
 */
function handleSelectDragMove(event) {
    if (!bulkEditSelectDragState) return;

    const targetElement = document.elementFromPoint(event.clientX, event.clientY);
    const targetCell = targetElement ? targetElement.closest('td.editable-cell') : null;

    if (!targetCell) return;

    // 標記為正在選取（只要滑鼠移動就開始選取）
    if (!bulkEditSelectDragState.isSelecting) {
        bulkEditSelectDragState.isSelecting = true;
        // 清除原本的單一選取
        clearCellSelection();
    }

    // 清除舊的選取
    document.querySelectorAll('.bulk-edit-grid td.selecting').forEach(cell => {
        cell.classList.remove('selecting');
    });

    // 計算選取範圍
    const startCell = bulkEditSelectDragState.startCell;
    const startRow = startCell.closest('tr');
    const endRow = targetCell.closest('tr');

    const allRows = Array.from(document.querySelectorAll('.bulk-edit-grid tbody tr'));
    const startRowIndex = allRows.indexOf(startRow);
    const endRowIndex = allRows.indexOf(endRow);

    const startColIndex = bulkEditColumns.findIndex(c => c.key === startCell.dataset.column);
    const endColIndex = bulkEditColumns.findIndex(c => c.key === targetCell.dataset.column);

    const minRow = Math.min(startRowIndex, endRowIndex);
    const maxRow = Math.max(startRowIndex, endRowIndex);
    const minCol = Math.min(startColIndex, endColIndex);
    const maxCol = Math.max(startColIndex, endColIndex);

    // 選取範圍內的所有儲存格
    for (let r = minRow; r <= maxRow; r++) {
        const row = allRows[r];
        for (let c = minCol; c <= maxCol; c++) {
            const column = bulkEditColumns[c];
            if (!column.editable) continue;

            const cellId = `${row.dataset.recordId}_${column.key}`;
            const cell = document.querySelector(`td[data-cell-id="${cellId}"]`);
            if (cell) {
                cell.classList.add('selecting');
            }
        }
    }
}

function handleSelectDragEnd(event) {
    if (!bulkEditSelectDragState) return;

    // 如果有拖移選取，套用選取
    if (bulkEditSelectDragState.isSelecting) {
        clearCellSelection();

        // 同步更新選取狀態，立即生效
        const selectingCells = document.querySelectorAll('.bulk-edit-grid td.selecting');

        selectingCells.forEach(cell => {
            const cellId = cell.dataset.cellId;
            bulkEditSelectedCells.add(cellId);
            cell.classList.remove('selecting');
            cell.classList.add('selected');
        });
    }

    bulkEditSelectDragState = null;
}

async function saveBulkEditChanges() {
    if (bulkEditChanges.size === 0) {
        AppUtils.showError('沒有要儲存的變更');
        return;
    }

    const saveBtn = document.getElementById('saveBulkEditBtn');
    const originalText = saveBtn.innerHTML;
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>儲存中...';

    try {
        let successCount = 0;
        let errorCount = 0;
        const errors = []; // 記錄錯誤訊息

        console.log('=== 開始儲存 Bulk Edit 變更 ===');
        console.log('總共要更新', bulkEditChanges.size, '筆資料');

        for (const [recordId, changes] of bulkEditChanges) {
            try {
                console.log('\n--- 處理 recordId:', recordId, '---');

                // 找到原始測試案例
                const originalTestCase = testCases.find(tc => tc.record_id === recordId);
                if (!originalTestCase) {
                    const errMsg = `找不到 record_id: ${recordId}`;
                    console.error(errMsg);
                    errors.push(errMsg);
                    errorCount++;
                    continue;
                }

                console.log('=== 準備更新 recordId:', recordId, '===');
                console.log('changes:', changes);

                // 只發送實際變更的欄位，不發送完整的 test case 物件
                // 這樣可以避免不必要的欄位被誤更新
                const updateData = {};

                // API 支援的可更新欄位
                // 注意：bulk edit 不包含 TCG 欄位，所以不應發送 TCG 更新
                const updateableFields = [
                    'test_case_number',
                    'title',
                    'priority',
                    'precondition',
                    'steps',
                    'expected_result',
                    'test_result',
                    // 'tcg', // 不包含 TCG，bulk edit 不編輯此欄位
                    'assignee',
                    'attachments',
                    'user_story_map',
                    'parent_record',
                    'temp_upload_id'
                ];

                // 只加入實際變更的欄位
                for (const [key, value] of Object.entries(changes)) {
                    if (updateableFields.includes(key)) {
                        updateData[key] = value;
                    }
                }

                console.log('updateData:', updateData);

                // 呼叫 API 更新
                const currentTeam = AppUtils.getCurrentTeam();
                if (!currentTeam) {
                    throw new Error('請先選擇團隊');
                }

                console.log('Request body:', JSON.stringify(updateData, null, 2));

                const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${recordId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(updateData)
                });

                console.log('API Response status:', response.status);

                if (!response.ok) {
                    // 讀取錯誤詳情
                    let errorDetail = '';
                    try {
                        const errorData = await response.json();
                        errorDetail = JSON.stringify(errorData, null, 2);
                        console.error('API 錯誤詳情:', errorDetail);
                    } catch (e) {
                        errorDetail = await response.text();
                        console.error('API 錯誤文本:', errorDetail);
                    }
                    throw new Error(`HTTP ${response.status}: ${response.statusText}\n${errorDetail}`);
                }

                const updatedTestCase = await response.json();
                console.log('API 返回的更新後資料:', updatedTestCase);
                console.log('API 返回的 record_id:', updatedTestCase.record_id);
                console.log('原本的 recordId:', recordId);

                // 更新本地資料：使用原本的 recordId 查找
                const index = testCases.findIndex(tc => tc.record_id === recordId);
                if (index >= 0) {
                    // 保留原本的 record_id，但更新其他欄位
                    const originalRecordId = testCases[index].record_id;
                    testCases[index] = { ...updatedTestCase, record_id: originalRecordId };
                    console.log('✅ 已更新 testCases 索引:', index);
                } else {
                    console.warn('⚠️ 在 testCases 中找不到 recordId:', recordId);
                }

                const filteredIndex = filteredTestCases.findIndex(tc => tc.record_id === recordId);
                if (filteredIndex >= 0) {
                    const originalRecordId = filteredTestCases[filteredIndex].record_id;
                    filteredTestCases[filteredIndex] = { ...updatedTestCase, record_id: originalRecordId };
                    console.log('✅ 已更新 filteredTestCases 索引:', filteredIndex);
                }

                // 更新快取：使用 test_case_number 作為關鍵字
                if (updatedTestCase.test_case_number) {
                    updateTestCaseInCache(updatedTestCase);
                    console.log('✅ 已更新快取:', updatedTestCase.test_case_number);
                }

                console.log('✅ 成功更新 recordId:', recordId);
                successCount++;

            } catch (error) {
                const errMsg = `更新 ${recordId} 失敗: ${error.message}`;
                console.error(errMsg, error);
                errors.push(errMsg);
                errorCount++;
            }
        }

        console.log('=== 儲存完成 ===');
        console.log('成功:', successCount, '筆');
        console.log('失敗:', errorCount, '筆');

        // 顯示結果
        if (successCount > 0) {
            let message = `儲存成功 ${successCount} 筆`;
            if (errorCount > 0) {
                message += `，失敗 ${errorCount} 筆`;
                console.warn('失敗詳情:', errors);
            }
            AppUtils.showSuccess(message);

            // 清除變更記錄
            bulkEditChanges.clear();

            // 清空 undo 堆疊（因為已經儲存）
            bulkEditUndoStack = [];

            // 更新狀態
            updateBulkEditStatus();

            // 禁用 undo 按鈕
            const undoBtn = document.getElementById('bulkEditUndoBtn');
            if (undoBtn) undoBtn.disabled = true;

            // 刷新表格顯示
            renderTestCasesTable();

            // 不關閉 modal，讓用戶繼續編輯
        } else {
            const errorMsg = '儲存失敗：' + (errors.length > 0 ? '\n' + errors.join('\n') : '所有資料都更新失敗');
            console.error(errorMsg);
            AppUtils.showError(errorMsg);
        }

    } catch (error) {
        console.error('saveBulkEditChanges error:', error);
        AppUtils.showError('儲存失敗: ' + error.message);
    } finally {
        saveBtn.disabled = false;
        saveBtn.innerHTML = originalText;
    }
}
