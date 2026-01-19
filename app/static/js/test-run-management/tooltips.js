/* ============================================================
   TEST RUN MANAGEMENT - TOOLTIP
   ============================================================ */

function getOrCreateJiraTooltip() {
    let tooltip = document.getElementById('tcg-tooltip-content');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'tcg-tooltip-content';
        tooltip.className = 'tcg-tooltip-content';

        // 添加鼠標事件，讓用戶可以移動到 tooltip 上而不會消失
        tooltip.addEventListener('mouseenter', cancelHideTooltip);
        tooltip.addEventListener('mouseleave', hideJiraPreview);

        document.body.appendChild(tooltip);
    }
    return tooltip;
}

// 顯示 JIRA 預覽
async function showJiraPreview(event, ticketNumber) {
    const tooltip = getOrCreateJiraTooltip();
    const targetElement = event.currentTarget;
    
    // 設定 tooltip 位置，確保畫面內可見
    positionTooltip(tooltip, targetElement);
    
    // 顯示載入中狀態
    tooltip.innerHTML = `
        <div class="loading-spinner">
            <i class="fas fa-spinner fa-spin me-2"></i>
            載入中...
        </div>
    `;
    tooltip.classList.add('show');
    
    try {
        // 檢查快取
        if (jiraDataCache.has(ticketNumber)) {
            const cachedData = jiraDataCache.get(ticketNumber);
            displayJiraData(tooltip, ticketNumber, cachedData);
            return;
        }
        
        // 呼叫 JIRA API
        const response = await window.AuthClient.fetch(`/api/jira/tp/${ticketNumber}/details`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        
        // 快取資料（5分鐘）
        jiraDataCache.set(ticketNumber, data);
        setTimeout(() => jiraDataCache.delete(ticketNumber), 5 * 60 * 1000);
        
        // 顯示資料
        displayJiraData(tooltip, ticketNumber, data);
        
    } catch (error) {
        console.error('載入 JIRA 資料失敗:', error);
        tooltip.innerHTML = `
            <div class="error-message">
                <i class="fas fa-exclamation-triangle me-2"></i>
                載入失敗，請稍後再試
            </div>
        `;
    }
}

// 隱藏 JIRA 預覽（延遲機制避免誤觸發）
let hideTooltipTimer = null;

function hideJiraPreview() {
    // 設定延遲隱藏，讓用戶有時間移動到 tooltip 上
    hideTooltipTimer = setTimeout(() => {
        const tooltip = document.getElementById('tcg-tooltip-content');
        if (tooltip) {
            tooltip.classList.remove('show');
        }
    }, 150); // 150ms 延遲
}

// 取消隱藏 tooltip（用戶移動到 tooltip 上時）
function cancelHideTooltip() {
    if (hideTooltipTimer) {
        clearTimeout(hideTooltipTimer);
        hideTooltipTimer = null;
    }
}

// 顯示 JIRA 資料
function displayJiraData(tooltip, ticketNumber, data) {
    // 安全地獲取狀態文字 - status 可能是物件或字串
    let statusText = 'unknown';
    if (data.status) {
        if (typeof data.status === 'object' && data.status.name) {
            statusText = data.status.name;
        } else if (typeof data.status === 'string') {
            statusText = data.status;
        }
    }
    
    const statusClass = getStatusClass(statusText);
    
    // 安全地獲取負責人資訊 - assignee 也可能是物件
    let assigneeDisplay = '未指派';
    if (data.assignee) {
        if (typeof data.assignee === 'object') {
            assigneeDisplay = data.assignee.display_name || data.assignee.displayName || '未指派';
        } else if (typeof data.assignee === 'string') {
            assigneeDisplay = data.assignee;
        }
    }
    
    tooltip.innerHTML = `
        <div class="tcg-tooltip-header">
            <div class="tcg-ticket-info">
                <span class="tcg-ticket-number">${ticketNumber}</span>
                <span class="tcg-ticket-status ${statusClass}">${statusText || 'Unknown'}</span>
            </div>
        </div>
        
        <div class="tcg-ticket-content">
            <div class="tcg-ticket-title">${data.summary || '無標題'}</div>
            
            <div class="tcg-ticket-meta">
                <div class="tcg-assignee">
                    <span class="tcg-label">負責人:</span>
                    <span class="tcg-value">${assigneeDisplay}</span>
                </div>
                ${data.priority ? `
                <div class="tcg-priority">
                    <span class="tcg-label">優先級:</span>
                    <span class="tcg-value">${typeof data.priority === 'object' ? (data.priority.name || '未設定') : data.priority}</span>
                </div>
                ` : ''}
            </div>
        </div>
        
        <div class="tcg-tooltip-footer">
            <a href="${data.url || '#'}" target="_blank" class="tcg-jira-link">
                <i class="fas fa-external-link-alt me-1"></i>
                在 JIRA 中檢視
            </a>
        </div>
    `;
}


// 定位 tooltip
function positionTooltip(tooltip, targetElement) {
    const targetRect = targetElement.getBoundingClientRect();
    
    // 臨時顯示 tooltip 以獲得正確尺寸
    const wasVisible = tooltip.classList.contains('show');
    if (!wasVisible) {
        tooltip.style.visibility = 'hidden';
        tooltip.style.opacity = '1';
        tooltip.classList.add('show');
    }
    
    const tooltipRect = tooltip.getBoundingClientRect();
    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;
    
    // 如果之前是隱藏的，恢復隱藏狀態
    if (!wasVisible) {
        tooltip.classList.remove('show');
        tooltip.style.visibility = '';
        tooltip.style.opacity = '';
    }
    
    // 預設放在目標元素下方
    let left = targetRect.left + (targetRect.width / 2) - (tooltipRect.width / 2);
    let top = targetRect.bottom + 8;
    
    // 調整水平位置避免超出視窗
    if (left < 8) {
        left = 8;
    } else if (left + tooltipRect.width > windowWidth - 8) {
        left = windowWidth - tooltipRect.width - 8;
    }
    
    // 調整垂直位置避免超出視窗
    if (top + tooltipRect.height > windowHeight - 8) {
        top = targetRect.top - tooltipRect.height - 8;
    }
    
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
}

// 開啟 JIRA 票號
function openJiraTicket(ticketNumber) {
    // 嘗試從快取獲取 URL，否則使用預設格式
    const cachedData = jiraDataCache.get(ticketNumber);
    if (cachedData && cachedData.url) {
        window.open(cachedData.url, '_blank');
        return;
    }
    
    // 使用 API 獲取正確的 JIRA URL
    window.AuthClient.fetch(`/api/jira/tp/${ticketNumber}/details`)
        .then(response => response.json())
        .then(data => {
            if (data.url) {
                window.open(data.url, '_blank');
            } else {
                console.error('無法獲取 JIRA URL');
            }
        })
        .catch(error => {
            console.error('開啟 JIRA 票號失敗:', error);
        });
}

// === T022 JIRA 整合工具函數 ===

// 獲取 TP 票號詳情
async function fetchTPDetails(ticketNumber) {
    try {
        // 檢查快取
        if (jiraDataCache.has(ticketNumber)) {
            return jiraDataCache.get(ticketNumber);
        }
        
        // 呼叫 JIRA API
        const response = await window.AuthClient.fetch(`/api/jira/tp/${ticketNumber}/details`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const data = await response.json();
        
        // 快取資料（5分鐘）
        jiraDataCache.set(ticketNumber, data);
        setTimeout(() => jiraDataCache.delete(ticketNumber), 5 * 60 * 1000);
        
        return data;
        
    } catch (error) {
        console.error('獲取 JIRA 資料失敗:', error);
        throw error;
    }
}

// 顯示 TP 票號預覽（T022 兼容介面）
async function showTPPreview(element, ticketNumber) {
    // 創建兼容的 event 物件
    const fakeEvent = {
        currentTarget: element
    };
    
    // 使用現有的 showJiraPreview 函數
    return showJiraPreview(fakeEvent, ticketNumber);
}

// 開啟 JIRA 連結（T022 別名函數）
function openJiraLink(ticketNumber) {
    return openJiraTicket(ticketNumber);
}

// === Modal 表單驗證系統 ===

// 綜合表單驗證函數
