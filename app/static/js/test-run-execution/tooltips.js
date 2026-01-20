/* Test Run Execution - Tooltips */

// ===== JIRA Tooltip 功能 =====

// Tooltip 相關變數
let jiraTooltipTimeout = null;
let currentJiraHoveredElement = null;
let isJiraHoveringTooltip = false;

// 建立 JIRA tooltip 元素
function createJIRATooltip() {
    // 如果已經存在，先移除
    const existingTooltip = document.getElementById('tcg-tooltip-content');
    if (existingTooltip) {
        existingTooltip.remove();
    }

    const tooltip = document.createElement('div');
    tooltip.id = 'tcg-tooltip-content';
    tooltip.className = 'tcg-tooltip-content';
    tooltip.style.position = 'fixed';
    tooltip.style.display = 'none';

    document.body.appendChild(tooltip);
    return tooltip;
}

// 從 JIRA 取得 ticket 資訊
async function fetchJIRATicketInfo(tcgNumber) {
    try {
        const response = await window.AuthClient.fetch(`/api/jira/ticket/${tcgNumber}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (response.ok) {
            const data = await response.json();
            return data;
        } else if (response.status === 404) {
            return null;
        } else {
            console.error('JIRA API 錯誤:', response.status, response.statusText);
            return null;
        }
    } catch (error) {
        console.error('取得 JIRA ticket 資訊失敗:', error);
        return null;
    }
}

// 格式化 ticket tooltip 內容
function formatJIRATicketTooltip(tcgNumber, ticketData) {
    const summary = ticketData.summary || '無標題';
    const status = ticketData.status?.name || '未知狀態';
    const assignee = ticketData.assignee?.displayName || '未指派';
    const url = ticketData.url || `https://jira.example.com/browse/${tcgNumber}`;

    let statusClass = 'status-todo';
    if (status.toLowerCase().includes('in progress')) {
        statusClass = 'status-in-progress';
    } else if (status.toLowerCase().includes('done') || status.toLowerCase().includes('resolved')) {
        statusClass = 'status-done';
    }

    return `
        <div class="tcg-tooltip-header">
            <div class="tcg-ticket-info">
                <span class="tcg-ticket-number">${tcgNumber}</span>
                <span class="tcg-ticket-status ${statusClass}">${status}</span>
            </div>
        </div>

        <div class="tcg-ticket-content">
            <div class="tcg-ticket-title">${summary}</div>

            <div class="tcg-ticket-meta">
                <div class="tcg-assignee">
                    <span class="tcg-label">負責人:</span>
                    <span class="tcg-value">${assignee}</span>
                </div>
            </div>
        </div>

        <div class="tcg-tooltip-footer">
            <a href="${url}" target="_blank" class="tcg-jira-link">
                <i class="fas fa-external-link-alt me-1"></i>
                在 JIRA 中檢視
            </a>
        </div>
    `;
}

// 定位 tooltip
function positionJIRATooltip(tooltip, element) {
    if (!element || !tooltip) return;

    const rect = element.getBoundingClientRect();

    // 先設置初始位置並確保可見，這樣才能獲取準確的尺寸
    tooltip.style.visibility = 'hidden';
    tooltip.style.display = 'block';

    const tooltipRect = tooltip.getBoundingClientRect();

    // 預設位置：元素下方
    let top = rect.bottom + 8;
    let left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);

    // 如果下方空間不足，顯示在元素上方
    if (top + tooltipRect.height > window.innerHeight - 8) {
        top = rect.top - tooltipRect.height - 8;
    }

    // 確保不超出視窗邊界
    if (left < 8) {
        left = 8;
    } else if (left + tooltipRect.width > window.innerWidth - 8) {
        left = window.innerWidth - tooltipRect.width - 8;
    }

    // 應用最終位置並顯示
    tooltip.style.top = top + 'px';
    tooltip.style.left = left + 'px';
    tooltip.style.visibility = 'visible';
}

// Test Run 頁面的 TCG 預覽函數
async function showTCGPreviewInTestRun(tcgNumber, eventObj) {
    if (!tcgNumber || !tcgNumber.trim()) {
        return;
    }

    // 找到觸發元素（查找包含該 TCG 號碼的按鈕）
    const triggerButton = eventObj ? eventObj.target : event.target;

    const tooltip = createJIRATooltip();

    // 設定載入狀態
    tooltip.innerHTML = `
        <div class="d-flex align-items-center">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <span>載入中...</span>
        </div>
    `;

    // 顯示 tooltip
    positionJIRATooltip(tooltip, triggerButton);

    try {
        const ticketData = await fetchJIRATicketInfo(tcgNumber);

        if (ticketData) {
            tooltip.innerHTML = formatJIRATicketTooltip(tcgNumber, ticketData);
        } else {
            tooltip.innerHTML = `
                <div class="text-muted small">
                    <i class="fas fa-exclamation-triangle me-1"></i>
                    無法取得 ${tcgNumber} 的資訊
                </div>
            `;
        }

        // 重新定位
        positionJIRATooltip(tooltip, triggerButton);

        // 添加點擊關閉事件
        tooltip.addEventListener('click', function(e) {
            e.stopPropagation();
        });

        // 點擊其他地方關閉 tooltip
        const closeTooltip = function(e) {
            if (!tooltip.contains(e.target) && e.target !== triggerButton) {
                tooltip.style.display = 'none';
                document.removeEventListener('click', closeTooltip);
            }
        };

        setTimeout(() => {
            document.addEventListener('click', closeTooltip);
        }, 100);

        // 自動隱藏 tooltip
        setTimeout(() => {
            if (tooltip && tooltip.style.display !== 'none') {
                tooltip.style.display = 'none';
                document.removeEventListener('click', closeTooltip);
            }
        }, 8000);

    } catch (error) {
        console.error('JIRA tooltip 載入失敗:', error);
        tooltip.innerHTML = `
            <div class="text-danger small">
                <i class="fas fa-times-circle me-1"></i>
                載入失敗
            </div>
        `;

        // 重新定位
        positionJIRATooltip(tooltip, triggerButton);

        // 添加點擊關閉事件
        tooltip.addEventListener('click', function(e) {
            e.stopPropagation();
        });

        // 點擊其他地方關閉 tooltip
        const closeTooltip = function(e) {
            if (!tooltip.contains(e.target) && e.target !== triggerButton) {
                tooltip.style.display = 'none';
                document.removeEventListener('click', closeTooltip);
            }
        };

        setTimeout(() => {
            document.addEventListener('click', closeTooltip);
        }, 100);

        // 自動隱藏 tooltip
        setTimeout(() => {
            if (tooltip && tooltip.style.display !== 'none') {
                tooltip.style.display = 'none';
                document.removeEventListener('click', closeTooltip);
            }
        }, 5000);
    }
}
