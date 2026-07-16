// System log viewer DOM-free core 測試：node --test app/testsuite/js/system-logs.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const core = require('../../static/js/system-logs-core.js');

// ---- highlight segmenter（XSS 契約：輸出為片段資料，不產生 HTML 字串） ----

test('segmenter: 惡意 HTML 僅是純文字片段', () => {
    const payload = '<img src=x onerror=alert(1)> and <script>alert(2)</script>';
    const segments = core.segmentHighlight(payload, 'alert');
    assert.equal(segments.map((s) => s.text).join(''), payload); // 內容原樣保留
    assert.ok(segments.every((s) => typeof s.text === 'string' && typeof s.mark === 'boolean'));
    assert.deepEqual(
        segments.filter((s) => s.mark).map((s) => s.text),
        ['alert', 'alert'],
    );
});

test('segmenter: 引號與換行安全切段', () => {
    const text = 'line1 "quoted" \'single\'\nline2 key';
    const segments = core.segmentHighlight(text, 'key');
    assert.equal(segments.map((s) => s.text).join(''), text);
    assert.equal(segments.filter((s) => s.mark).length, 1);
});

test('segmenter: keyword 的 regex 特殊字元被 escape', () => {
    const text = 'match a.b(c)[d]* here a.b(c)[d]*';
    const segments = core.segmentHighlight(text, 'a.b(c)[d]*');
    assert.equal(segments.filter((s) => s.mark).length, 2);
    // "aXbYcZd" 不得被 . 或 * 誤比對
    const none = core.segmentHighlight('aXb(cY[dZ', 'a.b(c)[d]*');
    assert.ok(none.every((s) => !s.mark));
});

test('segmenter: 大小寫不敏感、無 keyword 回傳單一片段', () => {
    const upper = core.segmentHighlight('Hello WORLD', 'world');
    assert.deepEqual(upper.filter((s) => s.mark).map((s) => s.text), ['WORLD']);
    assert.deepEqual(core.segmentHighlight('plain', ''), [{ text: 'plain', mark: false }]);
});

// ---- SSE parser ----

const FRAME = (event, data, id) =>
    `${id != null ? `id: ${id}\n` : ''}event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

test('sse: 同一 chunk 多事件', () => {
    const parser = core.createSseParser();
    const events = parser.push(FRAME('log', { seq: 1 }, 1) + FRAME('log', { seq: 2 }, 2));
    assert.equal(events.length, 2);
    assert.deepEqual(events.map((e) => e.data.seq), [1, 2]);
    assert.deepEqual(events.map((e) => e.id), [1, 2]);
});

test('sse: 事件跨任意 chunk boundary', () => {
    const raw = FRAME('meta', { pid: 7 }) + FRAME('log', { seq: 1, message: 'hello' }, 1);
    for (let cut = 1; cut < raw.length - 1; cut += 3) {
        const parser = core.createSseParser();
        const events = [...parser.push(raw.slice(0, cut)), ...parser.push(raw.slice(cut))];
        assert.equal(events.length, 2, `cut=${cut}`);
        assert.equal(events[0].event, 'meta');
        assert.equal(events[1].data.message, 'hello');
    }
});

test('sse: UTF-8 多位元組字元被拆段仍正確', () => {
    const raw = FRAME('log', { message: '繁體中文與 emoji 🚀 訊息' }, 3);
    const bytes = new TextEncoder().encode(raw);
    for (const cut of [5, 17, 23, bytes.length - 4]) {
        const parser = core.createSseParser();
        const events = [...parser.push(bytes.slice(0, cut)), ...parser.push(bytes.slice(cut))];
        assert.equal(events.length, 1, `cut=${cut}`);
        assert.equal(events[0].data.message, '繁體中文與 emoji 🚀 訊息');
    }
});

test('sse: keep-alive comment 不產生事件', () => {
    const parser = core.createSseParser();
    assert.deepEqual(parser.push(': keep-alive\n\n'), []);
    const events = parser.push(': ka\n\n' + FRAME('log', { seq: 9 }, 9));
    assert.equal(events.length, 1);
});

test('sse: 結尾不完整 frame 暫存待續', () => {
    const parser = core.createSseParser();
    assert.deepEqual(parser.push('event: log\ndata: {"seq":'), []);
    const events = parser.push('1}\n\n');
    assert.equal(events.length, 1);
    assert.equal(events[0].data.seq, 1);
});

// ---- backoff ----

test('backoff: 指數成長、jitter 有界、上限 30s', () => {
    const fixed = { random: () => 1 }; // jitter 上界
    assert.equal(core.computeBackoffMs(0, fixed), 1000);
    assert.equal(core.computeBackoffMs(2, fixed), 4000);
    assert.equal(core.computeBackoffMs(10, fixed), 30000); // capped
    const low = core.computeBackoffMs(2, { random: () => 0 });
    assert.equal(low, 2000); // jitter 下界 50%
});

test('backoff: 429 Retry-After 優先', () => {
    assert.equal(core.computeBackoffMs(5, { retryAfterSeconds: 7 }), 7000);
    assert.equal(core.computeBackoffMs(0, { retryAfterSeconds: 999 }), 30000); // 仍受上限
});

test('backoff: 401/403 停止重連判斷', () => {
    assert.ok(core.shouldStopReconnect(401));
    assert.ok(core.shouldStopReconnect(403));
    assert.ok(!core.shouldStopReconnect(429));
    assert.ok(!core.shouldStopReconnect(500));
});

// ---- log model：環形淘汰、gap、instance reset ----

test('model: 5000 筆環形淘汰（資料模型有界）', () => {
    const model = core.createLogModel(5000);
    let lastResult;
    for (let i = 1; i <= 5100; i += 1) {
        lastResult = model.push({ seq: i, message: `m${i}` });
    }
    assert.equal(model.records.length, 5000);
    assert.equal(model.records[0].seq, 101); // 最舊被淘汰
    assert.equal(model.lastSeq, 5100);
    assert.deepEqual(lastResult.evictedSeqs, [100]); // DOM 可精確移除同一筆
});

test('model: seq 缺口偵測', () => {
    const model = core.createLogModel(100);
    assert.equal(model.push({ seq: 1 }).gap, 0);
    assert.equal(model.push({ seq: 2 }).gap, 0);
    assert.equal(model.push({ seq: 7 }).gap, 4); // 3..6 遺失
});

test('model: worker instance 切換 → 清空資料與 cursor', () => {
    const model = core.createLogModel(100);
    assert.deepEqual(model.applyMeta({ worker_instance_id: 'w1' }), { switched: false });
    model.push({ seq: 1 });
    model.push({ seq: 2 });
    const result = model.applyMeta({ worker_instance_id: 'w2' });
    assert.equal(result.switched, true);
    assert.equal(model.records.length, 0);
    assert.equal(model.lastSeq, null); // cursor 拋棄，不與新 instance 的 seq 混用
    assert.equal(model.instanceId, 'w2');
});

test('model: 同 instance 重連不清空', () => {
    const model = core.createLogModel(100);
    model.applyMeta({ worker_instance_id: 'w1' });
    model.push({ seq: 1 });
    assert.equal(model.applyMeta({ worker_instance_id: 'w1' }).switched, false);
    assert.equal(model.records.length, 1);
});

test('notice queue: 暫停期間有界累積並於續播一次 drain', () => {
    const queue = core.createBoundedQueue(3);
    queue.push({ kind: 'gap', count: 1 });
    queue.push({ kind: 'gap', count: 2 });
    queue.push({ kind: 'gap', count: 3 });
    queue.push({ kind: 'sourceSwitched' });
    assert.equal(queue.length, 3);
    assert.deepEqual(queue.drain(), [
        { kind: 'gap', count: 2 },
        { kind: 'gap', count: 3 },
        { kind: 'sourceSwitched' },
    ]);
    assert.equal(queue.length, 0);
});
