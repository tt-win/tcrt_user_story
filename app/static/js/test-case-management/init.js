/* ============================================================
   TEST CASE MANAGEMENT - INIT/LOADING
   ============================================================ */

/* ============================================================
   10. 初始化 (Initialization)
   ============================================================ */

/**
 * 初始化測試案例管理頁面
 */
async function initTestCaseManagement() {
    // 顯示進度條
    showLoadingProgress();

    try {
        // 載入 TCG 快取 (如果需要)
        const hasCachedTCG = await loadTCGCacheFromStorage();
        if (!hasCachedTCG || shouldUpdateTCGCache()) {
            await loadTCGCache((progress, message) => {
                updateTCGCacheProgress(progress, message);
            });
        } else {
            updateTCGCacheProgress(100, `使用快取 (${tcgCache.length} 筆)`);
        }

        // 載入測試案例
        await loadTestCases(false, (progress, message) => {
            updateTestCaseProgress(progress, message);
        });

    } catch (error) {
        console.error('初始化失敗:', error);
    } finally {
        // 隱藏進度條
        hideLoadingProgress();
        // 初始化篩選狀態
        updateFilterStatus();
        // Query string 篩選優先於 localStorage；若有 query params 則套用並觸發篩選
        let restoredFromQS = false;
        try { restoredFromQS = restoreFiltersFromQueryString(); } catch (_) {}
        if (restoredFromQS) {
            try { applyFilters(); } catch (_) {}
        } else {
            try { restoreTcmFiltersToUI(); } catch (_) {}
        }
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

// 進度條控制函數
function showLoadingProgress() {
    const progressDiv = document.getElementById('loadingProgress');
    if (progressDiv) {
        progressDiv.style.display = 'block';
    }

    // 隱藏搜尋與篩選區和表格
    const searchCard = document.getElementById('searchFilterCard');
    const tableCard = document.getElementById('testCasesCard');
    if (searchCard) searchCard.style.display = 'none';
    if (tableCard) tableCard.style.display = 'none';
}

function hideLoadingProgress() {
    const progressDiv = document.getElementById('loadingProgress');
    if (progressDiv) {
        progressDiv.style.display = 'none';
    }

    // 顯示搜尋與篩選區和表格
    const searchCard = document.getElementById('searchFilterCard');
    const tableCard = document.getElementById('testCasesCard');
    if (searchCard) searchCard.style.display = 'block';
    if (tableCard) tableCard.style.display = 'block';
    // 顯示後調整列表高度
    adjustTestCasesScrollHeight();
}


function updateTestCaseProgress(progress, message = '') {
    const progressBar = document.getElementById('testCaseProgressBar');
    const progressText = document.getElementById('testCaseProgress');

    if (progressBar) {
        progressBar.style.width = progress + '%';
    }
    if (progressText) {
        progressText.textContent = `${Math.round(progress)}%${message ? ' - ' + message : ''}`;
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

function updateTCGCacheProgress(progress, message = '') {
    const progressBar = document.getElementById('tcgCacheProgressBar');
    const progressText = document.getElementById('tcgCacheProgress');

    if (progressBar) {
        progressBar.style.width = progress + '%';
    }
    if (progressText) {
        progressText.textContent = `${Math.round(progress)}%${message ? ' - ' + message : ''}`;
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}


async function loadTestCases(showLoadingBlock = true, updateProgress = null, forceRefresh = false, preserveState = false) {
    try {
        if (updateProgress) updateProgress(0, '開始載入測試案例...');

        // 獲取當前選擇的團隊
        let currentTeam = AppUtils.getCurrentTeam ? AppUtils.getCurrentTeam() : null;
        if (!currentTeam || !currentTeam.id) {
            currentTeam = await ensureTeamContext();
        }
        if (!currentTeam || !currentTeam.id) {
            throw new Error('請先選擇團隊');
        }
        const teamIdForLoad = String(currentTeam.id);

        // 非強制刷新時先檢查快取
        // 注意：如果指定了 currentSetId，則不使用快取（因為快取是按 team 保存的，不區分 set）
        if (!forceRefresh && !currentSetId) {
            const cachedTestCases = getTestCasesCache(teamIdForLoad);
            if (cachedTestCases) {
                if (updateProgress) updateProgress(90, '使用快取資料...');

                testCases = cachedTestCases;
                if (!preserveState) sectionSortStates.clear();
                console.debug('[CACHE] LOAD list from cache', { teamId: teamIdForLoad, count: testCases.length });

                // 依當前排序狀態排序（預設 number/asc）
                sortTestCaseList(testCases, tcmSortField, tcmSortOrder);

                // 依目前記憶體中的過濾器計算顯示清單
                applyCurrentFiltersAndRender();

                const completedMsg = window.i18n ?
                    window.i18n.t('loading.completedWithCount', {count: testCases.length}) + ' (快取)' :
                    `載入完成 (${testCases.length} 筆，快取)`;
                if (updateProgress) updateProgress(100, completedMsg);

                return; // 使用快取，直接返回
            }
            console.debug('[CACHE] BYPASS: no cache hit for list', { teamId: teamIdForLoad });
        } else {
            if (forceRefresh) {
                console.debug('[CACHE] BYPASS: forceRefresh=true, skip cache', { teamId: teamIdForLoad });
            } else {
                console.debug('[CACHE] BYPASS: currentSetId=' + currentSetId + ', skip cache', { teamId: teamIdForLoad });
            }
        }

        if (showLoadingBlock) {
            showLoadingState();
        }

        // 提供 fallback 參數確保即使 i18n 未完全載入也有正確顯示
        const connectingMsg = window.i18n ? window.i18n.t('loading.connecting', {}, '連接伺服器...') : '連接伺服器...';
        if (updateProgress) updateProgress(30, connectingMsg);

        // 如果指定了 currentSetId，只載入該 set 的 test case；否則載入所有
        let url = `/api/teams/${teamIdForLoad}/testcases/?load_all=true`;
        if (currentSetId) {
            console.log(`[TCM] 載入 Set ${currentSetId} 的測試案例`);
            url += `&set_id=${currentSetId}`;
        }

        const response = await window.AuthClient.fetch(url);
        if (!response.ok) {
            throw new Error(`載入測試案例失敗: ${response.status} ${response.statusText}`);
        }

        if (updateProgress) updateProgress(60, '解析資料...');

        testCases = await response.json();
        if (!preserveState) sectionSortStates.clear();

        // 儲存到快取
        if (updateProgress) updateProgress(70, '更新快取...');
        setTestCasesCache(testCases, teamIdForLoad);

        if (updateProgress) updateProgress(80, '處理資料...');

        // 依當前排序狀態排序（預設 number/asc）
        sortTestCaseList(testCases, tcmSortField, tcmSortOrder);

        // 依目前記憶體中的過濾器計算顯示清單
        if (updateProgress) updateProgress(95, '渲染表格...');

        applyCurrentFiltersAndRender();
        if (showLoadingBlock) {
            hideLoadingState();
        }

        const completedMsg = window.i18n ? window.i18n.t('loading.completedWithCount', {count: testCases.length}) : `載入完成 (${testCases.length} 筆)`;
        if (updateProgress) updateProgress(100, completedMsg);

    } catch (error) {
        console.error('載入測試案例失敗:', error);
        const message = window.i18n ? window.i18n.t('errors.loadTestCasesFailed') : '載入測試案例失敗';
        const errorMsg = error && error.message ? String(error.message) : '';
        showError(message + (errorMsg ? '：' + errorMsg : ''));
        if (showLoadingBlock) {
            hideLoadingState();
        }
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

async function refreshTestCases() {
    const refreshBtn = document.getElementById('refreshBtn');
    const originalHTML = refreshBtn.innerHTML;

    // 檢查是否有搜尋條件
    const hasFilters = hasAnyFilters();

    // 顯示載入動畫在按鈕內
    refreshBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status"></span>${window.i18n ? window.i18n.t('common.refresh') : '重新載入'}${hasFilters ? (window.i18n ? ' & ' + window.i18n.t('common.filter') : ' & 篩選') : ''}`;
    refreshBtn.disabled = true;

    try {
        // 清除所有快取，強制從伺服器重新載入
        clearTestCasesCache();

        // 調用 loadTestCases，強制刷新且不顯示載入區塊
        await loadTestCases(false, null, true);

        // 重新載入後，自動套用當前的搜尋條件
        if (hasFilters) {
            applyFilters();
            // 提示使用者已保持篩選條件
            AppUtils.showSuccess(window.i18n ? window.i18n.t('messages.dataReloadedWithFilters') : '資料已重新載入，篩選條件已保持');
        } else {
            AppUtils.showSuccess(window.i18n ? window.i18n.t('messages.dataReloaded') : '資料已重新載入');
        }

    } finally {
        // 恢復按鈕原始狀態
        refreshBtn.innerHTML = originalHTML;
        refreshBtn.disabled = false;
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

// 檢查是否有任何篩選條件的輔助函數
function hasAnyFilters() {
    const testCaseNumberSearch = document.getElementById('testCaseNumberSearch').value.trim();
    const search = document.getElementById('searchInput').value.trim();
    const tcg = (document.getElementById('tcgFilter')?.value || '').trim();
    const priority = document.getElementById('priorityFilter').value;

    return testCaseNumberSearch || search || tcg || priority;
}

function renderTestCasesTable() {
    const stack = document.getElementById('testCasesStack');
    if (!stack) return;
    // 依目前排序設定排序並更新指示
    sortFilteredTestCases();

    if (!filteredTestCases.length) {
        tcmNavigationTestCases = [];
        stack.innerHTML = `
            <div class="text-center py-4">
                <i class="fas fa-search fa-2x text-muted mb-2"></i>
                <div class="text-muted" data-i18n="errors.noMatchingTestCases">沒有找到符合條件的測試案例</div>
            </div>
        `;
        return;
    }

    // 建立待渲染佇列（依 Section 分組，按排序好的 Section 順序）
    const grouped = groupTestCasesBySection(filteredTestCases);
    const sortedSectionIds = sortSectionIds(Object.keys(grouped), grouped);
    tcmNavigationTestCases = buildNavigationTestCasesFromGroups(grouped, sortedSectionIds);
    tcmRenderQueue = sortedSectionIds.map(sectionId => ({
        sectionId,
        group: grouped[sectionId]
    }));
    tcmRenderedCount = 0;
    stack.innerHTML = '';
    ensureVirtualScrollHandler();
    renderNextBatch(); // 首次渲染一批
    fillViewportIfNeeded('initial');
}

function renderNextBatch() {
    const stack = document.getElementById('testCasesStack');
    if (!stack || !tcmRenderQueue.length) return;
    const fragment = document.createDocumentFragment();
    let renderedNow = 0;

    while (tcmRenderQueue.length && renderedNow < TCM_RENDER_BATCH) {
        const { sectionId, group } = tcmRenderQueue.shift();
        const rowsHtml = group.testCases.map(renderTestCaseRow).join('');
        const visible = isSectionVisible(sectionId);
        const wrapper = document.createElement('div');
        wrapper.innerHTML = renderSectionBlockHTML(group, rowsHtml, visible);
        fragment.appendChild(wrapper.firstElementChild);
        renderedNow += group.testCases.length;
        tcmRenderedCount += group.testCases.length;
    }

    stack.appendChild(fragment);

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(stack);
    }

    updateTcmSortIndicators();
    adjustTestCasesScrollHeight();
}

let tcmVirtualScrollBound = false;
let tcmFillViewportLock = false;
function ensureVirtualScrollHandler() {
    if (tcmVirtualScrollBound) return;
    const scrollBox = document.getElementById('testCasesScroll');
    if (!scrollBox) return;
    tcmVirtualScrollBound = true;
    scrollBox.addEventListener('scroll', () => {
        const threshold = 200;
        if (scrollBox.scrollTop + scrollBox.clientHeight + threshold >= scrollBox.scrollHeight) {
            renderNextBatch();
        }
    });
}

function fillViewportIfNeeded(reason = '') {
    if (tcmFillViewportLock) return;
    const scrollBox = document.getElementById('testCasesScroll');
    if (!scrollBox || typeof renderNextBatch !== 'function') return;
    if (!Array.isArray(tcmRenderQueue) || tcmRenderQueue.length === 0) return;
    tcmFillViewportLock = true;
    try {
        const threshold = 120;
        let guard = 0;
        while (tcmRenderQueue.length &&
               scrollBox.scrollHeight <= scrollBox.clientHeight + threshold &&
               guard < 50) {
            renderNextBatch();
            guard += 1;
        }
        if (guard >= 50) {
            console.warn('[TCM] fillViewportIfNeeded guard hit', { reason });
        }
    } finally {
        tcmFillViewportLock = false;
    }
}


function bindEvents() {
    // 新增按鈕
    document.getElementById('addTestCaseBtn').addEventListener('click', () => showTestCaseModal());
    // 監聽大量新增欄位變更以更新預覽
    // 移除舊的前綴/末尾輸入監聽；改由 renderPrefixes 中的 oninput 觸發

    // 重新載入按鈕
    document.getElementById('refreshBtn').addEventListener('click', refreshTestCases);

    // Modal TCG 事件已在 DOMContentLoaded 中統一處理
    // 避免重複繫定

    // 批次複製按鈕
    const batchCopyBtn = document.getElementById('batchCopyBtn');
    if (batchCopyBtn) batchCopyBtn.addEventListener('click', openTestCaseBatchCopyModal);

    // 搜尋與篩選
    document.getElementById('applyFiltersBtn').addEventListener('click', applyFilters);
    document.getElementById('clearFiltersBtn').addEventListener('click', clearFilters);

    // 分享篩選連結
    const genLinkBtn = document.getElementById('generateFilterLinkBtn');
    if (genLinkBtn) genLinkBtn.addEventListener('click', generateShareFilterLink);
    const copyLinkBtn = document.getElementById('copyShareFilterLinkBtn');
    if (copyLinkBtn) copyLinkBtn.addEventListener('click', copyShareFilterLink);

    // 搜尋欄位 Enter 鍵支援
    document.getElementById('testCaseNumberSearch').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            applyFilters();
        }
    });
    document.getElementById('searchInput').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            applyFilters();
        }
    });

    // 批次操作
    const globalSelectAll = document.getElementById('selectAllCheckbox');
    if (globalSelectAll) globalSelectAll.addEventListener('change', toggleSelectAll);
    const batchModifyBtn = document.getElementById('batchModifyBtn');
    if (batchModifyBtn) batchModifyBtn.addEventListener('click', openTestCaseBatchModifyModal);
    const batchDeleteBtn = document.getElementById('batchDeleteBtn');
    if (batchDeleteBtn) batchDeleteBtn.addEventListener('click', batchDeleteTestCases);
    const clearSelectionBtnTC = document.getElementById('clearSelectionBtnTC');
    if (clearSelectionBtnTC) clearSelectionBtnTC.addEventListener('click', deselectAll);

    // 上一隻/下一隻測試案例按鈕
    document.getElementById('prevTestCaseBtn').addEventListener('click', showPrevTestCase);
    document.getElementById('nextTestCaseBtn').addEventListener('click', showNextTestCase);

    // 參考測試案例按鈕 - 使用內聯 onclick，不需要特別繫定
    // 因為 HTML 中已經有 onclick="openReferenceTestCasePopup()"

    // 批次修改模態框事件綁定
    const batchModifyPriorityCheckbox = document.getElementById('batchModifyPriority');
    const batchPrioritySelect = document.getElementById('batchPrioritySelect');
    if (batchModifyPriorityCheckbox && batchPrioritySelect) {
        batchModifyPriorityCheckbox.addEventListener('change', function() {
            batchPrioritySelect.disabled = !this.checked;
            if (!this.checked) {
                batchPrioritySelect.value = '';
            }
        });
    }
    const batchModifySectionCheckbox = document.getElementById('batchModifySection');
    const batchSectionSelect = document.getElementById('batchSectionSelect');
    const batchModifyTestSetCheckbox = document.getElementById('batchModifyTestSet');
    const batchTestSetSelect = document.getElementById('batchTestSetSelect');

    if (batchModifySectionCheckbox && batchSectionSelect) {
        batchModifySectionCheckbox.addEventListener('change', function() {
            if (this.checked) {
                // 區段與 Test Set 互斥
                if (batchModifyTestSetCheckbox && batchModifyTestSetCheckbox.checked) {
                    batchModifyTestSetCheckbox.checked = false;
                    batchTestSetSelect.value = '';
                    batchTestSetSelect.disabled = true;
                }

                if (!Array.isArray(tcmSectionsTree) || tcmSectionsTree.length === 0) {
                    const msg = window.i18n ? window.i18n.t('errors.sectionsNotReady', {}, '尚未載入區段列表') : '尚未載入區段列表';
                    AppUtils.showError(msg);
                    this.checked = false;
                    batchSectionSelect.disabled = true;
                    return;
                }
                populateBatchSectionSelect();
                batchSectionSelect.disabled = false;
            } else {
                batchSectionSelect.value = '';
                batchSectionSelect.disabled = true;
            }
        });
    }

    if (batchModifyTestSetCheckbox && batchTestSetSelect) {
        batchModifyTestSetCheckbox.addEventListener('change', function() {
            if (this.checked) {
                // Test Set 與區段互斥
                if (batchModifySectionCheckbox && batchModifySectionCheckbox.checked) {
                    batchModifySectionCheckbox.checked = false;
                    batchSectionSelect.value = '';
                    batchSectionSelect.disabled = true;
                }

                // 取得當前團隊的所有 Test Sets
                const currentTeam = AppUtils.getCurrentTeam();
                if (!currentTeam || !currentTeam.id) {
                    const msg = window.i18n ? window.i18n.t('errors.pleaseSelectTeam') : '請先選擇團隊';
                    AppUtils.showError(msg);
                    this.checked = false;
                    batchTestSetSelect.disabled = true;
                    return;
                }
                populateBatchTestSetSelect(currentTeam.id);
                batchTestSetSelect.disabled = false;
            } else {
                batchTestSetSelect.value = '';
                batchTestSetSelect.disabled = true;
            }
        });
    }

    const confirmBatchModifyBtn = document.getElementById('confirmTestCaseBatchModifyBtn');
    if (confirmBatchModifyBtn) {
        confirmBatchModifyBtn.addEventListener('click', performTestCaseBatchModify);
    }

    // 監聽表格內的複選框變化
    document.addEventListener('change', function(e) {
        if (e.target.classList.contains('test-case-checkbox')) {
            const recordId = e.target.value;
            if (e.target.checked) {
                selectedTestCases.add(recordId);
            } else {
                selectedTestCases.delete(recordId);
            }
            updateBatchToolbar();
            return;
        }

        if (e.target.classList.contains('section-select-all')) {
            const sectionCard = e.target.closest('.section-card');
            const checkboxes = sectionCard ? sectionCard.querySelectorAll('.test-case-checkbox') : [];
            checkboxes.forEach(cb => {
                cb.checked = e.target.checked;
                const recordId = cb.value;
                if (e.target.checked) {
                    selectedTestCases.add(recordId);
                } else {
                    selectedTestCases.delete(recordId);
                }
            });
            updateBatchToolbar();
        }
    });

    // 支援 Shift-點選 連續多選（同頁範圍）
    document.addEventListener('click', function(e) {
        const cb = e.target;
        if (cb.classList && cb.classList.contains('test-case-checkbox')) {
            const checkboxes = Array.from(document.querySelectorAll('.test-case-checkbox'));
            const currentIndex = checkboxes.indexOf(cb);
            if (currentIndex !== -1) {
                if (e.shiftKey && lastCaseCheckboxIndex !== null && lastCaseCheckboxIndex !== -1) {
                    const start = Math.min(lastCaseCheckboxIndex, currentIndex);
                    const end = Math.max(lastCaseCheckboxIndex, currentIndex);
                    const shouldCheck = cb.checked;
                    for (let i = start; i <= end; i++) {
                        const c = checkboxes[i];
                        if (c.checked !== shouldCheck) c.checked = shouldCheck;
                        const id = c.value;
                        if (shouldCheck) selectedTestCases.add(id); else selectedTestCases.delete(id);
                    }
                    updateBatchToolbar();
                }
                lastCaseCheckboxIndex = currentIndex;
            }
            return;
        }

        const sortableHeader = e.target.closest('.section-table-header th.sortable');
        if (sortableHeader) {
            const table = sortableHeader.closest('.section-table');
            if (!table) return;
            const sectionId = table.getAttribute('data-section-id');
            const datasetField = sortableHeader.getAttribute('data-sort-field');
            const fieldKey = mapAttrToField(datasetField);
            if (sectionId && fieldKey) {
                handleSectionSort(sectionId, fieldKey);
            }
        }
    });

    // 大量新增模式（文字輸入）
    const openBulkBtn = document.getElementById('openBulkCreateBtn');
    if (openBulkBtn) openBulkBtn.addEventListener('click', function(e) {
        e.preventDefault();
        openBulkCreateModal();
    });

    // 大量編輯模式
    const openBulkEditBtn = document.getElementById('openBulkEditBtn');
    if (openBulkEditBtn) openBulkEditBtn.addEventListener('click', function(e) {
        e.preventDefault();
        openBulkEditModal();
    });
    const startBulkBtn = document.getElementById('startBulkCreateBtn');
    if (startBulkBtn) startBulkBtn.addEventListener('click', startBulkTextCreate);
    const confirmBulkBtn = document.getElementById('confirmBulkCreateBtn');
    if (confirmBulkBtn) confirmBulkBtn.addEventListener('click', confirmBulkTextCreate);

    // 文字輸入區鍵盤快捷鍵支援
    const bulkTextInput = document.getElementById('bulkTextInput');
    if (bulkTextInput) {
        bulkTextInput.addEventListener('keydown', function(e) {
            // Ctrl+Enter 或 Cmd+Enter 觸發儲存
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                startBulkTextCreate();
            }
        });
        setupMarkdownHotkeys(bulkTextInput);
    }

    // 儲存按鈕
    document.getElementById('saveTestCaseBtn').addEventListener('click', saveTestCase);

    // 儲存並新增下一筆按鈕
    document.getElementById('saveAndAddNextBtn').addEventListener('click', saveAndAddNext);

    // 複製並新增下一筆按鈕
    document.getElementById('cloneAndAddNextBtn').addEventListener('click', showCloneSelector);
    // 啟用「/」快速搜尋
    setupQuickSearch_TCM();

    // 批次複製 Modal 內部事件
    bindBatchCopyModalEvents();
}

// 初始化「跳至」菜單 - 快速切換 Test Case Sets
async function initJumpToSetMenu() {
    const jumpToSetGroup = document.getElementById('jumpToSetGroup');
    const jumpToSetDropdown = document.getElementById('jumpToSetDropdown');

    if (!jumpToSetGroup || !jumpToSetDropdown || !currentSetId) {
        return; // 如果沒有當前 Set ID，不顯示菜單
    }

    try {
        // 優先從 AppUtils 獲取，若失敗則從 URL 參數獲取
        let teamId = null;
        const activeTeam = window.AppUtils && window.AppUtils.getCurrentTeam ?
                          window.AppUtils.getCurrentTeam() : null;

        if (activeTeam && activeTeam.id) {
            teamId = activeTeam.id;
        } else {
            // 從 URL 參數獲取 team_id
            const urlParams = new URLSearchParams(window.location.search);
            const teamParam = urlParams.get('team_id') || urlParams.get('teamId') || urlParams.get('team');
            if (teamParam) {
                teamId = parseInt(teamParam);
            }
        }

        if (!teamId) {
            return;
        }

        // 獲取所有 Test Case Sets
        const response = await window.AuthClient.fetch(
            `/api/teams/${teamId}/test-case-sets`
        );

        if (!response.ok) {
            return;
        }

        const sets = await response.json();

        // 過濾出不是當前 Set 的所有 Sets
        const otherSets = Array.isArray(sets) ?
                         sets.filter(s => s.id !== currentSetId) :
                         [];

        if (otherSets.length === 0) {
            // 如果沒有其他 Sets，隱藏菜單
            jumpToSetGroup.style.display = 'none';
            return;
        }

        // 清空現有菜單項
        jumpToSetDropdown.innerHTML = '';

        // 添加每個 Set 為菜單項
        otherSets.forEach(set => {
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.className = 'dropdown-item';
            a.href = '#';
            a.style.cursor = 'pointer';

            const icon = set.is_default ? 'star' : 'folder';
            a.innerHTML = `<i class="fas fa-${icon} me-2"></i>${escapeHtml(set.name)}`;

            a.addEventListener('click', (e) => {
                e.preventDefault();
                const currentTeam = window.AppUtils && window.AppUtils.getCurrentTeam ?
                                   window.AppUtils.getCurrentTeam() : null;
                const newTeamId = currentTeam ? currentTeam.id : teamId;
                window.location.href = `/test-case-management?set_id=${set.id}&team_id=${newTeamId}`;
            });

            li.appendChild(a);
            jumpToSetDropdown.appendChild(li);
        });

        // 顯示菜單
        jumpToSetGroup.style.display = 'block';

    } catch (error) {
        console.error('Failed to initialize jump to set menu:', error);
        jumpToSetGroup.style.display = 'none';
    }
}
