/* Test Run Execution - Filters */

// ===== 排序狀態（TRE） =====
let treSortField = 'number'; // number|title|priority|result|assignee|executed
let treSortOrder = 'asc';

function initializeExecutionFilters() {
    if (executionFilterInitialized) return;

    executionFilterPanelEl = document.getElementById('executionFilterPanel');
    executionFilterToggleBtn = document.getElementById('executionFilterToggle');

    if (!executionFilterPanelEl || !executionFilterToggleBtn) {
        return;
    }

    executionFilterPanelEl.addEventListener('click', (event) => event.stopPropagation());
    executionFilterToggleBtn.addEventListener('click', toggleExecutionFilterPanel);
    executionFilterToggleBtn.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            toggleExecutionFilterPanel();
        }
    });
    executionFilterToggleBtn.setAttribute('aria-expanded', 'false');

    const closeBtn = document.getElementById('closeExecutionFiltersBtn');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => closeExecutionFilterPanel());
    }

    executionFilterInitialized = true;
    retranslateExecutionFilterUI();

    if (!executionFilterI18nBound) {
        executionFilterI18nBound = true;
        try {
            document.addEventListener('i18nReady', retranslateExecutionFilterUI);
        } catch (_) {}
        try {
            document.addEventListener('languageChanged', retranslateExecutionFilterUI);
        } catch (_) {}
        if (window.i18n && typeof window.i18n.on === 'function') {
            try { window.i18n.on('languageChanged', retranslateExecutionFilterUI); } catch (_) {}
            try { window.i18n.on('loaded', retranslateExecutionFilterUI); } catch (_) {}
        }
    }

    const statusCheckboxes = document.querySelectorAll('.execution-status-filter');
    statusCheckboxes.forEach(cb => {
        cb.addEventListener('change', handleExecutionStatusChange);
    });
    updateExecutionStatusFiltersFromUI();

    const caseInput = document.getElementById('filterCaseNumberInput');
    if (caseInput) {
        caseInput.addEventListener('input', debounceExecutionFilter(event => {
            const value = (event && event.target && event.target.value) ? event.target.value : '';
            executionFilterState.searchNumber = value.trim().toLowerCase();
            renderTestRunItems();
        }));
    }

    const titleInput = document.getElementById('filterTitleInput');
    if (titleInput) {
        titleInput.addEventListener('input', debounceExecutionFilter(event => {
            const value = (event && event.target && event.target.value) ? event.target.value : '';
            executionFilterState.searchTitle = value.trim().toLowerCase();
            renderTestRunItems();
        }));
    }

    const prioritySelect = document.getElementById('filterPrioritySelect');
    if (prioritySelect) {
        if (!executionFilterOriginalSelectTexts.has(prioritySelect)) {
            const defaultTexts = {};
            Array.from(prioritySelect.options).forEach(option => {
                defaultTexts[option.value || option.textContent] = option.textContent;
            });
            executionFilterOriginalSelectTexts.set(prioritySelect, defaultTexts);
        }
        prioritySelect.addEventListener('change', (event) => {
            executionFilterState.priority = event.target.value || 'ALL';
            renderTestRunItems();
        });
    }

    const resetBtn = document.getElementById('resetExecutionFiltersBtn');
    if (resetBtn) {
        resetBtn.addEventListener('click', resetExecutionFilters);
    }

    const chipsContainer = document.getElementById('filterAssigneeChips');
    if (chipsContainer) {
        chipsContainer.addEventListener('click', (event) => {
            const target = event.target.closest('[data-remove-index]');
            if (!target) return;
            const index = parseInt(target.dataset.removeIndex, 10);
            if (!isNaN(index)) {
                removeExecutionFilterAssignee(index);
            }
        });
    }

    const assigneeInput = document.getElementById('filterAssigneeInput');
    if (assigneeInput && window.AssigneeSelector) {
        if (executionFilterAssigneeSelector) {
            try { executionFilterAssigneeSelector.destroy(); } catch (_) {}
        }
        executionFilterAssigneeSelector = new AssigneeSelector(assigneeInput, {
            teamId: currentTeamId,
            allowCustomValue: false,
            placeholder: (window.i18n && typeof window.i18n.t === 'function')
                ? window.i18n.t('testRun.filterAssigneePlaceholder')
                : '搜尋並選擇執行者',
            searchPlaceholder: (window.i18n && typeof window.i18n.t === 'function')
                ? window.i18n.t('testRun.filterAssigneePlaceholder')
                : '搜尋並選擇執行者',
            onSelect: (contact) => {
                addExecutionFilterAssignee(contact);
                try { executionFilterAssigneeSelector.setValue(''); } catch (_) {}
                executionFilterAssigneeSelector.selectedContact = null;
                executionFilterAssigneeSelector.originalValue = '';
            }
        });
        executionFilterAssigneeSelector.setValue('');
        executionFilterAssigneeSelector.selectedContact = null;
        executionFilterAssigneeSelector.originalValue = '';
    }

    renderExecutionFilterAssigneeChips();
    updateExecutionFilterSummary(testRunItems.length, testRunItems.length);
}

function toggleExecutionFilterPanel() {
    if (executionFilterIsOpen) {
        closeExecutionFilterPanel();
    } else {
        openExecutionFilterPanel();
    }
}

function positionExecutionFilterPanel() {
    if (!executionFilterPanelEl || !executionFilterToggleBtn) return;

    const rect = executionFilterToggleBtn.getBoundingClientRect();
    const panelRect = executionFilterPanelEl.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;

    let left = rect.left;
    let top = rect.bottom + 8;

    if (left + panelRect.width > viewportWidth - 16) {
        left = viewportWidth - panelRect.width - 16;
    }

    if (left < 16) {
        left = 16;
    }

    if (top + panelRect.height > viewportHeight - 16) {
        top = rect.top - panelRect.height - 8;
    }

    if (top < 16) {
        top = 16;
    }

    executionFilterPanelEl.style.top = `${top}px`;
    executionFilterPanelEl.style.left = `${left}px`;
}

function openExecutionFilterPanel() {
    if (!executionFilterPanelEl || !executionFilterToggleBtn) return;

    executionFilterPanelEl.classList.add('show');
    executionFilterToggleBtn.setAttribute('aria-expanded', 'true');
    executionFilterIsOpen = true;
    positionExecutionFilterPanel();

    if (!executionFilterResizeHandler) {
        executionFilterResizeHandler = () => positionExecutionFilterPanel();
        window.addEventListener('resize', executionFilterResizeHandler);
    }

    document.addEventListener('click', handleExecutionFilterOutsideClick);
    document.addEventListener('keydown', handleExecutionFilterKeydown);
}

function retranslateExecutionFilterUI() {
    if (!executionFilterPanelEl) return;

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(executionFilterPanelEl);
    }

    applyExecutionFilterTranslations();
}

function applyExecutionFilterTranslations() {
    const prioritySelect = document.getElementById('filterPrioritySelect');
    if (!prioritySelect || !executionFilterOriginalSelectTexts.has(prioritySelect)) return;

    const defaultTexts = executionFilterOriginalSelectTexts.get(prioritySelect) || {};
    const options = Array.from(prioritySelect.options);
    options.forEach(option => {
        const originalText = defaultTexts[option.value || option.textContent];
        if (!originalText) return;
        if (window.i18n && typeof window.i18n.t === 'function') {
            const key = option.dataset.i18n;
            if (key) {
                const translated = window.i18n.t(key);
                if (translated && translated !== key) {
                    option.textContent = translated;
                } else {
                    option.textContent = originalText;
                }
            } else {
                option.textContent = originalText;
            }
        } else {
            option.textContent = originalText;
        }
    });

    const assigneeInput = document.getElementById('filterAssigneeInput');
    if (assigneeInput && executionFilterAssigneeSelector) {
        const placeholder = window.i18n && typeof window.i18n.t === 'function'
            ? window.i18n.t('testRun.filterAssigneePlaceholder')
            : '搜尋並選擇執行者';
        executionFilterAssigneeSelector.options.placeholder = placeholder;
        executionFilterAssigneeSelector.options.searchPlaceholder = placeholder;
        executionFilterAssigneeSelector.setValue('');
    }
}

function closeExecutionFilterPanel() {
    if (!executionFilterPanelEl || !executionFilterToggleBtn) return;

    executionFilterPanelEl.classList.remove('show');
    executionFilterToggleBtn.setAttribute('aria-expanded', 'false');
    executionFilterIsOpen = false;

    if (executionFilterResizeHandler) {
        window.removeEventListener('resize', executionFilterResizeHandler);
        executionFilterResizeHandler = null;
    }

    document.removeEventListener('click', handleExecutionFilterOutsideClick);
    document.removeEventListener('keydown', handleExecutionFilterKeydown);
}

function handleExecutionFilterOutsideClick(event) {
    if (!executionFilterPanelEl || !executionFilterToggleBtn) return;
    if (executionFilterPanelEl.contains(event.target) || executionFilterToggleBtn.contains(event.target)) {
        return;
    }
    closeExecutionFilterPanel();
}

function handleExecutionFilterKeydown(event) {
    if (event.key === 'Escape') {
        closeExecutionFilterPanel();
    }
}

function handleExecutionStatusChange(event) {
    const checkbox = event.target;
    if (!checkbox) return;

    const status = checkbox.value;
    if (status === 'ALL') {
        if (checkbox.checked) {
            executionFilterState.statuses = new Set(['ALL']);
            document.querySelectorAll('.execution-status-filter').forEach(cb => {
                if (cb.value !== 'ALL') cb.checked = false;
            });
        }
    } else {
        if (checkbox.checked) {
            executionFilterState.statuses.delete('ALL');
            executionFilterState.statuses.add(status);
            const allCheckbox = document.querySelector('.execution-status-filter[value="ALL"]');
            if (allCheckbox) allCheckbox.checked = false;
        } else {
            executionFilterState.statuses.delete(status);
            if (executionFilterState.statuses.size === 0) {
                executionFilterState.statuses.add('ALL');
                const allCheckbox = document.querySelector('.execution-status-filter[value="ALL"]');
                if (allCheckbox) allCheckbox.checked = true;
            }
        }
    }

    renderTestRunItems();
}

function updateExecutionStatusFiltersFromUI() {
    const checked = Array.from(document.querySelectorAll('.execution-status-filter:checked'));
    if (checked.length === 0) {
        executionFilterState.statuses = new Set(['ALL']);
        const allCheckbox = document.querySelector('.execution-status-filter[value="ALL"]');
        if (allCheckbox) allCheckbox.checked = true;
        return;
    }

    const statuses = new Set();
    checked.forEach(cb => statuses.add(cb.value));

    if (statuses.has('ALL')) {
        executionFilterState.statuses = new Set(['ALL']);
        document.querySelectorAll('.execution-status-filter').forEach(cb => {
            if (cb.value !== 'ALL') cb.checked = false;
        });
    } else {
        executionFilterState.statuses = statuses;
    }
}

function addExecutionFilterAssignee(contact) {
    if (!contact || !contact.name) return;
    const name = contact.name.trim();
    if (!name) return;
    const lower = name.toLowerCase();

    if (!executionFilterState.assignees.some(a => a.lowercase === lower)) {
        executionFilterState.assignees.push({
            name,
            lowercase: lower
        });
        renderExecutionFilterAssigneeChips();
        renderTestRunItems();
    }
}

function removeExecutionFilterAssignee(index) {
    if (index < 0 || index >= executionFilterState.assignees.length) return;
    executionFilterState.assignees.splice(index, 1);
    renderExecutionFilterAssigneeChips();
    renderTestRunItems();
}

function renderExecutionFilterAssigneeChips() {
    const container = document.getElementById('filterAssigneeChips');
    if (!container) return;

    if (executionFilterState.assignees.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = executionFilterState.assignees.map((assignee, idx) => `
        <span class="badge bg-secondary-subtle text-secondary border d-inline-flex align-items-center gap-1" data-remove-index="${idx}">
            <span>${escapeHtml(assignee.name)}</span>
            <i class="fas fa-times"></i>
        </span>
    `).join('');
}

function resetExecutionFilters() {
    executionFilterState.statuses = new Set(['ALL']);
    executionFilterState.searchNumber = '';
    executionFilterState.searchTitle = '';
    executionFilterState.priority = 'ALL';
    executionFilterState.assignees = [];

    document.querySelectorAll('.execution-status-filter').forEach(cb => {
        cb.checked = cb.value === 'ALL';
    });

    const caseInput = document.getElementById('filterCaseNumberInput');
    if (caseInput) caseInput.value = '';

    const titleInput = document.getElementById('filterTitleInput');
    if (titleInput) titleInput.value = '';

    const prioritySelect = document.getElementById('filterPrioritySelect');
    if (prioritySelect) prioritySelect.value = 'ALL';

    if (executionFilterAssigneeSelector) {
        try { executionFilterAssigneeSelector.setValue(''); } catch (_) {}
        executionFilterAssigneeSelector.selectedContact = null;
        executionFilterAssigneeSelector.originalValue = '';
    }

    renderExecutionFilterAssigneeChips();
    renderTestRunItems();
}

function updateExecutionFilterSummary(matched, total) {
    const matchedEl = document.getElementById('executionFilterMatched');
    if (matchedEl) {
        matchedEl.textContent = String(matched);
    }

    const tooltipText = (window.i18n && typeof window.i18n.t === 'function')
        ? window.i18n.t('testRun.filterMatchCount', { matched, total })
        : `${matched} / ${total}`;

    if (executionFilterToggleBtn) {
        executionFilterToggleBtn.setAttribute('title', tooltipText);
        executionFilterToggleBtn.setAttribute('aria-label', tooltipText);
    }
}

function getExecutionItemStatus(item) {
    const result = (item && item.test_result) ? String(item.test_result).trim() : '';
    return result ? result : 'Not Executed';
}

function getFilteredTestRunItems() {
    const numberKeyword = executionFilterState.searchNumber;
    const titleKeyword = executionFilterState.searchTitle;
    const priorityFilter = executionFilterState.priority;
    const assigneeFilters = executionFilterState.assignees.map(a => a.lowercase);
    const matchAllStatuses = executionFilterState.statuses.has('ALL');
    const hasSectionSelections = treSectionFilterIds && treSectionFilterIds.size > 0;

    return (testRunItems || []).filter(item => {
        const itemStatus = getExecutionItemStatus(item);
        if (!matchAllStatuses && !executionFilterState.statuses.has(itemStatus)) {
            return false;
        }

        if (hasSectionSelections) {
            const sid = getItemSectionId(item);
            const key = sid === null || typeof sid === 'undefined' ? 'unassigned' : String(sid);
            if (!treSectionFilterIds.has(key)) return false;
        }

        if (numberKeyword) {
            const numberValue = (item.test_case_number || '').toLowerCase();
            if (!numberValue.includes(numberKeyword)) return false;
        }

        if (titleKeyword) {
            const titleValue = (item.title || '').toLowerCase();
            if (!titleValue.includes(titleKeyword)) return false;
        }

        if (priorityFilter !== 'ALL') {
            if ((item.priority || '') !== priorityFilter) return false;
        }

        if (assigneeFilters.length) {
            const assigneeName = (item.assignee_name || (item.assignee && item.assignee.name) || '').toLowerCase();
            if (!assigneeName) return false;
            if (!assigneeFilters.some(name => assigneeName === name)) return false;
        }

        return true;
    });
}

function setTreSort(field) {
    if (treSortField === field) {
        treSortOrder = (treSortOrder === 'asc') ? 'desc' : 'asc';
    } else {
        treSortField = field;
        treSortOrder = 'asc';
    }
    renderTestRunItems();
}

function updateTreSortIndicators() {
    try {
        const map = {
            number: document.querySelector('#th-tre-number .sort-indicator'),
            title: document.querySelector('#th-tre-title .sort-indicator'),
            priority: document.querySelector('#th-tre-priority .sort-indicator'),
            result: document.querySelector('#th-tre-result .sort-indicator'),
            assignee: document.querySelector('#th-tre-assignee .sort-indicator'),
            executed: document.querySelector('#th-tre-executed .sort-indicator')
        };
        Object.values(map).forEach(el => { if (el) el.textContent = ''; });
        const target = map[treSortField];
        if (target) target.textContent = (treSortOrder === 'asc') ? '▲' : '▼';
    } catch (_) {}
}

function sortTestRunItems() {
    const priRank = v => ({ High: 3, Medium: 2, Low: 1 }[v] || 0);
    const resRank = v => ({ Passed: 6, Failed: 5, Retest: 4, 'Not Available': 3, 'Not Required': 2, Skip: 2, Pending: 1 }[v] || 0);
    const assigneeOf = it => (it.assignee_name || (it.assignee && it.assignee.name) || '').toLowerCase();
    const parseNumberSegments = str => {
        try {
            if (!str) return [];
            const ms = String(str).match(/\d+/g);
            return ms ? ms.map(s => parseInt(s, 10)) : [];
        } catch (_) { return []; }
    };
    const compareByNumericParts = (aStr, bStr) => {
        const aSeg = parseNumberSegments(aStr);
        const bSeg = parseNumberSegments(bStr);
        const len = Math.min(aSeg.length, bSeg.length);
        for (let i = 0; i < len; i++) {
            if (aSeg[i] !== bSeg[i]) return aSeg[i] - bSeg[i];
        }
        return aSeg.length - bSeg.length;
    };
    const cmp = (a, b) => {
        switch (treSortField) {
            case 'number':
                return compareByNumericParts(a.test_case_number || '', b.test_case_number || '');
            case 'title':
                return (a.title || '').toLowerCase().localeCompare((b.title || '').toLowerCase());
            case 'priority':
                return priRank(a.priority) - priRank(b.priority);
            case 'result':
                return resRank(getExecutionItemStatus(a)) - resRank(getExecutionItemStatus(b));
            case 'assignee':
                return assigneeOf(a).localeCompare(assigneeOf(b));
            case 'executed':
                return (a.executed_at || '').localeCompare(b.executed_at || '');
            default:
                return 0;
        }
    };

    const sorted = [...(testRunItems || [])].sort((a, b) => {
        const r = cmp(a, b);
        return treSortOrder === 'asc' ? r : -r;
    });

    return sorted;
}

// 初始化「跳至」菜單 - 快速切換 Test Runs
async function initJumpToTestRunMenu() {
    const jumpToTestRunGroup = document.getElementById('jumpToTestRunGroup');
    const jumpToTestRunDropdown = document.getElementById('jumpToTestRunDropdown');

    if (!jumpToTestRunGroup || !jumpToTestRunDropdown || !testRunConfig || !testRunConfig.set_id) {
        return; // 如果沒有 set_id，不顯示菜單
    }

    try {
        const teamId = currentTeamId;
        if (!teamId) {
            return;
        }

        // 獲取該 Test Run Set 中的所有 Test Runs
        const response = await window.AuthClient.fetch(
            `/api/teams/${teamId}/test-run-sets/${testRunConfig.set_id}`
        );

        if (!response.ok) {
            return;
        }

        const setData = await response.json();
        const testRuns = setData.test_runs || [];

        // 過濾出不是當前 Test Run 的所有 Test Runs
        const otherTestRuns = Array.isArray(testRuns) ?
                             testRuns.filter(tr => tr.id !== currentConfigId) :
                             [];

        if (otherTestRuns.length === 0) {
            // 如果沒有其他 Test Runs，隱藏菜單
            jumpToTestRunGroup.style.display = 'none';
            return;
        }

        // 清空現有菜單項
        jumpToTestRunDropdown.innerHTML = '';

        // 添加每個 Test Run 為菜單項
        otherTestRuns.forEach(testRun => {
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.className = 'dropdown-item';
            a.href = '#';
            a.style.cursor = 'pointer';

            const statusIcon = testRun.status === 'active' ? 'play-circle' :
                              testRun.status === 'draft' ? 'file-alt' :
                              testRun.status === 'completed' ? 'check-circle' :
                              'archive';
            a.innerHTML = `<i class="fas fa-${statusIcon} me-2"></i>${escapeHtml(testRun.name)}`;

            a.addEventListener('click', (e) => {
                e.preventDefault();
                window.location.href = `/test-run-execution?config_id=${testRun.id}&team_id=${teamId}`;
            });

            li.appendChild(a);
            jumpToTestRunDropdown.appendChild(li);
        });

        // 顯示菜單
        jumpToTestRunGroup.style.display = 'block';

    } catch (error) {
        console.error('Failed to initialize jump to test run menu:', error);
        jumpToTestRunGroup.style.display = 'none';
    }
}

function setupQuickSearch_TR() {
    if (!document.getElementById('quickSearchOverlay')) {
        const overlay = document.createElement('div');
        overlay.id = 'quickSearchOverlay';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:1060;display:none;background:rgba(0,0,0,0.35)';
        overlay.innerHTML = `
          <div class="position-fixed" style="top:34vh; left:50%; transform: translateX(-50%); width:min(720px, 92vw);">
            <div class="card shadow">
              <div class="card-body p-2">
                <input id="quickSearchInput" type="text" class="form-control form-control-lg" placeholder="${window.i18n ? window.i18n.t('testRun.searchTestCases') : '搜尋測試案例...'}" autocomplete="off" />
                <div id="quickSearchResults" class="list-group list-group-flush" style="max-height:30vh; overflow:auto;"></div>
              </div>
            </div>
          </div>`;
        document.body.appendChild(overlay);
        // 語言切換時即時更新 placeholder
        try {
            const applyPlaceholder = () => {
                const el = document.getElementById('quickSearchInput');
                if (!el) return;
                if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
                    let text = window.i18n.t('testRun.searchTestCases');
                    if (!text || text === 'testRun.searchTestCases') {
                        // 後備：沿用 testCase 的搜尋文案或硬編碼中文
                        const alt = window.i18n.t('testCase.searchTestCases');
                        text = (alt && alt !== 'testCase.searchTestCases') ? alt : '搜尋測試案例...';
                    }
                    el.placeholder = text;
                } else {
                    el.placeholder = '搜尋測試案例...';
                }
            };
            applyPlaceholder();
            document.addEventListener('languageChanged', applyPlaceholder);
            document.addEventListener('i18nReady', applyPlaceholder);
        } catch (_) {}
        overlay.addEventListener('click', (e)=>{ if(e.target===overlay) closeQuickSearch_TR(); });
    }
    document.addEventListener('keydown', function(e){
        const tag = (e.target && e.target.tagName || '').toLowerCase();
        const isTyping = ['input','textarea','select'].includes(tag) || (e.target && e.target.isContentEditable);
        if (!isTyping && e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            openQuickSearch_TR();
        }
    });
}
function openQuickSearch_TR() {
    const overlay = document.getElementById('quickSearchOverlay');
    const input = document.getElementById('quickSearchInput');
    const results = document.getElementById('quickSearchResults');
    if (!overlay || !input || !results) return;
    overlay.style.display = 'block';
    input.value = '';
    results.innerHTML = '';
    input.focus();
    const handleKey = (e) => {
        if (e.key === 'Escape') { closeQuickSearch_TR(); return; }
        if (e.key === 'Enter') {
            const active = results.querySelector('.active');
            if (active) { active.click(); }
        } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const items = Array.from(results.querySelectorAll('.list-group-item'));
            if (items.length === 0) return;
            let idx = items.findIndex(li => li.classList.contains('active'));
            if (idx < 0) idx = 0;
            idx = (e.key === 'ArrowDown') ? Math.min(idx+1, items.length-1) : Math.max(idx-1, 0);
            items.forEach(li => li.classList.remove('active'));
            items[idx].classList.add('active');
            items[idx].scrollIntoView({ block:'nearest' });
        }
    };
    input.onkeydown = handleKey;
    input.oninput = () => quickSearchRender_TR(input.value, results);
}
function closeQuickSearch_TR() {
    const overlay = document.getElementById('quickSearchOverlay');
    if (overlay) overlay.style.display = 'none';
}
function quickSearchRender_TR(query, container) {
    const q = (query || '').trim().toLowerCase();
    let matches = [];
    if (q.length > 0) {
        matches = (testRunItems || []).filter(it => {
            const num = (it.test_case_number || '').toLowerCase();
            const title = (it.title || '').toLowerCase();
            return num.includes(q) || title.includes(q);
        }).slice(0, 100);
    }
    if (matches.length === 0) {
        const noText = window.i18n ? window.i18n.t('errors.noMatchingTestCases') : '沒有找到符合條件的測試案例';
        container.innerHTML = `<div class="list-group-item text-muted">${noText}</div>`;
        return;
    }
    container.innerHTML = matches.map((it, idx) => `
      <button type="button" class="list-group-item list-group-item-action ${idx===0?'active':''}" data-num="${it.test_case_number}">
        <div class="d-flex justify-content-between align-items-center">
          <code class="me-2" style="color: rgb(194, 54, 120); font-weight: 500;">${escapeHtml(it.test_case_number || '')}</code>
          <span class="text-truncate">${escapeHtml(it.title || '')}</span>
        </div>
      </button>`).join('');

    // 重新應用翻譯到新生成的內容
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(container);
    }
    container.querySelectorAll('.list-group-item').forEach(btn => {
        btn.addEventListener('click', async () => {
            const tcNum = btn.getAttribute('data-num');
            closeQuickSearch_TR();
            if (tcNum) {
                await showTestCaseDetailModal(tcNum);
            }
        });
    });
}
