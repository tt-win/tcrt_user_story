/* ============================================================
   TEST RUN MANAGEMENT - RENDER
   ============================================================ */

function renderTestRunOverview(filterStatus = 'all') {
    const hasSets = Array.isArray(testRunSets) && testRunSets.length > 0;
    const hasUnassigned = Array.isArray(unassignedTestRuns) && unassignedTestRuns.length > 0;

    // 若尚未載入 Test Case Set 選項，嘗試載入
    if (!testCaseSets.length && currentTeamId) {
        loadTestCaseSets().catch(() => {});
    }

    // 即使沒有任何 Test Run，也要顯示新增 Test Run / Test Run Set 卡片
    showConfigsSection();
    renderTestRunSetCards(filterStatus);
    renderUnassignedTestRunCards(filterStatus);
}

function renderTestRunSetCards(filterStatus) {
    const container = document.getElementById('test-run-sets-container');
    const emptyHint = document.getElementById('no-test-run-sets');
    if (!container) return;

    const perms = window._testRunPermissions || testRunPermissions || {};
    const hasSets = Array.isArray(testRunSets) && testRunSets.length > 0;

    // 根據狀態篩選 Test Run Set
    let filteredSets = testRunSets;
    if (hasSets && filterStatus !== 'all') {
        filteredSets = testRunSets.filter(set => {
            const setStatus = set.status || 'active';
            // archived 篩選：只顯示 archived 的 set
            if (filterStatus === 'archived') {
                return setStatus === 'archived';
            }
            // 其他篩選 (draft, active, completed)：只顯示非 archived 的 set
            return setStatus !== 'archived';
        });
    }

    const cards = filteredSets.length > 0 ? filteredSets.map(set => createTestRunSetCard(set, filterStatus)) : [];

    if (perms.canCreate) {
        cards.push(getAddTestRunSetCardHtml());
    }

    container.innerHTML = cards.join('');

    if (emptyHint) emptyHint.style.display = hasSets ? 'none' : 'block';

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(container);
    }
}

function summarizeSetMetrics(testRuns) {
    let totalCases = 0;
    let executedCases = 0;
    let passedCases = 0;

    (testRuns || []).forEach(run => {
        totalCases += run.total_test_cases || 0;
        executedCases += run.executed_cases || 0;
        passedCases += run.passed_cases || 0;
    });

    const executionRate = totalCases > 0 ? (executedCases / totalCases) * 100 : 0;
    const passRate = executedCases > 0 ? (passedCases / executedCases) * 100 : 0;

    return { totalCases, executedCases, passedCases, executionRate, passRate };
}

// ------- Test Run Set Report -------
let testRunSetReportModalInstance = null;

function openTestRunSetReport(setData) {
    if (!setData) return;
    renderTestRunSetReport(setData);
    refreshSetHtmlReportStatus(setData.id);
    if (!testRunSetReportModalInstance) {
        testRunSetReportModalInstance = new bootstrap.Modal(document.getElementById('testRunSetReportModal'));
    }
    testRunSetReportModalInstance.show();
}

function renderTestRunSetReport(setData) {
    const titleEl = document.getElementById('setReportTitle');
    const statusEl = document.getElementById('setReportStatusBadge');
    const metaEl = document.getElementById('setReportMeta');
    const descEl = document.getElementById('setReportDescription');
    const statGrid = document.getElementById('setReportStatGrid');
    const runsBody = document.getElementById('setReportRunsBody');

    const runs = Array.isArray(setData.test_runs) ? setData.test_runs : [];
    const metrics = summarizeSetMetrics(runs);
    const statusCounts = runs.reduce((acc, run) => {
        const key = String(run.status || 'unknown').toLowerCase();
        acc[key] = (acc[key] || 0) + 1;
        return acc;
    }, {});

    if (titleEl) titleEl.textContent = setData.name || '';
    if (statusEl) statusEl.innerHTML = getSetStatusBadge(setData.status);
    if (metaEl) metaEl.textContent = `Test Run: ${runs.length} · 總案例: ${metrics.totalCases} · 執行率 ${Math.round(metrics.executionRate)}% · Pass Rate ${Math.round(metrics.passRate)}%`;
    if (descEl) {
        descEl.innerHTML = setData.description ? escapeHtml(setData.description).replace(/\n/g, '<br>') : '<span class="text-muted" data-i18n="testRun.sets.detail.noDescription">尚未填寫描述</span>';
    }

    if (statGrid) {
        statGrid.innerHTML = `
            <div class="col-6 col-md-3">
                <div class="small text-muted">Active</div>
                <div class="fw-semibold">${statusCounts['active'] || 0}</div>
            </div>
            <div class="col-6 col-md-3">
                <div class="small text-muted">Completed</div>
                <div class="fw-semibold">${statusCounts['completed'] || 0}</div>
            </div>
            <div class="col-6 col-md-3">
                <div class="small text-muted">Archived</div>
                <div class="fw-semibold">${statusCounts['archived'] || 0}</div>
            </div>
            <div class="col-6 col-md-3">
                <div class="small text-muted">草稿/其他</div>
                <div class="fw-semibold">${statusCounts['draft'] || 0}</div>
            </div>
            <div class="col-6 col-md-3">
                <div class="small text-muted">總案例</div>
                <div class="fw-semibold">${metrics.totalCases}</div>
            </div>
            <div class="col-6 col-md-3">
                <div class="small text-muted">已執行</div>
                <div class="fw-semibold">${metrics.executedCases}</div>
            </div>
            <div class="col-6 col-md-3">
                <div class="small text-muted">執行率</div>
                <div class="fw-semibold">${Math.round(metrics.executionRate)}%</div>
            </div>
            <div class="col-6 col-md-3">
                <div class="small text-muted">Pass Rate</div>
                <div class="fw-semibold">${Math.round(metrics.passRate)}%</div>
            </div>
        `;
    }

    if (runsBody) {
        if (!runs.length) {
            runsBody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-3">尚未加入任何 Test Run</td></tr>';
        } else {
            runsBody.innerHTML = runs.map(run => {
                const execRate = run.total_test_cases > 0 ? Math.round((run.executed_cases || 0) / run.total_test_cases * 100) : 0;
                const passRate = (run.executed_cases || 0) > 0 ? Math.round((run.passed_cases || 0) / run.executed_cases * 100) : 0;
                return `
                    <tr>
                        <td>${escapeHtml(run.name || '')}</td>
                        <td><span class="status-badge ${getStatusClass(run.status)}">${getStatusText(run.status)}</span></td>
                        <td class="text-center">${execRate}%</td>
                        <td class="text-center">${passRate}%</td>
                        <td class="text-center">${run.total_test_cases || 0}</td>
                        <td class="text-center">${run.executed_cases || 0}</td>
                        <td class="text-center">${run.passed_cases || 0}</td>
                        <td>${escapeHtml(run.test_environment || '-')}</td>
                        <td>${escapeHtml(run.test_version || '-')}</td>
                    </tr>
                `;
            }).join('');
        }
    }
}

async function refreshSetHtmlReportStatus(setId) {
    const statusEl = document.getElementById('setReportHtmlStatus');
    const openBtn = document.getElementById('setReportOpenHtmlBtn');
    if (openBtn) openBtn.classList.add('d-none');
    if (statusEl) statusEl.textContent = '';
    if (!currentTeamId) return;

    try {
        const resp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${setId}/report`);
        const data = await resp.json();
        if (resp.ok && data.exists) {
            if (statusEl) statusEl.textContent = '已有報告，可直接開啟';
            if (openBtn && data.report_url) {
                openBtn.href = data.report_url;
                openBtn.classList.remove('d-none');
            }
        } else if (statusEl) {
            statusEl.textContent = '尚未生成報告';
        }
    } catch (e) {
        if (statusEl) statusEl.textContent = '查詢報告狀態失敗';
    }
}

async function generateTestRunSetHtmlReport() {
    const btn = document.getElementById('setReportGenerateHtmlBtn');
    const icon = document.getElementById('setReportGenerateIcon');
    const text = document.getElementById('setReportGenerateText');
    if (!currentSetContext || !currentTeamId || !btn) return;

    const defaultLabel = (window.i18n?.t('testRun.generateHtmlButton') || '生成並複製連結');
    const loadingLabel = (window.i18n?.t('testRun.generatingHtml') || '生成中...');

    try {
        btn.disabled = true;
        if (icon) {
            icon.classList.remove('fa-file-alt');
            icon.classList.add('fa-spinner', 'fa-spin');
        }
        if (text) text.textContent = loadingLabel;

        const resp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${currentSetContext.id}/generate-html`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
            throw new Error(data?.detail || '生成失敗');
        }

        if (data.report_url) {
            if (window.AppUtils?.showCopyModal) {
                window.AppUtils.showCopyModal(data.report_url);
            } else {
                window.prompt('請手動複製此連結：', data.report_url);
            }
        }
        refreshSetHtmlReportStatus(currentSetContext.id);
    } catch (error) {
        const msg = error?.message || '生成失敗';
        AppUtils.showError(`生成 HTML 報告時發生錯誤：${msg}`);
    } finally {
        btn.disabled = false;
        if (icon) {
            icon.classList.remove('fa-spinner', 'fa-spin');
            icon.classList.add('fa-file-alt');
        }
        if (text) text.textContent = defaultLabel;
    }
}

function createTestRunSetCard(set, filterStatus) {
    const allRuns = Array.isArray(set.test_runs) ? set.test_runs : [];
    const filteredRuns = filterTestRunsByStatus(allRuns, filterStatus);
    const metrics = summarizeSetMetrics(allRuns);
    const filteredMetrics = summarizeSetMetrics(filteredRuns);
    const totalRuns = allRuns.length;
    const filteredCount = filteredRuns.length;

    const recentRunsHtml = filteredRuns.slice(0, 3).map(run => {
        const statusClass = getStatusClass(run.status);
        const statusText = getStatusText(run.status);
        return `
            <div class="d-flex align-items-center justify-content-between py-1 border-bottom gap-2">
                <div class="flex-grow-1 min-width-0 text-truncate"><i class="fas fa-flag text-muted me-2"></i>${escapeHtml(run.name)}</div>
                <span class="status-badge ${statusClass} flex-shrink-0">${statusText}</span>
            </div>
        `;
    }).join('');

    const emptyKey = filterStatus === 'all' ? 'testRun.sets.card.empty' : 'testRun.sets.card.noMatches';
    const emptyFallback = filterStatus === 'all' ? '尚未包含任何 Test Run' : '沒有符合篩選條件的 Test Run';
    const noRunsHtml = `
        <div class="text-muted small py-2" data-i18n="${emptyKey}">
            ${emptyFallback}
        </div>
    `;

    const statusClass = getStatusClass(set.status || 'active');
    const statusBadge = getSetStatusBadge(set.status);

    let tpContent = '';
    if (set.related_tp_tickets && Array.isArray(set.related_tp_tickets) && set.related_tp_tickets.length > 0) {
        const maxDisplay = 5;
        const visibleTickets = set.related_tp_tickets.slice(0, maxDisplay);
        const remainingCount = set.related_tp_tickets.length - maxDisplay;
        const tpTags = visibleTickets.map(ticket => {
            const safe = escapeHtml(ticket);
            return `<span class="tcg-tag me-1" data-tp-ticket="${safe}"` +
                ` onmouseenter="showJiraPreview(event, '${safe}')"` +
                ` onmouseleave="hideJiraPreview()"` +
                ` onclick="event.stopPropagation(); openJiraTicket('${safe}')" style="cursor:pointer; font-size: 0.75rem;">${safe}</span>`;
        }).join('');
        const remainingTag = remainingCount > 0
            ? `<span class="badge bg-light text-dark" style="font-size: 0.75rem;">+${remainingCount}</span>`
            : '';
        tpContent = `${tpTags}${remainingTag}`;
    } else {
        tpContent = `<span class="tp-tag badge bg-secondary me-1">N/A</span>`;
    }
    const tpLine = `<div class="stats-item mb-1">
        <i class="fas fa-tags stats-icon"></i>
        <small class="text-muted flex-grow-1" data-i18n="testRun.relatedTpTickets">相關 JIRA Tickets</small>
        <div class="d-flex flex-wrap gap-1 justify-content-end ms-auto">${tpContent}</div>
    </div>`;

    return `
        <div class="col-xl-4 col-lg-6 mb-4">
            <div class="card h-100 test-run-card ${statusClass}" onclick="openTestRunSetDetail(${set.id})">
                <div class="card-body d-flex flex-column">
                    <div class="d-flex justify-content-between align-items-start mb-3 gap-2">
                        <div class="flex-grow-1 min-width-0">
                            <h5 class="card-title text-primary mb-1 text-truncate">${escapeHtml(set.name)}</h5>
                            <div class="text-muted small">
                                <i class="fas fa-calendar-plus me-1"></i>${AppUtils.formatDate(set.created_at, 'datetime')}
                            </div>
                        </div>
                        <div class="flex-shrink-0">
                            ${statusBadge}
                        </div>
                    </div>
                    <div class="mb-3">
                        <div class="small text-muted">
                            <div class="d-flex justify-content-between"><span data-i18n="testRun.sets.card.totalRuns">包含 Test Run</span><span>${filteredCount}/${totalRuns}</span></div>
                            <div class="d-flex justify-content-between"><span data-i18n="testRun.progressLabel">執行進度</span><span>${filteredMetrics.executionRate.toFixed(1)}%</span></div>
                            <div class="d-flex justify-content-between"><span data-i18n="testRun.passRateLabel">Pass Rate</span><span>${filteredMetrics.passRate.toFixed(1)}%</span></div>
                        </div>
                        ${tpLine}
                    </div>
                    <div class="border rounded p-2 bg-light flex-grow-1">
                        ${filteredCount > 0 ? recentRunsHtml : noRunsHtml}
                    </div>
                    <div class="mt-3 d-flex gap-2 flex-wrap">
                        <button type="button" class="btn btn-primary btn-sm flex-grow-1" onclick="event.stopPropagation(); openTestRunSetDetail(${set.id})">
                            <i class="fas fa-layer-group me-1"></i><span data-i18n="testRun.sets.card.openDetail">管理 Test Run</span>
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderUnassignedTestRunCards(filterStatus) {
    const container = document.getElementById('unassigned-test-runs-container');
    const emptyHint = document.getElementById('no-unassigned-test-runs');
    if (!container) return;

    if (!Array.isArray(unassignedTestRuns) || unassignedTestRuns.length === 0) {
        const perms = window._testRunPermissions || testRunPermissions || {};
        container.innerHTML = perms.canCreate ? getAddTestRunCardHtml() : '';
        if (emptyHint) emptyHint.style.display = 'block';
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(container);
        }
        return;
    }

    const runs = filterTestRunsByStatus(unassignedTestRuns, filterStatus);
    const perms = window._testRunPermissions || testRunPermissions || {};

    if (runs.length === 0) {
        let messageHtml = '';
        if (filterStatus === 'all') {
            if (emptyHint) emptyHint.style.display = 'block';
        } else {
            messageHtml = `
                <div class="col-12">
                    <div class="text-center text-muted py-4" data-i18n="testRun.unassigned.noFilterMatches">目前沒有符合篩選條件的 Test Run</div>
                </div>
            `;
            if (emptyHint) emptyHint.style.display = 'none';
        }
        container.innerHTML = messageHtml + (perms.canCreate ? getAddTestRunCardHtml() : '');
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(container);
        }
        return;
    }

    let cardsHtml = runs.map(config => createConfigCard(config)).join('');
    if (perms.canCreate) {
        cardsHtml += getAddTestRunCardHtml();
    }
    container.innerHTML = cardsHtml;
    if (emptyHint) emptyHint.style.display = 'none';

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(container);
    }
}


function showLoading() {
    document.getElementById('loading-state').style.display = 'block';
    document.getElementById('test-run-configs-section').style.display = 'none';
    document.getElementById('no-configs-section').style.display = 'none';
}

function hideLoading() {
    document.getElementById('loading-state').style.display = 'none';
}

function showNoConfigs() {
    document.getElementById('no-configs-section').style.display = 'block';
    document.getElementById('test-run-configs-section').style.display = 'none';
}

function showConfigsSection() {
    document.getElementById('no-configs-section').style.display = 'none';
    document.getElementById('test-run-configs-section').style.display = 'block';
}

function createConfigCard(config) {
    const permissions = window._testRunPermissions || testRunPermissions || {};
    const statusClass = getStatusClass(config.status);
    const statusText = getStatusText(config.status);
    const progressPercentage = config.execution_rate || 0;
    const passPercentage = config.pass_rate || 0;
    const createdDate = AppUtils.formatDate(config.created_at, 'datetime-tz');
    const envLine = config.test_environment ? `<div class=\"stats-item\"><i class=\"fas fa-server stats-icon\"></i><small class=\"text-muted\"><span data-i18n=\"testRun.testEnvironment\">測試環境</span>: ${escapeHtml(config.test_environment)}</small></div>` : '';
    
    // TP 標籤顯示邏輯
    let tpContent = '';
    if (config.related_tp_tickets && Array.isArray(config.related_tp_tickets) && config.related_tp_tickets.length > 0) {
        const maxDisplay = 5; // 最多顯示5個標籤
        const visibleTickets = config.related_tp_tickets.slice(0, maxDisplay);
        const remainingCount = config.related_tp_tickets.length - maxDisplay;

        const tpTags = visibleTickets.map(ticket =>
            `<span class="tcg-tag me-1" data-tp-ticket="${escapeHtml(ticket)}"
                   onmouseenter="showJiraPreview(event, '${escapeHtml(ticket)}')"
                   onmouseleave="hideJiraPreview()"
                   onclick="event.stopPropagation(); openJiraTicket('${escapeHtml(ticket)}')"
                   style="cursor: pointer; font-size: 0.75rem;">${escapeHtml(ticket)}</span>`
        ).join('');

        const remainingTag = remainingCount > 0 ?
            `<span class="badge bg-light text-dark" style="font-size: 0.75rem;">+${remainingCount}</span>` : '';

        tpContent = `${tpTags}${remainingTag}`;
    } else {
        tpContent = `<span class="tp-tag badge bg-secondary me-1">N/A</span>`;
    }
    const tpLine = `<div class="stats-item mb-1">
        <i class="fas fa-tags stats-icon"></i>
        <small class="text-muted flex-grow-1"><span data-i18n="testRun.relatedTpTickets">相關 JIRA Tickets</span></small>
        <div class="d-flex flex-wrap gap-1 justify-content-end ms-auto">${tpContent}</div>
    </div>`;
    
    const buildLine = config.build_number ? `<div class=\"stats-item\"><i class=\"fas fa-code-branch stats-icon\"></i><small class=\"text-muted\"><span data-i18n=\"testRun.buildNumber\">建置版本</span>: ${escapeHtml(config.build_number)}</small></div>` : '';
    
    const primaryActions = [];
    const secondaryActions = [];

    primaryActions.push(`
                        <button class="btn btn-primary btn-sm flex-grow-1" onclick="event.stopPropagation(); enterTestRun(${config.id})">
                            <i class="fas fa-arrow-right me-1"></i><span data-i18n="testRun.enterButton">進入</span>
                        </button>
    `);

    const lockedForConfigEdit = config.status === 'completed' || config.status === 'archived';
    const lockedForCasesEdit = config.status === 'completed';
    const lockedConfigTitle = lockedForConfigEdit
        ? ` title="${(window.i18n && window.i18n.isReady()) ? window.i18n.t('testRun.cannotEditCompleted') : '已完成或已歸檔的 Test Run 不可編輯'}"`
        : '';
    const lockedCasesTitle = lockedForCasesEdit
        ? ` title="${(window.i18n && window.i18n.isReady()) ? window.i18n.t('testRun.cannotEditCompleted') : '已完成的 Test Run 不可編輯 Test Case'}"`
        : '';

    if (permissions.canUpdate) {
        primaryActions.push(`
                        <button class="btn btn-secondary btn-sm${lockedForConfigEdit ? ' disabled' : ''}" 
                                ${lockedForConfigEdit ? 'disabled' : ''}${lockedConfigTitle}
                                onclick="event.stopPropagation(); editBasicSettings(${config.id})">
                            <i class="fas fa-edit me-1"></i><span data-i18n="testRun.editBasicSettings">編輯基本設定</span>
                        </button>
        `);
        primaryActions.push(`
                        <button class="btn btn-info btn-sm${(lockedForConfigEdit || lockedForCasesEdit) ? ' disabled' : ''}" 
                                ${(lockedForConfigEdit || lockedForCasesEdit) ? 'disabled' : ''}${lockedCasesTitle}
                                onclick="event.stopPropagation(); editTestCases(${config.id})">
                            <i class="fas fa-list me-1"></i><span data-i18n="testRun.editTestCases">編輯 Test Case</span>
                        </button>
        `);
    }

    if (permissions.canChangeStatus) {
        secondaryActions.push(`
                        <div class="position-relative" onclick="event.stopPropagation()">
                            <button type="button" class="btn btn-warning btn-sm custom-status-btn" 
                                    data-config-id="${config.id}" 
                                    onclick="event.stopPropagation(); toggleCustomStatusDropdown(this, ${config.id})">
                                <i class="fas fa-exchange-alt me-1"></i><span data-i18n="testRun.changeStatus">狀態</span>
                                <i class="fas fa-chevron-down ms-1"></i>
                            </button>
                        </div>
        `);
    }

    if (permissions.canDelete) {
        secondaryActions.push(`
                        <button class="btn btn-danger btn-sm" onclick="event.stopPropagation(); deleteTestRun(${config.id}, '${escapeHtml(config.name)}')">
                            <i class="fas fa-trash me-1"></i><span data-i18n="common.delete">刪除</span>
                        </button>
        `);
    }

    const actionsHtml = (() => {
        const merged = [...primaryActions, ...secondaryActions];
        if (!merged.length) return '';
        return `<div class="d-flex gap-2 flex-wrap w-100 justify-content-lg-end">${merged.join('')}</div>`;
    })();

    return `
        <div class="col-md-6 col-lg-4 mb-4">
            <div class="card h-100 test-run-card ${getStatusClass(config.status)}" onclick="enterTestRun(${config.id})">
                <div class="card-body d-flex flex-column h-100">
                    <div class="d-flex justify-content-between align-items-start mb-3 gap-2">
                        <div class="d-flex align-items-center overflow-hidden flex-grow-1">
                            <div class="flex-shrink-0 me-3">
                                <div class="bg-primary text-white rounded-circle d-flex align-items-center justify-content-center" 
                                     style="width: 48px; height: 48px; font-size: 16px; font-weight: bold;">
                                    <i class="fas fa-play"></i>
                                </div>
                            </div>
                            <div class="min-width-0">
                                <h5 class="card-title text-primary mb-1 text-truncate">${escapeHtml(config.name)}</h5>
                            </div>
                        </div>
                        <div class="flex-shrink-0">
                            <span class="status-badge ${statusClass}">${statusText}</span>
                        </div>
                    </div>
                    <div class="mb-3">
                        <div class="d-flex justify-content-between align-items-center mb-1">
                            <small class="text-muted" data-i18n="testRun.progressLabel">執行進度</small>
                            <small class="text-muted">${progressPercentage.toFixed(1)}%</small>
                        </div>
                        <div class="progress mb-2">
                            <div class="progress-bar bg-primary" style="width: ${progressPercentage}%"></div>
                        </div>
                        <div class="d-flex justify-content-between align-items-center mb-1">
                            <small class="text-muted" data-i18n="testRun.passRateLabel">Pass Rate</small>
                            <small class="text-muted">${passPercentage.toFixed(1)}%</small>
                        </div>
                        <div class="progress">
                            <div class="progress-bar bg-success" style="width: ${passPercentage}%"></div>
                        </div>
                    </div>
                    <div class="mb-3">
                        ${envLine}
                        ${tpLine}
                        ${buildLine}
                        <div class="stats-item">
                            <i class="fas fa-list-ul stats-icon"></i>
                            <small class="text-muted">${(window.i18n && window.i18n.isReady()) ? window.i18n.t('testRun.totalExecuted', {total: config.total_test_cases, executed: config.executed_cases}) : `總數: ${config.total_test_cases} | 已執行: ${config.executed_cases}`}</small>
                        </div>
                        <div class="stats-item">
                            <i class="fas fa-calendar stats-icon"></i>
                            <small class="text-muted">${(window.i18n && window.i18n.isReady()) ? window.i18n.t('testRun.createdLabel', {date: createdDate}) : `建立: ${createdDate}`}</small>
                        </div>
                    </div>
                    ${actionsHtml ? `<div class="mt-auto pt-2">${actionsHtml}</div>` : ''}
                </div>
            </div>
        </div>
    `;
}

function getAddTestRunCardHtml() {
    return `
        <div class="col-md-6 col-lg-4 mb-4">
            <div class="card h-100 add-test-run-card text-center" data-card-type="run">
                <div class="card-body d-flex flex-column justify-content-center">
                    <div class="text-primary rounded-circle d-flex align-items-center justify-content-center mx-auto mb-3" 
                         style="width: 48px; height: 48px; font-size: 18px; border: 2px dashed var(--tr-primary);">
                        <i class="fas fa-plus"></i>
                    </div>
                    <h6 class="text-primary mb-1" data-i18n="testRun.addConfigs">新增 Test Run</h6>
                    <small class="text-muted" data-i18n="testRun.addConfigsHint">建立新的測試執行配置</small>
                </div>
            </div>
        </div>
    `;
}

function getAddTestRunSetCardHtml() {
    return `
        <div class="col-xl-4 col-lg-6 mb-4">
            <div class="card h-100 add-test-run-card text-center" data-card-type="set">
                <div class="card-body d-flex flex-column justify-content-center">
                    <div class="text-primary rounded-circle d-flex align-items-center justify-content-center mx-auto mb-3"
                         style="width: 48px; height: 48px; font-size: 18px; border: 2px dashed var(--tr-primary);">
                        <i class="fas fa-layer-group"></i>
                    </div>
                    <h6 class="text-primary mb-1" data-i18n="testRun.sets.form.addCardTitle">新增 Test Run Set</h6>
                    <small class="text-muted" data-i18n="testRun.sets.form.addCardHint">將相關的 Test Run 分組管理</small>
                </div>
            </div>
        </div>
    `;
}

function getStatusClass(status) {
    switch (status) {
        case 'active': return 'status-active';
        case 'completed': return 'status-completed';
        case 'draft': return 'status-draft';
        case 'archived': return 'status-archived';
        default: return 'status-draft';
    }
}

function getStatusText(status) {
    if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
        const statusKey = `testRun.status.${status}`;
        const translated = window.i18n.t(statusKey);
        // 如果翻譯失敗（返回原始鍵），使用預設文字
        if (translated === statusKey || !translated) {
            return getDefaultStatusText(status);
        }
        return translated;
    }
    return getDefaultStatusText(status);
}

function getDefaultStatusText(status) {
    const defaultTexts = {
        'active': '進行中',
        'completed': '已完成', 
        'draft': '草稿',
        'archived': '已歸檔',
        'unknown': '未知'
    };
    return defaultTexts[status] || '未知';
}

function getSetStatusText(status) {
    const key = String(status || '').toLowerCase();
    if (key === 'active') {
        return window.i18n?.t('testRun.sets.status.active') || 'Active';
    }
    if (key === 'completed') {
        return window.i18n?.t('testRun.sets.status.completed') || 'Completed';
    }
    if (key === 'archived') {
        return window.i18n?.t('testRun.sets.status.archived') || 'Archived';
    }
    return key || 'Unknown';
}

function getSetStatusBadge(status) {
    const text = getSetStatusText(status);
    const key = String(status || '').toLowerCase();
    let className = 'status-badge status-active';
    if (key === 'archived') {
        className = 'status-badge status-archived';
    } else if (key === 'completed') {
        className = 'status-badge status-completed';
    }
    return `<span class="${className}">${text}</span>`;
}

// 自訂下拉選單邏輯
let currentDropdownConfig = null;
