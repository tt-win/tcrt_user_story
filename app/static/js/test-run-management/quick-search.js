/* ============================================================
   TEST RUN MANAGEMENT - QUICK SEARCH
   ============================================================ */

function getSearchResultStatusInfo(status, executionRate, passRate) {
    // 使用與主卡片相同的狀態樣式
    const statusClass = getStatusClass(status);
    const statusText = getStatusText(status);
    
    return {
        statusClass: statusClass,
        statusText: statusText,
        showProgress: status === 'active'
    };
}

function setupQuickSearch_TPTicket() {
    if (!document.getElementById('quickSearchTPOverlay')) {
        const overlay = document.createElement('div');
        overlay.id = 'quickSearchTPOverlay';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:1060;display:none;background:rgba(0,0,0,0.35)';
        overlay.innerHTML = `
          <div class="position-fixed" style="top:34vh; left:50%; transform: translateX(-50%); width:min(800px, 95vw);">
            <div class="card shadow">
              <div class="card-body p-3">
                <input id="quickSearchTPInput" type="text" class="form-control form-control-lg" placeholder="${window.i18n ? window.i18n.t('tp.searchPlaceholder') : '搜尋 TP 票號...'}" autocomplete="off" />
                <div id="quickSearchTPResults" class="list-group list-group-flush" style="max-height:30vh; overflow-y:auto; overflow-x:hidden; padding: 0 4px;"></div>
              </div>
            </div>
          </div>`;
        document.body.appendChild(overlay);
        
        try {
            const applyPlaceholder = () => {
                const input = overlay.querySelector('#quickSearchTPInput');
                if (!input) return;
                if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
                    let text = window.i18n.t('tp.searchPlaceholder');
                    if (!text || text === 'tp.searchPlaceholder') {
                        text = '搜尋 TP 票號...';
                    }
                    input.placeholder = text;
                } else {
                    input.placeholder = '搜尋 TP 票號...';
                }
            };
            
            // 立即嘗試設置
            applyPlaceholder();
            
            // 語言切換時更新
            document.addEventListener('languageChanged', applyPlaceholder);
            
            // 如果翻譯系統還未準備好，監聽 i18nReady 事件
            if (!window.i18n || !window.i18n.isReady || !window.i18n.isReady()) {
                document.addEventListener('i18nReady', applyPlaceholder);
            }
        } catch (_) {}
        
        overlay.addEventListener('click', (e) => { 
            if(e.target === overlay) closeQuickSearchTP(); 
        });
    }

    // 鍵盤事件監聽器 - "/" 鍵觸發搜尋
    document.addEventListener('keydown', function(e) {
        const tag = (e.target && e.target.tagName || '').toLowerCase();
        const isTyping = ['input','textarea','select'].includes(tag) || (e.target && e.target.isContentEditable);
        if (!isTyping && e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            openQuickSearchTP();
        }
    });
}

// 底部左側 TP 搜尋提示
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('quickSearchTPHint')) return;
    const hint = document.createElement('div');
    hint.id = 'quickSearchTPHint';
    hint.className = 'position-fixed';
    hint.style.cssText = 'left:12px; bottom:12px; z-index:1040; opacity:0.85; pointer-events:none;';
    const label = window.i18n && window.i18n.isReady() ? window.i18n.t('hotkeys.quickSearchTP') : '按 / 快速搜尋 TP 票號';
    hint.innerHTML = `<span class="badge bg-secondary-subtle text-secondary border" style="--bs-bg-opacity:.65;">${label}</span>`;
    document.body.appendChild(hint);
    
    // i18n 準備完成時也同步更新
    document.addEventListener('i18nReady', () => {
        const text = window.i18n ? window.i18n.t('hotkeys.quickSearchTP') : '按 / 快速搜尋 TP 票號';
        const badge = document.querySelector('#quickSearchTPHint .badge');
        if (badge) badge.textContent = text;
    });
    document.addEventListener('languageChanged', () => {
        const text = window.i18n ? window.i18n.t('hotkeys.quickSearchTP') : '按 / 快速搜尋 TP 票號';
        const badge = document.querySelector('#quickSearchTPHint .badge');
        if (badge) badge.textContent = text;
    });
});

// T030: Debounce 函數 - 延遲執行搜尋，減少 API 呼叫
function debounce(func, delay) {
    let timeoutId;
    return function (...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(this, args), delay);
    };
}

// T031: 關鍵字高亮顯示函數 - 在搜尋結果中高亮顯示匹配的關鍵字
function highlightSearchTerm(text, searchTerm) {
    if (!text || !searchTerm || searchTerm.trim().length === 0) {
        return escapeHtml(text || '');
    }
    
    const escapedText = escapeHtml(text);
    const escapedTerm = escapeHtml(searchTerm.trim());
    
    // 使用不區分大小寫的全局替換
    const regex = new RegExp(`(${escapedTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    return escapedText.replace(regex, '<mark class="bg-warning bg-opacity-50 rounded px-1">$1</mark>');
}

// T032: 搜尋歷史記錄管理 - 使用 localStorage 儲存最近搜尋記錄
const tpSearchHistory = {
    key: 'tp_search_history',
    maxItems: 10,
    
    // 獲取搜尋歷史
    get() {
        try {
            const history = localStorage.getItem(this.key);
            return history ? JSON.parse(history) : [];
        } catch (e) {
            console.warn('無法讀取搜尋歷史:', e);
            return [];
        }
    },
    
    // 添加搜尋記錄
    add(searchTerm) {
        if (!searchTerm || searchTerm.trim().length === 0) return;
        
        const term = searchTerm.trim();
        let history = this.get();
        
        // 移除重複項目
        history = history.filter(item => item !== term);
        
        // 添加到開頭
        history.unshift(term);
        
        // 限制數量
        if (history.length > this.maxItems) {
            history = history.slice(0, this.maxItems);
        }
        
        try {
            localStorage.setItem(this.key, JSON.stringify(history));
        } catch (e) {
            console.warn('無法儲存搜尋歷史:', e);
        }
    },
    
    // 清空歷史
    clear() {
        try {
            localStorage.removeItem(this.key);
        } catch (e) {
            console.warn('無法清空搜尋歷史:', e);
        }
    }
};

// T032: 渲染搜尋歷史記錄
function renderSearchHistory(container) {
    const history = tpSearchHistory.get();
    if (history.length === 0) {
        container.innerHTML = `<div class="list-group-item text-center text-muted py-3 border-0">
            <small><i class="fas fa-history me-2"></i>${window.i18n ? window.i18n.t('search.noHistory') : '尚無搜尋歷史'}</small>
        </div>`;
        return;
    }

    container.innerHTML = history.map((term, idx) => `
        <button type="button" class="list-group-item list-group-item-action d-flex align-items-center py-2 ${idx===0?'active':''}" 
                data-search-term="${escapeHtml(term)}">
            <i class="fas fa-history text-muted me-3" style="width: 16px;"></i>
            <span class="flex-grow-1">${escapeHtml(term)}</span>
            <small class="text-muted">${window.i18n ? window.i18n.t('search.recent') : '最近'}</small>
        </button>
    `).join('');

    const buttons = container.querySelectorAll('.list-group-item-action');
    buttons.forEach((btn, idx) => {
        if (idx === 0) {
            btn.classList.add('quick-search-active');
            btn.classList.add('active');
        } else {
            btn.classList.remove('quick-search-active');
        }
    });

    // 綁定點擊事件 - 點擊歷史記錄項目直接搜尋
    container.querySelectorAll('[data-search-term]').forEach(btn => {
        btn.addEventListener('click', () => {
            const term = btn.getAttribute('data-search-term');
            const input = document.getElementById('quickSearchTPInput');
            if (input && term) {
                input.value = term;
                input.dispatchEvent(new Event('input'));
            }
        });
    });
}

function openQuickSearchTP() {
    const overlay = document.getElementById('quickSearchTPOverlay');
    const input = document.getElementById('quickSearchTPInput');
    const results = document.getElementById('quickSearchTPResults');
    if (!overlay || !input || !results) return;
    
    overlay.style.display = 'block';
    input.value = '';
    results.innerHTML = '';
    input.focus();
    
    // T032: 初始顯示搜尋歷史記錄
    renderSearchHistory(results);

    const handleKey = (e) => {
        if (e.key === 'Escape') { 
            closeQuickSearchTP(); 
            return; 
        }
        if (e.key === 'Enter') {
            const active = results.querySelector('.active');
            if (active) { 
                active.click(); 
            }
        } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            // T032: 同時處理搜尋結果和歷史記錄項目
            const items = Array.from(results.querySelectorAll('.quick-search-tp-item, .list-group-item-action'));
            if (items.length === 0) return;
            let idx = items.findIndex(li => li.classList.contains('active'));
            if (idx < 0) idx = 0;
            idx = (e.key === 'ArrowDown') ? Math.min(idx+1, items.length-1) : Math.max(idx-1, 0);
            items.forEach(li => {
                li.classList.remove('active');
                li.classList.remove('quick-search-active');
            });
            items[idx].classList.add('active');
            items[idx].classList.add('quick-search-active');
            items[idx].scrollIntoView({ block:'nearest' });
        }
    };
    
    input.onkeydown = handleKey;
    
    // T030: 使用 debounce 優化搜尋，300ms 延遲減少 API 呼叫
    const debouncedSearch = debounce((query) => {
        quickSearchRenderTP(query, results);
    }, 300);
    
    input.oninput = () => {
        const query = input.value.trim();
        
        // T032: 如果查詢為空，顯示搜尋歷史記錄
        if (query.length === 0) {
            renderSearchHistory(results);
            return;
        }
        
        // 顯示搜尋中狀態（立即響應）
        if (query.length >= 1) {
            results.innerHTML = `<div class="list-group-item text-muted d-flex align-items-center">
                <div class="spinner-border spinner-border-sm me-2" role="status"></div>
                ${window.i18n ? window.i18n.t('common.searching') : '搜尋中...'}
            </div>`;
        }
        
        // 延遲執行實際搜尋
        debouncedSearch(query);
    };
}

function closeQuickSearchTP() {
    const overlay = document.getElementById('quickSearchTPOverlay');
    if (overlay) overlay.style.display = 'none';
}

// T027: TP 票號搜尋結果渲染 (含快取優化)
function quickSearchRenderTP(query, container) {
    const q = (query || '').trim().toUpperCase();
    if (q.length === 0) {
        container.innerHTML = '';
        return;
    }
    
    const currentTeamId = AppUtils.getCurrentTeamId();
    if (!currentTeamId) {
        container.innerHTML = `<div class="list-group-item text-muted">${window.i18n ? window.i18n.t('errors.noTeamSelected') : '請先選擇團隊'}</div>`;
        return;
    }
    
    const limit = 20;

    // T027: 檢查快取
    const cachedResult = tpSearchCache.get(q, currentTeamId, limit);
    if (cachedResult) {
        renderSearchResults(cachedResult, container, q);
        return;
    }
    
    // 顯示載入中
    container.innerHTML = `<div class="list-group-item text-muted d-flex align-items-center">
        <div class="spinner-border spinner-border-sm me-2" role="status"></div>
        ${window.i18n ? window.i18n.t('common.searching') : '搜尋中...'}
    </div>`;
    
    const configsUrl = `/api/test-run-configs/search/tp?q=${encodeURIComponent(q)}&team_id=${currentTeamId}&limit=${limit}`;
    const setsUrl = `/api/teams/${currentTeamId}/test-run-sets/search/tp?q=${encodeURIComponent(q)}&limit=${limit}`;

    const configRequest = window.AuthClient.fetch(configsUrl)
        .then(response => {
            if (!response.ok) throw new Error(`Config search failed: ${response.status}`);
            return response.json();
        });

    const setRequest = window.AuthClient.fetch(setsUrl)
        .then(response => {
            if (!response.ok) throw new Error(`Set search failed: ${response.status}`);
            return response.json();
        })
        .catch(error => {
            console.warn('Test Run Set search failed:', error);
            return [];
        });

    Promise.all([configRequest, setRequest])
        .then(([configData, setData]) => {
            const payload = { configs: configData, sets: setData };
            tpSearchCache.set(q, currentTeamId, limit, payload);
            renderSearchResults(payload, container, q);
        })
        .catch(error => {
            console.error('TP 搜尋 API 錯誤:', error);
            container.innerHTML = `<div class="quick-search-tp-no-results text-danger">${window.i18n ? window.i18n.t('errors.searchFailed') : '搜尋失敗，請稍後再試'}</div>`;
        });
}

// T027 + T028: 快速搜尋結果渲染 (簡潔下拉選單風格)
function renderSearchResults(data, container, searchTerm = '') {
    let configs = [];
    let sets = [];

    if (Array.isArray(data)) {
        configs = data;
    } else if (data && typeof data === 'object') {
        configs = Array.isArray(data.configs) ? data.configs : [];
        sets = Array.isArray(data.sets) ? data.sets : [];
    }

    if (configs.length === 0 && sets.length === 0) {
        container.innerHTML = `<div class="list-group-item text-center text-muted py-3 border-0">
            <small><i class="fas fa-search me-2"></i>${window.i18n ? window.i18n.t('errors.noMatchingTPConfigs') : '沒有找到符合條件的 TP 票號配置'}</small>
        </div>`;
        return;
    }

    const sections = [];
    const setHeading = window.i18n ? (window.i18n.t('testRun.quickSearch.testRunSetsHeading') || window.i18n.t('testRun.sets.heading')) : 'Test Run Sets';
    const runHeading = window.i18n ? (window.i18n.t('testRun.quickSearch.testRunsHeading') || 'Test Runs') : 'Test Runs';

    if (sets.length > 0) {
        sections.push(`<div class="list-group-item text-muted small fw-semibold bg-light border-0">${escapeHtml(setHeading || 'Test Run Sets')}</div>`);
        sections.push(sets.map(set => buildSetSearchItem(set, searchTerm)).join(''));
    }

    if (configs.length > 0) {
        sections.push(`<div class="list-group-item text-muted small fw-semibold bg-light border-0">${escapeHtml(runHeading || 'Test Runs')}</div>`);
        sections.push(configs.map(config => buildConfigSearchItem(config, searchTerm)).join(''));
    }

    container.innerHTML = sections.join('');

    const items = Array.from(container.querySelectorAll('.quick-search-tp-item'));
    if (items.length) {
        items[0].classList.add('quick-search-active', 'active');
    }

    items.forEach(btn => {
        btn.addEventListener('click', () => {
            const configId = btn.getAttribute('data-config-id');
            const setId = btn.getAttribute('data-set-id');
            const searchTermValue = btn.getAttribute('data-search-term');

            if (searchTermValue && searchTermValue.trim().length >= 2) {
                tpSearchHistory.add(searchTermValue.trim());
            }

            closeQuickSearchTP();

            if (configId) {
                const teamId = (typeof AppUtils.getCurrentTeamId === 'function') ? AppUtils.getCurrentTeamId() : (AppUtils.getCurrentTeam()?.id ?? '');
                const params = new URLSearchParams({ config_id: String(configId) });
                if (teamId) params.set('team_id', String(teamId));
                window.location.href = `/test-run-execution?${params.toString()}`;
            } else if (setId) {
                openTestRunSetDetail(Number(setId));
            }
        });
    });
}

function buildConfigSearchItem(config, searchTerm) {
    const statusInfo = getSearchResultStatusInfo(config.status, config.execution_rate, config.pass_rate);

    let tpDisplay = '';
    if (config.related_tp_tickets && Array.isArray(config.related_tp_tickets) && config.related_tp_tickets.length > 0) {
        const maxDisplay = 3;
        const visibleTickets = config.related_tp_tickets.slice(0, maxDisplay);
        const remainingCount = config.related_tp_tickets.length - maxDisplay;

        const tpTags = visibleTickets.map(ticket =>
            `<span class="tp-tag badge bg-secondary me-1">${highlightSearchTerm(ticket, searchTerm)}</span>`
        ).join('');

        const remainingTag = remainingCount > 0
            ? `<span class="badge bg-light text-dark" style="font-size: 0.75rem;">+${remainingCount}</span>`
            : '';

        tpDisplay = `<span class="d-inline-flex flex-wrap align-items-center gap-1">${tpTags}${remainingTag}</span>`;
    }

    const envInfo = config.test_environment || '';
    const buildInfo = config.build_number || '';
    const envBuildDisplay = [envInfo, buildInfo].filter(Boolean).join(' • ');

    return `
        <button type="button" class="list-group-item list-group-item-action quick-search-tp-item py-3 px-4 w-100 text-start"
                data-result-type="config" data-config-id="${config.id}" data-search-term="${escapeHtml(searchTerm)}">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1 min-width-0 pe-3">
                    <div class="d-flex align-items-center mb-1">
                        <i class="fas fa-play stats-icon me-2"></i>
                        <span class="fw-medium text-dark result-title" style="font-size: 1rem;">${highlightSearchTerm(config.name || '', searchTerm)}</span>
                        <span class="status-badge ${statusInfo.statusClass} ms-2 flex-shrink-0" style="font-size: 0.7rem; padding: 0.15rem 0.4rem;">
                            ${statusInfo.statusText}
                        </span>
                    </div>
                    <div class="small text-muted">
                        ${tpDisplay ? `<span class="me-3"><i class="fas fa-ticket-alt stats-icon"></i>${tpDisplay}</span>` : ''}
                        ${envBuildDisplay ? `<span class="me-3"><i class="fas fa-server stats-icon"></i>${escapeHtml(envBuildDisplay)}</span>` : ''}
                        <span><i class="fas fa-list-ul stats-icon"></i>${config.total_test_cases || 0} 案例</span>
                        ${statusInfo.showProgress ? ` • <i class="fas fa-clock stats-icon"></i> ${Math.round(config.execution_rate || 0)}% 執行` : ''}
                    </div>
                </div>
            </div>
        </button>
    `;
}

function buildSetSearchItem(set, searchTerm) {
    const statusInfo = getSearchResultStatusInfo(set.status || 'active', 0, 0);
    const matchingTickets = Array.isArray(set.related_tp_tickets) ? set.related_tp_tickets : [];
    const maxDisplay = 3;
    const visibleTickets = matchingTickets.slice(0, maxDisplay);
    const remainingCount = matchingTickets.length - maxDisplay;
    let tpTags = '';
    let tpMeta = '';
    if (visibleTickets.length > 0) {
        const badges = visibleTickets.map(ticket =>
            `<span class="tp-tag badge bg-secondary me-1">${highlightSearchTerm(ticket, searchTerm)}</span>`
        ).join('');
        const remaining = remainingCount > 0
            ? `<span class="badge bg-light text-dark ms-1" style="font-size: 0.75rem;">+${remainingCount}</span>`
            : '';
        tpMeta = `<span class="d-inline-flex align-items-center gap-1">${badges}${remaining}</span>`;
    }

    const totalRunsLabel = window.i18n ? (window.i18n.t('testRun.sets.card.totalRuns') || '包含 Test Run') : 'Test Runs';

    return `
        <button type="button" class="list-group-item list-group-item-action quick-search-tp-item py-3 px-4 w-100 text-start"
                data-result-type="set" data-set-id="${set.id}" data-search-term="${escapeHtml(searchTerm)}">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1 min-width-0 pe-3">
                    <div class="d-flex align-items-center mb-1">
                        <i class="fas fa-layer-group stats-icon me-2"></i>
                        <span class="fw-medium text-dark result-title" style="font-size: 1rem;">${highlightSearchTerm(set.name || '', searchTerm)}</span>
                        <span class="status-badge ${statusInfo.statusClass} ms-2 flex-shrink-0" style="font-size: 0.7rem; padding: 0.15rem 0.4rem;">
                            ${statusInfo.statusText}
                        </span>
                    </div>
                    <div class="small text-muted">
                        <span class="me-3"><i class="fas fa-layer-group stats-icon"></i>${escapeHtml(totalRunsLabel || 'Test Runs')}: ${set.test_run_count || 0}</span>
                        ${tpMeta ? `<span class="me-3"><i class="fas fa-ticket-alt stats-icon"></i>${tpMeta}</span>` : ''}
                    </div>
                </div>
            </div>
        </button>
    `;
}

// 初始化快速搜尋功能
document.addEventListener('DOMContentLoaded', function() {
    setupQuickSearch_TPTicket();
});

// ===== 通知設定相關功能 =====
