/* ============================================================
   TEST CASE MANAGEMENT - TCG TOOLTIP
   ============================================================ */

/* ============================================================
   22. TCG Tooltip (TCG Hover)
   ============================================================ */

// NOTE: currentTooltip, tooltipTimeout, currentHoveredElement, isHoveringTooltip, isInitialized 已統一定義於 Section 2

// 建立 TCG tooltip 元素
function createTCGTTooltip() {
    // 如果已經存在，先移除
    const existingTooltip = document.getElementById('tcg-tooltip-content');
    if (existingTooltip) {
        existingTooltip.remove();
    }

    const tooltip = document.createElement('div');
    tooltip.id = 'tcg-tooltip-content';
    tooltip.className = 'tcg-tooltip-content';
    tooltip.style.cssText = `
        position: fixed;
        background: white;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        padding: 12px;
        max-width: 300px;
        z-index: 1080;
        display: none;
        font-size: 0.875rem;
        pointer-events: auto;
    `;

    document.body.appendChild(tooltip);
    return tooltip;
}

// 顯示 TCG tooltip
async function showTCGTTooltip(tcgNumber, element) {
    // 如果正在載入其他 tooltip，先取消
    if (tooltipTimeout) {
        clearTimeout(tooltipTimeout);
        tooltipTimeout = null;
    }

    // 設定當前 hover 元素
    currentHoveredElement = element;

    // 建立/取得 tooltip 元素
    const tooltip = createTCGTTooltip();

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
    tooltip.style.display = 'block';

    // 定位 tooltip
    positionTooltip(tooltip, element);

    try {
        // 從 JIRA 取得 ticket 資訊
        const ticketData = await fetchJIRATicketInfo(tcgNumber);

        // 檢查是否還在同一個元素上
        if (currentHoveredElement !== element) {
            return; // 用戶已經移開，不顯示結果
        }

        if (ticketData) {
            console.log('準備顯示 ticket 資料:', ticketData); // 除錯用
            // 顯示 ticket 資訊
            tooltip.innerHTML = formatTicketTooltip(tcgNumber, ticketData);
            console.log('Tooltip HTML 已設定'); // 除錯用
        } else {
            // 顯示錯誤訊息
            tooltip.innerHTML = `
                <div class="text-muted small">
                    <i class="fas fa-exclamation-triangle me-1"></i>
                    無法取得 ${tcgNumber} 的資訊
                </div>
            `;
        }
    } catch (error) {
        console.error('TCG tooltip 載入失敗:', error);

        // 檢查是否還在同一個元素上
        if (currentHoveredElement !== element) {
            return;
        }

        tooltip.innerHTML = `
            <div class="text-danger small">
                <i class="fas fa-times-circle me-1"></i>
                載入失敗
            </div>
        `;
    }

    // 重新定位 (內容改變後)
    if (currentHoveredElement === element) {
        positionTooltip(tooltip, element);
    }
}

// 隱藏 TCG tooltip
function hideTCGTTooltip(immediate = false) {
    // 清除之前的 timeout
    if (tooltipTimeout) {
        clearTimeout(tooltipTimeout);
        tooltipTimeout = null;
    }

    // 如果正在 hover tooltip，不隱藏
    if (isHoveringTooltip && !immediate) {
        return;
    }

    const hideTooltip = () => {
        const tooltip = document.getElementById('tcg-tooltip-content');
        if (tooltip) {
            tooltip.style.display = 'none';
        }
        currentHoveredElement = null;
    };

    if (immediate) {
        hideTooltip();
    } else {
        // 延遲隱藏，允許滑鼠移動到 tooltip 上
        tooltipTimeout = setTimeout(hideTooltip, 200);
    }
}

// 從 JIRA 取得 ticket 資訊
async function fetchJIRATicketInfo(tcgNumber) {
    try {
        // 使用 API 端點取得 ticket 資訊
        const response = await window.AuthClient.fetch(`/api/jira/ticket/${tcgNumber}`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (response.ok) {
            const data = await response.json();
            console.log('JIRA API 回應資料:', data); // 除錯用
            return data;
        } else if (response.status === 404) {
            // Ticket 不存在
            console.log('Ticket 不存在:', tcgNumber);
            return null;
        } else {
            // 其他錯誤
            console.error('JIRA API 錯誤:', response.status, response.statusText);
            return null;
        }
    } catch (error) {
        console.error('取得 JIRA ticket 資訊失敗:', error);
        return null;
    }
}

// 格式化 ticket tooltip 內容
function formatTicketTooltip(tcgNumber, ticketData) {
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
function positionTooltip(tooltip, element) {
    const rect = element.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();

    // 預設位置：元素上方
    let top = rect.top - tooltipRect.height - 8;
    let left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);

    // 如果上方空間不足，顯示在元素下方
    if (top < 8) {
        top = rect.bottom + 8;
    }

    // 確保不超出視窗邊界
    if (left < 8) {
        left = 8;
    } else if (left + tooltipRect.width > window.innerWidth - 8) {
        left = window.innerWidth - tooltipRect.width - 8;
    }

    tooltip.style.top = top + 'px';
    tooltip.style.left = left + 'px';
}

// 初始化 TCG hover 功能
function initializeTCGHover() {
    // 防止重複初始化
    if (isInitialized) {
        return;
    }
    isInitialized = true;

    // TCG tag hover 事件處理
    document.addEventListener('mouseover', function(e) {
        // 檢查是否是 TCG tag 或其子元素
        const tcgTag = e.target.closest('.tcg-tag');
        if (tcgTag) {
            const tcgNumber = tcgTag.textContent.trim();
            if (tcgNumber && !isHoveringTooltip) {
                showTCGTTooltip(tcgNumber, tcgTag);
            }
        }

        // 檢查是否移到 tooltip 上
        if (e.target.closest('#tcg-tooltip-content')) {
            isHoveringTooltip = true;
            if (tooltipTimeout) {
                clearTimeout(tooltipTimeout);
                tooltipTimeout = null;
            }
        }
    });

    document.addEventListener('mouseout', function(e) {
        // 檢查是否離開 TCG tag
        const tcgTag = e.target.closest('.tcg-tag');
        if (tcgTag && !e.relatedTarget?.closest('.tcg-tag')) {
            // 確保沒有移到其他 TCG tag 上
            setTimeout(() => {
                if (!isHoveringTooltip && !document.querySelector('.tcg-tag:hover')) {
                    hideTCGTTooltip();
                }
            }, 50);
        }

        // 檢查是否離開 tooltip
        if (e.target.closest('#tcg-tooltip-content') && !e.relatedTarget?.closest('#tcg-tooltip-content')) {
            isHoveringTooltip = false;
            // 延遲檢查是否需要隱藏 tooltip
            setTimeout(() => {
                if (!isHoveringTooltip && !document.querySelector('.tcg-tag:hover')) {
                    hideTCGTTooltip();
                }
            }, 100);
        }
    });

    // 點擊其他地方時隱藏 tooltip
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.tcg-tag') && !e.target.closest('#tcg-tooltip-content')) {
            hideTCGTTooltip(true);
        }
    });

    console.log('TCG hover tooltip initialized');
}

// 清理函數
function cleanupTCGHover() {
    const tooltip = document.getElementById('tcg-tooltip');
    if (tooltip) {
        tooltip.remove();
    }

    if (tooltipTimeout) {
        clearTimeout(tooltipTimeout);
        tooltipTimeout = null;
    }

    currentHoveredElement = null;
    isHoveringTooltip = false;
}

// Modal 中的 TCG 預覽函數 - 獨立實現
async function showTCGPreviewForModal() {
    console.log('showTCGPreviewForModal called'); // 調試用

    const tcgInput = document.getElementById('tcg');
    if (!tcgInput || !tcgInput.value.trim()) {
        alert(window.i18n ? window.i18n.t('errors.noTCGNumber') : '請先輸入 TCG 編號');
        return;
    }

    const tcgNumber = tcgInput.value.trim();
    console.log('TCG Number:', tcgNumber); // 調試用

    // 移除現有的 tooltip（如果有的話）
    const existingTooltip = document.getElementById('tcg-tooltip-content');
    if (existingTooltip) {
        existingTooltip.remove();
    }

    // 創建新的 tooltip
    const tooltip = document.createElement('div');
    tooltip.id = 'tcg-tooltip-content';
    tooltip.style.cssText = `
        position: fixed;
        background: white;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        padding: 12px;
        max-width: 300px;
        z-index: 1080;
        display: block;
        font-size: 0.875rem;
        pointer-events: auto;
    `;

    // 設定載入狀態
    tooltip.innerHTML = `
        <div class="d-flex align-items-center">
            <div class="spinner-border spinner-border-sm me-2" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <span>載入中...</span>
        </div>
    `;

    document.body.appendChild(tooltip);

    // 定位 tooltip
    const rect = tcgInput.getBoundingClientRect();
    let top = rect.top - tooltip.offsetHeight - 8;
    let left = rect.left + (rect.width / 2) - (tooltip.offsetWidth / 2);

    // 確保不超出視窗邊界
    if (top < 8) {
        top = rect.bottom + 8;
    }
    if (left < 8) {
        left = 8;
    } else if (left + tooltip.offsetWidth > window.innerWidth - 8) {
        left = window.innerWidth - tooltip.offsetWidth - 8;
    }

    tooltip.style.top = top + 'px';
    tooltip.style.left = left + 'px';

    try {
        // 從 JIRA 取得 ticket 資訊
        const response = await window.AuthClient.fetch(`/api/jira/ticket/${tcgNumber}`, {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' }
        });

        if (response.ok) {
            const ticketData = await response.json();
            console.log('JIRA 資料:', ticketData); // 調試用

            // 格式化 tooltip 內容
            const summary = ticketData.summary || '無標題';
            const status = ticketData.status?.name || '未知狀態';
            const assignee = ticketData.assignee?.displayName || '未指派';
            const created = ticketData.created || '';
            const updated = ticketData.updated || '';

            // 格式化日期
            let createdDate = '未知';
            let updatedDate = '';
            if (created) {
                try {
                    createdDate = new Date(created).toLocaleDateString('zh-TW');
                } catch (e) {}
            }
            if (updated) {
                try {
                    updatedDate = new Date(updated).toLocaleDateString('zh-TW');
                } catch (e) {}
            }

            const jiraUrl = ticketData.url || `https://jira.example.com/browse/${tcgNumber}`;

            tooltip.innerHTML = `
                <div class="jira-tooltip-content">
                    <div class="mb-2">
                        <div class="fw-bold">
                            <a href="${jiraUrl}" target="_blank" class="text-primary text-decoration-none" style="cursor: pointer;">
                                ${tcgNumber}
                                <i class="fas fa-external-link-alt ms-1" style="font-size: 0.8em;"></i>
                            </a>
                        </div>
                        <div class="small text-muted mb-2" style="word-break: break-word; line-height: 1.3;">${summary}</div>
                    </div>
                    <div class="row g-2">
                        <div class="col-6">
                            <div class="small">
                                <i class="fas fa-tasks me-1"></i>
                                <strong>狀態:</strong>
                            </div>
                            <div class="small text-muted">${status}</div>
                        </div>
                        <div class="col-6">
                            <div class="small">
                                <i class="fas fa-user me-1"></i>
                                <strong>執行者:</strong>
                            </div>
                            <div class="small text-muted" style="word-break: break-word;">${assignee}</div>
                        </div>
                        <div class="col-6">
                            <div class="small">
                                <i class="fas fa-calendar me-1"></i>
                                <strong>建立:</strong>
                            </div>
                            <div class="small text-muted">${createdDate}</div>
                        </div>
                        <div class="col-6">
                            <div class="small">
                                <i class="fas fa-clock me-1"></i>
                                <strong>更新:</strong>
                            </div>
                            <div class="small text-muted">${updatedDate || '無'}</div>
                        </div>
                    </div>
                </div>
            `;
        } else {
            tooltip.innerHTML = `
                <div class="text-muted small">
                    <i class="fas fa-exclamation-triangle me-1"></i>
                    無法取得 ${tcgNumber} 的資訊
                </div>
            `;
        }
    } catch (error) {
        console.error('JIRA 請求失敗:', error);
        tooltip.innerHTML = `
            <div class="text-danger small">
                <i class="fas fa-times-circle me-1"></i>
                載入失敗
            </div>
        `;
    }

    // 點擊其他地方關閉
    const closeHandler = function(e) {
        if (!tooltip.contains(e.target) && e.target !== tcgInput) {
            tooltip.remove();
            document.removeEventListener('click', closeHandler);
        }
    };

    setTimeout(() => {
        document.addEventListener('click', closeHandler);
    }, 100);

    // 自動隱藏
    setTimeout(() => {
        if (tooltip && tooltip.parentNode) {
            tooltip.remove();
            document.removeEventListener('click', closeHandler);
        }
    }, 8000);
}

// 頁面載入完成後初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeTCGHover();
});

// 頁面卸載時清理
window.addEventListener('beforeunload', function() {
    cleanupTCGHover();
});

// 動態內容更新時重新初始化
document.addEventListener('dynamicContentLoaded', function() {
    // 重新初始化，但不清理由有的事件監聽器
    const tooltip = document.getElementById('tcg-tooltip-content');
    if (tooltip) {
        tooltip.remove();
    }
    currentHoveredElement = null;
    isHoveringTooltip = false;
});

    document.addEventListener('mouseout', function(e) {
        if (e.target.classList.contains('tcg-tag')) {
            hideTCGTTooltip();
        }
    });

    // 當滑鼠移到 tooltip 上時，不要隱藏
    document.addEventListener('mouseover', function(e) {
        if (e.target.closest('#tcg-tooltip-content')) {
            if (tooltipTimeout) {
                clearTimeout(tooltipTimeout);
                tooltipTimeout = null;
            }
        }
    });

    // 當滑鼠離開 tooltip 時，隱藏
    document.addEventListener('mouseout', function(e) {
        if (e.target.closest('#tcg-tooltip-content')) {
            hideTCGTTooltip();
        }
    });

// 頁面載入完成後初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeTCGHover();
});

// 動態內容更新時重新初始化
document.addEventListener('dynamicContentLoaded', function() {
    initializeTCGHover();
});
