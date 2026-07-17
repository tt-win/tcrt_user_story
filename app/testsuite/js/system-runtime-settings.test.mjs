// Runtime Settings 分頁 DOM-free core 測試：node --test app/testsuite/js/system-runtime-settings.test.mjs
// openspec: add-system-runtime-settings-viewer
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const core = require('../../static/js/system-logs-core.js');

const here = path.dirname(fileURLToPath(import.meta.url));
const localesDir = path.join(here, '../../static/locales');

function makeSnapshot(overrides = {}) {
    return {
        generated_at: '2026-07-17T00:00:00Z',
        pid: 1,
        worker_instance_id: 'w-1',
        ...overrides,
    };
}

function makeFetch({ failures = 0, snapshots = null } = {}) {
    let calls = 0;
    return {
        get calls() {
            return calls;
        },
        fetchSnapshot() {
            calls += 1;
            if (calls <= failures) return Promise.reject(new Error('boom'));
            const data = snapshots ? snapshots[Math.min(calls, snapshots.length) - 1] : makeSnapshot();
            return Promise.resolve(data);
        },
    };
}

// ---- lazy 一次 / refresh 再 fetch ----

test('controller: 首次切入 lazy fetch 一次，再次切入不重打', async () => {
    const fetcher = makeFetch();
    const controller = core.createRuntimeSettingsController({
        fetchSnapshot: () => fetcher.fetchSnapshot(),
    });
    assert.equal(controller.state.status, 'idle');
    await controller.onTabShown();
    assert.equal(fetcher.calls, 1);
    assert.equal(controller.state.status, 'loaded');
    assert.equal(controller.state.data.worker_instance_id, 'w-1');
    await controller.onTabShown();
    await controller.onTabShown();
    assert.equal(fetcher.calls, 1); // lazy：成功後切入不自動重打
});

test('controller: refresh 永遠再 fetch 並更新資料', async () => {
    const fetcher = makeFetch({
        snapshots: [makeSnapshot(), makeSnapshot({ worker_instance_id: 'w-2' })],
    });
    const controller = core.createRuntimeSettingsController({
        fetchSnapshot: () => fetcher.fetchSnapshot(),
    });
    await controller.onTabShown();
    await controller.refresh();
    assert.equal(fetcher.calls, 2);
    assert.equal(controller.state.data.worker_instance_id, 'w-2');
});

test('controller: 失敗 → error 狀態；再次切入不重打；refresh 可重試成功', async () => {
    const fetcher = makeFetch({ failures: 1 });
    const controller = core.createRuntimeSettingsController({
        fetchSnapshot: () => fetcher.fetchSnapshot(),
    });
    await controller.onTabShown();
    assert.equal(controller.state.status, 'error');
    assert.equal(controller.state.data, null);
    await controller.onTabShown();
    assert.equal(fetcher.calls, 1); // error 後切入分頁不自動重打
    await controller.refresh();
    assert.equal(fetcher.calls, 2);
    assert.equal(controller.state.status, 'loaded');
});

test('controller: 載入中重複觸發不疊加 fetch', async () => {
    let resolveFetch;
    const controller = core.createRuntimeSettingsController({
        fetchSnapshot: () =>
            new Promise((resolve) => {
                resolveFetch = resolve;
            }),
    });
    const first = controller.onTabShown();
    assert.equal(controller.state.status, 'loading');
    const second = controller.onTabShown();
    const third = controller.refresh();
    resolveFetch(makeSnapshot());
    await Promise.all([first, second, third]);
    assert.equal(controller.state.status, 'loaded');
    assert.equal(controller.state.fetchCount, 1);
});

// ---- 錯誤不影響 Logs 狀態模型 ----

test('controller 錯誤不影響 Logs 資料模型', async () => {
    const model = core.createLogModel(10);
    model.applyMeta({ worker_instance_id: 'logs-w' });
    model.push({ seq: 1, message: 'a' });
    model.push({ seq: 2, message: 'b' });

    const controller = core.createRuntimeSettingsController({
        fetchSnapshot: () => Promise.reject(new Error('settings api down')),
    });
    await controller.onTabShown();
    assert.equal(controller.state.status, 'error');

    // Logs 狀態模型完全不受影響
    assert.equal(model.instanceId, 'logs-w');
    assert.equal(model.lastSeq, 2);
    assert.equal(model.records.length, 2);
    const { gap } = model.push({ seq: 3, message: 'c' });
    assert.equal(gap, 0); // 仍可正常接收
});

// ---- worker mismatch 判定 ----

test('mismatch: 僅雙端非空 instance 且不同才 mismatch', () => {
    assert.equal(core.workerMismatchState('w-1', 'w-2'), 'mismatch');
    assert.equal(core.workerMismatchState('w-1', 'w-1'), 'match');
});

test('mismatch: 任一方 instance 缺失 → unknown（不因 PID 判定）', () => {
    assert.equal(core.workerMismatchState(null, 'w-2'), 'unknown');
    assert.equal(core.workerMismatchState('w-1', null), 'unknown');
    assert.equal(core.workerMismatchState('', 'w-2'), 'unknown');
    assert.equal(core.workerMismatchState('w-1', ''), 'unknown');
    assert.equal(core.workerMismatchState(undefined, undefined), 'unknown');
    assert.equal(core.workerMismatchState(null, null), 'unknown');
});

// ---- code → i18n 文案映射 ----

test('code 映射：concurrency source 與 worker note 對應 i18n key', () => {
    assert.equal(
        core.concurrencySourceKey('configured'),
        'systemLogs.settings.sourceConfigured',
    );
    assert.equal(
        core.concurrencySourceKey('inferred_default'),
        'systemLogs.settings.sourceInferredDefault',
    );
    assert.equal(
        core.concurrencySourceKey('invalid_configured'),
        'systemLogs.settings.sourceInvalidConfigured',
    );
    assert.equal(core.concurrencySourceKey('something_new'), null);
    assert.equal(core.concurrencySourceKey('__proto__'), null); // 僅接受白名單 code
    assert.equal(
        core.workerCountNoteKey('not_actual_worker_count'),
        'systemLogs.settings.notActualWorkerCount',
    );
    assert.equal(core.workerCountNoteKey('other_code'), null);
});

test('code 映射的 i18n key 在三語系皆有文案', () => {
    const keys = [
        core.concurrencySourceKey('configured'),
        core.concurrencySourceKey('inferred_default'),
        core.concurrencySourceKey('invalid_configured'),
        core.workerCountNoteKey('not_actual_worker_count'),
    ];
    for (const locale of ['en-US', 'zh-CN', 'zh-TW']) {
        const data = JSON.parse(readFileSync(path.join(localesDir, `${locale}.json`), 'utf-8'));
        for (const key of keys) {
            const value = key.split('.').reduce((node, part) => node && node[part], data);
            assert.equal(typeof value, 'string', `${locale} 缺 ${key}`);
            assert.ok(value.length > 0, `${locale} ${key} 為空`);
        }
    }
});

// ---- 語系重繪（i18n lifecycle 契約） ----

function loadLocale(locale) {
    return JSON.parse(readFileSync(path.join(localesDir, `${locale}.json`), 'utf-8'));
}

function lookupKey(data, key) {
    return key.split('.').reduce((node, part) => node && node[part], data);
}

/** 最小 element stub：applyI18nText 只需要 attribute 與 textContent */
function makeElementStub() {
    const attributes = new Map();
    return {
        textContent: '',
        setAttribute(name, value) {
            attributes.set(name, String(value));
        },
        removeAttribute(name) {
            attributes.delete(name);
        },
        getAttribute(name) {
            return attributes.has(name) ? attributes.get(name) : null;
        },
    };
}

/** 模擬 i18n.js translateElement 在 languageChanged 後的重譯行為 */
function retranslateStub(el, localeData) {
    const key = el.getAttribute('data-i18n');
    if (!key) return;
    const paramsAttr = el.getAttribute('data-i18n-params');
    const params = paramsAttr ? JSON.parse(paramsAttr) : {};
    let text = lookupKey(localeData, key);
    for (const [name, value] of Object.entries(params)) {
        text = text.replaceAll(`{${name}}`, String(value));
    }
    el.textContent = text;
}

test('applyI18nText：寫入 data-i18n 供 lifecycle 重譯，並立即渲染當前語系', () => {
    const enUS = loadLocale('en-US');
    const el = makeElementStub();
    const key = core.concurrencySourceKey('invalid_configured');
    core.applyI18nText(el, key, null, (k) => lookupKey(enUS, k));
    assert.equal(el.getAttribute('data-i18n'), key);
    assert.equal(el.getAttribute('data-i18n-params'), null);
    assert.equal(el.textContent, lookupKey(enUS, key));
});

test('languageChanged 重譯：動態 badge／note 依 data-i18n 重繪為新語系文案', () => {
    const enUS = loadLocale('en-US');
    const codes = [
        core.concurrencySourceKey('configured'),
        core.concurrencySourceKey('inferred_default'),
        core.concurrencySourceKey('invalid_configured'),
        core.workerCountNoteKey('not_actual_worker_count'),
    ];
    for (const key of codes) {
        const el = makeElementStub();
        core.applyI18nText(el, key, null, (k) => lookupKey(enUS, k));
        const before = el.textContent;
        for (const locale of ['zh-TW', 'zh-CN']) {
            const localeData = loadLocale(locale);
            retranslateStub(el, localeData); // 模擬 languageChanged → document retranslate
            assert.equal(el.textContent, lookupKey(localeData, key), `${locale} ${key}`);
            assert.notEqual(el.textContent, before, `${locale} ${key} 未重繪`);
        }
    }
});

test('applyI18nText：params 序列化進 data-i18n-params 且重譯後保留代入值', () => {
    const enUS = loadLocale('en-US');
    const el = makeElementStub();
    core.applyI18nText(el, 'systemLogs.workerLabel', { pid: 42, instance: 'w-9' }, (k, p) =>
        lookupKey(enUS, k).replaceAll('{pid}', String(p.pid)).replaceAll('{instance}', p.instance)
    );
    assert.equal(el.getAttribute('data-i18n-params'), '{"pid":42,"instance":"w-9"}');
    assert.ok(el.textContent.includes('42') && el.textContent.includes('w-9'));
    retranslateStub(el, loadLocale('zh-TW'));
    assert.ok(el.textContent.includes('42') && el.textContent.includes('w-9'), '重譯後參數保留');
});

test('invalid_configured 文案不得暗示會改用推導預設', () => {
    const key = core.concurrencySourceKey('invalid_configured');
    for (const locale of ['en-US', 'zh-CN', 'zh-TW']) {
        const data = JSON.parse(readFileSync(path.join(localesDir, `${locale}.json`), 'utf-8'));
        const value = key.split('.').reduce((node, part) => node && node[part], data);
        assert.doesNotMatch(value, /will use|將使用|将使用/i, `${locale} 文案暗示 fallback`);
    }
});
