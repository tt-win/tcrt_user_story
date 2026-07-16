/**
 * System log viewer 的 DOM-free 純函式核心。
 * 瀏覽器掛在 window.SystemLogsCore；Node（CJS）以 module.exports 匯出供 node --test。
 * 這裡不得引用 document / window DOM API。
 */
(function (root, factory) {
    const api = factory();
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    } else {
        root.SystemLogsCore = api;
    }
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    /** regex 特殊字元 escape（keyword 比對前必經） */
    function escapeRegExp(text) {
        return String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    /**
     * keyword highlight 切段：輸出 [{text, mark}] 片段結構。
     * 純資料，由 thin DOM assembler 以 textContent/createTextNode 落地。
     */
    function segmentHighlight(text, keyword) {
        const source = String(text);
        if (!keyword) {
            return [{ text: source, mark: false }];
        }
        const pattern = new RegExp(escapeRegExp(keyword), 'gi');
        const segments = [];
        let cursor = 0;
        let match;
        while ((match = pattern.exec(source)) !== null) {
            if (match.index > cursor) {
                segments.push({ text: source.slice(cursor, match.index), mark: false });
            }
            segments.push({ text: match[0], mark: true });
            cursor = match.index + match[0].length;
            if (match[0].length === 0) pattern.lastIndex += 1; // 防空比對死迴圈
        }
        if (cursor < source.length) {
            segments.push({ text: source.slice(cursor), mark: false });
        }
        return segments.length ? segments : [{ text: '', mark: false }];
    }

    /**
     * SSE 增量 parser：push(Uint8Array|string) → 事件陣列。
     * - TextDecoder stream 模式處理 UTF-8 多位元組拆段
     * - frame 以空行分隔；結尾不完整 frame 暫存待下個 chunk
     * - comment 行（keep-alive）不產生事件
     */
    function createSseParser() {
        const decoder = typeof TextDecoder !== 'undefined' ? new TextDecoder('utf-8') : null;
        let buffer = '';

        function parseFrame(rawFrame) {
            const event = { event: 'message', id: null, data: null };
            const dataLines = [];
            let hasField = false;
            for (const rawLine of rawFrame.split('\n')) {
                if (!rawLine || rawLine.startsWith(':')) continue;
                const sep = rawLine.indexOf(':');
                const field = sep === -1 ? rawLine : rawLine.slice(0, sep);
                let value = sep === -1 ? '' : rawLine.slice(sep + 1);
                if (value.startsWith(' ')) value = value.slice(1);
                hasField = true;
                if (field === 'event') event.event = value;
                else if (field === 'id') event.id = Number.parseInt(value, 10);
                else if (field === 'data') dataLines.push(value);
            }
            if (!hasField) return null; // comment-only frame（keep-alive）
            const rawData = dataLines.join('\n');
            try {
                event.data = rawData ? JSON.parse(rawData) : null;
            } catch (_err) {
                event.data = rawData;
            }
            return event;
        }

        return {
            push(chunk) {
                if (typeof chunk === 'string') {
                    buffer += chunk;
                } else if (decoder) {
                    buffer += decoder.decode(chunk, { stream: true });
                }
                buffer = buffer.replace(/\r\n/g, '\n');
                const events = [];
                let boundary;
                while ((boundary = buffer.indexOf('\n\n')) !== -1) {
                    const frame = buffer.slice(0, boundary);
                    buffer = buffer.slice(boundary + 2);
                    const event = parseFrame(frame);
                    if (event) events.push(event);
                }
                return events;
            },
        };
    }

    /**
     * 重連退避：exponential backoff + jitter；429 遵循 Retry-After。
     * random 可注入以利測試。
     */
    function computeBackoffMs(attempt, options) {
        const opts = options || {};
        const baseMs = opts.baseMs || 1000;
        const maxMs = opts.maxMs || 30000;
        const random = opts.random || Math.random;
        if (opts.retryAfterSeconds != null && Number.isFinite(opts.retryAfterSeconds)) {
            return Math.min(maxMs, Math.max(0, opts.retryAfterSeconds * 1000));
        }
        const exp = Math.min(maxMs, baseMs * Math.pow(2, Math.max(0, attempt)));
        return Math.round(exp * (0.5 + random() * 0.5)); // jitter：50%–100%
    }

    /** 401/403 → 停止重連並呈現未授權狀態 */
    function shouldStopReconnect(status) {
        return status === 401 || status === 403;
    }

    /**
     * 前端資料模型：有界 record 陣列（與 DOM 同步環形淘汰）、
     * seq 缺口偵測、worker instance 切換 reset。
     */
    function createLogModel(maxRecords) {
        const limit = maxRecords || 5000;
        return {
            records: [],
            instanceId: null,
            lastSeq: null,

            /** meta event：instance 改變 → 清空資料與 cursor，回報 switched */
            applyMeta(meta) {
                const incoming = meta && meta.worker_instance_id;
                const switched = this.instanceId !== null && incoming !== this.instanceId;
                if (switched) {
                    this.records = [];
                    this.lastSeq = null;
                }
                this.instanceId = incoming || null;
                return { switched };
            },

            /** log event：回傳 gap 與實際淘汰的 seq，供 DOM 精確同步移除 */
            push(record) {
                let gap = 0;
                if (this.lastSeq !== null && record.seq > this.lastSeq + 1) {
                    gap = record.seq - this.lastSeq - 1;
                }
                this.lastSeq = record.seq;
                this.records.push(record);
                const evictedSeqs = [];
                while (this.records.length > limit) {
                    evictedSeqs.push(this.records.shift().seq);
                }
                return { gap, evicted: evictedSeqs.length, evictedSeqs };
            },

            clear() {
                this.records = [];
                this.lastSeq = null;
            },
        };
    }

    /** 暫停期間的 UI notice 使用有界 queue，避免 DOM 停更時在記憶體無界累積。 */
    function createBoundedQueue(maxItems) {
        const limit = Math.max(1, maxItems || 100);
        const items = [];
        return {
            push(item) {
                items.push(item);
                while (items.length > limit) items.shift();
            },
            drain() {
                return items.splice(0, items.length);
            },
            clear() {
                items.length = 0;
            },
            get length() {
                return items.length;
            },
        };
    }

    return {
        escapeRegExp,
        segmentHighlight,
        createSseParser,
        computeBackoffMs,
        shouldStopReconnect,
        createLogModel,
        createBoundedQueue,
    };
});
