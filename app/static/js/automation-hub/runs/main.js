(function () {
  const STATUS_BADGE = {
    QUEUED: 'bg-secondary',
    RUNNING: 'bg-info text-dark',
    SUCCEEDED: 'bg-success',
    FAILED: 'bg-danger',
    CANCELLED: 'bg-warning text-dark',
    UNKNOWN: 'bg-dark'
  };

  const TERMINAL = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED']);

  const state = {
    teamId: null,
    runs: [],
    runModal: null,
    selectedGroup: null,
    selectedScript: null,
    filters: { status: '', triggered_by: '', branch: '' },
    hasLoaded: false
  };

  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('i18nReady', refreshTexts);
  document.addEventListener('languageChanged', () => {
    renderRuns();
    refreshTexts();
  });

  function init() {
    state.teamId = resolveTeamId();
    if (!state.teamId) return;

    const modalEl = document.getElementById('runSuiteModal');
    if (modalEl) state.runModal = new bootstrap.Modal(modalEl);

    document.addEventListener('automation:run-suite', (event) => {
      const group = event.detail && event.detail.group;
      if (group) openRunModal(group);
    });
    document.addEventListener('automation:run-script', (event) => {
      const script = event.detail && event.detail.script;
      if (script) openScriptRunModal(script);
    });

    document.getElementById('runSuiteConfirmBtn').addEventListener('click', submitRun);
    document.getElementById('runRefreshBtn').addEventListener('click', loadRuns);
    document.getElementById('runSyncPendingBtn').addEventListener('click', syncPending);

    document.getElementById('runFilterStatus').addEventListener('change', applyFilter);
    document.getElementById('runFilterTrigger').addEventListener('change', applyFilter);
    let branchTimer = null;
    document.getElementById('runFilterBranch').addEventListener('input', () => {
      clearTimeout(branchTimer);
      branchTimer = setTimeout(applyFilter, 300);
    });

    document.getElementById('runRows').addEventListener('click', onRowAction);

    const runsTab = document.getElementById('runs-tab');
    if (runsTab) {
      runsTab.addEventListener('shown.bs.tab', () => {
        if (!state.hasLoaded) loadRuns();
      });
    }
  }

  // ----------------------------------------------------------- Run modal

  function openRunModal(group) {
    state.selectedGroup = group;
    state.selectedScript = null;
    resetRunModal(
      'automationHub.runs.modalTitle',
      'automationHub.runs.modalSuite',
      'automationHub.runs.modalCiJob',
      group.name || '',
      group.ci_job_name || '—'
    );
  }

  function openScriptRunModal(script) {
    state.selectedGroup = null;
    state.selectedScript = script;
    resetRunModal(
      'automationHub.runs.modalScriptTitle',
      'automationHub.runs.modalScript',
      'automationHub.runs.modalScriptPath',
      script.name || script.ref_path || '',
      script.ref_path || '—'
    );
  }

  function resetRunModal(titleKey, sourceKey, metaKey, sourceName, metaValue) {
    const title = document.getElementById('runSuiteModalTitle');
    const sourceLabel = document.getElementById('runSuiteSourceLabel');
    const metaLabel = document.getElementById('runSuiteMetaLabel');
    if (title) title.dataset.i18n = titleKey;
    if (sourceLabel) sourceLabel.dataset.i18n = sourceKey;
    if (metaLabel) metaLabel.dataset.i18n = metaKey;
    document.getElementById('runSuiteName').textContent = sourceName;
    document.getElementById('runSuiteJob').textContent = metaValue;
    document.getElementById('runSuiteBranch').value = '';
    document.getElementById('runSuiteRunner').value = '';
    document.getElementById('runSuiteInputs').value = '';
    if (state.runModal) state.runModal.show();
    loadRunnerOptions();
    refreshTexts();
  }

  let _runnerOptionsLoaded = false;
  async function loadRunnerOptions() {
    const dl = document.getElementById('runSuiteRunnerOptions');
    const hint = document.getElementById('runSuiteRunnerHint');
    if (!dl) return;
    // Cache for the session — runners rarely change. Refresh by closing/reopening hub.
    if (_runnerOptionsLoaded) return;
    try {
      // CI providers are now org-scoped → call system router instead of team router.
      const data = await apiFetch('/api/system/automation-providers/active-ci/runners');
      _runnerOptionsLoaded = true;
      const labels = Array.isArray(data && data.labels) ? data.labels : [];
      const defaultLabel = data && data.default_runner_label;
      const runnerEl = document.getElementById('runSuiteRunner');
      if (runnerEl && defaultLabel && !runnerEl.placeholder.includes('(')) {
        runnerEl.placeholder = `${runnerEl.placeholder} — ${t('automationHub.runs.modalRunnerDefault', 'default')}: ${defaultLabel}`;
      }
      dl.innerHTML = labels.map((label) => `<option value="${escapeAttr(label)}"></option>`).join('');
      if (hint && labels.length) {
        const baseHint = t('automationHub.runs.modalRunnerHint', 'Maps to GitHub Actions runs-on or Jenkins NODE_LABEL.');
        const discovered = t('automationHub.runs.modalRunnerDiscovered', 'Discovered labels');
        hint.textContent = `${baseHint} · ${discovered}: ${labels.length}`;
      }
    } catch (_e) {
      // Discovery is best-effort; the free-text field still works.
      _runnerOptionsLoaded = true;
    }
  }

  async function submitRun() {
    const group = state.selectedGroup;
    const script = state.selectedScript;
    if (!group && !script) return;
    const branch = document.getElementById('runSuiteBranch').value.trim();
    const runner = document.getElementById('runSuiteRunner').value.trim();
    const inputsRaw = document.getElementById('runSuiteInputs').value.trim();

    let inputs = {};
    if (inputsRaw) {
      try {
        inputs = JSON.parse(inputsRaw);
        if (typeof inputs !== 'object' || Array.isArray(inputs) || inputs === null) {
          throw new Error('not object');
        }
      } catch (_e) {
        showError(t('automationHub.runs.modalInputsInvalid', 'Extra inputs must be a JSON object'));
        return;
      }
    }

    const payload = { inputs };
    if (branch) payload.branch = branch;
    if (runner) payload.runner_label = runner;

    const button = document.getElementById('runSuiteConfirmBtn');
    button.disabled = true;
    try {
      const endpoint = script
        ? `/api/teams/${state.teamId}/automation-scripts/${script.id}/runs`
        : `/api/teams/${state.teamId}/automation-script-groups/${group.id}/runs`;
      await apiFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (state.runModal) state.runModal.hide();
      showSuccess(script
        ? t('automationHub.scripts.runQueued', 'Script run queued')
        : t('automationHub.suites.runQueued', 'Suite run queued'));
      // Refresh runs list so user sees the new row when they switch tab
      await loadRuns();
    } catch (error) {
      showError(error.message || (script
        ? t('automationHub.scripts.runFailed', 'Failed to run script')
        : t('automationHub.suites.runFailed', 'Failed to run suite')));
    } finally {
      button.disabled = false;
    }
  }

  // ----------------------------------------------------------- Run history

  async function loadRuns() {
    state.hasLoaded = true;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('limit', '50');
      if (state.filters.status) params.set('status', state.filters.status);
      if (state.filters.triggered_by) params.set('triggered_by', state.filters.triggered_by);
      if (state.filters.branch) params.set('branch', state.filters.branch);
      const url = `/api/teams/${state.teamId}/automation-runs?${params.toString()}`;
      const result = await apiFetch(url);
      state.runs = (result && result.items) || [];
      renderRuns();
    } catch (error) {
      showError(error.message || t('automationHub.runs.loadFailed', 'Failed to load runs'));
    } finally {
      setLoading(false);
    }
  }

  function applyFilter() {
    state.filters.status = document.getElementById('runFilterStatus').value;
    state.filters.triggered_by = document.getElementById('runFilterTrigger').value;
    state.filters.branch = document.getElementById('runFilterBranch').value.trim();
    loadRuns();
  }

  async function syncPending() {
    const button = document.getElementById('runSyncPendingBtn');
    button.disabled = true;
    try {
      const result = await apiFetch(`/api/teams/${state.teamId}/automation-runs/sync-pending?limit=50`, {
        method: 'POST'
      });
      showSuccess(
        t('automationHub.runs.syncDone', 'Sync done')
        + ` · ${(result && result.synced) || 0} / ${(result && result.terminal) || 0}`
      );
      await loadRuns();
    } catch (error) {
      showError(error.message || t('automationHub.runs.syncFailed', 'Failed to sync runs'));
    } finally {
      button.disabled = false;
    }
  }

  function renderRuns() {
    const tableWrap = document.getElementById('runTableWrap');
    const empty = document.getElementById('runEmpty');
    const rows = document.getElementById('runRows');

    if (!state.runs.length) {
      tableWrap.classList.add('d-none');
      empty.classList.remove('d-none');
      refreshTexts();
      return;
    }

    empty.classList.add('d-none');
    tableWrap.classList.remove('d-none');
    rows.innerHTML = state.runs.map(renderRunRow).join('');
    refreshTexts(rows);
  }

  function renderRunRow(run) {
    const statusClass = STATUS_BADGE[run.status] || 'bg-secondary';
    const isTerminal = TERMINAL.has(run.status);
    const sourceLabel = run.script_group_id
      ? `${escapeHtml(t('automationHub.runs.suiteShort', 'Suite'))} #${run.script_group_id}`
      : (run.automation_script_id
        ? `${escapeHtml(t('automationHub.runs.scriptShort', 'Script'))} #${run.automation_script_id}`
        : '—');
    const externalLink = run.external_run_url
      ? `<a href="${escapeAttr(run.external_run_url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm" title="${escapeAttr(t('automationHub.runs.openExternal', 'Open in CI'))}"><i class="fas fa-external-link-alt"></i></a>`
      : '';
    const reportLink = run.report_url
      ? `<a href="${escapeAttr(run.report_url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm" title="${escapeAttr(t('automationHub.runs.report', 'Report'))}"><i class="fas fa-chart-bar"></i></a>`
      : '';
    const cancelBtn = isTerminal
      ? ''
      : `<button type="button" class="btn btn-danger btn-sm" data-run-action="cancel" data-run-id="${run.id}" title="${escapeAttr(t('automationHub.runs.cancel', 'Cancel'))}"><i class="fas fa-stop"></i></button>`;
    const syncBtn = isTerminal
      ? ''
      : `<button type="button" class="btn btn-secondary btn-sm" data-run-action="sync" data-run-id="${run.id}" title="${escapeAttr(t('automationHub.runs.syncOne', 'Sync now'))}"><i class="fas fa-sync"></i></button>`;
    const reconcileBtn = run.status === 'UNKNOWN' || !run.external_run_id
      ? `<button type="button" class="btn btn-warning btn-sm" data-run-action="reconcile" data-run-id="${run.id}" title="${escapeAttr(t('automationHub.runs.reconcile', 'Reconcile'))}"><i class="fas fa-link"></i></button>`
      : '';

    return `
      <tr>
        <td class="font-monospace">${run.id}</td>
        <td>${sourceLabel}</td>
        <td><div class="font-monospace text-truncate" style="max-width: 200px;" title="${escapeAttr(run.workflow_id || '')}">${escapeHtml(run.workflow_id || '—')}</div></td>
        <td class="font-monospace">${escapeHtml(run.branch || '—')}</td>
        <td><span class="badge ${statusClass}">${escapeHtml(run.status)}</span></td>
        <td>${escapeHtml(run.triggered_by || '—')}</td>
        <td class="text-muted small">${formatDate(run.started_at)}</td>
        <td class="text-muted small">${formatDuration(run.duration_ms)}</td>
        <td class="text-end automation-run-actions">
          ${externalLink}
          ${reportLink}
          ${syncBtn}
          ${reconcileBtn}
          ${cancelBtn}
        </td>
      </tr>`;
  }

  async function onRowAction(event) {
    const button = event.target.closest('[data-run-action]');
    if (!button) return;
    const runId = button.dataset.runId;
    const action = button.dataset.runAction;
    button.disabled = true;
    try {
      if (action === 'cancel') {
        const ok = await AppUtils.showConfirm(t('automationHub.runs.cancelConfirm', 'Cancel this run?'));
        if (!ok) return;
        await apiFetch(`/api/teams/${state.teamId}/automation-runs/${runId}/cancel`, { method: 'POST' });
        showSuccess(t('automationHub.runs.cancelDone', 'Run cancelled'));
      } else if (action === 'sync') {
        await apiFetch(`/api/teams/${state.teamId}/automation-runs/${runId}/sync`, { method: 'POST' });
        showSuccess(t('automationHub.runs.syncOneDone', 'Run synced'));
      } else if (action === 'reconcile') {
        const externalId = window.prompt(t('automationHub.runs.reconcilePrompt', 'External run id (leave blank to mark UNKNOWN):')) || '';
        const payload = externalId.trim() ? { external_run_id: externalId.trim() } : {};
        await apiFetch(`/api/teams/${state.teamId}/automation-runs/${runId}/reconcile`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        showSuccess(t('automationHub.runs.reconcileDone', 'Run reconciled'));
      }
      await loadRuns();
    } catch (error) {
      showError(error.message || t('automationHub.runs.actionFailed', 'Run action failed'));
    } finally {
      button.disabled = false;
    }
  }

  // ----------------------------------------------------------- helpers

  function setLoading(isLoading) {
    document.getElementById('runLoading').classList.toggle('d-none', !isLoading);
  }

  function formatDate(value) {
    if (!value) return '—';
    try {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return escapeHtml(value);
      return date.toLocaleString();
    } catch (_e) {
      return escapeHtml(value);
    }
  }

  function formatDuration(ms) {
    if (ms === null || ms === undefined) return '—';
    const value = Number(ms);
    if (!Number.isFinite(value) || value < 0) return '—';
    if (value < 1000) return `${value} ms`;
    const seconds = value / 1000;
    if (seconds < 60) return `${seconds.toFixed(1)} s`;
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.round(seconds - minutes * 60);
    return `${minutes}m ${remainder}s`;
  }

  async function apiFetch(url, options) {
    const response = await window.AuthClient.fetch(url, options || {});
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(extractApiErrorMessage(data, response));
    }
    return data;
  }

  function extractApiErrorMessage(data, response) {
    if (Array.isArray(data && data.detail) && data.detail.length) {
      return data.detail.map((entry) => {
        const loc = Array.isArray(entry && entry.loc) ? entry.loc.filter((p) => p !== 'body') : [];
        const field = loc.join('.');
        const msg = (entry && entry.msg) || '';
        return field ? `${field}: ${msg}` : msg;
      }).filter(Boolean).join('; ');
    }
    if (data && data.detail && typeof data.detail === 'object') {
      return data.detail.message || data.detail.detail || data.detail.code || (response && response.statusText) || 'Request failed';
    }
    if (typeof (data && data.detail) === 'string') return data.detail;
    if (typeof (data && data.message) === 'string') return data.message;
    return (response && response.statusText) || 'Request failed';
  }

  function resolveTeamId() {
    const params = new URLSearchParams(window.location.search);
    const queryTeamId = params.get('team_id');
    if (queryTeamId) return queryTeamId;
    if (window.AppUtils && window.AppUtils.getCurrentTeamId) return window.AppUtils.getCurrentTeamId();
    const stored = localStorage.getItem('currentTeam');
    if (!stored) return null;
    try {
      const team = JSON.parse(stored);
      return team && team.id ? String(team.id) : null;
    } catch (_e) {
      return null;
    }
  }

  function refreshTexts(root) {
    if (window.i18n) window.i18n.retranslate(root || document);
  }

  function showSuccess(message) {
    if (window.AppUtils) window.AppUtils.showSuccess(message);
  }

  function showError(message) {
    if (window.AppUtils) window.AppUtils.showError(message);
  }

  function t(key, fallback) {
    return window.i18n && window.i18n.t ? window.i18n.t(key, {}, fallback) : fallback;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }
})();
