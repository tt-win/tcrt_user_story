/**
 * Council Inspection Animation Module
 *
 * Provides the overlay that visualises the multi-perspective parallel
 * extraction phase (AI #1 / AI #2 / AI #3) followed by the
 * consolidation phase. Communicates with the backend via SSE.
 *
 * Public API (attached to window.CouncilAnimation):
 *   start(teamId, sessionId, { authFetch, onDone, onError, t })
 *   cancel()
 */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ */
  /*  Constants                                                          */
  /* ------------------------------------------------------------------ */

  // key = model_label from backend ("A", "B", "C")
  const ROLES = [
    { key: 'A', code: 'AI #1', label: 'AI #1' },
    { key: 'B', code: 'AI #2', label: 'AI #2' },
    { key: 'C', code: 'AI #3', label: 'AI #3' },
  ];

  const STATUS = { IDLE: 'idle', RUNNING: 'running', DONE: 'done', ERROR: 'error' };

  /* ------------------------------------------------------------------ */
  /*  Module state                                                       */
  /* ------------------------------------------------------------------ */

  let _overlay = null;
  let _abortController = null;
  let _opts = {};          // { authFetch, onDone, onError, t }
  let _phase = 1;          // 1 = extraction, 2 = consolidation
  let _roleStatus = {};    // { role_a: STATUS, ... }

  /* ------------------------------------------------------------------ */
  /*  Helpers                                                            */
  /* ------------------------------------------------------------------ */

  function t(key, params, fallback) {
    if (_opts.t) return _opts.t(key, params, fallback);
    return fallback || key;
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  /* ------------------------------------------------------------------ */
  /*  DOM construction                                                   */
  /* ------------------------------------------------------------------ */

  function buildOverlay() {
    const overlay = document.createElement('div');
    overlay.className = 'council-overlay';
    overlay.innerHTML = `
      <div class="council-container">
        <div class="council-header">
          <div class="council-title">COUNCIL REVIEW</div>
          <div class="council-subtitle" id="councilSubtitle">${escapeHtml(t('qaAiHelper.councilPhase1', {}, 'Phase 1 — Parallel Extraction'))}</div>
        </div>
        <div class="council-panels" id="councilPanels">
          ${ROLES.map(r => `
          <div class="council-panel" data-role="${r.key}" id="councilPanel_${r.key}">
            <div class="council-panel-header">
              <span class="council-panel-code">${r.code}</span>
              <span class="council-indicator council-indicator--idle" id="councilInd_${r.key}"></span>
            </div>
            <div class="council-panel-label">${r.label}</div>
            <div class="council-panel-status" id="magcouncilStatus_${r.key}">${escapeHtml(t('qaAiHelper.councilIdle', {}, 'STANDBY'))}</div>
          </div>`).join('')}
        </div>
        <div class="council-consolidation" id="councilConsolidation" style="display:none;">
          <div class="council-consolidation-label">${escapeHtml(t('qaAiHelper.councilConsolidation', {}, 'Phase 2 — Consolidation'))}</div>
          <div class="council-consolidation-status" id="councilConsolidationStatus">${escapeHtml(t('qaAiHelper.councilRunning', {}, 'PROCESSING...'))}</div>
        </div>
        <div class="council-verdict" id="councilVerdict" style="display:none;">
          <span class="council-verdict-text" id="councilVerdictText"></span>
        </div>
        <div class="council-footer">
          <button type="button" class="btn btn-outline-light btn-sm council-cancel-btn" id="councilCancelBtn">
            <i class="fas fa-xmark me-1"></i>${escapeHtml(t('qaAiHelper.councilCancel', {}, '取消'))}
          </button>
        </div>
      </div>`;
    return overlay;
  }

  function mount() {
    if (_overlay) return;
    _overlay = buildOverlay();
    document.body.appendChild(_overlay);
    requestAnimationFrame(() => _overlay.classList.add('is-visible'));
    const cancelBtn = _overlay.querySelector('#councilCancelBtn');
    if (cancelBtn) cancelBtn.addEventListener('click', cancel);
  }

  function unmount() {
    if (!_overlay) return;
    _overlay.classList.remove('is-visible');
    setTimeout(() => { if (_overlay) { _overlay.remove(); _overlay = null; } }, 350);
  }

  /* ------------------------------------------------------------------ */
  /*  Panel updates                                                      */
  /* ------------------------------------------------------------------ */

  function setRoleStatus(roleKey, status, detail) {
    _roleStatus[roleKey] = status;
    const ind = document.getElementById('councilInd_' + roleKey);
    const statusEl = document.getElementById('magcouncilStatus_' + roleKey);
    const panel = document.getElementById('councilPanel_' + roleKey);
    if (ind) {
      ind.className = 'council-indicator council-indicator--' + status;
    }
    if (panel) {
      panel.setAttribute('data-status', status);
    }
    if (statusEl) {
      const labels = {
        [STATUS.IDLE]: t('qaAiHelper.councilIdle', {}, 'STANDBY'),
        [STATUS.RUNNING]: t('qaAiHelper.councilRunning', {}, 'PROCESSING...'),
        [STATUS.DONE]: t('qaAiHelper.councilDone', {}, 'COMPLETE'),
        [STATUS.ERROR]: detail || t('qaAiHelper.councilError', {}, 'ERROR'),
      };
      statusEl.textContent = labels[status] || status;
    }
  }

  function transitionToPhase2() {
    _phase = 2;
    const subtitle = document.getElementById('councilSubtitle');
    if (subtitle) subtitle.textContent = t('qaAiHelper.councilPhase2', {}, 'Phase 2 — Consolidation');
    const panels = document.getElementById('councilPanels');
    if (panels) panels.classList.add('council-panels--shrink');
    const consol = document.getElementById('councilConsolidation');
    if (consol) consol.style.display = '';
  }

  function showVerdict(success, message) {
    const verdict = document.getElementById('councilVerdict');
    const text = document.getElementById('councilVerdictText');
    if (!verdict || !text) return;
    verdict.style.display = '';
    verdict.classList.add(success ? 'council-verdict--ok' : 'council-verdict--fail');
    text.textContent = message || (success
      ? t('qaAiHelper.councilAllApproved', {}, 'ALL APPROVED')
      : t('qaAiHelper.councilFailed', {}, 'INSPECTION FAILED'));
    // hide cancel button
    const cancelBtn = document.getElementById('councilCancelBtn');
    if (cancelBtn) cancelBtn.style.display = 'none';
  }

  /* ------------------------------------------------------------------ */
  /*  SSE connection                                                     */
  /* ------------------------------------------------------------------ */

  async function connectSSE(teamId, sessionId) {
    _abortController = new AbortController();
    const url = `/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}/council-inspection`;

    // We need POST + streaming, so use fetch (not EventSource)
    const fetchFn = _opts.authFetch || fetch;
    let response;
    try {
      response = await fetchFn(url, {
        method: 'POST',
        headers: { 'Accept': 'text/event-stream' },
        signal: _abortController.signal,
      });
    } catch (err) {
      if (err.name === 'AbortError') return;
      throw err;
    }

    if (!response.ok) {
      const body = await response.text().catch(() => '');
      throw new Error(body || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      let result;
      try {
        result = await reader.read();
      } catch (err) {
        if (err.name === 'AbortError') return;
        throw err;
      }
      if (result.done) break;

      buffer += decoder.decode(result.value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let eventType = '';
      let dataLines = [];
      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trim());
        } else if (line === '') {
          if (eventType && dataLines.length) {
            handleSSEEvent(eventType, dataLines.join('\n'));
          }
          eventType = '';
          dataLines = [];
        }
      }
    }
  }

  function handleSSEEvent(event, rawData) {
    let data = {};
    try { data = JSON.parse(rawData); } catch (_) { /* ignore */ }

    switch (event) {
      case 'extraction_start':
        setRoleStatus(data.model_label || '', STATUS.RUNNING);
        break;
      case 'extraction_complete':
        setRoleStatus(data.model_label || '', STATUS.DONE);
        break;
      case 'extraction_error':
        setRoleStatus(data.model_label || '', STATUS.ERROR, data.error || '');
        break;
      case 'phase_change':
        if (data.phase === 'consolidation' || data.phase === 2) transitionToPhase2();
        break;
      case 'consolidation_complete': {
        const consolStatus = document.getElementById('councilConsolidationStatus');
        if (consolStatus) consolStatus.textContent = t('qaAiHelper.councilDone', {}, 'COMPLETE');
        break;
      }
      case 'consolidation_error': {
        const consolStatus = document.getElementById('councilConsolidationStatus');
        if (consolStatus) consolStatus.textContent = data.error || t('qaAiHelper.councilError', {}, 'ERROR');
        showVerdict(false, data.error);
        break;
      }
      case 'done':
        showVerdict(true);
        setTimeout(() => {
          unmount();
          if (_opts.onDone) _opts.onDone(data);
        }, 1200);
        break;
      case 'error':
        showVerdict(false, data.error);
        setTimeout(() => {
          unmount();
          if (_opts.onError) _opts.onError(data.error || 'Unknown error');
        }, 2000);
        break;
      default:
        break;
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Public API                                                         */
  /* ------------------------------------------------------------------ */

  function start(teamId, sessionId, opts) {
    _opts = opts || {};
    _phase = 1;
    _roleStatus = {};

    mount();

    // Set all roles to running at start
    ROLES.forEach(r => setRoleStatus(r.key, STATUS.RUNNING));

    connectSSE(teamId, sessionId).catch(err => {
      if (err.name === 'AbortError') return;
      showVerdict(false, err.message);
      setTimeout(() => {
        unmount();
        if (_opts.onError) _opts.onError(err.message);
      }, 2000);
    });
  }

  function cancel() {
    if (_abortController) {
      _abortController.abort();
      _abortController = null;
    }
    unmount();
    if (_opts.onError) _opts.onError('cancelled');
  }

  /* ------------------------------------------------------------------ */
  /*  Expose                                                             */
  /* ------------------------------------------------------------------ */

  window.CouncilAnimation = { start, cancel };
})();
