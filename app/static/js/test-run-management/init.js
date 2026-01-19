/* ============================================================
   TEST RUN MANAGEMENT - INIT
   ============================================================ */

document.addEventListener('DOMContentLoaded', async function() {
    await applyTestRunManagementPermissions();
    if (window.AuthClient && typeof window.AuthClient.on === 'function') {
        window.AuthClient.on('authReady', async () => {
            await applyTestRunManagementPermissions();
            try {
                const activeFilter = document.querySelector('input[name="statusFilter"]:checked');
                const filterValue = activeFilter ? activeFilter.value : 'all';
                currentStatusFilter = filterValue;
                renderTestRunOverview(filterValue);
            } catch (_) {}
        });
    }
    // 監聽全域 team 變更事件，隨時更新 URL 的 team_id
    try {
        window.addEventListener('teamChanged', function(e) {
            const newTeam = e && e.detail && e.detail.team;
            if (newTeam && newTeam.id) {
                ensureTeamIdInUrl_TRM(newTeam.id);
            }
        });
    } catch (_) {}

    initializePage();
    bindEventListeners();

    // 綁定 i18n 事件（僅重翻譯，不觸發資料重載）
    if (!eventsBound) {
        document.addEventListener('i18nReady', onI18nEventOnce);
        document.addEventListener('languageChanged', onI18nEvent);
        // 處理 bfcache 返回
        window.addEventListener('pageshow', onPageShow);
        eventsBound = true;
    }

    // DOM 就緒且 i18n 已就緒時，僅重翻譯
    if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
        refreshStatusTexts();
    }
});

function onI18nEventOnce() {
    // i18n 初始化完成後，不重打 API，僅更新文案
    refreshStatusTexts();
}

function onI18nEvent() {
    // 語言切換後，不重打 API，僅更新文案
    refreshStatusTexts();
}

function onPageShow(event) {
    // bfcache 或一般顯示時，確認 teamId 狀態
    const latestTeamId = AppUtils.getCurrentTeamId ? AppUtils.getCurrentTeamId() : (AppUtils.getCurrentTeam()?.id ?? null);
    if (latestTeamId && latestTeamId !== currentTeamId) {
        currentTeamId = latestTeamId;
        teamIdReady = true;
        // 只有在尚未載入過資料時才載入，避免返回頁面時不必要的 API 呼叫
        if (!dataLoadedOnce) {
            loadTestRunConfigs();
        } else {
            refreshStatusTexts();
        }
    } else if (!latestTeamId) {
        teamIdReady = false;
        console.warn('pageshow: Skip loading due to missing teamId');
        // 可選：顯示需選擇團隊的提示
    } else {
        // teamId 未變更
        refreshStatusTexts();
    }
}

function initializePage() {
    // 以 AppUtils.getCurrentTeamId 為單一資料源
    currentTeamId = (typeof AppUtils.getCurrentTeamId === 'function')
        ? AppUtils.getCurrentTeamId()
        : (AppUtils.getCurrentTeam()?.id ?? null);

    // 確保網址列包含 team_id（不重新載入頁面）
    try { if (currentTeamId) ensureTeamIdInUrl_TRM(currentTeamId); } catch (_) {}

    if (currentTeamId) {
        teamIdReady = true;
        loadTestRunConfigs();
    } else {
        teamIdReady = false;
        console.warn('initializePage: teamId not ready, skip loading');
        // 不打 API；可選：顯示需先選擇團隊的 UI 狀態
        showNoConfigs();
    }
}

function bindEventListeners() {
    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => {
        if (!teamIdReady) {
            // 嘗試延遲取得 teamId
            const latestTeamId = (typeof AppUtils.getCurrentTeamId === 'function')
                ? AppUtils.getCurrentTeamId()
                : (AppUtils.getCurrentTeam()?.id ?? null);
            if (latestTeamId) {
                currentTeamId = latestTeamId;
                teamIdReady = true;
            }
        }
        if (teamIdReady) {
            loadTestRunConfigs();
        } else {
            console.warn('Refresh skipped: teamId not ready');
            AppUtils.showWarning && AppUtils.showWarning((window.i18n && window.i18n.isReady()) ? window.i18n.t('errors.teamNotSelected') : '請先選擇團隊');
        }
    });
    
    document.addEventListener('click', function(e) {
        const addCard = e.target.closest('.add-test-run-card');
        if (addCard) {
            const perms = window._testRunPermissions || testRunPermissions || {};
            if (!perms.canCreate) {
                showPermissionDenied();
                return;
            }
            const cardType = addCard.dataset.cardType || 'run';
            if (cardType === 'set') {
                openTestRunSetFormModal();
            } else if (cardType === 'adhoc') {
                openAdHocRunModal();
            } else {
                openConfigFormModal();
            }
        }
    });
    
    const saveBtn = document.getElementById('saveConfigBtn');
    if (saveBtn) saveBtn.addEventListener('click', handleSaveConfig);

    const saveSetBtn = document.getElementById('saveTestRunSetBtn');
    if (saveSetBtn) saveSetBtn.addEventListener('click', handleSaveTestRunSet);

    const confirmAddExistingBtn = document.getElementById('confirmAddExistingToSetBtn');
    if (confirmAddExistingBtn) confirmAddExistingBtn.addEventListener('click', confirmAddExistingToSet);

    const setReportGenerateBtn = document.getElementById('setReportGenerateHtmlBtn');
    if (setReportGenerateBtn) setReportGenerateBtn.addEventListener('click', generateTestRunSetHtmlReport);
    
    // 狀態過濾事件監聽器
    document.querySelectorAll('input[name="statusFilter"]').forEach(radio => {
        radio.addEventListener('change', function() {
            if (this.checked) {
                const filterValue = this.value;
                currentStatusFilter = filterValue;
                renderTestRunOverview(filterValue);
            }
        });
    });
}
