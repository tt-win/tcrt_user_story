/**
 * 團隊數據統計頁面
 *
 * 提供全面的團隊活動與測試數據分析，包含 7 個統計模組：
 * 1. 總覽 (Overview)
 * 2. 團隊活動 (Team Activity)
 * 3. 測試案例趨勢 (Test Case Trends)
 * 4. 測試執行指標 (Test Run Metrics)
 * 5. 使用者行為 (User Activity)
 * 6. 審計分析 (Audit Analysis)
 * 7. 部門統計 (Department Stats)
 */

(function() {
    'use strict';

    // 全域變數
    let currentDays = 30;  // 預設統計天數
    let customStartDate = null;
    let customEndDate = null;
    const MAX_CUSTOM_RANGE_DAYS = 90;
    const charts = {};  // 儲存所有圖表實例
    let authClient = null;
    let cachedUserInfo = null;
    let teamFilterTeams = [];
    let teamFilterSelectedIds = new Set();
    let teamFilterPendingIds = new Set();
    let teamFilterInitialized = false;
    const TEAM_FILTER_STORAGE_KEY = 'teamStatsSelectedTeams';
    bootstrapFallbackChart();

    // 等待 i18n 系統就緒
    async function waitForI18n(timeoutMs = 5000) {
        // 如果 i18n 已經準備好了，直接返回
        if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
            return true;
        }
        
        // 否則等待 i18nReady 事件
        return new Promise((resolve) => {
            const timeout = setTimeout(() => {
                console.warn('i18n initialization timeout, proceeding with fallback translations');
                resolve(false);
            }, timeoutMs);
            
            const onReady = () => {
                clearTimeout(timeout);
                resolve(true);
            };
            
            if (document.readyState === 'loading') {
                document.addEventListener('i18nReady', onReady, { once: true });
            } else {
                // DOM 已經載入，可能 i18nReady 已經觸發過了
                // 再次檢查以確保
                if (window.i18n && window.i18n.isReady && window.i18n.isReady()) {
                    clearTimeout(timeout);
                    resolve(true);
                } else {
                    document.addEventListener('i18nReady', onReady, { once: true });
                }
            }
        });
    }

    // 初始化頁面
    document.addEventListener('DOMContentLoaded', async function() {
        try {
            // 等待 i18n 系統準備就緒（對 Safari特別重要）
            const i18nReady = await waitForI18n();
            if (!i18nReady) {
                console.warn('i18n system not fully ready, translations may use fallback text');
            }

            authClient = await waitForAuthClient();

            if (!authClient || !authClient.isAuthenticated()) {
                window.location.href = '/login';
                return;
            }

            cachedUserInfo = await authClient.getUserInfo();
            if (!cachedUserInfo) {
                AppUtils.showError('無法取得使用者資訊，請重新登入');
                setTimeout(() => window.location.href = '/login', 1500);
                return;
            }

            if (!hasAdminAccess(cachedUserInfo)) {
                AppUtils.showError('權限不足：需要 Admin 或更高權限');
                setTimeout(() => window.location.href = '/', 2000);
                return;
            }

            await initTeamFilter();
            initEventListeners();
            await loadAllStatistics();

            // 初始化 Bootstrap Tooltip（含漏斗面板的說明提示）
            document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function(el) {
                new bootstrap.Tooltip(el);
            });
        } catch (error) {
            console.error('初始化團隊統計頁面失敗:', error);
            AppUtils.showError('初始化統計頁面失敗');
        }
    });

    async function waitForAuthClient(timeoutMs = 5000) {
        const start = Date.now();
        while (!window.AuthClient) {
            if (Date.now() - start > timeoutMs) {
                console.error('AuthClient 初始化逾時');
                return null;
            }
            await sleep(100);
        }
        return window.AuthClient;
    }

    function hasAdminAccess(user) {
        if (!user || !user.role) return false;
        const role = String(user.role).toLowerCase();
        return role === 'admin' || role === 'super_admin';
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function translate(key, fallback, params = {}) {
        try {
            if (window.i18n && typeof window.i18n.t === 'function') {
                const value = window.i18n.t(key, params);
                if (value && value !== key) {
                    return value;
                }
            }
        } catch (err) {
            console.warn('翻譯字串取得失敗:', err);
        }
        return fallback;
    }

    async function initTeamFilter() {
        const toggle = document.getElementById('team-filter-toggle');
        if (!toggle || teamFilterInitialized) return;
        teamFilterInitialized = true;

        try {
            const response = await authFetch('/api/teams');
            if (!response.ok) {
                const body = await response.text().catch(() => '');
                throw new Error(`Failed to load teams: ${response.status} ${body}`);
            }
            const teams = await response.json();
            teamFilterTeams = Array.isArray(teams)
                ? teams.filter(team => team && team.id !== null && team.id !== undefined)
                : [];
            teamFilterTeams.sort((a, b) => {
                const nameA = String(a.name || '');
                const nameB = String(b.name || '');
                return nameA.localeCompare(nameB, 'zh-Hant');
            });
        } catch (error) {
            console.error('載入團隊清單失敗:', error);
            AppUtils.showError(translate('teamStats.teamFilter.loadFailed', '載入團隊清單失敗'));
            teamFilterTeams = [];
        }

        initTeamFilterSelection();
        renderTeamFilterOptions();
        bindTeamFilterEvents();
        updateTeamFilterSummary();
    }

    function initTeamFilterSelection() {
        const allIds = teamFilterTeams.map(team => String(team.id));
        let storedIds = [];
        try {
            const raw = sessionStorage.getItem(TEAM_FILTER_STORAGE_KEY);
            if (raw) {
                const parsed = JSON.parse(raw);
                if (Array.isArray(parsed)) {
                    storedIds = parsed.map(id => String(id));
                }
            }
        } catch (_) {
            storedIds = [];
        }
        const validStoredIds = storedIds.filter(id => allIds.includes(id));
        const initialIds = validStoredIds.length > 0 ? validStoredIds : allIds;
        teamFilterSelectedIds = new Set(initialIds);
        teamFilterPendingIds = new Set(initialIds);
    }

    function renderTeamFilterOptions() {
        const container = document.getElementById('team-filter-options');
        if (!container) return;
        
        // 不再移除 data-i18n 屬性，讓 i18n 系統有機會處理初始的載入提示

        if (!Array.isArray(teamFilterTeams) || teamFilterTeams.length === 0) {
            container.innerHTML = `
                <div class="text-muted small">
                    ${translate('teamStats.teamFilter.noTeams', '無可用團隊')}
                </div>
            `;
            return;
        }

        container.innerHTML = teamFilterTeams.map(team => `
            <div class="form-check">
                <input
                    class="form-check-input team-filter-checkbox"
                    type="checkbox"
                    value="${escapeHtml(String(team.id))}"
                    id="team-filter-${escapeHtml(String(team.id))}"
                />
                <label class="form-check-label" for="team-filter-${escapeHtml(String(team.id))}">
                    ${escapeHtml(team.name || `Team #${team.id}`)}
                </label>
            </div>
        `).join('');

        syncTeamFilterCheckboxes();
    }

    function syncTeamFilterCheckboxes() {
        const checkboxes = document.querySelectorAll('.team-filter-checkbox');
        if (!checkboxes.length) return;
        checkboxes.forEach(box => {
            const id = String(box.value);
            box.checked = teamFilterPendingIds.has(id);
        });
    }

    function bindTeamFilterEvents() {
        const options = document.getElementById('team-filter-options');
        if (options && !options.dataset.bound) {
            options.addEventListener('change', handleTeamFilterOptionChange);
            options.dataset.bound = '1';
        }

        const applyBtn = document.getElementById('team-filter-apply');
        if (applyBtn && !applyBtn.dataset.bound) {
            applyBtn.addEventListener('click', () => applyTeamFilterSelection());
            applyBtn.dataset.bound = '1';
        }

        const resetBtn = document.getElementById('team-filter-reset');
        if (resetBtn && !resetBtn.dataset.bound) {
            resetBtn.addEventListener('click', () => resetTeamFilterSelection());
            resetBtn.dataset.bound = '1';
        }
    }

    function handleTeamFilterOptionChange(event) {
        const target = event.target;
        if (!target || !target.classList.contains('team-filter-checkbox')) return;
        const id = String(target.value);
        if (target.checked) {
            teamFilterPendingIds.add(id);
        } else {
            teamFilterPendingIds.delete(id);
        }
    }

    function applyTeamFilterSelection() {
        if (!teamFilterTeams.length) return;
        if (teamFilterPendingIds.size === 0) {
            AppUtils.showError(translate('teamStats.teamFilter.emptyError', '請至少選擇一個團隊'));
            teamFilterPendingIds = new Set(teamFilterSelectedIds);
            syncTeamFilterCheckboxes();
            return;
        }
        teamFilterSelectedIds = new Set(teamFilterPendingIds);
        try {
            sessionStorage.setItem(
                TEAM_FILTER_STORAGE_KEY,
                JSON.stringify(Array.from(teamFilterSelectedIds))
            );
        } catch (_) {}
        updateTeamFilterSummary();
        loadAllStatistics();
    }

    function resetTeamFilterSelection() {
        if (!teamFilterTeams.length) return;
        const allIds = teamFilterTeams.map(team => String(team.id));
        teamFilterPendingIds = new Set(allIds);
        syncTeamFilterCheckboxes();
        applyTeamFilterSelection();
    }

    function updateTeamFilterSummary() {
        const summary = document.getElementById('team-filter-summary');
        if (!summary) return;
        if (!teamFilterTeams.length) {
            summary.textContent = '';
            return;
        }
        if (!shouldFilterTeams()) {
            summary.textContent = translate('teamStats.teamFilter.summaryAll', '全部');
            return;
        }
        summary.textContent = translate(
            'teamStats.teamFilter.summaryCount',
            '已選 {count} 個',
            { count: teamFilterSelectedIds.size }
        );
    }

    function shouldFilterTeams() {
        if (!teamFilterTeams.length) return false;
        if (teamFilterSelectedIds.size === 0) return false;
        return teamFilterSelectedIds.size < teamFilterTeams.length;
    }

    function filterTeamList(list, idKey = 'team_id') {
        if (!Array.isArray(list)) return [];
        if (!shouldFilterTeams()) return list;
        return list.filter(item => teamFilterSelectedIds.has(String(item[idKey])));
    }

    function sumByField(list, field) {
        if (!Array.isArray(list)) return 0;
        return list.reduce((sum, item) => sum + (Number(item?.[field]) || 0), 0);
    }

    function buildStatsQueryParams(options = {}) {
        const includeTeamFilter = Boolean(options.includeTeamFilter);
        let startValue = customStartDate;
        let endValue = customEndDate;
        const params = [];
        if (!startValue || !endValue) {
            const inputs = getCustomRangeInputValues();
            if (inputs.startValue && inputs.endValue) {
                startValue = inputs.startValue;
                endValue = inputs.endValue;
                customStartDate = startValue;
                customEndDate = endValue;
            }
        }
        if (startValue && endValue) {
            params.push(`start_date=${encodeURIComponent(startValue)}`);
            params.push(`end_date=${encodeURIComponent(endValue)}`);
        } else {
            params.push(`days=${currentDays}`);
        }

        if (includeTeamFilter && shouldFilterTeams()) {
            const selected = Array.from(teamFilterSelectedIds)
                .map(id => String(id).trim())
                .filter(id => id);
            if (selected.length > 0) {
                params.push(`team_ids=${encodeURIComponent(selected.join(','))}`);
            }
        }
        return params.join('&');
    }

    function buildStatsUrl(endpoint, options = {}) {
        return `/api/admin/team_statistics/${endpoint}?${buildStatsQueryParams(options)}`;
    }

    function parseDateValue(value) {
        if (!value) return null;
        const parts = value.split('-').map(Number);
        if (parts.length !== 3 || parts.some(Number.isNaN)) {
            return null;
        }
        return new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    }

    function calculateRangeDays(startValue, endValue) {
        const startDateObj = parseDateValue(startValue);
        const endDateObj = parseDateValue(endValue);
        if (!startDateObj || !endDateObj) return null;
        const diffMs = endDateObj.getTime() - startDateObj.getTime();
        return Math.floor(diffMs / (24 * 60 * 60 * 1000)) + 1;
    }

    function updateCustomRangeDisplay(startValue, endValue) {
        const display = document.getElementById('custom-range-display');
        if (!display) return;

        if (startValue && endValue) {
            const separator = translate('teamStats.to', 'to');
            display.textContent = `${startValue} ${separator} ${endValue}`;
            return;
        }

        display.textContent = '';
    }

    function getCustomRangeInputValues() {
        const startInput = document.getElementById('custom-range-start');
        const endInput = document.getElementById('custom-range-end');
        const startValue = startInput ? startInput.value.trim() : '';
        const endValue = endInput ? endInput.value.trim() : '';
        return { startValue, endValue };
    }

    function clearCustomRangeInputs() {
        const startInput = document.getElementById('custom-range-start');
        const endInput = document.getElementById('custom-range-end');
        if (startInput) startInput.value = '';
        if (endInput) endInput.value = '';
        updateCustomRangeDisplay(null, null);
        const dropdownToggle = document.getElementById('custom-range-toggle');
        if (dropdownToggle) dropdownToggle.classList.remove('active');
    }

    function applyCustomRange() {
        const { startValue, endValue } = getCustomRangeInputValues();

        if (!startValue || !endValue) {
            AppUtils.showError(
                translate('teamStats.customRangeMissing', '請選擇開始與結束日期')
            );
            return;
        }

        const rangeDays = calculateRangeDays(startValue, endValue);
        if (!rangeDays || rangeDays <= 0) {
            AppUtils.showError(
                translate('teamStats.customRangeInvalid', '結束日期不可早於開始日期')
            );
            return;
        }

        if (rangeDays > MAX_CUSTOM_RANGE_DAYS) {
            AppUtils.showError(
                translate(
                    'teamStats.customRangeTooLong',
                    `日期區間不可超過 ${MAX_CUSTOM_RANGE_DAYS} 天`,
                    { max: MAX_CUSTOM_RANGE_DAYS }
                )
            );
            return;
        }

        customStartDate = startValue;
        customEndDate = endValue;
        currentDays = rangeDays;

        document.querySelectorAll('[data-days]').forEach(btn => btn.classList.remove('active'));
        updateCustomRangeDisplay(startValue, endValue);
        loadAllStatistics();

        const dropdownToggle = document.getElementById('custom-range-toggle');
        if (dropdownToggle) dropdownToggle.classList.add('active');
        if (dropdownToggle && window.bootstrap && window.bootstrap.Dropdown) {
            const instance = window.bootstrap.Dropdown.getInstance(dropdownToggle)
                || new window.bootstrap.Dropdown(dropdownToggle);
            instance.hide();
        }
    }

    /**
     * 初始化事件監聽器
     */
    function initEventListeners() {
        // 日期範圍選擇器
        document.querySelectorAll('[data-days]').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('[data-days]').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                currentDays = parseInt(this.getAttribute('data-days'));
                customStartDate = null;
                customEndDate = null;
                clearCustomRangeInputs();
                loadAllStatistics();
            });
        });

        const customApplyBtn = document.getElementById('custom-range-apply');
        if (customApplyBtn) {
            customApplyBtn.addEventListener('click', function(event) {
                event.preventDefault();
                event.stopPropagation();
                applyCustomRange();
            });
        }

        const rangeStartInput = document.getElementById('custom-range-start');
        const rangeEndInput = document.getElementById('custom-range-end');
        const rangeInputs = [rangeStartInput, rangeEndInput].filter(Boolean);
        rangeInputs.forEach(input => {
            input.addEventListener('change', () => {
                const { startValue, endValue } = getCustomRangeInputValues();
                if (startValue && endValue) {
                    updateCustomRangeDisplay(startValue, endValue);
                }
            });
            input.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    applyCustomRange();
                }
            });
        });

        // 刷新按鈕
        document.getElementById('refresh-stats-btn').addEventListener('click', async function() {
            await loadAllStatistics();
        });

        // 標籤頁切換事件（延遲載入策略）
        document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tab => {
            tab.addEventListener('shown.bs.tab', function(event) {
                const targetId = event.target.getAttribute('data-bs-target');
                handleTabSwitch(targetId, event.target);
            });
        });
    }

    /**
     * 處理標籤頁切換（首次載入時才獲取數據）
     */
    function handleTabSwitch(targetId, tabElement = null) {
        if (!window.i18n || !window.i18n.isReady || !window.i18n.isReady()) {
            return;
        }

        // Safari 在 hidden tab 首次顯示時，偶爾會漏掉部分靜態翻譯；
        // 切換分頁後補做一次局部 retranslate，避免分頁標題與內容露出 key/fallback。
        window.requestAnimationFrame(() => {
            if (tabElement instanceof Element) {
                window.i18n.retranslate(tabElement);
            }

            if (!targetId) {
                return;
            }

            const pane = document.querySelector(targetId);
            if (pane instanceof Element) {
                window.i18n.retranslate(pane);
            }
        });

        // QA AI Helper tab: lazy-load on first switch
        if (targetId === '#qa-ai-helper-pane' && !helperDataLoaded) {
            loadQaAiHelperDashboard();
        }
    }

    /**
     * 載入所有統計數據
     */
    async function loadAllStatistics() {
        AppUtils.showLoading('載入統計數據中...');

        // Reset helper dashboard cache so refresh reloads it
        helperDataLoaded = false;
        helperSubTabData = {};

        try {
            const tasks = [
                loadOverview(),
                loadTeamActivity(),
                loadTestCaseTrends(),
                loadTestRunMetrics(),
                loadUserActivity(),
                loadAuditAnalysis()
                // loadDepartmentStats()  // 已註解 - Department Stats 功能暫時停用
            ];

            // If helper tab is currently active, also reload it
            const helperPane = document.getElementById('qa-ai-helper-pane');
            if (helperPane && helperPane.classList.contains('active')) {
                tasks.push(loadQaAiHelperDashboard());
            }

            await Promise.all(tasks);

            AppUtils.showSuccess('統計數據載入完成');
        } catch (error) {
            console.error('載入統計數據失敗:', error);
            AppUtils.showError('載入統計數據失敗');
        } finally {
            AppUtils.hideLoading(true);
        }
    }

    async function authFetch(url, options) {
        if (!authClient) {
            throw new Error('AuthClient 尚未就緒');
        }
        return authClient.fetch(url, options);
    }

    async function fetchStatsJson(url) {
        // 加入時間戳記以防止快取
        const separator = url.includes('?') ? '&' : '?';
        const urlWithTimestamp = `${url}${separator}_t=${Date.now()}`;
        
        const response = await authFetch(urlWithTimestamp);
        if (!response.ok) {
            const body = await response.text().catch(() => '');
            throw new Error(`Failed to fetch ${url}: ${response.status} ${body}`);
        }
        return response.json();
    }

    /**
     * 1. 載入總覽數據
     */
    async function loadOverview() {
        try {
            const data = await fetchStatsJson(
                buildStatsUrl('overview')
            );

            const filteredTeamTestCases = filterTeamList(data.team_test_cases, 'team_id');
            const filteredTeamTestRuns = filterTeamList(data.team_test_runs, 'team_id');
            const teamCountValue = shouldFilterTeams()
                ? teamFilterSelectedIds.size
                : (data.team_count || 0);
            const testCaseTotal = shouldFilterTeams()
                ? sumByField(filteredTeamTestCases, 'test_case_count')
                : (data.test_case_total || 0);
            const testRunTotal = shouldFilterTeams()
                ? sumByField(filteredTeamTestRuns, 'test_run_count')
                : (data.test_run_total || 0);

            // 更新關鍵指標卡片
            document.getElementById('overview-team-count').textContent = teamCountValue;
            document.getElementById('overview-user-count').textContent = data.user_count || 0;
            document.getElementById('overview-test-case-total').textContent = testCaseTotal;
            document.getElementById('overview-test-run-total').textContent = testRunTotal;

            // 更新團隊 Test Case 統計表格
            const teamTestCasesTbody = document.getElementById('team-test-cases-tbody');
            if (filteredTeamTestCases && filteredTeamTestCases.length > 0) {
                teamTestCasesTbody.innerHTML = filteredTeamTestCases.map(team => `
                    <tr>
                        <td>${escapeHtml(team.team_name)}</td>
                        <td><strong>${team.test_case_count}</strong></td>
                    </tr>
                `).join('');
            } else {
                teamTestCasesTbody.innerHTML = '<tr><td colspan="2" class="text-center text-muted">無數據</td></tr>';
            }

            // 更新團隊 Test Run 統計表格
            const teamTestRunsTbody = document.getElementById('team-test-runs-tbody');
            if (filteredTeamTestRuns && filteredTeamTestRuns.length > 0) {
                teamTestRunsTbody.innerHTML = filteredTeamTestRuns.map(team => `
                    <tr>
                        <td>${escapeHtml(team.team_name)}</td>
                        <td><strong>${team.test_run_count}</strong></td>
                    </tr>
                `).join('');
            } else {
                teamTestRunsTbody.innerHTML = '<tr><td colspan="2" class="text-center text-muted">無數據</td></tr>';
            }

            // 更新最近活動表格
            const tbody = document.getElementById('recent-activity-tbody');
            if (data.recent_activity && data.recent_activity.length > 0) {
                tbody.innerHTML = data.recent_activity.map(activity => `
                    <tr>
                        <td>${formatDateTime(activity.timestamp)}</td>
                        <td>${escapeHtml(activity.username)}</td>
                        <td><span class="badge bg-primary">${activity.action_type}</span></td>
                        <td><span class="badge bg-secondary">${activity.resource_type}</span></td>
                        <td>${escapeHtml(activity.action_brief || '-')}</td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">無活動記錄</td></tr>';
            }
        } catch (error) {
            console.error('載入總覽數據失敗:', error);
            throw error;
        }
    }

    /**
     * 2. 載入團隊活動數據
     */
    async function loadTeamActivity() {
        try {
            const data = await fetchStatsJson(
                buildStatsUrl('team_activity')
            );

            const allTeamsActivity = filterTeamList(
                data.all_teams_activity || data.top_active_teams || [],
                'team_id'
            );
            const topTeams = allTeamsActivity.slice(0, 10);

            // 渲染最活躍團隊圖表
            renderTeamActivityChart(topTeams);

            // 更新活動詳情表格
            const tbody = document.getElementById('team-activity-tbody');
            if (allTeamsActivity && allTeamsActivity.length > 0) {
                tbody.innerHTML = allTeamsActivity.map(team => `
                    <tr>
                        <td>${escapeHtml(team.team_name)}</td>
                        <td><strong>${team.total}</strong></td>
                        <td>${team.by_action?.CREATE ?? 0}</td>
                        <td>${team.by_action?.UPDATE ?? 0}</td>
                        <td>${team.by_action?.DELETE ?? 0}</td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">無數據</td></tr>';
            }
        } catch (error) {
            console.error('載入團隊活動數據失敗:', error);
            throw error;
        }
    }

    /**
     * 3. 載入測試案例趨勢數據
     */
    async function loadTestCaseTrends() {
        try {
            const data = await fetchStatsJson(
                buildStatsUrl('test_case_trends')
            );

            const filteredTeamDaily = filterTeamList(data?.per_team_daily, 'team_id');
            const hasTeamDaily = Array.isArray(filteredTeamDaily) && filteredTeamDaily.length > 0;

            if (hasTeamDaily) {
                const dates = Array.isArray(data.dates) ? data.dates : [];
                renderTestCaseCreatedChart(dates, filteredTeamDaily);
                renderTestCaseUpdatedChart(dates, filteredTeamDaily);
                renderTestCaseTeamDailyTable(filteredTeamDaily);
                renderTestCaseTeamSummaryTable(filteredTeamDaily, null);
            } else {
                renderTestCaseCreatedChart([], []);
                renderTestCaseUpdatedChart([], []);
                renderTestCaseTeamDailyTable([]);
                renderTestCaseTeamSummaryTable([], null);
            }
        } catch (error) {
            console.error('載入測試案例趨勢失敗:', error);
            throw error;
        }
    }

    /**
     * 4. 載入測試執行指標數據
     */
    async function loadTestRunMetrics() {
        try {
            const data = await fetchStatsJson(
                buildStatsUrl('test_run_metrics')
            );

            const dates = data.dates || [];
            const perTeamDaily = filterTeamList(data.per_team_daily || [], 'team_id');
            const perTeamPassRate = filterTeamList(data.per_team_pass_rate || [], 'team_id');
            const filteredByTeam = filterTeamList(data.by_team || [], 'team_id');

            // 渲染每日執行次數圖表（按團隊分組）
            if (dates.length > 0 && perTeamDaily.length > 0) {
                renderTestRunDailyChart(dates, perTeamDaily);
            } else {
                renderTestRunDailyChart([], []);
            }

            // 渲染通過率趨勢圖表（按團隊分組）
            if (dates.length > 0 && perTeamPassRate.length > 0) {
                renderTestRunPassRateChart(dates, perTeamPassRate);
            } else {
                renderTestRunPassRateChart([], []);
            }

            // 渲染狀態分佈圖表
            if (data.by_status) {
                renderTestRunStatusChart(data.by_status);
            }

            // 更新團隊統計表格
            const tbody = document.getElementById('test-run-team-tbody');
            if (filteredByTeam && filteredByTeam.length > 0) {
                tbody.innerHTML = filteredByTeam.map(team => `
                    <tr>
                        <td>${escapeHtml(team.team_name)}</td>
                        <td><strong>${team.count}</strong></td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = '<tr><td colspan="2" class="text-center text-muted">無數據</td></tr>';
            }
        } catch (error) {
            console.error('載入測試執行指標失敗:', error);
            throw error;
        }
    }

    /**
     * 5. 載入使用者行為數據
     */
    async function loadUserActivity() {
        try {
            const data = await fetchStatsJson(
                buildStatsUrl('user_activity')
            );

            // 渲染最活躍使用者圖表
            if (data.top_users) {
                renderUserActivityChart(data.top_users);
            }

            // 渲染操作類型分佈圖表
            if (data.by_operation) {
                renderUserOperationChart(data.by_operation);
            }

            // 渲染每小時活動分佈圖表
            if (data.hourly_distribution) {
                renderUserHourlyChart(data.hourly_distribution);
            }
        } catch (error) {
            console.error('載入使用者行為數據失敗:', error);
            throw error;
        }
    }

    /**
     * 6. 載入審計分析數據
     */
    async function loadAuditAnalysis() {
        try {
            const data = await fetchStatsJson(
                buildStatsUrl('audit_analysis')
            );

            // 渲染資源類型分佈圖表
            if (data.by_resource_type) {
                renderAuditResourceChart(data.by_resource_type);
            }

            // 渲染嚴重性分佈圖表
            if (data.by_severity) {
                renderAuditSeverityChart(data.by_severity);
            }

            // 渲染每日趨勢圖表
            if (data.daily_trend) {
                renderAuditDailyChart(data.daily_trend);
            }

            // 更新關鍵操作表格
            const tbody = document.getElementById('audit-critical-tbody');
            if (data.critical_actions && data.critical_actions.length > 0) {
                tbody.innerHTML = data.critical_actions.map(action => `
                    <tr>
                        <td>${formatDateTime(action.timestamp)}</td>
                        <td>${escapeHtml(action.username)}</td>
                        <td><span class="badge bg-warning">${action.action_type}</span></td>
                        <td><span class="badge bg-danger">${action.resource_type}</span></td>
                        <td>${escapeHtml(action.action_brief || '-')}</td>
                    </tr>
                `).join('');
            } else {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">無關鍵操作記錄</td></tr>';
            }
        } catch (error) {
            console.error('載入審計分析數據失敗:', error);
            throw error;
        }
    }

    /**
     * 7. 載入部門統計數據
     */
    async function loadDepartmentStats() {
        try {
            const data = await fetchStatsJson(
                buildStatsUrl('department_stats')
            );

            // 更新部門列表表格
            const deptTbody = document.getElementById('department-list-tbody');
            const departmentList = Array.isArray(data.department_list) ? data.department_list : [];
            if (departmentList.length > 0) {
                const totalLabel = translate('teamStats.department.totalCountLabel', '總數');
                const directLabel = translate('teamStats.department.directCountLabel', '直屬');

                deptTbody.innerHTML = departmentList.map(dept => {
                    const name = escapeHtml(dept.display_name || dept.dept_name || dept.dept_id || '-');
                    const total = Number(dept.total_user_count ?? dept.user_count ?? 0);
                    const direct = Number(dept.direct_user_count ?? 0);
                    const directMarkup = direct > 0 ? `<span class="text-muted ms-1">(${directLabel}: ${direct})</span>` : '';
                    return `
                        <tr>
                            <td title="${escapeHtml(dept.dept_id || '')}">${name}</td>
                            <td><strong>${total}</strong>${directMarkup}</td>
                        </tr>
                    `;
                }).join('');
            } else {
                deptTbody.innerHTML = '<tr><td colspan="2" class="text-center text-muted">無部門數據</td></tr>';
            }

            // 渲染使用者角色分佈圖表
            if (data.user_distribution) {
                renderDepartmentRoleChart(data.user_distribution);
            }

            // 更新最活躍使用者表格
            const usersTbody = document.getElementById('department-users-tbody');
            if (data.by_department_users && data.by_department_users.length > 0) {
                usersTbody.innerHTML = data.by_department_users.map(user => `
                    <tr>
                        <td>${escapeHtml(user.username)}</td>
                        <td><strong>${user.action_count}</strong></td>
                    </tr>
                `).join('');
            } else {
                usersTbody.innerHTML = '<tr><td colspan="2" class="text-center text-muted">無數據</td></tr>';
            }
        } catch (error) {
            console.error('載入部門統計失敗:', error);
            throw error;
        }
    }

    // ==================== 圖表渲染函數 ====================

    function bootstrapFallbackChart() {
        if (typeof window.Chart !== 'undefined') {
            return;
        }

        class SimpleChart {
            constructor(target, config) {
                this.config = config || {};
                this.canvas = target instanceof HTMLCanvasElement ? target : target?.canvas || null;
                if (!this.canvas) {
                    throw new Error('SimpleChart 需要一個 canvas 元素');
                }
                this.ctx = this.canvas.getContext('2d');
                this._initCanvasSize();
                this._draw();
            }

            destroy() {
                if (this.ctx && this.canvas) {
                    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
                }
            }

            _initCanvasSize() {
                const rect = this.canvas.getBoundingClientRect();
                const ratio = window.devicePixelRatio || 1;
                const width = rect.width || this.canvas.width || 400;
                const height = rect.height || this.canvas.height || 200;

                if (this.ctx.resetTransform) {
                    this.ctx.resetTransform();
                } else {
                    this.ctx.setTransform(1, 0, 0, 1, 0, 0);
                }

                this.canvas.width = width * ratio;
                this.canvas.height = height * ratio;
                this.canvas.style.width = width + 'px';
                this.canvas.style.height = height + 'px';
                this.ctx.scale(ratio, ratio);

                this.width = width;
                this.height = height;
            }

            _draw() {
                if (!this.ctx) return;
                this.ctx.clearRect(0, 0, this.width, this.height);

                const type = this.config.type;
                if (type === 'line') {
                    this._drawLine();
                } else if (type === 'pie' || type === 'doughnut') {
                    this._drawPie(type === 'doughnut');
                } else if (type === 'bar') {
                    if (this.config.options?.indexAxis === 'y') {
                        this._drawHorizontalBar();
                    } else {
                        this._drawVerticalBar();
                    }
                } else {
                    this._drawVerticalBar();
                }
            }

            _getDatasets() {
                const datasets = this.config?.data?.datasets;
                return Array.isArray(datasets) ? datasets : [];
            }

            _getDataset() {
                const datasets = this._getDatasets();
                return datasets[0] || { data: [] };
            }

            _getLabels() {
                return this.config?.data?.labels || [];
            }

            _getDataArray() {
                const dataset = this._getDataset();
                return Array.isArray(dataset.data) ? dataset.data.map(value => Number(value) || 0) : [];
            }

            _getColor(index) {
                const dataset = this._getDataset();
                const palette = [
                    '#5390d9', '#5e60ce', '#64dfdf', '#80ffdb', '#ffb703', '#fb8500', '#ef476f'
                ];

                if (Array.isArray(dataset.backgroundColor) && dataset.backgroundColor[index]) {
                    return dataset.backgroundColor[index];
                }
                if (typeof dataset.backgroundColor === 'string') {
                    return dataset.backgroundColor;
                }
                return palette[index % palette.length];
            }

            _withAlpha(color, alpha) {
                if (typeof color !== 'string') {
                    return `rgba(83, 144, 217, ${alpha})`;
                }
                if (color.startsWith('rgba')) {
                    return color.replace(/rgba\(([^)]+)\)/, (_match, body) => {
                        const parts = body.split(',').map(part => part.trim());
                        return `rgba(${parts.slice(0, 3).join(', ')}, ${alpha})`;
                    });
                }
                if (color.startsWith('rgb')) {
                    return color.replace(/rgb\(([^)]+)\)/, (_match, body) => `rgba(${body}, ${alpha})`);
                }
                if (color.startsWith('#')) {
                    let r, g, b;
                    if (color.length === 7) {
                        r = parseInt(color.slice(1, 3), 16);
                        g = parseInt(color.slice(3, 5), 16);
                        b = parseInt(color.slice(5, 7), 16);
                    } else if (color.length === 4) {
                        r = parseInt(color[1] + color[1], 16);
                        g = parseInt(color[2] + color[2], 16);
                        b = parseInt(color[3] + color[3], 16);
                    } else {
                        return `rgba(83, 144, 217, ${alpha})`;
                    }
                    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
                }
                return `rgba(83, 144, 217, ${alpha})`;
            }

            _drawAxes(padding) {
                this.ctx.strokeStyle = '#adb5bd';
                this.ctx.lineWidth = 1;
                // x axis
                this.ctx.beginPath();
                this.ctx.moveTo(padding, this.height - padding);
                this.ctx.lineTo(this.width - padding, this.height - padding);
                this.ctx.stroke();

                // y axis
                this.ctx.beginPath();
                this.ctx.moveTo(padding, padding);
                this.ctx.lineTo(padding, this.height - padding);
                this.ctx.stroke();
            }

            _drawVerticalBar() {
                const padding = 40;
                const data = this._getDataArray();
                const labels = this._getLabels();
                const maxValue = Math.max(...data, 1);
                const availableWidth = this.width - padding * 2;
                const space = data.length > 0 ? availableWidth / data.length : 0;
                const barWidth = space * 0.6;

                this._drawAxes(padding);
                this.ctx.textAlign = 'center';
                this.ctx.font = '12px sans-serif';

                data.forEach((value, index) => {
                    const barHeight = maxValue === 0 ? 0 : (value / maxValue) * (this.height - padding * 2);
                    const x = padding + index * space + (space - barWidth) / 2;
                    const y = this.height - padding - barHeight;

                    this.ctx.fillStyle = this._getColor(index);
                    this.ctx.fillRect(x, y, barWidth, barHeight);

                    this.ctx.fillStyle = '#495057';
                    if (labels[index]) {
                        this.ctx.fillText(String(labels[index]), x + barWidth / 2, this.height - padding + 16);
                    }
                    this.ctx.fillText(String(value), x + barWidth / 2, Math.max(y - 6, padding - 6));
                });
            }

            _drawHorizontalBar() {
                const padding = 60;
                const data = this._getDataArray();
                const labels = this._getLabels();
                const maxValue = Math.max(...data, 1);
                const availableHeight = this.height - padding * 2;
                const space = data.length > 0 ? availableHeight / data.length : 0;
                const barHeight = space * 0.6;

                this.ctx.font = '12px sans-serif';
                this.ctx.textBaseline = 'middle';

                data.forEach((value, index) => {
                    const barLength = maxValue === 0 ? 0 : (value / maxValue) * (this.width - padding * 2);
                    const x = padding;
                    const y = padding + index * space + (space - barHeight) / 2;

                    this.ctx.fillStyle = this._getColor(index);
                    this.ctx.fillRect(x, y, barLength, barHeight);

                    this.ctx.fillStyle = '#495057';
                    if (labels[index]) {
                        this.ctx.textAlign = 'right';
                        this.ctx.fillText(String(labels[index]), padding - 8, y + barHeight / 2);
                    }
                    this.ctx.textAlign = 'left';
                    this.ctx.fillText(String(value), x + barLength + 6, y + barHeight / 2);
                });
            }

            _drawLine() {
                const padding = 48;
                const datasets = this._getDatasets();
                const labels = this._getLabels();

                if (datasets.length === 0 || labels.length === 0) {
                    return;
                }

                const palette = [
                    '#5390d9', '#5e60ce', '#64dfdf', '#80ffdb', '#ffb703',
                    '#fb8500', '#ef476f', '#06d6a0', '#118ab2', '#8ecae6'
                ];

                const values = [];
                datasets.forEach(dataset => {
                    const dataArray = Array.isArray(dataset.data) ? dataset.data : [];
                    dataArray.forEach(value => {
                        const num = Number(value);
                        if (!Number.isNaN(num)) {
                            values.push(num);
                        }
                    });
                });

                if (values.length === 0) {
                    values.push(0);
                }

                const maxValue = Math.max(...values, 1);
                const minValue = Math.min(...values, 0);
                const spread = Math.max(maxValue - minValue, 1);
                const stepX = labels.length > 1 ? (this.width - padding * 2) / (labels.length - 1) : 0;

                this._drawAxes(padding);

                this.ctx.font = '12px sans-serif';
                this.ctx.fillStyle = '#495057';
                this.ctx.textAlign = 'center';
                labels.forEach((label, index) => {
                    const x = padding + index * stepX;
                    this.ctx.fillText(String(label), x, this.height - padding + 18);
                });

                let legendX = padding;
                const legendY = padding - 24;

                datasets.forEach((dataset, dsIndex) => {
                    const rawColor = Array.isArray(dataset.borderColor)
                        ? dataset.borderColor[0]
                        : dataset.borderColor || dataset.backgroundColor;
                    const strokeColor = typeof rawColor === 'string'
                        ? rawColor
                        : palette[dsIndex % palette.length];
                    const fillColor = Array.isArray(dataset.backgroundColor)
                        ? dataset.backgroundColor[0]
                        : (typeof dataset.backgroundColor === 'string'
                            ? dataset.backgroundColor
                            : this._withAlpha(strokeColor, 0.2));

                    const points = labels.map((_, index) => {
                        const rawValue = Array.isArray(dataset.data) ? dataset.data[index] : 0;
                        const value = Number(rawValue) || 0;
                        const ratio = (value - minValue) / spread;
                        const x = padding + index * stepX;
                        const y = this.height - padding - ratio * (this.height - padding * 2);
                        return { x, y, value };
                    });

                    if (dataset.fill) {
                        this.ctx.beginPath();
                        const firstPoint = points[0];
                        this.ctx.moveTo(firstPoint ? firstPoint.x : padding, this.height - padding);
                        points.forEach(point => this.ctx.lineTo(point.x, point.y));
                        const lastPoint = points[points.length - 1];
                        this.ctx.lineTo(lastPoint ? lastPoint.x : padding, this.height - padding);
                        this.ctx.closePath();
                        this.ctx.fillStyle = fillColor;
                        this.ctx.fill();
                    }

                    this.ctx.beginPath();
                    points.forEach((point, index) => {
                        if (index === 0) {
                            this.ctx.moveTo(point.x, point.y);
                        } else {
                            this.ctx.lineTo(point.x, point.y);
                        }
                    });
                    this.ctx.strokeStyle = strokeColor;
                    this.ctx.lineWidth = 2;
                    this.ctx.stroke();

                    this.ctx.fillStyle = strokeColor;
                    points.forEach(point => {
                        this.ctx.beginPath();
                        this.ctx.arc(point.x, point.y, 3, 0, Math.PI * 2);
                        this.ctx.fill();
                    });

                    if (dataset.label) {
                        const labelWidth = this.ctx.measureText(dataset.label).width;
                        this.ctx.fillStyle = strokeColor;
                        this.ctx.fillRect(legendX, legendY, 12, 12);
                        this.ctx.fillStyle = '#495057';
                        this.ctx.textAlign = 'left';
                        this.ctx.fillText(dataset.label, legendX + 16, legendY + 10);
                        legendX += labelWidth + 40;
                    }
                });
            }

            _drawPie(isDoughnut) {
                const data = this._getDataArray();
                const labels = this._getLabels();
                const sum = data.reduce((acc, value) => acc + value, 0) || 1;
                const radius = Math.min(this.width, this.height) / 2 - 20;
                const centerX = this.width / 2;
                const centerY = this.height / 2;

                let startAngle = -Math.PI / 2;
                data.forEach((value, index) => {
                    const angle = (value / sum) * Math.PI * 2;
                    this.ctx.beginPath();
                    this.ctx.moveTo(centerX, centerY);
                    this.ctx.fillStyle = this._getColor(index);
                    this.ctx.arc(centerX, centerY, radius, startAngle, startAngle + angle);
                    this.ctx.closePath();
                    this.ctx.fill();

                    const midAngle = startAngle + angle / 2;
                    const labelRadius = isDoughnut ? radius * 0.65 : radius * 0.5;
                    const labelX = centerX + Math.cos(midAngle) * labelRadius;
                    const labelY = centerY + Math.sin(midAngle) * labelRadius;

                    this.ctx.fillStyle = '#212529';
                    this.ctx.font = '12px sans-serif';
                    this.ctx.textAlign = 'center';
                    const percent = ((value / sum) * 100).toFixed(0);
                    this.ctx.fillText(`${percent}%`, labelX, labelY);

                    startAngle += angle;
                });

                if (isDoughnut) {
                    this.ctx.save();
                    this.ctx.globalCompositeOperation = 'destination-out';
                    this.ctx.beginPath();
                    this.ctx.arc(centerX, centerY, radius * 0.5, 0, Math.PI * 2);
                    this.ctx.fill();
                    this.ctx.restore();
                }

                // 圖例
                const legendStartY = 10;
                labels.forEach((label, index) => {
                    this.ctx.fillStyle = this._getColor(index);
                    this.ctx.fillRect(this.width - 150, legendStartY + index * 18, 12, 12);
                    this.ctx.fillStyle = '#495057';
                    this.ctx.font = '12px sans-serif';
                    this.ctx.textAlign = 'left';
                    this.ctx.fillText(`${label}: ${data[index] ?? 0}`, this.width - 130, legendStartY + index * 18 + 10);
                });
            }
        }

        window.Chart = SimpleChart;
    }

    /**
     * 渲染團隊活動圖表
     */
    function renderTeamActivityChart(data) {
        const ctx = document.getElementById('team-activity-chart');
        if (!ctx) return;

        destroyChart('team-activity-chart');

        if (!Array.isArray(data) || data.length === 0) {
            ctx.getContext('2d')?.clearRect(0, 0, ctx.width, ctx.height);
            return;
        }

        charts['team-activity-chart'] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.map(t => t.team_name),
                datasets: [{
                    label: '操作次數',
                    data: data.map(t => t.total),
                    backgroundColor: 'rgba(54, 162, 235, 0.6)',
                    borderColor: 'rgba(54, 162, 235, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    const teamColorPalette = [
        '#3b82f6', '#22c55e', '#a855f7', '#f97316', '#ef4444',
        '#14b8a6', '#8b5cf6', '#f59e0b', '#64748b', '#0ea5e9',
        '#d946ef', '#10b981', '#facc15', '#4b5563', '#2563eb'
    ];

    function toRgba(color, alpha) {
        if (typeof color !== 'string') return `rgba(59, 130, 246, ${alpha})`;
        if (color.startsWith('rgba')) {
            return color.replace(/rgba\(([^)]+)\)/, (_match, body) => {
                const parts = body.split(',').map(part => part.trim());
                return `rgba(${parts.slice(0, 3).join(', ')}, ${alpha})`;
            });
        }
        if (color.startsWith('rgb')) {
            return color.replace(/rgb\(([^)]+)\)/, (_match, body) => `rgba(${body}, ${alpha})`);
        }
        if (color.startsWith('#') && (color.length === 7 || color.length === 4)) {
            let r, g, b;
            if (color.length === 7) {
                r = parseInt(color.slice(1, 3), 16);
                g = parseInt(color.slice(3, 5), 16);
                b = parseInt(color.slice(5, 7), 16);
            } else {
                r = parseInt(color[1] + color[1], 16);
                g = parseInt(color[2] + color[2], 16);
                b = parseInt(color[3] + color[3], 16);
            }
            return `rgba(${r}, ${g}, ${b}, ${alpha})`;
        }
        return `rgba(59, 130, 246, ${alpha})`;
    }

    function buildTeamDatasets(perTeam, valueKey) {
        return perTeam.map((team, index) => {
            const baseColor = teamColorPalette[index % teamColorPalette.length];
            return {
                label: team.team_name || `Team #${team.team_id}`,
                data: team.daily.map(entry => entry[valueKey] ?? 0),
                borderColor: baseColor,
                backgroundColor: toRgba(baseColor, 0.15),
                tension: 0.25,
                fill: false,
                spanGaps: true,
                pointRadius: 3,
                pointHoverRadius: 5
            };
        });
    }

    function renderTestCaseCreatedChart(dates, perTeam) {
        const ctx = document.getElementById('test-case-created-chart');
        if (!ctx) return;

        destroyChart('test-case-created-chart');

        if (!dates || dates.length === 0 || !perTeam || perTeam.length === 0) {
            ctx.getContext('2d')?.clearRect(0, 0, ctx.width, ctx.height);
            return;
        }

        charts['test-case-created-chart'] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: dates,
                datasets: buildTeamDatasets(perTeam, 'created')
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    function renderTestCaseUpdatedChart(dates, perTeam) {
        const ctx = document.getElementById('test-case-updated-chart');
        if (!ctx) return;

        destroyChart('test-case-updated-chart');

        if (!dates || dates.length === 0 || !perTeam || perTeam.length === 0) {
            ctx.getContext('2d')?.clearRect(0, 0, ctx.width, ctx.height);
            return;
        }

        charts['test-case-updated-chart'] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: dates,
                datasets: buildTeamDatasets(perTeam, 'updated')
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    function renderTestCaseTeamDailyTable(perTeam) {
        const tbody = document.getElementById('test-case-team-daily-tbody');
        if (!tbody) return;

        if (!Array.isArray(perTeam) || perTeam.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">無數據</td></tr>';
            return;
        }

        const rows = [];
        perTeam.forEach(team => {
            (team.daily || []).forEach(entry => {
                const created = Number(entry.created) || 0;
                const updated = Number(entry.updated) || 0;
                if (created === 0 && updated === 0) {
                    return;
                }
                rows.push({
                    date: entry.date,
                    teamName: team.team_name || `Team #${team.team_id}`,
                    created,
                    updated
                });
            });
        });

        if (rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">無數據</td></tr>';
            return;
        }

        rows.sort((a, b) => {
            if (a.date === b.date) {
                return a.teamName.localeCompare(b.teamName, 'zh-Hant');
            }
            return b.date.localeCompare(a.date);
        });

        tbody.innerHTML = rows.map(row => `
            <tr>
                <td>${escapeHtml(row.date)}</td>
                <td>${escapeHtml(row.teamName)}</td>
                <td><strong>${row.created}</strong></td>
                <td>${row.updated}</td>
            </tr>
        `).join('');
    }

    function renderTestCaseTeamSummaryTable(perTeam, overall) {
        const tbody = document.getElementById('test-case-team-summary-tbody');
        if (!tbody) return;

        if (!Array.isArray(perTeam) || perTeam.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">無數據</td></tr>';
            return;
        }

        const sortedTeams = [...perTeam].sort((a, b) => {
            if (a.total_created === b.total_created) {
                return b.total_updated - a.total_updated;
            }
            return b.total_created - a.total_created;
        });

        const totalCreated = overall?.total_created ?? sortedTeams.reduce((sum, team) => sum + (team.total_created || 0), 0);
        const totalUpdated = overall?.total_updated ?? sortedTeams.reduce((sum, team) => sum + (team.total_updated || 0), 0);
        const totalLabel = translate('teamStats.testCase.totalLabel', '總計');

        const rows = sortedTeams.map(team => `
            <tr>
                <td>${escapeHtml(team.team_name || `Team #${team.team_id}`)}</td>
                <td><strong>${team.total_created}</strong></td>
                <td>${team.total_updated}</td>
            </tr>
        `);

        rows.push(`
            <tr class="table-active">
                <td>${escapeHtml(totalLabel)}</td>
                <td><strong>${totalCreated}</strong></td>
                <td>${totalUpdated}</td>
            </tr>
        `);

        tbody.innerHTML = rows.join('');
    }

    /**
     * 渲染測試執行每日圖表（按團隊分組）
     */
    function renderTestRunDailyChart(dates, perTeam) {
        const ctx = document.getElementById('test-run-daily-chart');
        if (!ctx) return;

        destroyChart('test-run-daily-chart');

        if (!dates || dates.length === 0 || !perTeam || perTeam.length === 0) {
            ctx.getContext('2d')?.clearRect(0, 0, ctx.width, ctx.height);
            return;
        }

        charts['test-run-daily-chart'] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: dates,
                datasets: buildTeamDatasets(perTeam, 'count')
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    /**
     * 渲染測試執行通過率趨勢圖表（按團隊分組）
     */
    function renderTestRunPassRateChart(dates, perTeam) {
        const ctx = document.getElementById('test-run-pass-rate-chart');
        if (!ctx) return;

        destroyChart('test-run-pass-rate-chart');

        if (!dates || dates.length === 0 || !perTeam || perTeam.length === 0) {
            ctx.getContext('2d')?.clearRect(0, 0, ctx.width, ctx.height);
            return;
        }

        charts['test-run-pass-rate-chart'] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: dates,
                datasets: buildTeamDatasets(perTeam, 'pass_rate')
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'nearest',
                    axis: 'x',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100
                    }
                }
            }
        });
    }

    /**
     * 渲染測試執行狀態圖表
     */
    function renderTestRunStatusChart(data) {
        const ctx = document.getElementById('test-run-status-chart');
        if (!ctx) return;

        destroyChart('test-run-status-chart');

        charts['test-run-status-chart'] = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: Object.keys(data),
                datasets: [{
                    data: Object.values(data),
                    backgroundColor: [
                        'rgba(75, 192, 192, 0.6)',
                        'rgba(255, 99, 132, 0.6)',
                        'rgba(255, 206, 86, 0.6)',
                        'rgba(153, 102, 255, 0.6)',
                        'rgba(54, 162, 235, 0.6)'
                    ]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }

    /**
     * 渲染使用者活動圖表
     */
    function renderUserActivityChart(data) {
        const ctx = document.getElementById('user-activity-chart');
        if (!ctx) return;

        destroyChart('user-activity-chart');

        charts['user-activity-chart'] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: data.map(u => u.username),
                datasets: [{
                    label: '操作次數',
                    data: data.map(u => u.action_count),
                    backgroundColor: 'rgba(255, 159, 64, 0.6)',
                    borderColor: 'rgba(255, 159, 64, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    /**
     * 渲染使用者操作類型圖表
     */
    function renderUserOperationChart(data) {
        const ctx = document.getElementById('user-operation-chart');
        if (!ctx) return;

        destroyChart('user-operation-chart');

        charts['user-operation-chart'] = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: Object.keys(data),
                datasets: [{
                    data: Object.values(data),
                    backgroundColor: [
                        'rgba(54, 162, 235, 0.6)',
                        'rgba(255, 99, 132, 0.6)',
                        'rgba(255, 206, 86, 0.6)',
                        'rgba(75, 192, 192, 0.6)',
                        'rgba(153, 102, 255, 0.6)',
                        'rgba(255, 159, 64, 0.6)'
                    ]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }

    /**
     * 渲染使用者每小時活動圖表
     */
    function renderUserHourlyChart(data) {
        const ctx = document.getElementById('user-hourly-chart');
        if (!ctx) return;

        destroyChart('user-hourly-chart');

        // 補齊 0-23 小時的數據
        const hourlyData = Array.from({length: 24}, (_, i) => data[i] || 0);

        charts['user-hourly-chart'] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: Array.from({length: 24}, (_, i) => `${i}:00`),
                datasets: [{
                    label: '活動次數',
                    data: hourlyData,
                    backgroundColor: 'rgba(153, 102, 255, 0.6)',
                    borderColor: 'rgba(153, 102, 255, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    /**
     * 渲染審計資源類型圖表
     */
    function renderAuditResourceChart(data) {
        const ctx = document.getElementById('audit-resource-chart');
        if (!ctx) return;

        destroyChart('audit-resource-chart');

        charts['audit-resource-chart'] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: Object.keys(data),
                datasets: [{
                    label: '記錄數',
                    data: Object.values(data),
                    backgroundColor: 'rgba(54, 162, 235, 0.6)',
                    borderColor: 'rgba(54, 162, 235, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                scales: {
                    x: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    /**
     * 渲染審計嚴重性圖表
     */
    function renderAuditSeverityChart(data) {
        const ctx = document.getElementById('audit-severity-chart');
        if (!ctx) return;

        destroyChart('audit-severity-chart');

        charts['audit-severity-chart'] = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: Object.keys(data),
                datasets: [{
                    data: Object.values(data),
                    backgroundColor: [
                        'rgba(75, 192, 192, 0.6)',
                        'rgba(255, 206, 86, 0.6)',
                        'rgba(255, 99, 132, 0.6)'
                    ]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }

    /**
     * 渲染審計每日趨勢圖表
     */
    function renderAuditDailyChart(data) {
        const ctx = document.getElementById('audit-daily-chart');
        if (!ctx) return;

        destroyChart('audit-daily-chart');

        charts['audit-daily-chart'] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.map(d => d.date),
                datasets: [{
                    label: '操作數',
                    data: data.map(d => d.count),
                    borderColor: 'rgba(255, 99, 132, 1)',
                    backgroundColor: 'rgba(255, 99, 132, 0.2)',
                    fill: true,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    /**
     * 渲染部門角色分佈圖表
     */
    function renderDepartmentRoleChart(data) {
        const ctx = document.getElementById('department-role-chart');
        if (!ctx) return;

        destroyChart('department-role-chart');

        charts['department-role-chart'] = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: Object.keys(data),
                datasets: [{
                    data: Object.values(data),
                    backgroundColor: [
                        'rgba(255, 99, 132, 0.6)',
                        'rgba(54, 162, 235, 0.6)',
                        'rgba(255, 206, 86, 0.6)',
                        'rgba(75, 192, 192, 0.6)'
                    ]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }

    // ==================== 輔助函數 ====================

    /**
     * 銷毀指定的圖表實例
     */
    function destroyChart(chartId) {
        if (charts[chartId]) {
            charts[chartId].destroy();
            delete charts[chartId];
        }
    }

    function formatNumber(value) {
        const number = Number(value || 0);
        if (!Number.isFinite(number)) return '0';
        return number.toLocaleString('en-US');
    }

    function formatUsd(value) {
        const number = Number(value || 0);
        if (!Number.isFinite(number)) return '$0.0000';
        return `$${number.toFixed(4)}`;
    }

    function formatDurationMs(value) {
        const ms = Number(value || 0);
        if (!Number.isFinite(ms) || ms <= 0) return '0 ms';
        if (ms < 1000) return `${Math.round(ms)} ms`;
        return `${(ms / 1000).toFixed(2)} s`;
    }

    /**
     * 格式化日期時間
     */
    function formatDateTime(isoString) {
        if (!isoString) return '-';
        // 使用 AppUtils.formatDate 以支援自動時區轉換 (UTC -> Local)
        return AppUtils.formatDate(isoString, 'datetime');
    }

    /**
     * 轉義 HTML 字符
     */
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ===========================================================================
    // QA AI Helper Dashboard
    // ===========================================================================

    const HELPER_API_BASE = '/api/admin/team_statistics/qa-ai-helper';

    function buildHelperUrl(endpoint) {
        return `${HELPER_API_BASE}/${endpoint}?${buildStatsQueryParams({ includeTeamFilter: true })}`;
    }

    function pct(value) {
        if (value == null) return '-';
        return `${(Number(value) * 100).toFixed(1)}%`;
    }

    function fmtNum(v) {
        return formatNumber(v);
    }

    // ---------- state ----------
    let helperDataLoaded = false;
    let helperSubTabData = {};

    // ---------- entry point ----------
    async function loadQaAiHelperDashboard() {
        const loading = document.getElementById('qa-ai-helper-loading');
        if (loading) loading.classList.remove('d-none');

        try {
            // Load overview first (always needed for KPI cards)
            const overviewData = await fetchStatsJson(buildHelperUrl('overview'));
            helperSubTabData.overview = overviewData;
            renderHelperOverview(overviewData);

            helperDataLoaded = true;

            // Load active sub-tab data
            const activeSubTab = document.querySelector('#helperSubTab .nav-link.active');
            if (activeSubTab) {
                const target = activeSubTab.getAttribute('data-bs-target');
                await loadHelperSubTabData(target);
            }
        } catch (err) {
            console.error('QA AI Helper dashboard load failed:', err);
        } finally {
            if (loading) loading.classList.add('d-none');
        }
    }

    async function loadHelperSubTabData(targetId) {
        if (!targetId) return;
        const map = {
            '#helper-overview-spane': { key: 'overview', endpoint: 'overview', render: renderHelperOverview },
            '#helper-adoption-spane': { key: 'adoption', endpoint: 'adoption', render: renderHelperAdoption },
            '#helper-generation-spane': { key: 'generation', endpoint: 'generation', render: renderHelperGeneration },
            '#helper-funnel-spane': { key: 'funnel', endpoint: 'funnel', render: renderHelperFunnel },
            '#helper-telemetry-spane': { key: 'telemetry', endpoint: 'telemetry', render: renderHelperTelemetry },
            '#helper-engagement-spane': { key: 'engagement', endpoint: 'user-engagement', render: renderHelperEngagement },
            '#helper-airatio-spane': { key: 'airatio', endpoint: 'ai-ratio', render: renderHelperAiRatio },
        };
        const spec = map[targetId];
        if (!spec) return;

        if (helperSubTabData[spec.key]) {
            spec.render(helperSubTabData[spec.key]);
            return;
        }

        try {
            const data = await fetchStatsJson(buildHelperUrl(spec.endpoint));
            helperSubTabData[spec.key] = data;
            spec.render(data);
        } catch (err) {
            console.error(`Helper sub-tab ${spec.key} load failed:`, err);
        }
    }

    // Hook into sub-tab switch
    document.addEventListener('shown.bs.tab', function(e) {
        if (!e.target || !e.target.closest('#helperSubTab')) return;
        const target = e.target.getAttribute('data-bs-target');
        loadHelperSubTabData(target);
    });

    // ---------- Render: Overview ----------
    function renderHelperOverview(data) {
        if (!data || !data.kpi) return;
        const k = data.kpi;
        setText('helper-kpi-sessions', fmtNum(k.total_sessions));
        setText('helper-kpi-completion-rate', pct(k.completion_rate));
        setText('helper-kpi-tcs-generated', fmtNum(k.total_tcs_generated));
        setText('helper-kpi-tcs-committed', fmtNum(k.total_tcs_committed));
        setText('helper-kpi-seed-adoption', pct(k.overall_seed_adoption_rate));
        setText('helper-kpi-tc-adoption', pct(k.overall_tc_adoption_rate));
        setText('helper-kpi-seeds-generated', fmtNum(k.total_seeds_generated));
        setText('helper-kpi-failed', fmtNum(k.failed_sessions));

        const tbody = document.getElementById('helper-overview-team-tbody');
        if (tbody && data.team_ranking) {
            tbody.innerHTML = data.team_ranking.map((t, i) =>
                `<tr>
                    <td>${i + 1}</td>
                    <td>${escapeHtml(t.team_name)}</td>
                    <td>${fmtNum(t.session_count)}</td>
                    <td>${pct(t.completion_rate)}</td>
                    <td>${pct(t.seed_adoption_rate)}</td>
                    <td>${pct(t.tc_adoption_rate)}</td>
                    <td>${fmtNum(t.committed_tc_count)}</td>
                </tr>`
            ).join('');
        }
    }

    // ---------- Render: Adoption ----------
    function renderHelperAdoption(data) {
        if (!data) return;
        const o = data.overall || {};
        setText('helper-adoption-seed-rate', pct(o.seed_adoption_rate));
        setText('helper-adoption-tc-rate', pct(o.tc_adoption_rate));
        setText('helper-adoption-edit-rate', pct(o.user_edit_rate));
        setText('helper-adoption-ai-ratio', pct(o.ai_generated_ratio));

        // Trend chart
        if (data.overall_trend) {
            renderHelperLineChart('helper-adoption-trend-chart', data.overall_trend.dates, [
                { label: 'Seed 採用率', data: data.overall_trend.seed_adoption, color: teamColorPalette[0] },
                { label: 'TC 採用率', data: data.overall_trend.tc_adoption, color: teamColorPalette[1] },
            ], true);
        }

        // By-team trend
        if (data.by_team_trend && data.by_team_trend.length > 0) {
            const dates = data.by_team_trend[0]?.trend?.dates || [];
            const datasets = data.by_team_trend.map((t, i) => ({
                label: t.team_name,
                data: t.trend?.tc_adoption || [],
                color: teamColorPalette[i % teamColorPalette.length],
            }));
            renderHelperLineChart('helper-adoption-team-trend-chart', dates, datasets, true);
        }

        // Team ranking
        renderHelperTable('helper-adoption-team-tbody', data.team_ranking, (t, i) =>
            `<tr>
                <td>${i + 1}</td>
                <td>${escapeHtml(t.team_name)}</td>
                <td>${pct(t.seed_adoption_rate)}</td>
                <td>${pct(t.tc_adoption_rate)}</td>
            </tr>`
        );

        // User ranking
        renderHelperTable('helper-adoption-user-tbody', data.user_ranking, (u, i) =>
            `<tr>
                <td>${i + 1}</td>
                <td>${escapeHtml(u.username)}</td>
                <td>${escapeHtml(u.team_name || '')}</td>
                <td>${pct(u.seed_adoption_rate)}</td>
                <td>${pct(u.tc_adoption_rate)}</td>
            </tr>`
        );
    }

    // ---------- Render: Generation ----------
    function renderHelperGeneration(data) {
        if (!data) return;
        const s = data.overall_summary || {};
        setText('helper-gen-total-seeds', fmtNum(s.total_seeds));
        setText('helper-gen-total-tcs', fmtNum(s.total_tcs));
        setText('helper-gen-total-committed', fmtNum(s.total_committed));
        setText('helper-gen-avg-per-session', s.avg_tcs_per_session != null ? Number(s.avg_tcs_per_session).toFixed(1) : '-');

        // Trend chart
        if (data.overall_trend) {
            const t = data.overall_trend;
            renderHelperBarChart('helper-generation-trend-chart', t.dates, [
                { label: 'Seeds', data: t.seeds_generated, color: teamColorPalette[0] },
                { label: 'TCs', data: t.tcs_generated, color: teamColorPalette[1] },
                { label: '入庫', data: t.tcs_committed, color: teamColorPalette[2] },
            ]);
        }

        // By-team trend
        if (data.by_team_trend && data.by_team_trend.length > 0) {
            const dates = data.by_team_trend[0]?.trend?.dates || [];
            const datasets = data.by_team_trend.map((t, i) => ({
                label: t.team_name,
                data: t.trend?.tcs || [],
                color: teamColorPalette[i % teamColorPalette.length],
            }));
            renderHelperBarChart('helper-generation-team-trend-chart', dates, datasets);
        }

        // Team ranking
        renderHelperTable('helper-generation-team-tbody', data.team_ranking, (t, i) =>
            `<tr>
                <td>${i + 1}</td>
                <td>${escapeHtml(t.team_name)}</td>
                <td>${fmtNum(t.seeds_generated)}</td>
                <td>${fmtNum(t.tcs_generated)}</td>
                <td>${fmtNum(t.tcs_committed)}</td>
            </tr>`
        );

        // User ranking
        renderHelperTable('helper-generation-user-tbody', data.user_ranking, (u, i) =>
            `<tr>
                <td>${i + 1}</td>
                <td>${escapeHtml(u.username)}</td>
                <td>${escapeHtml(u.team_name || '')}</td>
                <td>${fmtNum(u.seeds_generated)}</td>
                <td>${fmtNum(u.tcs_generated)}</td>
                <td>${fmtNum(u.tcs_committed)}</td>
            </tr>`
        );
    }

    // ---------- Render: Funnel ----------
    function renderHelperFunnel(data) {
        if (!data) return;
        setText('helper-funnel-avg-time', data.avg_completion_time_hours != null ? `${Number(data.avg_completion_time_hours).toFixed(1)} hr` : '-');

        // Funnel chart (horizontal bar)
        if (data.funnel) {
            const stages = Object.keys(data.funnel);
            const values = Object.values(data.funnel);
            destroyChart('helper-funnel-chart');
            const ctx = document.getElementById('helper-funnel-chart');
            if (ctx) {
                charts['helper-funnel-chart'] = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: stages,
                        datasets: [{
                            label: 'Sessions',
                            data: values,
                            backgroundColor: stages.map((_, i) => toRgba(teamColorPalette[i % teamColorPalette.length], 0.7)),
                            borderColor: stages.map((_, i) => teamColorPalette[i % teamColorPalette.length]),
                            borderWidth: 1,
                        }]
                    },
                    options: {
                        indexAxis: 'y',
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: { x: { beginAtZero: true } },
                        plugins: { legend: { display: false } },
                    }
                });
            }
        }

        // Status distribution pie
        if (data.status_distribution) {
            destroyChart('helper-funnel-status-chart');
            const ctx2 = document.getElementById('helper-funnel-status-chart');
            if (ctx2) {
                const labels = Object.keys(data.status_distribution);
                const vals = Object.values(data.status_distribution);
                charts['helper-funnel-status-chart'] = new Chart(ctx2, {
                    type: 'doughnut',
                    data: {
                        labels: labels,
                        datasets: [{
                            data: vals,
                            backgroundColor: labels.map((_, i) => toRgba(teamColorPalette[i % teamColorPalette.length], 0.7)),
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                    }
                });
            }
        }

        // Team funnel comparison
        renderHelperTable('helper-funnel-team-tbody', data.by_team, (t) =>
            `<tr>
                <td>${escapeHtml(t.team_name)}</td>
                <td>${fmtNum(t.total)}</td>
                <td>${fmtNum(t.completed)}</td>
                <td>${fmtNum(t.failed)}</td>
                <td>${pct(t.completion_rate)}</td>
            </tr>`
        );
    }

    // ---------- Render: Telemetry ----------
    function renderHelperTelemetry(data) {
        if (!data) return;
        const o = data.overall || {};
        setText('helper-tel-total-calls', fmtNum(o.total_calls));
        setText('helper-tel-prompt-tokens', fmtNum(o.total_prompt_tokens));
        setText('helper-tel-completion-tokens', fmtNum(o.total_completion_tokens));
        setText('helper-tel-total-tokens', fmtNum(o.total_tokens));
        setText('helper-tel-avg-duration', formatDurationMs(o.avg_duration_ms));
        setText('helper-tel-error-rate', pct(o.error_rate));

        // Token trend
        if (data.token_trend) {
            const t = data.token_trend;
            renderHelperLineChart('helper-telemetry-trend-chart', t.dates, [
                { label: 'Prompt Tokens', data: t.prompt_tokens, color: teamColorPalette[0] },
                { label: 'Completion Tokens', data: t.completion_tokens, color: teamColorPalette[1] },
            ]);
        }

        // By-team trend
        if (data.by_team_trend && data.by_team_trend.length > 0) {
            const dates = data.by_team_trend[0]?.trend?.dates || [];
            const datasets = data.by_team_trend.map((t, i) => ({
                label: t.team_name,
                data: t.trend?.tokens || [],
                color: teamColorPalette[i % teamColorPalette.length],
            }));
            renderHelperLineChart('helper-telemetry-team-trend-chart', dates, datasets);
        }

        // Team ranking
        renderHelperTable('helper-telemetry-team-tbody', data.team_ranking, (t, i) =>
            `<tr>
                <td>${i + 1}</td>
                <td>${escapeHtml(t.team_name)}</td>
                <td>${fmtNum(t.total_calls)}</td>
                <td>${fmtNum(t.prompt_tokens)}</td>
                <td>${fmtNum(t.completion_tokens)}</td>
                <td>${fmtNum(t.total_tokens)}</td>
                <td>${formatDurationMs(t.avg_duration_ms)}</td>
            </tr>`
        );

        // By stage (by_stage is a Dict keyed by stage name, convert to array)
        if (data.by_stage && typeof data.by_stage === 'object' && !Array.isArray(data.by_stage)) {
            const stageList = Object.entries(data.by_stage).map(([stage, info]) => ({ stage, ...info }));
            renderHelperTable('helper-telemetry-stage-tbody', stageList, (s) =>
                `<tr>
                    <td>${escapeHtml(s.stage)}</td>
                    <td>${fmtNum(s.calls)}</td>
                    <td>${fmtNum(s.prompt_tokens)}</td>
                    <td>${fmtNum(s.completion_tokens)}</td>
                    <td>${fmtNum(s.tokens)}</td>
                    <td>${formatDurationMs(s.avg_ms)}</td>
                </tr>`
            );
        }
    }

    // ---------- Render: Engagement ----------
    function renderHelperEngagement(data) {
        if (!data) return;

        // DAU trend chart
        if (data.dau_trend) {
            const dt = data.dau_trend;
            const datasets = [{ label: 'DAU', data: dt.overall || [], color: teamColorPalette[0] }];
            if (dt.by_team && dt.by_team.length > 0) {
                dt.by_team.forEach((t, i) => {
                    datasets.push({
                        label: t.team_name,
                        data: t.daily || [],
                        color: teamColorPalette[(i + 1) % teamColorPalette.length],
                    });
                });
            }
            renderHelperLineChart('helper-engagement-dau-chart', dt.dates || [], datasets);
        }

        // Team ranking
        renderHelperTable('helper-engagement-team-tbody', data.team_ranking, (t, i) =>
            `<tr>
                <td>${i + 1}</td>
                <td>${escapeHtml(t.team_name)}</td>
                <td>${fmtNum(t.active_user_count)}</td>
                <td>${fmtNum(t.session_count)}</td>
                <td>${t.session_count && t.active_user_count ? (t.session_count / t.active_user_count).toFixed(1) : '-'}</td>
            </tr>`
        );

        // User ranking
        renderHelperTable('helper-engagement-user-tbody', data.user_ranking, (u, i) =>
            `<tr>
                <td>${i + 1}</td>
                <td>${escapeHtml(u.username)}</td>
                <td>${escapeHtml(u.team_name || '')}</td>
                <td>${fmtNum(u.session_count)}</td>
                <td>${fmtNum(u.committed_tc_count)}</td>
            </tr>`
        );
    }

    // ---------- Render: AI vs Manual Ratio ----------
    function renderHelperAiRatio(data) {
        if (!data) return;

        // KPI cards
        var o = data.overall || {};
        setText('helper-airatio-total', fmtNum(o.total_created));
        setText('helper-airatio-ai', fmtNum(o.ai_committed));
        setText('helper-airatio-manual', fmtNum(o.manual_created));
        setText('helper-airatio-percent', pct(o.ai_ratio));

        // Overall trend — stacked bar chart (AI + Manual)
        if (data.overall_trend) {
            var t = data.overall_trend;
            destroyChart('helper-airatio-overall-chart');
            var ctx = document.getElementById('helper-airatio-overall-chart');
            if (ctx) {
                charts['helper-airatio-overall-chart'] = new Chart(ctx, {
                    type: 'bar',
                    data: {
                        labels: t.dates || [],
                        datasets: [
                            {
                                label: 'AI Committed',
                                data: t.ai_committed || [],
                                backgroundColor: toRgba(teamColorPalette[0], 0.7),
                                borderColor: teamColorPalette[0],
                                borderWidth: 1,
                            },
                            {
                                label: 'Manual',
                                data: t.manual_created || [],
                                backgroundColor: toRgba(teamColorPalette[3], 0.7),
                                borderColor: teamColorPalette[3],
                                borderWidth: 1,
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {
                            x: { stacked: true },
                            y: { stacked: true, beginAtZero: true }
                        },
                        plugins: { legend: { position: 'top' } }
                    }
                });
            }
        }

        // Top 10 team AI ratio trend line chart
        if (data.by_team_trend && data.by_team_trend.length > 0) {
            var dates = data.by_team_trend[0].trend ? data.by_team_trend[0].trend.dates : [];
            var datasets = data.by_team_trend.map(function(t, i) {
                return {
                    label: t.team_name,
                    data: t.trend ? t.trend.ai_ratio : [],
                    color: teamColorPalette[i % teamColorPalette.length],
                };
            });
            renderHelperLineChart('helper-airatio-team-chart', dates, datasets, true);
        }

        // Team ranking table
        renderHelperTable('helper-airatio-team-tbody', data.team_ranking, function(t, i) {
            return '<tr>' +
                '<td>' + (i + 1) + '</td>' +
                '<td>' + escapeHtml(t.team_name) + '</td>' +
                '<td>' + fmtNum(t.total_created) + '</td>' +
                '<td>' + fmtNum(t.ai_committed) + '</td>' +
                '<td>' + fmtNum(t.manual_created) + '</td>' +
                '<td>' + pct(t.ai_ratio) + '</td>' +
            '</tr>';
        });
    }

    // ---------- Chart Helpers ----------
    function renderHelperLineChart(canvasId, labels, datasets, isPercentage) {
        destroyChart(canvasId);
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        charts[canvasId] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: datasets.map(ds => ({
                    label: ds.label,
                    data: ds.data,
                    borderColor: ds.color,
                    backgroundColor: toRgba(ds.color, 0.1),
                    fill: false,
                    tension: 0.3,
                    pointRadius: 2,
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                scales: {
                    y: {
                        beginAtZero: true,
                        ...(isPercentage ? {
                            max: 1,
                            ticks: { callback: v => `${(v * 100).toFixed(0)}%` }
                        } : {})
                    }
                },
                plugins: { legend: { position: 'top' } }
            }
        });
    }

    function renderHelperBarChart(canvasId, labels, datasets) {
        destroyChart(canvasId);
        const ctx = document.getElementById(canvasId);
        if (!ctx) return;

        charts[canvasId] = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: datasets.map(ds => ({
                    label: ds.label,
                    data: ds.data,
                    backgroundColor: toRgba(ds.color, 0.6),
                    borderColor: ds.color,
                    borderWidth: 1,
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { beginAtZero: true } },
                plugins: { legend: { position: 'top' } }
            }
        });
    }

    function renderHelperTable(tbodyId, list, rowFn) {
        const tbody = document.getElementById(tbodyId);
        if (!tbody) return;
        if (!Array.isArray(list) || list.length === 0) {
            tbody.innerHTML = '<tr><td colspan="99" class="text-center text-muted">-</td></tr>';
            return;
        }
        tbody.innerHTML = list.map(rowFn).join('');
    }

    function setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

})();
