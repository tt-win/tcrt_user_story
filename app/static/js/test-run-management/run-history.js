/* ============================================================
   TEST RUN MANAGEMENT — RUN HISTORY
   ============================================================
   Read-only list of automation runs triggered by the current Test Run
   Set. Replaces the Automation Hub Runs tab
   (see move-run-history-to-test-run-set).

   Public API (all globals; consumed by set-modal.js):
     - TestRunSetRunHistory.loadForSet(setId, teamId)  fetch + render
     - TestRunSetRunHistory.clear()                   clear table on close
     - TestRunSetRunHistory.cancelRun(runId)
     - TestRunSetRunHistory.reconcileRun(runId)
     - TestRunSetRunHistory.openReport(url, openInCiUrl)
   ============================================================ */
(function () {
  const RUN_STATUS_BADGE = {
    QUEUED: 'bg-secondary',
    RUNNING: 'bg-info text-dark',
    SUCCEEDED: 'bg-success',
    FAILED: 'bg-danger',
    CANCELLED: 'bg-warning text-dark',
    UNKNOWN: 'bg-dark',
  };

  const TERMINAL_STATUSES = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED', 'UNKNOWN']);
  const REPORTABLE_TERMINAL_STATUSES = new Set(['SUCCEEDED', 'FAILED']);
  const AUTO_REFRESH_MS = 10000;

  const state = {
    teamId: null,
    setId: null,
    runs: [],
    loading: false,
    pollTimer: null,
  };

  // i18n shortcut that returns the localized string with an English fallback.
  function t(key, fallback) {
    if (window.i18n && typeof window.i18n.t === 'function') {
      const value = window.i18n.t(key);
      if (value && value !== key) return value;
    }
    return fallback;
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }

  function formatTimestamp(value) {
    if (!value) return '—';
    try {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString();
    } catch (_e) {
      return value;
    }
  }

  function formatDuration(ms) {
    if (ms === null || ms === undefined) return '';
    const sec = Math.round(ms / 1000);
    if (sec < 60) return `${sec}s`;
    const min = Math.floor(sec / 60);
    const rest = sec % 60;
    return `${min}m ${rest}s`;
  }

  function getSetIds() {
    // The set-modal keeps the current set id under window._currentTestRunSetId
    // (and the modal element exposes it on the wrapping container). Fall back
    // to either so callers can mix & match.
    if (window._currentTestRunSetId) return Number(window._currentTestRunSetId);
    const modalEl = document.getElementById('testRunSetDetailModal');
    const raw = modalEl && modalEl.dataset ? modalEl.dataset.targetSetId : null;
    return raw ? Number(raw) : null;
  }

  function getErrorMessage(payload, fallback) {
    const detail = payload && payload.detail;
    if (detail && typeof detail === 'object' && detail.message) return detail.message;
    if (typeof detail === 'string') return detail;
    return fallback;
  }

  async function requestJson(url, opts) {
    const fetcher = window.AuthClient && window.AuthClient.fetch
      ? window.AuthClient.fetch.bind(window.AuthClient)
      : fetch;
    const resp = await fetcher(url, opts);
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      const err = new Error(getErrorMessage(detail, resp.statusText));
      err.status = resp.status;
      err.body = detail;
      throw err;
    }
    return resp.status === 204 ? null : resp.json();
  }

  function getApi() {
    return requestJson;
  }

  function showError(message) {
    if (window.AppUtils && window.AppUtils.showError) {
      window.AppUtils.showError(message);
      return;
    }
    if (window.alert) window.alert(message);
  }

  function setVisible(el, visible) {
    if (!el) return;
    el.classList.toggle('d-none', !visible);
  }

  function reretranlate(root) {
    if (window.i18n && window.i18n.retranslate) window.i18n.retranslate(root);
  }

  // ------------------------------------------------------------------- load

  async function loadForSet(setId, teamId, options = {}) {
    const silent = !!options.silent;
    state.setId = setId != null ? Number(setId) : null;
    state.teamId = teamId != null ? Number(teamId) : null;
    if (!silent) state.runs = [];

    const loadingEl = document.getElementById('setDetailAutomationRunsLoading');
    const emptyEl = document.getElementById('setDetailAutomationRunsEmpty');
    const tableEl = document.getElementById('setDetailAutomationRunsTable');
    const rowsEl = document.getElementById('setDetailAutomationRunsRows');
    const countEl = document.getElementById('setDetailAutomationRunsCount');
    if (!state.setId || !state.teamId) {
      setVisible(loadingEl, false);
      setVisible(emptyEl, true);
      setVisible(tableEl, false);
      if (countEl) countEl.textContent = '0';
      return;
    }

    if (!silent) {
      setVisible(loadingEl, true);
      setVisible(emptyEl, false);
      setVisible(tableEl, false);
      if (rowsEl) rowsEl.innerHTML = '';
    }
    state.loading = true;

    try {
      const api = getApi();
      const payload = await api(
        `/api/teams/${state.teamId}/test-run-sets/${state.setId}/runs?limit=200`
      );
      state.runs = Array.isArray(payload && payload.items) ? payload.items : [];
    } catch (error) {
      showError(error.message || t('testRun.sets.detail.automationRunsLoadFailed', 'Failed to load runs'));
      state.runs = [];
    } finally {
      state.loading = false;
      if (!silent) setVisible(loadingEl, false);
      render();
      updateAutoRefresh();
    }
  }

  function clear() {
    stopAutoRefresh();
    state.setId = null;
    state.teamId = null;
    state.runs = [];
    const rowsEl = document.getElementById('setDetailAutomationRunsRows');
    if (rowsEl) rowsEl.innerHTML = '';
    const tableEl = document.getElementById('setDetailAutomationRunsTable');
    const emptyEl = document.getElementById('setDetailAutomationRunsEmpty');
    const loadingEl = document.getElementById('setDetailAutomationRunsLoading');
    const countEl = document.getElementById('setDetailAutomationRunsCount');
    setVisible(loadingEl, false);
    setVisible(emptyEl, true);
    setVisible(tableEl, false);
    if (countEl) countEl.textContent = '0';
  }

  function hasPendingUpdates() {
    return state.runs.some((run) => {
      if (!TERMINAL_STATUSES.has(run.status)) return true;
      return REPORTABLE_TERMINAL_STATUSES.has(run.status) && !run.report_url;
    });
  }

  function updateAutoRefresh() {
    if (!state.setId || !state.teamId || !hasPendingUpdates()) {
      stopAutoRefresh();
      return;
    }
    if (state.pollTimer) return;
    state.pollTimer = window.setInterval(() => {
      if (!state.setId || !state.teamId || state.loading) return;
      loadForSet(state.setId, state.teamId, { silent: true });
    }, AUTO_REFRESH_MS);
  }

  function stopAutoRefresh() {
    if (!state.pollTimer) return;
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  function render() {
    const rowsEl = document.getElementById('setDetailAutomationRunsRows');
    const tableEl = document.getElementById('setDetailAutomationRunsTable');
    const emptyEl = document.getElementById('setDetailAutomationRunsEmpty');
    const countEl = document.getElementById('setDetailAutomationRunsCount');
    if (!rowsEl) return;

    if (!state.runs.length) {
      setVisible(tableEl, false);
      setVisible(emptyEl, true);
      if (countEl) countEl.textContent = '0';
      return;
    }
    setVisible(tableEl, true);
    setVisible(emptyEl, false);
    if (countEl) countEl.textContent = String(state.runs.length);

    rowsEl.innerHTML = state.runs.map(renderRow).join('');
    reretranlate(rowsEl);
  }

  function renderRow(run) {
    const badgeClass = RUN_STATUS_BADGE[run.status] || 'bg-secondary';
    const suiteName = run.script_group_name || (run.script_group_id ? `Suite #${run.script_group_id}` : `Run #${run.id}`);
    const branch = run.branch || '—';
    const started = run.started_at ? formatTimestamp(run.started_at) : '—';
    const duration = formatDuration(run.duration_ms);
    const triggerLabels = {
      USER: t('testRun.sets.detail.automationRunsTriggerUser', 'User'),
      WEBHOOK: t('testRun.sets.detail.automationRunsTriggerWebhook', 'Webhook'),
      SCHEDULE: t('testRun.sets.detail.automationRunsTriggerSchedule', 'Schedule'),
      MCP: t('testRun.sets.detail.automationRunsTriggerMcp', 'MCP'),
    };
    const trigger = triggerLabels[run.triggered_by] || run.triggered_by || '—';
    const externalLink = run.external_run_url
      ? `<a href="${escapeAttr(run.external_run_url)}" target="_blank" rel="noopener" class="btn btn-link btn-sm p-0 ms-2" title="${escapeAttr(t('testRun.sets.detail.automationRunsOpenExternal', 'Open in CI'))}"><i class="fas fa-external-link-alt"></i></a>`
      : '';
    const reportPending = REPORTABLE_TERMINAL_STATUSES.has(run.status) && !run.report_url;
    const reportLink = run.report_url
      ? `<button type="button" class="btn btn-link btn-sm p-0 ms-1" data-run-report="${run.id}" data-run-report-url="${escapeAttr(run.report_url)}" data-run-external-url="${escapeAttr(run.external_run_url || '')}" title="${escapeAttr(t('testRun.sets.detail.automationRunsOpenReport', 'Open report'))}"><i class="fas fa-chart-bar"></i></button>`
      : reportPending
        ? `<span class="text-muted small ms-2" title="${escapeAttr(t('testRun.sets.detail.automationRunsReportPendingTitle', 'Allure report is still being generated'))}"><i class="fas fa-hourglass-half me-1"></i><span data-i18n="testRun.sets.detail.automationRunsReportPending">Report pending</span></span>`
      : '';
    const cancelBtn = TERMINAL_STATUSES.has(run.status)
      ? ''
      : `<button type="button" class="btn btn-link btn-sm p-0 ms-1 text-danger" data-run-cancel="${run.id}" title="${escapeAttr(t('testRun.sets.detail.automationRunsCancel', 'Cancel'))}"><i class="fas fa-ban"></i></button>`;
    const reconcileBtn = run.external_run_id
      ? ''
      : `<button type="button" class="btn btn-link btn-sm p-0 ms-1 text-warning" data-run-reconcile="${run.id}" title="${escapeAttr(t('testRun.sets.detail.automationRunsReconcile', 'Reconcile'))}"><i class="fas fa-link"></i></button>`;
    return `
      <tr>
        <td>
          <div class="fw-semibold">${escapeHtml(suiteName)}</div>
          <div class="font-monospace small text-muted">#${escapeHtml(run.id)}</div>
        </td>
        <td><span class="font-monospace small">${escapeHtml(branch)}</span></td>
        <td><span class="badge ${badgeClass}">${escapeHtml(run.status)}</span></td>
        <td>${escapeHtml(trigger)}</td>
        <td>${escapeHtml(started)}${duration ? ' · ' + escapeHtml(duration) : ''}</td>
        <td class="text-end">${externalLink}${reportLink}${cancelBtn}${reconcileBtn}</td>
      </tr>`;
  }

  // ------------------------------------------------------------------- actions

  async function cancelRun(runId) {
    if (!state.teamId || !state.setId) return;
    const message = t('testRun.sets.detail.automationRunsCancelConfirm', 'Cancel this run?');
    if (window.AppUtils && window.AppUtils.showConfirm) {
      const ok = await window.AppUtils.showConfirm(message);
      if (!ok) return;
    } else if (!window.confirm(message)) {
      return;
    }
    try {
      const api = getApi();
      await api(
        `/api/teams/${state.teamId}/test-run-sets/${state.setId}/runs/${runId}/cancel`,
        { method: 'POST' }
      );
      if (window.AppUtils && window.AppUtils.showSuccess) {
        window.AppUtils.showSuccess(t('testRun.sets.detail.automationRunsCancelDone', 'Run cancelled'));
      }
      await loadForSet(state.setId, state.teamId);
    } catch (error) {
      showError(error.message || t('testRun.sets.detail.automationRunsActionFailed', 'Run action failed'));
    }
  }

  async function reconcileRun(runId) {
    if (!state.teamId || !state.setId) return;
    const message = t('testRun.sets.detail.automationRunsReconcilePrompt', 'External run id (leave blank to mark UNKNOWN):');
    const externalId = window.prompt ? window.prompt(message) : null;
    if (externalId === null) return; // user cancelled
    try {
      const api = getApi();
      await api(
        `/api/teams/${state.teamId}/test-run-sets/${state.setId}/runs/${runId}/reconcile`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ external_run_id: externalId || null }),
        }
      );
      if (window.AppUtils && window.AppUtils.showSuccess) {
        window.AppUtils.showSuccess(t('testRun.sets.detail.automationRunsReconcileDone', 'Run reconciled'));
      }
      await loadForSet(state.setId, state.teamId);
    } catch (error) {
      showError(error.message || t('testRun.sets.detail.automationRunsActionFailed', 'Run action failed'));
    }
  }

  function openReport(reportUrl, externalRunUrl) {
    if (!reportUrl) return;
    const modalEl = document.getElementById('reportEmbedModal');
    const frame = document.getElementById('reportEmbedFrame');
    const openLink = document.getElementById('reportEmbedOpenLink');
    const warning = document.getElementById('reportEmbedWarning');
    if (!modalEl || !frame || !openLink) return;
    frame.src = reportUrl;
    openLink.href = externalRunUrl || reportUrl;
    if (warning) warning.classList.add('d-none');
    if (window.bootstrap && window.bootstrap.Modal) {
      window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } else {
      modalEl.classList.add('show');
    }
  }

  // ------------------------------------------------------------------- events

  function bindEvents() {
    const refreshBtn = document.getElementById('setDetailAutomationRunsRefreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        if (state.setId && state.teamId) {
          loadForSet(state.setId, state.teamId);
        }
      });
    }
    const tableEl = document.getElementById('setDetailAutomationRunsTable');
    if (tableEl) {
      tableEl.addEventListener('click', (event) => {
        const target = event.target.closest('[data-run-cancel]');
        if (target) {
          const runId = target.getAttribute('data-run-cancel');
          if (runId) cancelRun(Number(runId));
          return;
        }
        const reconcile = event.target.closest('[data-run-reconcile]');
        if (reconcile) {
          const runId = reconcile.getAttribute('data-run-reconcile');
          if (runId) reconcileRun(Number(runId));
          return;
        }
        const report = event.target.closest('[data-run-report]');
        if (report) {
          openReport(
            report.getAttribute('data-run-report-url'),
            report.getAttribute('data-run-external-url')
          );
        }
      });
    }
    document.addEventListener('automation:run-triggered', (event) => {
      const detail = event.detail || {};
      const setId = detail.setId != null ? Number(detail.setId) : null;
      if (state.setId && state.teamId && setId === state.setId) {
        loadForSet(state.setId, state.teamId, { silent: true });
      }
    });
  }

  // ------------------------------------------------------------------- expose

  window.TestRunSetRunHistory = {
    loadForSet,
    clear,
    cancelRun,
    reconcileRun,
    openReport,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindEvents);
  } else {
    bindEvents();
  }
})();
