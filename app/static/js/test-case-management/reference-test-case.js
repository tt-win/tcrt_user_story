/* ============================================================
   TEST CASE MANAGEMENT - REFERENCE TEST CASE
   ============================================================ */

/* ============================================================
   23. 參考測試案例 (Reference Test Case)
   ============================================================ */

/**
 * 開啟參考測試案例彈窗
 */
function openReferenceTestCasePopup() {
    try {
        const currentTeam = AppUtils.getCurrentTeam();
        if (!currentTeam || !currentTeam.id) {
            const teamErrorMsg = window.i18n ?
                window.i18n.t('errors.noTeamSelected', {}, '請先選擇團隊') :
                '請先選擇團隊';
            showError(teamErrorMsg);
            return;
        }

        const popupUrl = `/test-case-reference?team_id=${currentTeam.id}`;
        const popupFeatures = 'width=1400,height=900,scrollbars=yes,resizable=yes,menubar=no,toolbar=no,location=no,status=no';
        const popupWindow = window.open(popupUrl, 'referenceTestCase', popupFeatures);

        if (!popupWindow) {
            const popupErrorMsg = window.i18n ?
                window.i18n.t('errors.popupBlocked', {}, '彈窗被阻擋，請允許彈窗後再試') :
                '彈窗被阻擋，請允許彈窗後再試';
            showError(popupErrorMsg);
            return;
        }

        // 焦點到彈窗
        if (popupWindow.focus) {
            popupWindow.focus();
        }

    } catch (error) {
        console.error('開啟參考測試案例彈窗失敗:', error);
        const openErrorMsg = window.i18n ?
            window.i18n.t('testCase.referenceTestCaseError', {}, '開啟參考測試案例失敗') :
            '開啟參考測試案例失敗';
        showError(openErrorMsg + ': ' + error.message);
    }
}
