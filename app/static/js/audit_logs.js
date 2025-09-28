class AuditLogsPage {
    constructor() {
        this.authClient = null;
        this.currentUser = null;
        this.formatter = new DateTimeFormatter();
        this.currentPage = 0;
        this.pageSize = 100;
        this.totalPages = 1;
        this.totalItems = 0;
        this.loadedItems = 0;
        this.activeFilters = {};
        this.teamMap = new Map();
        this.elements = {};
        this.isLoading = false;
        this.hasMore = true;
        this.observer = null;
    }

    async init() {
        await this.waitForAuthClient();
        this.authClient = window.AuthClient;

        this.cacheElements();
        this.setupInfiniteScroll();
        this.updateTimezoneLabel();

        const userInfo = await this.authClient.getUserInfo();
        if (!userInfo || !this.isRoleAllowed(userInfo.role)) {
            this.handleUnauthorized();
            return;
        }
        this.currentUser = userInfo;

        this.bindEvents();

        await this.loadTeams();
        await this.fetchLogs({ reset: true });
    }

    async waitForAuthClient() {
        const maxRetries = 50;
        let attempt = 0;
        while (!window.AuthClient && attempt < maxRetries) {
            await new Promise((resolve) => setTimeout(resolve, 100));
            attempt += 1;
        }
        if (!window.AuthClient) {
            throw new Error('AuthClient not available');
        }
    }

    cacheElements() {
        this.elements = {
            username: document.getElementById('filterUsername'),
            startTime: document.getElementById('filterStartTime'),
            endTime: document.getElementById('filterEndTime'),
            role: document.getElementById('filterRole'),
            resourceType: document.getElementById('filterResourceType'),
            team: document.getElementById('filterTeam'),
            applyFilters: document.getElementById('applyFiltersBtn'),
            resetFilters: document.getElementById('resetFiltersBtn'),
            exportCsv: document.getElementById('exportCsvBtn'),
            refresh: document.getElementById('auditRefreshBtn'),
            tableBody: document.getElementById('auditTableBody'),
            emptyState: document.getElementById('auditEmptyState'),
            loadingState: document.getElementById('auditLoadingState'),
            tableWrapper: document.getElementById('auditTableWrapper'),
            totalBadge: document.getElementById('auditTotalBadge'),
            summary: document.getElementById('auditSummary'),
            timezoneLabel: document.getElementById('auditTimezoneLabel'),
            scrollHint: document.getElementById('auditScrollHint'),
            loadMoreIndicator: document.getElementById('auditLoadMoreIndicator'),
            loadMoreSentinel: document.getElementById('auditLoadMoreSentinel'),
            allLoaded: document.getElementById('auditAllLoaded'),
        };
    }

    updateTimezoneLabel() {
        if (!this.elements.timezoneLabel) return;
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
        const prefix = window.i18n ? window.i18n.t('audit.currentTimezone', { tz }) : `當前時區：${tz}`;
        this.elements.timezoneLabel.textContent = prefix;
    }

    isRoleAllowed(role) {
        if (!role) return false;
        const normalized = String(role).toLowerCase();
        return normalized === 'admin' || normalized === 'super_admin';
    }

    handleUnauthorized() {
        const message = window.i18n ? window.i18n.t('audit.unauthorized') : '沒有存取審計記錄的權限';
        if (window.AppUtils && typeof window.AppUtils.showError === 'function') {
            window.AppUtils.showError(message);
        } else {
            alert(message);
        }
        setTimeout(() => {
            window.location.href = '/';
        }, 1500);
    }

    bindEvents() {
        this.elements.applyFilters?.addEventListener('click', () => {
            this.fetchLogs({ reset: true });
        });

        this.elements.resetFilters?.addEventListener('click', () => {
            this.resetFilters();
            this.fetchLogs({ reset: true });
        });

        this.elements.refresh?.addEventListener('click', () => {
            this.fetchLogs({ reset: true });
        });

        this.elements.exportCsv?.addEventListener('click', () => {
            this.exportCsv();
        });
    }

    setupInfiniteScroll() {
        const sentinel = this.elements.loadMoreSentinel;
        const container = this.elements.tableWrapper;
        if (!sentinel || !container) {
            return;
        }
        if (this.observer) {
            this.observer.disconnect();
        }
        this.observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting && this.hasMore && !this.isLoading) {
                    this.fetchLogs();
                }
            });
        }, {
            root: container,
            rootMargin: '0px 0px 200px 0px',
            threshold: 0,
        });
        this.observer.observe(sentinel);
    }

    resetFilters() {
        if (this.elements.username) this.elements.username.value = '';
        if (this.elements.startTime) this.elements.startTime.value = '';
        if (this.elements.endTime) this.elements.endTime.value = '';
        if (this.elements.role) this.elements.role.value = '';
        if (this.elements.resourceType) this.elements.resourceType.value = '';
        if (this.elements.team) this.elements.team.value = '';
    }

    readFilters() {
        return {
            username: this.elements.username?.value.trim() || '',
            role: this.elements.role?.value || '',
            resource_type: this.elements.resourceType?.value || '',
            team_id: this.elements.team?.value || '',
            start_time: this.elements.startTime?.value || '',
            end_time: this.elements.endTime?.value || '',
        };
    }

    convertToUtcIso(localValue) {
        if (!localValue) return '';
        const localDate = new Date(localValue);
        if (Number.isNaN(localDate.getTime())) {
            return '';
        }
        const utcDate = new Date(localDate.getTime() - localDate.getTimezoneOffset() * 60000);
        return utcDate.toISOString();
    }

    buildQueryParams({ page }) {
        const params = new URLSearchParams();
        params.set('page', String(page));
        params.set('page_size', String(this.pageSize));

        const filters = this.activeFilters;

        if (filters.username) params.set('username', filters.username);
        if (filters.role) params.set('role', filters.role);
        if (filters.resource_type) params.set('resource_type', filters.resource_type);
        if (filters.team_id) params.set('team_id', filters.team_id);

        if (filters.start_time) params.set('start_time', this.convertToUtcIso(filters.start_time));
        if (filters.end_time) params.set('end_time', this.convertToUtcIso(filters.end_time));

        return params;
    }

    async loadTeams() {
        try {
            const response = await this.authClient.fetch('/api/teams/');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const teams = await response.json();
            this.teamMap.clear();
            teams.forEach((team) => {
                this.teamMap.set(String(team.id), team.name);
            });
            this.populateTeamFilter();
        } catch (error) {
            console.warn('載入團隊列表失敗', error);
            if (window.AppUtils && typeof window.AppUtils.showWarning === 'function') {
                window.AppUtils.showWarning(window.i18n ? window.i18n.t('audit.filters.teamLoadFailed') : '載入團隊列表失敗');
            }
        }
    }

    populateTeamFilter() {
        const select = this.elements.team;
        if (!select) return;
        const currentValue = select.value;
        select.innerHTML = '';
        const optionAll = document.createElement('option');
        optionAll.value = '';
        optionAll.textContent = window.i18n ? window.i18n.t('audit.filters.teamAll') : '全部團隊';
        select.appendChild(optionAll);

        this.teamMap.forEach((name, id) => {
            const option = document.createElement('option');
            option.value = id;
            option.textContent = `${name} (#${id})`;
            select.appendChild(option);
        });

        if (currentValue && this.teamMap.has(currentValue)) {
            select.value = currentValue;
        }
    }

    async fetchLogs({ reset = false } = {}) {
        if (this.isLoading) {
            return;
        }

        if (reset) {
            this.currentPage = 0;
            this.totalPages = 1;
            this.totalItems = 0;
            this.loadedItems = 0;
            this.hasMore = true;
            this.activeFilters = this.readFilters();
            this.clearTable();
            this.hideAllLoadedIndicator();
            this.updateScrollHint();
            if (this.observer && this.elements.loadMoreSentinel) {
                this.observer.observe(this.elements.loadMoreSentinel);
            }
        }

        if (!this.hasMore) {
            return;
        }

        const nextPage = this.currentPage + 1;
        const isInitialLoad = this.loadedItems === 0;
        this.isLoading = true;
        this.showLoading({ initial: isInitialLoad });

        try {
            const params = this.buildQueryParams({ page: nextPage });
            const response = await this.authClient.fetch(`/api/audit/logs?${params.toString()}`);
            if (!response.ok) {
                if (response.status === 403) {
                    this.handleUnauthorized();
                    return;
                }
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            const items = Array.isArray(data.items) ? data.items : [];
            const append = nextPage > 1;

            this.renderTable(items, { append });

            this.currentPage = data.page || nextPage;
            this.totalPages = data.total_pages || 1;
            this.totalItems = data.total ?? this.totalItems;
            this.loadedItems += items.length;
            this.hasMore = this.currentPage < this.totalPages;

            if (!this.hasMore) {
                this.showAllLoadedIndicator();
            }

            this.updateSummary();
            this.updateScrollHint();
        } catch (error) {
            console.error('Fetch audit logs failed', error);
            const message = window.i18n ? window.i18n.t('audit.loadFailed') : `載入審計記錄失敗：${error.message}`;
            if (window.AppUtils && typeof window.AppUtils.showError === 'function') {
                window.AppUtils.showError(message);
            } else {
                alert(message);
            }
        } finally {
            this.hideLoading();
            this.isLoading = false;
        }
    }

    clearTable() {
        const tbody = this.elements.tableBody;
        const emptyState = this.elements.emptyState;
        if (tbody) {
            tbody.innerHTML = '';
        }
        if (emptyState) {
            emptyState.style.display = 'none';
        }
    }

    renderTable(items, { append = false } = {}) {
        const tbody = this.elements.tableBody;
        const emptyState = this.elements.emptyState;
        if (!tbody || !emptyState) return;

        if (!append) {
            tbody.innerHTML = '';
        }

        if (!items.length && !append && this.totalItems === 0) {
            emptyState.style.display = 'block';
            return;
        }

        emptyState.style.display = 'none';

        const fragment = document.createDocumentFragment();
        items.forEach((item) => {
            const row = document.createElement('tr');
            const timestampLocal = this.formatDate(item.timestamp);
            const roleLabel = this.translateRole(item.role);
            const actionLabel = this.translateAction(item.action_type);
            const resourceLabel = this.translateResource(item.resource_type);
            const severity = this.translateSeverity(item.severity);
            const severityClass = this.getSeverityClass(item.severity);
            const teamLabel = this.formatTeam(item.team_name, item.team_id);
            const actionBriefHtml = this.formatActionBrief(item);

            row.innerHTML = `
                <td><div class="d-flex flex-column"><span>${timestampLocal}</span><small class="text-muted">${this.formatDate(item.timestamp, 'datetime-tz')}</small></div></td>
                <td>${actionBriefHtml}</td>
                <td>${this.escapeHtml(item.username || '')}</td>
                <td>${roleLabel}</td>
                <td>${teamLabel}</td>
                <td>${actionLabel}</td>
                <td>${resourceLabel}</td>
                <td><span class="badge ${severityClass}">${severity}</span></td>
                <td>${this.escapeHtml(item.ip_address || '-')}</td>
            `;
            fragment.appendChild(row);
        });

        tbody.appendChild(fragment);
    }

    updateSummary() {
        if (this.elements.totalBadge) {
            this.elements.totalBadge.textContent = String(this.totalItems);
        }
        if (this.elements.summary) {
            const loaded = Math.min(this.loadedItems, this.totalItems || this.loadedItems);
            const text = window.i18n ? window.i18n.t('audit.summary', { total: this.totalItems, loaded }) : `共 ${this.totalItems} 筆資料，已載入 ${loaded} 筆`;
            this.elements.summary.textContent = text;
        }
    }

    updateScrollHint() {
        if (!this.elements.scrollHint) return;
        if (this.hasMore) {
            this.elements.scrollHint.classList.remove('d-none');
        } else {
            this.elements.scrollHint.classList.add('d-none');
        }
    }

    showLoading({ initial = false } = {}) {
        if (initial) {
            if (this.elements.loadingState) this.elements.loadingState.style.display = 'block';
            if (this.elements.tableWrapper) this.elements.tableWrapper.style.opacity = '0.4';
        } else if (this.elements.loadMoreIndicator) {
            this.elements.loadMoreIndicator.style.display = 'block';
        }
    }

    hideLoading() {
        if (this.elements.loadingState) this.elements.loadingState.style.display = 'none';
        if (this.elements.tableWrapper) this.elements.tableWrapper.style.opacity = '1';
        if (this.elements.loadMoreIndicator) this.elements.loadMoreIndicator.style.display = 'none';
    }

    showAllLoadedIndicator() {
        if (this.elements.allLoaded) {
            this.elements.allLoaded.style.display = this.totalItems > 0 ? 'block' : 'none';
        }
        if (this.observer && this.elements.loadMoreSentinel) {
            this.observer.unobserve(this.elements.loadMoreSentinel);
        }
    }

    hideAllLoadedIndicator() {
        if (this.elements.allLoaded) {
            this.elements.allLoaded.style.display = 'none';
        }
    }

    translateRole(role) {
        if (!role) return '-';
        const key = `roles.${String(role).toLowerCase()}`;
        return window.i18n ? window.i18n.t(key) : role;
    }

    translateAction(action) {
        if (!action) return '-';
        const key = `audit.action.${String(action).toUpperCase()}`;
        return window.i18n ? window.i18n.t(key) : action;
    }

    translateResource(resource) {
        if (!resource) return '-';
        const key = `audit.resource.${String(resource).toLowerCase()}`;
        return window.i18n ? window.i18n.t(key) : resource;
    }

    translateSeverity(severity) {
        if (!severity) return '-';
        const key = `audit.severity.${String(severity).toLowerCase()}`;
        return window.i18n ? window.i18n.t(key) : severity;
    }

    getSeverityClass(severity) {
        const value = String(severity || '').toLowerCase();
        if (value === 'critical') return 'bg-danger';
        if (value === 'warning') return 'bg-warning text-dark';
        return 'bg-secondary';
    }

    formatActionBrief(item) {
        if (item && item.action_brief) {
            return this.escapeHtml(item.action_brief);
        }
        const username = item?.username ? this.escapeHtml(item.username) : '';
        const actionLabelRaw = this.translateAction(item?.action_type) || '';
        const resourceLabelRaw = this.translateResource(item?.resource_type) || '';
        const actionLabel = actionLabelRaw ? this.escapeHtml(actionLabelRaw) : '';
        const resourceLabel = resourceLabelRaw ? this.escapeHtml(resourceLabelRaw) : '';
        const resourceId = item?.resource_id ? `(${this.escapeHtml(String(item.resource_id))})` : '';
        const segments = [username, actionLabel, resourceLabel].filter(Boolean);
        const text = `${segments.join(' ')} ${resourceId}`.trim();
        return text ? text : '-';
    }

    formatTeam(teamName, teamId) {
        const resolvedName = teamName || this.teamMap.get(String(teamId)) || '-';
        const safeName = this.escapeHtml(resolvedName);
        if (!teamId) return safeName;
        return `${safeName} (#${teamId})`;
    }

    formatDate(value, style = 'datetime') {
        if (!value) return '';
        try {
            return this.formatter.format(value, style);
        } catch (error) {
            console.warn('format date failed', error);
            return value;
        }
    }

    escapeHtml(text) {
        const value = String(text ?? '');
        return value.replace(/[&<>'"]/g, (char) => {
            const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' };
            return map[char];
        });
    }

    async exportCsv() {
        try {
            const filters = this.readFilters();
            const params = new URLSearchParams();
            if (filters.username) params.set('username', filters.username);
            if (filters.role) params.set('role', filters.role);
            if (filters.resource_type) params.set('resource_type', filters.resource_type);
            if (filters.team_id) params.set('team_id', filters.team_id);
            if (filters.start_time) params.set('start_time', this.convertToUtcIso(filters.start_time));
            if (filters.end_time) params.set('end_time', this.convertToUtcIso(filters.end_time));
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
            params.set('timezone', tz);

            const response = await this.authClient.fetch(`/api/audit/logs/export?${params.toString()}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const blob = await response.blob();
            const disposition = response.headers.get('Content-Disposition') || '';
            const fileName = this.extractFilename(disposition) || `audit_logs_${Date.now()}.csv`;
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = fileName;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.URL.revokeObjectURL(url);

            if (window.AppUtils && typeof window.AppUtils.showSuccess === 'function') {
                window.AppUtils.showSuccess(window.i18n ? window.i18n.t('audit.exportSuccess') : 'CSV 匯出成功');
            }
        } catch (error) {
            console.error('Export CSV failed', error);
            const msg = window.i18n ? window.i18n.t('audit.exportFailed') : `匯出失敗：${error.message}`;
            if (window.AppUtils && typeof window.AppUtils.showError === 'function') {
                window.AppUtils.showError(msg);
            } else {
                alert(msg);
            }
        }
    }

    extractFilename(disposition) {
        const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disposition);
        if (!match) return '';
        if (match[1]) {
            try {
                return decodeURIComponent(match[1]);
            } catch (_) {
                return match[1];
            }
        }
        return match[2] || '';
    }
}

(function initAuditLogsPage() {
    document.addEventListener('DOMContentLoaded', () => {
        const page = new AuditLogsPage();
        page.init().catch((error) => console.error('初始化審計頁面失敗', error));
    });
})();
