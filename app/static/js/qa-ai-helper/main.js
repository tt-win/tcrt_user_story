(function () {
  const state = {
    bootstrapped: false,
    teamId: null,
    setId: null,
    sessionId: null,
    workspace: null,
    sessions: [],
    sets: [],
    selectedDraftKey: null,
    activePhaseView: 'fetch',
  };

  const PHASE_ORDER = ['fetch', 'canonical', 'plan', 'draft'];

  function el(id) {
    return document.getElementById(id);
  }

  function t(key, params, fallback) {
    if (window.i18n && typeof window.i18n.t === 'function' && window.i18n.isReady()) {
      return window.i18n.t(key, params || {}, fallback || key);
    }
    return fallback || key;
  }

  function splitLines(raw) {
    return String(raw || '')
      .split('\n')
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function joinLines(items) {
    return (items || []).map((item) => String(item || '').trim()).filter(Boolean).join('\n');
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value || {}));
  }

  function pageRoot() {
    return el('qaAiHelperPage');
  }

  function normalizeLocale(raw) {
    const value = String(raw || '').trim().toLowerCase();
    if (!value) return 'zh-TW';
    if (value === 'zh-cn') return 'zh-CN';
    if (value === 'zh-tw') return 'zh-TW';
    if (value === 'en-us' || value === 'en') return 'en';
    return raw;
  }

  function currentOutputLocale() {
    return normalizeLocale(el('qaHelperOutputLocale') ? el('qaHelperOutputLocale').value : 'zh-TW');
  }

  function currentCanonicalLanguage() {
    return normalizeLocale(el('qaHelperCanonicalLanguage') ? el('qaHelperCanonicalLanguage').value : 'zh-TW');
  }

  function getCurrentTeamFromStorage() {
    if (window.AppUtils && typeof window.AppUtils.getCurrentTeam === 'function') {
      const team = window.AppUtils.getCurrentTeam();
      if (team && team.id) return team;
    }
    try {
      const raw = localStorage.getItem('currentTeam');
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && parsed.id) return parsed;
      }
    } catch (_) {
      // noop
    }
    const id = localStorage.getItem('currentTeamId');
    return id ? { id: Number(id) } : null;
  }

  function ensureTeamId() {
    if (state.teamId) return state.teamId;
    const root = pageRoot();
    const fromPage = Number((root && root.dataset.teamId) || 0);
    if (fromPage) {
      state.teamId = fromPage;
      return state.teamId;
    }
    const stored = getCurrentTeamFromStorage();
    if (stored && stored.id) {
      state.teamId = Number(stored.id);
      return state.teamId;
    }
    return null;
  }

  async function authFetch(url, options) {
    if (window.AuthClient && typeof window.AuthClient.fetch === 'function') {
      return window.AuthClient.fetch(url, options || {});
    }
    return fetch(url, options || {});
  }

  function setFeedback(level, message) {
    const box = el('qaHelperFeedbackBox');
    if (!box) return;
    box.className = `alert alert-${level}`;
    box.classList.remove('d-none');
    box.textContent = message;
  }

  function clearFeedback() {
    const box = el('qaHelperFeedbackBox');
    if (!box) return;
    box.className = 'alert alert-info d-none';
    box.textContent = '';
  }

  function confirmAction(message) {
    return window.confirm(message);
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function selectedReferences() {
    const selected = (((state.workspace || {}).planned_revision || {}).selected_references || {});
    return clone(selected.section_references ? selected : { section_references: {} });
  }

  function availablePhases() {
    const phases = new Set(['fetch']);
    if (state.sessionId) phases.add('canonical');
    if ((state.workspace || {}).canonical_revision) phases.add('plan');
    if ((state.workspace || {}).planned_revision) phases.add('draft');
    return phases;
  }

  function inferPhaseView() {
    const workspace = state.workspace || {};
    if (workspace.draft_set) return 'draft';
    if (workspace.planned_revision) return 'plan';
    if (workspace.canonical_revision || state.sessionId) return 'canonical';
    return 'fetch';
  }

  function setActivePhaseView(phase, options) {
    const nextPhase = String(phase || '').trim() || inferPhaseView();
    const available = availablePhases();
    if (!((options || {}).force) && !available.has(nextPhase)) return;
    state.activePhaseView = nextPhase;
  }

  function phaseDescription(phase) {
    const descriptions = {
      fetch: t('qaAiHelper.phaseFetchHint', {}, 'Step 1：建立 session、抓 ticket，先確認 raw source。'),
      canonical: t('qaAiHelper.phaseCanonicalHint', {}, 'Step 2：整理 canonical sections，鎖定需求內容。'),
      plan: t('qaAiHelper.phasePlanHint', {}, 'Step 3：檢查 verification matrix、references 與 requirement delta。'),
      draft: t('qaAiHelper.phaseDraftHint', {}, 'Step 4：產生並編修 testcase drafts，確認後 commit。'),
    };
    return descriptions[phase] || '';
  }

  function renderPhaseWorkflow() {
    const available = availablePhases();
    if (!available.has(state.activePhaseView)) {
      state.activePhaseView = inferPhaseView();
    }
    const activeIndex = PHASE_ORDER.indexOf(state.activePhaseView);
    const fetchPanel = el('qaHelperFetchPanel');
    const mainCol = el('qaHelperPhaseMainCol');

    PHASE_ORDER.forEach((phase) => {
      const button = document.querySelector(`[data-phase-target="${phase}"]`);
      if (button) {
        button.disabled = !available.has(phase);
        button.classList.toggle('is-active', phase === state.activePhaseView);
        button.setAttribute('aria-selected', phase === state.activePhaseView ? 'true' : 'false');
      }
      document.querySelectorAll(`[data-phase-panel="${phase}"]`).forEach((node) => {
        node.classList.toggle('is-active', phase === state.activePhaseView);
      });
    });

    if (fetchPanel) {
      fetchPanel.classList.toggle('col-xl-12', state.activePhaseView === 'fetch');
      fetchPanel.classList.toggle('col-xl-4', state.activePhaseView !== 'fetch');
    }
    if (mainCol) {
      const showMain = state.activePhaseView !== 'fetch';
      mainCol.classList.toggle('d-none', !showMain);
      mainCol.classList.toggle('col-xl-8', false);
      mainCol.classList.toggle('col-xl-12', showMain);
    }

    const description = el('qaHelperPhaseDescription');
    if (description) {
      description.textContent = phaseDescription(state.activePhaseView);
    }

    const prevBtn = el('qaHelperPrevPhaseBtn');
    const nextBtn = el('qaHelperNextPhaseBtn');
    if (prevBtn) prevBtn.disabled = activeIndex <= 0;
    if (nextBtn) {
      const nextPhase = PHASE_ORDER[activeIndex + 1];
      nextBtn.disabled = !nextPhase || !available.has(nextPhase);
    }
  }

  function updateUrl() {
    const params = new URLSearchParams(window.location.search);
    if (state.teamId) {
      params.set('team_id', String(state.teamId));
    } else {
      params.delete('team_id');
    }
    if (state.setId) {
      params.set('set_id', String(state.setId));
    } else {
      params.delete('set_id');
    }
    if (state.sessionId) {
      params.set('session_id', String(state.sessionId));
    } else {
      params.delete('session_id');
    }
    const ticketKey = String(el('qaHelperTicketKey') ? el('qaHelperTicketKey').value : '').trim();
    if (ticketKey) {
      params.set('ticket_key', ticketKey);
    } else {
      params.delete('ticket_key');
    }
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`);
  }

  async function ensureSessionExists() {
    if (state.sessionId) return state.sessionId;
    await createSession({ silent: true });
    return state.sessionId;
  }

  async function createSession(options) {
    const silent = !!((options || {}).silent);
    clearFeedback();
    const teamId = ensureTeamId();
    const setId = Number(el('qaHelperTargetSetSelect').value || 0);
    const ticketKey = String(el('qaHelperTicketKey').value || '').trim();
    if (!teamId) {
      setFeedback('warning', t('qaAiHelper.errorTeamRequired', {}, '請先選擇團隊'));
      return null;
    }
    if (!setId) {
      setFeedback('warning', t('qaAiHelper.errorSetRequired', {}, '請先選擇目標 Test Case Set'));
      return null;
    }
    const payload = {
      target_test_case_set_id: setId,
      ticket_key: ticketKey || null,
      include_comments: !!el('qaHelperIncludeComments').checked,
      output_locale: currentOutputLocale(),
      canonical_language: currentCanonicalLanguage(),
      counter_settings: {
        middle: String(el('qaHelperMiddle').value || '010').trim(),
        tail: String(el('qaHelperTail').value || '010').trim(),
      },
    };
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'create session failed');
    }
    const workspace = await response.json();
    updateWorkspace(workspace);
    await loadSessions();
    if (!silent) {
      setFeedback('success', t('qaAiHelper.sessionCreated', {}, '已建立 Session'));
    }
    return workspace;
  }

  async function loadWorkspace(sessionId) {
    const teamId = ensureTeamId();
    if (!teamId || !sessionId) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}`);
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || 'load workspace failed');
    }
    const workspace = await response.json();
    updateWorkspace(workspace);
  }

  async function loadSets() {
    const teamId = ensureTeamId();
    if (!teamId) {
      state.sets = [];
      renderTargetSetSelect();
      return;
    }
    const response = await authFetch(`/api/teams/${teamId}/test-case-sets`);
    if (!response.ok) {
      throw new Error(await response.text());
    }
    state.sets = await response.json();
    renderTargetSetSelect();
  }

  async function loadSessions() {
    const teamId = ensureTeamId();
    if (!teamId) {
      state.sessions = [];
      renderSessionSelect();
      return;
    }
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions?limit=200&offset=0`);
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const payload = await response.json();
    state.sessions = payload.items || [];
    renderSessionSelect();
  }

  function sessionLabel(item) {
    const session = item.session || {};
    const ticketKey = session.ticket_key || t('qaAiHelper.noTicket', {}, '未綁定 Ticket');
    return `${ticketKey} (#${session.id})`;
  }

  function renderSessionSelect() {
    const select = el('qaHelperSessionSelect');
    if (!select) return;
    const currentId = state.sessionId ? String(state.sessionId) : '';
    const options = [
      `<option value="">${escapeHtml(t('qaAiHelper.selectSession', {}, '選擇 Session'))}</option>`,
    ];
    (state.sessions || []).forEach((item) => {
      const session = item.session || {};
      const selected = String(session.id) === currentId ? ' selected' : '';
      options.push(`<option value="${session.id}"${selected}>${escapeHtml(sessionLabel(item))}</option>`);
    });
    select.innerHTML = options.join('');
  }

  function renderTargetSetSelect() {
    const select = el('qaHelperTargetSetSelect');
    if (!select) return;
    const current = state.setId || Number((pageRoot() && pageRoot().dataset.setId) || 0);
    const options = [
      `<option value="">${escapeHtml(t('qaAiHelper.selectTargetSet', {}, '請選擇目標 Test Case Set'))}</option>`,
    ];
    (state.sets || []).forEach((item) => {
      const selected = Number(item.id) === Number(current) ? ' selected' : '';
      options.push(`<option value="${item.id}"${selected}>${escapeHtml(item.name)}</option>`);
    });
    select.innerHTML = options.join('');
  }

  function updateWorkspace(workspace) {
    state.workspace = workspace;
    state.sessionId = workspace && workspace.session ? workspace.session.id : null;
    state.setId = workspace && workspace.session ? workspace.session.target_test_case_set_id : state.setId;
    state.activePhaseView = inferPhaseView();
    populateFormFromWorkspace();
    renderAll();
    updateUrl();
  }

  function populateFormFromWorkspace() {
    const workspace = state.workspace;
    if (!workspace) return;
    const session = workspace.session || {};
    const canonical = workspace.canonical_revision || {};
    const planned = workspace.planned_revision || {};
    const content = canonical.content || {};
    const counters = canonical.counter_settings || planned.counter_settings || {};
    el('qaHelperTicketKey').value = session.ticket_key || el('qaHelperTicketKey').value || '';
    el('qaHelperIncludeComments').checked = !!session.include_comments;
    el('qaHelperOutputLocale').value = normalizeLocale(session.output_locale || 'zh-TW');
    el('qaHelperCanonicalLanguage').value = normalizeLocale(canonical.canonical_language || session.canonical_language || 'zh-TW');
    el('qaHelperTargetSetSelect').value = String(session.target_test_case_set_id || state.setId || '');
    el('qaHelperMiddle').value = counters.middle || el('qaHelperMiddle').value || '010';
    el('qaHelperTail').value = counters.tail || el('qaHelperTail').value || '010';
    el('qaHelperUserStory').value = content.userStoryNarrative || '';
    el('qaHelperCriteria').value = content.criteria || '';
    el('qaHelperTechnicalSpecs').value = content.technicalSpecifications || '';
    el('qaHelperAcceptanceCriteria').value = content.acceptanceCriteria || '';
    el('qaHelperAssumptions').value = joinLines(content.assumptions || []);
    el('qaHelperUnknowns').value = joinLines(content.unknowns || []);
  }

  function renderWorkspaceSummary() {
    const container = el('qaHelperWorkspaceSummary');
    const badge = el('qaHelperPhaseBadge');
    if (!container || !badge) return;
    const workspace = state.workspace;
    if (!workspace || !workspace.session) {
      badge.className = 'badge text-bg-secondary';
      badge.textContent = t('qaAiHelper.noSession', {}, '尚未建立 Session');
      container.innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.sessionSummaryEmpty', {}, '建立 Session 後會顯示 revision、lock 與 draft 狀態。'))}</div>`;
      return;
    }
    const session = workspace.session;
    const planned = workspace.planned_revision;
    const draftSet = workspace.draft_set;
    badge.className = session.status === 'completed' ? 'badge text-bg-success' : 'badge text-bg-info';
    badge.textContent = `${session.current_phase} / ${session.status}`;
    container.innerHTML = `
      <dl class="qa-helper-kv mb-0">
        <dt>${escapeHtml(t('qaAiHelper.sessionId', {}, 'Session ID'))}</dt>
        <dd class="qa-helper-mono">#${session.id}</dd>
        <dt>${escapeHtml(t('qaAiHelper.canonicalRevision', {}, 'Canonical Revision'))}</dt>
        <dd>${workspace.canonical_revision ? `#${workspace.canonical_revision.revision_number} (${workspace.canonical_revision.status})` : '-'}</dd>
        <dt>${escapeHtml(t('qaAiHelper.plannedRevision', {}, 'Planned Revision'))}</dt>
        <dd>${planned ? `#${planned.revision_number} (${planned.status})` : '-'}</dd>
        <dt>${escapeHtml(t('qaAiHelper.draftSet', {}, 'Draft Set'))}</dt>
        <dd>${draftSet ? `#${draftSet.id} (${draftSet.status})` : '-'}</dd>
      </dl>
    `;
  }

  function renderSourceTable() {
    const tbody = el('qaHelperSourceTable') ? el('qaHelperSourceTable').querySelector('tbody') : null;
    if (!tbody) return;
    const blocks = ((state.workspace || {}).source_payload || {}).source_blocks || [];
    if (!blocks.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="text-center text-muted py-3">${escapeHtml(t('qaAiHelper.sourceEmpty', {}, '尚未抓取任何 raw source'))}</td></tr>`;
      return;
    }
    tbody.innerHTML = blocks.map((block) => `
      <tr>
        <td>${escapeHtml(block.source_type || '-')}</td>
        <td>${escapeHtml(block.language || '-')}</td>
        <td>${escapeHtml(block.title || '-')}</td>
        <td><details><summary>${escapeHtml(t('common.view', {}, '檢視'))}</summary><div class="mt-2 qa-helper-mono">${escapeHtml(block.content || '')}</div></details></td>
      </tr>
    `).join('');
  }

  function renderCanonicalValidation() {
    const box = el('qaHelperCanonicalValidationBox');
    if (!box) return;
    const validation = (state.workspace || {}).canonical_validation || {};
    if (!Object.keys(validation).length) {
      box.className = 'alert alert-secondary mt-3 mb-0';
      box.textContent = t('qaAiHelper.canonicalValidationEmpty', {}, '尚未有 canonical validation 結果');
      return;
    }
    const missingSections = validation.missing_sections || [];
    const missingFields = validation.missing_fields || [];
    const unresolved = validation.unresolved_items || [];
    box.className = validation.quality_level === 'high' ? 'alert alert-success mt-3 mb-0' : 'alert alert-warning mt-3 mb-0';
    box.innerHTML = `
      <div class="fw-semibold mb-2">${escapeHtml(t('qaAiHelper.canonicalValidationTitle', {}, 'Canonical Validation'))}</div>
      <div>${escapeHtml(t('qaAiHelper.qualityLevel', { level: validation.quality_level || '-' }, `品質等級：${validation.quality_level || '-'}`))}</div>
      <div>${escapeHtml(t('qaAiHelper.missingSections', {}, '缺漏段落'))}: ${escapeHtml(missingSections.join(', ') || '-')}</div>
      <div>${escapeHtml(t('qaAiHelper.missingFields', {}, '缺漏欄位'))}: ${escapeHtml(missingFields.join(', ') || '-')}</div>
      <div>${escapeHtml(t('qaAiHelper.unresolvedItems', {}, 'Unresolved'))}: ${escapeHtml(unresolved.join(', ') || '-')}</div>
    `;
  }

  function sectionList() {
    return ((((state.workspace || {}).planned_revision || {}).matrix || {}).sections || []);
  }

  function flattenedRows() {
    const rows = [];
    sectionList().forEach((section) => {
      (((section.matrix || {}).row_groups) || []).forEach((group) => {
        (group.rows || []).forEach((row) => {
          rows.push({
            section_id: section.section_id,
            scenario_title: section.scenario_title,
            group_key: group.group_key,
            group_label: group.label,
            row_key: row.row_key,
            applicability: row.applicability,
            axis_values: row.axis_values || {},
            override_reason: row.override_reason || '',
          });
        });
      });
    });
    return rows;
  }

  function renderSectionFilters() {
    const planFilter = el('qaHelperPlanSectionFilter');
    const refFilter = el('qaHelperReferenceSectionSelect');
    const sections = sectionList();
    const options = [`<option value="">${escapeHtml(t('common.all', {}, '全部'))}</option>`];
    sections.forEach((section) => {
      options.push(`<option value="${section.section_id}">${escapeHtml(`${section.section_id} ${section.scenario_title}`)}</option>`);
    });
    if (planFilter) planFilter.innerHTML = options.join('');
    if (refFilter) {
      refFilter.innerHTML = options.join('');
      if (!refFilter.value && sections.length) {
        refFilter.value = sections[0].section_id;
      }
    }
  }

  function currentReferenceSectionId() {
    return String((el('qaHelperReferenceSectionSelect') || {}).value || '').trim();
  }

  function renderReferenceEditor() {
    const textarea = el('qaHelperReferencesInput');
    if (!textarea) return;
    const sectionId = currentReferenceSectionId();
    const references = selectedReferences();
    const entries = ((references.section_references || {})[sectionId] || []).map((item) => item.title || item.text || item.reference_id || '').filter(Boolean);
    textarea.value = entries.join('\n');
  }

  function planFilterRows() {
    const sectionId = String((el('qaHelperPlanSectionFilter') || {}).value || '').trim();
    const status = String((el('qaHelperPlanStatusFilter') || {}).value || 'all').trim();
    const query = String((el('qaHelperPlanSearch') || {}).value || '').trim().toLowerCase();
    return flattenedRows().filter((row) => {
      if (sectionId && row.section_id !== sectionId) return false;
      if (status !== 'all' && row.applicability !== status) return false;
      if (!query) return true;
      const haystack = [row.section_id, row.scenario_title, row.group_key, row.row_key, JSON.stringify(row.axis_values)].join(' ').toLowerCase();
      return haystack.includes(query);
    });
  }

  function renderPlanTable() {
    const tbody = el('qaHelperPlanTable') ? el('qaHelperPlanTable').querySelector('tbody') : null;
    if (!tbody) return;
    const rows = planFilterRows();
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-3">${escapeHtml(t('qaAiHelper.noPlanRows', {}, '尚無可顯示的 planning rows'))}</td></tr>`;
      renderImpactPreview();
      return;
    }
    tbody.innerHTML = rows.map((row) => `
      <tr>
        <td><input type="checkbox" class="form-check-input qa-helper-row-check" value="${escapeHtml(row.row_key)}"></td>
        <td><div class="qa-helper-mono">${escapeHtml(row.section_id)}</div><div>${escapeHtml(row.scenario_title)}</div></td>
        <td>${escapeHtml(row.group_key)}</td>
        <td class="qa-helper-mono">${escapeHtml(row.row_key)}</td>
        <td class="qa-helper-mono">${escapeHtml(Object.entries(row.axis_values || {}).map(([key, value]) => `${key}=${value}`).join(', ') || '-')}</td>
        <td><span class="qa-helper-pill">${escapeHtml(row.applicability)}</span></td>
      </tr>
    `).join('');
    renderImpactPreview();
  }

  function renderPlanSummary() {
    const container = el('qaHelperPlanSummary');
    if (!container) return;
    const planned = (state.workspace || {}).planned_revision;
    if (!planned) {
      container.innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.planSummaryEmpty', {}, '尚未建立 plan'))}</div>`;
      return;
    }
    const matrix = planned.matrix || {};
    const sections = matrix.sections || [];
    const rows = flattenedRows().length;
    const items = (matrix.generation_items || []).length;
    const locked = planned.status === 'locked';
    container.innerHTML = `
      <dl class="qa-helper-kv mb-0">
        <dt>${escapeHtml(t('qaAiHelper.planRevision', {}, 'Plan Revision'))}</dt>
        <dd>#${planned.revision_number} (${escapeHtml(planned.status)})</dd>
        <dt>${escapeHtml(t('qaAiHelper.sectionCount', {}, 'Sections'))}</dt>
        <dd>${sections.length}</dd>
        <dt>${escapeHtml(t('qaAiHelper.rowCount', {}, 'Rows'))}</dt>
        <dd>${rows}</dd>
        <dt>${escapeHtml(t('qaAiHelper.generationItems', {}, 'Generation Items'))}</dt>
        <dd>${items}</dd>
        <dt>${escapeHtml(t('qaAiHelper.lockState', {}, 'Lock 狀態'))}</dt>
        <dd>${locked ? escapeHtml(t('qaAiHelper.locked', {}, '已鎖定')) : escapeHtml(t('qaAiHelper.unlocked', {}, '未鎖定'))}</dd>
      </dl>
    `;
  }

  function selectedRowKeys() {
    return Array.from(document.querySelectorAll('.qa-helper-row-check:checked')).map((node) => node.value);
  }

  function renderImpactPreview() {
    const box = el('qaHelperImpactPreview');
    if (!box) return;
    const selectedCount = selectedRowKeys().length;
    const draftSet = (state.workspace || {}).draft_set;
    const planned = (state.workspace || {}).planned_revision;
    const notes = [];
    notes.push(t('qaAiHelper.selectedRowsPreview', { count: selectedCount }, `本次選取 ${selectedCount} 筆 row`));
    if (planned && planned.status === 'locked') {
      notes.push(t('qaAiHelper.lockInvalidationPreview', {}, '任何 planning override 或 requirement delta 都會使 lock 失效。'));
    }
    if (draftSet && draftSet.status === 'active') {
      notes.push(t('qaAiHelper.outdatedDraftPreview', {}, '若 plan 改變，現有 active draft set 會被標記為 outdated。'));
    }
    box.innerHTML = notes.map((line) => `<div>${escapeHtml(line)}</div>`).join('');
  }

  function currentDraftSet() {
    return (state.workspace || {}).draft_set || null;
  }

  function renderDraftSummary() {
    const box = el('qaHelperDraftSummary');
    if (!box) return;
    const draftSet = currentDraftSet();
    if (!draftSet) {
      box.className = 'alert alert-secondary mb-3';
      box.textContent = t('qaAiHelper.draftSummaryEmpty', {}, '尚未產生 drafts');
      return;
    }
    const summary = draftSet.summary || {};
    box.className = summary.ok ? 'alert alert-success mb-3' : 'alert alert-warning mb-3';
    box.innerHTML = `
      <div class="fw-semibold">#${draftSet.id} (${escapeHtml(draftSet.status)})</div>
      <div>${escapeHtml(t('qaAiHelper.validationStatus', {}, 'Validation'))}: ${summary.ok ? 'OK' : 'FAILED'}</div>
      <div>${escapeHtml(t('qaAiHelper.errorCount', {}, 'Errors'))}: ${summary.error_count || 0}</div>
      <div>${escapeHtml(t('qaAiHelper.draftCount', {}, 'Drafts'))}: ${(draftSet.drafts || []).length}</div>
    `;
  }

  function ensureSelectedDraft() {
    const draftSet = currentDraftSet();
    const drafts = (draftSet && draftSet.drafts) || [];
    if (!drafts.length) {
      state.selectedDraftKey = null;
      return null;
    }
    if (!state.selectedDraftKey || !drafts.some((item) => item.item_key === state.selectedDraftKey)) {
      state.selectedDraftKey = drafts[0].item_key;
    }
    return drafts.find((item) => item.item_key === state.selectedDraftKey) || drafts[0];
  }

  function renderDraftList() {
    const list = el('qaHelperDraftList');
    if (!list) return;
    const draftSet = currentDraftSet();
    const drafts = (draftSet && draftSet.drafts) || [];
    if (!drafts.length) {
      list.innerHTML = `<div class="list-group-item qa-helper-empty">${escapeHtml(t('qaAiHelper.noDrafts', {}, '尚未有 draft items'))}</div>`;
      return;
    }
    ensureSelectedDraft();
    list.innerHTML = drafts.map((item) => {
      const active = item.item_key === state.selectedDraftKey ? ' active' : '';
      const body = item.body || {};
      return `
        <button type="button" class="list-group-item list-group-item-action${active}" data-draft-key="${escapeHtml(item.item_key)}">
          <div class="fw-semibold qa-helper-mono">${escapeHtml(item.testcase_id || item.item_key)}</div>
          <div>${escapeHtml(body.title || item.item_key)}</div>
        </button>
      `;
    }).join('');
  }

  function renderDraftEditor() {
    const draft = ensureSelectedDraft();
    const disabled = !draft;
    ['qaHelperDraftTitle', 'qaHelperDraftPriority', 'qaHelperDraftPreconditions', 'qaHelperDraftSteps', 'qaHelperDraftExpected', 'qaHelperSaveDraftBtn'].forEach((id) => {
      if (el(id)) el(id).disabled = disabled;
    });
    if (!draft) {
      el('qaHelperDraftTitle').value = '';
      el('qaHelperDraftPriority').value = 'Medium';
      el('qaHelperDraftPreconditions').value = '';
      el('qaHelperDraftSteps').value = '';
      el('qaHelperDraftExpected').value = '';
      el('qaHelperDraftTrace').innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.noDraftSelected', {}, '請先選擇 draft'))}</div>`;
      return;
    }
    const body = draft.body || {};
    const trace = draft.trace || {};
    el('qaHelperDraftTitle').value = body.title || '';
    el('qaHelperDraftPriority').value = body.priority || 'Medium';
    el('qaHelperDraftPreconditions').value = joinLines(body.preconditions || []);
    el('qaHelperDraftSteps').value = joinLines(body.steps || []);
    el('qaHelperDraftExpected').value = joinLines(body.expected_results || []);
    el('qaHelperDraftTrace').innerHTML = `
      <dl class="qa-helper-kv mb-0">
        <dt>${escapeHtml(t('qaAiHelper.section', {}, 'Section'))}</dt>
        <dd>${escapeHtml(trace.section_id || '-')}</dd>
        <dt>${escapeHtml(t('qaAiHelper.coverage', {}, 'Coverage'))}</dt>
        <dd>${escapeHtml(trace.coverage_category || '-')}</dd>
        <dt>${escapeHtml(t('qaAiHelper.assertions', {}, 'Assertions'))}</dt>
        <dd class="qa-helper-mono">${escapeHtml((trace.assertion_refs || []).join(', ') || '-')}</dd>
        <dt>${escapeHtml(t('qaAiHelper.references', {}, 'References'))}</dt>
        <dd class="qa-helper-mono">${escapeHtml((trace.reference_ids_used || []).join(', ') || '-')}</dd>
      </dl>
    `;
  }

  function renderAll() {
    renderPhaseWorkflow();
    renderTargetSetSelect();
    renderSessionSelect();
    renderWorkspaceSummary();
    renderSourceTable();
    renderCanonicalValidation();
    renderSectionFilters();
    renderReferenceEditor();
    renderPlanTable();
    renderPlanSummary();
    renderDraftSummary();
    renderDraftList();
    renderDraftEditor();
  }

  async function fetchTicket() {
    clearFeedback();
    const teamId = ensureTeamId();
    const sessionId = await ensureSessionExists();
    if (!teamId || !sessionId) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}/ticket`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ticket_key: String(el('qaHelperTicketKey').value || '').trim() || null,
        include_comments: !!el('qaHelperIncludeComments').checked,
      }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('canonical');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.ticketFetched', {}, 'Ticket 抓取完成'));
  }

  async function saveCanonical() {
    clearFeedback();
    const teamId = ensureTeamId();
    const sessionId = await ensureSessionExists();
    if (!teamId || !sessionId) return;
    const payload = {
      canonical_language: currentCanonicalLanguage(),
      counter_settings: {
        middle: String(el('qaHelperMiddle').value || '010').trim(),
        tail: String(el('qaHelperTail').value || '010').trim(),
      },
      content: {
        userStoryNarrative: String(el('qaHelperUserStory').value || '').trim(),
        criteria: String(el('qaHelperCriteria').value || '').trim(),
        technicalSpecifications: String(el('qaHelperTechnicalSpecs').value || '').trim(),
        acceptanceCriteria: String(el('qaHelperAcceptanceCriteria').value || '').trim(),
        assumptions: splitLines(el('qaHelperAssumptions').value),
        unknowns: splitLines(el('qaHelperUnknowns').value),
      },
    };
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}/canonical-revisions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('plan');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.canonicalSaved', {}, '已儲存 canonical revision'));
  }

  async function planWorkspace() {
    clearFeedback();
    const teamId = ensureTeamId();
    const sessionId = state.sessionId;
    if (!teamId || !sessionId) return;
    const canonicalRevision = (state.workspace || {}).canonical_revision;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        canonical_revision_id: canonicalRevision ? canonicalRevision.id : null,
        selected_references: selectedReferences(),
      }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('plan');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.planReady', {}, '已建立 deterministic plan'));
  }

  function referencesFromEditor() {
    const mapping = selectedReferences();
    const sectionId = currentReferenceSectionId();
    mapping.section_references = mapping.section_references || {};
    mapping.section_references[sectionId] = splitLines(el('qaHelperReferencesInput').value).map((line, index) => ({
      reference_id: `manual-${index + 1}`,
      title: line,
      text: line,
    }));
    return mapping;
  }

  async function saveReferences() {
    clearFeedback();
    const teamId = ensureTeamId();
    const sessionId = state.sessionId;
    if (!teamId || !sessionId) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}/planning-overrides`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        overrides: [],
        selected_references: referencesFromEditor(),
        counter_settings: {
          middle: String(el('qaHelperMiddle').value || '010').trim(),
          tail: String(el('qaHelperTail').value || '010').trim(),
        },
      }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('plan');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.referencesSaved', {}, '已更新 section references'));
  }

  async function applyOverrides() {
    clearFeedback();
    const teamId = ensureTeamId();
    const sessionId = state.sessionId;
    const rowKeys = selectedRowKeys();
    if (!teamId || !sessionId || !rowKeys.length) {
      setFeedback('warning', t('qaAiHelper.noRowsSelected', {}, '請先選取 rows'));
      return;
    }
    const status = String(el('qaHelperBulkStatus').value || 'applicable').trim();
    const reason = String(el('qaHelperBulkReason').value || '').trim() || null;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}/planning-overrides`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        overrides: rowKeys.map((rowKey) => ({ row_key: rowKey, status, reason })),
        selected_references: referencesFromEditor(),
        counter_settings: {
          middle: String(el('qaHelperMiddle').value || '010').trim(),
          tail: String(el('qaHelperTail').value || '010').trim(),
        },
      }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('plan');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.overrideApplied', {}, '已套用 planning override'));
  }

  async function applyRequirementDelta() {
    clearFeedback();
    const teamId = ensureTeamId();
    const sessionId = state.sessionId;
    if (!teamId || !sessionId) return;
    const payload = {
      delta_type: String(el('qaHelperDeltaType').value || 'add').trim(),
      target_scope: String(el('qaHelperDeltaScope').value || '').trim(),
      target_requirement_key: String(el('qaHelperDeltaRequirementKey').value || '').trim() || null,
      target_scenario_key: String(el('qaHelperDeltaScenarioKey').value || '').trim() || null,
      proposed_content: {
        title: String(el('qaHelperDeltaTitle').value || '').trim(),
        text: String(el('qaHelperDeltaContent').value || '').trim(),
        original_text: String(el('qaHelperDeltaOriginalText').value || '').trim() || null,
      },
      reason: String(el('qaHelperDeltaReason').value || '').trim(),
    };
    if (!payload.reason) {
      setFeedback('warning', t('qaAiHelper.deltaReasonRequired', {}, '請填寫 requirement delta 原因'));
      return;
    }
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}/requirement-deltas`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('plan');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.deltaApplied', {}, '已套用 requirement delta 並重建 plan'));
  }

  async function lockPlanning() {
    const teamId = ensureTeamId();
    const planned = (state.workspace || {}).planned_revision;
    if (!teamId || !planned) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/lock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ planned_revision_id: planned.id }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('plan');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.locked', {}, '已鎖定'));
  }

  async function unlockPlanning() {
    const teamId = ensureTeamId();
    if (!teamId || !state.sessionId) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/unlock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('plan');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.unlocked', {}, '已解鎖'));
  }

  async function generateDrafts(confirmExhaustive) {
    const teamId = ensureTeamId();
    if (!teamId || !state.sessionId) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        confirm_exhaustive: !!confirmExhaustive,
      }),
    });
    if (!response.ok) {
      const text = await response.text();
      if (!confirmExhaustive && text.includes('budget')) {
        const confirmed = confirmAction(t('qaAiHelper.confirmExhaustivePrompt', {}, '本次生成超出 budget，是否仍要以 exhaustive mode 繼續？'));
        if (confirmed) {
          return generateDrafts(true);
        }
      }
      throw new Error(text);
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('draft');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.draftsGenerated', {}, '已產生 drafts'));
  }

  async function saveDraft() {
    const teamId = ensureTeamId();
    const draftSet = currentDraftSet();
    const draft = ensureSelectedDraft();
    if (!teamId || !state.sessionId || !draftSet || !draft) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/draft-sets/${draftSet.id}/drafts`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_key: draft.item_key,
        body: {
          title: String(el('qaHelperDraftTitle').value || '').trim(),
          priority: String(el('qaHelperDraftPriority').value || 'Medium').trim(),
          preconditions: splitLines(el('qaHelperDraftPreconditions').value),
          steps: splitLines(el('qaHelperDraftSteps').value),
          expected_results: splitLines(el('qaHelperDraftExpected').value),
        },
      }),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('draft');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.draftSaved', {}, '已更新 draft'));
  }

  async function discardDraftSet() {
    const teamId = ensureTeamId();
    const draftSet = currentDraftSet();
    if (!teamId || !state.sessionId || !draftSet) return;
    if (!confirmAction(t('qaAiHelper.discardConfirm', {}, '確定要 discard 目前 drafts 嗎？'))) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/draft-sets/${draftSet.id}/discard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    updateWorkspace(await response.json());
    await loadSessions();
    setActivePhaseView('plan');
    renderPhaseWorkflow();
    setFeedback('success', t('qaAiHelper.draftsDiscarded', {}, '已 discard draft set'));
  }

  async function commitDraftSet() {
    const teamId = ensureTeamId();
    const draftSet = currentDraftSet();
    if (!teamId || !state.sessionId || !draftSet) return;
    if (!confirmAction(t('qaAiHelper.commitConfirm', {}, '確認要 commit 目前 drafts 嗎？'))) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/draft-sets/${draftSet.id}/commit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const payload = await response.json();
    setFeedback('success', t('qaAiHelper.commitDone', { count: payload.created_count }, `已建立 ${payload.created_count} 筆 Test Case`));
    await loadWorkspace(state.sessionId);
    await loadSessions();
    setActivePhaseView('draft');
    renderPhaseWorkflow();
  }

  function bindEvents() {
    el('qaHelperRefreshSessionsBtn').addEventListener('click', () => loadSessions().catch(handleError));
    document.querySelectorAll('[data-phase-target]').forEach((button) => {
      button.addEventListener('click', (event) => {
        const phase = event.currentTarget.getAttribute('data-phase-target');
        setActivePhaseView(phase);
        renderPhaseWorkflow();
      });
    });
    el('qaHelperPrevPhaseBtn').addEventListener('click', () => {
      const index = PHASE_ORDER.indexOf(state.activePhaseView);
      if (index > 0) {
        setActivePhaseView(PHASE_ORDER[index - 1]);
        renderPhaseWorkflow();
      }
    });
    el('qaHelperNextPhaseBtn').addEventListener('click', () => {
      const index = PHASE_ORDER.indexOf(state.activePhaseView);
      const nextPhase = PHASE_ORDER[index + 1];
      if (nextPhase) {
        setActivePhaseView(nextPhase);
        renderPhaseWorkflow();
      }
    });
    el('qaHelperSessionSelect').addEventListener('change', (event) => {
      const value = Number(event.target.value || 0);
      if (value) {
        loadWorkspace(value).catch(handleError);
      }
    });
    el('qaHelperTargetSetSelect').addEventListener('change', (event) => {
      state.setId = Number(event.target.value || 0) || null;
      updateUrl();
    });
    el('qaHelperCreateSessionBtn').addEventListener('click', () => createSession().catch(handleError));
    el('qaHelperFetchTicketBtn').addEventListener('click', () => fetchTicket().catch(handleError));
    el('qaHelperDeleteSessionBtn').addEventListener('click', async () => {
      const teamId = ensureTeamId();
      const sessionId = state.sessionId || Number(el('qaHelperSessionSelect').value || 0);
      if (!teamId || !sessionId) return;
      if (!confirmAction(t('qaAiHelper.deleteSessionConfirm', {}, '確定要刪除目前 Session 嗎？'))) return;
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}`, { method: 'DELETE' });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      state.workspace = null;
      state.sessionId = null;
      state.selectedDraftKey = null;
      state.activePhaseView = 'fetch';
      renderAll();
      await loadSessions();
      updateUrl();
      setFeedback('success', t('qaAiHelper.sessionDeleted', {}, '已刪除 Session'));
    });
    el('qaHelperSaveCanonicalBtn').addEventListener('click', () => saveCanonical().catch(handleError));
    el('qaHelperPlanBtn').addEventListener('click', () => planWorkspace().catch(handleError));
    el('qaHelperApplyOverridesBtn').addEventListener('click', () => applyOverrides().catch(handleError));
    el('qaHelperSaveReferencesBtn').addEventListener('click', () => saveReferences().catch(handleError));
    el('qaHelperApplyDeltaBtn').addEventListener('click', () => applyRequirementDelta().catch(handleError));
    el('qaHelperLockBtn').addEventListener('click', () => lockPlanning().catch(handleError));
    el('qaHelperUnlockBtn').addEventListener('click', () => unlockPlanning().catch(handleError));
    el('qaHelperGenerateBtn').addEventListener('click', () => generateDrafts(false).catch(handleError));
    el('qaHelperSaveDraftBtn').addEventListener('click', () => saveDraft().catch(handleError));
    el('qaHelperDiscardDraftBtn').addEventListener('click', () => discardDraftSet().catch(handleError));
    el('qaHelperCommitBtn').addEventListener('click', () => commitDraftSet().catch(handleError));
    el('qaHelperReferenceSectionSelect').addEventListener('change', renderReferenceEditor);
    el('qaHelperPlanSectionFilter').addEventListener('change', renderPlanTable);
    el('qaHelperPlanStatusFilter').addEventListener('change', renderPlanTable);
    el('qaHelperPlanSearch').addEventListener('input', renderPlanTable);
    el('qaHelperSelectAllRows').addEventListener('change', (event) => {
      document.querySelectorAll('.qa-helper-row-check').forEach((node) => {
        node.checked = !!event.target.checked;
      });
      renderImpactPreview();
    });
    document.addEventListener('change', (event) => {
      if (event.target && event.target.classList && event.target.classList.contains('qa-helper-row-check')) {
        renderImpactPreview();
      }
    });
    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-draft-key]');
      if (!button) return;
      state.selectedDraftKey = button.getAttribute('data-draft-key');
      renderDraftList();
      renderDraftEditor();
    });
  }

  function handleError(error) {
    console.error(error);
    const message = error && error.message ? error.message : t('common.failed', {}, '失敗');
    setFeedback('danger', message);
  }

  async function bootstrap() {
    if (state.bootstrapped) return;
    state.bootstrapped = true;
    const root = pageRoot();
    if (!root) return;
    state.setId = Number(root.dataset.setId || 0) || null;
    state.sessionId = Number(root.dataset.sessionId || 0) || null;
    const initialTicketKey = String(root.dataset.ticketKey || '').trim();
    if (initialTicketKey && el('qaHelperTicketKey')) {
      el('qaHelperTicketKey').value = initialTicketKey;
    }
    state.activePhaseView = inferPhaseView();
    bindEvents();
    try {
      await loadSets();
      await loadSessions();
      if (state.sessionId) {
        await loadWorkspace(state.sessionId);
      } else {
        renderAll();
      }
    } catch (error) {
      handleError(error);
    }
  }

  document.addEventListener('DOMContentLoaded', bootstrap);
  document.addEventListener('authReady', () => {
    loadSets().catch(handleError);
    loadSessions().catch(handleError);
  });
  document.addEventListener('i18nReady', renderAll);
  document.addEventListener('languageChanged', renderAll);
})();
