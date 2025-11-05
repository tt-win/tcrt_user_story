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
    document.getElementById('larkPreviewResult').innerHTML = '';
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
            throw new Error('獲取團隊列表失敗');
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
        AppUtils.showError('載入團隊列表失敗');
    }
}

/**
 * 預覽 Lark 表格
 */
async function previewLarkTable() {
    try {
        const larkUrl = document.getElementById('larkUrlInput').value.trim();
        
        if (!larkUrl) {
            AppUtils.showError('請輸入 Lark URL');
            return;
        }
        
        // 驗證 URL 格式
        if (!larkUrl.includes('larksuite.com')) {
            AppUtils.showError('URL 格式無效，請輸入有效的 Lark 連結');
            return;
        }
        
        // 顯示加載狀態
        const resultDiv = document.getElementById('larkPreviewResult');
        resultDiv.innerHTML = '<small class="text-info"><i class="fas fa-spinner fa-spin me-1"></i>正在預覽...</small>';
        
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
            throw new Error(error.detail || '預覽失敗');
        }
        
        const data = await response.json();
        
        // 保存預覽數據
        usmImportData.previewData = data;
        usmImportData.larkUrl = larkUrl;
        
        // 顯示預覽結果
        showPreviewResult(data);
        
    } catch (error) {
        console.error('Preview error:', error);
        const resultDiv = document.getElementById('larkPreviewResult');
        resultDiv.innerHTML = `<small class="text-danger"><i class="fas fa-times-circle me-1"></i>${error.message}</small>`;
    }
}

/**
 * 顯示預覽結果
 */
function showPreviewResult(data) {
    const resultDiv = document.getElementById('larkPreviewResult');
    
    let html = `
        <div class="alert alert-success" role="alert">
            <h6 class="alert-heading">
                <i class="fas fa-check-circle me-2"></i>預覽成功
            </h6>
            <ul class="mb-0 small">
                <li>總記錄數: <strong>${data.total_records}</strong></li>
                <li>預覽記錄: <strong>${data.preview_records.length}</strong></li>
            </ul>
        </div>
        <div class="alert alert-info" role="alert">
            <h6 class="alert-heading">
                <i class="fas fa-info-circle me-2"></i>數據結構
            </h6>
            <small>
    `;
    
    // 顯示字段映射
    if (data.structure) {
        Object.entries(data.structure).forEach(([larkField, dbField]) => {
            html += `<div><strong>${larkField}</strong> → ${dbField}</div>`;
        });
    }
    
    html += '</small></div>';
    
    // 顯示示例記錄
    if (data.preview_records && data.preview_records.length > 0) {
        html += '<div class="alert alert-secondary" role="alert"><h6>示例記錄</h6><small><ul class="mb-0">';
        
        data.preview_records.slice(0, 3).forEach((record, index) => {
            const title = record['Features'] || '(無標題)';
            html += `<li>#${index + 1}: ${title}</li>`;
        });
        
        if (data.preview_records.length > 3) {
            html += `<li>... 及 ${data.preview_records.length - 3} 條記錄</li>`;
        }
        
        html += '</ul></small></div>';
    }
    
    resultDiv.innerHTML = html;
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
            AppUtils.showError('請輸入 Lark URL');
            return;
        }
        
        if (!rootName) {
            AppUtils.showError('請輸入根節點名稱');
            return;
        }
        
        if (!teamId || teamId <= 0) {
            AppUtils.showError('請選擇目標團隊');
            return;
        }
        
        if (!usmImportData.previewData) {
            AppUtils.showError('請先預覽數據');
            return;
        }
        
        // 確認匯入
        const confirmed = await AppUtils.showConfirm(
            `確認要匯入 ${usmImportData.previewData.total_records} 條記錄到 User Story Map 嗎？\n\n根節點名稱: ${rootName}`
        );
        
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
            throw new Error(result.message || '匯入失敗');
        }
        
        if (result.success) {
            AppUtils.showSuccess(`匯入成功！已建立 User Story Map: ${result.map_id}`);
            
            // 刷新頁面或導向到新建的 map
            if (result.map_id) {
                // 導向到新建的 USM
                window.location.href = `/user-story-map/${result.map_id}`;
            } else {
                // 刷新頁面
                location.reload();
            }
        } else {
            AppUtils.showError(result.message || '匯入失敗');
        }
        
    } catch (error) {
        console.error('Import error:', error);
        AppUtils.showError(`匯入失敗: ${error.message}`);
    }
}

// 在頁面加載時初始化
document.addEventListener('DOMContentLoaded', () => {
    // USM 匯入功能已在 initTeamManagement 中初始化
});
