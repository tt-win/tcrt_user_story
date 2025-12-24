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

    bootstrapFallbackChart();

    // 初始化頁面
    document.addEventListener('DOMContentLoaded', async function() {
        try {
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

            initEventListeners();
            await loadAllStatistics();
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

    function buildStatsQueryParams() {
        if (customStartDate && customEndDate) {
            return `start_date=${encodeURIComponent(customStartDate)}&end_date=${encodeURIComponent(customEndDate)}`;
        }
        return `days=${currentDays}`;
    }

    function buildStatsUrl(endpoint) {
        return `/api/admin/team_statistics/${endpoint}?${buildStatsQueryParams()}`;
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
        const startInput = document.getElementById('custom-range-start');
        const endInput = document.getElementById('custom-range-end');
        const startValue = startInput ? startInput.value : '';
        const endValue = endInput ? endInput.value : '';

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
            customApplyBtn.addEventListener('click', function() {
                applyCustomRange();
            });
        }

        // 刷新按鈕
        document.getElementById('refresh-stats-btn').addEventListener('click', async function() {
            await loadAllStatistics();
        });

        // 標籤頁切換事件（延遲載入策略）
        document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tab => {
            tab.addEventListener('shown.bs.tab', function(event) {
                const targetId = event.target.getAttribute('data-bs-target');
                handleTabSwitch(targetId);
            });
        });
    }

    /**
     * 處理標籤頁切換（首次載入時才獲取數據）
     */
    function handleTabSwitch(targetId) {
        // 標籤頁首次顯示時，已載入的數據會自動顯示圖表
        // 由於我們使用統一載入策略，這裡不需要額外處理
    }

    /**
     * 載入所有統計數據
     */
    async function loadAllStatistics() {
        AppUtils.showLoading('載入統計數據中...');

        try {
            await Promise.all([
                loadOverview(),
                loadTeamActivity(),
                loadTestCaseTrends(),
                loadTestRunMetrics(),
                loadUserActivity(),
                loadAuditAnalysis()
                // loadDepartmentStats()  // 已註解 - Department Stats 功能暫時停用
            ]);

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

            // 更新關鍵指標卡片
            document.getElementById('overview-team-count').textContent = data.team_count || 0;
            document.getElementById('overview-user-count').textContent = data.user_count || 0;
            document.getElementById('overview-test-case-total').textContent = data.test_case_total || 0;
            document.getElementById('overview-test-run-total').textContent = data.test_run_total || 0;

            // 更新團隊 Test Case 統計表格
            const teamTestCasesTbody = document.getElementById('team-test-cases-tbody');
            if (data.team_test_cases && data.team_test_cases.length > 0) {
                teamTestCasesTbody.innerHTML = data.team_test_cases.map(team => `
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
            if (data.team_test_runs && data.team_test_runs.length > 0) {
                teamTestRunsTbody.innerHTML = data.team_test_runs.map(team => `
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

            // 渲染最活躍團隊圖表
            if (data.top_active_teams && data.top_active_teams.length > 0) {
                renderTeamActivityChart(data.top_active_teams);
            }

            // 更新活動詳情表格
            const tbody = document.getElementById('team-activity-tbody');
            const tableData = data.all_teams_activity || data.top_active_teams;
            
            if (tableData && tableData.length > 0) {
                tbody.innerHTML = tableData.map(team => `
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

            const hasTeamDaily = Array.isArray(data?.per_team_daily) && data.per_team_daily.length > 0;

            if (hasTeamDaily) {
                const dates = Array.isArray(data.dates) ? data.dates : [];
                renderTestCaseCreatedChart(dates, data.per_team_daily);
                renderTestCaseUpdatedChart(dates, data.per_team_daily);
                renderTestCaseTeamDailyTable(data.per_team_daily);
                renderTestCaseTeamSummaryTable(data.per_team_daily, data.overall);
            } else {
                renderTestCaseCreatedChart([], []);
                renderTestCaseUpdatedChart([], []);
                renderTestCaseTeamDailyTable([]);
                renderTestCaseTeamSummaryTable([], data.overall);
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
            const perTeamDaily = data.per_team_daily || [];
            const perTeamPassRate = data.per_team_pass_rate || [];

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
            if (data.by_team && data.by_team.length > 0) {
                tbody.innerHTML = data.by_team.map(team => `
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

})();
