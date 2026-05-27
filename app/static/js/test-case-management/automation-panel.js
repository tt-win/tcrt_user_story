/* ============================================================
   TEST CASE MANAGEMENT - AUTOMATION PANEL
   ============================================================
   Read-only display of automation scripts linked to a test case.
   Triggered by showTestCaseModal() via testCaseAutomationPanel.load(record_id).
   ============================================================ */

(function () {
  const LINK_BADGE = {
    PRIMARY: 'bg-success',
    COVERS: 'bg-info text-dark',
    REFERENCES: 'bg-secondary'
  };

  const STATUS_BADGE = {
    QUEUED: 'bg-secondary',
    RUNNING: 'bg-info text-dark',
    SUCCEEDED: 'bg-success',
    FAILED: 'bg-danger',
    CANCELLED: 'bg-warning text-dark',
    UNKNOWN: 'bg-dark'
  };

  const elements = () => ({
    wrap: document.getElementById('automationPanelWrap'),
    loading: document.getElementById('automationPanelLoading'),
    empty: document.getElementById('automationPanelEmpty'),
    error: document.getElementById('automationPanelError'),
    list: document.getElementById('automationPanelList'),
    hubLink: document.getElementById('automationOpenHubLink')
  });

  async function load(recordId) {
    const el = elements();
    if (!el.wrap) return;

    if (!recordId) {
      el.wrap.style.display = 'none';
      return;
    }

    const team = (window.AppUtils && window.AppUtils.getCurrentTeam) ? window.AppUtils.getCurrentTeam() : null;
    if (!team || !team.id) {
      el.wrap.style.display = 'none';
      return;
    }

    el.wrap.style.display = '';
    el.list.innerHTML = '';
    el.empty.classList.add('d-none');
    el.error.classList.add('d-none');
    el.loading.classList.remove('d-none');

    if (el.hubLink) {
      el.hubLink.href = `/automation-hub?team_id=${encodeURIComponent(team.id)}`;
    }

    try {
      const url = `/api/teams/${team.id}/test-cases/${encodeURIComponent(recordId)}/linked-automation`;
      const response = await window.AuthClient.fetch(url);
      const data = await response.json().catch(() => []);
      if (!response.ok) {
        throw new Error(extractApiErrorMessage(data, response));
      }
      render(Array.isArray(data) ? data : []);
    } catch (error) {
      showError(error.message || t('testCase.automation.loadFailed', 'Failed to load automation links'));
    } finally {
      el.loading.classList.add('d-none');
    }
  }

  function render(items) {
    const el = elements();
    if (!items.length) {
      el.empty.classList.remove('d-none');
      el.list.innerHTML = '';
      retranslate(el.empty);
      return;
    }
    el.empty.classList.add('d-none');
    el.list.innerHTML = items.map(renderItem).join('');
    retranslate(el.list);
  }

  function renderItem(item) {
    const linkClass = LINK_BADGE[item.link_type] || 'bg-secondary';
    const statusClass = item.last_run_status ? (STATUS_BADGE[item.last_run_status] || 'bg-secondary') : '';
    const statusBadge = item.last_run_status
      ? `<span class="badge ${statusClass}">${escapeHtml(item.last_run_status)}</span>`
      : `<span class="text-muted small">${escapeHtml(t('testCase.automation.neverRun', 'No runs yet'))}</span>`;
    const lastRunAt = item.last_run_at ? formatDate(item.last_run_at) : '';
    const lastRunLink = item.last_run_url
      ? `<a href="${escapeAttr(item.last_run_url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm py-0" title="${escapeAttr(t('testCase.automation.openLastRun', 'Open last run in CI'))}"><i class="fas fa-external-link-alt"></i></a>`
      : '';
    const reportLink = item.report_url
      ? `<a href="${escapeAttr(item.report_url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm py-0" title="${escapeAttr(t('testCase.automation.openReport', 'Open report'))}"><i class="fas fa-chart-bar"></i></a>`
      : '';

    const sourceBadge = renderLinkSourceBadge(item.created_by);
    return `
      <div class="automation-panel-item">
        <div class="automation-panel-item-main">
          <div class="d-flex align-items-center gap-2 flex-wrap">
            <span class="badge ${linkClass}">${escapeHtml(item.link_type)}</span>
            ${sourceBadge}
            <span class="fw-semibold automation-panel-name" title="${escapeAttr(item.name)}">${escapeHtml(item.name)}</span>
            <span class="text-muted small">${escapeHtml(item.script_format || 'OTHER')}</span>
          </div>
          <div class="automation-panel-item-meta">
            ${statusBadge}
            ${lastRunAt ? `<span class="text-muted small">${escapeHtml(lastRunAt)}</span>` : ''}
          </div>
        </div>
        <div class="automation-panel-item-actions">
          ${lastRunLink}
          ${reportLink}
        </div>
      </div>`;
  }

  function renderLinkSourceBadge(createdBy) {
    if (createdBy === 'marker-sync') {
      return `<span class="badge bg-info text-dark" title="${escapeAttr(t('testCase.automation.sourceMarkerTip', 'Derived from @pytest.mark.tcrt or // tcrt:'))}">
                <i class="fas fa-tag me-1"></i>${escapeHtml(t('testCase.automation.sourceMarker', 'marker'))}
              </span>`;
    }
    if (typeof createdBy === 'string' && createdBy.indexOf('ai-suggest:') === 0) {
      return `<span class="badge bg-warning text-dark" title="${escapeAttr(t('testCase.automation.sourceAiTip', 'Accepted from an AI suggestion'))}">
                <i class="fas fa-robot me-1"></i>${escapeHtml(t('testCase.automation.sourceAi', 'AI'))}
              </span>`;
    }
    return `<span class="badge bg-secondary" title="${escapeAttr(t('testCase.automation.sourceHumanTip', 'Created manually by a user'))}">
              <i class="fas fa-user me-1"></i>${escapeHtml(t('testCase.automation.sourceHuman', 'manual'))}
            </span>`;
  }

  function showError(message) {
    const el = elements();
    el.error.textContent = message;
    el.error.classList.remove('d-none');
    el.empty.classList.add('d-none');
    el.list.innerHTML = '';
  }

  function reset() {
    const el = elements();
    if (!el.wrap) return;
    el.wrap.style.display = 'none';
    el.list.innerHTML = '';
    el.empty.classList.add('d-none');
    el.error.classList.add('d-none');
    el.loading.classList.add('d-none');
  }

  function formatDate(value) {
    if (!value) return '';
    try {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString();
    } catch (_e) {
      return value;
    }
  }

  function retranslate(root) {
    if (window.i18n && window.i18n.retranslate) window.i18n.retranslate(root);
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
      "'": '&#39;'
    }[char]));
  }

  function escapeAttr(value) {
    return escapeHtml(value);
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

  window.testCaseAutomationPanel = { load, reset };
})();
