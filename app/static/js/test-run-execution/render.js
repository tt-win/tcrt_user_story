/* Test Run Execution - Render */

let itemDetailModal = null;
let confirmModal = null;
let restartModal = null;
let batchModifyModal = null;
let selectedItems = new Set(); // 追踪選中的測試執行項目
// Shift 連續多選的錨點索引
let lastItemCheckboxIndex = null;
let testCaseDetailModalInstance = null;
let currentDetailTestCase = null; // 目前顯示於執行頁 Modal 的 Test Case，用於鍵盤導航
let __tcOpenedFromUrl = false;
function updateHeader() {
    if (!testRunConfig) return;

    // 更新頁面副標題 - 使用 i18n 翻譯
    const subtitleText = window.i18n ?
        window.i18n.t('testRun.currentExecutionWithName', { name: testRunConfig.name }, `現在執行：${testRunConfig.name}`) :
        `現在執行：${testRunConfig.name}`;
    document.getElementById('test-run-subtitle').textContent = subtitleText;
    
    // 顯示對應的控制按鈕
    updateControlButtons(testRunConfig.status);
    
    // 顯示頁面內容
    document.getElementById('test-run-header').style.display = 'block';
    const itemsContainer = document.getElementById('test-run-items-container');
    if (itemsContainer) {
        itemsContainer.style.display = '';
    }
}

function updateControlButtons(status) {
    const permissions = getTrePermissions();
    // 隱藏所有按鈕
    const startBtn = document.getElementById('startBtn');
    const completeBtn = document.getElementById('completeBtn');
    const restartBtn = document.getElementById('restartBtn');

    if (startBtn) startBtn.style.display = 'none';
    if (completeBtn) completeBtn.style.display = 'none';
    if (restartBtn) restartBtn.style.display = 'none';
    
    // 根據狀態顯示對應按鈕
    switch (status) {
        case 'draft':
            if (startBtn && permissions.canStart) {
                startBtn.style.display = 'inline-block';
            }
            break;
        case 'active':
            if (completeBtn && permissions.canComplete) {
                completeBtn.style.display = 'inline-block';
            }
            break;
        case 'completed':
            if (restartBtn && permissions.canRestart) {
                restartBtn.style.display = 'inline-block';
            }
            break;
    }
    
    // 更新批量修改按鈕狀態
    const batchModifyBtn = document.getElementById('batchModifyBtn');
    if (batchModifyBtn) {
        const allowModify = permissions.canBatchModify && status !== 'completed';
        if (!allowModify) {
            batchModifyBtn.disabled = true;
            batchModifyBtn.classList.add('disabled');
            batchModifyBtn.title = window.i18n && window.i18n.isReady() 
                ? window.i18n.t('testRun.cannotEditCompleted')
                : '已完成的 Test Run 不可編輯 Test Case';
        } else {
            batchModifyBtn.disabled = false;
            batchModifyBtn.classList.remove('disabled');
            batchModifyBtn.removeAttribute('title');
        }
    }

    const batchDeleteBtn = document.getElementById('batchDeleteBtn');
    if (batchDeleteBtn) {
        const allowDelete = permissions.canBatchDelete && status !== 'completed';
        batchDeleteBtn.disabled = !allowDelete;
        if (!allowDelete) {
            batchDeleteBtn.classList.add('disabled');
        } else {
            batchDeleteBtn.classList.remove('disabled');
        }
    }
}

function renderTestRunItems() {
    const tbody = document.getElementById('items-table-body');
    const permissions = getTrePermissions();
    const canUpdate = permissions.canUpdateResults && testRunConfig && testRunConfig.status === 'active';

    // 更新表格標頭顯示
    updateTableHeader();
    // 依排序設定排序並更新指示
    sortTestRunItems();
    updateTreSortIndicators();

    const filteredItems = getFilteredTestRunItems();
    updateExecutionFilterSummary(filteredItems.length, testRunItems.length);

    const showCheckbox = shouldShowCheckbox(testRunConfig ? testRunConfig.status : 'draft');

    // 依 Section 分組
    const sectionMap = new Map();
    const sectionNameById = new Map();
    const sectionOrder = [];

    filteredItems.forEach(item => {
        const sidRaw = getItemSectionId(item);
        const sid = sidRaw ? String(sidRaw) : 'unassigned';
        if (!sectionMap.has(sid)) sectionMap.set(sid, []);
        sectionMap.get(sid).push(item);
        // Populate sectionNameById from item's section info if available
        if (sid !== 'unassigned' && item.test_case_section && item.test_case_section.name) {
            sectionNameById.set(sid, item.test_case_section.name);
        } else if (sid === 'unassigned') {
            sectionNameById.set('unassigned', window.i18n && window.i18n.isReady() ? (window.i18n.t('testRun.unassigned.label') || window.i18n.t('testRun.unassigned')) : 'Unassigned');
        }
    });

    const finalSectionOrder = [];
    const explicitUnassignedIds = []; // 儲存名稱為 "Unassigned" 的實體 Section ID

    // 1. 從 treSections (已排序的樹狀結構) 收集 Section ID
    function collectOrderedSectionsFromTree(sections) {
        (sections || []).forEach(sec => {
            const sid = String(sec.id);
            const isUnassignedByName = (sec.name || '').trim().toLowerCase() === 'unassigned';
            
            // Populate sectionNameById (important for display)
            sectionNameById.set(sid, sec.name || `Section ${sid}`);

            if (sectionMap.has(sid) && sectionMap.get(sid).length > 0) {
                if (isUnassignedByName) {
                    explicitUnassignedIds.push(sid);
                } else {
                    finalSectionOrder.push(sid);
                }
            }
            
            if (sec.children && sec.children.length) collectOrderedSectionsFromTree(sec.children);
        });
    }
    collectOrderedSectionsFromTree(treSections || []);

    // 2. 找出 sectionMap 中有但 finalSectionOrder + explicitUnassignedIds 中沒有的 section (孤立 Section)
    const knownSections = new Set([...finalSectionOrder, ...explicitUnassignedIds]);
    const orphanSections = [];
    sectionMap.forEach((_, sid) => {
        if (sid !== 'unassigned' && !knownSections.has(sid)) {
            orphanSections.push(sid);
        }
    });
    
    // 對孤立 Section 排序，並檢查名稱是否為 Unassigned
    orphanSections.sort((a, b) => {
        return a.localeCompare(b);
    });
    
    // 將孤立 Section 分流 (一般 vs Unassigned)
    orphanSections.forEach(sid => {
        const name = (sectionNameById.get(sid) || '').toLowerCase();
        if (name === 'unassigned') {
            explicitUnassignedIds.push(sid);
        } else {
            finalSectionOrder.push(sid);
        }
    });

    // 3. 將 "Unassigned" 實體 Section 放到列表後方
    finalSectionOrder.push(...explicitUnassignedIds);

    // 4. 確保 Virtual Unassigned (null ID) 永遠在最後
    if (sectionMap.has('unassigned') && sectionMap.get('unassigned').length > 0) {
        finalSectionOrder.push('unassigned');
    }

    // 將最終排序應用到 sectionOrder
    sectionOrder.push(...finalSectionOrder);

    const rows = [];
    sectionOrder.forEach(sid => {
        const items = sectionMap.get(sid) || [];
        if (!items.length) return;
        
        const displayName = getSectionDisplayName(sid, treSections);
        
        const collapsed = sessionStorage.getItem(`tre-section-${sid}`) === 'collapsed';
        const caret = collapsed ? 'fa-chevron-right' : 'fa-chevron-down';
        const colspan = showCheckbox ? 7 : 6;
        rows.push(`
            <tr class="tre-section-row" data-section-id="${sid}">
                <td colspan="${colspan}">
                    <div class="d-flex align-items-center gap-2">
                        <i class="fas ${caret} section-toggle" data-section-id="${sid}"></i>
                        <span>${escapeHtml(displayName)}</span>
                        <span class="badge bg-light text-muted">${items.length}</span>
                    </div>
                </td>
            </tr>
        `);
        items.forEach((item, idx) => {
            const rowHtml = createItemRow(item, idx + 1, canUpdate);
            const wrapped = collapsed ? rowHtml.replace('<tr ', '<tr style="display:none" ') : rowHtml;
            rows.push(wrapped.replace('<tr ', `<tr data-section-id="${sid}" `));
        });
    });

    if (!rows.length) {
        const colspan = showCheckbox ? 7 : 6;
        tbody.innerHTML = `
            <tr class="no-items">
                <td colspan="${colspan}" class="text-center text-muted py-4" data-i18n="testRun.noItemsAfterFilter">
                    目前沒有符合篩選條件的項目
                </td>
            </tr>
        `;
        if (window.i18n && window.i18n.isReady()) window.i18n.retranslate(tbody);
        updateItemSelectionUI();
        hideItemsLoading();
        return;
    }

    tbody.innerHTML = rows.join('');
    
    // 重新應用翻譯到新生成的內容
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(tbody);
    }
    
    // 綁定事件處理器
    bindItemEventHandlers(canUpdate);
    // Section 展開/收合事件
    tbody.querySelectorAll('.section-toggle').forEach(icon => {
        icon.addEventListener('click', () => {
            const sid = icon.getAttribute('data-section-id');
            const key = `tre-section-${sid}`;
            const collapsed = sessionStorage.getItem(key) === 'collapsed';
            if (collapsed) sessionStorage.removeItem(key); else sessionStorage.setItem(key, 'collapsed');
            renderTestRunItems();
        });
    });
    updateItemSelectionUI();

    // 嘗試處理從 URL 帶入的 tc（只執行一次）
    tryOpenTcFromUrlOnce();

    // 確保載入動畫關閉，顯示列表
    hideItemsLoading();
}

function tryOpenTcFromUrlOnce() {
    if (__tcOpenedFromUrl) return;
    const tc = window.__PENDING_TC_FROM_URL__;
    if (!tc) { __tcOpenedFromUrl = true; return; }
    if (!Array.isArray(testRunItems) || testRunItems.length === 0) return;
    const exists = testRunItems.some(i => i && i.test_case_number === tc);
    if (exists) {
        __tcOpenedFromUrl = true;
        showTestCaseDetailModal(tc);
    } else {
        // 一次性嘗試即可，避免影響後續流程
        __tcOpenedFromUrl = true;
        console.warn('tc from URL not found in current testRunItems:', tc);
    }
}
// 初始化表頭排序點擊事件（一次性）
(function initTreHeaderSorting(){
  const bind = (id, field) => {
    const el = document.getElementById(id);
    if (el && !el._sortBound) {
      el.addEventListener('click', () => setTreSort(field));
      el._sortBound = true;
    }
  };
  bind('th-tre-number', 'number');
  bind('th-tre-title', 'title');
  bind('th-tre-priority', 'priority');
  bind('th-tre-result', 'result');
  bind('th-tre-assignee', 'assignee');
  bind('th-tre-executed', 'executed');
})();

// 列表區載入動畫控制（顯示空框 + spinner）
function showItemsLoading() {
    try {
        const container = document.getElementById('test-run-items-container');
        const loading = document.getElementById('items-loading');
        const tableWrap = container.querySelector('.test-run-items-table');
        if (container) container.style.display = '';
        if (loading) {
            loading.classList.remove('d-none');
            loading.classList.add('d-flex');
            loading.style.display = '';
        }
        if (tableWrap) tableWrap.style.display = 'none';
        const tbody = document.getElementById('items-table-body');
        if (tbody) tbody.innerHTML = '';
    } catch (_) {}
}

function hideItemsLoading() {
    try {
        const container = document.getElementById('test-run-items-container');
        const loading = document.getElementById('items-loading');
        const tableWrap = container.querySelector('.test-run-items-table');
        if (loading) {
            loading.classList.remove('d-flex');
            loading.classList.add('d-none');
            loading.style.display = '';
        }
        if (tableWrap) tableWrap.style.display = 'block';
    } catch (_) {}
}

function shouldShowCheckbox(status) {
    const permissions = getTrePermissions();
    if (!(permissions.canBatchModify || permissions.canBatchDelete)) {
        return false;
    }
    return status === 'draft' || status === 'active';
}

function updateTableHeader() {
    const table = document.querySelector('.test-run-items-table');
    const checkboxHeader = document.getElementById('checkbox-header');
    const showCheckbox = shouldShowCheckbox(testRunConfig ? testRunConfig.status : 'draft');

    if (showCheckbox) {
        table.classList.remove('hide-checkbox');
        if (checkboxHeader) {
            checkboxHeader.style.display = '';
            checkboxHeader.style.visibility = '';
            checkboxHeader.style.width = '';
            checkboxHeader.style.padding = '';
        }
    } else {
        table.classList.add('hide-checkbox');
        if (checkboxHeader) {
            // Completely hide the column while maintaining table structure
            checkboxHeader.style.width = '0';
            checkboxHeader.style.padding = '0';
            checkboxHeader.style.minWidth = '0';
            checkboxHeader.style.maxWidth = '0';
            checkboxHeader.style.visibility = 'collapse';
        }
        // 清空選擇狀態
        selectedItems.clear();
        updateItemSelectionUI();
    }
}
function createItemRow(item, index, canUpdate) {
    const permissions = getTrePermissions();
    const resultClass = getResultClass(item.test_result);
    const resultText = getResultText(item.test_result);
    const executedAt = item.executed_at ? AppUtils.formatDate(item.executed_at, 'datetime') : '-';
    const assigneeName = (item.assignee_name || (item.assignee && item.assignee.name)) || '-';
    const canEditAssignee = permissions.canAssign && testRunConfig && testRunConfig.status !== 'completed' && testRunConfig.status !== 'archived';
    const showCheckbox = shouldShowCheckbox(testRunConfig ? testRunConfig.status : 'draft');
    const hasExecutionHistory = item.executed_at !== null && item.executed_at !== undefined;
    const isDeleted = !!item.__testCaseDeleted;
    const deletedBadge = `<span class="badge bg-danger-subtle text-danger ms-2">已刪除</span>`;

    const safeTitle = escapeHtml(item.title || '');
    const titleCellContent = isDeleted
        ? `<span class="text-muted" title="${safeTitle || '測試案例已刪除'}">${safeTitle || '測試案例已刪除'}</span>${deletedBadge}`
        : `<a href="#" class="text-decoration-none" onclick="navigateToTestCase('${item.test_case_number}'); return false;">${safeTitle}</a>`;

    const priorityLabel = isDeleted ? '-' : (item.priority || 'Medium');
    const priorityBadgeClass = isDeleted ? 'badge bg-secondary-subtle text-muted priority-badge-lg border border-secondary-subtle' : 'badge bg-secondary priority-badge-lg';

    return `
        <tr data-item-id="${item.id}">
            <td class="checkbox-cell">
                <input type="checkbox" class="form-check-input test-run-item-checkbox" value="${item.id}">
            </td>
            <td><code style="color: rgb(194, 54, 120); font-weight: 500;"><a href="#" class="text-decoration-none" style="color: rgb(194, 54, 120);" onclick="navigateToTestCase('${item.test_case_number}'); return false;">${escapeHtml(item.test_case_number)}</a></code></td>
            <td class="text-truncate" title="${safeTitle || (isDeleted ? '測試案例已刪除' : '')}">${titleCellContent}</td>
            <td><span class="${priorityBadgeClass}">${escapeHtml(priorityLabel)}</span></td>
            <td>
                ${canUpdate ? `
                    <select class="form-select result-selector-lg ${resultClass}"
                            data-item-id="${item.id}" onchange="updateTestResult(${item.id}, this.value)">
                        ${!hasExecutionHistory ? `<option value="">${escapeHtml(treTranslate('testRun.notExecuted', 'Not Executed'))}</option>` : ''}
                        <option value="Passed" ${item.test_result === 'Passed' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.passed', 'Passed'))}</option>
                        <option value="Failed" ${item.test_result === 'Failed' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.failed', 'Failed'))}</option>
                        <option value="Retest" ${item.test_result === 'Retest' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.retest', 'Retest'))}</option>
                        <option value="Not Available" ${item.test_result === 'Not Available' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.notAvailable', 'Not Available'))}</option>
                        <option value="Pending" ${item.test_result === 'Pending' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.pending', 'Pending'))}</option>
                        <option value="Not Required" ${item.test_result === 'Not Required' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.notRequired', 'Not Required'))}</option>
                        <option value="Skip" ${item.test_result === 'Skip' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.skip', 'Skip'))}</option>
                    </select>
                ` : `
                    <span class="badge result-badge-lg ${resultClass}">${resultText}</span>
                `}
            </td>
            <td>
                ${canEditAssignee ? `
                    <input type="text" class="form-control form-control-sm assignee-editor"
                           value="${escapeHtml(assigneeName === '-' ? '' : assigneeName)}"
                           data-item-id="${item.id}"
                           data-assignee-selector
                           data-i18n-placeholder="testRun.enterAssigneeName"
                           placeholder="${treTranslate('testRun.enterAssigneeName', '輸入執行者姓名')}"
                           onblur="updateAssignee(${item.id}, this.value)">
                ` : `
                    ${assigneeName}
                `}
            </td>
            <td class="small text-muted">${executedAt}</td>
        </tr>
    `;
}

function bindItemEventHandlers(canUpdate) {
    const permissions = getTrePermissions();

    if (canUpdate && permissions.canUpdateResults) {
        document.querySelectorAll('.result-selector, .result-selector-lg').forEach(select => {
            select.addEventListener('change', function() {
                updateSelectClass(this);
            });
            updateSelectClass(select);
        });
    }

    if (permissions.canAssign && window.initAssigneeSelectors && currentTeamId) {
        document.querySelectorAll('.assignee-editor[data-assignee-selector]').forEach(input => {
            if (input._assigneeSelector) {
                input._assigneeSelector.destroy();
            }
        });

        document.querySelectorAll('.assignee-editor[data-assignee-selector]').forEach(input => {
            const itemId = parseInt(input.dataset.itemId);

            if (input._assigneeSelector) {
                input._assigneeSelector.destroy();
            }

            const options = {
                teamId: currentTeamId,
                allowCustomValue: true,
                onSelect: (contact) => {
                    updateAssignee(itemId, contact.name);
                },
                onClear: () => {
                    updateAssignee(itemId, '');
                }
            };

            input._assigneeSelector = new AssigneeSelector(input, options);
        });
    }
}

function updateSelectClass(select) {
    const value = select.value;
    const hasSm = select.classList.contains('form-select-sm');
    const sizeClass = hasSm ? 'form-select-sm ' : '';
    select.className = `form-select ${sizeClass}result-selector-lg ${getResultClass(value)}`;
}

async function updateTestResult(itemId, result) {
    if (!getTrePermissions().canUpdateResults) {
        showExecutionPermissionDenied();
        return;
    }
    try {
        const executedAt = result ? new Date().toISOString() : null;
        
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/${itemId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                test_result: result || null,
                executed_at: executedAt
            })
        });
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        // 更新本地資料
        const itemIndex = testRunItems.findIndex(item => item.id === itemId);
        if (itemIndex !== -1) {
            testRunItems[itemIndex].test_result = result || null;
            testRunItems[itemIndex].executed_at = executedAt;
        }
        
        // 更新統計
        await updateStatistics();

        // 重新渲染列表頁以反映更新
        renderTestRunItems();

        // 若詳情 Modal 開啟中且為同一測試案例，刷新右側 timeline 和標題區域
        try {
            const modalEl = document.getElementById('testCaseDetailModal');
            const isShown = modalEl && modalEl.classList.contains('show');
            const item = testRunItems.find(i => i.id === itemId);
            if (isShown && item && currentDetailTestCase && currentDetailTestCase.test_case_number === item.test_case_number) {
                // 刷新標題區域的 Test Result 顯示
                renderModalHeaderResult(currentDetailTestCase);
                // 刷新右側 timeline
                renderResultHistoryTimeline({ test_case_number: item.test_case_number });
            }
        } catch (_) {}
        
    } catch (error) {
        console.error('Failed to update test result:', error);
        AppUtils.showError(`${treTranslate('testRun.updateFailed', '更新失敗')}: ${error.message}`);
        // 重新載入項目以恢復狀態
        await loadTestRunItems();
    }
}

function showItemDetail(itemId) {
    const item = testRunItems.find(i => i.id === itemId);
    if (!item) return;
    
    const basicInfoLabel = treTranslate('testRun.basicInfo', '基本資訊');
    const executionInfoLabel = treTranslate('testRun.executionInfo', '執行資訊');
    const testCaseNumberLabel = treTranslate('testRun.testCaseNumber', '測試案例編號');
    const titleLabel = treTranslate('common.title', '標題');
    const priorityLabel = treTranslate('testRun.priority', '優先級');
    const testResultLabel = treTranslate('testRun.testResult', '測試結果');
    const executorLabel = treTranslate('testRun.executor', '執行者');
    const executionTimeLabel = treTranslate('testRun.executionTime', '執行時間');
    const executionDurationLabel = treTranslate('testRun.executionDuration', '執行時長');
    const attachmentCountLabel = treTranslate('testRun.attachmentCount', '附件數量');
    const preconditionsLabel = treTranslate('testRun.preconditions', '前置條件');
    const testStepsLabel = treTranslate('testRun.testSteps', '測試步驟');
    const expectedResultsLabel = treTranslate('testRun.expectedResults', '預期結果');
    const minutesLabel = treTranslate('testRun.minutes', '分鐘');
    const isDeleted = !!item.__testCaseDeleted;
    const titleValue = escapeHtml(item.title || (isDeleted ? '測試案例已刪除' : ''));
    const priorityValue = isDeleted ? '-' : (item.priority || 'Medium');
    const deletedNote = isDeleted ? `<span class="badge bg-danger-subtle text-danger ms-2">已刪除</span>` : '';
    
    const content = `
        <div class="row">
            <div class="col-md-6">
                <h6>${basicInfoLabel}</h6>
                <table class="table table-sm">
                    <tr><td>${testCaseNumberLabel}</td><td><code style="color: rgb(194, 54, 120); font-weight: 500;">${escapeHtml(item.test_case_number)}</code></td></tr>
                    <tr><td>${titleLabel}</td><td><span class="${isDeleted ? 'text-muted' : ''}">${titleValue || '-'}</span>${deletedNote}</td></tr>
                    <tr><td>${priorityLabel}</td><td>${escapeHtml(priorityValue)}</td></tr>
                    <tr><td>${testResultLabel}</td><td><span class="badge ${getResultClass(item.test_result)}">${getResultText(item.test_result)}</span></td></tr>
                </table>
            </div>
            <div class="col-md-6">
                <h6>${executionInfoLabel}</h6>
                <table class="table table-sm">
                    <tr><td>${executorLabel}</td><td>${escapeHtml(item.assignee_name || '-')}</td></tr>
                    <tr><td>${executionTimeLabel}</td><td>${item.executed_at ? AppUtils.formatDate(item.executed_at, 'datetime') : '-'}</td></tr>
                    <tr><td>${executionDurationLabel}</td><td>${item.execution_duration ? item.execution_duration + ' ' + minutesLabel : '-'}</td></tr>
                    <tr><td>${attachmentCountLabel}</td><td>${item.attachment_count || 0}</td></tr>
                </table>
            </div>
        </div>
        ${!isDeleted && item.precondition ? `<div class="mt-3"><h6>${preconditionsLabel}</h6><p class="text-muted">${escapeHtml(item.precondition)}</p></div>` : ''}
        ${!isDeleted && item.steps ? `<div class="mt-3"><h6>${testStepsLabel}</h6><p class="text-muted">${escapeHtml(item.steps).replace(/\n/g, '<br>')}</p></div>` : ''}
        ${!isDeleted && item.expected_result ? `<div class="mt-3"><h6>${expectedResultsLabel}</h6><p class="text-muted">${escapeHtml(item.expected_result)}</p></div>` : ''}
    `;
    
    document.getElementById('item-detail-content').innerHTML = content;
    itemDetailModal.show();
}

function confirmStatusChange(newStatus, message) {
    const permissions = getTrePermissions();
    if ((newStatus === 'active' && !permissions.canStart) || (newStatus === 'completed' && !permissions.canComplete)) {
        showExecutionPermissionDenied();
        return;
    }
    document.getElementById('confirm-message').textContent = message;
    const confirmBtn = document.getElementById('confirm-action-btn');
    
    confirmBtn.onclick = async () => {
        try {
            await changeTestRunStatus(newStatus);
            confirmModal.hide();
        } catch (error) {
            AppUtils.showError(`${treTranslate('testRun.statusChangeFailed', '狀態變更失敗')}: ${error.message}`);
        }
    };
    
    confirmModal.show();
}

async function changeTestRunStatus(newStatus) {
    const permissions = getTrePermissions();
    if ((newStatus === 'active' && !permissions.canStart) || (newStatus === 'completed' && !permissions.canComplete)) {
        showExecutionPermissionDenied();
        throw new Error('permission_denied');
    }
    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        testRunConfig.status = newStatus;
        updateHeader();
        
        // 重新渲染項目以更新 checkbox 顯示和編輯權限
        renderTestRunItems();
        
        const statusMsg = {
            'active': treTranslate('testRun.executionStarted', '已開始執行'),
            'completed': treTranslate('testRun.executionCompleted', '已結束執行')
        };
        
        AppUtils.showSuccess(statusMsg[newStatus] || treTranslate('testRun.statusUpdated', '狀態已更新'));
        
    } catch (error) {
        console.error('Failed to change status:', error);
        throw error;
    }
}

function showRestartModal() {
    if (!getTrePermissions().canRestart) {
        showExecutionPermissionDenied();
        return;
    }
    if (!testRunConfig || testRunConfig.status !== 'completed') {
        AppUtils.showWarning(treTranslate('testRun.onlyCompletedCanRestart', '只有已完成的 Test Run 才能重新執行'));
        return;
    }
    
    // 重置選項為默認值
    document.getElementById('restartAll').checked = true;
    // 預設名稱：Rerun - 原有名稱
    const input = document.getElementById('rerunNameInput');
    if (input) {
        const base = (testRunConfig && testRunConfig.name) ? `Rerun - ${testRunConfig.name}` : 'Rerun -';
        input.value = base;
    }
    restartModal.show();
}

async function handleRestartConfirm() {
    if (!getTrePermissions().canRestart) {
        showExecutionPermissionDenied();
        return;
    }
    const selectedMode = document.querySelector('input[name="restartMode"]:checked');
    if (!selectedMode) {
        AppUtils.showWarning(treTranslate('testRun.selectRestartMode', '請選擇重新執行模式'));
        return;
    }
    
    try {
        await restartTestRun(selectedMode.value);
        restartModal.hide();
        
    } catch (error) {
        AppUtils.showError(`${treTranslate('testRun.restartFailed', '重新執行失敗')}: ${error.message}`);
    }
}

async function restartTestRun(mode) {
    if (!getTrePermissions().canRestart) {
        showExecutionPermissionDenied();
        throw new Error('permission_denied');
    }
    try {
        // 調用重新執行 API
        const nameInput = document.getElementById('rerunNameInput');
        const newName = nameInput && nameInput.value ? nameInput.value.trim() : '';
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/restart`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: mode, name: newName })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const result = await response.json();
        const newId = result && result.new_config_id;
        if (!newId) throw new Error('Missing new_config_id');
        AppUtils.showSuccess(treTranslate('testRun.rerunCreated', '已建立新的 Test Run'));
        window.location.href = `/test-run-execution?config_id=${encodeURIComponent(newId)}`;
        
    } catch (error) {
        const consoleMsg = window.i18n && window.i18n.isReady() 
            ? window.i18n.t('testRun.restartFailed')
            : '重新執行 Test Run 失敗';
        console.error(consoleMsg + ':', error);
        throw error;
    }
}

// 全頁載入已移除，使用列表區載入動畫（showItemsLoading/hideItemsLoading）

function toggleSelectAllItems() {
    if (!(getTrePermissions().canBatchModify || getTrePermissions().canBatchDelete)) {
        const selectAll = document.getElementById('selectAllItemsCheckbox');
        if (selectAll) selectAll.checked = false;
        showExecutionPermissionDenied();
        updateItemSelectionUI();
        return;
    }
    const selectAll = document.getElementById('selectAllItemsCheckbox').checked;
    const checkboxes = document.querySelectorAll('.test-run-item-checkbox');
    
    checkboxes.forEach(checkbox => {
        checkbox.checked = selectAll;
        const itemId = parseInt(checkbox.value);
        if (selectAll) {
            selectedItems.add(itemId);
        } else {
            selectedItems.delete(itemId);
        }
    });
    
    updateItemSelectionUI();
    // 重置 Shift 多選錨點
    lastItemCheckboxIndex = null;
}

function clearSelectedItems() {
    try {
        document.querySelectorAll('.test-run-item-checkbox').forEach(cb => cb.checked = false);
    } catch (_) {}
    const header = document.getElementById('selectAllItemsCheckbox');
    if (header) header.checked = false;
    selectedItems.clear();
    updateItemSelectionUI();
    lastItemCheckboxIndex = null;
}

function updateItemSelectionUI() {
    const totalCheckboxes = document.querySelectorAll('.test-run-item-checkbox').length;
    const selectedCount = selectedItems.size;
    const selectAllCheckbox = document.getElementById('selectAllItemsCheckbox');
    const toolbar = document.getElementById('batchOperationsToolbar');
    const countDisplay = document.getElementById('selectedItemsCount');

    if (!toolbar) {
        return;
    }

    const applyToolbarVisibility = (visible) => {
        if (visible) {
            toolbar.classList.remove('d-none');
            const defaultDisplay = toolbar.dataset.defaultDisplay || 'flex';
            toolbar.style.setProperty('display', defaultDisplay, 'important');
        } else {
            toolbar.classList.add('d-none');
            toolbar.style.setProperty('display', 'none', 'important');
        }
    };
    
    // 如果不顯示 checkbox，隱藏工具列
    if (!shouldShowCheckbox(testRunConfig ? testRunConfig.status : 'draft')) {
        applyToolbarVisibility(false);
        return;
    }
    
    // 更新全選 checkbox 狀態
    if (selectAllCheckbox) {
        if (selectedCount === 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
            applyToolbarVisibility(false);
        } else if (selectedCount === totalCheckboxes) {
            selectAllCheckbox.checked = true;
            selectAllCheckbox.indeterminate = false;
            applyToolbarVisibility(true);
        } else {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = true;
            applyToolbarVisibility(true);
        }
    } else {
        applyToolbarVisibility(selectedCount > 0);
    }
    
    // 更新選中項目計數
    if (countDisplay) {
        if (window.i18n && window.i18n.isReady()) {
            countDisplay.textContent = window.i18n.t('testRun.selectedItemsCount', {count: selectedCount});
        } else {
            countDisplay.textContent = `已選取 ${selectedCount} 個項目`;
        }
        countDisplay.setAttribute('data-i18n-params', JSON.stringify({count: selectedCount}));
    }
}

function getBatchAssigneePrefillValue() {
    if (!selectedItems || selectedItems.size === 0) return '';
    let resolved = null;
    selectedItems.forEach(itemId => {
        const item = (testRunItems || []).find(it => it.id === itemId);
        if (!item) return;
        const name = (item.assignee_name || (item.assignee && item.assignee.name) || '').trim();
        if (!name) {
            resolved = '';
            return;
        }
        if (resolved === null) {
            resolved = name;
        } else if (resolved !== name) {
            resolved = '';
        }
    });
    return resolved || '';
}

function syncBatchAssigneeInput(value) {
    const input = document.getElementById('batchAssigneeInput');
    if (!input) return;
    const nextValue = value ? String(value) : '';
    if (input._assigneeSelector && typeof input._assigneeSelector.setValue === 'function') {
        input._assigneeSelector.setValue(nextValue);
    } else {
        input.value = nextValue;
    }
}

function getBatchAssigneeValue() {
    const input = document.getElementById('batchAssigneeInput');
    if (!input) return '';
    let value = (input.value || '').trim();
    if (value) return value;
    if (input._assigneeSelector && input._assigneeSelector.displayInput) {
        value = (input._assigneeSelector.displayInput.value || '').trim();
        if (value && typeof input._assigneeSelector.setValue === 'function') {
            input._assigneeSelector.setValue(value);
        }
    }
    return value;
}

function showBatchModifyModal() {
    if (!getTrePermissions().canBatchModify) {
        showExecutionPermissionDenied();
        return;
    }
    if (selectedItems.size === 0) {
        const noSelectionMsg = treTranslate('testRun.noItemsSelected', '請先選擇要修改的項目');
        AppUtils.showWarning(noSelectionMsg);
        return;
    }
    
    // 檢查 Test Run 狀態，已完成的不允許編輯
    if (testRunConfig && testRunConfig.status === 'completed') {
        const completedEditMsg = treTranslate('testRun.cannotEditCompleted', '已完成的 Test Run 不可編輯 Test Case');
        AppUtils.showWarning(completedEditMsg);
        return;
    }
    
    // 更新選中項目數量
    document.getElementById('batchModifyCount').textContent = selectedItems.size;
    
    // 根據當前狀態顯示/隱藏測試結果選項
    const canUpdateResult = testRunConfig && testRunConfig.status === 'active';
    const resultSection = document.getElementById('batchResultSection');
    
    if (canUpdateResult) {
        resultSection.style.display = 'block';
    } else {
        resultSection.style.display = 'none';
        document.getElementById('batchModifyResult').checked = false;
    }
    
    // 重置表單
    syncBatchAssigneeInput(getBatchAssigneePrefillValue());
    document.getElementById('batchResultSelect').value = '';
    document.getElementById('batchModifyAssignee').checked = true;
    document.getElementById('batchModifyResult').checked = false;
    document.getElementById('batchCommentInput').value = '';
    document.getElementById('batchModifyComment').checked = false;
    
    toggleBatchAssigneeInput();
    toggleBatchResultSelect();
    toggleBatchCommentInput();
    
    batchModifyModal.show();
}

function toggleBatchAssigneeInput() {
    const checkbox = document.getElementById('batchModifyAssignee');
    const input = document.getElementById('batchAssigneeInput');
    input.disabled = !checkbox.checked;
}

function toggleBatchResultSelect() {
    const checkbox = document.getElementById('batchModifyResult');
    const select = document.getElementById('batchResultSelect');
    select.disabled = !checkbox.checked;
}

function toggleBatchCommentInput() {
    const checkbox = document.getElementById('batchModifyComment');
    const input = document.getElementById('batchCommentInput');
    input.disabled = !checkbox.checked;
}

async function handleBatchModifyConfirm() {
    if (!getTrePermissions().canBatchModify) {
        showExecutionPermissionDenied();
        return;
    }
    try {
        const modifyAssignee = document.getElementById('batchModifyAssignee').checked;
        const modifyResult = document.getElementById('batchModifyResult').checked;
        const modifyComment = document.getElementById('batchModifyComment').checked;
        const assigneeName = getBatchAssigneeValue();
        const testResult = document.getElementById('batchResultSelect').value;
        const comment = document.getElementById('batchCommentInput').value.trim();
        
        if (!modifyAssignee && !modifyResult && !modifyComment) {
            const selectOptionMsg = treTranslate('testRun.selectAtLeastOneOption', '請至少選擇一個要修改的項目');
            AppUtils.showWarning(selectOptionMsg);
            return;
        }
        
        if (modifyAssignee && !assigneeName) {
            const enterAssigneeMsg = treTranslate('testRun.enterAssigneeName', '請輸入執行者姓名');
            AppUtils.showWarning(enterAssigneeMsg);
            return;
        }
        
        if (modifyResult && !testResult) {
            const selectResultMsg = treTranslate('testRun.selectTestResult', '請選擇測試結果');
            AppUtils.showWarning(selectResultMsg);
            return;
        }

        if (modifyComment && !comment) {
            const enterCommentMsg = treTranslate('testRun.enterComment', '請輸入註釋內容');
            AppUtils.showWarning(enterCommentMsg);
            return;
        }
        
        await batchModifyItems({ modifyAssignee, modifyResult, modifyComment, assigneeName, testResult, comment });
        batchModifyModal.hide();
        
    } catch (error) {
        const batchFailedMsg = treTranslate('testRun.batchModifyFailed', '批次修改失敗');
        AppUtils.showError(batchFailedMsg + ': ' + error.message);
    }
}

async function batchModifyItems(modifications) {
    if (!getTrePermissions().canBatchModify) {
        showExecutionPermissionDenied();
        throw new Error('permission_denied');
    }
    try {
        const itemsToModify = Array.from(selectedItems);

        // 為每個選中的項目建立更新資料
        const updates = itemsToModify.map(itemId => {
            const updateData = { id: itemId };

            if (modifications.modifyAssignee) {
                updateData.assignee_name = modifications.assigneeName || null;
            }

            if (modifications.modifyResult) {
                updateData.test_result = modifications.testResult;
                updateData.executed_at = new Date().toISOString();
            }

            if (modifications.modifyComment) {
                updateData.comment = modifications.comment;
            }

            return updateData;
        });

        // 批次修改 API 調用（使用正確的端點）
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/batch-update-results`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                updates: updates
            })
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(`HTTP ${response.status}: ${errorData.detail || 'Unknown error'}`);
        }

        // 解析API響應
        const result = await response.json();

        // 樂觀更新本地列表（避免等待重載也能即時看到變更）
        try {
            updates.forEach(u => {
                const id = u.id;
                const idx = testRunItems.findIndex(it => it.id === id);
                if (idx !== -1) {
                    if ('assignee_name' in u) {
                        testRunItems[idx].assignee_name = (u.assignee_name || null);
                    }
                    if ('test_result' in u) {
                        testRunItems[idx].test_result = (u.test_result || null);
                        testRunItems[idx].executed_at = u.executed_at || new Date().toISOString();
                    }
                }
            });
            renderTestRunItems();
        } catch (_) {}

        // 再從伺服器重載一次，確保資料正確
        await loadTestRunItems();
        await updateStatistics();

        // 若詳情 Modal 開啟中則刷新 timeline（以目前顯示的 test case）
        try {
            const modalEl = document.getElementById('testCaseDetailModal');
            const isShown = modalEl && modalEl.classList.contains('show');
            if (isShown && currentDetailTestCase && currentDetailTestCase.test_case_number) {
                renderResultHistoryTimeline({ test_case_number: currentDetailTestCase.test_case_number });
                const detailItem = testRunItems.find(it => it.test_case_number === currentDetailTestCase.test_case_number);
                if (detailItem && detailItem.id) {
                    loadComment(detailItem.id);
                }
            }
        } catch (_) {}

        // 清空選擇狀態並更新 UI
        selectedItems.clear();
        updateItemSelectionUI();

        // 顯示成功訊息，包括處理結果
        if (result.success) {
            const successMsg = window.i18n && window.i18n.isReady()
                ? window.i18n.t('testRun.batchModifySuccess', {count: result.success_count})
                : `成功修改 ${result.success_count} 個測試執行項目`;
            AppUtils.showSuccess(successMsg);
        } else {
            // 部分成功的情況
            const partialMsg = window.i18n && window.i18n.isReady()
                ? window.i18n.t('testRun.batchModifyPartial', {success: result.success_count, total: result.processed_count})
                : `已處理 ${result.processed_count} 個項目，成功 ${result.success_count} 個`;
            AppUtils.showWarning(partialMsg);

            if (result.error_messages && result.error_messages.length > 0) {
                console.warn('批次修改錯誤:', result.error_messages);
            }
        }

    } catch (error) {
        const consoleMsg = window.i18n && window.i18n.isReady()
            ? window.i18n.t('testRun.batchModifyFailed')
            : '批次修改測試執行項目失敗';
        console.error(consoleMsg + ':', error);
        throw error;
    }
}

// 顯示批次刪除確認對話框
function showBatchDeleteConfirm() {
    if (!getTrePermissions().canBatchDelete) {
        showExecutionPermissionDenied();
        return;
    }
    if (selectedItems.size === 0) {
        const noSelectionMsg = treTranslate('testRun.noItemsSelected', '請先選擇要刪除的項目');
        AppUtils.showWarning(noSelectionMsg);
        return;
    }

    const confirmMessage = window.i18n && window.i18n.isReady()
        ? window.i18n.t('testRun.batchDeleteConfirm', {count: selectedItems.size})
        : `確定要刪除選中的 ${selectedItems.size} 個測試執行項目嗎？\n\n⚠️ 警告：此操作將同時清除所有相關的測試歷程記錄，此動作無法復原！`;

    // 為批次刪除添加特殊的警告樣式
    const modalDialog = document.querySelector('#confirmModal .modal-dialog');
    const modalContent = document.querySelector('#confirmModal .modal-content');
    const modalHeader = document.querySelector('#confirmModal .modal-header');
    const confirmBtn = document.getElementById('confirm-action-btn');

    // 保存原始樣式
    const originalClasses = {
        dialog: modalDialog.className,
        content: modalContent.className,
        header: modalHeader.className,
        btn: confirmBtn.className
    };

    // 應用危險操作的樣式
    modalDialog.className = 'modal-dialog modal-dialog-centered modal-dialog-scrollable';
    modalContent.className = 'modal-content border-danger';
    modalHeader.className = 'modal-header bg-danger text-white';
    confirmBtn.className = 'btn btn-danger';

    // 更新標題圖標和文字
    const modalTitle = document.querySelector('#confirmModal .modal-title');
    modalTitle.innerHTML = `
        <i class="fas fa-exclamation-triangle me-2"></i>
        <span data-i18n="testRun.batchDeleteWarning">危險操作警告</span>
    `;

    document.getElementById('confirm-message').innerHTML = confirmMessage.replace(/\n/g, '<br>');

    // 設置確認按鈕事件
    confirmBtn.onclick = async () => {
        try {
            await batchDeleteItems();
            confirmModal.hide();
        } catch (error) {
            AppUtils.showError(`${treTranslate('testRun.batchDeleteFailed', '批次刪除失敗')}: ${error.message}`);
        }
    };

    // 當對話框隱藏時恢復原始樣式
    const modalElement = document.getElementById('confirmModal');
    modalElement.addEventListener('hidden.bs.modal', function() {
        modalDialog.className = originalClasses.dialog;
        modalContent.className = originalClasses.content;
        modalHeader.className = originalClasses.header;
        confirmBtn.className = originalClasses.btn;
        modalTitle.innerHTML = `
            <i class="fas fa-exclamation-triangle text-warning me-2"></i>
            <span data-i18n="common.confirm">確認操作</span>
        `;
    }, { once: true });

    confirmModal.show();
}

// 批次刪除測試執行項目
async function batchDeleteItems() {
    if (!getTrePermissions().canBatchDelete) {
        showExecutionPermissionDenied();
        throw new Error('permission_denied');
    }
    try {
        const itemsToDelete = Array.from(selectedItems);
        let successCount = 0;
        let errorMessages = [];

        // 逐個刪除項目（因為可能沒有批次刪除 API）
        for (const itemId of itemsToDelete) {
            try {
                const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/${itemId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    successCount++;
                    // 從本地列表中移除已刪除的項目
                    const idx = testRunItems.findIndex(it => it.id === itemId);
                    if (idx !== -1) {
                        testRunItems.splice(idx, 1);
                    }
                } else {
                    let errorMessage = 'Unknown error';
                    try {
                        const errorData = await response.json();
                        if (typeof errorData.detail === 'string') {
                            errorMessage = errorData.detail;
                        } else if (errorData.detail && typeof errorData.detail === 'object') {
                            errorMessage = JSON.stringify(errorData.detail);
                        } else if (errorData.message) {
                            errorMessage = errorData.message;
                        }
                    } catch (e) {
                        errorMessage = response.statusText || 'Request failed';
                    }
                    errorMessages.push(`項目 ${itemId}: ${errorMessage}`);
                }
            } catch (error) {
                errorMessages.push(`項目 ${itemId}: ${error.message}`);
            }
        }

        // 重新渲染列表
        renderTestRunItems();

        // 重新載入項目和統計
        await loadTestRunItems();
        await updateStatistics();

        // 若詳情 Modal 開啟中且顯示的項目已被刪除，則關閉 Modal
        try {
            const modalEl = document.getElementById('testCaseDetailModal');
            const isShown = modalEl && modalEl.classList.contains('show');
            if (isShown && currentDetailTestCase) {
                const item = testRunItems.find(i => i.test_case_number === currentDetailTestCase.test_case_number);
                if (!item) {
                    // 如果當前顯示的項目已被刪除，關閉 Modal
                    const modal = bootstrap.Modal.getInstance(modalEl);
                    if (modal) modal.hide();
                }
            }
        } catch (_) {}

        // 清空選擇狀態並更新 UI
        selectedItems.clear();
        updateItemSelectionUI();

        // 顯示結果訊息
        if (successCount === itemsToDelete.length) {
            // 全部成功
            const successMsg = window.i18n && window.i18n.isReady()
                ? window.i18n.t('testRun.batchDeleteSuccess', {count: successCount})
                : `成功刪除 ${successCount} 個測試執行項目及其測試歷程`;
            AppUtils.showSuccess(successMsg);
        } else if (successCount > 0) {
            // 部分成功
            const partialMsg = window.i18n && window.i18n.isReady()
                ? window.i18n.t('testRun.batchDeletePartial', {success: successCount, total: itemsToDelete.length})
                : `已處理 ${itemsToDelete.length} 個項目，成功刪除 ${successCount} 個測試執行項目`;
            AppUtils.showWarning(partialMsg);

            if (errorMessages.length > 0) {
                console.warn('批次刪除錯誤:', errorMessages);
            }
        } else {
            // 全部失敗
            const failMsg = window.i18n && window.i18n.isReady()
                ? window.i18n.t('testRun.batchDeleteFailed')
                : '批次刪除失敗';
            throw new Error(`${failMsg}: ${errorMessages.join(', ')}`);
        }

    } catch (error) {
        const consoleMsg = window.i18n && window.i18n.isReady()
            ? window.i18n.t('testRun.batchDeleteFailed')
            : '批次刪除測試執行項目失敗';
        console.error(consoleMsg + ':', error);
        throw error;
    }
}

function navigateToTestCase(testCaseNumber) {
    if (!testCaseNumber) {
        AppUtils.showWarning(treTranslate('testRun.invalidTestCaseNumber', '無效的測試案例編號'));
        return;
    }

    try {
        if (Array.isArray(testRunItems)) {
            const item = testRunItems.find(it => it.test_case_number === testCaseNumber);
            if (item && item.__testCaseDeleted) {
                AppUtils.showWarning('此測試案例已刪除');
                return;
            }
        }
    } catch (_) {}
    
    // 顯示 Test Case 詳細資料 Modal
    showTestCaseDetailModal(testCaseNumber);
}

// Test Case 詳細資料 Modal 相關函數

// 初始化 Test Case 詳細資料 Modal 中的 AssigneeSelector
function initializeTestCaseAssigneeSelector(testCase) {
    if (!getTrePermissions().canAssign) return;
    if (!window.AssigneeSelector || !currentTeamId) return;

    const assigneeInput = document.querySelector('#testCaseDetailModal .assignee-editor[data-assignee-selector]');
    if (!assigneeInput) return;

    // 清理之前的實例
    if (assigneeInput._assigneeSelector) {
        assigneeInput._assigneeSelector.destroy();
    }

    const options = {
        teamId: currentTeamId,
        allowCustomValue: true,
        onSelect: (contact) => {
            // 更新當前 Test Run Item 的 assignee（以本地 SQLite 為準）
            const item = (testRunItems || []).find(i => i.test_case_number === testCase.test_case_number);
            if (item) updateAssignee(item.id, contact.name);
        },
        onClear: () => {
            const item = (testRunItems || []).find(i => i.test_case_number === testCase.test_case_number);
            if (item) updateAssignee(item.id, '');
        }
    };

    assigneeInput._assigneeSelector = new AssigneeSelector(assigneeInput, options);
}

// 已移除：原先更新 Test Case 的 Assignee（改為只更新 Test Run Item 的本地欄位）

function handleAttachmentSummaryClick(event) {
    try {
        if (event) {
            event.preventDefault();
        }
        const link = event && event.currentTarget ? event.currentTarget : null;
        const canScroll = link && link.dataset ? link.dataset.canScroll === 'true' : true;
        if (!canScroll) {
            return false;
        }
        scrollToAttachments();
    } catch (_) {
        return false;
    }
    return false;
}

async function showTestCaseDetailModal(testCaseNumber) {
    // 初始化 Modal
    const modalElement = document.getElementById('testCaseDetailModal');
    if (!testCaseDetailModalInstance) {
        testCaseDetailModalInstance = new bootstrap.Modal(modalElement);
    }
    const permissions = getTrePermissions();
    
    // 確保這個 Modal 有最高的 z-index (高於其他 Modal)
    // Bug Tickets Summary Modal 預設是 1055，所以設置為 1080 確保在上層
    modalElement.style.zIndex = '1080';
    
    // 設置 Modal 事件監聽器來處理 backdrop z-index
    modalElement.addEventListener('shown.bs.modal', function() {
        // 找到最新的 backdrop 並設置正確的 z-index
        const backdrops = document.querySelectorAll('.modal-backdrop');
        if (backdrops.length > 0) {
            // 設置最新的 backdrop 有較高的 z-index
            const latestBackdrop = backdrops[backdrops.length - 1];
            latestBackdrop.style.zIndex = '1079';
        }
        
        // 確保 Modal 本身的 z-index 是最高的
        modalElement.style.zIndex = '1080';
    });
    
    // 重置 Modal 狀態
    document.getElementById('testCaseDetailLoading').style.display = 'block';
    const fixedDiv = document.getElementById('testCaseDetailFixed');
    const scrollDiv = document.getElementById('testCaseDetailScrollable');
    fixedDiv.style.display = 'none';
    scrollDiv.style.display = 'none';
    document.getElementById('testCaseDetailError').style.display = 'none';
    document.getElementById('openFullTestCaseBtn').style.display = 'none';
    // 在載入期間先隱藏/清空標頭的 Test Result，避免顯示舊資料
    const headerResult = document.getElementById('testCaseDetailHeaderResult');
    if (headerResult) {
        headerResult.innerHTML = '';
        headerResult.style.visibility = 'hidden';
    }
    
    // 顯示 Modal
    testCaseDetailModalInstance.show();
    // 綁定鍵盤左右鍵支援
    const modalEl = document.getElementById('testCaseDetailModal');
    if (!modalEl._keydownBound) {
        modalEl.addEventListener('shown.bs.modal', function() {
            document.addEventListener('keydown', handleExecDetailModalKeydown);
        });
        modalEl.addEventListener('hidden.bs.modal', function() {
            document.removeEventListener('keydown', handleExecDetailModalKeydown);
        });
        modalEl._keydownBound = true;
    }
    
    try {
        // 載入 Test Case 資料
        await loadTestCaseDetail(testCaseNumber);
    } catch (error) {
        console.error('Failed to load test case detail:', error);
        showTestCaseDetailError();
    }
}

async function loadTestCaseDetail(testCaseNumber) {
    try {
        // 先嘗試從跨頁快取讀取
        const cached = await getCachedTestCase(testCaseNumber);
        const isFresh = cached && (Date.now() - cached.ts) < TEST_CASE_CACHE_TTL_MS;
        const hasAttachments = cached && cached.data && Array.isArray(cached.data.attachments) && cached.data.attachments.length > 0;
        // 若快取新鮮且包含附件，直接使用；否則改以 by-number 拉完整詳情（含附件）
        if (isFresh && hasAttachments) {
            displayTestCaseDetail(cached.data);
            return;
        }

        // 先以 by-number 取得完整詳情（含附件）
        const resp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/testcases/by-number/${encodeURIComponent(testCaseNumber)}`);
        if (resp.ok) {
            const testCase = await resp.json();
            setCachedTestCase(testCaseNumber, testCase);
            displayTestCaseDetail(testCase);
            return;
        }

        // 後備：用列表搜尋（可能不含附件，僅避免完全失敗）
        const url = new URL(`/api/teams/${currentTeamId}/testcases/`, window.location.origin);
        url.searchParams.set('search', testCaseNumber);
        url.searchParams.set('limit', '1');
        const response = await window.AuthClient.fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const testCases = await response.json();
        if (!Array.isArray(testCases) || testCases.length === 0) {
            throw new Error('找不到指定的測試案例');
        }
        const fallback = testCases.find(tc => tc.test_case_number === testCaseNumber) || testCases[0];
        setCachedTestCase(testCaseNumber, fallback);
        displayTestCaseDetail(fallback);
        
    } catch (error) {
        console.error('Error loading test case detail:', error);
        throw error;
    }
}

function displayTestCaseDetail(testCase) {
    const permissions = getTrePermissions();

    // 隱藏載入狀態
    document.getElementById('testCaseDetailLoading').style.display = 'none';
    
    // 準備顯示資料
    const fixedDiv = document.getElementById('testCaseDetailFixed');
    const scrollDiv = document.getElementById('testCaseDetailScrollable');
    const openBtn = document.getElementById('openFullTestCaseBtn');
    
    // 生成詳細資料 HTML（拆分固定與可捲動內容）
    const { fixedHtml, scrollableHtml } = createTestCaseDetailHtml(testCase);
    fixedDiv.innerHTML = fixedHtml;
    scrollDiv.innerHTML = scrollableHtml;
    
    // 顯示內容和開啟按鈕
    const bodyRow = document.getElementById('testCaseDetailBodyRow');
    const referenceBtn = document.getElementById('referenceTestCaseExecBtn');
    if (bodyRow) bodyRow.classList.remove('d-none');
    fixedDiv.style.display = 'block';
    scrollDiv.style.display = 'block';
    openBtn.style.display = 'inline-block';
    if (referenceBtn) referenceBtn.style.display = 'inline-block';
    // 記錄目前展示的 Test Case，供鍵盤導航使用
    currentDetailTestCase = testCase;
    
    // 設定開啟按鈕的點擊事件
    openBtn.onclick = function() {
        const url = `/test-case-management?tc=${encodeURIComponent(testCase.test_case_number)}&team_id=${encodeURIComponent(currentTeamId)}&minimal=1&mode=edit`;
        window.open(url, 'TestCaseEditor', 'width=1200,height=800,noopener,noreferrer');
    };
    
    // 設定參考測試案例按鈕的點擊事件（改為開啟瀏覽器彈窗）
    if (referenceBtn) {
        referenceBtn.onclick = function() {
            const url = `/test-case-reference?team_id=${encodeURIComponent(currentTeamId)}`;
            window.open(url, 'TestCaseReference', 'width=1200,height=800,noopener,noreferrer');
        };
    }
    
    // 應用 i18n 翻譯
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(fixedDiv);
        window.i18n.retranslate(scrollDiv);
    }

    // 在標頭區渲染 Test Result 下拉或唯讀 badge
    renderModalHeaderResult(testCase);

    // 渲染右側 Timeline（結果歷程）
    renderResultHistoryTimeline(testCase);
    
    // 載入 Bug Tickets 和 Test Results
    const testRunItem = (testRunItems || []).find(item => item.test_case_number === testCase.test_case_number);
    if (testRunItem && testRunItem.id) {
        loadBugTickets(testRunItem.id);

        // 初始化 Test Results 管理器
        initializeTestResults(
            testRunItem.id,
            testCase.test_case_number,
            currentTeamId,
            currentConfigId
        );

        // 載入 Comment
        loadComment(testRunItem.id);
    }
    // 載入完成後再顯示，避免切換時顯示上一筆資料
    const headerResult = document.getElementById('testCaseDetailHeaderResult');
    if (headerResult) {
        headerResult.style.visibility = 'visible';
    }

    // 綁定上一隻、下一隻按鈕
    const prevBtn = document.getElementById('prevExecCaseBtn');
    const nextBtn = document.getElementById('nextExecCaseBtn');
    if (prevBtn && nextBtn) {
        prevBtn.onclick = () => navigateExecCase(testCase, -1);
        nextBtn.onclick = () => navigateExecCase(testCase, 1);
        // 依序號狀態啟用/停用
        const idx = (testRunItems || []).findIndex(i => i.test_case_number === testCase.test_case_number);
        prevBtn.disabled = idx <= 0;
        nextBtn.disabled = idx < 0 || idx >= testRunItems.length - 1;
    }

    // 綁定複製連結按鈕（Test Case 詳情）
    try {
        const copyBtn = document.getElementById('copyExecCaseLinkBtn');
        if (copyBtn) {
            copyBtn.onclick = () => {
                const teamId = getCurrentTeamId();
                const cfgId = (typeof currentConfigId !== 'undefined' && currentConfigId) ? currentConfigId : new URLSearchParams(window.location.search).get('config_id');
                const url = buildTreUrl(cfgId, teamId, testCase.test_case_number);
                if (window.AppUtils && typeof AppUtils.showCopyModal === 'function') {
                    AppUtils.showCopyModal(url);
                } else {
                    const promptLabel = (window.i18n && typeof window.i18n.t === 'function')
                        ? window.i18n.t('copyModal.prompt', {}, '請手動複製此連結：')
                        : '請手動複製此連結：';
                    window.prompt(promptLabel, url);
                }
            };
        }
    } catch (_) {}

    // 初始化 AssigneeSelector
    initializeTestCaseAssigneeSelector(testCase);

    // 控制 Bug Tickets 新增按鈕狀態
    const addBugTicketBtn = document.getElementById('addBugTicketBtn');
    if (addBugTicketBtn && testRunConfig) {
        const canAddBugTickets = permissions.canManageBugTickets && testRunConfig.status !== 'completed' && testRunConfig.status !== 'archived';
        addBugTicketBtn.disabled = !canAddBugTickets;
        addBugTicketBtn.style.opacity = canAddBugTickets ? '1' : '0.3';
        addBugTicketBtn.style.cursor = canAddBugTickets ? 'pointer' : 'not-allowed';
    }

    // 控制 Comment 編輯按鈕狀態
    const editCommentBtn = document.getElementById('editCommentBtn');
    if (editCommentBtn && testRunConfig) {
        const canEditComments = permissions.canUpdateResults && testRunConfig.status !== 'completed' && testRunConfig.status !== 'archived';
        editCommentBtn.disabled = !canEditComments;
        editCommentBtn.style.opacity = canEditComments ? '1' : '0.3';
        editCommentBtn.style.cursor = canEditComments ? 'pointer' : 'not-allowed';

        if (canEditComments) {
            editCommentBtn.onclick = () => {
                const testRunItem = (testRunItems || []).find(item => item.test_case_number === testCase.test_case_number);
                if (testRunItem && testRunItem.id) {
                    editComment(testRunItem.id);
                }
            };
        }
    }
}

// 生成基本資訊區域的 HTML
function generateBasicInfoHtml(testCase) {
    // 以 Test Run Item 的 assignee_name 為準（本地 DB），而非 Test Case 的 assignee
    const itemForCase = (testRunItems || []).find(i => i.test_case_number === testCase.test_case_number);
    const assigneeName = itemForCase ? (itemForCase.assignee_name || '') : '';
    const permissions = getTrePermissions();
    const canAssign = permissions.canAssign && testRunConfig && testRunConfig.status !== 'completed' && testRunConfig.status !== 'archived';
    const tcgNumbers = Array.isArray(testCase.tcg)
        ? testCase.tcg.flatMap(t => {
            if (t && Array.isArray(t.text_arr) && t.text_arr.length) {
                return t.text_arr;
            }
            if (t && t.text) {
                return String(t.text)
                    .split(/[\s,，、|/]+/)
                    .map(s => s.trim())
                    .filter(Boolean);
            }
            if (typeof t === 'string') {
                return String(t)
                    .split(/[\s,，、|/]+/)
                    .map(s => s.trim())
                    .filter(Boolean);
            }
            return [];
        }).filter(Boolean)
        : [];
    const attachmentCount = Array.isArray(testCase.attachments) ? testCase.attachments.length : 0;

    const tcgTagsHtml = tcgNumbers.map(num => {
        const safe = escapeHtml(num);
        return '<span class="tcg-tag" style="margin-right:4px;" onclick="showTCGPreviewInTestRun(\'' + safe + '\', event)" title="' + safe + '">' + safe + '</span>';
    }).join('');

    const assigneeCell = canAssign
        ? `<input type="text" class="form-control form-control-sm assignee-editor basic-info-input"
               value="${escapeHtml(assigneeName || '')}"
               data-assignee-selector
               data-test-case-id="${testCase.test_case_number}"
               placeholder="${treTranslate('testRun.enterAssigneeName', '輸入執行者姓名')}">`
        : `<span class="text-muted">${escapeHtml(assigneeName || '-')}</span>`;

    return `
        <!-- Basic Info 區域 -->
        <div class="card mb-2">
            <div class="card-header py-1">
                <h6 class="card-title mb-0">
                    <i class="fas fa-info-circle me-2"></i>
                    <span data-i18n=\"testRun.basicInfo\">基本資訊</span>
                </h6>
            </div>
            <div class="card-body px-2 basic-info-body">
                <table class="table table-sm table-borderless mb-0 basic-info-table">
                    <tr>
                        <td class="basic-info-label" data-i18n=\"testRun.testCaseNumber\">編號</td>
                        <td class="basic-info-value"><code class="basic-info-code">${escapeHtml(testCase.test_case_number)}</code></td>
                        <td class="basic-info-label">${tcgNumbers.length ? 'TCG' : ''}</td>
                        <td class="basic-info-value">${tcgNumbers.length ? tcgTagsHtml : ''}</td>
                    </tr>
                    <tr>
                        <td class="basic-info-label" data-i18n="testRun.title">標題</td>
                        <td class="basic-info-value basic-info-title" colspan="3">${escapeHtml(testCase.title)}</td>
                    </tr>
                    <tr>
                        <td class="basic-info-label" data-i18n="testRun.priority">優先級</td>
                        <td class="basic-info-value"><span class="badge bg-secondary basic-info-badge">${escapeHtml(testCase.priority || 'Medium')}</span></td>
                        <td class="basic-info-label" data-i18n="testRun.assignee">執行者</td>
                        <td class="basic-info-value">${assigneeCell}</td>
                    </tr>
                    <tr>
                        <td class="basic-info-label basic-info-label-top" data-i18n="testRun.attachments">附件</td>
                        <td colspan="3" class="basic-info-value">
                            <div class="d-flex align-items-center">
                                <a href="#"
                                   id="attachmentCountLink"
                                   class="text-decoration-none ${attachmentCount > 0 ? '' : 'text-muted disabled-attachment-link'}"
                                   data-can-scroll="${attachmentCount > 0 ? 'true' : 'false'}"
                                   ${attachmentCount > 0 ? '' : 'aria-disabled="true" tabindex="-1"'}
                                   onclick="return handleAttachmentSummaryClick(event);"
                                   title="${escapeHtml(treTranslate('testRun.attachments', '附件'))}">
                                    <i class="fas fa-paperclip me-1"></i>
                                    <span id="attachmentCountValue">${attachmentCount}</span>
                                    <span data-i18n="testRun.files">個文件</span>
                                </a>
                            </div>
                        </td>
                    </tr>
                </table>
            </div>
        </div>
        <!-- Test Details 標題（固定） -->
        <div class="card mb-2">
            <div class="card-header py-2">
                <h6 class="card-title mb-0">
                    <i class="fas fa-clipboard-list me-2"></i>
                    <span data-i18n="testRun.testDetails">測試詳情</span>
                </h6>
            </div>
        </div>`;
}

// 生成可捲動內容區域的 HTML
function generateScrollableContentHtml(testCase) {
    const attachments = Array.isArray(testCase.attachments) ? testCase.attachments : [];
    const attachmentCount = attachments.length;

    return `
        <div class="card scrollable-content-card">
            <div class="card-body scrollable-content-body">
                ${testCase.precondition ? `
                <div class="mb-3">
                    <h6 class="mb-2" data-i18n="testRun.precondition">前置條件</h6>
                    <div class="section-block section-precondition">
                        <div class="markdown-preview mb-0 content-markdown">${renderMarkdown(testCase.precondition)}</div>
                    </div>
                </div>
                ` : ''}
                ${testCase.steps ? `
                <div class="mb-3">
                    <h6 class="mb-2" data-i18n="testRun.steps">測試步驟</h6>
                    <div class="section-block section-steps">
                        <div class="markdown-preview mb-0 content-markdown">${renderMarkdown(testCase.steps)}</div>
                    </div>
                </div>
                ` : ''}
                ${testCase.expected_result ? `
                <div class="mb-3">
                    <h6 class="mb-2" data-i18n="testRun.expectedResult">預期結果</h6>
                    <div class="section-block section-expected">
                        <div class="markdown-preview mb-0 content-markdown">${renderMarkdown(testCase.expected_result)}</div>
                    </div>
                </div>
                ` : ''}
                ${attachmentCount > 0 ? `
                <div class="mt-3" id="attachmentsSection">
                    <h6 class="mb-2" data-i18n="testRun.attachments">附件</h6>
                    <div class="section-block section-attachments">
                    <div class="d-flex flex-wrap align-items-center">
                        ${attachments.map((attachment, index) => {
                            const fileExtension = attachment.name ? attachment.name.split('.').pop().toLowerCase() : '';
                            let iconClass = 'fas fa-file';
                            let iconColor = 'text-secondary';
                            switch(fileExtension) {
                                case 'pdf': iconClass = 'fas fa-file-pdf'; iconColor = 'text-danger'; break;
                                case 'doc': case 'docx': iconClass = 'fas fa-file-word'; iconColor = 'text-primary'; break;
                                case 'xls': case 'xlsx': iconClass = 'fas fa-file-excel'; iconColor = 'text-success'; break;
                                case 'jpg': case 'jpeg': case 'png': case 'gif': case 'bmp': case 'webp': iconClass = 'fas fa-file-image'; iconColor = 'text-info'; break;
                                case 'txt': iconClass = 'fas fa-file-alt'; iconColor = 'text-secondary'; break;
                                case 'zip': case 'rar': case '7z': iconClass = 'fas fa-file-archive'; iconColor = 'text-warning'; break;
                                default: iconClass = 'fas fa-file'; iconColor = 'text-secondary';
                            }
                            const attachmentToken = attachment.file_token || attachment.token || '';
                            const attachmentName = attachment.name || ('附件 ' + (index + 1));
                            const attachmentUrl = attachment.url || '';
                            return '<span class="d-inline-flex align-items-center me-3 mb-2 attachment-item" '
                                + 'style="cursor: pointer; padding: 0.25rem 0.5rem; border-radius: 0.25rem; transition: background-color 0.15s;" '
                                + 'onclick="handleAttachmentClick(\'' + escapeHtml(attachmentName) + '\', \'' + attachmentToken + '\', \'' + attachmentUrl + '\')" '
                                + 'onmouseover="this.style.backgroundColor=\'var(--tr-bg-light)\'" '
                                + 'onmouseout="this.style.backgroundColor=\'transparent\'" '
                                + 'title="點擊查看附件: ' + escapeHtml(attachmentName) + '">'
                                + '<i class="' + iconClass + ' ' + iconColor + ' me-1"></i>'
                                + '<small style="text-decoration: underline; color: var(--tr-primary);">' + escapeHtml(attachmentName) + '</small>'
                                + '</span>';
                        }).join('')}
                    </div>
                    </div>
                </div>
                ` : ''}
            </div>
        </div>`;
}

function createTestCaseDetailHtml(testCase) {
    const fixedHtml = generateBasicInfoHtml(testCase);
    const scrollableHtml = generateScrollableContentHtml(testCase);

    return { fixedHtml, scrollableHtml };
}


function renderModalHeaderResult(testCase) {
    const container = document.getElementById('testCaseDetailHeaderResult');
    if (!container) return;

    const item = getItemByTestCaseNumber(testCase.test_case_number);
    const currentResult = item ? (item.test_result || '') : '';
    const canEdit = testRunConfig && testRunConfig.status === 'active';
    const hasExecutionHistory = item && item.executed_at !== null && item.executed_at !== undefined;

    if (canEdit && item) {
        container.innerHTML = `
            <select class="form-select form-select-sm result-selector-lg ${getResultClass(currentResult)}"
                    onchange="updateSelectClass(this); updateTestResult(${item.id}, this.value)">
                ${!hasExecutionHistory ? `<option value="">${escapeHtml(treTranslate('testRun.notExecuted', 'Not Executed'))}</option>` : ''}
                <option value="Passed" ${currentResult === 'Passed' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.passed', 'Passed'))}</option>
                <option value="Failed" ${currentResult === 'Failed' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.failed', 'Failed'))}</option>
                <option value="Retest" ${currentResult === 'Retest' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.retest', 'Retest'))}</option>
                <option value="Not Available" ${currentResult === 'Not Available' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.notAvailable', 'Not Available'))}</option>
                <option value="Pending" ${currentResult === 'Pending' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.pending', 'Pending'))}</option>
                <option value="Not Required" ${currentResult === 'Not Required' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.notRequired', 'Not Required'))}</option>
                <option value="Skip" ${currentResult === 'Skip' ? 'selected' : ''}>${escapeHtml(treTranslate('testRun.skip', 'Skip'))}</option>
            </select>
        `;
        const select = container.querySelector('select');
        if (select) updateSelectClass(select);
    } else {
        container.innerHTML = `
            <span class="badge result-badge-lg ${getResultClass(currentResult)}">${getResultText(currentResult)}</span>
        `;
    }
}

// 依 test_case_number 找到對應 item
function getItemByTestCaseNumber(testCaseNumber) {
    return (testRunItems || []).find(i => i.test_case_number === testCaseNumber);
}

async function renderResultHistoryTimeline(testCase) {
    try {
        const middlePane = document.getElementById('testCaseDetailMiddlePane');
        const rightPane = document.getElementById('testCaseDetailRightPane');
        const loading = document.getElementById('timelineLoading');
        const empty = document.getElementById('timelineEmpty');
        const list = document.getElementById('timelineList');
        if (!middlePane || !rightPane || !list) return;

        // 顯示中欄和右欄 (使用 flex 佈局)
        middlePane.style.display = 'flex';
        rightPane.style.display = 'flex';
        loading.style.display = 'block';
        empty.style.display = 'none';
        list.innerHTML = '';

        const item = getItemByTestCaseNumber(testCase.test_case_number);
        if (!item) { loading.style.display = 'none'; empty.style.display = 'block'; return; }
        
        // 設定當前項目 ID 供 Bug Ticket 功能使用
        currentItemIdForBugTicket = item.id;

        const resp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/${item.id}/result-history?limit=50`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const records = await resp.json();
        loading.style.display = 'none';

        if (!Array.isArray(records) || records.length === 0) {
            empty.style.display = 'block';
            return;
        }

        // 生成 timeline 項目
        const rows = records.map(r => {
            const time = r.changed_at ? AppUtils.formatDate(r.changed_at, 'datetime') : '';
            const from = r.prev_result ? getResultText(r.prev_result) : treTranslate('testRun.notExecuted', 'Not Executed');
            const to = r.new_result ? getResultText(r.new_result) : treTranslate('testRun.notExecuted', 'Not Executed');
            const badgeFrom = `<span class="badge ${getResultClass(r.prev_result)}">${from}</span>`;
            const badgeTo = `<span class="badge ${getResultClass(r.new_result)}">${to}</span>`;
            const who = r.changed_by_name || '';
            const reason = r.change_reason ? `<div class="text-muted small">${escapeHtml(r.change_reason)}</div>` : '';
            return `
                <div class="timeline-item">
                    <div class="time">${time}${who ? ` · ${escapeHtml(who)}` : ''}</div>
                    <div class="status">${badgeFrom} <i class="fas fa-arrow-right mx-1"></i> ${badgeTo}</div>
                    ${reason}
                    <div class="timeline-divider"></div>
                </div>
            `;
        }).join('');
        list.innerHTML = rows;

        // Bug Tickets 在 displayTestCaseDetail 中載入

        // 綁定刷新按鈕
        const refreshBtn = document.getElementById('refreshTimelineBtn');
        if (refreshBtn) refreshBtn.onclick = () => renderResultHistoryTimeline(testCase);
    } catch (e) {
        const loading = document.getElementById('timelineLoading');
        const empty = document.getElementById('timelineEmpty');
        if (loading) loading.style.display = 'none';
        if (empty) empty.style.display = 'block';
        console.warn('load result history failed:', e);
    }
}

// 點擊 Basic Info 的附件摘要時，捲動到內容區的附件區塊
function scrollToAttachments() {
    try {
        const container = document.getElementById('testCaseDetailScrollable');
        const target = container ? container.querySelector('#attachmentsSection') : null;
        if (container && target) {
            const top = target.offsetTop - 8; // 預留一點上邊距
            container.scrollTo({ top, behavior: 'smooth' });
        }
    } catch (_) {}
}

// 鍵盤支援：在執行頁的 Test Case 詳細 Modal 使用左右鍵切換
function handleExecDetailModalKeydown(e) {
    try {
        const modal = document.getElementById('testCaseDetailModal');
        if (!modal || !modal.classList.contains('show')) return;
        // 避免在輸入元件或可編輯區域觸發
        const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
        const isEditable = e.target && (e.target.isContentEditable || tag === 'input' || tag === 'textarea' || tag === 'select');
        if (isEditable) return;
        if (!currentDetailTestCase) return;
        if (e.key === 'ArrowLeft') {
            e.preventDefault();
            navigateExecCase(currentDetailTestCase, -1);
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            navigateExecCase(currentDetailTestCase, 1);
        }
    } catch (_) {}
}

async function navigateExecCase(currentTestCase, step) {
    if (!Array.isArray(testRunItems) || testRunItems.length === 0) return;
    const idx = testRunItems.findIndex(i => i.test_case_number === currentTestCase.test_case_number);
    if (idx < 0) return;
    const newIdx = idx + step;
    if (newIdx < 0 || newIdx >= testRunItems.length) return;
    const nextItem = testRunItems[newIdx];
    if (!nextItem) return;
    // 重用現有流程：以 test_case_number 載入詳細
    await showTestCaseDetailModal(nextItem.test_case_number);
}

// 移除 Modal 內更新結果的輔助函式（已回滾設計）

function showTestCaseDetailError() {
    const loadingEl = document.getElementById('testCaseDetailLoading');
    const bodyRowEl = document.getElementById('testCaseDetailBodyRow');
    const errorEl = document.getElementById('testCaseDetailError');

    if (loadingEl) loadingEl.style.display = 'none';
    if (bodyRowEl) bodyRowEl.style.display = 'none';
    if (errorEl) errorEl.style.display = 'block';
}

async function updateAssignee(itemId, assigneeName) {
    if (!getTrePermissions().canAssign) {
        showExecutionPermissionDenied();
        return;
    }
    try {
        // 清理輸入值
        const cleanAssignee = assigneeName ? assigneeName.trim() : '';
        
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/${itemId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                assignee_name: cleanAssignee || null
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        // 更新本地資料
        const itemIndex = testRunItems.findIndex(item => item.id === itemId);
        if (itemIndex !== -1) {
            testRunItems[itemIndex].assignee_name = cleanAssignee || null;
        }
        
        // 不顯示成功訊息，讓編輯過程更流暢
        
    } catch (error) {
        console.error('Failed to update assignee:', error);
        AppUtils.showError(`${treTranslate('testRun.updateAssigneeFailed', '更新執行者失敗')}: ${error.message}`);
        
        // 恢復原始值
        const input = document.querySelector(`input[data-item-id="${itemId}"]`);
        if (input) {
            const originalItem = testRunItems.find(item => item.id === itemId);
            input.value = originalItem ? (originalItem.assignee_name || '') : '';
        }
    }
}

// 處理附件點擊事件
function handleAttachmentClick(attachmentName, fileToken, fileUrl) {
    // 1) 本地附件：直接打開 /attachments 相對路徑
    if (fileUrl && fileUrl.trim().startsWith('/attachments')) {
        window.open(fileUrl, '_blank', 'noopener,noreferrer');
        return;
    }
    
    // 2) 絕對 URL：直接開啟
    if (fileUrl && /^(https?:)?\/\//i.test(fileUrl.trim())) {
        window.open(fileUrl, '_blank', 'noopener,noreferrer');
        return;
    }

    // 3) 仍需走代理（保留相容）
    if ((fileToken && fileToken.trim() !== '') || (fileUrl && fileUrl.trim() !== '')) {
        try {
            const proxyUrl = new URL(`/api/attachments/teams/${currentTeamId}/attachments/download`, window.location.origin);
            if (fileUrl && fileUrl.trim() !== '') {
                proxyUrl.searchParams.set('file_url', fileUrl);
            } else if (fileToken && fileToken.trim() !== '') {
                proxyUrl.searchParams.set('file_token', fileToken);
            }
            if (attachmentName && attachmentName.trim() !== '') {
                proxyUrl.searchParams.set('filename', attachmentName);
            }
            window.open(proxyUrl.toString(), '_blank', 'noopener,noreferrer');
            return;
        } catch (error) {
            console.error('構建代理下載 URL 失敗:', error);
        }
    }
    
    // 4) 沒有可用資訊：顯示說明
    showAttachmentInfo(attachmentName, fileToken, fileUrl);
}

// 顯示附件信息
function showAttachmentInfo(attachmentName, fileToken, fileUrl) {
    const modalHtml = `
        <div class="modal fade" id="attachmentInfoModal" tabindex="-1">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-paperclip me-2"></i>
                            <span data-i18n="testRun.attachmentDetails">附件詳情</span>
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <table class="table table-borderless">
                            <tr>
                                <td class="fw-bold" data-i18n="testRun.attachmentName">附件名稱:</td>
                                <td>${escapeHtml(attachmentName)}</td>
                            </tr>
                            <tr>
                                <td class="fw-bold">File Token:</td>
                                <td><code style="font-size: 0.8rem; word-break: break-all;">${escapeHtml(fileToken)}</code></td>
                            </tr>
                            ${fileUrl ? `
                            <tr>
                                <td class="fw-bold">URL:</td>
                                <td><a href="${escapeHtml(fileUrl)}" target="_blank" rel="noopener">${escapeHtml(fileUrl)}</a></td>
                            </tr>
                            ` : ''}
                        </table>
                        <div class="alert alert-info">
                            <i class="fas fa-info-circle me-2"></i>
                            <span data-i18n="testRun.attachmentNote">此附件存儲在 Lark 中。如需下載，請前往原始 Lark 多維表格查看。</span>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal" data-i18n="common.close">關閉</button>
                        ${(fileUrl || fileToken) ? `
                        <button type="button" class="btn btn-primary" onclick="handleAttachmentDownload('${escapeHtml(attachmentName)}', '${fileToken}', '${escapeHtml(fileUrl)}')">
                            <i class="fas fa-download me-2"></i>
                            <span data-i18n="testRun.downloadAttachment">下載附件</span>
                        </button>
                        ` : ''}
                    </div>
                </div>
            </div>
        </div>`;
    
    // 移除舊的模態框（如果存在）
    const existingModal = document.getElementById('attachmentInfoModal');
    if (existingModal) {
        existingModal.remove();
    }
    
    // 添加新的模態框到頁面
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // 顯示模態框
    const modal = new bootstrap.Modal(document.getElementById('attachmentInfoModal'));
    
    // 應用翻譯（如果可用）
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(document.getElementById('attachmentInfoModal'));
    }
    
    modal.show();
    
    // 模態框關閉後清理
    document.getElementById('attachmentInfoModal').addEventListener('hidden.bs.modal', function() {
        this.remove();
    });
}

// 處理附件下載（從信息模態框中）
function handleAttachmentDownload(attachmentName, fileToken, fileUrl) {
    // 1) 本地附件：直接開啟 /attachments 相對路徑
    if (fileUrl && fileUrl.trim().startsWith('/attachments')) {
        window.open(fileUrl, '_blank', 'noopener,noreferrer');
        return;
    }
    // 2) 絕對 URL：直接開啟
    if (fileUrl && /^(https?:)?\/\//i.test(fileUrl.trim())) {
        window.open(fileUrl, '_blank', 'noopener,noreferrer');
        return;
    }

    // 3) 走代理（保留相容）
    if ((fileToken && fileToken.trim() !== '') || (fileUrl && fileUrl.trim() !== '')) {
        try {
            const proxyUrl = new URL(`/api/attachments/teams/${currentTeamId}/attachments/download`, window.location.origin);
            if (fileUrl && fileUrl.trim() !== '') {
                proxyUrl.searchParams.set('file_url', fileUrl);
            } else if (fileToken && fileToken.trim() !== '') {
                proxyUrl.searchParams.set('file_token', fileToken);
            }
            if (attachmentName && attachmentName.trim() !== '') {
                proxyUrl.searchParams.set('filename', attachmentName);
            }
            window.open(proxyUrl.toString(), '_blank', 'noopener,noreferrer');
        } catch (error) {
            console.error('構建附件下載 URL 失敗:', error);
            const errorMessage = window.i18n ? window.i18n.t('errors.attachmentDownloadFailed', {}, '附件下載失敗') : '附件下載失敗';
            AppUtils.showError(errorMessage + ': ' + error.message);
        }
    } else {
        const warningMessage = window.i18n ? window.i18n.t('errors.noAttachmentDownloadInfo', {}, '沒有可用的附件下載信息') : '沒有可用的附件下載信息';
        AppUtils.showWarning(warningMessage);
    }
}

// ===== JIRA Tooltip 功能 =====
