/* ============================================================
   TEST RUN MANAGEMENT - NOTIFICATIONS
   ============================================================ */

function initNotificationSettings() {
    const enabledEl = document.getElementById('notificationsEnabled');
    const sectionEl = document.getElementById('notificationGroupsSection');
    const searchBtn = document.getElementById('searchGroupsBtn');
    const searchInput = document.getElementById('notifyGroupsInput');

    if (!enabledEl || !sectionEl) return;

    const toggleSection = () => {
        if (enabledEl.checked) {
            sectionEl.style.display = '';
            sectionEl.classList.add('notification-groups-entering');
            requestAnimationFrame(() => {
                sectionEl.classList.remove('notification-groups-entering');
                sectionEl.classList.add('notification-groups-entered');
            });
        } else {
            sectionEl.classList.remove('notification-groups-entered');
            sectionEl.classList.add('notification-groups-exiting');
            setTimeout(() => {
                sectionEl.classList.remove('notification-groups-exiting');
                sectionEl.style.display = 'none';
            }, 150);
        }
    };

    enabledEl.onchange = toggleSection;
    toggleSection();

    if (searchBtn && searchInput) {
        searchBtn.onclick = () => performGroupSearch(searchInput.value.trim());
        searchInput.onkeydown = (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                performGroupSearch(searchInput.value.trim());
            }
        };
    }
}

// ===== URL 工具：確保 team_id 反映在網址列（不重新載入頁面） =====
function ensureTeamIdInUrl_TRM(teamId) {
    try {
        const url = new URL(window.location.href);
        const before = url.searchParams.get('team_id');
        if (String(before || '') !== String(teamId)) {
            url.searchParams.set('team_id', teamId);
            history.replaceState(null, '', `${url.pathname}?${url.searchParams.toString()}`);
        }
    } catch (_) {}
}

function clearNotificationSettings() {
    const enabledEl = document.getElementById('notificationsEnabled');
    const sectionEl = document.getElementById('notificationGroupsSection');
    const resultsEl = document.getElementById('groupSearchResults');
    const tagsEl = document.getElementById('selectedGroupsTags');
    const countEl = document.getElementById('selectedGroupsCount');
    const displayEl = document.getElementById('selectedGroupsDisplay');
    const searchInput = document.getElementById('notifyGroupsInput');

    if (enabledEl) enabledEl.checked = false;
    if (sectionEl) sectionEl.style.display = 'none';
    if (resultsEl) resultsEl.style.display = 'none', resultsEl.innerHTML = '';
    if (tagsEl) tagsEl.innerHTML = '';
    if (countEl) countEl.textContent = '0';
    if (displayEl) displayEl.style.display = 'none';
    if (searchInput) searchInput.value = '';

    selectedNotifyGroups = [];
}

let selectedNotifyGroups = [];

function loadNotificationSettings(enabled, chatIds, chatNames) {
    const enabledEl = document.getElementById('notificationsEnabled');
    const sectionEl = document.getElementById('notificationGroupsSection');
    enabledEl.checked = !!enabled;
    if (enabled) {
        sectionEl.style.display = '';
    }
    selectedNotifyGroups = [];
    if (Array.isArray(chatIds)) {
        for (let i = 0; i < chatIds.length; i++) {
            const id = chatIds[i];
            const name = (Array.isArray(chatNames) && chatNames[i]) ? chatNames[i] : id;
            selectedNotifyGroups.push({ chat_id: id, name });
        }
    }
    renderSelectedGroups();
}

async function performGroupSearch(keyword) {
    const resultsEl = document.getElementById('groupSearchResults');
    resultsEl.style.display = '';
    resultsEl.innerHTML = `<div class="text-muted small"><i class="fas fa-spinner fa-spin me-2"></i>${window.i18n ? window.i18n.t('testRun.notifications.searchingGroups') : '搜尋群組中...'}</div>`;
    try {
        const url = new URL('/api/integrations/lark/groups', window.location.origin);
        if (keyword) url.searchParams.set('q', keyword);
        const resp = await window.AuthClient.fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (!Array.isArray(data) || data.length === 0) {
            resultsEl.innerHTML = `<div class="text-muted small"><i class="fas fa-info-circle me-2"></i>${window.i18n ? window.i18n.t('testRun.notifications.noGroupsFound') : '找不到符合條件的群組'}</div>`;
            return;
        }
        resultsEl.innerHTML = data.map(g => renderGroupSearchItem(g)).join('');
        // 綁定點擊事件
        resultsEl.querySelectorAll('.group-search-item').forEach(el => {
            el.addEventListener('click', () => {
                const id = el.getAttribute('data-chat-id');
                const name = el.getAttribute('data-name');
                addSelectedGroup({ chat_id: id, name });
            });
        });
    } catch (e) {
        resultsEl.innerHTML = `<div class="text-danger small"><i class="fas fa-exclamation-triangle me-2"></i>${window.i18n ? window.i18n.t('testRun.notifications.searchError') : '搜尋群組失敗'}</div>`;
    }
}

function renderGroupSearchItem(group) {
    const id = escapeHtml(group.chat_id || '');
    const name = escapeHtml(group.name || id);
    return `
        <div class="group-search-item" data-chat-id="${id}" data-name="${name}">
            <i class="fas fa-users group-icon"></i>
            <span class="group-name">${name}</span>
            <code class="group-id">${id}</code>
        </div>
    `;
}

function addSelectedGroup(group) {
    if (!group || !group.chat_id) return;
    // 去重
    const exists = selectedNotifyGroups.some(g => g.chat_id === group.chat_id);
    if (exists) return;
    if (selectedNotifyGroups.length >= 100) {
        AppUtils.showWarning && AppUtils.showWarning(window.i18n ? window.i18n.t('testRun.notifications.maxGroupsReached') : '最多選擇 100 個群組');
        return;
    }
    selectedNotifyGroups.push({ chat_id: group.chat_id, name: group.name || group.chat_id });
    renderSelectedGroups();
}

function removeSelectedGroup(chatId) {
    selectedNotifyGroups = selectedNotifyGroups.filter(g => g.chat_id !== chatId);
    renderSelectedGroups();
}

function renderSelectedGroups() {
    const displayEl = document.getElementById('selectedGroupsDisplay');
    const tagsEl = document.getElementById('selectedGroupsTags');
    const countEl = document.getElementById('selectedGroupsCount');
    if (!tagsEl || !countEl || !displayEl) return;

    if (selectedNotifyGroups.length === 0) {
        displayEl.style.display = 'none';
        tagsEl.innerHTML = '';
        countEl.textContent = '0';
        return;
    }
    displayEl.style.display = '';
    countEl.textContent = String(selectedNotifyGroups.length);
    tagsEl.innerHTML = selectedNotifyGroups.map(g => renderSelectedGroupTag(g)).join('');
    // 綁定移除按鈕
    tagsEl.querySelectorAll('.group-remove-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.getAttribute('data-chat-id');
            removeSelectedGroup(id);
        });
    });
}

function renderSelectedGroupTag(group) {
    const id = escapeHtml(group.chat_id || '');
    const name = escapeHtml(group.name || id);
    return `
        <span class="selected-group-tag">
            <i class="fas fa-users"></i>${name}
            <button type="button" class="group-remove-btn" data-chat-id="${id}" title="${window.i18n ? window.i18n.t('testRun.notifications.removeGroup') : '移除群組'}"><i class="fas fa-times"></i></button>
        </span>
    `;
}

function getCurrentNotificationSettings() {
    const enabled = !!document.getElementById('notificationsEnabled')?.checked;
    const chatIds = selectedNotifyGroups.map(g => g.chat_id);
    const chatNames = selectedNotifyGroups.map(g => g.name || g.chat_id);
    return { enabled, chatIds, chatNames };
}

function renderSetDetailTpTags(tickets) {
    const container = document.getElementById('setDetailTpTags');
    const section = document.getElementById('setDetailTpSection');
    
    if (!tickets || tickets.length === 0) {
        if (section) section.style.display = 'none';
        if (container) container.innerHTML = '';
        return;
    }
    
    if (section) section.style.display = 'block';
    if (container) {
        container.innerHTML = tickets.map(ticket => 
            `<span class="tcg-tag me-1" 
                   onmouseenter="showJiraPreview(event, '${escapeHtml(ticket)}')"
                   onmouseleave="hideJiraPreview()"
                   onclick="event.stopPropagation(); openJiraTicket('${escapeHtml(ticket)}')"
                   style="cursor: pointer;">${escapeHtml(ticket)}</span>`
        ).join('');
    }
}
