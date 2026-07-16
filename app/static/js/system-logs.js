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
            head.textContent = `${record.timestamp} ${record.level} [${record.logger_name}] `;
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

    document.addEventListener('DOMContentLoaded', () => {
        new SystemLogsPage().init();
    });
})();
