/* ============================================================
   TEST RUN MANAGEMENT - DATA
   ============================================================ */

async function loadTestRunConfigs() {
    try {
        // 防護：若 teamId 尚未就緒，嘗試回填，否則中止
        if (!currentTeamId) {
            const latestTeamId = (typeof AppUtils.getCurrentTeamId === 'function')
                ? AppUtils.getCurrentTeamId()
                : (AppUtils.getCurrentTeam()?.id ?? null);
            if (latestTeamId) {
                currentTeamId = latestTeamId;
                teamIdReady = true;
            }
        }
        if (!currentTeamId) {
            console.warn('loadTestRunConfigs: Skip loading due to missing teamId');
            showNoConfigs();
            return;
        }

        // 預先載入 Test Case Set 列表
        await loadTestCaseSets();

        showLoading();
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/overview?include_archived=true`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const payload = await response.json();
        testRunSets = Array.isArray(payload.sets) ? payload.sets : [];
        unassignedTestRuns = Array.isArray(payload.unassigned) ? payload.unassigned : [];
        
        // Load Ad-hoc Runs
        try {
            const adhocResponse = await window.AuthClient.fetch(`/api/adhoc-runs/team/${currentTeamId}`);
            if (adhocResponse.ok) {
                const adhocRuns = await adhocResponse.json();
                renderAdHocRuns(adhocRuns);
            } else {
                renderAdHocRuns([]);
            }
        } catch (e) {
            console.error('Failed to load adhoc runs', e);
            renderAdHocRuns([]);
        }

        rebuildTestRunConfigIndex();
        dataLoadedOnce = true;
        renderTestRunOverview(currentStatusFilter);
        await refreshCurrentSetDetail();
    } catch (error) {
        console.error('Failed to load Test Run configurations:', error);
        const errorMsg = window.i18n ? window.i18n.t('messages.loadConfigsFailed') : '載入失敗';
        AppUtils.showError(errorMsg + '：' + error.message);
        showNoConfigs();
    } finally {
        hideLoading();
        
        // 檢查是否有從 Test Case Set 預選的 Test Cases
        const preselectedCaseIds = sessionStorage.getItem('testRunSelectedCaseIds');
        const setId = sessionStorage.getItem('testRunSetId');
        if (preselectedCaseIds && setId) {
          // 保存預選信息到 window，稍後在建立配置後使用
          window._preselectedCaseIdsFromSet = preselectedCaseIds;
          window._testCaseSetIdSource = parseInt(setId);
          currentScopeSetIdsForCaseSelection = [parseInt(setId)];
          currentSetIdForCaseSelection = parseInt(setId);
          // 打開 Test Run Set 建立表單（正規流程的第一步）
          openConfigFormModal();
          // 清除 sessionStorage，避免重複使用
          sessionStorage.removeItem('testRunSelectedCaseIds');
          sessionStorage.removeItem('testRunSetId');
        }
    }
}

function rebuildTestRunConfigIndex() {
    const flattened = [];
    (testRunSets || []).forEach(set => {
        (set.test_runs || []).forEach(run => {
            flattened.push({
                ...run,
                set_id: run.set_id ?? set.id,
                set_name: run.set_name ?? set.name,
            });
        });
    });
    (unassignedTestRuns || []).forEach(run => {
        flattened.push({
            ...run,
            set_id: run.set_id ?? null,
            set_name: run.set_name ?? null,
        });
    });
    testRunConfigs = flattened;
}

function filterTestRunsByStatus(runs, filterStatus) {
    if (!runs) return [];
    if (!filterStatus || filterStatus === 'all') return [...runs];
    return runs.filter(item => (item.status || '').toLowerCase() === filterStatus.toLowerCase());
}
