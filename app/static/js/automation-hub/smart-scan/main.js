(function () {
  const state = {
    teamId: null,
    modal: null,
    result: null,
    scanRunId: null,
    pollTimer: null,
    selected: new Set(),
  };

  document.addEventListener('DOMContentLoaded', init);

  function init() {
    state.teamId = resolveTeamId();
    const modalEl = document.getElementById('smartScanModal');
    if (modalEl) state.modal = new bootstrap.Modal(modalEl);

    const btn = document.getElementById('smartScanBtn');
    if (btn) btn.addEventListener('click', openModal);

    const rescanBtn = document.getElementById('smartScanRescanBtn');
    if (rescanBtn) rescanBtn.addEventListener('click', () => runScan());

    const createBtn = document.getElementById('smartScanCreateBtn');
    if (createBtn) createBtn.addEventListener('click', createSelected);

    const proposalsEl = document.getElementById('smartScanProposals');
    if (proposalsEl) {
      proposalsEl.addEventListener('change', (event) => {
        const cb = event.target.closest('[data-proposal-check]');
        if (!cb) return;
        const idx = Number(cb.dataset.proposalCheck);
        if (cb.checked) state.selected.add(idx); else state.selected.delete(idx);
        updateSelectionCounter();
      });
    }
  }

  async function openModal() {
    if (!state.teamId) return;
    if (state.modal) state.modal.show();
    await runScan();
  }

  async function runScan() {
    clearPollTimer();
    setLoading(true);
    showError(null);
    state.result = null;
    state.scanRunId = null;
    state.selected.clear();
    try {
      const data = await apiFetch(`/api/teams/${state.teamId}/automation-scripts/smart-scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      state.scanRunId = data.scan_run_id;
      setProgress(t('automationHub.smartScan.queued', 'Scan queued...'));
      await pollScanRun(data.scan_run_id);
    } catch (error) {
      showError(error.message || t('automationHub.smartScan.scanFailed', 'Smart Scan failed'));
      setLoading(false);
    }
  }

  async function pollScanRun(scanRunId) {
    try {
      const data = await apiFetch(`/api/teams/${state.teamId}/automation-scripts/smart-scan/${scanRunId}`);
      const status = data.status || 'QUEUED';
      const progress = data.progress || {};
      setProgress(progress.step ? `${status} — ${progress.step}` : status);
      if (status === 'READY') {
        state.result = data.result || {};
        (state.result.proposals || []).forEach((_p, idx) => state.selected.add(idx));
        render();
        setLoading(false);
        return;
      }
      if (status === 'FAILED' || status === 'CANCELLED') {
        showError(data.error_summary || t('automationHub.smartScan.scanFailed', 'Smart Scan failed'));
        setLoading(false);
        return;
      }
      state.pollTimer = window.setTimeout(() => {
        pollScanRun(scanRunId);
      }, 1500);
    } catch (error) {
      showError(error.message || t('automationHub.smartScan.scanFailed', 'Smart Scan failed'));
      setLoading(false);
    }
  }

  function clearPollTimer() {
    if (state.pollTimer) {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function setProgress(message) {
    const el = document.getElementById('smartScanProgress');
    if (el) el.textContent = message;
  }

  function resetProgressText() {
    const el = document.getElementById('smartScanProgress');
    if (!el) return;
    el.textContent = t('automationHub.smartScan.loading', 'Scanning repository...');
    el.setAttribute('data-i18n', 'automationHub.smartScan.loading');
  }

  async function createSelected() {
    if (!state.result || !state.selected.size) return;
    const proposals = (state.result.proposals || [])
      .map((p, idx) => ({ p, idx }))
      .filter((it) => state.selected.has(it.idx))
      .map((it) => ({
        name: it.p.name,
        description: it.p.description,
        script_paths: it.p.script_paths,
      }));
    const btn = document.getElementById('smartScanCreateBtn');
    btn.disabled = true;
    try {
      const result = await apiFetch(`/api/teams/${state.teamId}/automation-script-groups/batch-create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposals }),
      });
      const msg = `${t('automationHub.smartScan.batchDone', 'Suites created')}: `
        + `${result.created} created · ${result.skipped} skipped · ${result.failed} failed`;
      showSuccess(msg);
      if (state.modal) state.modal.hide();
      // Reload the parent suites list to reflect new groups
      if (window.location.pathname.includes('automation-hub')) {
        setTimeout(() => window.location.reload(), 300);
      }
    } catch (error) {
      showError(error.message || t('automationHub.smartScan.batchFailed', 'Batch create failed'));
    } finally {
      btn.disabled = false;
    }
  }

  function render() {
    const wrap = document.getElementById('smartScanResult');
    if (!wrap) return;
    if (!state.result) {
      wrap.classList.add('d-none');
      return;
    }
    wrap.classList.remove('d-none');
    renderContract();
    renderProposals();
    renderExcluded();
    updateSelectionCounter();
    if (window.i18n) window.i18n.retranslate(wrap);
  }

  function renderContract() {
    const c = state.result.contract || {};
    const status = c.contract_status || 'missing';
    const statusBadge = {
      ok: 'bg-success',
      partial: 'bg-warning text-dark',
      missing: 'bg-danger',
    }[status] || 'bg-secondary';
    const present = (c.standard_paths_present || []).map((p) => `<span class="badge bg-success me-1">${escapeHtml(p)}</span>`).join('');
    const missing = (c.standard_paths_missing || []).map((p) => `<span class="badge bg-secondary me-1">${escapeHtml(p)}</span>`).join('');
    document.getElementById('smartScanContract').innerHTML = `
      <div class="d-flex align-items-center gap-2 flex-wrap mb-2">
        <span class="badge ${statusBadge}">${escapeHtml(status.toUpperCase())}</span>
        <span class="text-muted small">${escapeHtml(t('automationHub.smartScan.manifest', 'Manifest'))}: ${c.manifest_found ? '✅' : '—'} <code>${escapeHtml(c.manifest_path || '')}</code></span>
        <span class="text-muted small">${escapeHtml(t('automationHub.smartScan.testsPath', 'Tests path'))}: <code>${escapeHtml(c.effective_tests_path || '')}</code></span>
      </div>
      <div class="small">
        <strong>${escapeHtml(t('automationHub.smartScan.present', 'Present'))}:</strong> ${present || '—'}
      </div>
      <div class="small">
        <strong>${escapeHtml(t('automationHub.smartScan.missing', 'Missing'))}:</strong> ${missing || '—'}
      </div>`;
  }

  function renderProposals() {
    const proposals = state.result.proposals || [];
    const container = document.getElementById('smartScanProposals');
    document.getElementById('smartScanProposalTotal').textContent = String(proposals.length);
    if (!proposals.length) {
      container.innerHTML = `<div class="text-muted small">${escapeHtml(t('automationHub.smartScan.noProposals', 'No suites suggested — try Rescan after adding tests under the configured tests path.'))}</div>`;
      return;
    }
    container.innerHTML = proposals.map((p, idx) => `
      <div class="card automation-smart-scan-proposal">
        <div class="card-body py-2">
          <div class="d-flex align-items-center gap-2">
            <input class="form-check-input mt-0" type="checkbox" data-proposal-check="${idx}" ${state.selected.has(idx) ? 'checked' : ''}>
            <div class="flex-grow-1">
              <div class="fw-semibold">${escapeHtml(p.name)}</div>
              <div class="text-muted small">${escapeHtml(p.description || '')}</div>
            </div>
            <span class="badge bg-secondary">${(p.script_paths || []).length}</span>
          </div>
          <details class="mt-1">
            <summary class="small text-muted">${escapeHtml(t('automationHub.smartScan.viewPaths', 'View paths'))}</summary>
            <ul class="small font-monospace mt-1 mb-0 ps-3">
              ${(p.script_paths || []).map((path) => `<li>${escapeHtml(path)}</li>`).join('')}
            </ul>
          </details>
        </div>
      </div>`).join('');
  }

  function renderExcluded() {
    const excluded = state.result.excluded || [];
    const ul = document.getElementById('smartScanExcluded');
    if (!ul) return;
    ul.innerHTML = excluded.length
      ? excluded.map((x) => `<li><code>${escapeHtml(x.ref_path)}</code> — ${escapeHtml(x.reason)}</li>`).join('')
      : `<li>${escapeHtml(t('automationHub.smartScan.noExcluded', 'No files excluded.'))}</li>`;
  }

  function updateSelectionCounter() {
    document.getElementById('smartScanProposalSelected').textContent = String(state.selected.size);
  }

  function setLoading(isLoading) {
    document.getElementById('smartScanLoading').classList.toggle('d-none', !isLoading);
    document.getElementById('smartScanResult').classList.toggle('d-none', isLoading || !state.result);
    if (isLoading) resetProgressText();
  }

  function showError(msg) {
    const el = document.getElementById('smartScanError');
    if (!el) return;
    if (msg) {
      el.textContent = msg;
      el.classList.remove('d-none');
    } else {
      el.classList.add('d-none');
    }
  }

  function showSuccess(msg) {
    if (window.AppUtils) window.AppUtils.showSuccess(msg);
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

  function t(key, fallback) {
    return (window.i18n && window.i18n.t) ? window.i18n.t(key, {}, fallback) : fallback;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[char]));
  }
})();
