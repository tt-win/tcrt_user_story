/* Test Run Execution - Init */
window.addEventListener('storage', (event) => {
    if (event.key !== TEST_CASE_UPDATE_EVENT_KEY || !event.newValue) return;
    try {
        const data = JSON.parse(event.newValue);
        applyExternalTestCaseUpdate(data);
    } catch (err) {
        console.debug('忽略無法解析的 test case 更新事件:', err);
    }
});

// 頁面初始化
document.addEventListener('DOMContentLoaded', async function() {
    await applyTestRunExecutionPermissions();
    if (window.AuthClient && typeof window.AuthClient.on === 'function') {
        try {
            window.AuthClient.on('authReady', async () => {
                await applyTestRunExecutionPermissions();
                if (testRunConfig) {
                    updateControlButtons(testRunConfig.status);
                    renderTestRunItems();
                }
            });
        } catch (_) {}
    }
    // 從 URL 參數取得必要參數
    const urlParams = new URLSearchParams(window.location.search);
    currentConfigId = parseInt(urlParams.get('config_id'));
    const teamParam = urlParams.get('team_id') || urlParams.get('teamId') || urlParams.get('team');
    window.__PENDING_TC_FROM_URL__ = urlParams.get('tc') || urlParams.get('test_case_number') || null;

    if (!currentConfigId) {
        AppUtils.showError(treTranslate('testRun.missingConfigId', '缺少測試執行配置 ID'));
        window.location.href = '/test-run-management';
        return;
    }

    // 若 URL 有 team_id 且目前尚未設定 current team，先寫入
    try {
        const cur = AppUtils.getCurrentTeam && AppUtils.getCurrentTeam();
        if (teamParam && (!cur || !cur.id) && AppUtils.setCurrentTeam) {
            const parsedTeam = parseInt(teamParam);
            if (!isNaN(parsedTeam)) AppUtils.setCurrentTeam({ id: parsedTeam });
        }
    } catch (_) {}

    initializePage();
    bindEventListeners();
    bindBugTicketEvents();
    setupQuickSearch_TR();
    // 在加載配置後初始化跳至菜單
    setTimeout(() => {
        if (testRunConfig && testRunConfig.set_id) {
            initJumpToTestRunMenu();
        }
    }, 500);

    // 確保 i18n 系統準備好後立即套用翻譯
    setTimeout(() => {
        if (typeof applyExecutionFilterTranslations === 'function') {
            applyExecutionFilterTranslations();
        }
    }, 100);
    // 左下角熱鍵提示
    if (!document.getElementById('quickSearchHint')) {
        const hint = document.createElement('div');
        hint.id = 'quickSearchHint';
        hint.className = 'position-fixed';
        hint.style.cssText = 'left:12px; bottom:12px; z-index:1040; opacity:0.85; pointer-events:none;';
        const label = window.i18n && window.i18n.isReady() ? (window.i18n.t('hotkeys.quickSearch') || 'Press / for quick search') : 'Press / for quick search';
        hint.innerHTML = `<span class="badge bg-secondary-subtle text-secondary border" style="--bs-bg-opacity:.65;">${label}</span>`;
        document.body.appendChild(hint);
        // i18n 準備完成時同步更新
        document.addEventListener('i18nReady', () => {
            const text = window.i18n ? (window.i18n.t('hotkeys.quickSearch') || 'Press / for quick search') : 'Press / for quick search';
            const badge = document.querySelector('#quickSearchHint .badge');
            if (badge) badge.textContent = text;
            // 同時更新執行過濾器的翻譯
            if (typeof applyExecutionFilterTranslations === 'function') {
                applyExecutionFilterTranslations();
            }
        });
        document.addEventListener('languageChanged', () => {
            const text = window.i18n ? (window.i18n.t('hotkeys.quickSearch') || 'Press / for quick search') : 'Press / for quick search';
            const badge = document.querySelector('#quickSearchHint .badge');
            if (badge) badge.textContent = text;
            // 同時更新執行過濾器的翻譯
            if (typeof applyExecutionFilterTranslations === 'function') {
                applyExecutionFilterTranslations();
            }
        });
    }
});

function initializePage() {
    // 監聽全域 team 變更事件，隨時更新 URL 的 team_id
    try {
        window.addEventListener('teamChanged', function(e) {
            const newTeam = e && e.detail && e.detail.team;
            if (newTeam && newTeam.id) {
                // 更新目前使用中的 teamId，確保後續快取用正確的 key 寫入
                currentTeamId = newTeam.id;
                ensureTeamIdInUrl_TRE(newTeam.id);
                if (executionFilterAssigneeSelector) {
                    executionFilterAssigneeSelector.options.teamId = currentTeamId;
                    try { executionFilterAssigneeSelector.refresh(); } catch (_) {}
                }
            }
        });
    } catch (_) {}
    // 取得目前團隊 ID（與管理頁一致），無則暫用 1
    currentTeamId = AppUtils.getCurrentTeam()?.id;
    if (!currentTeamId) {
        currentTeamId = 1;
    }
    // 確保網址列包含 team_id（不重新載入頁面）
    try { ensureTeamIdInUrl_TRE(currentTeamId); } catch (_) {}

    initializeExecutionFilters();

    itemDetailModal = new bootstrap.Modal(document.getElementById('itemDetailModal'));
    confirmModal = new bootstrap.Modal(document.getElementById('confirmModal'));
    restartModal = new bootstrap.Modal(document.getElementById('restartModal'));
    batchModifyModal = new bootstrap.Modal(document.getElementById('batchModifyModal'));
    
    // 綁定重新執行確認按鈕事件
    document.getElementById('confirmRestartBtn').addEventListener('click', handleRestartConfirm);
    
    // 綁定批次修改相關事件
    document.getElementById('confirmBatchModifyBtn').addEventListener('click', handleBatchModifyConfirm);
    document.getElementById('batchModifyAssignee').addEventListener('change', toggleBatchAssigneeInput);
    document.getElementById('batchModifyResult').addEventListener('change', toggleBatchResultSelect);
    document.getElementById('batchModifyComment').addEventListener('change', toggleBatchCommentInput);
    
    // 初始化 AssigneeSelector 元件（批次修改模態框中的）
    if (window.AssigneeSelector && currentTeamId) {
        // 為批次修改的 input 初始化 AssigneeSelector
        const batchInput = document.getElementById('batchAssigneeInput');
        if (batchInput && batchInput.dataset.assigneeSelector !== undefined) {
            const options = {
                teamId: currentTeamId,
                allowCustomValue: true,  // 批次修改允許自定義值
                onSelect: () => {}
            };
            
            if (batchInput._assigneeSelector) {
                batchInput._assigneeSelector.destroy();
            }
            batchInput._assigneeSelector = new AssigneeSelector(batchInput, options);
        }
    }
    
    loadTestRunConfig();
}


function bindEventListeners() {
    const permissions = getTrePermissions();

    const refreshBtnEl = document.getElementById('refreshBtn');
    if (refreshBtnEl) {
        refreshBtnEl.addEventListener('click', async () => {
            const refreshBtn = document.getElementById('refreshBtn');
            const originalHTML = refreshBtn.innerHTML;

            refreshBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status"></span>${window.i18n ? window.i18n.t('common.refresh') : '重新整理'}`;
            refreshBtn.disabled = true;

            try {
                try {
                    const TEST_CASES_CACHE_KEY = 'test_cases_list_cache_v1';
                    const keys = Object.keys(localStorage);
                    keys.forEach(key => {
                        if (key.startsWith(TEST_CASES_CACHE_KEY)) {
                            localStorage.removeItem(key);
                        }
                    });
                } catch (e) {
                    console.debug('清除 Test Case Management 快取失敗:', e);
                }

                try {
                    const keys = Object.keys(localStorage);
                    keys.forEach(key => {
                        if (key.startsWith('tr_exec_tc_cache_v1')) {
                            localStorage.removeItem(key);
                        }
                    });
                } catch (e) {
                    console.debug('清除個別快取失敗:', e);
                }

                await loadTestRunItemsWithoutLoading();
                await updateStatistics();
                try {
                    await refreshBugTicketsStatus();
                } catch (e) {
                    console.debug('更新 Bug Tickets 狀態失敗:', e);
                }
                try {
                    const modalEl = document.getElementById('testCaseDetailModal');
                    const isShown = modalEl && modalEl.classList.contains('show');
                    if (isShown && currentDetailTestCase && currentDetailTestCase.test_case_number) {
                        renderResultHistoryTimeline({ test_case_number: currentDetailTestCase.test_case_number });
                    }
                } catch (_) {}
                try {
                    const bugModalEl = document.getElementById('bugTicketsSummaryModal');
                    const isBugModalShown = bugModalEl && bugModalEl.classList.contains('show');
                    if (isBugModalShown) {
                        await loadBugTicketsSummary();
                    }
                } catch (_) {}

                AppUtils.showSuccess(window.i18n ? window.i18n.t('messages.dataReloaded') : '資料已重新載入');

            } finally {
                refreshBtn.innerHTML = originalHTML;
                refreshBtn.disabled = false;
            }
        });
    }

    const startBtn = document.getElementById('startBtn');
    if (startBtn) {
        startBtn.addEventListener('click', () => {
            if (!getTrePermissions().canStart) {
                showExecutionPermissionDenied();
                return;
            }
            confirmStatusChange('active', treTranslate('testRun.startExecutionConfirm', '開始執行此 Test Run？'));
        });
    }

    const completeBtn = document.getElementById('completeBtn');
    if (completeBtn) {
        completeBtn.addEventListener('click', () => {
            if (!getTrePermissions().canComplete) {
                showExecutionPermissionDenied();
                return;
            }
            confirmStatusChange('completed', treTranslate('testRun.completeExecutionConfirm', '結束此 Test Run？結束後將無法再修改測試結果。'));
        });
    }

    const restartBtn = document.getElementById('restartBtn');
    if (restartBtn) {
        restartBtn.addEventListener('click', () => {
            if (!getTrePermissions().canRestart) {
                showExecutionPermissionDenied();
                return;
            }
            showRestartModal();
        });
    }

    const selectAllCheckbox = document.getElementById('selectAllItemsCheckbox');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', toggleSelectAllItems);
    }

    const batchModifyBtn = document.getElementById('batchModifyBtn');
    if (batchModifyBtn) {
        batchModifyBtn.addEventListener('click', () => {
            if (!getTrePermissions().canBatchModify) {
                showExecutionPermissionDenied();
                return;
            }
            showBatchModifyModal();
        });
    }

    const batchDeleteBtn = document.getElementById('batchDeleteBtn');
    if (batchDeleteBtn) {
        batchDeleteBtn.addEventListener('click', () => {
            if (!getTrePermissions().canBatchDelete) {
                showExecutionPermissionDenied();
                return;
            }
            showBatchDeleteConfirm();
        });
    }

    const clearSelectionExecBtn = document.getElementById('clearSelectionExecBtn');
    if (clearSelectionExecBtn) {
        clearSelectionExecBtn.addEventListener('click', clearSelectedItems);
    }

    document.addEventListener('change', function(e) {
        if (e.target && e.target.classList && e.target.classList.contains('test-run-item-checkbox')) {
            if (!(getTrePermissions().canBatchModify || getTrePermissions().canBatchDelete)) {
                e.target.checked = false;
                showExecutionPermissionDenied();
                updateItemSelectionUI();
                return;
            }
            const itemId = parseInt(e.target.value);
            if (e.target.checked) {
                selectedItems.add(itemId);
            } else {
                selectedItems.delete(itemId);
            }
            updateItemSelectionUI();
        }
    });

    document.addEventListener('click', function(e) {
        const cb = e.target;
        if (!cb.classList || !cb.classList.contains('test-run-item-checkbox')) return;
        if (!(getTrePermissions().canBatchModify || getTrePermissions().canBatchDelete)) {
            cb.checked = false;
            showExecutionPermissionDenied();
            updateItemSelectionUI();
            return;
        }

        const checkboxes = Array.from(document.querySelectorAll('.test-run-item-checkbox'));
        const currentIndex = checkboxes.indexOf(cb);
        if (currentIndex === -1) return;

        if (e.shiftKey && lastItemCheckboxIndex !== null && lastItemCheckboxIndex !== -1) {
            const start = Math.min(lastItemCheckboxIndex, currentIndex);
            const end = Math.max(lastItemCheckboxIndex, currentIndex);
            const shouldCheck = cb.checked;

            for (let i = start; i <= end; i++) {
                const c = checkboxes[i];
                if (c.checked !== shouldCheck) {
                    c.checked = shouldCheck;
                }
                const id = parseInt(c.value);
                if (shouldCheck) {
                    selectedItems.add(id);
                } else {
                    selectedItems.delete(id);
                }
            }
            updateItemSelectionUI();
        }

        lastItemCheckboxIndex = currentIndex;
    });
}
