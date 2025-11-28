/**
 * USM 匯入功能 JavaScript
 * 處理從 Lark 匯入 User Story Map 的前端邏輯
 */

let usmImportData = {
    larkUrl: '',
    rootName: '',
    teamId: null,
    previewData: null
};

/**
 * 打開 USM 匯入模態框
 */
function openUSMImportModal() {
    // 重設表單
    document.getElementById('usmImportForm').reset();
    const countSpan = document.getElementById('larkRecordCount');
    if (countSpan) {
        countSpan.style.display = 'none';
    }
    usmImportData = {
        larkUrl: '',
        rootName: '',
        teamId: null,
        previewData: null
    };
    
    // 填充團隊選擇下拉選單
    populateTeamSelect();
    
    // 打開模態框
    const modal = new bootstrap.Modal(document.getElementById('usmImportModal'));
    modal.show();
}

/**
 * 填充團隊選擇下拉選單
 */
async function populateTeamSelect() {
    try {
        const response = await window.AuthClient.fetch('/api/teams', {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) {
            throw new Error(window.i18n ? window.i18n.t('usmImport.loadTeamsFailed') : '獲取團隊列表失敗');
        }
        
        const teams = await response.json();
        const select = document.getElementById('targetTeamSelect');
        
        // 清空現有選項（除了第一個）
        while (select.options.length > 1) {
            select.remove(1);
        }
        
        // 添加團隊選項
        teams.forEach(team => {
            const option = document.createElement('option');
            option.value = team.id;
            option.textContent = team.name;
            select.appendChild(option);
        });
        
    } catch (error) {
        console.error('Error loading teams:', error);
        AppUtils.showError(window.i18n ? window.i18n.t('usmImport.loadTeamsFailed') : '載入團隊列表失敗');
    }
}

/**
 * 預處理 Lark 表格
 */
async function preprocessLarkTable() {
    try {
        const larkUrl = document.getElementById('larkUrlInput').value.trim();
        
        if (!larkUrl) {
            AppUtils.showError(window.i18n ? window.i18n.t('usmImport.enterLarkUrl') : '請輸入 Lark URL');
            return;
        }
        
        // 驗證 URL 格式
        if (!larkUrl.includes('larksuite.com')) {
            AppUtils.showError(window.i18n ? window.i18n.t('usmImport.invalidUrl') : 'URL 格式無效，請輸入有效的 Lark 連結');
            return;
        }
        
        // 顯示加載狀態
        const countSpan = document.getElementById('larkRecordCount');
        countSpan.style.display = 'inline';
        countSpan.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>' + (window.i18n ? window.i18n.t('usmImport.preprocessing') : '預處理中...');

        // 調用預覽 API
        const response = await window.AuthClient.fetch(
            `/api/usm-import/lark-preview?lark_url=${encodeURIComponent(larkUrl)}`,
            {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || (window.i18n ? window.i18n.t('usmImport.preprocessFailed') : '預處理失敗'));
        }

        const data = await response.json();

        // 保存預覽數據
        usmImportData.previewData = data;
        usmImportData.larkUrl = larkUrl;

        // 顯示總筆數
        const totalText = window.i18n ? window.i18n.t('usmImport.totalRecords', { count: data.total_records }) : `共 ${data.total_records} 筆記錄`;
        countSpan.innerHTML = totalText;
        
    } catch (error) {
        console.error('Preprocess error:', error);
        const countSpan = document.getElementById('larkRecordCount');
        countSpan.style.display = 'none';
        AppUtils.showError((window.i18n ? window.i18n.t('usmImport.preprocessFailed') : '預處理失敗') + `: ${error.message}`);
    }
}



/**
 * 確認並開始匯入
 */
async function confirmUSMImport() {
    try {
        // 驗證所有必填欄位
        const larkUrl = document.getElementById('larkUrlInput').value.trim();
        const rootName = document.getElementById('rootNodeNameInput').value.trim();
        const teamId = parseInt(document.getElementById('targetTeamSelect').value);
        
        if (!larkUrl) {
            AppUtils.showError(window.i18n ? window.i18n.t('usmImport.enterLarkUrl') : '請輸入 Lark URL');
            return;
        }
        
        if (!rootName) {
            AppUtils.showError(window.i18n ? window.i18n.t('usmImport.enterRootNodeName') : '請輸入根節點名稱');
            return;
        }
        
        if (!teamId || teamId <= 0) {
            AppUtils.showError(window.i18n ? window.i18n.t('usmImport.selectTargetTeam') : '請選擇目標團隊');
            return;
        }
        
        if (!usmImportData.previewData) {
            AppUtils.showError(window.i18n ? window.i18n.t('usmImport.preprocessFirst') : '請先預處理數據');
            return;
        }
        
        // 確認匯入
        const confirmText = window.i18n ? 
            window.i18n.t('usmImport.confirmImport', { 
                count: usmImportData.previewData.total_records, 
                rootName: rootName 
            }) : 
            `確認要匯入 ${usmImportData.previewData.total_records} 條記錄到 User Story Map 嗎？\n\n根節點名稱: ${rootName}`;
        const confirmed = await AppUtils.showConfirm(confirmText);
        
        if (!confirmed) {
            return;
        }
        
        // 關閉模態框
        const modal = bootstrap.Modal.getInstance(document.getElementById('usmImportModal'));
        modal.hide();
        
        // 顯示加載狀態
        AppUtils.showLoading();
        
        // 調用匯入 API
        const response = await window.AuthClient.fetch('/api/usm-import/import-from-lark', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                lark_url: larkUrl,
                root_name: rootName,
                team_id: teamId
            })
        });
        
        const result = await response.json();
        
        if (!response.ok) {
            throw new Error(result.message || (window.i18n ? window.i18n.t('usmImport.importFailed') : '匯入失敗'));
        }
        
        if (result.success) {
            const successText = window.i18n ? 
            window.i18n.t('usmImport.importSuccess', { mapId: result.map_id }) : 
            `匯入成功！已建立 User Story Map: ${result.map_id}`;
        AppUtils.showSuccess(successText);
            
            // 刷新頁面或導向到新建的 map
            if (result.map_id) {
                // 導向到新建的 USM - 需要 team_id 和 map_id
                const teamId = parseInt(document.getElementById('targetTeamSelect').value);
                window.location.href = `/user-story-map/${teamId}/${result.map_id}`;
            } else {
                // 刷新頁面
                location.reload();
            }
        } else {
            AppUtils.showError(result.message || (window.i18n ? window.i18n.t('usmImport.importFailed') : '匯入失敗'));
        }
        
    } catch (error) {
        console.error('Import error:', error);
        AppUtils.showError((window.i18n ? window.i18n.t('usmImport.importFailed') : '匯入失敗') + `: ${error.message}`);
    }
}

// 在頁面加載時初始化
document.addEventListener('DOMContentLoaded', () => {
    // USM 匯入功能已在 initTeamManagement 中初始化
});
