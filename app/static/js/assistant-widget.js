/**
 * 全域 AI 助手懸浮 widget（openspec change add-global-ai-assistant，task 7）。
 *
 * 純函式（SSE parser／確認卡狀態機／取消流程）刻意宣告為檔案頂層 function，
 * 供 app/testsuite/js/assistant-widget.test.mjs 以 `vm.runInContext` 載入後單獨測試
 * （仿 app/static/js/test-case-management/bulk.js 的既有慣例）。IIFE 模組本體僅負責
 * DOM／網路，呼叫這些純函式做決策。
 */

/* ======================================================================
 * 純函式（可獨立測試）
 * ==================================================================== */

/** HTML escape；確認卡的 target_label 等不可信字串一律先經此再嵌入樣板字串。 */
function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** 工具名稱只用來選擇既有翻譯 key；未知／異常 identifier 不得直接顯示給使用者。 */
function toolActionI18nKey(toolName) {
  return /^[a-z][a-z0-9_]*$/.test(String(toolName || ''))
    ? `assistant.action.${toolName}`
    : 'assistant.unknownAction';
}

/** 確認摘要只接受 canonical action key，文字 fallback 永不使用 raw key 或 method identifier。 */
function confirmationActionLabelMarkup(actionKey, t) {
  const safeKey = /^assistant\.action\.[a-z][a-z0-9_]*$/.test(String(actionKey || ''))
    ? actionKey
    : 'assistant.unknownAction';
  const genericAction = t('assistant.unknownAction', {}, 'System action');
  const actionLabel = t(safeKey, {}, genericAction);
  return `<span data-i18n="${escapeHtml(safeKey)}">${escapeHtml(actionLabel)}</span>`;
}

/**
 * SSE 分塊解析：純函式，輸入目前緩衝字串與新收到的 chunk 文字，回傳已解析完整事件陣列
 * 與剩餘（尚不完整）緩衝，供下次呼叫接續——正確處理跨 chunk 邊界、單一 chunk 內多事件、
 * 殘缺行（trailing partial line）。`: keepalive` 等註解行與空白 block 會被忽略。
 *
 * 回傳的每個事件：{ type, id, seq, payload }；`data:` 內容預期為
 * `{"seq": <int>, "payload": <any|null>}`（見 app/api/assistant.py `_tail_turn_events`）。
 */
function parseSSEChunk(buffer, chunkText) {
  const combined = buffer + (chunkText || '');
  const blocks = combined.split('\n\n');
  const remainder = blocks.pop();
  const events = [];
  for (const block of blocks) {
    const trimmed = block.trim();
    if (!trimmed || trimmed.startsWith(':')) continue;
    let type = null;
    let id = null;
    const dataLines = [];
    for (const rawLine of block.split('\n')) {
      const line = rawLine.replace(/\r$/, '');
      if (line.startsWith('event:')) type = line.slice(6).trim();
      else if (line.startsWith('id:')) id = line.slice(3).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    if (!type) continue;
    let seq = null;
    let payload = null;
    if (dataLines.length) {
      try {
        const parsed = JSON.parse(dataLines.join('\n'));
        if (parsed && typeof parsed === 'object') {
          seq = typeof parsed.seq === 'number' ? parsed.seq : null;
          payload = 'payload' in parsed ? parsed.payload : null;
        }
      } catch (e) {
        // 忽略無法解析的 data（不應發生於符合協定的伺服器輸出）
      }
    }
    events.push({ type, id, seq, payload });
  }
  return { events, remainder };
}

/** 解析 SSE `id:` 欄位（`<turn_key>:<seq>`），供前端得知目前 turn_key 以支援 stop/重連。 */
function parseSseEventId(id) {
  if (!id) return null;
  const idx = id.lastIndexOf(':');
  if (idx < 0) return null;
  const turnKey = id.slice(0, idx);
  const seq = parseInt(id.slice(idx + 1), 10);
  if (!turnKey || Number.isNaN(seq)) return null;
  return { turnKey, seq };
}

/** risk_level → 兩級確認卡（design：idempotent_write/reversible_write=輕量，high_impact/irreversible=警告）。 */
function confirmTier(riskLevel) {
  return riskLevel === 'high_impact' || riskLevel === 'irreversible' ? 'warning' : 'light';
}

/**
 * 由 server-derived confirmation_summary 組出確認卡的「目標」行（純函式、可測試）。
 * target_label 等不可信欄位一律先 escapeHtml 才嵌入，不得以 HTML/i18n key 解譯（spec 要求）。
 * `t(key, params, fallback)` 簽名比照 `window.i18n.t`。
 */
function formatConfirmTargetLine(summary, t) {
  if (!summary || typeof summary !== 'object') return '';
  const targetType = summary.target_type;
  if (targetType === 'new') {
    return t('assistant.confirmTargetNew', { label: escapeHtml(summary.target_label || '') }, 'Target: {label}');
  }
  if (targetType === 'batch') {
    return t('assistant.confirmTargetBatch', { count: summary.affected_count || 0 }, '{count} item(s) affected');
  }
  if (targetType === 'batch_actions') {
    return t('assistant.confirmTargetBatch', { count: summary.affected_count || 0 }, '{count} item(s) affected');
  }
  if (targetType === 'membership') {
    return t('assistant.confirmTargetMembership', { count: summary.affected_count || 0 }, '{count} member(s) affected');
  }
  if (targetType === 'unknown') {
    return t('assistant.confirmTargetUnresolvable', {}, 'Impact scope could not be resolved');
  }
  // 其餘皆為 target_resolver="single" 產生（resource_team_resolver 名稱，如 test_case/test_run_config）
  return t(
    'assistant.confirmTargetSingle',
    { label: escapeHtml(summary.target_label || ''), id: summary.target_id != null ? summary.target_id : '' },
    'Target: {label} (#{id})'
  );
}

function formatConfirmTargetList(summary, t) {
  if (!summary || summary.target_type !== 'batch_actions' || !Array.isArray(summary.actions)
      || summary.actions.length < 2 || summary.actions.length !== summary.affected_count) return '';
  const rows = summary.actions.map((entry) => {
    if (!entry || !entry.tool_name || !entry.action || !entry.target) return '';
    const actionLabel = confirmationActionLabelMarkup(entry.action, t);
    const targetLine = formatConfirmTargetLine(entry.target, t);
    const batchDetails = entry.target.target_type === 'batch' ? formatConfirmBatchTargetList(entry.target) : '';
    if (!actionLabel || !targetLine || (entry.target.target_type === 'batch' && !batchDetails)) return '';
    return `<li><span>${actionLabel}</span><br>${targetLine}${batchDetails}</li>`;
  });
  if (rows.some((row) => !row)) return '';
  return `<ul class="tcrt-assistant-cc-targets">${rows.join('')}</ul>`;
}

function formatConfirmBatchTargetList(summary) {
  if (!summary || summary.target_type !== 'batch' || !Array.isArray(summary.targets)
      || !summary.targets.length || summary.targets.length !== summary.affected_count) return '';
  const rows = summary.targets.map((target) => {
    if (!target || !target.target_label) return '';
    const identity = target.target_id != null ? `#${escapeHtml(target.target_id)} — `
      : target.target_key != null ? `${escapeHtml(target.target_key)} — ` : '';
    return `<li>${identity}${escapeHtml(target.target_label)}</li>`;
  });
  if (rows.some((row) => !row)) return '';
  return `<ul class="tcrt-assistant-cc-targets">${rows.join('')}</ul>`;
}

/**
 * turn 串流狀態機（純函式 reducer）。狀態：idle|streaming|stopping|cancelled|done。
 * 「停止中」與「已取消」MUST 為可區分的兩段狀態（spec 要求），故 stopRequested 只進入
 * stopping，真正的 cancelled 需等對應 SSE 事件到達。
 */
function turnStateReducer(state, action) {
  if (!action) return state;
  switch (action.type) {
    case 'start':
      return 'streaming';
    case 'stopRequested':
      return state === 'streaming' ? 'stopping' : state;
    case 'event':
      if (action.eventType === 'cancelled') return 'cancelled';
      if (action.eventType === 'done' || action.eventType === 'error') return 'done';
      return state;
    default:
      return state;
  }
}

/** pending action 的目前狀態 → 確認卡渲染模式：actionable（可按）｜resolved（徽章）｜unknown。 */
function pendingActionRenderMode(status) {
  if (status === 'pending') return 'actionable';
  if (status === 'executing') return 'executing';
  if (status === 'unknown') return 'unknown';
  return 'resolved';
}

/** Convert a tool outcome to deterministic icon-only presentation data. */
function toolOutcomeView(outcome) {
  const kind = outcome === 'running' ? 'running'
    : outcome === 'succeeded' ? 'success'
      : outcome === 'failed' ? 'failure'
        : outcome === 'cancelled' ? 'cancelled'
          : outcome === 'expired' ? 'expired' : 'unknown';
  const labelKey = kind === 'running' ? 'assistant.resolvedExecuting'
    : kind === 'success' ? 'assistant.resultSucceeded'
      : kind === 'failure' ? 'assistant.resultFailed'
        : kind === 'cancelled' ? 'assistant.resolvedCancelled'
          : kind === 'expired' ? 'assistant.resolvedExpired' : 'assistant.unknownTitle';
  return {
    kind,
    labelKey,
    fallback: kind === 'running' ? 'Running…'
      : kind === 'success' ? 'Action completed'
        : kind === 'failure' ? 'Action failed'
          : kind === 'cancelled' ? 'Cancelled'
            : kind === 'expired' ? 'Expired' : 'Result unknown',
  };
}

function confirmStatusOutcome(status) {
  if (status === 'confirmed') return 'succeeded';
  if (status === 'executing') return 'running';
  if (status === 'failed' || status === 'unknown' || status === 'cancelled' || status === 'expired') return status;
  return 'unknown';
}

function toolActivitySummaryMarkup(label) {
  return `<summary><span class="tcrt-assistant-tool-heading" data-i18n="assistant.activity">${escapeHtml(label)}</span><span class="tcrt-assistant-tool-status"></span></summary>`;
}

/** Confirmed writes use icon-only events; ordinary read tools retain the activity list. */
function toolEventPresentation(eventType, payload = {}) {
  if (eventType === 'tool_started' && payload.display_mode === 'status_only') return 'status';
  if (eventType === 'tool_finished' && payload.outcome) return 'status';
  return 'activity';
}

/** Build the status-only DOM markup; callers cannot pass tool arguments or result payloads. */
function toolStatusIconMarkup(outcome, actionId, label) {
  const view = toolOutcomeView(outcome);
  const path = view.kind === 'running'
    ? '<circle cx="12" cy="12" r="9" opacity=".3"/><path d="M12 3a9 9 0 0 1 9 9"/>'
    : view.kind === 'success'
      ? '<path d="m7 12 3 3 7-7"/><circle cx="12" cy="12" r="9"/>'
      : view.kind === 'failure'
        ? '<path d="m9 9 6 6m0-6-6 6"/><circle cx="12" cy="12" r="9"/>'
        : view.kind === 'cancelled'
          ? '<path d="M8 8l8 8M16 8l-8 8"/><circle cx="12" cy="12" r="9"/>'
          : view.kind === 'expired'
            ? '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>'
            : '<path d="M9.8 9a2.4 2.4 0 1 1 3.1 2.3c-.7.3-.9.8-.9 1.7M12 17h.01"/><circle cx="12" cy="12" r="9"/>';
  const actionAttr = actionId == null ? '' : ` data-action-id="${escapeHtml(actionId)}"`;
  return `<span class="tcrt-assistant-tool-result tcrt-assistant-result-${view.kind}" role="status" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}" data-i18n-aria-label="${view.labelKey}" data-i18n-title="${view.labelKey}"${actionAttr}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">${path}</svg></span>`;
}

/** Confirm UI state only settles after an authoritative tool outcome. */
function confirmActionUiState(state, event) {
  if (state === 'actionable' && event === 'submit') return 'submitting';
  if (state === 'submitting' && event === 'api_error') return 'actionable';
  if (state === 'submitting' && event === 'succeeded') return 'confirmed';
  if (state === 'submitting' && event === 'failed') return 'failed';
  if (state === 'submitting' && event === 'unknown') return 'unknown';
  return state;
}

/** The rendered actionable confirmation cards are authoritative for composer locking. */
function confirmComposerShouldLock(actionableCardCount) {
  return Number(actionableCardCount) > 0;
}

/** Backend running-turn state is authoritative over any stale local marker. */
function authoritativeInflightKey(storedKey, activeTurn) {
  if (activeTurn && activeTurn.turn_key) return activeTurn.turn_key;
  return null;
}

/* ======================================================================
 * IIFE 模組本體
 * ==================================================================== */

const AssistantWidget = (() => {
  const AVAILABILITY_CACHE_KEY = 'tcrt_assistant_availability_cache';
  const AVAILABILITY_CACHE_TTL_MS = 5 * 60 * 1000;
  const PANEL_OPEN_KEY = 'tcrt_assistant_panel_open';
  const CONV_KEY_PREFIX = 'tcrt_assistant_conv_';
  const INFLIGHT_KEY_PREFIX = 'tcrt_assistant_inflight_';
  const MARKED_URL = 'https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js';
  const DOMPURIFY_URL = 'https://cdn.jsdelivr.net/npm/dompurify@3.0.6/dist/purify.min.js';
  const RECONNECT_MAX_ATTEMPTS = 3;
  const SCOPE_NOTICE_AUTO_DISMISS_MS = 8000;

  let mounted = false;
  let root = null;
  let panelEl = null;
  let fabEl = null;
  let messagesEl = null;
  let inputEl = null;
  let sendBtnEl = null;
  let composerEl = null;
  let historyMenuEl = null;
  let attachChipEl = null;
  let teamBadgeEl = null;

  let currentConversation = null; // {id, conversation_key, scope_type, team_id, ...}
  let currentTurnKey = null;
  let turnState = 'idle';
  let hasUnresolvedConfirm = false;
  let selectedFiles = [];
  let mdLibsPromise = null;
  let mdLibsReady = false;
  let activeAbortController = null;
  let currentEventSeq = -1;
  let streamGeneration = 0;

  function t(key, params, fallback) {
    if (window.i18n && typeof window.i18n.t === 'function') {
      return window.i18n.t(key, params || {}, fallback != null ? fallback : key);
    }
    let text = fallback != null ? fallback : key;
    if (params) {
      Object.keys(params).forEach((k) => {
        text = text.replace(new RegExp('\\{' + k + '\\}', 'g'), params[k]);
      });
    }
    return text;
  }

  function el(html) {
    const tpl = document.createElement('template');
    tpl.innerHTML = html.trim();
    return tpl.content.firstChild;
  }

  function randomId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID();
    return 'xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function getCurrentTeamId() {
    return window.AppUtils && typeof window.AppUtils.getCurrentTeamId === 'function'
      ? window.AppUtils.getCurrentTeamId()
      : null;
  }

  /* ---------------- Availability ---------------- */

  async function checkAvailability() {
    try {
      const cachedRaw = sessionStorage.getItem(AVAILABILITY_CACHE_KEY);
      if (cachedRaw) {
        const cached = JSON.parse(cachedRaw);
        if (cached && typeof cached.enabled === 'boolean' && Date.now() - cached.ts < AVAILABILITY_CACHE_TTL_MS) {
          return cached.enabled;
        }
      }
    } catch (e) { /* ignore cache corruption */ }

    try {
      if (!window.AuthClient || !window.AuthClient.getToken || !window.AuthClient.getToken()) return false;
      const resp = await window.AuthClient.fetch('/api/assistant/availability');
      const enabled = resp.ok && (await resp.json()).enabled === true;
      sessionStorage.setItem(AVAILABILITY_CACHE_KEY, JSON.stringify({ enabled, ts: Date.now() }));
      return enabled;
    } catch (e) {
      return false; // fail-closed
    }
  }

  /* ---------------- Markdown（lazy-load + fallback） ---------------- */

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function ensureMarkdownLibs() {
    if (mdLibsPromise) return mdLibsPromise;
    mdLibsPromise = Promise.all([loadScript(MARKED_URL), loadScript(DOMPURIFY_URL)])
      .then(() => {
        if (window.DOMPurify && typeof window.DOMPurify.addHook === 'function') {
          window.DOMPurify.addHook('afterSanitizeAttributes', (node) => {
            if (node.tagName === 'A') {
              node.setAttribute('target', '_blank');
              node.setAttribute('rel', 'noopener');
            }
          });
        }
        if (window.marked && typeof window.marked.use === 'function') {
          // 面板寬度固定，寬表格（多欄或單欄超長文字）必須能獨立橫向捲動，
          // 不能撐破訊息氣泡；用 wrapper div 而非在 <table> 本身設 display:block，
          // 避免破壞瀏覽器對 table/thead/tr/td 內建的表格版面配置。
          window.marked.use({
            renderer: {
              table(header, body) {
                const bodyHtml = body ? `<tbody>${body}</tbody>` : '';
                return `<div class="tcrt-assistant-table-wrap"><table>\n<thead>\n${header}</thead>\n${bodyHtml}</table>\n</div>\n`;
              },
            },
          });
        }
        mdLibsReady = !!(window.marked && window.DOMPurify);
      })
      .catch(() => {
        mdLibsReady = false;
      });
    return mdLibsPromise;
  }

  function renderMarkdown(rawText) {
    if (mdLibsReady && window.marked && window.DOMPurify) {
      try {
        return window.DOMPurify.sanitize(window.marked.parse(rawText || ''));
      } catch (e) { /* fall through to plain text */ }
    }
    return `<p>${escapeHtml(rawText || '').replace(/\n/g, '<br>')}</p>`;
  }

  /* ---------------- DOM 建構 ---------------- */

  function scrollToBottom() {
    if (messagesEl) messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function mount() {
    if (mounted) return;
    root = el(`<div id="tcrt-assistant-root"></div>`);
    root.appendChild(el(`
      <button class="tcrt-assistant-fab" id="tcrt-assistant-fab" type="button" data-i18n-aria-label="assistant.fabLabel" aria-label="${escapeHtml(t('assistant.fabLabel', {}, 'Open TCRT Assistant'))}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
          <path d="M21 12c0 4.1-4 7.4-9 7.4-1 0-2-.13-2.9-.38L4 21l1.2-3.6C3.8 16 3 14.1 3 12c0-4.1 4-7.4 9-7.4s9 3.3 9 7.4Z" stroke-linejoin="round"/>
          <circle cx="8.6" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="15.4" cy="12" r="1" fill="currentColor" stroke="none"/>
        </svg><span class="tcrt-assistant-unread" aria-hidden="true"></span>
      </button>
    `));
    root.appendChild(el(`
      <section class="tcrt-assistant-panel" id="tcrt-assistant-panel" role="dialog" aria-modal="false" data-i18n-aria-label="assistant.title" aria-label="${escapeHtml(t('assistant.title', {}, 'TCRT Assistant'))}">
        <header class="tcrt-assistant-head">
          <span class="tcrt-assistant-title" data-i18n="assistant.title">${escapeHtml(t('assistant.title', {}, 'TCRT Assistant'))}</span>
          <span class="tcrt-assistant-team-badge" id="tcrt-assistant-team-badge"></span>
          <span class="tcrt-assistant-spacer"></span>
          <button class="tcrt-assistant-icon-btn" type="button" id="tcrt-assistant-history-btn" data-i18n-title="assistant.historyTitle" data-i18n-aria-label="assistant.historyTitle" title="${escapeHtml(t('assistant.historyTitle', { team: '' }, 'Recent conversations'))}" aria-label="${escapeHtml(t('assistant.historyTitle', { team: '' }, 'Recent conversations'))}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l2.5 2.5M21 12a9 9 0 1 1-9-9 9 9 0 0 1 9 9Z"/></svg>
          </button>
          <button class="tcrt-assistant-icon-btn" type="button" id="tcrt-assistant-new-btn" data-i18n-title="assistant.newConversation" data-i18n-aria-label="assistant.newConversation" title="${escapeHtml(t('assistant.newConversation', {}, 'New conversation'))}" aria-label="${escapeHtml(t('assistant.newConversation', {}, 'New conversation'))}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
          </button>
          <button class="tcrt-assistant-icon-btn" type="button" id="tcrt-assistant-close-btn" data-i18n-title="assistant.close" data-i18n-aria-label="assistant.close" title="${escapeHtml(t('assistant.close', {}, 'Close'))}" aria-label="${escapeHtml(t('assistant.close', {}, 'Close'))}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>
          </button>
          <div class="tcrt-assistant-history-menu" id="tcrt-assistant-history-menu">
            <div class="tcrt-assistant-hm-title" id="tcrt-assistant-hm-title" data-i18n="assistant.historyTitle" data-i18n-params='{"team":""}'></div>
            <div id="tcrt-assistant-hm-list"></div>
            <button class="tcrt-assistant-hm-new" type="button" id="tcrt-assistant-hm-new-btn" data-i18n="assistant.newConversation">${escapeHtml(t('assistant.newConversation', {}, 'New conversation'))}</button>
          </div>
        </header>
        <div class="tcrt-assistant-messages" id="tcrt-assistant-messages" aria-live="polite"></div>
        <footer class="tcrt-assistant-composer" id="tcrt-assistant-composer">
          <div class="tcrt-assistant-attach-chip" id="tcrt-assistant-attach-chip"></div>
          <div class="tcrt-assistant-row">
            <input type="file" id="tcrt-assistant-file-input" multiple style="display:none">
            <button class="tcrt-assistant-composer-btn tcrt-assistant-attach-btn" type="button" id="tcrt-assistant-attach-btn" data-i18n-title="assistant.attachFile" data-i18n-aria-label="assistant.attachFile" title="${escapeHtml(t('assistant.attachFile', {}, 'Attach a file'))}" aria-label="${escapeHtml(t('assistant.attachFile', {}, 'Attach a file'))}">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 12.5 12.6 21a5.5 5.5 0 0 1-7.8-7.8l8.5-8.5a3.7 3.7 0 0 1 5.2 5.2l-8.5 8.5a1.8 1.8 0 0 1-2.6-2.6l7.8-7.8"/></svg>
            </button>
            <textarea id="tcrt-assistant-input" rows="1" data-i18n-placeholder="assistant.inputPlaceholder" placeholder="${escapeHtml(t('assistant.inputPlaceholder', {}, 'Ask or act on test cases / test runs…'))}" data-i18n-aria-label="assistant.inputPlaceholder" aria-label="${escapeHtml(t('assistant.inputPlaceholder', {}, 'Ask or act on test cases / test runs…'))}"></textarea>
            <button class="tcrt-assistant-composer-btn tcrt-assistant-send-btn" id="tcrt-assistant-send-btn" type="button" data-i18n-aria-label="assistant.send" aria-label="${escapeHtml(t('assistant.send', {}, 'Send'))}">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" stroke-linejoin="round"/></svg>
            </button>
          </div>
          <div class="tcrt-assistant-composer-hint">
            <span data-i18n="assistant.enterHint">${escapeHtml(t('assistant.enterHint', {}, 'Enter to send · Shift+Enter for new line'))}</span>
            <span class="tcrt-assistant-lock" id="tcrt-assistant-lock-hint"></span>
          </div>
        </footer>
      </section>
    `));
    document.body.appendChild(root);

    panelEl = root.querySelector('#tcrt-assistant-panel');
    fabEl = root.querySelector('#tcrt-assistant-fab');
    messagesEl = root.querySelector('#tcrt-assistant-messages');
    inputEl = root.querySelector('#tcrt-assistant-input');
    sendBtnEl = root.querySelector('#tcrt-assistant-send-btn');
    composerEl = root.querySelector('#tcrt-assistant-composer');
    historyMenuEl = root.querySelector('#tcrt-assistant-history-menu');
    attachChipEl = root.querySelector('#tcrt-assistant-attach-chip');
    teamBadgeEl = root.querySelector('#tcrt-assistant-team-badge');

    wireEvents();
    mounted = true;

    if (window.i18n && typeof window.i18n.retranslate === 'function') window.i18n.retranslate(root);

    if (localStorage.getItem(PANEL_OPEN_KEY) === '1') openPanel();
  }

  function destroy() {
    if (!mounted) return;
    if (activeAbortController) activeAbortController.abort();
    root.remove();
    root = null; panelEl = null; fabEl = null; messagesEl = null; inputEl = null;
    sendBtnEl = null; composerEl = null; historyMenuEl = null; attachChipEl = null; teamBadgeEl = null;
    mounted = false;
  }

  function setUnread(on) {
    if (fabEl) fabEl.classList.toggle('tcrt-assistant-has-unread', on);
  }

  function isOpen() {
    return panelEl && panelEl.classList.contains('tcrt-assistant-is-open');
  }

  function openPanel() {
    if (!panelEl) return;
    panelEl.classList.add('tcrt-assistant-is-open');
    localStorage.setItem(PANEL_OPEN_KEY, '1');
    setUnread(false);
    inputEl.focus();
    if (!currentConversation) void switchToTeamConversation();
  }

  function closePanel() {
    if (!panelEl) return;
    panelEl.classList.remove('tcrt-assistant-is-open');
    localStorage.setItem(PANEL_OPEN_KEY, '0');
    closeHistoryMenu();
    if (fabEl) fabEl.focus();
  }

  function togglePanel() {
    if (isOpen()) closePanel(); else openPanel();
  }

  function toggleHistoryMenu() {
    if (!historyMenuEl) return;
    const show = !historyMenuEl.classList.contains('tcrt-assistant-show');
    historyMenuEl.classList.toggle('tcrt-assistant-show', show);
    if (show) void refreshHistoryMenu();
  }

  function closeHistoryMenu() {
    if (historyMenuEl) historyMenuEl.classList.remove('tcrt-assistant-show');
  }

  function lockComposer(lock) {
    if (!composerEl) return;
    composerEl.classList.toggle('tcrt-assistant-locked', lock);
    inputEl.disabled = lock;
    if (!lock) {
      sendBtnEl.disabled = false;
      composerEl.classList.remove('tcrt-assistant-stopping');
    }
    const hint = root.querySelector('#tcrt-assistant-lock-hint');
    if (hint) hint.textContent = lock ? t('assistant.confirmPendingHint', {}, 'Waiting for you to confirm the action above') : '';
  }

  function setStreamingUI(streaming) {
    sendBtnEl.classList.toggle('tcrt-assistant-stop', streaming);
    sendBtnEl.setAttribute('aria-label', t(streaming ? 'assistant.stop' : 'assistant.send', {}, streaming ? 'Stop' : 'Send'));
    sendBtnEl.disabled = false;
    sendBtnEl.innerHTML = streaming
      ? '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="7" width="10" height="10" rx="1.5"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" stroke-linejoin="round"/></svg>';
  }

  function refreshLockState() {
    lockComposer(turnState === 'streaming' || turnState === 'stopping' || hasUnresolvedConfirm);
  }

  /* ---------------- 訊息渲染 ---------------- */

  function addUserBubble(text) {
    const node = el('<div class="tcrt-assistant-msg tcrt-assistant-user"><div class="tcrt-assistant-bubble"></div></div>');
    node.querySelector('.tcrt-assistant-bubble').textContent = text;
    messagesEl.appendChild(node);
    scrollToBottom();
    return node;
  }

  function addAssistantShell() {
    const node = el('<div class="tcrt-assistant-msg tcrt-assistant-assistant"><div class="tcrt-assistant-bubble"><span class="tcrt-assistant-typing"><i></i><i></i><i></i></span></div></div>');
    messagesEl.appendChild(node);
    scrollToBottom();
    return node;
  }

  function addSysNote(text) {
    const node = el('<div class="tcrt-assistant-sys-note"></div>');
    node.textContent = text;
    messagesEl.appendChild(node);
    scrollToBottom();
  }

  function addScopeNoticeToast() {
    const node = el(`
      <div class="tcrt-assistant-scope-toast" role="status">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/></svg>
        <span><span data-i18n="assistant.scopeNotice">${escapeHtml(t('assistant.scopeNotice', {}, ''))}</span> <span class="tcrt-assistant-warn" data-i18n="assistant.scopeDataEgress">${escapeHtml(t('assistant.scopeDataEgress', {}, ''))}</span></span>
      </div>
    `);
    messagesEl.appendChild(node);
    setTimeout(() => {
      if (!node.isConnected) return; // 已被使用者捲動離開視窗範圍不影響，這裡只處理仍在 DOM 中的情況
      node.classList.add('tcrt-assistant-toast-fade');
      node.addEventListener('transitionend', () => node.remove(), { once: true });
    }, SCOPE_NOTICE_AUTO_DISMISS_MS);
  }

  function ensureToolActivity(assistantNode) {
    const bubble = assistantNode.querySelector('.tcrt-assistant-bubble');
    let act = bubble.querySelector('.tcrt-assistant-tool-activity');
    if (!act) {
      // 有工具活動時，typing 指示應讓位給活動區塊；正式文字仍待 text_delta。
      const typing = bubble.querySelector('.tcrt-assistant-typing');
      if (typing) typing.remove();
      act = el(`<details class="tcrt-assistant-tool-activity" open>${toolActivitySummaryMarkup(t('assistant.activity', {}, 'Running actions'))}</details>`);
      bubble.appendChild(act);
    }
    return act;
  }

  function addToolStep(assistantNode, toolName) {
    const act = ensureToolActivity(assistantNode);
    const actionKey = toolActionI18nKey(toolName);
    const genericAction = t('assistant.unknownAction', {}, 'System action');
    const actionName = t(actionKey, {}, genericAction);
    const executingPrefix = t('assistant.executingPrefix', {}, 'Running:');
    const row = el(`<div class="tcrt-assistant-tool-step" data-tool="${escapeHtml(toolName)}"><span class="tcrt-assistant-st"><span class="tcrt-assistant-spinner"></span></span><span class="tcrt-assistant-desc"><span data-i18n="assistant.executingPrefix">${escapeHtml(executingPrefix)}</span> <span data-i18n="${escapeHtml(actionKey)}">${escapeHtml(actionName)}</span></span></div>`);
    act.appendChild(row);
    if (window.i18n && typeof window.i18n.retranslate === 'function') window.i18n.retranslate(row);
    renderToolResult(act, 'running');
    scrollToBottom();
    return row;
  }

  function resolveToolStep(assistantNode, toolName, ok) {
    const act = ensureToolActivity(assistantNode);
    const rows = act.querySelectorAll(`.tcrt-assistant-tool-step[data-tool="${CSS.escape(toolName)}"]`);
    const row = rows[rows.length - 1] || addToolStep(assistantNode, toolName);
    if (!row || row.classList.contains('tcrt-assistant-ok') || row.classList.contains('tcrt-assistant-fail')) return;
    row.classList.add(ok ? 'tcrt-assistant-ok' : 'tcrt-assistant-fail');
    row.querySelector('.tcrt-assistant-st').textContent = ok ? '✓' : '✕';
    renderToolResult(act, ok ? 'succeeded' : 'failed');
  }

  function discardPendingToolStep(assistantNode) {
    const act = assistantNode.querySelector('.tcrt-assistant-tool-activity');
    if (!act) return;
    const rows = act.querySelectorAll('.tcrt-assistant-tool-step:not(.tcrt-assistant-ok):not(.tcrt-assistant-fail)');
    const row = rows[rows.length - 1];
    if (row) row.remove();
    const statusHost = act.querySelector('.tcrt-assistant-tool-status');
    if (statusHost) statusHost.replaceChildren();
  }

  function failUnresolvedToolSteps(assistantNode) {
    const act = assistantNode.querySelector('.tcrt-assistant-tool-activity');
    if (!act) return;
    const rows = act.querySelectorAll('.tcrt-assistant-tool-step:not(.tcrt-assistant-ok):not(.tcrt-assistant-fail)');
    rows.forEach((row) => {
      row.classList.add('tcrt-assistant-fail');
      row.querySelector('.tcrt-assistant-st').textContent = '✕';
    });
    if (rows.length) renderToolResult(act, 'failed');
  }

  function closeToolActivity(assistantNode) {
    const act = assistantNode.querySelector('.tcrt-assistant-tool-activity');
    if (act && !act.querySelector('.tcrt-assistant-acts')) act.removeAttribute('open');
  }

  function setAssistantText(assistantNode, text) {
    const bubble = assistantNode.querySelector('.tcrt-assistant-bubble');
    const typing = bubble.querySelector('.tcrt-assistant-typing');
    if (typing) typing.remove();
    const textWrap = el('<div class="tcrt-assistant-text"></div>');
    textWrap.innerHTML = renderMarkdown(text);
    bubble.appendChild(textWrap);
    scrollToBottom();
    void ensureMarkdownLibs().then(() => {
      if (mdLibsReady) textWrap.innerHTML = renderMarkdown(text);
    });
  }

  function addErrorBubble(message, retryFn) {
    const node = el(`<div class="tcrt-assistant-error-bubble"><span></span><button type="button" data-i18n="assistant.retry">${escapeHtml(t('assistant.retry', {}, 'Retry'))}</button></div>`);
    node.querySelector('span').textContent = message || t('assistant.errorGeneric', {}, 'Something went wrong');
    node.querySelector('button').addEventListener('click', () => { node.remove(); retryFn && retryFn(); });
    messagesEl.appendChild(node);
    scrollToBottom();
  }

  /* ---------------- 確認卡 ---------------- */

  function buildConfirmCardNode(summary, tier) {
    const actionLabel = confirmationActionLabelMarkup(summary.action, t);
    const targetLine = formatConfirmTargetLine(summary, t);
    const batchTargetList = summary.target_type === 'batch_actions'
      ? formatConfirmTargetList(summary, t) : formatConfirmBatchTargetList(summary);
    const batchInvalid = (summary.target_type === 'batch_actions' || summary.target_type === 'batch') && !batchTargetList;
    if (tier === 'warning') {
      // confirmation_summary 不攜帶 warning_key（那是 registry 端工具定義的屬性，不在送往前端的
      // summary payload 內）；risk_level 本身已能區分 high_impact/irreversible，故直接由它決定文案。
      const warningKey = summary.risk_level === 'irreversible' ? 'assistant.warning.irreversible' : 'assistant.warning.high_impact';
      const warningText = escapeHtml(t(warningKey, {}, ''));
      const confirmKey = summary.risk_level === 'irreversible' ? 'assistant.confirmDelete' : 'assistant.confirm';
      const confirmText = summary.risk_level === 'irreversible' ? 'Confirm delete' : 'Confirm';
      return el(`
        <div class="tcrt-assistant-confirm-card tcrt-assistant-warning" role="group">
          <div class="tcrt-assistant-cc-title">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4M12 17v.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>
            <span data-i18n="assistant.confirmTitle">${escapeHtml(t('assistant.confirmTitle', {}, 'Your confirmation is required'))}</span>
          </div>
          <div class="tcrt-assistant-cc-desc"><strong>${actionLabel}</strong></div>
          <div class="tcrt-assistant-cc-target">${targetLine}${warningText ? ' — ' + warningText : ''}${batchTargetList}</div>
          <div class="tcrt-assistant-acts">
            ${batchInvalid ? '' : `<button class="tcrt-assistant-btn tcrt-assistant-btn-sm tcrt-assistant-btn-danger" type="button" data-act="confirm" data-i18n="${confirmKey}">${escapeHtml(t(confirmKey, {}, confirmText))}</button>`}
            <button class="tcrt-assistant-btn tcrt-assistant-btn-sm tcrt-assistant-btn-outline" type="button" data-act="cancel" data-i18n="assistant.cancel">${escapeHtml(t('assistant.cancel', {}, 'Cancel'))}</button>
          </div>
        </div>
      `);
    }
    return el(`
      <div class="tcrt-assistant-confirm-card tcrt-assistant-light" role="group">
        <div class="tcrt-assistant-cc-desc">${actionLabel}</div>
        <div class="tcrt-assistant-cc-target">${targetLine}${batchTargetList}</div>
        <div class="tcrt-assistant-acts">
          ${batchInvalid ? '' : `<button class="tcrt-assistant-btn tcrt-assistant-btn-sm tcrt-assistant-btn-primary" type="button" data-act="confirm" data-i18n="assistant.confirm">${escapeHtml(t('assistant.confirm', {}, 'Confirm'))}</button>`}
          <button class="tcrt-assistant-btn-text" type="button" data-act="cancel" data-i18n="assistant.cancel">${escapeHtml(t('assistant.cancel', {}, 'Cancel'))}</button>
        </div>
      </div>
    `);
  }

  function settleConfirmCard(card, status) {
    const acts = card.querySelector('.tcrt-assistant-acts');
    if (acts) acts.remove();
    card.removeAttribute('aria-busy');
    card.dataset.status = status;
    const activity = card.closest('.tcrt-assistant-tool-activity');
    if (activity) renderToolResult(activity, confirmStatusOutcome(status), card.dataset.actionId || null);
  }

  function setConfirmSubmitting(card, submitting) {
    card.setAttribute('aria-busy', submitting ? 'true' : 'false');
    card.querySelectorAll('button').forEach((button) => { button.disabled = submitting; });
    const confirmBtn = card.querySelector('[data-act="confirm"]');
    if (confirmBtn) confirmBtn.textContent = submitting
      ? t('assistant.confirmSubmitting', {}, 'Running…')
      : t('assistant.confirm', {}, 'Confirm');
    if (submitting) {
      const activity = card.closest('.tcrt-assistant-tool-activity');
      if (activity) renderToolResult(activity, 'running', card.dataset.actionId || null);
    }
  }

  function renderToolResult(container, outcome, actionId = null) {
    const activity = container.matches && container.matches('.tcrt-assistant-tool-activity')
      ? container
      : (container.querySelector && container.querySelector('.tcrt-assistant-tool-activity'))
        || (container.closest && container.closest('.tcrt-assistant-tool-activity'));
    if (!activity) return null;
    const statusHost = activity.querySelector('.tcrt-assistant-tool-status');
    if (!statusHost) return null;
    const view = toolOutcomeView(outcome);
    const label = t(view.labelKey, {}, view.fallback);
    const icon = el(toolStatusIconMarkup(outcome, actionId, label));
    const existing = actionId == null ? statusHost.querySelector('.tcrt-assistant-tool-result')
      : Array.from(statusHost.querySelectorAll('.tcrt-assistant-tool-result'))
        .find((node) => node.dataset.actionId === String(actionId));
    if (existing) existing.replaceWith(icon);
    else statusHost.replaceChildren(icon);
    if (window.i18n && typeof window.i18n.retranslate === 'function') window.i18n.retranslate(icon);
    scrollToBottom();
    return icon;
  }

  function appendConfirmCard(assistantNode, card, actionId) {
    const activity = ensureToolActivity(assistantNode);
    activity.open = true;
    card.dataset.actionId = String(actionId);
    activity.appendChild(card);
    if (window.i18n && typeof window.i18n.retranslate === 'function') window.i18n.retranslate(card);
    return card;
  }

  function attachConfirmCardHandlers(card, actionId) {
    card.dataset.actionId = String(actionId);
    const confirmBtn = card.querySelector('[data-act="confirm"]');
    const cancelBtn = card.querySelector('[data-act="cancel"]');
    if (confirmBtn) confirmBtn.addEventListener('click', () => void handleConfirmAction(actionId, card));
    if (cancelBtn) cancelBtn.addEventListener('click', () => void handleCancelAction(actionId, card));
  }

  function renderLiveConfirmCard(assistantNode, actionId, summary) {
    const tier = confirmTier(summary.risk_level);
    const card = buildConfirmCardNode(summary, tier);
    appendConfirmCard(assistantNode, card, actionId);
    scrollToBottom();
    hasUnresolvedConfirm = true;
    refreshLockState();
    attachConfirmCardHandlers(card, actionId);
    return card;
  }

  async function handleConfirmAction(actionId, card) {
    const conversationId = currentConversation.id;
    setConfirmSubmitting(card, true);
    const result = await streamToNewBubble(`/api/assistant/conversations/${conversationId}/actions/${actionId}/confirm`, { method: 'POST' });
    if (
      !currentConversation
      || currentConversation.id !== conversationId
      || !result
      || result.generation !== streamGeneration
    ) return;
    const nextState = confirmActionUiState('submitting', result && result.outcome ? result.outcome : 'api_error');
    if (nextState === 'actionable') {
      const data = await fetchJson(`/api/assistant/conversations/${conversationId}/messages`);
      if (!currentConversation || currentConversation.id !== conversationId || result.generation !== streamGeneration) return;
      if (data) renderHistoryMessages(historyItemsForSnapshot(data));
      else setConfirmSubmitting(card, false);
      if (data && data.active_turn) {
        await resumeActiveTurn(currentConversation, data.active_turn.turn_key);
        return;
      }
    } else if (nextState === 'unknown') {
      settleConfirmCard(card, 'unknown');
    } else {
      settleConfirmCard(card, nextState);
    }
    hasUnresolvedConfirm = confirmComposerShouldLock(messagesEl.querySelectorAll('.tcrt-assistant-acts').length);
    refreshLockState();
  }

  async function handleCancelAction(actionId, card) {
    const conversationId = currentConversation.id;
    const generation = streamGeneration;
    try {
      const resp = await window.AuthClient.fetch(`/api/assistant/conversations/${conversationId}/actions/${actionId}/cancel`, { method: 'POST' });
      if (!currentConversation || currentConversation.id !== conversationId || generation !== streamGeneration) return;
      if (resp.ok) {
        settleConfirmCard(card, 'cancelled');
        hasUnresolvedConfirm = false;
      } else {
        await showApiError(resp);
        const data = await fetchJson(`/api/assistant/conversations/${conversationId}/messages`);
        if (!currentConversation || currentConversation.id !== conversationId || generation !== streamGeneration) return;
        if (data) renderHistoryMessages(historyItemsForSnapshot(data));
        if (data && data.active_turn) {
          await resumeActiveTurn(currentConversation, data.active_turn.turn_key);
          return;
        }
        hasUnresolvedConfirm = !!messagesEl.querySelector('.tcrt-assistant-acts');
      }
    } catch (e) {
      if (!currentConversation || currentConversation.id !== conversationId || generation !== streamGeneration) return;
      await showApiError(null, e);
      const data = await fetchJson(`/api/assistant/conversations/${conversationId}/messages`);
      if (!currentConversation || currentConversation.id !== conversationId || generation !== streamGeneration) return;
      if (data) renderHistoryMessages(historyItemsForSnapshot(data));
      if (data && data.active_turn) {
        await resumeActiveTurn(currentConversation, data.active_turn.turn_key);
        return;
      }
      hasUnresolvedConfirm = !!messagesEl.querySelector('.tcrt-assistant-acts');
    }
    refreshLockState();
  }

  /* ---------------- SSE 串流處理 ---------------- */

  function errorCodeToMessage(code, fallback) {
    const map = {
      MESSAGE_TOO_LONG: 'assistant.errorMessageTooLong',
      TOO_MANY_ATTACHMENTS: 'assistant.errorTooManyAttachments',
      ADMISSION_DENIED: 'assistant.errorAdmissionDenied',
      CONFIRMATION_STALE: 'assistant.errorConfirmationStale',
      CONVERSATION_NOT_FOUND: 'assistant.errorNotFound',
      PENDING_ACTION_NOT_FOUND: 'assistant.errorNotFound',
      PENDING_ACTION_NOT_CLAIMABLE: 'assistant.errorNotFound',
    };
    const key = map[code];
    return key ? t(key, {}, fallback) : (fallback || t('assistant.errorGeneric', {}, 'Something went wrong'));
  }

  async function showApiError(resp, exc) {
    let message = t('assistant.errorGeneric', {}, 'Something went wrong');
    if (resp) {
      try {
        const body = await resp.json();
        const detail = body && body.detail;
        if (detail && detail.code) message = errorCodeToMessage(detail.code, detail.message);
        else if (typeof detail === 'string') message = detail;
      } catch (e) { /* ignore */ }
    } else if (exc) {
      message = t('assistant.connectionLost', {}, 'Connection lost, reconnecting…');
    }
    if (window.AppUtils && typeof window.AppUtils.showError === 'function') window.AppUtils.showError(message);
    else addSysNote(message);
  }

  function setInflightMarker(turnKey, conversationId) {
    const id = conversationId || (currentConversation && currentConversation.id);
    if (!id) return;
    if (turnKey) localStorage.setItem(INFLIGHT_KEY_PREFIX + id, turnKey);
    else localStorage.removeItem(INFLIGHT_KEY_PREFIX + id);
  }

  /** 消化單一 SSE 事件，更新 UI；回傳 true 代表本次事件為 turn 的終結事件。 */
  function ensureAssistantNode(assistantNodeRef) {
    if (!assistantNodeRef.node || !assistantNodeRef.node.isConnected) assistantNodeRef.node = addAssistantShell();
    return assistantNodeRef.node;
  }

  function findConfirmCard(actionId) {
    if (actionId == null) return null;
    return messagesEl.querySelector(`.tcrt-assistant-confirm-card[data-action-id="${CSS.escape(String(actionId))}"]`);
  }

  function dispatchEvent(assistantNodeRef, evt) {
    if (
      !currentConversation
      || assistantNodeRef.conversationId !== currentConversation.id
      || assistantNodeRef.generation !== streamGeneration
    ) return true;
    const parsedId = parseSseEventId(evt.id);
    if (parsedId) {
      if (assistantNodeRef.turnKey === parsedId.turnKey && parsedId.seq <= assistantNodeRef.eventSeq) return false;
      if (currentTurnKey !== parsedId.turnKey) setInflightMarker(parsedId.turnKey);
      assistantNodeRef.turnKey = parsedId.turnKey;
      assistantNodeRef.eventSeq = parsedId.seq;
      currentTurnKey = parsedId.turnKey;
      currentEventSeq = parsedId.seq;
    }

    if (evt.type === 'message_start') {
      turnState = turnStateReducer(turnState, { type: 'start' });
      setStreamingUI(true);
      return false;
    }
    if (evt.type === 'text_delta') {
      const content = evt.payload && evt.payload.content != null ? evt.payload.content : '';
      setAssistantText(ensureAssistantNode(assistantNodeRef), content);
      return false;
    }
    if (evt.type === 'tool_started') {
      const p = evt.payload || {};
      if (toolEventPresentation(evt.type, p) === 'status') {
        const sourceCard = findConfirmCard(p.action_id);
        if (sourceCard) {
          renderToolResult(sourceCard, 'running', p.action_id);
        } else {
          const node = ensureAssistantNode(assistantNodeRef);
          renderToolResult(ensureToolActivity(node), 'running', p.action_id);
        }
      } else if (p.tool_name) {
        addToolStep(ensureAssistantNode(assistantNodeRef), p.tool_name);
      }
      return false;
    }
    if (evt.type === 'tool_finished') {
      const p = evt.payload || {};
      if (toolEventPresentation(evt.type, p) === 'status') {
        assistantNodeRef.lastToolOutcome = p.outcome;
        const sourceCard = findConfirmCard(p.action_id);
        if (sourceCard) settleConfirmCard(sourceCard, p.outcome === 'succeeded' ? 'confirmed' : p.outcome);
        else renderToolResult(ensureToolActivity(ensureAssistantNode(assistantNodeRef)), p.outcome, p.action_id);
      } else if (p.tool_name) {
        resolveToolStep(ensureAssistantNode(assistantNodeRef), p.tool_name, p.ok !== false);
      }
      return false;
    }
    if (evt.type === 'confirmation_required') {
      const p = evt.payload || {};
      if (p.summary) {
        const node = ensureAssistantNode(assistantNodeRef);
        discardPendingToolStep(node);
        renderLiveConfirmCard(node, p.action_id, p.summary);
      }
      return false;
    }
    if (evt.type === 'error') {
      turnState = turnStateReducer(turnState, { type: 'event', eventType: 'error' });
      if (assistantNodeRef.node) {
        failUnresolvedToolSteps(assistantNodeRef.node);
        closeToolActivity(assistantNodeRef.node);
      }
      addErrorBubble((evt.payload && evt.payload.message) || null, null);
      return true;
    }
    if (evt.type === 'done') {
      turnState = turnStateReducer(turnState, { type: 'event', eventType: 'done' });
      if (assistantNodeRef.node) closeToolActivity(assistantNodeRef.node);
      return true;
    }
    if (evt.type === 'cancelled') {
      turnState = turnStateReducer(turnState, { type: 'event', eventType: 'cancelled' });
      if (assistantNodeRef.node) closeToolActivity(assistantNodeRef.node);
      composerEl.classList.remove('tcrt-assistant-stopping');
      addSysNote(t('assistant.cancelledNote', {}, 'Cancelled — the action already in progress finished normally; no further steps were started'));
      return true;
    }
    return false;
  }

  async function pumpStream(response, assistantNodeRef) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let terminal = false;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      const { events, remainder } = parseSSEChunk(buffer, decoder.decode(value, { stream: true }));
      buffer = remainder;
      for (const evt of events) {
        if (dispatchEvent(assistantNodeRef, evt)) terminal = true;
      }
    }
    return terminal;
  }

  async function streamWithReconnect(initialResponse, assistantNodeRef, signal) {
    const conversationId = assistantNodeRef.conversationId;
    let response = initialResponse;
    let attempts = 0;
    for (;;) {
      let terminal = false;
      try {
        terminal = await pumpStream(response, assistantNodeRef);
      } catch (e) {
        terminal = false;
      }
      if (terminal) break;
      attempts += 1;
      if (
        attempts > RECONNECT_MAX_ATTEMPTS
        || !currentConversation
        || currentConversation.id !== conversationId
        || assistantNodeRef.generation !== streamGeneration
        || !assistantNodeRef.turnKey
      ) {
        showApiError(null, new Error('stream ended unexpectedly'));
        break;
      }
      await new Promise((r) => setTimeout(r, Math.min(1000 * attempts, 3000)));
      try {
        response = await window.AuthClient.fetch(
          `/api/assistant/conversations/${conversationId}/turns/${assistantNodeRef.turnKey}/events?after_seq=${assistantNodeRef.eventSeq}`,
          { signal }
        );
        if (!response.ok) break;
      } catch (e) {
        break;
      }
    }
    if (
      currentConversation
      && currentConversation.id === conversationId
      && assistantNodeRef.generation === streamGeneration
    ) {
      turnState = 'idle';
      setStreamingUI(false);
      hasUnresolvedConfirm = !!(messagesEl && messagesEl.querySelector('.tcrt-assistant-acts'));
      refreshLockState();
      setInflightMarker(null, conversationId);
    }
    return {
      terminal: turnState === 'idle',
      outcome: assistantNodeRef.lastToolOutcome || null,
      generation: assistantNodeRef.generation,
    };
  }

  async function streamToNewBubble(url, fetchOptions) {
    const assistantNodeRef = {
      node: null,
      conversationId: currentConversation.id,
      generation: ++streamGeneration,
      turnKey: null,
      eventSeq: -1,
    };
    const controller = new AbortController();
    activeAbortController = controller;
    lockComposer(true);
    try {
      const resp = await window.AuthClient.fetch(url, { ...(fetchOptions || {}), signal: controller.signal });
      if (!resp.ok || !resp.body) {
        await showApiError(resp);
        lockComposer(false);
        return { outcome: null, generation: assistantNodeRef.generation };
      }
      if (
        !currentConversation
        || currentConversation.id !== assistantNodeRef.conversationId
        || assistantNodeRef.generation !== streamGeneration
      ) return { outcome: null, generation: assistantNodeRef.generation };
      assistantNodeRef.turnKey = resp.headers.get('X-TCRT-Turn-Key') || currentTurnKey;
      assistantNodeRef.eventSeq = -1;
      currentTurnKey = assistantNodeRef.turnKey;
      currentEventSeq = -1;
      if (currentTurnKey) setInflightMarker(currentTurnKey);
      return await streamWithReconnect(resp, assistantNodeRef, controller.signal);
    } catch (e) {
      if (e.name !== 'AbortError') await showApiError(null, e);
      lockComposer(false);
      return { outcome: null, generation: assistantNodeRef.generation };
    } finally {
      if (activeAbortController === controller) activeAbortController = null;
    }
  }

  /* ---------------- 送出 / 停止 ---------------- */

  async function sendMessage() {
    if (!currentConversation) return;
    const text = inputEl.value.trim();
    if (!text && selectedFiles.length === 0) return;
    if (turnState === 'streaming' || turnState === 'stopping') return;

    const clientMessageId = randomId();
    inputEl.value = '';
    inputEl.style.height = '';
    addUserBubble(text);

    const form = new FormData();
    form.append('text', text);
    form.append('client_message_id', clientMessageId);
    selectedFiles.forEach((f) => form.append('attachments', f, f.name));
    clearAttachments();

    const assistantNodeRef = {
      node: null,
      conversationId: currentConversation.id,
      generation: ++streamGeneration,
      turnKey: null,
      eventSeq: -1,
    };
    const controller = new AbortController();
    activeAbortController = controller;
    lockComposer(true);
    setInflightMarker('pending');
    try {
      const resp = await window.AuthClient.fetch(
        `/api/assistant/conversations/${currentConversation.id}/messages`,
        { method: 'POST', body: form, signal: controller.signal }
      );
      if (!resp.ok || !resp.body) {
        await showApiError(resp);
        lockComposer(false);
        return;
      }
      if (
        !currentConversation
        || currentConversation.id !== assistantNodeRef.conversationId
        || assistantNodeRef.generation !== streamGeneration
      ) return;
      assistantNodeRef.turnKey = resp.headers.get('X-TCRT-Turn-Key') || currentTurnKey;
      assistantNodeRef.eventSeq = -1;
      currentTurnKey = assistantNodeRef.turnKey;
      currentEventSeq = -1;
      if (currentTurnKey) setInflightMarker(currentTurnKey);
      assistantNodeRef.node = addAssistantShell();
      await streamWithReconnect(resp, assistantNodeRef, controller.signal);
    } catch (e) {
      if (e.name !== 'AbortError') await showApiError(null, e);
      lockComposer(false);
    } finally {
      if (activeAbortController === controller) activeAbortController = null;
    }
  }

  async function stopCurrentTurn() {
    if (!currentConversation || !currentTurnKey) return;
    turnState = turnStateReducer(turnState, { type: 'stopRequested' });
    composerEl.classList.add('tcrt-assistant-stopping');
    setStreamingUI(false);
    sendBtnEl.disabled = true;
    try {
      await window.AuthClient.fetch(
        `/api/assistant/conversations/${currentConversation.id}/turns/${currentTurnKey}/stop`,
        { method: 'POST' }
      );
    } catch (e) { /* SSE stream will still resolve via reconnect/terminal event or timeout */ }
  }

  function handleSendOrStop() {
    if (turnState === 'streaming') { void stopCurrentTurn(); return; }
    void sendMessage();
  }

  /* ---------------- 附件 ---------------- */

  function renderAttachChips() {
    attachChipEl.innerHTML = '';
    attachChipEl.classList.toggle('tcrt-assistant-show', selectedFiles.length > 0);
    selectedFiles.forEach((f, idx) => {
      const chip = el(`<span style="display:inline-flex;align-items:center;gap:6px;"><span></span><button type="button" data-i18n-aria-label="assistant.removeAttachment" aria-label="${escapeHtml(t('assistant.removeAttachment', {}, 'Remove attachment'))}">✕</button></span>`);
      chip.querySelector('span').textContent = `📎 ${f.name}`;
      chip.querySelector('button').addEventListener('click', () => { selectedFiles.splice(idx, 1); renderAttachChips(); });
      attachChipEl.appendChild(chip);
    });
  }

  function clearAttachments() {
    selectedFiles = [];
    renderAttachChips();
  }

  /* ---------------- 對話管理 ---------------- */

  function conversationStorageKey(teamId) {
    return CONV_KEY_PREFIX + (teamId != null ? 'team_' + teamId : 'global');
  }

  function rememberConversation(teamId, conversationId) {
    localStorage.setItem(conversationStorageKey(teamId), String(conversationId));
  }

  function recalledConversationId(teamId) {
    const raw = localStorage.getItem(conversationStorageKey(teamId));
    return raw ? parseInt(raw, 10) : null;
  }

  async function fetchJson(url, options) {
    const resp = await window.AuthClient.fetch(url, options);
    if (!resp.ok) { await showApiError(resp); return null; }
    if (resp.status === 204) return {};
    return resp.json();
  }

  async function createConversation(teamId) {
    const body = teamId != null ? { scope_type: 'team', team_id: teamId } : { scope_type: 'global' };
    return fetchJson('/api/assistant/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  }

  async function listRelevantConversations(teamId) {
    const data = await fetchJson('/api/assistant/conversations?limit=20');
    if (!data) return [];
    return data.filter((c) => (teamId != null ? c.team_id === teamId : c.scope_type === 'global'));
  }

  function renderTeamBadge() {
    if (!teamBadgeEl) return;
    const team = window.AppUtils && window.AppUtils.getCurrentTeam && window.AppUtils.getCurrentTeam();
    teamBadgeEl.textContent = team ? team.name : '';
    teamBadgeEl.style.display = team ? '' : 'none';
  }

  async function refreshHistoryMenu() {
    const teamId = getCurrentTeamId() ? parseInt(getCurrentTeamId(), 10) : null;
    const list = root.querySelector('#tcrt-assistant-hm-list');
    const titleEl = root.querySelector('#tcrt-assistant-hm-title');
    const team = window.AppUtils && window.AppUtils.getCurrentTeam && window.AppUtils.getCurrentTeam();
    titleEl.textContent = t('assistant.historyTitle', { team: team ? team.name : '' }, 'Recent conversations');
    list.innerHTML = '';
    const conversations = await listRelevantConversations(teamId);
    if (!conversations.length) {
      list.appendChild(el(`<div class="tcrt-assistant-hm-empty" data-i18n="assistant.historyEmpty">${escapeHtml(t('assistant.historyEmpty', {}, 'No recent conversations'))}</div>`));
      return;
    }
    conversations.forEach((c) => {
      const row = el(`
        <div class="tcrt-assistant-hm-row">
          <button class="tcrt-assistant-hm-item" type="button">
            <span class="tcrt-assistant-t"></span>
            <span class="tcrt-assistant-m"></span>
          </button>
          <button class="tcrt-assistant-hm-delete" type="button" data-i18n-aria-label="assistant.confirmDelete" aria-label="${escapeHtml(t('assistant.confirmDelete', {}, 'Delete'))}">✕</button>
        </div>
      `);
      row.querySelector('.tcrt-assistant-t').textContent = c.title || c.conversation_key.slice(0, 8);
      row.querySelector('.tcrt-assistant-m').textContent = new Date(c.last_message_at).toLocaleString();
      row.querySelector('.tcrt-assistant-hm-item').addEventListener('click', () => {
        closeHistoryMenu();
        void loadConversation(c, teamId);
      });
      row.querySelector('.tcrt-assistant-hm-delete').addEventListener('click', async (ev) => {
        ev.stopPropagation();
        if (!window.confirm(t('assistant.deleteConversationConfirm', {}, 'Delete this conversation? This cannot be undone.'))) return;
        const resp = await window.AuthClient.fetch(`/api/assistant/conversations/${c.id}`, { method: 'DELETE' });
        if (resp.ok || resp.status === 204) {
          if (currentConversation && currentConversation.id === c.id) await switchToTeamConversation(true);
          await refreshHistoryMenu();
        } else {
          await showApiError(resp);
        }
      });
      list.appendChild(row);
    });
  }

  function renderHistoryMessages(items) {
    messagesEl.innerHTML = '';
    if (!items.length) {
      addScopeNoticeToast();
      const node = addAssistantShell();
      setAssistantText(node, t('assistant.emptyState', {}, "Hi, I'm the TCRT Assistant."));
      return;
    }
    let lastAssistantNode = null;
    let lastTurnKey = null;
    const activityByCallId = new Map();
    items.forEach((m) => {
      if (m.turn_key !== lastTurnKey) {
        lastAssistantNode = null;
        lastTurnKey = m.turn_key;
      }
      if (m.role === 'user') {
        addUserBubble(m.content || '');
        lastAssistantNode = null;
        return;
      }
      if (m.role === 'assistant') {
        if (m.pending_action) {
          const node = lastAssistantNode || addAssistantShell();
          const mode = pendingActionRenderMode(m.pending_action.status);
          const tier = confirmTier(m.pending_action.confirmation_summary && m.pending_action.confirmation_summary.risk_level);
          const card = buildConfirmCardNode(m.pending_action.confirmation_summary || {}, tier);
          appendConfirmCard(node, card, m.pending_action.action_id);
          if (mode === 'unknown') {
            settleConfirmCard(card, 'unknown');
          } else if (mode === 'executing') {
            settleConfirmCard(card, 'executing');
          } else {
            if (mode === 'actionable') attachConfirmCardHandlers(card, m.pending_action.action_id);
            else settleConfirmCard(card, m.pending_action.status);
          }
          if (m.llm_tool_call_id) activityByCallId.set(m.llm_tool_call_id, node);
          lastAssistantNode = node;
          return;
        }
        if (m.tool_calls && m.tool_calls.length) {
          const node = lastAssistantNode || addAssistantShell();
          const bubble = node.querySelector('.tcrt-assistant-bubble');
          const typing = bubble.querySelector('.tcrt-assistant-typing');
          if (typing) typing.remove();
          m.tool_calls.forEach((call) => {
            addToolStep(node, call.name);
          });
          lastAssistantNode = node;
          return;
        }
        if (m.content) {
          const node = addAssistantShell();
          setAssistantText(node, m.content);
          lastAssistantNode = node;
        }
      }
      if (m.role === 'tool') {
        const outcome = m.tool_outcome || (m.tool_result && m.tool_result.status === 'error' ? 'failed' : null);
        if (!outcome) return;
        const sourceNode = m.llm_tool_call_id ? activityByCallId.get(m.llm_tool_call_id) : null;
        const node = sourceNode || lastAssistantNode || addAssistantShell();
        const matchingSteps = m.tool_name
          ? node.querySelectorAll(`.tcrt-assistant-tool-step[data-tool="${CSS.escape(m.tool_name)}"]`)
          : [];
        if (matchingSteps.length) resolveToolStep(node, m.tool_name, outcome === 'succeeded');
        renderToolResult(ensureToolActivity(node), outcome);
        if (!sourceNode) lastAssistantNode = node;
      }
    });
    scrollToBottom();
  }

  function historyItemsForSnapshot(data) {
    const messages = data && Array.isArray(data.messages) ? data.messages : [];
    const activeTurn = data && data.active_turn ? data.active_turn : null;
    return messages.filter((message) => !(
      activeTurn && message.turn_key === activeTurn.turn_key && message.role !== 'user'
    ));
  }

  async function resumeActiveTurn(conversation, turnKey) {
    currentTurnKey = turnKey;
    currentEventSeq = -1;
    setInflightMarker(turnKey, conversation.id);
    const assistantNodeRef = {
      node: null,
      conversationId: conversation.id,
      generation: ++streamGeneration,
      turnKey,
      eventSeq: -1,
    };
    const controller = new AbortController();
    activeAbortController = controller;
    try {
      const resp = await window.AuthClient.fetch(
        `/api/assistant/conversations/${conversation.id}/turns/${turnKey}/events?after_seq=-1`,
        { signal: controller.signal }
      );
      if (resp.ok && resp.body) await streamWithReconnect(resp, assistantNodeRef, controller.signal);
      else if (assistantNodeRef.node) assistantNodeRef.node.remove();
    } catch (e) {
      if (assistantNodeRef.node) assistantNodeRef.node.remove();
    } finally {
      if (activeAbortController === controller) activeAbortController = null;
    }
  }

  async function loadConversation(conversation, teamId) {
    if (activeAbortController) activeAbortController.abort();
    streamGeneration += 1;
    currentConversation = conversation;
    currentTurnKey = null;
    currentEventSeq = -1;
    turnState = 'idle';
    hasUnresolvedConfirm = false;
    rememberConversation(teamId, conversation.id);
    const data = await fetchJson(`/api/assistant/conversations/${conversation.id}/messages`);
    let inflightKey = localStorage.getItem(INFLIGHT_KEY_PREFIX + conversation.id);
    const activeTurn = data && data.active_turn ? data.active_turn : null;
    inflightKey = authoritativeInflightKey(inflightKey, activeTurn);
    const historyItems = historyItemsForSnapshot(data);
    renderHistoryMessages(historyItems);
    const pendingCards = messagesEl.querySelectorAll('.tcrt-assistant-acts');
    hasUnresolvedConfirm = pendingCards.length > 0;
    refreshLockState();

    if (inflightKey && activeTurn && inflightKey === activeTurn.turn_key) {
      await resumeActiveTurn(conversation, inflightKey);
    } else if (inflightKey) {
      setInflightMarker(null, conversation.id);
    }
  }

  async function switchToTeamConversation(forceNew) {
    const teamIdRaw = getCurrentTeamId();
    const teamId = teamIdRaw ? parseInt(teamIdRaw, 10) : null;
    renderTeamBadge();
    let conversation = null;
    if (!forceNew) {
      const recalledId = recalledConversationId(teamId);
      if (recalledId) {
        const list = await listRelevantConversations(teamId);
        conversation = list.find((c) => c.id === recalledId) || null;
      }
    }
    if (!conversation) conversation = await createConversation(teamId);
    if (conversation) await loadConversation(conversation, teamId);
  }

  async function newConversation() {
    if (currentConversation && currentTurnKey && (turnState === 'streaming' || turnState === 'stopping')) {
      await stopCurrentTurn();
    }
    await switchToTeamConversation(true);
  }

  async function onTeamChanged() {
    if (currentTurnKey && (turnState === 'streaming' || turnState === 'stopping')) {
      await stopCurrentTurn();
      addSysNote(t('assistant.teamSwitched', {}, 'Switched teams — the in-progress turn was stopped'));
    }
    await switchToTeamConversation(false);
  }

  /* ---------------- 事件綁定 ---------------- */

  function autoResizeInput() {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 96) + 'px';
  }

  function wireEvents() {
    fabEl.addEventListener('click', togglePanel);
    root.querySelector('#tcrt-assistant-close-btn').addEventListener('click', closePanel);
    root.querySelector('#tcrt-assistant-history-btn').addEventListener('click', toggleHistoryMenu);
    root.querySelector('#tcrt-assistant-new-btn').addEventListener('click', () => { closeHistoryMenu(); void newConversation(); });
    root.querySelector('#tcrt-assistant-hm-new-btn').addEventListener('click', () => { closeHistoryMenu(); void newConversation(); });
    sendBtnEl.addEventListener('click', handleSendOrStop);
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); handleSendOrStop(); }
    });
    inputEl.addEventListener('input', autoResizeInput);

    const attachBtn = root.querySelector('#tcrt-assistant-attach-btn');
    const fileInput = root.querySelector('#tcrt-assistant-file-input');
    attachBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => {
      selectedFiles = selectedFiles.concat(Array.from(fileInput.files || []));
      fileInput.value = '';
      renderAttachChips();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (historyMenuEl && historyMenuEl.classList.contains('tcrt-assistant-show')) { closeHistoryMenu(); return; }
      if (isOpen()) closePanel();
    });

    document.addEventListener('click', (e) => {
      if (!historyMenuEl || !historyMenuEl.classList.contains('tcrt-assistant-show')) return;
      if (historyMenuEl.contains(e.target) || root.querySelector('#tcrt-assistant-history-btn').contains(e.target)) return;
      closeHistoryMenu();
    });

    window.addEventListener('teamChanged', () => void onTeamChanged());
    window.addEventListener('teamCleared', () => void onTeamChanged());
    document.addEventListener('i18nReady', () => { if (mounted && window.i18n) window.i18n.retranslate(root); });
    document.addEventListener('languageChanged', () => { if (mounted && window.i18n) window.i18n.retranslate(root); });
    document.addEventListener('logout', () => destroy());
  }

  /* ---------------- 啟動 ---------------- */

  async function init() {
    if (!(await checkAvailability())) return;
    mount();
  }

  document.addEventListener('DOMContentLoaded', () => { void init(); });
  window.addEventListener('storage', (e) => {
    if (e.key === AVAILABILITY_CACHE_KEY) return;
  });

  return {
    init,
    destroy,
    mount,
    isOpen,
    openPanel,
    closePanel,
  };
})();

window.AssistantWidget = AssistantWidget;
