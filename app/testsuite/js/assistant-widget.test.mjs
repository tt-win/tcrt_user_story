// assistant-widget.js 純函式的 DOM-free 測試：
//   node --test app/testsuite/js/assistant-widget.test.mjs
// assistant-widget.js 是瀏覽器全域 script（無 module.exports），以 vm 載入後測其全域函式
// （SSE parser / 確認卡狀態機 / 取消流程），仿 bulk-test-data.test.mjs 既有慣例
// （spec assistant-widget-ui「前端核心邏輯自動化測試」）。
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = readFileSync(path.join(here, '../../static/js/assistant-widget.js'), 'utf-8');
const cssSource = readFileSync(path.join(here, '../../static/css/assistant-widget.css'), 'utf-8');
const localeSources = Object.fromEntries(['zh-TW', 'zh-CN', 'en-US'].map((locale) => [
  locale,
  JSON.parse(readFileSync(path.join(here, `../../static/locales/${locale}.json`), 'utf-8')),
]));
const assistantServiceDir = path.join(here, '../../services/assistant');
const registryToolNames = new Set(readdirSync(assistantServiceDir)
  .filter((name) => /^tools_.*\.py$/.test(name))
  .flatMap((name) => Array.from(
    readFileSync(path.join(assistantServiceDir, name), 'utf-8').matchAll(/name="([^"]+)"/g),
    (match) => match[1]
  )));

const context = vm.createContext({
  window: {},
  document: { addEventListener() {}, body: { appendChild() {} } },
  console,
  localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  sessionStorage: { getItem() { return null; }, setItem() {} },
});
context.window.addEventListener = () => {};
vm.runInContext(source, context);

const {
  parseSSEChunk,
  parseSseEventId,
  confirmTier,
  formatConfirmTargetLine,
  formatConfirmTargetList,
  formatConfirmBatchTargetList,
  turnStateReducer,
  pendingActionRenderMode,
  toolOutcomeView,
  confirmStatusOutcome,
  toolActivitySummaryMarkup,
  toolEventPresentation,
  toolStatusIconMarkup,
  confirmActionUiState,
  confirmComposerShouldLock,
  authoritativeInflightKey,
  toolActionI18nKey,
  confirmationActionLabelMarkup,
  escapeHtml,
} = context;

// ---------------------------------------------------------------------- //
// escapeHtml
// ---------------------------------------------------------------------- //

test('escapeHtml 轉義 5 個特殊字元', () => {
  assert.equal(escapeHtml(`<script>&"'</script>`), '&lt;script&gt;&amp;&quot;&#39;&lt;/script&gt;');
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(undefined), '');
  assert.equal(escapeHtml(42), '42');
});

test('toolActionI18nKey：合法工具使用 action key，異常 identifier 不直接外顯', () => {
  assert.equal(toolActionI18nKey('list_test_case_sets'), 'assistant.action.list_test_case_sets');
  assert.equal(toolActionI18nKey('list-test-case-sets'), 'assistant.unknownAction');
  assert.equal(toolActionI18nKey('<script>'), 'assistant.unknownAction');
});

test('所有 registry 工具皆有三語明確動作名稱，且不等於 method identifier', () => {
  assert.equal(registryToolNames.size, 65, '工具擷取必須覆蓋完整 registry');
  for (const [locale, translations] of Object.entries(localeSources)) {
    const actions = translations.assistant.action;
    for (const toolName of registryToolNames) {
      assert.equal(typeof actions[toolName], 'string', `${locale} 缺少 assistant.action.${toolName}`);
      assert.ok(actions[toolName].trim(), `${locale} 的 ${toolName} 動作名稱不可為空`);
      assert.notEqual(actions[toolName], toolName, `${locale} 不得直接顯示 method identifier ${toolName}`);
    }
  }
});

test('工具步驟以可重譯 action key 呈現，沒有 method identifier 可見 fallback', () => {
  assert.match(source, /function addToolStep[\s\S]*?toolActionI18nKey\(toolName\)/);
  assert.match(source, /data-i18n="assistant\.executingPrefix"/);
  assert.match(source, /data-i18n="\$\{escapeHtml\(actionKey\)\}"/);
  assert.match(source, /window\.i18n\.retranslate\(row\)/);
  assert.equal(source.includes('t(`assistant.action.${toolName}`, {}, toolName)'), false);
  assert.equal(source.includes('t(entry.action, {}, entry.tool_name)'), false);
});

test('confirmation action：i18n 未載入或 key 異常時不外顯 raw identifier，並可重新翻譯', () => {
  const unloadedT = (_key, _params, fallback) => fallback;
  const known = confirmationActionLabelMarkup('assistant.action.list_test_case_sets', unloadedT);
  assert.match(known, /data-i18n="assistant\.action\.list_test_case_sets"/);
  assert.match(known, />System action</);
  assert.equal(known.includes('>list_test_case_sets<'), false);

  const invalid = confirmationActionLabelMarkup('list_test_case_sets', unloadedT);
  assert.match(invalid, /data-i18n="assistant\.unknownAction"/);
  assert.equal(invalid.includes('list_test_case_sets'), false);
  assert.match(source, /function appendConfirmCard[\s\S]*?window\.i18n\.retranslate\(card\)/);
});

test('composite confirmation 的每筆 action label 保留 data-i18n 且不以 tool_name fallback', () => {
  const html = formatConfirmTargetList({ target_type: 'batch_actions', affected_count: 2, actions: [
    { tool_name: 'list_test_case_sets', action: 'assistant.action.list_test_case_sets', target: { target_type: 'new', target_label: 'A' } },
    { tool_name: 'delete_test_run_set', action: 'assistant.action.delete_test_run_set', target: { target_type: 'new', target_label: 'B' } },
  ] }, (_key, _params, fallback) => fallback);
  assert.match(html, /data-i18n="assistant\.action\.list_test_case_sets"/);
  assert.match(html, /data-i18n="assistant\.action\.delete_test_run_set"/);
  assert.equal(html.includes('>list_test_case_sets<'), false);
});

// ---------------------------------------------------------------------- //
// SSE parser
// ---------------------------------------------------------------------- //

test('SSE parser：單一完整事件', () => {
  const chunk = 'event: done\nid: abc123:2\ndata: {"seq": 2, "payload": null}\n\n';
  const { events, remainder } = parseSSEChunk('', chunk);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'done');
  assert.equal(events[0].id, 'abc123:2');
  assert.equal(events[0].seq, 2);
  assert.equal(events[0].payload, null);
  assert.equal(remainder, '');
});

test('SSE parser：一個 chunk 內含多個事件', () => {
  const chunk =
    'event: tool_started\nid: t1:0\ndata: {"seq": 0, "payload": {"tool_name": "list_test_cases"}}\n\n' +
    'event: tool_finished\nid: t1:1\ndata: {"seq": 1, "payload": {"tool_name": "list_test_cases", "ok": true}}\n\n';
  const { events, remainder } = parseSSEChunk('', chunk);
  assert.equal(events.length, 2);
  assert.equal(events[0].type, 'tool_started');
  assert.equal(events[0].payload.tool_name, 'list_test_cases');
  assert.equal(events[1].type, 'tool_finished');
  assert.equal(events[1].payload.ok, true);
  assert.equal(remainder, '');
});

test('SSE parser：跨 chunk 邊界（事件被切在中間）', () => {
  const full = 'event: text_delta\nid: t1:3\ndata: {"seq": 3, "payload": {"content": "hello"}}\n\n';
  const splitAt = 30;
  const part1 = full.slice(0, splitAt);
  const part2 = full.slice(splitAt);

  const first = parseSSEChunk('', part1);
  assert.equal(first.events.length, 0, '第一個 chunk 尚未收到完整事件，不應解析出任何事件');

  const second = parseSSEChunk(first.remainder, part2);
  assert.equal(second.events.length, 1);
  assert.equal(second.events[0].type, 'text_delta');
  assert.equal(second.events[0].payload.content, 'hello');
  assert.equal(second.remainder, '');
});

test('SSE parser：殘缺行（trailing partial line，尚無結尾 \\n\\n）保留在 remainder', () => {
  const chunk = 'event: done\nid: t1:5\ndata: {"seq": 5, "payload": null}\n\nevent: tool_start';
  const { events, remainder } = parseSSEChunk('', chunk);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'done');
  assert.equal(remainder, 'event: tool_start');
});

test('SSE parser：keepalive 註解行不視為事件', () => {
  const chunk = ': keepalive\n\nevent: done\nid: t1:9\ndata: {"seq": 9, "payload": null}\n\n';
  const { events } = parseSSEChunk('', chunk);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'done');
});

test('parseSseEventId：正確解析與非法輸入', () => {
  // 注意：parseSseEventId 在 vm context 內執行，回傳的物件字面量之 prototype 與本測試檔
  // 所在 realm 不同，deepStrictEqual 會因 prototype 不同而誤判失敗，故逐欄位比對。
  const parsed = parseSseEventId('a1b2c3:42');
  assert.equal(parsed.turnKey, 'a1b2c3');
  assert.equal(parsed.seq, 42);
  assert.equal(parseSseEventId(''), null);
  assert.equal(parseSseEventId(null), null);
  assert.equal(parseSseEventId('no-colon-here'), null);
});

// ---------------------------------------------------------------------- //
// confirmTier
// ---------------------------------------------------------------------- //

test('confirmTier：兩級分類正確', () => {
  assert.equal(confirmTier('idempotent_write'), 'light');
  assert.equal(confirmTier('reversible_write'), 'light');
  assert.equal(confirmTier('high_impact'), 'warning');
  assert.equal(confirmTier('irreversible'), 'warning');
  assert.equal(confirmTier('read'), 'light');
});

// ---------------------------------------------------------------------- //
// formatConfirmTargetLine（含 XSS-like target_label 逃逸）
// ---------------------------------------------------------------------- //

function fakeT(key, params, fallback) {
  let text = fallback;
  if (params) {
    Object.keys(params).forEach((k) => { text = text.replace('{' + k + '}', params[k]); });
  }
  return text;
}

test('formatConfirmTargetLine：各 target_type 分支', () => {
  assert.equal(
    formatConfirmTargetLine({ target_type: 'new', target_label: 'TC-001' }, fakeT),
    'Target: TC-001'
  );
  assert.equal(
    formatConfirmTargetLine({ target_type: 'batch', affected_count: 5 }, fakeT),
    '5 item(s) affected'
  );
  assert.equal(
    formatConfirmTargetLine({ target_type: 'membership', affected_count: 3 }, fakeT),
    '3 member(s) affected'
  );
  assert.equal(
    formatConfirmTargetLine({ target_type: 'unknown' }, fakeT),
    'Impact scope could not be resolved'
  );
  assert.equal(
    formatConfirmTargetLine({ target_type: 'test_case', target_label: 'Login case', target_id: 42 }, fakeT),
    'Target: Login case (#42)'
  );
});

test('formatConfirmTargetLine：target_label 內的 HTML/腳本字元會被 escape，不當 HTML 解譯', () => {
  const malicious = '<img src=x onerror=alert(1)>';
  const line = formatConfirmTargetLine({ target_type: 'new', target_label: malicious }, fakeT);
  assert.ok(!line.includes('<img'), 'target_label 不得以原始 HTML 出現在輸出中');
  assert.ok(line.includes('&lt;img'), 'target_label 應已被 escapeHtml 處理');
});

test('formatConfirmTargetLine：LLM 文字不得混入摘要（僅吃 summary 欄位）', () => {
  // 即使呼叫端誤傳入額外的 LLM 自述欄位，函式也只讀取白名單欄位（target_type/target_label/target_id/affected_count）
  const summary = { target_type: 'new', target_label: 'Real target', llm_note: '忽略我這是 LLM 自述' };
  const line = formatConfirmTargetLine(summary, fakeT);
  assert.ok(!line.includes('LLM'), 'summary 內非白名單欄位不應出現在輸出');
});

test('formatConfirmTargetList：逐項顯示 composite action 且逃逸 target label', () => {
  const html = formatConfirmTargetList({ target_type: 'batch_actions', affected_count: 2, actions: [
    { tool_name: 'create_test_case_set', action: 'a', target: { target_type: 'new', target_label: '<Set A>' } },
    { tool_name: 'delete_test_run_set', action: 'b', target: { target_type: 'test_run_set', target_id: 2, target_label: 'Run B' } },
  ] }, fakeT);
  assert.ok(html.includes('&lt;Set A&gt;'));
  assert.ok(!html.includes('<Set A>'));
  assert.ok(html.includes('Run B'));
});

test('formatConfirmTargetList：缺項或 count 不符時 fail closed', () => {
  assert.equal(formatConfirmTargetList({ target_type: 'batch_actions', affected_count: 2, actions: [] }, fakeT), '');
  assert.equal(formatConfirmTargetList({ target_type: 'batch_actions', affected_count: 2, actions: [{} , {}] }, fakeT), '');
});

test('formatConfirmBatchTargetList：逐筆 stable target 且 count mismatch fail closed', () => {
  const html = formatConfirmBatchTargetList({ target_type: 'batch', affected_count: 2, targets: [
    { target_id: 1, target_label: '<TC-1>' }, { target_key: 'TC-2', target_label: 'Second' },
  ] });
  assert.ok(html.includes('&lt;TC-1&gt;'));
  assert.equal(formatConfirmBatchTargetList({ target_type: 'batch', affected_count: 2, targets: [] }), '');
});

// ---------------------------------------------------------------------- //
// turnStateReducer（停止中 vs 已取消 兩段明確狀態）
// ---------------------------------------------------------------------- //

test('turnStateReducer：start 進入 streaming', () => {
  assert.equal(turnStateReducer('idle', { type: 'start' }), 'streaming');
});

test('turnStateReducer：streaming 中 stopRequested 進入 stopping（非直接 cancelled）', () => {
  assert.equal(turnStateReducer('streaming', { type: 'stopRequested' }), 'stopping');
});

test('turnStateReducer：非 streaming 狀態下 stopRequested 無效（避免對已結束回合誤觸發）', () => {
  assert.equal(turnStateReducer('idle', { type: 'stopRequested' }), 'idle');
  assert.equal(turnStateReducer('done', { type: 'stopRequested' }), 'done');
});

test('turnStateReducer：stopping 狀態收到 cancelled 事件才真正進入 cancelled', () => {
  const afterStop = turnStateReducer('streaming', { type: 'stopRequested' });
  assert.equal(afterStop, 'stopping');
  const afterCancelled = turnStateReducer(afterStop, { type: 'event', eventType: 'cancelled' });
  assert.equal(afterCancelled, 'cancelled');
});

test('turnStateReducer：done/error 事件進入 done', () => {
  assert.equal(turnStateReducer('streaming', { type: 'event', eventType: 'done' }), 'done');
  assert.equal(turnStateReducer('streaming', { type: 'event', eventType: 'error' }), 'done');
});

test('turnStateReducer：未知 action 或事件不改變狀態', () => {
  assert.equal(turnStateReducer('streaming', { type: 'noop' }), 'streaming');
  assert.equal(turnStateReducer('streaming', { type: 'event', eventType: 'tool_started' }), 'streaming');
  assert.equal(turnStateReducer('streaming', null), 'streaming');
});

// ---------------------------------------------------------------------- //
// pending action 渲染模式 / 徽章樣式
// ---------------------------------------------------------------------- //

test('pendingActionRenderMode：pending 可操作、unknown 專屬卡、其餘皆為 resolved', () => {
  assert.equal(pendingActionRenderMode('pending'), 'actionable');
  assert.equal(pendingActionRenderMode('unknown'), 'unknown');
  assert.equal(pendingActionRenderMode('confirmed'), 'resolved');
  assert.equal(pendingActionRenderMode('cancelled'), 'resolved');
  assert.equal(pendingActionRenderMode('expired'), 'resolved');
  assert.equal(pendingActionRenderMode('failed'), 'resolved');
});

test('pendingActionRenderMode：executing 不得被當成已取消', () => {
  assert.equal(pendingActionRenderMode('executing'), 'executing');
});

test('toolOutcomeView：write 結果只保留狀態，不暴露 payload', () => {
  const success = toolOutcomeView('succeeded', { id: 17, name: 'Regression Run', secret: 'must-not-render' });
  assert.equal(success.kind, 'success');
  assert.equal(success.labelKey, 'assistant.resultSucceeded');
  assert.equal('entries' in success, false);
  assert.equal(JSON.stringify(success).includes('Regression Run'), false);
  assert.equal(JSON.stringify(success).includes('must-not-render'), false);

  assert.equal(toolOutcomeView('failed', { status: 409, detail: 'conflict' }).kind, 'failure');
  assert.equal(toolOutcomeView('unknown', { status: 'unknown' }).kind, 'unknown');
  assert.equal(toolOutcomeView('running').kind, 'running');
  assert.equal(toolOutcomeView('cancelled').kind, 'cancelled');
  assert.equal(toolOutcomeView('expired').kind, 'expired');
});

test('confirmStatusOutcome：確認狀態全部映射為圖示而非文字 badge', () => {
  assert.equal(confirmStatusOutcome('confirmed'), 'succeeded');
  assert.equal(confirmStatusOutcome('executing'), 'running');
  assert.equal(confirmStatusOutcome('failed'), 'failed');
  assert.equal(confirmStatusOutcome('unknown'), 'unknown');
  assert.equal(confirmStatusOutcome('cancelled'), 'cancelled');
  assert.equal(confirmStatusOutcome('expired'), 'expired');
});

test('toolActivitySummaryMarkup：動作標題與右側狀態槽共用同一 summary', () => {
  const markup = toolActivitySummaryMarkup('執行動作');
  assert.equal((markup.match(/<summary>/g) || []).length, 1);
  assert.match(markup, /tcrt-assistant-tool-heading/);
  assert.match(markup, /tcrt-assistant-tool-status/);
  assert.match(markup, /執行動作/);
});

test('toolEventPresentation：confirm write 全程只顯示狀態圖示', () => {
  assert.equal(toolEventPresentation('tool_started', { display_mode: 'status_only' }), 'status');
  assert.equal(toolEventPresentation('tool_finished', { outcome: 'succeeded' }), 'status');
  assert.equal(toolEventPresentation('tool_finished', { outcome: 'failed' }), 'status');
  assert.equal(toolEventPresentation('tool_started', { tool_name: 'list_test_cases' }), 'activity');
  assert.equal(toolEventPresentation('tool_finished', { tool_name: 'list_test_cases', ok: true }), 'activity');
});

test('toolStatusIconMarkup：DOM 無可見文字且不包含動作與 payload 明細', () => {
  const markup = toolStatusIconMarkup('succeeded', 42, 'Action completed');
  const visibleText = markup.replace(/<[^>]+>/g, '').trim();
  assert.equal(visibleText, '');
  for (const forbidden of ['delete_test_case_section', 'attempted_count', 'remaining_count', 'secret detail']) {
    assert.equal(markup.includes(forbidden), false);
  }
  assert.match(markup, /role="status"/);
  assert.match(markup, /tcrt-assistant-result-success/);
});

test('unknown 狀態圖示沒有舊卡片 selector 樣式衝突', () => {
  assert.match(cssSource, /\.tcrt-assistant-tool-result\.tcrt-assistant-result-unknown\s*\{/);
  assert.equal(/^\.tcrt-assistant-result-unknown\s*\{/m.test(cssSource), false);
});

test('確認摘要與圖示使用同一動作容器版型', () => {
  assert.match(cssSource, /\.tcrt-assistant-tool-activity\s*>\s*\.tcrt-assistant-confirm-card\s*\{/);
  assert.match(cssSource, /\.tcrt-assistant-tool-status\s*\{[^}]*margin-left:\s*auto/s);
  assert.match(cssSource, /\.tcrt-assistant-tool-result\s*\{[^}]*width:\s*20px;[^}]*height:\s*20px/s);
  assert.equal(cssSource.includes('.tcrt-assistant-resolved {'), false);
  assert.match(source, /function appendConfirmCard[\s\S]*?ensureToolActivity\(assistantNode\)[\s\S]*?activity\.appendChild\(card\)/);
  assert.match(source, /const statusHost = activity\.querySelector\('\.tcrt-assistant-tool-status'\)/);
  assert.match(source, /statusHost\.replaceChildren\(icon\)/);
  assert.equal(source.includes('container.appendChild(icon)'), false);
  assert.match(source, /function discardPendingToolStep[\s\S]*?row\.remove\(\)[\s\S]*?statusHost\.replaceChildren\(\)/);
  assert.match(source, /evt\.type === 'confirmation_required'[\s\S]*?discardPendingToolStep\(node\)[\s\S]*?renderLiveConfirmCard\(node/);
  assert.match(source, /function failUnresolvedToolSteps[\s\S]*?tcrt-assistant-fail[\s\S]*?renderToolResult\(act, 'failed'\)/);
  assert.match(source, /evt\.type === 'error'[\s\S]*?failUnresolvedToolSteps\(assistantNodeRef\.node\)/);
  assert.match(source, /const activityByCallId = new Map\(\)[\s\S]*?activityByCallId\.set\(m\.llm_tool_call_id, node\)/);
  assert.match(source, /const sourceNode = m\.llm_tool_call_id \? activityByCallId\.get\(m\.llm_tool_call_id\) : null/);
});

test('confirmActionUiState：API 失敗恢復可操作，只有權威 outcome 可 settle', () => {
  assert.equal(confirmActionUiState('actionable', 'submit'), 'submitting');
  assert.equal(confirmActionUiState('submitting', 'api_error'), 'actionable');
  assert.equal(confirmActionUiState('submitting', 'succeeded'), 'confirmed');
  assert.equal(confirmActionUiState('submitting', 'failed'), 'failed');
  assert.equal(confirmActionUiState('submitting', 'unknown'), 'unknown');
});

test('confirmComposerShouldLock：confirm 後同 stream 有下一張確認卡時仍鎖定', () => {
  assert.equal(confirmComposerShouldLock(1), true);
  assert.equal(confirmComposerShouldLock(2), true);
  assert.equal(confirmComposerShouldLock(0), false);
});

test('authoritativeInflightKey：backend active turn 覆蓋 stale concrete marker', () => {
  assert.equal(authoritativeInflightKey('old-turn', { turn_key: 'new-turn', status: 'running' }), 'new-turn');
  assert.equal(authoritativeInflightKey('old-turn', null), null);
  assert.equal(authoritativeInflightKey('pending', { turn_key: 'active-turn' }), 'active-turn');
});
