(function () {
  // Coverage explorer — scales to thousands of manual cases.
  //   • Summary (hero) + per-group rollups load once (light payload).
  //   • Cases are fetched server-side, paginated & filtered, via
  //     /automation-coverage/cases — never the whole set at once.
  //   • Tree mode: collapsed ticket groups; expanding lazy-loads that group's
  //     cases a page at a time. Flat mode (search / group-off): one paginated
  //     list with infinite scroll.
  const PAGE = 50;

  const state = {
    teamId: null,
    summary: null,
    q: '',
    status: 'all',          // all | uncovered | covered | primary
    sort: 'pct-asc',        // pct-asc | pct-desc | size-desc | name
    groupBy: true,
    expanded: {},           // group key -> { items, total, skip, loading, hasMore }
    flat: { items: [], total: 0, skip: 0, hasMore: false, loading: false, reqId: 0 },
  };

  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('i18nReady', refreshTexts);
  document.addEventListener('languageChanged', () => { render(); refreshTexts(); });
  window.addEventListener('pageshow', refreshTexts);

  function init() {
    state.teamId = resolveTeamId();
    bindEvents();
    if (!state.teamId) return;
    loadSummary();
  }

  function mode() { return state.groupBy && !state.q ? 'tree' : 'flat'; }

  function bindEvents() {
    const refreshBtn = document.getElementById('coverageRefreshBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadSummary);

    const search = document.getElementById('coverageSearch');
    if (search) {
      let timer;
      search.addEventListener('input', (e) => {
        const value = e.target.value;
        clearTimeout(timer);
        timer = setTimeout(() => {
          state.q = value.trim();
          resetCaseState();
          if (mode() === 'flat') fetchFlat(false);
          render();
        }, 200);
      });
    }

    const statusGroup = document.getElementById('coverageStatusFilter');
    if (statusGroup) {
      statusGroup.addEventListener('click', (event) => {
        const btn = event.target.closest('[data-status]');
        if (!btn) return;
        state.status = btn.dataset.status;
        statusGroup.querySelectorAll('[data-status]').forEach((b) => b.classList.toggle('active', b === btn));
        resetCaseState();
        if (mode() === 'flat') fetchFlat(false);
        render();
      });
    }

    const sort = document.getElementById('coverageSort');
    if (sort) sort.addEventListener('change', (e) => { state.sort = e.target.value; render(); });

    const groupToggle = document.getElementById('coverageGroupToggle');
    if (groupToggle) {
      groupToggle.addEventListener('click', () => {
        state.groupBy = !state.groupBy;
        groupToggle.classList.toggle('active', state.groupBy);
        groupToggle.setAttribute('aria-pressed', String(state.groupBy));
        resetCaseState();
        if (mode() === 'flat') fetchFlat(false);
        render();
      });
    }

    const expandAll = document.getElementById('coverageExpandAll');
    if (expandAll) expandAll.addEventListener('click', toggleExpandAll);

    const list = document.getElementById('coverageList');
    if (list) list.addEventListener('click', onListClick);

    const scroll = document.getElementById('coverageScroll');
    if (scroll) {
      scroll.addEventListener('scroll', () => {
        if (mode() !== 'flat') return;
        if (state.flat.loading || !state.flat.hasMore) return;
        if (scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 80) fetchFlat(true);
      });
    }
  }

  function resetCaseState() {
    state.expanded = {};
    state.flat = { items: [], total: 0, skip: 0, hasMore: false, loading: false, reqId: state.flat.reqId };
    setExpandAllLabel(false);
  }

  async function loadSummary() {
    setLoading(true);
    try {
      state.summary = await apiFetch(`/api/teams/${state.teamId}/automation-coverage`);
      resetCaseState();
      render();
      if (mode() === 'flat') fetchFlat(false);
    } catch (error) {
      showError(error.message || t('automationHub.coverage.loadFailed', 'Failed to load coverage'));
    } finally {
      setLoading(false);
      refreshTexts();
    }
  }

  // ── data fetch (server-side pagination) ──────────────────────────
  function casesUrl(params) {
    const usp = new URLSearchParams();
    usp.set('status', state.status);
    if (state.q) usp.set('q', state.q);
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null) usp.set(k, v); });
    return `/api/teams/${state.teamId}/automation-coverage/cases?${usp.toString()}`;
  }

  async function fetchFlat(append) {
    const f = state.flat;
    if (f.loading) return;
    f.loading = true;
    const reqId = ++f.reqId;
    const skip = append ? f.skip : 0;
    if (!append) { f.items = []; f.skip = 0; }
    renderFooter();
    try {
      const page = await apiFetch(casesUrl({ skip, limit: PAGE }));
      if (reqId !== f.reqId) return;     // a newer search superseded this one
      f.items = append ? f.items.concat(page.items) : page.items;
      f.total = page.total;
      f.skip = skip + page.items.length;
      f.hasMore = page.has_next;
    } catch (error) {
      showError(error.message || t('automationHub.coverage.loadFailed', 'Failed to load coverage'));
    } finally {
      if (reqId === f.reqId) f.loading = false;
      render();
    }
  }

  async function fetchGroup(groupKey, append) {
    const g = state.expanded[groupKey];
    if (!g || g.loading) return;
    g.loading = true;
    render();
    try {
      const page = await apiFetch(casesUrl({ group: groupKey, skip: append ? g.skip : 0, limit: PAGE }));
      g.items = append ? g.items.concat(page.items) : page.items;
      g.total = page.total;
      g.skip = (append ? g.skip : 0) + page.items.length;
      g.hasMore = page.has_next;
    } catch (error) {
      showError(error.message || t('automationHub.coverage.loadFailed', 'Failed to load coverage'));
    } finally {
      g.loading = false;
      render();
    }
  }

  // ── render ───────────────────────────────────────────────────────
  function render() {
    if (!state.summary) return;
    const hasCases = Number(state.summary.total_test_cases || 0) > 0;
    document.getElementById('coverageContent').classList.toggle('d-none', !hasCases);
    document.getElementById('coverageEmpty').classList.toggle('d-none', hasCases);
    if (!hasCases) return;
    renderHero();
    if (mode() === 'tree') renderTree(); else renderFlat();
    renderFooter();
    refreshTexts(document.getElementById('coverageList'));
  }

  function heroSlices() {
    const total = Number(state.summary?.total_test_cases || 0);
    const primary = Number(state.summary?.with_primary_link || 0);
    const covered = Number(state.summary?.with_any_link || 0);
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

  function groupStatusCount(group) {
    const total = Number(group.total || 0);
    const covered = Number(group.covered || 0);
    const primary = Number(group.primary || 0);
    if (state.status === 'covered') return covered;
    if (state.status === 'uncovered') return Math.max(total - covered, 0);
    if (state.status === 'primary') return primary;
    return total;
  }

  function sortedGroups() {
    const groups = (state.summary.by_group || []).slice()
      .filter((g) => state.status === 'all' || groupStatusCount(g) > 0);
    const rate = (g) => (g.total ? g.covered / g.total : 0);
    const cmp = {
      'pct-asc': (a, b) => rate(a) - rate(b),
      'pct-desc': (a, b) => rate(b) - rate(a),
      'size-desc': (a, b) => Number(b.total) - Number(a.total),
      'name': (a, b) => String(a.group).localeCompare(String(b.group)),
    }[state.sort] || ((a, b) => rate(a) - rate(b));
    return groups.sort(cmp);
  }

  function renderTree() {
    const list = document.getElementById('coverageList');
    const groups = sortedGroups();
    if (!groups.length) { list.innerHTML = emptyRow(); return; }
    list.innerHTML = groups.map((group) => {
      const open = !!state.expanded[group.group];
      let html = groupRow(group, open);
      if (open) html += expandedBody(state.expanded[group.group]);
      return html;
    }).join('');
  }

  function expandedBody(g) {
    if (!g) return '';
    if (g.loading && !g.items.length) return loadingRow();
    if (!g.items.length) return `<div class="ac-note">${escapeHtml(t('automationHub.coverage.noResults', 'No matching cases'))}</div>`;
    let html = g.items.map((c) => caseRow(c, false)).join('');
    if (g.hasMore) {
      const remaining = Math.max(Number(g.total || 0) - g.items.length, 0);
      html += `<div class="ac-more"><button type="button" class="btn btn-link btn-sm p-0" data-more-group="${escapeAttr(g.key)}" ${g.loading ? 'disabled' : ''}>
        <i class="fas fa-angle-down me-1"></i>${escapeHtml(t('automationHub.coverage.loadMore', 'Load more'))} (${formatNumber(remaining)})</button></div>`;
    }
    return html;
  }

  function renderFlat() {
    const list = document.getElementById('coverageList');
    const f = state.flat;
    if (f.loading && !f.items.length) { list.innerHTML = loadingRow(); return; }
    if (!f.items.length) { list.innerHTML = emptyRow(); return; }
    let html = f.items.map((c) => caseRow(c, true)).join('');
    if (f.loading) html += loadingRow();
    else if (f.hasMore) {
      const remaining = Math.max(Number(f.total || 0) - f.items.length, 0);
      html += `<div class="ac-more"><button type="button" class="btn btn-link btn-sm p-0" data-more-flat="1">
        <i class="fas fa-angle-down me-1"></i>${escapeHtml(t('automationHub.coverage.loadMore', 'Load more'))} (${formatNumber(remaining)})</button></div>`;
    }
    list.innerHTML = html;
  }

  function groupRow(group, open) {
    const total = Number(group.total || 0);
    const covered = Number(group.covered || 0);
    const primary = Number(group.primary || 0);
    const coversOnly = Math.max(covered - primary, 0);
    const uncovered = Math.max(total - covered, 0);
    const pct = (v) => (total ? (v / total) * 100 : 0);
    const rate = total ? Math.round((covered / total) * 100) : 0;
    const rateClass = rate >= 80 ? 'text-success' : (rate >= 50 ? 'text-warning' : 'text-danger');
    return `
      <div class="ac-row ac-grow" data-group="${escapeAttr(group.group)}" role="button" tabindex="0" aria-expanded="${open}">
        <span class="ac-grow-name">
          <i class="fas fa-chevron-${open ? 'down' : 'right'} ac-caret" aria-hidden="true"></i>
          <span class="font-monospace text-truncate">${escapeHtml(group.group)}</span>
        </span>
        <span class="automation-coverage-bar automation-coverage-bar-sm">
          <span class="automation-coverage-bar-seg seg-primary" style="width:${pct(primary)}%"></span>
          <span class="automation-coverage-bar-seg seg-covers" style="width:${pct(coversOnly)}%"></span>
          <span class="automation-coverage-bar-seg seg-uncovered" style="width:${pct(uncovered)}%"></span>
        </span>
        <span class="ac-count text-muted text-end">${formatNumber(covered)}/${formatNumber(total)}</span>
        <span class="ac-rate text-end ${rateClass}">${rate}%</span>
      </div>`;
  }

  const STATUS_META = {
    primary: { cls: 'is-primary', label: 'PRIMARY' },
    covers: { cls: 'is-covers', label: 'COVERS' },
    uncovered: { cls: 'is-uncovered', labelKey: 'automationHub.coverage.uncovered', label: 'Uncovered' },
  };

  function caseRow(c, showGroup) {
    const meta = STATUS_META[c.status] || STATUS_META.uncovered;
    const chipLabel = meta.labelKey ? t(meta.labelKey, meta.label) : meta.label;
    const groupPrefix = showGroup ? `<span class="ac-cgroup font-monospace">${escapeHtml(caseGroup(c.test_case_number))}</span> ` : '';
    const links = (c.links && c.links.length) ? renderLinkBadges(c.links) : '';
    return `
      <div class="ac-row ac-crow${showGroup ? ' ac-crow-flat' : ''}">
        <span class="ac-cmeta">
          <span class="ac-chip ${meta.cls}">${escapeHtml(chipLabel)}</span>
          <span class="font-monospace ac-cnum">${escapeHtml(c.test_case_number)}</span>
        </span>
        <span class="ac-ctitle text-truncate" title="${escapeAttr(c.title)}">${groupPrefix}${escapeHtml(c.title)}${links}</span>
      </div>`;
  }

  function renderLinkBadges(links) {
    return `<span class="automation-coverage-links">${links.map((link) => {
      const typeClass = {
        PRIMARY: 'link-primary-badge',
        COVERS: 'link-covers-badge',
        REFERENCES: 'link-references-badge',
      }[String(link.link_type || '').toUpperCase()] || 'link-references-badge';
      const repoPrefix = link.ref_repo ? `${link.ref_repo}: ` : '';
      return `<span class="automation-coverage-link-badge ${typeClass}" title="${escapeAttr(`[${link.link_type}] ${repoPrefix}${link.ref_path}`)}">${escapeHtml(link.script_name)}</span>`;
    }).join('')}</span>`;
  }

  function loadingRow() {
    return `<div class="ac-note"><span class="spinner-border spinner-border-sm me-2" role="status"></span>${escapeHtml(t('common.loading', 'Loading...'))}</div>`;
  }

  function emptyRow() {
    return `<div class="ac-note text-muted">${escapeHtml(t('automationHub.coverage.noResults', 'No matching cases'))}</div>`;
  }

  function renderFooter() {
    if (!state.summary) return;
    const { total, covered, uncovered } = heroSlices();
    document.getElementById('coverageFootLeft').textContent =
      tp('automationHub.coverage.footSummary', { total: formatNumber(total), covered: formatNumber(covered), uncovered: formatNumber(uncovered) },
        `${formatNumber(total)} cases · ${formatNumber(covered)} covered · ${formatNumber(uncovered)} uncovered`);
    const right = document.getElementById('coverageFootRight');
    if (mode() === 'flat') {
      right.textContent = tp('automationHub.coverage.footMatches', { n: formatNumber(state.flat.total) }, `${formatNumber(state.flat.total)} matches`);
    } else {
      right.textContent = t('automationHub.coverage.footTreeHint', 'Click a group to expand its cases');
    }
  }

  // ── interactions ─────────────────────────────────────────────────
  function onListClick(event) {
    const more = event.target.closest('[data-more-group]');
    if (more) { fetchGroup(more.dataset.moreGroup, true); return; }
    if (event.target.closest('[data-more-flat]')) { fetchFlat(true); return; }
    const groupRowEl = event.target.closest('[data-group]');
    if (groupRowEl) toggleGroup(groupRowEl.dataset.group);
  }

  function toggleGroup(key) {
    if (state.expanded[key]) {
      delete state.expanded[key];
      render();
    } else {
      state.expanded[key] = { key, items: [], total: 0, skip: 0, loading: false, hasMore: false };
      render();
      fetchGroup(key, false);
    }
  }

  function toggleExpandAll() {
    const groups = sortedGroups();
    const allOpen = groups.length && groups.every((g) => state.expanded[g.group]);
    if (allOpen) {
      state.expanded = {};
      setExpandAllLabel(false);
      render();
    } else {
      setExpandAllLabel(true);
      groups.forEach((g) => {
        if (!state.expanded[g.group]) {
          state.expanded[g.group] = { key: g.group, items: [], total: 0, skip: 0, loading: false, hasMore: false };
          fetchGroup(g.group, false);
        }
      });
      render();
    }
  }

  function setExpandAllLabel(allOpen) {
    const btn = document.getElementById('coverageExpandAll');
    if (!btn) return;
    btn.innerHTML = `<i class="fas fa-angle-double-${allOpen ? 'up' : 'down'} me-1" aria-hidden="true"></i><span data-i18n="automationHub.coverage.${allOpen ? 'collapseAll' : 'expandAll'}">${allOpen ? 'Collapse all' : 'Expand all'}</span>`;
    refreshTexts(btn);
  }

  function caseGroup(caseNumber) {
    return String(caseNumber || '').split('.', 1)[0];
  }

  // ── helpers ──────────────────────────────────────────────────────
  function setLoading(isLoading) {
    document.getElementById('coverageLoading').classList.toggle('d-none', !isLoading);
  }

  async function apiFetch(url, options) {
    const response = await window.AuthClient.fetch(url, options || {});
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(extractApiErrorMessage(data, response));
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

  function tp(key, params, fallback) {
    return window.i18n && window.i18n.t ? window.i18n.t(key, params || {}, fallback) : fallback;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[char]));
  }

  function escapeAttr(value) {
    return escapeHtml(value);
  }
})();
