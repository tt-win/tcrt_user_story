/**
 * Super Admin 系統 log viewer 頁面邏輯。
 * 純函式核心（SSE parser / highlight segmenter / backoff / model）在 system-logs-core.js。
 * 安全契約：log 內容與 keyword 一律以 textContent / createTextNode 落地，禁止 innerHTML。
 */
(function () {
    'use strict';

    const Core = window.SystemLogsCore;
    const MAX_RECORDS = 5000;
    const MAX_PENDING_NOTICES = 100;
    const STREAM_URL = '/api/admin/system-logs/stream';
    const RUNTIME_SETTINGS_URL = '/api/admin/system-runtime-settings';

    class SystemLogsPage {
        constructor() {
            this.authClient = null;
            this.model = Core.createLogModel(MAX_RECORDS);
            this.pendingNotices = Core.createBoundedQueue(MAX_PENDING_NOTICES);
            this.elements = {};
            this.paused = false;
            this.followTail = true;
            this.filters = { level: '', logger: '', keyword: '', hideAccess: false };
            this.reconnectAttempt = 0;
            this.stopped = false;
            this.abortController = null;
        }

        async init() {
            this.cacheElements();
            await this.waitForAuthClient();
            this.authClient = window.AuthClient;
            if (!this.authClient || !this.authClient.isAuthenticated()) {
                if (this.authClient) this.authClient.redirectToLogin();
                return;
            }
            const userInfo = await this.authClient.getUserInfo();
            if (!userInfo || userInfo.role !== 'super_admin') {
                this.showUnauthorized();
                return;
            }
            this.bindEvents();
            this.settingsPanel = new RuntimeSettingsPanel(this);
            this.settingsPanel.init();
            this.connect();
        }

        async waitForAuthClient() {
            let attempt = 0;
            while (!window.AuthClient && attempt < 50) {
                await new Promise((resolve) => setTimeout(resolve, 100));
                attempt += 1;
            }
        }

        cacheElements() {
            const byId = (id) => document.getElementById(id);
            this.elements = {
                output: byId('logOutput'),
                status: byId('logStreamStatus'),
                instance: byId('logWorkerInstance'),
                pauseBtn: byId('logPauseBtn'),
                clearBtn: byId('logClearBtn'),
                downloadBtn: byId('logDownloadBtn'),
                levelSelect: byId('logLevelFilter'),
                loggerInput: byId('logLoggerFilter'),
                keywordInput: byId('logKeywordFilter'),
                hideAccess: byId('logHideAccess'),
                unauthorized: byId('logUnauthorized'),
                main: byId('logViewerMain'),
            };
        }

        bindEvents() {
            this.elements.pauseBtn.addEventListener('click', () => this.togglePause());
            this.elements.clearBtn.addEventListener('click', () => {
                this.model.clear();
                this.pendingNotices.clear();
                this.renderAll();
            });
            this.elements.downloadBtn.addEventListener('click', () => this.download());
            this.elements.levelSelect.addEventListener('change', () => {
                this.filters.level = this.elements.levelSelect.value;
                this.renderAll();
            });
            this.elements.loggerInput.addEventListener('input', () => {
                this.filters.logger = this.elements.loggerInput.value.trim();
                this.renderAll();
            });
            this.elements.keywordInput.addEventListener('input', () => {
                this.filters.keyword = this.elements.keywordInput.value;
                this.renderAll();
            });
            this.elements.hideAccess.addEventListener('change', () => {
                this.filters.hideAccess = this.elements.hideAccess.checked;
                this.renderAll();
            });
            // 手動上捲暫停跟隨；回到底部恢復
            this.elements.output.addEventListener('scroll', () => {
                const el = this.elements.output;
                this.followTail = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
            });
        }

        // ---- 串流 ----

        async connect() {
            while (!this.stopped) {
                let status = 0;
                try {
                    status = await this.streamOnce();
                } catch (_err) {
                    status = 0; // 網路錯誤
                }
                if (this.stopped) return;
                if (Core.shouldStopReconnect(status)) {
                    this.showUnauthorized();
                    return;
                }
                const delay = Core.computeBackoffMs(this.reconnectAttempt, {
                    retryAfterSeconds: this.retryAfterSeconds,
                });
                this.retryAfterSeconds = null;
                this.reconnectAttempt += 1;
                this.setStatus('reconnecting');
                await new Promise((resolve) => setTimeout(resolve, delay));
            }
        }

        async streamOnce() {
            const params = new URLSearchParams();
            if (this.model.lastSeq !== null && this.model.instanceId) {
                params.set('since_seq', String(this.model.lastSeq));
                params.set('instance_id', this.model.instanceId);
            }
            const url = params.toString() ? `${STREAM_URL}?${params}` : STREAM_URL;
            this.abortController = new AbortController();
            const response = await this.authClient.fetch(url, {
                signal: this.abortController.signal,
            });
            if (!response.ok) {
                if (response.status === 429) {
                    const retryAfter = Number.parseInt(response.headers.get('retry-after') || '', 10);
                    if (Number.isFinite(retryAfter)) this.retryAfterSeconds = retryAfter;
                }
                return response.status;
            }
            this.setStatus('connected');
            const parser = Core.createSseParser();
            const reader = response.body.getReader();
            for (;;) {
                const { done, value } = await reader.read();
                if (done) break;
                for (const event of parser.push(value)) {
                    this.handleEvent(event);
                }
            }
            return 200; // 正常結束（如 lifetime end）→ 重連
        }

        handleEvent(event) {
            if (event.event === 'meta') {
                const { switched } = this.model.applyMeta(event.data);
                if (switched) {
                    if (!this.paused) this.renderAll();
                    this.showOrQueueNotice('sourceSwitched');
                }
                this.reconnectAttempt = 0; // 成功收到 meta：退避重置
                this.updateInstanceLabel(event.data);
                if (this.settingsPanel) this.settingsPanel.updateWorkerComparison();
            } else if (event.event === 'log') {
                const { gap, evictedSeqs } = this.model.push(event.data);
                if (!this.paused) this.removeEvictedRows(evictedSeqs);
                if (gap > 0) this.showOrQueueNotice('gap', gap);
                this.scheduleRender(event.data);
            } else if (event.event === 'gap') {
                this.showOrQueueNotice('gap', event.data.lost_count);
            } else if (event.event === 'end') {
                this.setStatus('ended');
            }
        }

        // ---- 渲染（textContent / createTextNode only） ----

        matchesFilters(record) {
            const levelOrder = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };
            if (this.filters.level && (levelOrder[record.level] || 0) < levelOrder[this.filters.level]) {
                return false;
            }
            if (this.filters.hideAccess && record.logger_name === 'uvicorn.access') return false;
            if (this.filters.logger && !record.logger_name.startsWith(this.filters.logger)) return false;
            if (this.filters.keyword) {
                const keyword = this.filters.keyword.toLowerCase();
                if (!record.message.toLowerCase().includes(keyword)) return false;
            }
            return true;
        }

        buildLine(record) {
            const line = document.createElement('div');
            line.className = `log-line log-level-${(record.level || '').toLowerCase()}`;
            line.dataset.logSeq = String(record.seq);
            const head = document.createElement('span');
            head.className = 'log-line-head';
            const metaParts = [`${record.timestamp} ${record.level} [${record.logger_name}]`];
            if (record.event_code) {
                const ec = document.createElement('span');
                ec.className = 'log-event-code';
                ec.textContent = `event=${record.event_code}`;
                metaParts.push(ec);
            }
            if (record.outcome) {
                const oc = document.createElement('span');
                oc.className = `log-outcome log-outcome-${record.outcome.toLowerCase()}`;
                oc.textContent = `outcome=${record.outcome}`;
                metaParts.push(oc);
            }
            head.appendChild(document.createTextNode(metaParts[0] + ' '));
            for (let i = 1; i < metaParts.length; i += 1) {
                if (typeof metaParts[i] === 'string') {
                    head.appendChild(document.createTextNode(metaParts[i] + ' '));
                } else {
                    head.appendChild(metaParts[i]);
                    head.appendChild(document.createTextNode(' '));
                }
            }
            line.appendChild(head);
            const body = document.createElement('span');
            body.className = 'log-line-message';
            for (const segment of Core.segmentHighlight(record.message, this.filters.keyword)) {
                if (segment.mark) {
                    const mark = document.createElement('mark');
                    mark.textContent = segment.text;
                    body.appendChild(mark);
                } else {
                    body.appendChild(document.createTextNode(segment.text));
                }
            }
            line.appendChild(body);
            return line;
        }

        appendNotice(kind, count) {
            const notice = document.createElement('div');
            notice.className = 'log-line log-notice';
            const key = kind === 'gap' ? 'systemLogs.gapNotice' : 'systemLogs.sourceSwitched';
            notice.setAttribute('data-i18n', key);
            if (kind === 'gap') {
                notice.setAttribute('data-i18n-params', JSON.stringify({ count }));
            }
            notice.textContent =
                window.i18n && window.i18n.t ? window.i18n.t(key, { count }) : key;
            this.elements.output.appendChild(notice);
            this.trimNotices();
            if (window.i18n && window.i18n.retranslate) {
                window.i18n.retranslate(notice);
            }
        }

        showOrQueueNotice(kind, count) {
            if (this.paused) {
                this.pendingNotices.push({ kind, count });
                return;
            }
            this.appendNotice(kind, count);
        }

        removeEvictedRows(seqs) {
            for (const seq of seqs) {
                const row = this.elements.output.querySelector(`[data-log-seq="${seq}"]`);
                if (row) row.remove();
            }
        }

        scheduleRender(record) {
            if (this.paused) return; // 暫停 = 停止 DOM 更新；資料模型持續累積
            if (this.matchesFilters(record)) {
                this.elements.output.appendChild(this.buildLine(record));
                if (this.followTail) {
                    this.elements.output.scrollTop = this.elements.output.scrollHeight;
                }
            }
        }

        trimNotices() {
            const notices = this.elements.output.querySelectorAll('.log-notice');
            for (let i = 0; i < notices.length - MAX_PENDING_NOTICES; i += 1) {
                notices[i].remove();
            }
        }

        renderAll() {
            const output = this.elements.output;
            output.textContent = '';
            const fragment = document.createDocumentFragment();
            for (const record of this.model.records) {
                if (this.matchesFilters(record)) fragment.appendChild(this.buildLine(record));
            }
            output.appendChild(fragment);
            if (this.followTail) output.scrollTop = output.scrollHeight;
        }

        // ---- UI 動作 ----

        togglePause() {
            this.paused = !this.paused;
            const key = this.paused ? 'systemLogs.resume' : 'systemLogs.pause';
            const label = this.elements.pauseBtn.querySelector('span');
            label.setAttribute('data-i18n', key);
            if (window.i18n && window.i18n.retranslate) {
                window.i18n.retranslate(this.elements.pauseBtn);
            }
            if (!this.paused) {
                this.renderAll(); // 續播：以資料模型重繪
                for (const notice of this.pendingNotices.drain()) {
                    this.appendNotice(notice.kind, notice.count);
                }
            }
        }

        download() {
            const lines = this.model.records
                .filter((record) => this.matchesFilters(record))
                .map((r) => `${r.timestamp} ${r.level} [${r.logger_name}] ${r.message}`);
            const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = `tcrt-system-logs-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
            link.click();
            URL.revokeObjectURL(link.href);
        }

        updateInstanceLabel(meta) {
            const params = { pid: meta.pid, instance: meta.worker_instance_id || '-' };
            this.elements.instance.textContent =
                window.i18n && window.i18n.t
                    ? window.i18n.t('systemLogs.workerLabel', params)
                    : `${params.pid} (${params.instance})`;
        }

        setStatus(state) {
            const el = this.elements.status;
            const key = `systemLogs.status.${state}`;
            el.setAttribute('data-i18n', key);
            el.textContent = window.i18n && window.i18n.t ? window.i18n.t(key) : state;
            el.className = `badge ${state === 'connected' ? 'bg-success' : 'bg-secondary'}`;
        }

        showUnauthorized() {
            this.stopped = true;
            if (this.abortController) this.abortController.abort();
            if (this.elements.main) this.elements.main.classList.add('d-none');
            if (this.elements.unauthorized) this.elements.unauthorized.classList.remove('d-none');
        }
    }

    /**
     * Runtime Settings 分頁（openspec: add-system-runtime-settings-viewer）。
     * 狀態機在 Core.createRuntimeSettingsController（DOM-free）；本 class 只做安全 DOM 落地。
     * 錯誤僅影響本面板，不碰 Logs 分頁的串流與資料模型。
     */
    class RuntimeSettingsPanel {
        constructor(page) {
            this.page = page;
            this.controller = Core.createRuntimeSettingsController({
                fetchSnapshot: () => this.fetchSnapshot(),
            });
            this.elements = {};
        }

        init() {
            const byId = (id) => document.getElementById(id);
            this.elements = {
                tabButton: byId('runtimeSettingsTabBtn'),
                refreshBtn: byId('rtsRefreshBtn'),
                generatedAt: byId('rtsGeneratedAt'),
                mismatchBanner: byId('rtsMismatchBanner'),
                workerUnknownNote: byId('rtsWorkerUnknownNote'),
                loading: byId('rtsLoading'),
                error: byId('rtsError'),
                content: byId('rtsContent'),
                pid: byId('rtsPid'),
                workerInstance: byId('rtsWorkerInstance'),
                configuredConcurrency: byId('rtsConfiguredConcurrency'),
                concurrencySourceBadge: byId('rtsConcurrencySourceBadge'),
                inferredConcurrency: byId('rtsInferredConcurrency'),
                workerCountNote: byId('rtsWorkerCountNote'),
                databaseRows: byId('rtsDatabaseRows'),
                publicBaseUrl: byId('rtsPublicBaseUrl'),
                enableAuth: byId('rtsEnableAuth'),
                bufferSize: byId('rtsBufferSize'),
                maxStreams: byId('rtsMaxStreams'),
                maxMessageChars: byId('rtsMaxMessageChars'),
                subscriberQueueSize: byId('rtsSubscriberQueueSize'),
                keepaliveSeconds: byId('rtsKeepaliveSeconds'),
                streamMaxLifetime: byId('rtsStreamMaxLifetime'),
            };
            this.elements.tabButton.addEventListener('shown.bs.tab', () => {
                this.loadWith(() => this.controller.onTabShown());
            });
            this.elements.refreshBtn.addEventListener('click', () => {
                this.loadWith(() => this.controller.refresh());
            });
        }

        async fetchSnapshot() {
            const response = await this.page.authClient.fetch(RUNTIME_SETTINGS_URL);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
        }

        async loadWith(action) {
            const before = this.controller.state.fetchCount;
            const pending = action();
            if (this.controller.state.status === 'loading' && this.controller.state.fetchCount > before) {
                this.showLoading();
            }
            await pending;
            this.render();
        }

        setI18nText(el, key, params) {
            const translate =
                window.i18n && window.i18n.t ? (k, p) => window.i18n.t(k, p) : null;
            Core.applyI18nText(el, key, params, translate);
        }

        showLoading() {
            this.elements.loading.classList.remove('d-none');
            this.elements.error.classList.add('d-none');
        }

        render() {
            const state = this.controller.state;
            this.elements.loading.classList.toggle('d-none', state.status !== 'loading');
            this.elements.error.classList.toggle('d-none', state.status !== 'error');
            this.elements.content.classList.toggle('d-none', state.status !== 'loaded' && !state.data);
            if (state.data) this.renderData(state.data);
            this.updateWorkerComparison();
        }

        renderData(data) {
            const dash = '—';
            this.elements.generatedAt.textContent = data.generated_at || '';
            this.elements.pid.textContent = String(data.pid);
            this.elements.workerInstance.textContent = data.worker_instance_id || dash;

            const proc = data.process || {};
            this.elements.configuredConcurrency.textContent =
                proc.configured_web_concurrency !== null && proc.configured_web_concurrency !== undefined
                    ? String(proc.configured_web_concurrency)
                    : dash;
            const sourceKey = Core.concurrencySourceKey(proc.web_concurrency_source);
            const badge = this.elements.concurrencySourceBadge;
            if (sourceKey) {
                const badgeClass = {
                    configured: 'bg-success',
                    inferred_default: 'bg-secondary',
                    invalid_configured: 'bg-danger',
                }[proc.web_concurrency_source];
                badge.className = `badge ms-1 ${badgeClass}`;
                this.setI18nText(badge, sourceKey);
                badge.classList.remove('d-none');
            } else {
                badge.classList.add('d-none');
                badge.removeAttribute('data-i18n');
                badge.textContent = '';
            }
            this.elements.inferredConcurrency.textContent = String(
                proc.inferred_default_web_concurrency
            );
            const noteKey = Core.workerCountNoteKey(proc.worker_count_note_code);
            if (noteKey) {
                this.setI18nText(this.elements.workerCountNote, noteKey);
            } else {
                this.elements.workerCountNote.removeAttribute('data-i18n');
                this.elements.workerCountNote.textContent = proc.worker_count_note_code || '';
            }

            this.renderDatabaseRows(data.database || {});

            const appInfo = data.app || {};
            this.elements.publicBaseUrl.textContent = appInfo.public_base_url || dash;
            this.setI18nText(
                this.elements.enableAuth,
                appInfo.enable_auth ? 'systemLogs.settings.enabled' : 'systemLogs.settings.disabled'
            );

            const logViewer = data.log_viewer || {};
            this.elements.bufferSize.textContent = String(logViewer.buffer_size);
            this.elements.maxStreams.textContent = String(logViewer.max_streams);
            this.elements.maxMessageChars.textContent = String(logViewer.max_message_chars);
            this.elements.subscriberQueueSize.textContent = String(logViewer.subscriber_queue_size);
            this.elements.keepaliveSeconds.textContent = String(logViewer.keepalive_seconds);
            this.elements.streamMaxLifetime.textContent = String(
                logViewer.stream_max_lifetime_seconds
            );
        }

        renderDatabaseRows(database) {
            const dash = '—';
            const targets = [
                ['main', 'systemLogs.settings.dbMain'],
                ['audit', 'systemLogs.settings.dbAudit'],
                ['usm', 'systemLogs.settings.dbUsm'],
            ];
            const tbody = this.elements.databaseRows;
            tbody.textContent = '';
            for (const [target, labelKey] of targets) {
                const endpoint = database[target] || {};
                const row = document.createElement('tr');
                const th = document.createElement('th');
                th.scope = 'row';
                this.setI18nText(th, labelKey);
                row.appendChild(th);
                for (const field of ['engine', 'driver', 'host', 'port', 'database']) {
                    const td = document.createElement('td');
                    const value = endpoint[field];
                    td.textContent = value === null || value === undefined ? dash : String(value);
                    row.appendChild(td);
                }
                tbody.appendChild(row);
            }
        }

        /** Logs 端或 Settings 端 instance 變動時重算 mismatch 顯示 */
        updateWorkerComparison() {
            const data = this.controller.state.data;
            const banner = this.elements.mismatchBanner;
            const unknownNote = this.elements.workerUnknownNote;
            if (!banner || !unknownNote) return;
            if (!data) {
                banner.classList.add('d-none');
                unknownNote.classList.add('d-none');
                return;
            }
            const comparison = Core.workerMismatchState(
                this.page.model.instanceId,
                data.worker_instance_id
            );
            banner.classList.toggle('d-none', comparison !== 'mismatch');
            unknownNote.classList.toggle('d-none', comparison !== 'unknown');
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        new SystemLogsPage().init();
    });
})();
