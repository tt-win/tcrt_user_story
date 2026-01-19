/* ============================================================
   TEST RUN MANAGEMENT - STATUS
   ============================================================ */

function toggleCustomStatusDropdown(button, configId) {
    const permissions = window._testRunPermissions || testRunPermissions || {};
    if (!permissions.canChangeStatus) {
        showPermissionDenied();
        return;
    }

    const dropdown = document.getElementById('customStatusDropdown');
    const overlay = document.getElementById('statusDropdownOverlay');
    
    // 如果已經打開，則關閉
    if (dropdown.classList.contains('show')) {
        hideCustomStatusDropdown();
        return;
    }
    
    // 找到對應的配置
    const config = testRunConfigs.find(c => c.id === configId);
    if (!config) return;
    
    currentDropdownConfig = config;
    
    // 生成下拉選單內容
    generateCustomStatusDropdownItems(config, dropdown);
    
    // 計算位置
    const rect = button.getBoundingClientRect();
    dropdown.style.left = rect.left + 'px';
    dropdown.style.top = (rect.bottom + 5) + 'px';
    
    // 顯示下拉選單和覆蓋層
    overlay.classList.add('show');
    dropdown.classList.add('show');
}

function hideCustomStatusDropdown() {
    const dropdown = document.getElementById('customStatusDropdown');
    const overlay = document.getElementById('statusDropdownOverlay');
    
    dropdown.classList.remove('show');
    overlay.classList.remove('show');
    currentDropdownConfig = null;
}

function generateCustomStatusDropdownItems(config, dropdown) {
    const currentStatus = config.status;
    
    // 定義狀態轉換規則
    const statusTransitions = {
        'draft': ['active', 'archived'],
        'active': ['completed', 'archived'],  // 進行中不可回到草稿
        'completed': ['archived'],  // 已完成只能歸檔
        'archived': ['active', 'draft']
    };
    
    const availableStatuses = statusTransitions[currentStatus] || [];
    
    let html = '';
    
    availableStatuses.forEach(status => {
        const statusText = getStatusText(status);
        const icon = getStatusIcon(status);
        
        html += `
            <div class="custom-status-dropdown-item" onclick="handleCustomStatusChange('${status}')">
                <i class="${icon} me-2"></i>${statusText}
            </div>
        `;
    });
    
    dropdown.innerHTML = html;
}

function handleCustomStatusChange(newStatus) {
    if (currentDropdownConfig) {
        changeTestRunStatus(currentDropdownConfig.id, newStatus, currentDropdownConfig.name);
        hideCustomStatusDropdown();
    }
}

function generateStatusDropdownItems(config) {
    const currentStatus = config.status;
    
    // 定義狀態轉換規則
    const statusTransitions = {
        'draft': ['active', 'archived'],
        'active': ['completed', 'archived'],  // 進行中不可回到草稿
        'completed': ['archived'],  // 已完成只能歸檔
        'archived': ['active', 'draft']
    };
    
    const availableStatuses = statusTransitions[currentStatus] || [];
    
    let items = [];
    
    availableStatuses.forEach(status => {
        const statusText = getStatusText(status);
        const icon = getStatusIcon(status);
        
        items.push(`
            <li><a class="dropdown-item" href="#" onclick="event.stopPropagation(); changeTestRunStatus(${config.id}, '${status}', '${escapeHtml(config.name)}')">
                <i class="${icon} me-2"></i>${statusText}
            </a></li>
        `);
    });
    
    return items.join('');
}

function getStatusIcon(status) {
    const icons = {
        'active': 'fas fa-play text-primary',
        'completed': 'fas fa-check text-success',
        'draft': 'fas fa-edit text-warning',
        'archived': 'fas fa-archive text-secondary'
    };
    return icons[status] || 'fas fa-question text-muted';
}

async function changeTestRunStatus(configId, newStatus, configName) {
    // 直接執行狀態變更，不需要輸入原因
    const permissions = window._testRunPermissions || testRunPermissions || {};
    if (!permissions.canChangeStatus) {
        showPermissionDenied();
        return;
    }
    
    try {
        const teamId = currentTeamId; // 使用全域變數
        const response = await window.AuthClient.fetch(`/api/teams/${teamId}/test-run-configs/${configId}/status`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                status: newStatus
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '狀態變更失敗');
        }
        
        const updatedConfig = await response.json();
        
        // 顯示成功訊息 - 使用 fallback 參數確保有預設文字
        const successMsg = (window.i18n && window.i18n.isReady()) ? 
            window.i18n.t('testRun.statusChangedSuccess', {name: configName, status: getStatusText(newStatus)}, 
                         `Test Run "${configName}" 狀態已變更為 ${getStatusText(newStatus)}`) : 
            `Test Run "${configName}" 狀態已變更為 ${getStatusText(newStatus)}`;
        
        AppUtils.showSuccess(successMsg);
        
        // 重新載入 Test Run 列表
        await loadTestRunConfigs();
        
    } catch (error) {
        console.error('Change status error:', error);
        const errorMsg = (window.i18n && window.i18n.isReady()) ? 
            window.i18n.t('testRun.statusChangeFailed', {}, '狀態變更失敗：' + error.message) : 
            '狀態變更失敗：' + error.message;
        
        AppUtils.showError(errorMsg);
    }
}

function refreshStatusTexts() {
    // 僅做文案重翻譯，不重打 API，避免 teams/null 之類錯誤
    try {
        if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
            window.i18n.retranslate(document);
        }
    } catch (e) {
        console.warn('refreshStatusTexts: retranslate failed', e);
    }
    
    // 同步更新已開啟的詳情視窗中的狀態徽章文案
    const detailModal = document.getElementById('configDetailModal');
    if (detailModal && detailModal.classList.contains('show')) {
        const statusBadges = detailModal.querySelectorAll('.status-badge');
        statusBadges.forEach(badge => {
            const statusClass = badge.className.match(/status-(\w+)/);
            if (statusClass && statusClass[1]) {
                const status = statusClass[1];
                badge.textContent = getStatusText(status);
            }
        });
    }
}
