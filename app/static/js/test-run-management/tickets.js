/* ============================================================
   TEST RUN MANAGEMENT - TICKETS
   ============================================================ */

function validateTpTicketFormat(ticketNumber) {
    // TP 票號格式：TP-XXXXX（TP- 後接 1-10 位數字或字母）
    const tpTicketPattern = /^TP-[A-Z0-9]{1,10}$/i;
    return tpTicketPattern.test(ticketNumber.trim());
}

// 檢查重複票號
function isDuplicateTicket(ticketNumber) {
    return currentTpTickets.includes(ticketNumber.trim().toUpperCase());
}

// 新增 TP 票號標籤
function addTpTicket(ticketNumber) {
    const trimmedTicket = ticketNumber.trim().toUpperCase();
    
    // 驗證格式
    if (!validateTpTicketFormat(trimmedTicket)) {
        showTpInputError('TP 票號格式無效，請使用格式：TP-XXXXX');
        return false;
    }
    
    // 檢查重複
    if (isDuplicateTicket(trimmedTicket)) {
        showTpInputError('此 TP 票號已存在');
        return false;
    }
    
    // 添加到列表
    currentTpTickets.push(trimmedTicket);
    
    // 更新顯示
    renderTpTags();
    
    // 清空輸入欄位
    const inputElement = document.getElementById('relatedTpTicketsInput');
    if (inputElement) {
        inputElement.value = '';
        clearTpInputError();
    }
    
    return true;
}

// 移除 TP 票號標籤
function removeTpTicket(ticketNumber) {
    const index = currentTpTickets.indexOf(ticketNumber);
    if (index > -1) {
        currentTpTickets.splice(index, 1);
        renderTpTags();
    }
}

// 渲染 TP 標籤列表
function renderTpTags() {
    const tagsContainer = document.getElementById('tpTicketTags');
    const displayContainer = document.getElementById('tpTicketsDisplay');
    
    if (!tagsContainer || !displayContainer) return;
    
    // 如果沒有標籤，隱藏顯示區域
    if (currentTpTickets.length === 0) {
        displayContainer.style.display = 'none';
        tagsContainer.innerHTML = '';
        return;
    }
    
    // 顯示標籤區域
    displayContainer.style.display = 'block';
    
    // 生成標籤 HTML
    const tagsHtml = currentTpTickets.map(ticket => `
        <div class="tp-ticket-tag" data-ticket="${ticket}">
            <i class="fas fa-ticket-alt me-1"></i>
            <span>${ticket}</span>
            <button type="button" class="remove-btn" 
                    onclick="removeTpTicket('${ticket}')"
                    title="移除此票號"
                    aria-label="移除 ${ticket}">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `).join('');
    
    tagsContainer.innerHTML = tagsHtml;
    
    // 為所有 TP 標籤添加 hover 事件監聽器
    const ticketTags = tagsContainer.querySelectorAll('.tp-ticket-tag');
    ticketTags.forEach(tag => {
        const ticketNumber = tag.getAttribute('data-ticket');
        // 添加 hover 事件
        tag.addEventListener('mouseenter', (e) => showJiraPreview(e, ticketNumber));
        tag.addEventListener('mouseleave', hideJiraPreview);
        // 添加點擊跳轉事件
        tag.addEventListener('click', (e) => {
            // 如果點擊的是刪除按鈕，不執行跳轉
            if (e.target.closest('.remove-btn')) return;
            openJiraTicket(ticketNumber);
        });
    });
}

// 顯示輸入錯誤提示
function showTpInputError(message) {
    const inputElement = document.getElementById('relatedTpTicketsInput');
    if (!inputElement) return;
    
    // 移除現有的錯誤樣式
    clearTpInputError();
    
    // 添加錯誤樣式
    inputElement.classList.add('is-invalid');
    
    // 創建或更新錯誤訊息元素
    let errorElement = document.getElementById('tpTicketInputError');
    if (!errorElement) {
        errorElement = document.createElement('div');
        errorElement.id = 'tpTicketInputError';
        errorElement.className = 'invalid-feedback d-block';
        inputElement.parentNode.appendChild(errorElement);
    }
    
    errorElement.textContent = message;
    
    // 3秒後自動清除錯誤
    setTimeout(clearTpInputError, 3000);
}

// 清除輸入錯誤提示
function clearTpInputError() {
    const inputElement = document.getElementById('relatedTpTicketsInput');
    const errorElement = document.getElementById('tpTicketInputError');
    
    if (inputElement) {
        inputElement.classList.remove('is-invalid');
    }
    
    if (errorElement) {
        errorElement.remove();
    }
}

// 初始化 TP 標籤輸入功能
function initTpTicketInput() {
    const inputElement = document.getElementById('relatedTpTicketsInput');
    if (!inputElement) return;
    
    // Enter 鍵監聽
    inputElement.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            const value = this.value.trim();
            if (value) {
                addTpTicket(value);
            }
        }
    });
    
    // 失去焦點時也可以添加標籤（可選）
    inputElement.addEventListener('blur', function() {
        const value = this.value.trim();
        if (value && validateTpTicketFormat(value) && !isDuplicateTicket(value)) {
            addTpTicket(value);
        }
    });
    
    // 清除錯誤樣式當用戶開始輸入
    inputElement.addEventListener('input', function() {
        if (this.classList.contains('is-invalid')) {
            clearTpInputError();
        }
    });
}

// 獲取當前 TP 票號列表（用於表單提交）
function getCurrentTpTickets() {
    return [...currentTpTickets]; // 返回副本避免意外修改
}

// 設置 TP 票號列表（用於編輯模式）
function setTpTickets(tickets) {
    currentTpTickets = Array.isArray(tickets) ? [...tickets] : [];
    renderTpTags();
}

// 清空所有 TP 票號
function clearAllTpTickets() {
    currentTpTickets = [];
    renderTpTags();
    clearTpInputError();
}

// ===== Test Run Set TP 票號輸入功能 =====

function initSetTpTicketInput() {
    if (setTpInputInitialized) return;
    const inputElement = document.getElementById('setTpTicketsInput');
    if (!inputElement) return;

    setTpInputInitialized = true;

    inputElement.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            const value = this.value.trim();
            if (value) {
                addSetTpTicket(value);
            }
        }
    });

    inputElement.addEventListener('blur', function() {
        const value = this.value.trim();
        if (value) {
            addSetTpTicket(value);
        }
    });
}

function addSetTpTicket(ticketNumber) {
    const trimmed = ticketNumber.trim().toUpperCase();
    if (!trimmed) {
        return false;
    }

    if (!validateTpTicketFormat(trimmed)) {
        const message = window.i18n?.t('messages.invalidTpTicketFormat') || 'TP 票號格式不正確（需要 TP-12345）';
        showSetTpInputError(message);
        return false;
    }

    if (currentSetTpTickets.includes(trimmed)) {
        const message = window.i18n?.t('messages.duplicateTpTicket') || 'TP 票號已重複';
        showSetTpInputError(message);
        return false;
    }

    currentSetTpTickets.push(trimmed);
    renderSetTpTags();

    const inputElement = document.getElementById('setTpTicketsInput');
    if (inputElement) {
        inputElement.value = '';
    }
    clearSetTpInputError();
    return true;
}

function removeSetTpTicket(ticketNumber) {
    const index = currentSetTpTickets.indexOf(ticketNumber);
    if (index > -1) {
        currentSetTpTickets.splice(index, 1);
        renderSetTpTags();
    }
}

function renderSetTpTags() {
    const tagsContainer = document.getElementById('setTpTicketTags');
    const displayContainer = document.getElementById('setTpTicketsDisplay');
    const countBadge = document.getElementById('setTpTicketsCount');

    if (!tagsContainer || !displayContainer) return;

    if (currentSetTpTickets.length === 0) {
        displayContainer.style.display = 'none';
        tagsContainer.innerHTML = '';
        if (countBadge) countBadge.textContent = '0';
        return;
    }

    displayContainer.style.display = 'block';
    if (countBadge) countBadge.textContent = String(currentSetTpTickets.length);

    tagsContainer.innerHTML = currentSetTpTickets.map(ticket => {
        const safe = escapeHtml(ticket);
        return `
            <div class="tp-ticket-tag" data-ticket="${safe}">
                <i class="fas fa-ticket-alt me-1"></i>
                <span>${safe}</span>
                <button type="button" class="remove-btn" onclick="removeSetTpTicket('${safe}')" aria-label="移除 ${safe}">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `;
    }).join('');

    const ticketTags = tagsContainer.querySelectorAll('.tp-ticket-tag');
    ticketTags.forEach(tag => {
        const ticketNumber = tag.getAttribute('data-ticket');
        tag.addEventListener('mouseenter', (e) => showJiraPreview(e, ticketNumber));
        tag.addEventListener('mouseleave', hideJiraPreview);
        tag.addEventListener('click', (e) => {
            if (e.target.closest('.remove-btn')) return;
            openJiraTicket(ticketNumber);
        });
    });
}

function setSetTpTickets(tickets) {
    currentSetTpTickets = Array.isArray(tickets) ? [...tickets] : [];
    renderSetTpTags();
    clearSetTpInputError();
}

function clearAllSetTpTickets() {
    currentSetTpTickets = [];
    renderSetTpTags();
    clearSetTpInputError();
}

function showSetTpInputError(message) {
    const inputElement = document.getElementById('setTpTicketsInput');
    if (!inputElement) return;

    clearSetTpInputError();
    inputElement.classList.add('is-invalid');

    let errorElement = document.getElementById('setTpTicketInputError');
    if (!errorElement) {
        errorElement = document.createElement('div');
        errorElement.id = 'setTpTicketInputError';
        errorElement.className = 'invalid-feedback d-block';
        inputElement.parentNode.appendChild(errorElement);
    }

    errorElement.textContent = message;
    setTimeout(clearSetTpInputError, 3000);
}

function clearSetTpInputError() {
    const inputElement = document.getElementById('setTpTicketsInput');
    const errorElement = document.getElementById('setTpTicketInputError');
    if (inputElement) {
        inputElement.classList.remove('is-invalid');
    }
    if (errorElement) {
        errorElement.remove();
    }
}

function renderSetDetailTpTags(tickets) {
    const section = document.getElementById('setDetailTpSection');
    const container = document.getElementById('setDetailTpTags');
    if (!section || !container) return;

    if (!tickets || tickets.length === 0) {
        section.style.display = 'none';
        container.innerHTML = '';
        return;
    }

    section.style.display = 'block';
    container.innerHTML = tickets.map(ticket => {
        const safe = escapeHtml(ticket);
        return `
            <span class="tp-tag badge bg-secondary me-1" data-ticket="${safe}" style="cursor: pointer;">
                <i class="fas fa-ticket-alt me-1"></i>${safe}
            </span>
        `;
    }).join('');

    container.querySelectorAll('.tp-tag').forEach(tag => {
        const ticketNumber = tag.getAttribute('data-ticket');
        tag.addEventListener('mouseenter', (e) => showJiraPreview(e, ticketNumber));
        tag.addEventListener('mouseleave', hideJiraPreview);
        tag.addEventListener('click', () => openJiraTicket(ticketNumber));
    });
}

// === TP 票號 JIRA 預覽功能 ===

// JIRA 票號資料快取
const jiraDataCache = new Map();

// 創建或獲取 tooltip 元素
