(function () {
  const state = {
    teamId: null,
    coverage: null,
    scripts: [],
    linkModal: null,
    linkingCase: null
  };

  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('i18nReady', refreshTexts);
  document.addEventListener('languageChanged', () => {
    renderCoverage();
    refreshTexts();
  });
  window.addEventListener('pageshow', refreshTexts);

  function init() {
    state.teamId = resolveTeamId();
    state.linkModal = new bootstrap.Modal(document.getElementById('coverageLinkModal'));
    bindEvents();
    if (!state.teamId) return;
    loadCoverage();
  }

  function bindEvents() {
    document.getElementById('coverageRefreshBtn').addEventListener('click', loadCoverage);
    document.getElementById('coverageSaveLinkBtn').addEventListener('click', saveLink);
    document.getElementById('coverageUncoveredRows').addEventListener('click', (event) => {
      const button = event.target.closest('[data-coverage-link-case]');
      if (!button) return;
      const caseItem = (state.coverage?.uncovered_sample || []).find(
        (item) => String(item.test_case_id) === button.dataset.coverageLinkCase
      );
      if (caseItem) openLinkModal(caseItem);
    });
  }

  async function loadCoverage() {
    setLoading(true);
    try {
      state.coverage = await apiFetch(`/api/teams/${state.teamId}/automation-coverage`);
      renderCoverage();
    } catch (error) {
      showError(error.message || t('automationHub.coverage.loadFailed', 'Failed to load coverage'));
    } finally {
      setLoading(false);
      refreshTexts();
    }
  }

  function renderCoverage() {
    if (!state.coverage) return;
    const hasCases = state.coverage.total_test_cases > 0;
    document.getElementById('coverageContent').classList.toggle('d-none', !hasCases);
    document.getElementById('coverageEmpty').classList.toggle('d-none', hasCases);
    if (!hasCases) return;

    const total = state.coverage.total_test_cases || 0;
    const any = state.coverage.with_any_link || 0;
    document.getElementById('coverageTotalCases').textContent = formatNumber(total);
    document.getElementById('coveragePrimaryCount').textContent = formatNumber(state.coverage.with_primary_link || 0);
    document.getElementById('coverageCoversCount').textContent = formatNumber(state.coverage.with_covers_link || 0);
    document.getElementById('coverageUncoveredCount').textContent = formatNumber(state.coverage.uncovered_count || 0);
    document.getElementById('coverageRateText').textContent = total ? `${Math.round((any / total) * 100)}%` : '0%';
    renderTrend();
    renderUncoveredCases();
    renderStaleScripts();
  }

  function renderUncoveredCases() {
    const rows = document.getElementById('coverageUncoveredRows');
    const cases = state.coverage.uncovered_sample || [];
    if (!cases.length) {
      rows.innerHTML = `
        <tr>
          <td colspan="3" class="text-center text-muted py-4" data-i18n="automationHub.coverage.noUncovered">All cases have automation coverage.</td>
        </tr>`;
      refreshTexts(rows);
      return;
    }
    rows.innerHTML = cases.map((caseItem) => `
      <tr>
        <td class="font-monospace">${escapeHtml(caseItem.test_case_number)}</td>
        <td>
          <div class="text-truncate automation-coverage-case-title" title="${escapeAttr(caseItem.title)}">${escapeHtml(caseItem.title)}</div>
        </td>
        <td class="text-end">
          <button type="button" class="btn btn-primary btn-sm" data-coverage-link-case="${caseItem.test_case_id}">
            <i class="fas fa-link me-1"></i><span data-i18n="automationHub.coverage.linkScript">Link script</span>
          </button>
        </td>
      </tr>`).join('');
    refreshTexts(rows);
  }

  function renderStaleScripts() {
    const container = document.getElementById('coverageStaleList');
    const scripts = state.coverage.stale_scripts || [];
    if (!scripts.length) {
      container.innerHTML = `
        <div class="automation-empty text-center py-4">
          <i class="fas fa-check-circle text-success automation-state-icon"></i>
          <div class="fw-semibold mt-2" data-i18n="automationHub.coverage.noStale">No stale scripts</div>
        </div>`;
      refreshTexts(container);
      return;
    }
    container.innerHTML = scripts.map((script) => {
      const days = script.days_since_last_run === null || script.days_since_last_run === undefined
        ? t('automationHub.coverage.neverRun', 'Never run')
        : t('automationHub.coverage.daysAgo', `${script.days_since_last_run} days ago`).replace('{count}', script.days_since_last_run);
      return `
        <article class="automation-stale-item">
          <div class="d-flex align-items-start justify-content-between gap-2">
            <div class="min-w-0">
              <div class="fw-semibold text-truncate" title="${escapeAttr(script.name)}">${escapeHtml(script.name)}</div>
              <div class="text-muted small text-truncate" title="${escapeAttr(script.ref_path)}">${escapeHtml(script.ref_path)}</div>
            </div>
            <span class="badge bg-warning text-dark">${escapeHtml(days)}</span>
          </div>
          <div class="text-muted small mt-1">${escapeHtml(script.script_format || 'OTHER')}</div>
        </article>`;
    }).join('');
    refreshTexts(container);
  }

  function renderTrend() {
    const svg = document.getElementById('coverageTrendSvg');
    const points = state.coverage.trend || [];
    const width = 640;
    const height = 180;
    const pad = 20;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    if (points.length === 0) {
      svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" class="automation-trend-empty">${escapeHtml(t('automationHub.coverage.noTrend', 'No trend data'))}</text>`;
      return;
    }

    const maxRate = Math.max(100, ...points.map((item) => Number(item.coverage_rate || 0)));
    const coords = points.map((item, index) => {
      const x = pad + (index * (width - pad * 2)) / Math.max(points.length - 1, 1);
      const rate = Number(item.coverage_rate || 0);
      const y = height - pad - (rate / maxRate) * (height - pad * 2);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    const last = points[points.length - 1];
    const lastRate = Number(last.coverage_rate || 0).toFixed(0);
    svg.innerHTML = `
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" class="automation-trend-axis"></line>
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" class="automation-trend-axis"></line>
      <polyline points="${coords.join(' ')}" class="automation-trend-line"></polyline>
      <text x="${width - pad}" y="${pad + 4}" text-anchor="end" class="automation-trend-label">${escapeHtml(lastRate)}%</text>
    `;
  }

  async function openLinkModal(caseItem) {
    state.linkingCase = caseItem;
    document.getElementById('coverageLinkCaseId').value = caseItem.test_case_id;
    document.getElementById('coverageLinkCaseTitle').textContent = `${caseItem.test_case_number} ${caseItem.title}`;
    document.getElementById('coverageLinkType').value = 'COVERS';
    await ensureScriptsLoaded();
    renderScriptOptions();
    state.linkModal.show();
    refreshTexts();
  }

  async function ensureScriptsLoaded() {
    if (state.scripts.length) return;
    const result = await apiFetch(`/api/teams/${state.teamId}/automation-scripts?limit=200`);
    state.scripts = result.items || [];
  }

  function renderScriptOptions() {
    const select = document.getElementById('coverageScriptSelect');
    if (!state.scripts.length) {
      select.innerHTML = `<option value="">${escapeHtml(t('automationHub.coverage.noScripts', 'No scripts available'))}</option>`;
      return;
    }
    select.innerHTML = state.scripts.map((script) => `
      <option value="${script.id}">${escapeHtml(script.ref_path || script.name)}</option>`).join('');
  }

  async function saveLink() {
    const caseId = document.getElementById('coverageLinkCaseId').value;
    const scriptId = document.getElementById('coverageScriptSelect').value;
    if (!caseId || !scriptId) {
      showError(t('automationHub.coverage.linkValidation', 'Select a script first'));
      return;
    }
    try {
      await apiFetch(`/api/teams/${state.teamId}/automation-scripts/${scriptId}/links`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          test_case_id: Number(caseId),
          link_type: document.getElementById('coverageLinkType').value,
          note: 'Linked from Automation Hub coverage tab'
        })
      });
      state.linkModal.hide();
      showSuccess(t('automationHub.coverage.linkDone', 'Automation script linked'));
      await loadCoverage();
    } catch (error) {
      showError(error.message || t('automationHub.coverage.linkFailed', 'Failed to link automation script'));
    }
  }

  function setLoading(isLoading) {
    document.getElementById('coverageLoading').classList.toggle('d-none', !isLoading);
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
    } catch (error) {
      return null;
    }
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString();
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
