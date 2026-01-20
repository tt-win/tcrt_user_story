/* Test Run Execution - Bug Tickets */
// ================== Bug Tickets 功能 ==================
let addBugTicketModal = null;
let deleteBugTicketModal = null;
let currentItemIdForBugTicket = null;
let currentTicketNumberForDelete = null;

// 初始化 Bug Ticket Modal
function initBugTicketModal() {
    if (!addBugTicketModal) {
        addBugTicketModal = new bootstrap.Modal(document.getElementById('addBugTicketModal'));
    }
    
    // 確保 Bug Ticket Modal 有最高的 z-index (高於 Test Case Detail Modal)
    const modalElement = document.getElementById('addBugTicketModal');
    modalElement.style.zIndex = '1090';
    
    // 設置 Modal 事件監聽器來處理 backdrop z-index
    modalElement.addEventListener('shown.bs.modal', function() {
        // 找到最新的 backdrop 並設置正確的 z-index
        const backdrops = document.querySelectorAll('.modal-backdrop');
        if (backdrops.length > 0) {
            // 設置最新的 backdrop 有較高的 z-index
            const latestBackdrop = backdrops[backdrops.length - 1];
            latestBackdrop.style.zIndex = '1089';
        }
        
        // 確保 Modal 本身的 z-index 是最高的
        modalElement.style.zIndex = '1090';
    });
}

// 初始化刪除 Bug Ticket Modal
function initDeleteBugTicketModal() {
    if (!deleteBugTicketModal) {
        deleteBugTicketModal = new bootstrap.Modal(document.getElementById('deleteBugTicketModal'));
    }
    
    // 確保刪除 Bug Ticket Modal 有最高的 z-index
    const modalElement = document.getElementById('deleteBugTicketModal');
    modalElement.style.zIndex = '1090';
    
    // 設置 Modal 事件監聽器來處理 backdrop z-index
    modalElement.addEventListener('shown.bs.modal', function() {
        const backdrops = document.querySelectorAll('.modal-backdrop');
        if (backdrops.length > 0) {
            const latestBackdrop = backdrops[backdrops.length - 1];
            latestBackdrop.style.zIndex = '1089';
        }
        modalElement.style.zIndex = '1090';
    });
}

// 顯示 Bug Tickets
async function loadBugTickets(itemId) {
    try {
        // 顯示載入狀態
        const bugTicketsList = document.getElementById('bugTicketsList');
        const bugTicketsEmpty = document.getElementById('bugTicketsEmpty');
        const bugTicketsLoading = document.getElementById('bugTicketsLoading');

        if (bugTicketsLoading) bugTicketsLoading.style.display = 'block';
        if (bugTicketsEmpty) bugTicketsEmpty.style.display = 'none';
        if (bugTicketsList) bugTicketsList.innerHTML = '';
        
        const url = `/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/${itemId}/bug-tickets`;
        
        const response = await window.AuthClient.fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: Failed to load bug tickets`);
        }
        
        const bugTickets = await response.json();
        
        bugTicketsLoading.style.display = 'none';
        
        if (bugTickets.length === 0) {
            bugTicketsEmpty.style.display = 'block';
            bugTicketsList.innerHTML = '';
        } else {
            bugTicketsEmpty.style.display = 'none';
            bugTicketsList.innerHTML = bugTickets.map(ticket => {
                // 顯示時使用清理後的版本，但保留原始值用於刪除
                const cleanedTicket = cleanTicketNumber(ticket.ticket_number);
                const escapedCleanedTicket = escapeHtml(cleanedTicket);
                // 保留原始 ticket number 用於 API 呼叫（進行 HTML 轉義但不清理）
                const escapedOriginalTicket = escapeHtml(ticket.ticket_number);
                return `
                <div class="bug-ticket-item d-flex justify-content-between align-items-center mb-2 p-2 border rounded bg-light">
                    <div>
                        <strong class="bug-ticket-link" data-ticket="${escapedOriginalTicket}" style="cursor: pointer; color: #0066cc;">
                            ${escapedCleanedTicket}
                        </strong>
                    </div>
                    <button type="button" class="btn btn-secondary text-secondary p-0" data-item-id="${itemId}" data-ticket-original="${escapedOriginalTicket}" data-i18n-title="common.delete" style="border: none; background: none;">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            `;
            }).join('');

            // 綁定刪除按鈕事件（使用事件委託）
            bugTicketsList.querySelectorAll('.btn-secondary').forEach(btn => {
                btn.addEventListener('click', function() {
                    const itemId = this.getAttribute('data-item-id');
                    // 使用原始的 ticket number 進行刪除
                    const ticketNumber = this.getAttribute('data-ticket-original');
                    confirmDeleteBugTicket(parseInt(itemId), ticketNumber);
                });
            });

            // 重新翻譯動態添加的元素
            if (window.i18n && window.i18n.isReady()) {
                window.i18n.retranslate(bugTicketsList);
            }
        }
        
        return bugTickets;
    } catch (error) {
        console.error('載入 Bug Tickets 失敗:', error);
        const bugTicketsLoading = document.getElementById('bugTicketsLoading');
        const bugTicketsEmpty = document.getElementById('bugTicketsEmpty');
        
        bugTicketsLoading.style.display = 'none';
        bugTicketsEmpty.style.display = 'block';
        bugTicketsEmpty.innerHTML = '<i class="fas fa-exclamation-triangle me-1"></i><span data-i18n="testRun.loadBugTicketsFailed">載入 Bug Tickets 失敗</span>';
        return [];
    }
}

// 載入 Comment
async function loadComment(testRunItemId) {
    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/${testRunItemId}/comment`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const commentContent = document.getElementById('commentContent');
        if (commentContent) {
            // 確保恢復 small class 和 style（如果在編輯模式中被移除）
            if (!commentContent.classList.contains('small')) {
                commentContent.classList.add('small');
            }
            const currentStyle = commentContent.getAttribute('style');
            if (!currentStyle || !currentStyle.includes('white-space: pre-wrap')) {
                commentContent.setAttribute('style', 'flex: 1; overflow-y: auto; white-space: pre-wrap;');
            }

            if (data.comment && data.comment.trim()) {
                const originalMarkdown = data.comment;

                // 使用 marked 库将 markdown 转换为 HTML
                let htmlContent = marked.parse(originalMarkdown);

                // 使用 DOMPurify 清理 HTML，防止 XSS 攻击
                // 配置允许的标签和属性
                const cleanHtml = DOMPurify.sanitize(htmlContent, {
                    ALLOWED_TAGS: ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'strong', 'em', 'u', 'del',
                                  'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'hr', 'table', 'thead', 'tbody',
                                  'th', 'tr', 'td', 'a', 'img', 'span', 'div'],
                    ALLOWED_ATTR: ['href', 'title', 'alt', 'src', 'class', 'id'],
                    ALLOW_DATA_ATTR: false
                });

                // 在 data attribute 中存储原始 markdown，以便编辑时使用
                commentContent.setAttribute('data-original-markdown', originalMarkdown);

                // 设置渲染的 HTML
                commentContent.innerHTML = cleanHtml;
            } else {
                commentContent.innerHTML = '<span data-i18n="testRun.noComment">尚無註釋</span>';
                commentContent.removeAttribute('data-original-markdown');
            }
        }
    } catch (error) {
        console.error('載入 Comment 失敗:', error);
        const commentContent = document.getElementById('commentContent');
        if (commentContent) {
            commentContent.innerHTML = '<span class="text-danger">載入失敗</span>';
            commentContent.removeAttribute('data-original-markdown');
        }
    }
}

// 編輯 Comment
async function editComment(testRunItemId) {
    if (!getTrePermissions().canUpdateResults) {
        showExecutionPermissionDenied();
        return;
    }

    const commentContent = document.getElementById('commentContent');
    if (!commentContent) return;

    // 如果已經在編輯模式，不要重複進入
    if (document.getElementById('commentTextarea')) {
        return;
    }

    // 檢查是否顯示了"暫無註釋"，如果是則當前評論為空
    const isNoCommentShown = commentContent.querySelector && commentContent.querySelector('[data-i18n="testRun.noComment"]');

    // 優先使用存儲在 data attribute 中的原始 markdown，否則為空
    let currentComment = '';
    if (!isNoCommentShown) {
        const originalMarkdown = commentContent.getAttribute('data-original-markdown');
        if (originalMarkdown) {
            currentComment = originalMarkdown;
        }
    }

    // 儲存原始狀態
    const originalContent = commentContent.innerHTML;
    const originalMarkdown = commentContent.getAttribute('data-original-markdown');
    const hasSmallClass = commentContent.classList.contains('small');
    const originalStyle = commentContent.getAttribute('style');

    // 暫時移除 small class
    if (hasSmallClass) {
        commentContent.classList.remove('small');
    }
    // 調整 style 以配合編輯模式（保持 flex: 1 讓它填滿父容器）
    commentContent.setAttribute('style', 'flex: 1; overflow-y: auto; display: flex; flex-direction: column;');

    // 替換成編輯模式
    commentContent.innerHTML = `
        <textarea class="form-control mb-2" id="commentTextarea" rows="2" placeholder="輸入註釋內容..." style="flex: 1; resize: none; min-height: 60px;">${escapeHtml(currentComment)}</textarea>
        <div class="d-flex gap-2" style="flex-shrink: 0;">
            <button type="button" class="btn btn-primary" id="saveCommentBtn">
                <i class="fas fa-save me-1"></i>儲存
            </button>
            <button type="button" class="btn btn-secondary" id="cancelCommentBtn">
                <i class="fas fa-times me-1"></i>取消
            </button>
        </div>
    `;

    // 聚焦到 textarea
    const textarea = document.getElementById('commentTextarea');
    if (textarea) {
        textarea.focus();
        textarea.setSelectionRange(textarea.value.length, textarea.value.length);
        setupMarkdownHotkeys(textarea);
    }

    // 還原函數
    const restoreOriginal = () => {
        commentContent.innerHTML = originalContent;
        if (originalMarkdown) {
            commentContent.setAttribute('data-original-markdown', originalMarkdown);
        }
        if (hasSmallClass) {
            commentContent.classList.add('small');
        }
        if (originalStyle) {
            commentContent.setAttribute('style', originalStyle);
        }
    };

    // 綁定儲存按鈕事件
    document.getElementById('saveCommentBtn').addEventListener('click', async () => {
        const newComment = textarea.value.trim();
        await saveComment(testRunItemId, newComment);
    });

    // 綁定取消按鈕事件
    document.getElementById('cancelCommentBtn').addEventListener('click', () => {
        restoreOriginal();
    });

    // 綁定鍵盤事件
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            restoreOriginal();
        } else if (e.key === 'Enter' && e.ctrlKey) {
            e.preventDefault();
            document.getElementById('saveCommentBtn').click();
        }
    });
}

// 儲存 Comment
async function saveComment(testRunItemId, comment) {
    if (!getTrePermissions().canUpdateResults) {
        showExecutionPermissionDenied();
        return;
    }

    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/${testRunItemId}/comment`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment: comment })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        // 重新載入 comment
        await loadComment(testRunItemId);

        // 顯示成功訊息
        if (window.AppUtils && typeof window.AppUtils.showSuccess === 'function') {
            window.AppUtils.showSuccess('註釋已儲存');
        }

    } catch (error) {
        console.error('儲存 Comment 失敗:', error);
        if (window.AppUtils && typeof window.AppUtils.showError === 'function') {
            window.AppUtils.showError('儲存註釋失敗: ' + error.message);
        }
    }
}

// 清理 Bug Ticket 編號，移除 URL 和特殊字符
function cleanTicketNumber(ticketNumber) {
    if (!ticketNumber) return '';

    // 移除 URL 前綴 (http://, https://, etc.)
    let cleaned = ticketNumber.replace(/^https?:\/\//i, '');

    // 如果包含 '/'，取最後一段（通常是 ticket number）
    if (cleaned.includes('/')) {
        const parts = cleaned.split('/');
        cleaned = parts[parts.length - 1];
    }

    // 移除尾部的特殊字符和空白
    cleaned = cleaned.trim();

    return cleaned;
}

// 新增 Bug Ticket
async function addBugTicket() {
    if (!getTrePermissions().canManageBugTickets) {
        showExecutionPermissionDenied();
        return;
    }
    const rawTicketNumber = document.getElementById('bugTicketNumber').value.trim();
    const ticketNumber = cleanTicketNumber(rawTicketNumber);

    if (!ticketNumber) {
        AppUtils.showError(window.i18n ? window.i18n.t('testRun.ticketNumberHelp') : '請輸入 JIRA Ticket 編號');
        return;
    }

    if (!currentItemIdForBugTicket) {
        AppUtils.showError('Missing item ID');
        return;
    }

    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/${currentItemIdForBugTicket}/bug-tickets`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                ticket_number: ticketNumber
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to add bug ticket');
        }

        // 關閉模態框並清空表單
        addBugTicketModal.hide();
        document.getElementById('bugTicketNumber').value = '';

        // 重新載入 Bug Tickets 列表
        await loadBugTickets(currentItemIdForBugTicket);

        AppUtils.showSuccess(window.i18n ? window.i18n.t('testRun.bugTicketAdded') : 'Bug Ticket 新增成功');

    } catch (error) {
        console.error('新增 Bug Ticket 失敗:', error);
        AppUtils.showError(error.message || (window.i18n ? window.i18n.t('testRun.addBugTicketFailed') : '新增 Bug Ticket 失敗'));
    }
}

// 顯示刪除 Bug Ticket 確認對話框
function confirmDeleteBugTicket(itemId, ticketNumber) {
    initDeleteBugTicketModal();
    currentItemIdForBugTicket = itemId;
    currentTicketNumberForDelete = ticketNumber;

    // 顯示清理後的票號（更容易閱讀），但實際刪除時使用原始值
    const displayTicketNumber = cleanTicketNumber(ticketNumber);
    document.getElementById('deleteBugTicketNumber').textContent = displayTicketNumber;

    deleteBugTicketModal.show();
}

// 刪除 Bug Ticket
async function deleteBugTicket(itemId, ticketNumber) {
    if (!getTrePermissions().canManageBugTickets) {
        showExecutionPermissionDenied();
        return;
    }
    
    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/${itemId}/bug-tickets/${encodeURIComponent(ticketNumber)}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            throw new Error('Failed to delete bug ticket');
        }
        
        // 重新載入 Bug Tickets 列表
        await loadBugTickets(itemId);
        
        AppUtils.showSuccess(window.i18n ? window.i18n.t('testRun.bugTicketDeleted') : 'Bug Ticket 已刪除');
        
    } catch (error) {
        console.error('刪除 Bug Ticket 失敗:', error);
        AppUtils.showError(error.message || (window.i18n ? window.i18n.t('testRun.deleteBugTicketFailed') : '刪除 Bug Ticket 失敗'));
    }
}

// 綁定 Bug Ticket 相關事件
function bindBugTicketEvents() {
    const permissions = getTrePermissions();
    const canManageBugTickets = permissions.canManageBugTickets;
    // 新增 Bug Ticket 按鈕
    const addBugTicketBtn = document.getElementById('addBugTicketBtn');
    if (addBugTicketBtn) {
        if (canManageBugTickets) {
            addBugTicketBtn.addEventListener('click', () => {
                if (addBugTicketBtn.disabled) {
                    return;
                }

                initBugTicketModal();
                currentItemIdForBugTicket = getCurrentItemId();
                if (currentItemIdForBugTicket) {
                    addBugTicketModal.show();
                    document.getElementById('bugTicketNumber').value = '';
                    setTimeout(() => {
                        document.getElementById('bugTicketNumber').focus();
                    }, 300);
                } else {
                    AppUtils.showError('請先選擇一個測試項目');
                }
            });
        } else {
            addBugTicketBtn.disabled = true;
        }
    }
    
    // 確認新增 Bug Ticket 按鈕
    const confirmAddBugTicket = document.getElementById('confirmAddBugTicket');
    if (confirmAddBugTicket) {
        if (canManageBugTickets) {
            confirmAddBugTicket.addEventListener('click', addBugTicket);
        } else {
            confirmAddBugTicket.disabled = true;
        }
    }

    // 確認刪除 Bug Ticket 按鈕
    const confirmDeleteBugTicketBtn = document.getElementById('confirmDeleteBugTicket');
    if (confirmDeleteBugTicketBtn) {
        if (canManageBugTickets) {
            confirmDeleteBugTicketBtn.addEventListener('click', async () => {
                if (currentItemIdForBugTicket && currentTicketNumberForDelete) {
                    deleteBugTicketModal.hide();
                    await deleteBugTicket(currentItemIdForBugTicket, currentTicketNumberForDelete);
                    // 保留 currentItemIdForBugTicket 以便繼續新增其他 Bug Tickets
                    currentTicketNumberForDelete = null;
                }
            });
        } else {
            confirmDeleteBugTicketBtn.disabled = true;
        }
    }
    
    // Enter 鍵提交表單
    const bugTicketNumberInput = document.getElementById('bugTicketNumber');
    if (bugTicketNumberInput) {
        if (canManageBugTickets) {
            bugTicketNumberInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    addBugTicket();
                }
            });
        } else {
            bugTicketNumberInput.setAttribute('disabled', 'true');
        }
    }
    
    // 委託事件：Bug Ticket 點擊預覽
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('bug-ticket-link')) {
            const ticketNumber = e.target.getAttribute('data-ticket');
            if (ticketNumber) {
                showBugTicketPreview(ticketNumber, e.target);
            }
        }
    });
}

// 取得當前選中的測試項目 ID
function getCurrentItemId() {
    // 使用在 renderResultHistoryTimeline 中設定的 currentItemIdForBugTicket
    return currentItemIdForBugTicket;
}

// Bug Ticket 直接打開 JIRA 頁面
async function showBugTicketPreview(ticketNumber, triggerElement) {
    try {
        // 獲取 JIRA ticket 資訊（包括 URL）
        const response = await window.AuthClient.fetch(`/api/jira/ticket/${encodeURIComponent(ticketNumber)}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const ticketData = await response.json();

        // 如果成功獲取到 URL，直接在新標籤頁打開
        if (ticketData.url) {
            window.open(ticketData.url, '_blank');
        } else {
            console.error('未能獲取到 JIRA ticket URL');
        }
    } catch (error) {
        console.error('打開 JIRA ticket 失敗:', error);
        // 如果出現錯誤，顯示提示訊息
        alert('無法打開 JIRA ticket，請稍後重試');
    }
}

// JIRA 狀態對應的 Badge 類別
function getJIRAStatusBadgeClass(status) {
    if (!status) return 'bg-secondary';
    
    const statusLower = status.toLowerCase();
    if (['done', 'closed', 'resolved', 'fixed'].includes(statusLower)) {
        return 'bg-success';
    }
    if (['in progress', 'in-progress', 'inprogress'].includes(statusLower)) {
        return 'bg-primary';
    }
    if (['open', 'to do', 'todo', 'new'].includes(statusLower)) {
        return 'bg-info';
    }
    if (['blocked', 'on hold'].includes(statusLower)) {
        return 'bg-danger';
    }
    return 'bg-warning';
}

// ================== Bug Tickets Summary 功能 ==================
let bugTicketsSummaryModal = null;
let currentBugTicketsSummary = null;
let currentBugStatusFilter = 'ALL';

// Bug Tickets 狀態到徽章顏色的映射
function getBugStatusBadgeClass(status) {
    const statusName = (status || '').toUpperCase().trim();
    
    const statusMap = {
        'TO DO': 'bg-primary',
        'TODO': 'bg-primary',
        'IN PROGRESS': 'bg-info', 
        'INPROGRESS': 'bg-info',
        'RESOLVED': 'bg-success',
        'CLOSED': 'bg-dark',
        'OPEN': 'bg-warning',
        'SCHEDULED': 'bg-secondary'
    };
    
    return statusMap[statusName] || 'bg-secondary';
}

// Bug Tickets 狀態篩選功能
function filterBugTicketsByStatus(status) {
    currentBugStatusFilter = status;
    
    // 更新按鈕狀態
    document.querySelectorAll('[data-status]').forEach(btn => {
        btn.classList.remove('active');
        if (btn.getAttribute('data-status') === status) {
            btn.classList.add('active');
        }
    });
    
    // 重新渲染
    if (currentBugTicketsSummary) {
        renderBugTicketsCards(currentBugTicketsSummary, document.getElementById('bugTicketsSummaryList'));
        // 重新翻譯動態生成的內容
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(document.getElementById('bugTicketsSummaryList'));
        }
    }
}

// 初始化 Bug Tickets Summary Modal
function initBugTicketsSummaryModal() {
    const modalElement = document.getElementById('bugTicketsSummaryModal');
    if (modalElement && !bugTicketsSummaryModal) {
        bugTicketsSummaryModal = new bootstrap.Modal(modalElement);
    } else if (!modalElement) {
        console.error('找不到 bugTicketsSummaryModal 元素');
    }
}

// 顯示 Bug Tickets Summary Modal
async function showBugTicketsModal() {
    initBugTicketsSummaryModal();
    
    if (bugTicketsSummaryModal) {
        bugTicketsSummaryModal.show();
        
        // 延遲一下確保 Modal 完全打開
        setTimeout(() => {
            loadBugTicketsSummary();
        }, 100);
    } else {
        console.error('無法顯示 Modal');
    }
}

// 載入 Bug Tickets Summary 資料
async function loadBugTicketsSummary() {
    const loadingEl = document.getElementById('bugTicketsSummaryLoading');
    const emptyEl = document.getElementById('bugTicketsSummaryEmpty');
    const contentEl = document.getElementById('bugTicketsSummaryContent');
    
    // 檢查所有必要元素
    if (!loadingEl) {
        console.error('找不到 bugTicketsSummaryLoading 元素');
        return;
    }
    if (!emptyEl) {
        console.error('找不到 bugTicketsSummaryEmpty 元素');
        return;
    }
    if (!contentEl) {
        console.error('找不到 bugTicketsSummaryContent 元素');
        return;
    }
    
    // 重置所有狀態
    loadingEl.style.display = 'block';
    emptyEl.style.display = 'none';
    contentEl.style.display = 'none';
    
    try {
        const url = `/api/teams/${currentTeamId}/test-run-configs/${currentConfigId}/items/bug-tickets/summary`;
        const response = await window.AuthClient.fetch(url);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const summaryData = await response.json();
        currentBugTicketsSummary = summaryData;
        loadingEl.style.display = 'none';
        
        if (!summaryData || summaryData.total_unique_tickets === 0 || !summaryData.tickets || summaryData.tickets.length === 0) {
            emptyEl.style.display = 'block';
            return;
        }
        
        contentEl.style.display = 'block';
        renderBugTicketsSummary(summaryData);
        
    } catch (error) {
        console.error('載入失敗:', error);
        loadingEl.style.display = 'none';
        emptyEl.style.display = 'block';
        emptyEl.innerHTML = '<i class="fas fa-exclamation-triangle me-2"></i><span class="text-danger">載入失敗: ' + error.message + '</span>';
    }
}

// 渲染 Bug Tickets Summary
function renderBugTicketsSummary(summaryData) {
    const bugTicketsList = document.getElementById('bugTicketsSummaryList');
    
    if (!bugTicketsList) {
        console.error('找不到必要的元素');
        return;
    }
    
    renderBugTicketsCards(summaryData, bugTicketsList);
}

function renderBugTicketsCards(summaryData, bugTicketsList) {
    if (!summaryData.tickets || summaryData.tickets.length === 0) {
        const noBugTicketsText = treTranslate('testRun.noBugTicketsInRun', '此 Test Run 尚無 Bug Tickets');
        bugTicketsList.innerHTML = `<div class="text-muted text-center p-4"><i class="fas fa-info-circle me-2"></i>${noBugTicketsText}</div>`;
        return;
    }
    
    // 根據當前篩選條件過濾 tickets
    let filteredTickets = summaryData.tickets;
    if (currentBugStatusFilter !== 'ALL') {
        filteredTickets = summaryData.tickets.filter(ticket => {
            const statusName = (ticket.ticket_info.status.name || '').toUpperCase().trim();
            const filterStatus = currentBugStatusFilter.toUpperCase().trim();
            return statusName === filterStatus || 
                   (filterStatus === 'IN PROGRESS' && statusName === 'INPROGRESS') ||
                   (filterStatus === 'TO DO' && statusName === 'TODO');
        });
    }
    
    if (filteredTickets.length === 0) {
        const noTicketsForStatusText = treTranslate('testRun.noTicketsForStatus', '此狀態下無 Bug Tickets');
        bugTicketsList.innerHTML = `<div class="text-muted text-center p-4"><i class="fas fa-filter me-2"></i>${noTicketsForStatusText}</div>`;
        return;
    }
    
    let cardsHTML = '';
    
    filteredTickets.forEach(ticket => {
        const ticketInfo = ticket.ticket_info;
        const testCases = ticket.test_cases;
        
        let testCasesHTML = '';
        testCases.forEach(testCase => {
            testCasesHTML += `
                <div class="border rounded p-2 mb-2 bg-white" style="cursor: pointer;" 
                     onclick="showTestCaseQuickView('${testCase.test_case_number}')">
                    <strong class="text-primary">${testCase.test_case_number}</strong><br>
                    <small class="text-muted">${testCase.title || ''}</small>
                </div>
            `;
        });
        
        // 使用新的狀態顏色映射函數
        const badgeClass = getBugStatusBadgeClass(ticketInfo.status.name);
        
        cardsHTML += `
            <div class="card mb-3">
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-4">
                            <h6 class="card-title">
                                <a href="${ticketInfo.url}" target="_blank" class="text-decoration-none">
                                    ${ticketInfo.ticket_number} 
                                    <i class="fas fa-external-link-alt fa-sm"></i>
                                </a>
                            </h6>
                            <span class="badge ${badgeClass}">${ticketInfo.status.name}</span>
                            <p class="card-text mt-2">
                                <small class="text-muted">${ticketInfo.summary || 'No summary available'}</small>
                            </p>
                        </div>
                        <div class="col-md-8">
                            <h6><i class="fas fa-list-ul me-1"></i><span data-i18n="testRun.relatedTestCases">相關測試案例</span>
                                <span class="badge bg-info">${testCases.length}</span>
                            </h6>
                            <div style="max-height: 200px; overflow-y: auto;">
                                ${testCasesHTML}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });
    
    bugTicketsList.innerHTML = cardsHTML;
}



// 重新整理 Bug Tickets 狀態（呼叫 JIRA API 更新狀態）
async function refreshBugTicketsStatus() {
    if (!currentBugTicketsSummary || currentBugTicketsSummary.total_unique_tickets === 0) {
        return;
    }
    
    // 顯示重新整理進度
    const refreshBtn = document.querySelector('button[onclick="refreshBugTicketsStatus()"]');
    const originalHtml = refreshBtn.innerHTML;
    refreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>更新中...';
    refreshBtn.disabled = true;
    
    try {
        // 依序呼叫 JIRA API 更新每個 ticket 的狀態
        for (let ticket of currentBugTicketsSummary.tickets) {
            try {
                const response = await window.AuthClient.fetch(`/api/jira/ticket/${encodeURIComponent(ticket.ticket_info.ticket_number)}`);
                if (response.ok) {
                    const jiraData = await response.json();
                    // 更新本地資料
                    ticket.ticket_info.status = jiraData.status;
                    ticket.ticket_info.summary = jiraData.summary;
                }
            } catch (error) {
                console.warn(`Failed to update ticket ${ticket.ticket_info.ticket_number}:`, error);
            }
        }
        
        // 重新渲染
        renderBugTicketsSummary(currentBugTicketsSummary);
        AppUtils.showSuccess('Bug Tickets 狀態已更新');
        
    } catch (error) {
        console.error('重新整理 Bug Tickets 狀態失敗:', error);
        AppUtils.showError('更新狀態失敗: ' + error.message);
    } finally {
        refreshBtn.innerHTML = originalHtml;
        refreshBtn.disabled = false;
    }
}

// 測試案例快速預覽（使用瀏覽器 popup）
function showTestCaseQuickView(testCaseNumber) {
    // 直接使用現有的 Test Case Detail Modal
    showTestCaseDetailModal(testCaseNumber);
}
