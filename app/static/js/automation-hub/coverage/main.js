(function () {
  const state = {
    teamId: null,
    coverage: null,
    view: 'uncovered',      // 'uncovered' | 'covered'
    groupFilter: null       // ticket-prefix group key, or null = all
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
    bindEvents();
    if (!state.teamId) return;
    loadCoverage();
  }

  function bindEvents() {
    const refreshBtn = document.getElementById('coverageRefreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadCoverage);

    const uncoveredTab = document.getElementById('coverageTabUncovered');
    const coveredTab = document.getElementById('coverageTabCovered');
    if (uncoveredTab) uncoveredTab.addEventListener('click', () => setView('uncovered'));
    if (coveredTab) coveredTab.addEventListener('click', () => setView('covered'));

    const groupList = document.getElementById('coverageGroupList');
    if (groupList) {
      groupList.addEventListener('click', (event) => {
        const row = event.target.closest('[data-group]');
        if (!row) return;
        const group = row.dataset.group;
        state.groupFilter = state.groupFilter === group ? null : group;
        renderGroups();
        renderCaseTable();
      });
    }
    const filterClear = document.getElementById('coverageGroupFilterClear');
    if (filterClear) {
      filterClear.addEventListener('click', () => {
        state.groupFilter = null;
        renderGroups();
        renderCaseTable();
      });
    }
  }

  function setView(view) {
    if (state.view === view) return;
    state.view = view;
    document.getElementById('coverageTabUncovered').classList.toggle('active', view === 'uncovered');
    document.getElementById('coverageTabCovered').classList.toggle('active', view === 'covered');
    renderCaseTable();
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
    const hasCases = Number(state.coverage.total_test_cases || 0) > 0;
    document.getElementById('coverageContent').classList.toggle('d-none', !hasCases);
    document.getElementById('coverageEmpty').classList.toggle('d-none', hasCases);
    if (!hasCases) return;

    renderHero();
    renderGroups();
    renderCaseTable();
  }

  // Disjoint slices of all cases: PRIMARY-covered / covered-without-primary /
  // uncovered. (with_covers_link overlaps with_primary_link, so the legend
  // shows covered-only-by-COVERS instead.)
  function heroSlices() {
    const total = Number(state.coverage?.total_test_cases || 0);
    const primary = Number(state.coverage?.with_primary_link || 0);
    const covered = Number(state.coverage?.with_any_link || 0);
    const coversOnly = Math.max(covered - primary, 0);
    const uncovered = Math.max(total - covered, 0);
    return { total, primary, covered, coversOnly, uncovered };
  }

  function renderHero() {
    const { total, primary, covered, coversOnly, uncovered } = heroSlices();
    const pct = (value) => (total ? (value / total) * 100 : 0);

    document.getElementById('coverageRateText').textContent = total ? `${Math.round(pct(covered))}%` : '0%';
    document.getElementById('coverageCoveredOfTotal').textContent = `${formatNumber(covered)} / ${formatNumber(total)}`;
    document.getElementById('coverageBarPrimary').style.width = `${pct(primary)}%`;
    document.getElementById('coverageBarCovers').style.width = `${pct(coversOnly)}%`;
    document.getElementById('coverageBarUncovered').style.width = `${pct(uncovered)}%`;
    document.getElementById('coveragePrimaryCount').textContent = formatNumber(primary);
    document.getElementById('coverageCoversOnlyCount').textContent = formatNumber(coversOnly);
    document.getElementById('coverageUncoveredCount').textContent = formatNumber(uncovered);
  }

  function renderGroups() {
    const container = document.getElementById('coverageGroupList');
    const groups = state.coverage.by_group || [];
    if (groups.length <= 1) {
      // A single group adds no information over the hero bar.
      container.innerHTML = '';
      container.classList.add('d-none');
      return;
    }
    container.classList.remove('d-none');
    container.innerHTML = groups.map((group) => {
      const total = Number(group.total || 0);
      const covered = Number(group.covered || 0);
      const primary = Number(group.primary || 0);
      const coversOnly = Math.max(covered - primary, 0);
      const uncovered = Math.max(total - covered, 0);
      const pct = (value) => (total ? (value / total) * 100 : 0);
      const rate = total ? Math.round((covered / total) * 100) : 0;
      const isActive = state.groupFilter === group.group;
      return `
        <button type="button" class="automation-coverage-group ${isActive ? 'active' : ''}" data-group="${escapeAttr(group.group)}" title="${escapeAttr(group.group)}">
          <span class="automation-coverage-group-name font-monospace text-truncate">${escapeHtml(group.group)}</span>
          <span class="automation-coverage-bar automation-coverage-bar-sm">
            <span class="automation-coverage-bar-seg seg-primary" style="width:${pct(primary)}%"></span>
            <span class="automation-coverage-bar-seg seg-covers" style="width:${pct(coversOnly)}%"></span>
            <span class="automation-coverage-bar-seg seg-uncovered" style="width:${pct(uncovered)}%"></span>
          </span>
          <span class="automation-coverage-group-count text-muted">${formatNumber(covered)}/${formatNumber(total)}</span>
          <span class="automation-coverage-group-rate ${rate >= 80 ? 'text-success' : (rate >= 50 ? 'text-warning' : 'text-danger')}">${rate}%</span>
        </button>`;
    }).join('');
  }

  function caseGroup(caseNumber) {
    return String(caseNumber || '').split('.', 1)[0];
  }

  function renderCaseTable() {
    const rows = document.getElementById('coverageCaseRows');
    const linksHeader = document.getElementById('coverageLinksHeader');
    const isCovered = state.view === 'covered';
    linksHeader.classList.toggle('d-none', !isCovered);

    // Toggle counts + group-filter badge
    const uncoveredAll = state.coverage.uncovered_sample || [];
    const coveredAll = state.coverage.covered_cases || [];
    document.getElementById('coverageTabUncoveredCount').textContent = formatNumber(state.coverage.uncovered_count || uncoveredAll.length);
    document.getElementById('coverageTabCoveredCount').textContent = formatNumber(coveredAll.length);

    const badge = document.getElementById('coverageGroupFilterBadge');
    badge.classList.toggle('d-none', !state.groupFilter);
    if (state.groupFilter) {
      document.getElementById('coverageGroupFilterText').textContent = state.groupFilter;
    }

    const source = isCovered ? coveredAll : uncoveredAll;
    const items = state.groupFilter
      ? source.filter((item) => caseGroup(item.test_case_number) === state.groupFilter)
      : source;

    if (!items.length) {
      const emptyKey = isCovered ? 'automationHub.coverage.noCovered' : 'automationHub.coverage.noUncovered';
      const emptyFallback = isCovered ? 'No covered cases yet.' : 'All cases have automation coverage.';
      rows.innerHTML = `
        <tr>
          <td colspan="${isCovered ? 3 : 2}" class="text-center text-muted py-4">${escapeHtml(t(emptyKey, emptyFallback))}</td>
        </tr>`;
      return;
    }

    rows.innerHTML = items.map((item) => `
      <tr>
        <td class="font-monospace">${escapeHtml(item.test_case_number)}</td>
        <td>
          <div class="text-truncate automation-coverage-case-title" title="${escapeAttr(item.title)}">${escapeHtml(item.title)}</div>
        </td>
        ${isCovered ? `<td>${renderLinkBadges(item.links || [])}</td>` : ''}
      </tr>`).join('');
  }

  function renderLinkBadges(links) {
    if (!links.length) return '<span class="text-muted">—</span>';
    return `<div class="automation-coverage-links">${links.map((link) => {
      const typeClass = {
        PRIMARY: 'link-primary-badge',
        COVERS: 'link-covers-badge',
        REFERENCES: 'link-references-badge',
      }[String(link.link_type || '').toUpperCase()] || 'link-references-badge';
      const repoPrefix = link.ref_repo ? `${link.ref_repo}: ` : '';
      return `<span class="automation-coverage-link-badge ${typeClass}" title="${escapeAttr(`[${link.link_type}] ${repoPrefix}${link.ref_path}`)}">${escapeHtml(link.script_name)}</span>`;
    }).join('')}</div>`;
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
