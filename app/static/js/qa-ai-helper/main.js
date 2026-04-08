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
    selectedPlanSectionKey: null,
    selectedSeedSectionKey: null,
    selectedTestcaseSectionKey: null,
    planDirty: false,
    planAutosaveTimer: null,
    planSaveInFlight: false,
    planChangeVersion: 0,
    seedCommentDrafts: {},
    seedCommentDirtyMap: {},
    expandedSeedCommentIds: {},
    seedActionInFlight: false,
    testcaseActionInFlight: false,
    selectedTargetSetMode: 'existing',
    selectedExistingTargetSetId: null,
    newTargetSetDraft: {
      name: '',
      description: '',
    },
    commitInFlight: false,
    activePhaseView: 'fetch',
    sessionManagerSelectedId: null,
    sessionManagerCheckedIds: [],
    sessionManagerModalInstance: null,
    sessionManagerLoading: false,
    sessionManagerError: '',
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

  function resetWorkspaceState(options) {
    const clearTicketKey = !!((options || {}).clearTicketKey);
    clearRequirementPlanAutosave();
    state.workspace = null;
    state.sessionId = null;
    state.selectedDraftKey = null;
    state.selectedPlanSectionKey = null;
    state.selectedSeedSectionKey = null;
    state.selectedTestcaseSectionKey = null;
    state.seedCommentDrafts = {};
    state.seedCommentDirtyMap = {};
    state.expandedSeedCommentIds = {};
    state.testcaseActionInFlight = false;
    state.selectedTargetSetMode = 'existing';
    state.selectedExistingTargetSetId = null;
    state.newTargetSetDraft = { name: '', description: '' };
    state.commitInFlight = false;
    state.activePhaseView = 'fetch';
    state.sessionManagerLoading = false;
    state.sessionManagerError = '';
    if (clearTicketKey && el('qaHelperTicketKey')) el('qaHelperTicketKey').value = '';
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

  function formatUtcDate(value) {
    if (!value) return '-';
    const raw = String(value).trim();
    const iso = raw.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(raw) ? raw : raw + 'Z';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? raw : d.toLocaleString();
  }

  async function authFetch(url, options) {
    if (window.AuthClient && typeof window.AuthClient.fetch === 'function') {
      return window.AuthClient.fetch(url, options || {});
    }
    return fetch(url, options || {});
  }

  function ensureToastContainer() {
    let c = document.getElementById('qaHelperToastContainer');
    if (!c) {
      c = document.createElement('div');
      c.id = 'qaHelperToastContainer';
      const root = pageRoot();
      if (root) root.appendChild(c); else document.body.appendChild(c);
    }
    return c;
  }

  function setFeedback(level, message) {
    const container = ensureToastContainer();
    const iconMap = { success: 'fa-circle-check', danger: 'fa-circle-xmark', warning: 'fa-triangle-exclamation', info: 'fa-circle-info' };
    const toast = document.createElement('div');
    toast.className = `qa-helper-toast qa-helper-toast-${level}`;
    toast.innerHTML = `<i class="fas ${iconMap[level] || iconMap.info} me-2"></i><span>${escapeHtml(message)}</span><button type="button" class="btn-close btn-close-sm ms-auto" aria-label="Close"></button>`;
    toast.querySelector('.btn-close').addEventListener('click', () => dismissToast(toast));
    container.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('is-visible'));
    const duration = level === 'danger' ? 8000 : level === 'warning' ? 6000 : 4000;
    setTimeout(() => dismissToast(toast), duration);
  }

  function dismissToast(toast) {
    if (!toast || !toast.parentNode) return;
    toast.classList.remove('is-visible');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
    setTimeout(() => toast.remove(), 400);
  }

  function clearFeedback() {
    const c = document.getElementById('qaHelperToastContainer');
    if (c) c.innerHTML = '';
  }

  function confirmAction(message) {
    return window.confirm(message);
  }

  function bindIfPresent(target, eventName, handler) {
    const node = typeof target === 'string' ? el(target) : target;
    if (!node) return;
    node.addEventListener(eventName, handler);
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function availablePhases() {
    const currentScreen = (((state.workspace || {}).session || {}).current_screen || '').trim();
    if (currentScreen === 'ticket_confirmation') {
      return new Set(['fetch']);
    }
    const phases = new Set(['fetch']);
    if (state.sessionId || currentScreen === 'verification_planning') phases.add('canonical');
    if (['seed_review', 'testcase_review', 'set_selection', 'commit_result'].includes(currentScreen)) phases.add('plan');
    if (['testcase_review', 'set_selection', 'commit_result'].includes(currentScreen)) phases.add('draft');
    if ((state.workspace || {}).canonical_revision) phases.add('plan');
    if ((state.workspace || {}).planned_revision) phases.add('draft');
    return phases;
  }

  function inferPhaseView() {
    const workspace = state.workspace || {};
    const currentScreen = (((workspace || {}).session || {}).current_screen || '').trim();
    if (currentScreen === 'ticket_confirmation') return 'fetch';
    if (currentScreen === 'verification_planning') return 'canonical';
    if (currentScreen === 'seed_review') return 'plan';
    if (['testcase_review', 'set_selection', 'commit_result'].includes(currentScreen)) return 'draft';
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
      fetch: t('qaAiHelper.phaseFetchHint', {}, 'Step 1：建立 session，確認 ticket 原文與 parser gate。'),
      canonical: t('qaAiHelper.phaseCanonicalHint', {}, 'Step 2：依 AC 編輯驗證項目與檢查條件，完成 requirement lock。'),
      plan: t('qaAiHelper.phasePlanHint', {}, 'Step 3：確認 seed，決定納入或排除。'),
      draft: t('qaAiHelper.phaseDraftHint', {}, 'Step 4：確認 testcase draft，選擇目標 set 後 commit。'),
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

  function navigateToPhase(phase) {
    setActivePhaseView(phase, { force: true });
    renderPhaseWorkflow();
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
    const ticketKey = String(el('qaHelperTicketKey').value || '').trim();
    if (!teamId) {
      setFeedback('warning', t('qaAiHelper.errorTeamRequired', {}, '請先選擇團隊'));
      return null;
    }
    if (!ticketKey) {
      setFeedback('warning', t('qaAiHelper.errorTicketRequired', {}, '請先輸入 Ticket Number'));
      return null;
    }
    const payload = {
      ticket_key: ticketKey,
      output_locale: currentOutputLocale(),
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
      return;
    }
    const response = await authFetch(`/api/teams/${teamId}/test-case-sets`);
    if (!response.ok) {
      throw new Error(await response.text());
    }
    state.sets = await response.json();
  }

  async function loadSessions() {
    const teamId = ensureTeamId();
    if (!teamId) {
      state.sessions = [];
      state.sessionManagerSelectedId = null;
      state.sessionManagerCheckedIds = [];
      state.sessionManagerLoading = false;
      state.sessionManagerError = '';
      renderSessionSelect();
      return;
    }
    state.sessionManagerLoading = true;
    state.sessionManagerError = '';
    renderSessionManager();
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions?limit=200&offset=0`);
    if (!response.ok) {
      const errorText = await response.text();
      state.sessionManagerLoading = false;
      state.sessionManagerError = errorText;
      renderSessionManager();
      throw new Error(errorText);
    }
    const payload = await response.json();
    state.sessions = payload.items || [];
    const availableIds = new Set((state.sessions || []).map((item) => Number(((item || {}).session || {}).id || 0)));
    if (!availableIds.has(Number(state.sessionManagerSelectedId || 0))) {
      state.sessionManagerSelectedId = state.sessionId && availableIds.has(Number(state.sessionId))
        ? Number(state.sessionId)
        : (state.sessions[0] ? Number((state.sessions[0].session || {}).id || 0) : null);
    }
    state.sessionManagerCheckedIds = (state.sessionManagerCheckedIds || []).filter((id) => availableIds.has(Number(id)));
    state.sessionManagerLoading = false;
    state.sessionManagerError = '';
    renderSessionSelect();
  }

  function sessionLabel(item) {
    const session = item.session || {};
    const ticketKey = session.ticket_key || t('qaAiHelper.noTicket', {}, '未綁定 Ticket');
    return `${ticketKey} (#${session.id})`;
  }

  function renderSessionSelect() {
    const select = el('qaHelperSessionSelect');
    const summary = el('qaHelperSessionManagerSummary');
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
    if (summary) {
      if (!(state.sessions || []).length) {
        summary.textContent = t('qaAiHelper.sessionManagerSummaryEmpty', {}, '尚未載入 Session 清單');
      } else if (state.sessionId) {
        const current = (state.sessions || []).find((item) => Number(((item || {}).session || {}).id || 0) === Number(state.sessionId));
        summary.textContent = current
          ? t('qaAiHelper.sessionManagerSummaryCurrent', {
              label: sessionLabel(current),
              count: state.sessions.length,
            }, `目前 Session：${sessionLabel(current)}，共 ${state.sessions.length} 筆`)
          : t('qaAiHelper.sessionManagerSummaryCount', {
              count: state.sessions.length,
            }, `共 ${state.sessions.length} 筆 Session`);
      } else {
        summary.textContent = t('qaAiHelper.sessionManagerSummaryCount', {
          count: state.sessions.length,
        }, `共 ${state.sessions.length} 筆 Session`);
      }
    }
    renderSessionManager();
  }

  function sessionScreenText(session) {
    const screen = String((session || {}).current_screen || '').trim();
    const mapping = {
      ticket_confirmation: t('qaAiHelper.screen2Title', {}, '需求單內容確認'),
      verification_planning: t('qaAiHelper.screen3Title', {}, '需求驗證項目分類與填充'),
      seed_review: t('qaAiHelper.screen4Title', {}, 'Test Case 種子確認'),
      testcase_review: t('qaAiHelper.screen5Title', {}, 'Test Case 確認'),
      set_selection: t('qaAiHelper.screen6Title', {}, 'Test Case Set 選擇'),
      commit_result: t('qaAiHelper.screen7Title', {}, '新增結果'),
    };
    return mapping[screen] || screen || '-';
  }

  function sessionManagerSelectedItem() {
    return (state.sessions || []).find((item) => Number(((item || {}).session || {}).id || 0) === Number(state.sessionManagerSelectedId || 0)) || null;
  }

  function renderSessionManager() {
    const list = el('qaHelperSessionManagerList');
    const summary = el('qaHelperSessionManagerSelectionSummary');
    const detailEmpty = el('qaHelperSessionManagerDetailEmpty');
    const detail = el('qaHelperSessionManagerDetail');
    const deleteSelectedBtn = el('qaHelperSessionManagerDeleteSelectedBtn');
    const clearBtn = el('qaHelperSessionManagerClearBtn');
    const resumeBtn = el('qaHelperSessionManagerResumeBtn');
    const deleteOneBtn = el('qaHelperSessionManagerDeleteOneBtn');
    if (!list || !summary || !detailEmpty || !detail) return;

    const items = state.sessions || [];
    const checkedIds = new Set((state.sessionManagerCheckedIds || []).map((id) => Number(id)));
    if (state.sessionManagerLoading) {
      list.innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.sessionManagerLoading', {}, '載入 Session 列表中...'))}</div>`;
    } else if (state.sessionManagerError) {
      list.innerHTML = `
        <div class="qa-helper-empty text-danger">
          <div>${escapeHtml(t('qaAiHelper.sessionManagerLoadFailed', {}, '載入 Session 管理失敗'))}</div>
          <div class="small mt-2">${escapeHtml(state.sessionManagerError)}</div>
        </div>
      `;
    } else {
      list.innerHTML = items.length
        ? items.map((item) => {
            const session = item.session || {};
            const id = Number(session.id || 0);
            const isSelected = Number(state.sessionManagerSelectedId || 0) === id;
            const isChecked = checkedIds.has(id);
            return `
              <button type="button" class="list-group-item list-group-item-action qa-helper-session-manager-item ${isSelected ? 'active' : ''}" data-session-manager-item-id="${id}">
                <div class="d-flex align-items-start gap-2">
                  <input class="form-check-input mt-1 qa-helper-session-manager-check" type="checkbox" data-session-manager-check-id="${id}" ${isChecked ? 'checked' : ''}>
                  <div class="flex-grow-1 text-start">
                    <div class="d-flex justify-content-between gap-2 flex-wrap">
                      <span class="fw-semibold qa-helper-mono">${escapeHtml(String(session.ticket_key || '-'))}</span>
                      <span class="badge ${session.status === 'completed' ? 'text-bg-success' : 'text-bg-light'}">${escapeHtml(String(session.status || '-'))}</span>
                    </div>
                    <div class="small text-muted">#${escapeHtml(String(id || '-'))} · ${escapeHtml(sessionScreenText(session))}</div>
                    <div class="small text-muted">${escapeHtml(formatUtcDate(session.updated_at))}</div>
                  </div>
                </div>
              </button>
            `;
          }).join('')
        : `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.sessionManagerEmpty', {}, '目前沒有可管理的 Session'))}</div>`;
    }

    summary.textContent = checkedIds.size > 0
      ? t('qaAiHelper.sessionManagerSelectionCount', { count: checkedIds.size }, `已勾選 ${checkedIds.size} 筆`)
      : t('qaAiHelper.sessionManagerNoSelection', {}, '尚未選取項目');

    const selected = sessionManagerSelectedItem();
    detailEmpty.classList.toggle('d-none', !!selected);
    detail.classList.toggle('d-none', !selected);
    if (selected) {
      const session = selected.session || {};
      const assign = (id, value) => {
        const node = el(id);
        if (node) node.textContent = value;
      };
      assign('qaHelperSessionManagerDetailId', `#${session.id || '-'}`);
      assign('qaHelperSessionManagerDetailTicket', String(session.ticket_key || '-'));
      assign('qaHelperSessionManagerDetailScreen', sessionScreenText(session));
      assign('qaHelperSessionManagerDetailStatus', String(session.status || '-'));
      assign('qaHelperSessionManagerDetailCreatedAt', formatUtcDate(session.created_at));
      assign('qaHelperSessionManagerDetailUpdatedAt', formatUtcDate(session.updated_at));
    }

    if (deleteSelectedBtn) deleteSelectedBtn.disabled = checkedIds.size <= 0 || state.sessionManagerLoading;
    if (clearBtn) clearBtn.disabled = items.length <= 0 || state.sessionManagerLoading;
    if (resumeBtn) resumeBtn.disabled = !selected || state.sessionManagerLoading;
    if (deleteOneBtn) deleteOneBtn.disabled = !selected || state.sessionManagerLoading;
  }

  function openSessionManager() {
    if (!(window.bootstrap && window.bootstrap.Modal)) return;
    const modalEl = el('qaHelperSessionManagerModal');
    if (!modalEl) return;
    if (!state.sessionManagerModalInstance) {
      state.sessionManagerModalInstance = new window.bootstrap.Modal(modalEl);
    }
    renderSessionManager();
    state.sessionManagerModalInstance.show();
  }

  function closeSessionManager() {
    if (state.sessionManagerModalInstance) {
      state.sessionManagerModalInstance.hide();
    }
  }

  async function resumeManagedSession() {
    const selected = sessionManagerSelectedItem();
    if (!selected) return;
    await loadWorkspace(selected.session.id);
    closeSessionManager();
    setFeedback('success', t('qaAiHelper.sessionResumed', {
      ticket: String(((selected || {}).session || {}).ticket_key || '-'),
    }, '已恢復所選 Session'));
  }

  async function deleteSessions(sessionIds) {
    const teamId = ensureTeamId();
    const ids = Array.from(new Set((sessionIds || []).map((id) => Number(id)).filter((id) => id > 0)));
    if (!teamId || !ids.length) return;
    for (const sessionId of ids) {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}`, { method: 'DELETE' });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      if (Number(state.sessionId || 0) === sessionId) {
        resetWorkspaceState({ clearTicketKey: true });
      }
    }
    await loadSessions();
    renderAll();
    updateUrl();
  }

  function updateWorkspace(workspace, options) {
    const preservePlanAutosaveState = !!((options || {}).preservePlanAutosaveState);
    const renderMode = String((options || {}).renderMode || 'full').trim();
    if (!preservePlanAutosaveState) {
      clearRequirementPlanAutosave();
    }
    const previousSeedSetId = ((((state.workspace || {}).seed_set || {}).id) || null);
    const previousTestcaseDraftSetId = ((((state.workspace || {}).testcase_draft_set || {}).id) || null);
    state.workspace = workspace;
    normalizeRequirementPlanForEditor((state.workspace || {}).requirement_plan);
    state.sessionId = workspace && workspace.session ? workspace.session.id : null;
    state.setId = workspace && workspace.session ? workspace.session.target_test_case_set_id : state.setId;
    const selectedTargetSetId = workspace && workspace.session
      ? Number(workspace.session.selected_target_test_case_set_id || workspace.session.target_test_case_set_id || 0) || null
      : null;
    if (selectedTargetSetId) {
      state.selectedExistingTargetSetId = selectedTargetSetId;
      state.selectedTargetSetMode = 'existing';
    } else if (workspace && workspace.session) {
      state.selectedExistingTargetSetId = Number(workspace.session.target_test_case_set_id || state.setId || 0) || null;
      if (currentScreen() !== 'set_selection' && currentScreen() !== 'commit_result') {
        state.selectedTargetSetMode = 'existing';
        state.newTargetSetDraft = { name: '', description: '' };
      }
    }
    const sections = (((workspace || {}).requirement_plan || {}).sections || []);
    if (!sections.find((section) => section.section_key === state.selectedPlanSectionKey)) {
      state.selectedPlanSectionKey = sections.length ? sections[0].section_key : null;
    }
    const seedItems = ((((workspace || {}).seed_set || {}).seed_items) || []);
    const nextSeedSetId = ((((workspace || {}).seed_set || {}).id) || null);
    const validSeedIds = new Set(seedItems.map((item) => String(item.id)));
    if (previousSeedSetId !== nextSeedSetId) {
      state.seedCommentDrafts = {};
      state.seedCommentDirtyMap = {};
      state.expandedSeedCommentIds = {};
    } else {
      state.seedCommentDrafts = Object.fromEntries(
        Object.entries(state.seedCommentDrafts).filter(([key]) => validSeedIds.has(key))
      );
      state.seedCommentDirtyMap = Object.fromEntries(
        Object.entries(state.seedCommentDirtyMap).filter(([key]) => validSeedIds.has(key))
      );
      state.expandedSeedCommentIds = Object.fromEntries(
        Object.entries(state.expandedSeedCommentIds).filter(([key]) => validSeedIds.has(key))
      );
    }
    const seedSections = seedItems.map((item) => item.section_key).filter(Boolean);
    if (!seedSections.includes(state.selectedSeedSectionKey)) {
      state.selectedSeedSectionKey = seedSections.length ? seedSections[0] : null;
    }
    const testcaseDrafts = ((((workspace || {}).testcase_draft_set || {}).drafts) || []);
    const nextTestcaseDraftSetId = ((((workspace || {}).testcase_draft_set || {}).id) || null);
    const testcaseSections = testcaseDrafts.map((item) => item.section_key).filter(Boolean);
    if (previousTestcaseDraftSetId !== nextTestcaseDraftSetId) {
      state.selectedTestcaseSectionKey = testcaseSections.length ? testcaseSections[0] : null;
    } else if (!testcaseSections.includes(state.selectedTestcaseSectionKey)) {
      state.selectedTestcaseSectionKey = testcaseSections.length ? testcaseSections[0] : null;
    }
    state.activePhaseView = inferPhaseView();
    populateFormFromWorkspace();
    if (renderMode === 'requirement-plan-status') {
      renderPhaseWorkflow();
      renderWorkspaceSummary();
      renderTicketConfirmation();
      renderTicketValidationSummary();
      renderRequirementReferences();
      renderRequirementPlanStatus();
    } else {
      renderAll();
    }
    updateUrl();
  }

  function populateFormFromWorkspace() {
    const workspace = state.workspace;
    if (!workspace) return;
    const session = workspace.session || {};
    const ticketKeyEl = el('qaHelperTicketKey');
    if (ticketKeyEl) {
      ticketKeyEl.value = session.ticket_key || ticketKeyEl.value || '';
    }
    const includeCommentsEl = el('qaHelperIncludeComments');
    if (includeCommentsEl) {
      includeCommentsEl.checked = !!session.include_comments;
    }
    const outputLocaleEl = el('qaHelperOutputLocale');
    if (outputLocaleEl) {
      outputLocaleEl.value = normalizeLocale(session.output_locale || 'zh-TW');
    }
    state.setId = session.target_test_case_set_id || state.setId;
  }

  function captureRequirementPlanFocus() {
    const active = document.activeElement;
    if (!active || !active.closest || !active.closest('#qaHelperPlanEditor')) return null;
    const descriptor = {
      id: active.id || null,
      tagName: String(active.tagName || '').toLowerCase(),
      itemField: active.getAttribute('data-plan-item-field'),
      itemIndex: active.getAttribute('data-plan-item-index'),
      detailField: active.getAttribute('data-plan-detail-field'),
      conditionField: active.getAttribute('data-plan-condition-field'),
      conditionIndex: active.getAttribute('data-plan-condition-index'),
      selectionStart: typeof active.selectionStart === 'number' ? active.selectionStart : null,
      selectionEnd: typeof active.selectionEnd === 'number' ? active.selectionEnd : null,
    };
    return descriptor;
  }

  function buildRequirementPlanFocusSelector(descriptor) {
    if (!descriptor) return '';
    if (descriptor.id) return `#${descriptor.id}`;
    const parts = [];
    if (descriptor.itemField) parts.push(`[data-plan-item-field="${descriptor.itemField}"]`);
    if (descriptor.detailField) parts.push(`[data-plan-detail-field="${descriptor.detailField}"]`);
    if (descriptor.conditionField) parts.push(`[data-plan-condition-field="${descriptor.conditionField}"]`);
    if (descriptor.itemIndex !== null && descriptor.itemIndex !== undefined && descriptor.itemIndex !== '') {
      parts.push(`[data-plan-item-index="${descriptor.itemIndex}"]`);
    }
    if (descriptor.conditionIndex !== null && descriptor.conditionIndex !== undefined && descriptor.conditionIndex !== '') {
      parts.push(`[data-plan-condition-index="${descriptor.conditionIndex}"]`);
    }
    return parts.join('');
  }

  function restoreRequirementPlanFocus(descriptor) {
    if (!descriptor) return;
    const editor = el('qaHelperPlanEditor');
    if (!editor) return;
    const selector = buildRequirementPlanFocusSelector(descriptor);
    if (!selector) return;
    const target = editor.querySelector(selector);
    if (!target || typeof target.focus !== 'function' || target.disabled) return;
    try {
      target.focus({ preventScroll: true });
    } catch (_) {
      target.focus();
    }
    if (typeof descriptor.selectionStart === 'number' && typeof descriptor.selectionEnd === 'number' && typeof target.setSelectionRange === 'function') {
      const valueLength = String(target.value || '').length;
      const start = Math.min(descriptor.selectionStart, valueLength);
      const end = Math.min(descriptor.selectionEnd, valueLength);
      target.setSelectionRange(start, end);
    }
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
    const requirementPlan = workspace.requirement_plan;
    const planned = workspace.planned_revision;
    const draftSet = workspace.draft_set;
    badge.className = session.status === 'completed' ? 'badge text-bg-success' : 'badge text-bg-info';
    badge.textContent = `${session.current_screen || session.current_phase || 'ticket_input'} / ${session.status}`;
    container.innerHTML = `
      <dl class="qa-helper-kv mb-0">
        <dt>${escapeHtml(t('qaAiHelper.sessionId', {}, 'Session ID'))}</dt>
        <dd class="qa-helper-mono">#${session.id}</dd>
        <dt>${escapeHtml(t('qaAiHelper.requirementPlan', {}, 'Requirement Plan'))}</dt>
        <dd>${requirementPlan ? `#${requirementPlan.revision_number} (${requirementPlan.status})` : '-'}</dd>
        <dt>${escapeHtml(t('qaAiHelper.seedSet', {}, 'Seed Set'))}</dt>
        <dd>${workspace.seed_set ? `#${workspace.seed_set.id} (${workspace.seed_set.status})` : '-'}</dd>
        <dt>${escapeHtml(t('qaAiHelper.testcaseDraftSet', {}, 'Testcase Draft Set'))}</dt>
        <dd>${workspace.testcase_draft_set ? `#${workspace.testcase_draft_set.id} (${workspace.testcase_draft_set.status})` : (draftSet ? `#${draftSet.id} (${draftSet.status})` : (planned ? `#${planned.revision_number} (${planned.status})` : '-'))}</dd>
      </dl>
    `;
  }

  function jiraWikiToMarkdown(text) {
    if (!text) return text || '';
    // Detect Jira wiki: presence of h1. … h6. heading syntax at line start
    if (!/^h[1-6]\.\s/m.test(text)) return text;
    const lines = text.split('\n');
    const result = [];
    let inCode = false, inNoformat = false, inQuote = false;
    for (const line of lines) {
      const s = line.trim();
      // {code} blocks
      if (!inNoformat) {
        if (/^\{code(:\w+)?\}$/.test(s) && !inCode) {
          const lm = s.match(/^\{code:(\w+)\}$/);
          result.push('```' + (lm ? lm[1] : ''));
          inCode = true; continue;
        }
        if (s === '{code}' && inCode) { result.push('```'); inCode = false; continue; }
      }
      // {noformat} blocks
      if (!inCode) {
        if (s === '{noformat}' && !inNoformat) { result.push('```'); inNoformat = true; continue; }
        if (s === '{noformat}' && inNoformat) { result.push('```'); inNoformat = false; continue; }
      }
      if (inCode || inNoformat) { result.push(line); continue; }
      // {quote}
      if (s === '{quote}') { inQuote = !inQuote; continue; }
      // horizontal rule
      if (s === '----') { result.push('---'); continue; }
      // headings
      const hm = s.match(/^h([1-6])\.\s+(.*)/);
      if (hm) { result.push('#'.repeat(+hm[1]) + ' ' + jiraInline(hm[2])); continue; }
      // unordered list
      const ul = s.match(/^(\*+)\s+(.*)/);
      if (ul) { result.push('  '.repeat(ul[1].length - 1) + '- ' + jiraInline(ul[2])); continue; }
      // ordered list
      const ol = s.match(/^(#+)\s+(.*)/);
      if (ol) { result.push('  '.repeat(ol[1].length - 1) + '1. ' + jiraInline(ol[2])); continue; }
      // regular line
      const converted = jiraInline(s);
      result.push(inQuote ? '> ' + converted : converted);
    }
    return result.join('\n');
  }

  function jiraInline(text) {
    return text
      .replace(/(?<![*\w])\*([^\s*](?:[^*]*[^\s*])?)\*(?![*\w])/g, '**$1**')   // bold
      .replace(/(?<![_\w])_([^\s_](?:[^_]*[^\s_])?)_(?![_\w])/g, '*$1*')        // italic
      .replace(/\{\{(.+?)\}\}/g, '`$1`')                                         // monospace
      .replace(/\[([^|\]]+)\|([^\]]+)\]/g, '[$1]($2)')                           // links
      .replace(/\[(https?:\/\/[^\]]+)\]/g, '<$1>');                               // bare links
  }

  function renderMarkdownHtml(rawContent) {
    const content = jiraWikiToMarkdown(String(rawContent || '').trim());
    if (!content) {
      return `<p class="text-muted mb-0">${escapeHtml(t('qaAiHelper.ticketMarkdownEmpty', {}, '尚未載入需求單內容'))}</p>`;
    }
    if (window.marked && typeof window.marked.parse === 'function') {
      try {
        return window.marked.parse(content);
      } catch (_) {
        // fallback below
      }
    }
    return `<pre class="mb-0 qa-helper-pre">${escapeHtml(content)}</pre>`;
  }

  function renderTicketValidationSummary() {
    const box = el('qaHelperTicketValidationSummary');
    if (!box) return;
    const ticketSnapshot = (state.workspace || {}).ticket_snapshot;
    if (!ticketSnapshot) {
      box.innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.ticketConfirmationEmpty', {}, '載入需求單後，這裡會顯示格式檢查結果。'))}</div>`;
      return;
    }
    const validation = ticketSnapshot.validation_summary || {};
    const errors = []
      .concat(validation.missing_sections || [])
      .concat(validation.missing_fields || [])
      .concat(validation.scenario_errors || [])
      .concat(validation.parser_errors || []);
    const warnings = validation.warnings || [];
    const stats = validation.stats || {};
    const issueList = (items) => {
      if (!items.length) {
        return `<li class="text-muted">${escapeHtml(t('common.none', {}, '無'))}</li>`;
      }
      return items.map((item) => `<li>${escapeHtml(item.message || item.code || '-')}</li>`).join('');
    };
    box.innerHTML = `
      <div class="d-flex justify-content-between align-items-start gap-2">
        <div>
          <div class="fw-semibold">${escapeHtml(t('qaAiHelper.validationResultTitle', {}, '格式檢查結果'))}</div>
          <small class="text-muted">${escapeHtml(t('qaAiHelper.validationResultHint', {}, '至少需通過 User Story Narrative、Criteria、Acceptance Criteria 與 clause 檢查。'))}</small>
        </div>
        <span class="badge ${validation.is_valid ? 'text-bg-success' : 'text-bg-warning'}">${escapeHtml(validation.is_valid ? t('qaAiHelper.validationPassed', {}, '通過') : t('qaAiHelper.validationFailed', {}, '未通過'))}</span>
      </div>
      <dl class="qa-helper-kv qa-helper-kv-compact mt-3 mb-3">
        <dt>${escapeHtml(t('qaAiHelper.criteriaItemCount', {}, 'Criteria 項目數'))}</dt>
        <dd>${escapeHtml(String(stats.criteria_item_count || 0))}</dd>
        <dt>${escapeHtml(t('qaAiHelper.scenarioCount', {}, 'AC Scenario 數'))}</dt>
        <dd>${escapeHtml(String(stats.acceptance_scenario_count || 0))}</dd>
      </dl>
      <div class="qa-helper-issue-group">
        <div class="fw-semibold mb-1">${escapeHtml(t('qaAiHelper.validationErrors', {}, '錯誤'))}</div>
        <ul class="mb-3 qa-helper-issue-list">${issueList(errors)}</ul>
      </div>
      <div class="qa-helper-issue-group">
        <div class="fw-semibold mb-1">${escapeHtml(t('qaAiHelper.validationWarnings', {}, '警告'))}</div>
        <ul class="mb-0 qa-helper-issue-list">${issueList(warnings)}</ul>
      </div>
    `;
  }

  function renderTicketConfirmation() {
    const loadCard = el('qaHelperLoadTicketCard');
    const card = el('qaHelperTicketConfirmationCard');
    const meta = el('qaHelperTicketMeta');
    const markdown = el('qaHelperTicketMarkdown');
    const proceedBtn = el('qaHelperProceedVerificationBtn');
    const ticketSnapshot = (state.workspace || {}).ticket_snapshot;
    const session = (state.workspace || {}).session || {};
    if (!card || !meta || !markdown || !proceedBtn) return;
    if (!ticketSnapshot) {
      if (loadCard) loadCard.classList.remove('d-none');
      card.classList.add('d-none');
      proceedBtn.disabled = true;
      return;
    }
    if (loadCard) loadCard.classList.add('d-none');
    card.classList.remove('d-none');
    const validation = ticketSnapshot.validation_summary || {};
    meta.innerHTML = `
      <div class="qa-helper-ticket-meta-grid">
        <div><span class="qa-helper-ticket-meta-label">${escapeHtml(t('qaAiHelper.ticketNumber', {}, 'Ticket Number'))}</span><span class="qa-helper-ticket-meta-value qa-helper-mono">${escapeHtml(session.ticket_key || '-')}</span></div>
        <div><span class="qa-helper-ticket-meta-label">${escapeHtml(t('qaAiHelper.sessionId', {}, 'Session ID'))}</span><span class="qa-helper-ticket-meta-value qa-helper-mono">#${escapeHtml(String(session.id || '-'))}</span></div>
        <div><span class="qa-helper-ticket-meta-label">${escapeHtml(t('qaAiHelper.outputLocale', {}, '產出語系'))}</span><span class="qa-helper-ticket-meta-value">${escapeHtml(session.output_locale || '-')}</span></div>
      </div>
    `;
    markdown.innerHTML = renderMarkdownHtml(ticketSnapshot.raw_ticket_markdown);
    proceedBtn.disabled = !validation.is_valid;
  }

  function currentRequirementPlan() {
    return (state.workspace || {}).requirement_plan || null;
  }

  function clearRequirementPlanAutosave() {
    if (state.planAutosaveTimer) {
      window.clearTimeout(state.planAutosaveTimer);
      state.planAutosaveTimer = null;
    }
    state.planDirty = false;
    state.planSaveInFlight = false;
  }

  function currentPlanSections() {
    const plan = currentRequirementPlan();
    return (plan && plan.sections) || [];
  }

  function isRequirementPlanLocked() {
    return ((currentRequirementPlan() || {}).status || '') === 'locked';
  }

  function recomputeRequirementSectionIds(plan) {
    const ticketKey = (((state.workspace || {}).session || {}).ticket_key || '').trim();
    const startValue = Number(String(plan.section_start_number || '010').trim() || 10);
    (plan.sections || []).forEach((section, index) => {
      const nextNumber = startValue + (index * 10);
      section.section_id = ticketKey ? `${ticketKey}.${String(nextNumber).padStart(3, '0')}` : String(nextNumber).padStart(3, '0');
      section.display_order = index;
    });
  }

  function ensureSelectedPlanSectionKey() {
    const sections = currentPlanSections();
    if (!sections.length) {
      state.selectedPlanSectionKey = null;
      return null;
    }
    const matched = sections.find((section) => section.section_key === state.selectedPlanSectionKey);
    if (matched) return matched.section_key;
    state.selectedPlanSectionKey = sections[0].section_key;
    return state.selectedPlanSectionKey;
  }

  function selectedPlanSection() {
    const selectedKey = ensureSelectedPlanSectionKey();
    return currentPlanSections().find((section) => section.section_key === selectedKey) || null;
  }

  function createEmptyCheckCondition() {
    return {
      id: null,
      condition_text: '',
      coverage_tag: 'Happy Path',
    };
  }

  function createEmptyVerificationItem() {
    const primaryCondition = createEmptyCheckCondition();
    return {
      id: null,
      category: '功能驗證',
      summary: '',
      detail: {},
      check_conditions: [primaryCondition],
    };
  }

  function combineVerificationTargetAndCondition(summary, conditionText) {
    const target = String(summary || '').trim();
    const condition = String(conditionText || '').trim();
    if (target && condition) {
      return target === condition ? target : `${target}：${condition}`;
    }
    return target || condition;
  }

  function ensurePrimaryCondition(item) {
    if (!item) return createEmptyCheckCondition();
    item.check_conditions = Array.isArray(item.check_conditions) ? item.check_conditions : [];
    if (!item.check_conditions.length) {
      item.check_conditions.push(createEmptyCheckCondition());
    }
    const primary = item.check_conditions[0] || createEmptyCheckCondition();
    if (!String(primary.coverage_tag || '').trim()) {
      primary.coverage_tag = 'Happy Path';
    }
    item.check_conditions = [primary];
    return primary;
  }

  function normalizeVerificationItemsForEditor(items) {
    return (Array.isArray(items) ? items : []).flatMap((rawItem) => {
      const baseItem = rawItem || {};
      const category = String(baseItem.category || '功能驗證');
      const conditions = Array.isArray(baseItem.check_conditions) && baseItem.check_conditions.length
        ? baseItem.check_conditions
        : [createEmptyCheckCondition()];
      return conditions.map((condition, index) => {
        const combinedText = combineVerificationTargetAndCondition(
          baseItem.summary,
          condition && condition.condition_text
        );
        return {
          id: index === 0 ? (Object.prototype.hasOwnProperty.call(baseItem, 'id') ? baseItem.id : null) : null,
          category,
          summary: combinedText,
          detail: {},
          check_conditions: [
            {
              id: condition && Object.prototype.hasOwnProperty.call(condition, 'id') ? condition.id : null,
              condition_text: combinedText,
              coverage_tag: String((condition && condition.coverage_tag) || 'Happy Path'),
            },
          ],
        };
      });
    });
  }

  function normalizePlanSectionVerificationItems(section) {
    if (!section) return [];
    section.verification_items = normalizeVerificationItemsForEditor(section.verification_items);
    return section.verification_items;
  }

  function normalizeRequirementPlanForEditor(plan) {
    if (!plan || !Array.isArray(plan.sections)) return;
    plan.sections.forEach((section) => {
      normalizePlanSectionVerificationItems(section);
    });
  }

  function requirementPlanStatusBadge(status) {
    if (status === 'locked') return 'text-bg-warning';
    if (status === 'superseded') return 'text-bg-secondary';
    return 'text-bg-info';
  }

  function formatReferenceBlock(reference) {
    const payload = reference || {};
    const groups = Object.entries(payload);
    if (!groups.length) {
      return `<div class="qa-helper-empty">${escapeHtml(t('common.none', {}, '無'))}</div>`;
    }
    return groups.map(([groupName, groupValue]) => {
      const items = Array.isArray((groupValue || {}).items) ? groupValue.items : [];
      const renderedItems = items.length
        ? `<ul class="mb-0">${items.map((item) => {
            const name = String(item.name || '').trim();
            const description = String(item.description || '').trim();
            if (name && description) return `<li><span class="fw-semibold">${escapeHtml(name)}</span> - ${escapeHtml(description)}</li>`;
            return `<li>${escapeHtml(name || description || '-')}</li>`;
          }).join('')}</ul>`
        : `<div class="text-muted">${escapeHtml(String((groupValue || {}).description || '').trim() || t('common.none', {}, '無'))}</div>`;
      return `
        <div class="qa-helper-reference-group">
          <div class="fw-semibold mb-1">${escapeHtml(groupName)}</div>
          ${renderedItems}
        </div>
      `;
    }).join('');
  }

  function renderRequirementPlanStatus() {
    const plan = currentRequirementPlan();
    const headerStatus = el('qaHelperRequirementPlanHeaderStatus');
    const footerStatus = el('qaHelperRequirementPlanFooterStatus');
    const autosaveStatus = el('qaHelperPlanAutosaveStatus');
    const validationSummary = el('qaHelperPlanValidationSummary');
    const lockButton = el('qaHelperLockRequirementPlanBtn');
    const unlockButton = el('qaHelperUnlockRequirementPlanBtn');
    const seedButton = el('qaHelperStartSeedReviewBtn');
    const regenerateSeedsButton = el('qaHelperRegenerateSeedsBtn');
    const proceedSeedButton = el('qaHelperProceedToSeedReviewBtn');
    const saveButton = el('qaHelperSaveRequirementPlanBtn');

    if (!plan) {
      [headerStatus, footerStatus, autosaveStatus, validationSummary].forEach((node) => {
        if (node) node.innerHTML = '';
      });
      if (lockButton) lockButton.disabled = true;
      if (unlockButton) unlockButton.disabled = true;
      if (seedButton) seedButton.disabled = true;
      if (saveButton) saveButton.disabled = true;
      if (regenerateSeedsButton) regenerateSeedsButton.classList.add('d-none');
      if (proceedSeedButton) proceedSeedButton.classList.add('d-none');
      return;
    }

    const validation = plan.validation_summary || {};
    const stats = validation.stats || {};
    const autosave = plan.autosave_summary || {};
    const locked = plan.status === 'locked';

    if (headerStatus) {
      headerStatus.innerHTML = `
        <span class="badge ${requirementPlanStatusBadge(plan.status)}">${escapeHtml(plan.status || 'draft')}</span>
      `;
    }
    if (footerStatus) {
      const savedAt = formatUtcDate(autosave.saved_at);
      footerStatus.innerHTML = `
        <div class="small text-muted">
          ${escapeHtml(t('qaAiHelper.planFooterStatus', {
            sections: stats.section_count || 0,
            items: stats.verification_item_count || 0,
            conditions: stats.check_condition_count || 0,
          }, `Sections ${stats.section_count || 0} / Items ${stats.verification_item_count || 0} / Conditions ${stats.check_condition_count || 0}`))}
          <span class="ms-2">${escapeHtml(t('qaAiHelper.lastSavedAt', { value: savedAt }, `最後儲存 ${savedAt}`))}</span>
          ${state.planDirty ? `<span class="ms-2 text-warning">${escapeHtml(t('qaAiHelper.planDirty', {}, '有未儲存變更'))}</span>` : ''}
        </div>
      `;
    }
    if (autosaveStatus) {
      const savedAtText = autosave.saved_at
        ? formatUtcDate(autosave.saved_at)
        : t('qaAiHelper.autosavePending', {}, '尚未儲存');
      autosaveStatus.innerHTML = `
        <div class="small text-muted">${escapeHtml(t('qaAiHelper.lastSavedLabel', {}, '上次儲存'))}</div>
        <div class="small">${escapeHtml(savedAtText)}</div>
      `;
    }
    if (validationSummary) {
      const errors = validation.errors || [];
      validationSummary.innerHTML = `
        <div class="small text-muted">${escapeHtml(t('qaAiHelper.planValidationTitle', {}, '規劃檢查'))}</div>
        <div class="small">${escapeHtml(t('qaAiHelper.planValidationSummary', { count: errors.length }, `${errors.length} 個待補項目`))}</div>
      `;
    }

    const sectionStartInput = el('qaHelperSectionStartNumber');
    if (sectionStartInput) sectionStartInput.disabled = locked;

    if (saveButton) saveButton.disabled = locked || state.planSaveInFlight;
    if (lockButton) lockButton.disabled = locked || state.planSaveInFlight;
    if (unlockButton) unlockButton.disabled = !locked || state.planSaveInFlight;

    const ws = state.workspace || {};
    const existingSeedSet = ws.seed_set;
    const canReuseSeed = locked
      && existingSeedSet
      && existingSeedSet.requirement_plan_id === plan.id
      && (existingSeedSet.status === 'draft' || existingSeedSet.status === 'locked');

    if (canReuseSeed) {
      if (seedButton) seedButton.classList.add('d-none');
      if (regenerateSeedsButton) { regenerateSeedsButton.classList.remove('d-none'); regenerateSeedsButton.disabled = false; }
      if (proceedSeedButton) { proceedSeedButton.classList.remove('d-none'); proceedSeedButton.disabled = false; }
    } else {
      if (seedButton) { seedButton.classList.remove('d-none'); seedButton.disabled = !locked; }
      if (regenerateSeedsButton) regenerateSeedsButton.classList.add('d-none');
      if (proceedSeedButton) proceedSeedButton.classList.add('d-none');
    }
  }

  function renderRequirementReferences() {
    const plan = currentRequirementPlan();
    const criteria = el('qaHelperCriteriaReference');
    const technical = el('qaHelperTechnicalReference');
    if (!criteria || !technical) return;
    if (!plan) {
      const empty = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.screen3Empty', {}, '進入畫面三後會顯示 section 編輯工作區。'))}</div>`;
      criteria.innerHTML = empty;
      technical.innerHTML = empty;
      return;
    }
    criteria.innerHTML = `
      <div class="fw-semibold mb-2">${escapeHtml(t('qaAiHelper.criteriaReferenceTitle', {}, 'Criteria'))}</div>
      ${formatReferenceBlock(plan.criteria_reference)}
    `;
    technical.innerHTML = `
      <div class="fw-semibold mb-2">${escapeHtml(t('qaAiHelper.technicalReferenceTitle', {}, 'Technical Specifications'))}</div>
      ${formatReferenceBlock(plan.technical_reference)}
    `;
  }

  function renderRequirementPlanWorkspace() {
    const card = el('qaHelperRequirementPlanCard');
    const rail = el('qaHelperPlanSectionRail');
    const editor = el('qaHelperPlanEditor');
    const count = el('qaHelperSectionRailCount');
    const sectionStartInput = el('qaHelperSectionStartNumber');
    const plan = currentRequirementPlan();
    if (!card || !rail || !editor || !count || !sectionStartInput) return;
    const visible = !!plan || ((((state.workspace || {}).session || {}).current_screen || '') === 'verification_planning');
    card.classList.toggle('d-none', !visible);
    if (!visible) return;

    if (!plan) {
      rail.innerHTML = '';
      count.textContent = '0';
      editor.innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.screen3Empty', {}, '進入畫面三後會顯示 section 編輯工作區。'))}</div>`;
      sectionStartInput.value = '010';
      renderRequirementReferences();
      renderRequirementPlanStatus();
      return;
    }

    sectionStartInput.value = String(plan.section_start_number || '010');
    const rangeHint = el('qaHelperSectionRangeHint');
    const sections = currentPlanSections();
    if (rangeHint) {
      if (sections.length > 0) {
        const first = sections[0];
        const last = sections[sections.length - 1];
        const firstId = (first.section_id || '').split('.').pop() || '';
        const lastId = (last.section_id || '').split('.').pop() || '';
        rangeHint.textContent = t('qaAiHelper.sectionRangeHint', {
          count: sections.length, first: firstId, last: lastId,
        }, `目前 ${sections.length} 個 section（${firstId} ~ ${lastId}）`);
      } else {
        rangeHint.textContent = '';
      }
    }
    count.textContent = String(sections.length);
    const selectedKey = ensureSelectedPlanSectionKey();
    rail.innerHTML = sections.length
      ? sections.map((section) => {
          const itemCount = Array.isArray(section.verification_items) ? section.verification_items.length : 0;
          return `
            <button type="button" class="list-group-item list-group-item-action qa-helper-section-item ${section.section_key === selectedKey ? 'active' : ''}" data-plan-section-key="${escapeHtml(section.section_key)}">
              <div class="d-flex justify-content-between align-items-start gap-2">
                <div>
                  <div class="fw-semibold qa-helper-mono">${escapeHtml(section.section_id || '-')}</div>
                  <div>${escapeHtml(section.section_title || '-')}</div>
                </div>
                <span class="badge text-bg-light">${escapeHtml(String(itemCount))}</span>
              </div>
            </button>
          `;
        }).join('')
      : `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.noSections', {}, '尚未有可編輯的 sections'))}</div>`;

    const locked = isRequirementPlanLocked();
    const section = selectedPlanSection();
    if (!section) {
      editor.innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.noSections', {}, '尚未有可編輯的 sections'))}</div>`;
      renderRequirementReferences();
      renderRequirementPlanStatus();
      return;
    }

    const items = normalizePlanSectionVerificationItems(section);
    editor.innerHTML = `
      <div class="qa-helper-editor-card">
        <div class="row g-3">
          <div class="col-12 col-lg-8">
            <label class="form-label" for="qaHelperSectionTitleInput">${escapeHtml(t('qaAiHelper.sectionTitle', {}, 'Section 名稱'))}</label>
            <input type="text" class="form-control" id="qaHelperSectionTitleInput" value="${escapeHtml(section.section_title || '')}" ${locked ? 'disabled' : ''}>
          </div>
          <div class="col-12 col-lg-4">
            <label class="form-label">${escapeHtml(t('qaAiHelper.sectionIdLabel', {}, 'Section 編號'))}</label>
            <div class="form-control qa-helper-mono qa-helper-static-field">${escapeHtml(section.section_id || '-')}</div>
          </div>
          <div class="col-12">
            <div class="qa-helper-gherkin-summary">
              <div><span class="fw-semibold">Given</span><div>${(section.given || []).map((item) => `<div>${escapeHtml(item)}</div>`).join('') || `<span class="text-muted">${escapeHtml(t('common.none', {}, '無'))}</span>`}</div></div>
              <div><span class="fw-semibold">When</span><div>${(section.when || []).map((item) => `<div>${escapeHtml(item)}</div>`).join('') || `<span class="text-muted">${escapeHtml(t('common.none', {}, '無'))}</span>`}</div></div>
              <div><span class="fw-semibold">Then</span><div>${(section.then || []).map((item) => `<div>${escapeHtml(item)}</div>`).join('') || `<span class="text-muted">${escapeHtml(t('common.none', {}, '無'))}</span>`}</div></div>
            </div>
          </div>
          <div class="col-12">
            <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
              <div class="fw-semibold">${escapeHtml(t('qaAiHelper.verificationItemsTitle', {}, '驗證目標及檢查條件'))}</div>
              <button type="button" class="btn btn-outline-primary btn-sm" id="qaHelperAddVerificationItemBtn" ${locked ? 'disabled' : ''}>
                <i class="fas fa-plus me-1"></i>${escapeHtml(t('qaAiHelper.addVerificationItem', {}, '新增驗證目標及檢查條件'))}
              </button>
            </div>
            <div class="qa-helper-goal-list">
              ${items.length ? items.map((item, itemIndex) => {
                const primaryCondition = ensurePrimaryCondition(item);
                return `
                  <div class="qa-helper-goal-entry qa-helper-goal-entry-compact">
                    <div class="qa-helper-goal-entry-top">
                      <span class="qa-helper-goal-entry-index">${escapeHtml(String(itemIndex + 1).padStart(2, '0'))}</span>
                      <button type="button" class="btn btn-outline-danger btn-sm qa-helper-goal-entry-delete" data-plan-remove-item-index="${itemIndex}" ${locked ? 'disabled' : ''} aria-label="${escapeHtml(t('common.delete', {}, '刪除'))}">
                        <i class="fas fa-trash"></i>
                      </button>
                    </div>
                    <div class="qa-helper-goal-entry-meta qa-helper-goal-entry-meta-top">
                      <div class="qa-helper-goal-meta-field">
                        <label class="form-label qa-helper-goal-entry-label">${escapeHtml(t('qaAiHelper.verificationCategory', {}, '分類'))}</label>
                        <select class="form-select" data-plan-item-field="category" data-plan-item-index="${itemIndex}" ${locked ? 'disabled' : ''}>
                          ${['API', 'UI', '功能驗證', '其他'].map((category) => `<option value="${escapeHtml(category)}"${category === item.category ? ' selected' : ''}>${escapeHtml(category)}</option>`).join('')}
                        </select>
                      </div>
                      <div class="qa-helper-goal-meta-field">
                        <label class="form-label qa-helper-goal-entry-label">${escapeHtml(t('qaAiHelper.coverage', {}, 'Coverage'))}</label>
                        <select class="form-select" data-plan-condition-field="coverage_tag" data-plan-item-index="${itemIndex}" data-plan-condition-index="0" ${locked ? 'disabled' : ''}>
                          ${['Happy Path', 'Error Handling', 'Edge Test Case', 'Permission'].map((coverage) => `<option value="${escapeHtml(coverage)}"${coverage === primaryCondition.coverage_tag ? ' selected' : ''}>${escapeHtml(coverage)}</option>`).join('')}
                        </select>
                      </div>
                    </div>
                    <div class="qa-helper-goal-entry-body qa-helper-goal-entry-body-tight">
                      <label class="form-label qa-helper-goal-entry-label">${escapeHtml(t('qaAiHelper.verificationSummary', {}, '驗證目標及檢查條件'))}</label>
                      <textarea class="form-control qa-helper-goal-entry-textarea" data-plan-item-field="summary" data-plan-item-index="${itemIndex}" ${locked ? 'disabled' : ''} placeholder="${escapeHtml(t('qaAiHelper.verificationSummaryPlaceholder', {}, '例如：點擊 audience name 後應成功開啟詳情頁並顯示狀態'))}">${escapeHtml(item.summary || '')}</textarea>
                    </div>
                  </div>
                `;
              }).join('') : `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.noVerificationItems', {}, '此 section 尚未新增任何驗證目標及檢查條件'))}</div>`}
            </div>
          </div>
        </div>
      </div>
    `;

    renderRequirementReferences();
    renderRequirementPlanStatus();
  }

  function markRequirementPlanDirty() {
    state.planDirty = true;
    state.planChangeVersion += 1;
    renderRequirementPlanStatus();
    if (state.planAutosaveTimer) return;
    state.planAutosaveTimer = window.setTimeout(() => {
      state.planAutosaveTimer = null;
      if (!state.planDirty || !state.sessionId || isRequirementPlanLocked()) return;
      saveRequirementPlan({ autosave: true }).catch(handleError);
    }, 5000);
  }

  function currentSeedSet() {
    return (state.workspace || {}).seed_set || null;
  }

  function currentSeedItems() {
    return (currentSeedSet() && currentSeedSet().seed_items) || [];
  }

  function isSeedSetLocked() {
    const seedSet = currentSeedSet();
    return !!seedSet && seedSet.status === 'locked';
  }

  function seedSections() {
    const groups = new Map();
    currentSeedItems().forEach((item) => {
      const key = String(item.section_key || item.section_id || item.plan_section_id || item.id);
      if (!groups.has(key)) {
        groups.set(key, {
          section_key: key,
          section_id: item.section_id || '-',
          section_title: item.section_title || '-',
          items: [],
        });
      }
      groups.get(key).items.push(item);
    });
    return Array.from(groups.values()).sort((left, right) => {
      const leftKey = `${left.section_id} ${left.section_title}`.trim();
      const rightKey = `${right.section_id} ${right.section_title}`.trim();
      return leftKey.localeCompare(rightKey, 'en');
    });
  }

  function ensureSelectedSeedSectionKey() {
    const sections = seedSections();
    if (!sections.length) {
      state.selectedSeedSectionKey = null;
      return null;
    }
    if (!state.selectedSeedSectionKey || !sections.some((section) => section.section_key === state.selectedSeedSectionKey)) {
      state.selectedSeedSectionKey = sections[0].section_key;
    }
    return state.selectedSeedSectionKey;
  }

  function selectedSeedSection() {
    const selectedKey = ensureSelectedSeedSectionKey();
    return seedSections().find((section) => section.section_key === selectedKey) || null;
  }

  function seedItemsForSelectedSection() {
    const section = selectedSeedSection();
    return section ? section.items : [];
  }

  function seedBodyText(seedItem) {
    const body = (seedItem || {}).seed_body || {};
    if (typeof body === 'string') return body;
    if (body && typeof body.text === 'string') return body.text;
    return JSON.stringify(body || {}, null, 2);
  }

  function seedCommentValue(seedItem) {
    const key = String((seedItem || {}).id || '');
    if (Object.prototype.hasOwnProperty.call(state.seedCommentDrafts, key)) {
      return state.seedCommentDrafts[key];
    }
    return String((seedItem || {}).comment_text || '');
  }

  function isSeedCommentDirty(seedItem) {
    return !!state.seedCommentDirtyMap[String((seedItem || {}).id || '')];
  }

  function hasDirtySeedComments() {
    return Object.values(state.seedCommentDirtyMap).some(Boolean);
  }

  function commentPreview(text) {
    const normalized = String(text || '').trim();
    if (!normalized) return '';
    return normalized.length > 36 ? `${normalized.slice(0, 36)}...` : normalized;
  }

  function seedStatusBadge(status) {
    const normalized = String(status || 'draft').trim();
    const mapping = {
      draft: 'badge rounded-pill text-bg-warning',
      locked: 'badge rounded-pill text-bg-success',
      superseded: 'badge rounded-pill text-bg-secondary',
      consumed: 'badge rounded-pill text-bg-dark',
    };
    return `<span class="${mapping[normalized] || 'badge rounded-pill text-bg-secondary'}">${escapeHtml(normalized)}</span>`;
  }

  function renderSeedReviewSummary() {
    const summary = el('qaHelperSeedReviewSummary');
    const footer = el('qaHelperSeedReviewFooterStatus');
    const header = el('qaHelperSeedReviewHeaderStatus');
    const refineButton = el('qaHelperRefineSeedsBtn');
    const lockButton = el('qaHelperLockSeedsBtn');
    const unlockButton = el('qaHelperUnlockSeedsBtn');
    const testcaseButton = el('qaHelperStartTestcaseReviewBtn');
    const regenerateTestcasesButton = el('qaHelperRegenerateTestcasesBtn');
    const proceedTestcaseButton = el('qaHelperProceedToTestcaseReviewBtn');
    const includeButton = el('qaHelperIncludeSectionSeedsBtn');
    const excludeButton = el('qaHelperExcludeSectionSeedsBtn');
    const includeAllButton = el('qaHelperIncludeAllSeedsBtn');
    const excludeAllButton = el('qaHelperExcludeAllSeedsBtn');
    const seedSet = currentSeedSet();
    const selectedSection = selectedSeedSection();
    const dirtyComments = hasDirtySeedComments();

    if (summary) {
      if (!seedSet) {
        summary.innerHTML = '';
      } else {
        const generated = Number(seedSet.generated_seed_count || 0);
        const included = Number(seedSet.included_seed_count || 0);
        const excluded = Math.max(generated - included, 0);
        const savedAt = formatUtcDate(seedSet.updated_at);
        summary.innerHTML = `
          <div class="d-flex flex-wrap align-items-center gap-3 small text-muted">
            <span>${escapeHtml(t('qaAiHelper.generatedSeedCount', {}, '產生種子數'))} <strong class="qa-helper-mono">${generated}</strong></span>
            <span>${escapeHtml(t('qaAiHelper.includedSeedCount', {}, '納入數'))} <strong class="qa-helper-mono">${included}</strong></span>
            <span>${escapeHtml(t('qaAiHelper.excludedSeedCount', {}, '排除數'))} <strong class="qa-helper-mono">${excluded}</strong></span>
            <span class="ms-auto">${escapeHtml(t('qaAiHelper.lastSavedAt', { value: savedAt }, `最後儲存 ${savedAt}`))}</span>
          </div>
        `;
      }
    }

    if (header) {
      header.innerHTML = seedSet ? `${seedStatusBadge(seedSet.status)}` : '';
    }
    if (footer) {
      if (!seedSet) {
        footer.innerHTML = '';
      } else {
        footer.innerHTML = `
          <div class="small text-muted">${escapeHtml(t('qaAiHelper.seedFooterStatus', {}, 'Seed 狀態'))}</div>
          <div class="small">${escapeHtml(
            dirtyComments
              ? t('qaAiHelper.seedDirtyPending', {}, '有未套用的註解，請先依註解更新種子。')
              : isSeedSetLocked()
                ? t('qaAiHelper.seedLockedReady', {}, '已鎖定，可進入下一步。')
                : t('qaAiHelper.seedDraftPending', {}, '尚未鎖定，調整後需重新鎖定。')
          )}</div>
        `;
      }
    }

    if (refineButton) refineButton.disabled = !seedSet || !dirtyComments || state.seedActionInFlight;
    if (lockButton) lockButton.disabled = !seedSet || isSeedSetLocked() || dirtyComments || state.seedActionInFlight;
    if (unlockButton) unlockButton.disabled = !seedSet || !isSeedSetLocked() || state.seedActionInFlight;
    const seedLocked = seedSet && isSeedSetLocked();
    const seedReady = seedLocked && Number(seedSet.included_seed_count || 0) > 0 && !dirtyComments;
    const ws = state.workspace || {};
    const existingDraftSet = ws.testcase_draft_set;
    const canReuseTestcase = seedReady
      && existingDraftSet
      && existingDraftSet.seed_set_id === seedSet.id
      && (existingDraftSet.status === 'draft' || existingDraftSet.status === 'reviewing');

    if (canReuseTestcase) {
      if (testcaseButton) testcaseButton.classList.add('d-none');
      if (regenerateTestcasesButton) { regenerateTestcasesButton.classList.remove('d-none'); regenerateTestcasesButton.disabled = false; }
      if (proceedTestcaseButton) { proceedTestcaseButton.classList.remove('d-none'); proceedTestcaseButton.disabled = false; }
    } else {
      if (testcaseButton) { testcaseButton.classList.remove('d-none'); testcaseButton.disabled = !seedReady; }
      if (regenerateTestcasesButton) regenerateTestcasesButton.classList.add('d-none');
      if (proceedTestcaseButton) proceedTestcaseButton.classList.add('d-none');
    }

    if (includeButton) includeButton.disabled = !seedSet || !selectedSection || state.seedActionInFlight;
    if (excludeButton) excludeButton.disabled = !seedSet || !selectedSection || state.seedActionInFlight;
    if (includeAllButton) includeAllButton.disabled = !seedSet || state.seedActionInFlight;
    if (excludeAllButton) excludeAllButton.disabled = !seedSet || state.seedActionInFlight;
  }

  function renderSeedReviewWorkspace() {
    const card = el('qaHelperSeedReviewCard');
    const rail = el('qaHelperSeedSectionRail');
    const count = el('qaHelperSeedSectionRailCount');
    const list = el('qaHelperSeedCardList');
    const seedSet = currentSeedSet();
    const currentScreen = ((((state.workspace || {}).session || {}).current_screen) || '').trim();
    if (!card || !rail || !count || !list) return;
    const visible = !!seedSet || currentScreen === 'seed_review';
    card.classList.toggle('d-none', !visible);
    if (!visible) return;

    const sections = seedSections();
    count.textContent = String(sections.length);
    const selectedSectionKey = ensureSelectedSeedSectionKey();

    rail.innerHTML = sections.length
      ? sections.map((section) => {
          const itemCount = section.items.length;
          const includedCount = section.items.filter((item) => item.included_for_testcase_generation).length;
          return `
            <button type="button" class="list-group-item list-group-item-action qa-helper-section-item ${section.section_key === selectedSectionKey ? 'active' : ''}" data-seed-section-key="${escapeHtml(section.section_key)}">
              <div class="d-flex justify-content-between align-items-start gap-2">
                <div>
                  <div class="fw-semibold qa-helper-mono">${escapeHtml(section.section_id || '-')}</div>
                  <div>${escapeHtml(section.section_title || '-')}</div>
                </div>
                <span class="badge text-bg-light">${escapeHtml(`${includedCount}/${itemCount}`)}</span>
              </div>
            </button>
          `;
        }).join('')
      : `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.seedSectionEmpty', {}, '尚無種子資料'))}</div>`;

    const items = seedItemsForSelectedSection();
    list.innerHTML = items.length
      ? items.map((seedItem) => {
          const comment = seedCommentValue(seedItem);
          const expanded = !!state.expandedSeedCommentIds[String(seedItem.id)];
          const commentSnippet = commentPreview(comment);
          const coverageText = (seedItem.coverage_tags || []).join(', ') || '-';
          return `
            <div class="qa-helper-seed-card ${seedItem.included_for_testcase_generation ? '' : 'is-excluded'}" data-seed-item-id="${seedItem.id}">
              <div class="qa-helper-seed-card-head">
                <div>
                  <div class="d-flex flex-wrap align-items-center gap-2 mb-1">
                    <span class="qa-helper-mono fw-semibold">${escapeHtml(seedItem.seed_reference_key)}</span>
                    <span class="badge text-bg-info">${escapeHtml(t('qaAiHelper.aiGenerated', {}, 'AI'))}</span>
                    ${seedItem.included_for_testcase_generation
                      ? `<span class="badge text-bg-success">${escapeHtml(t('qaAiHelper.includedSeed', {}, '已納入'))}</span>`
                      : `<span class="badge text-bg-secondary">${escapeHtml(t('qaAiHelper.excludedSeed', {}, '已排除'))}</span>`}
                  </div>
                  <div class="qa-helper-seed-summary">${escapeHtml(seedItem.seed_summary || '-')}</div>
                </div>
                <div class="form-check form-switch">
                  <input class="form-check-input qa-helper-seed-include-toggle" type="checkbox" role="switch" data-seed-item-id="${seedItem.id}" ${seedItem.included_for_testcase_generation ? 'checked' : ''}>
                </div>
              </div>
              <div class="qa-helper-seed-card-body">
                <dl class="qa-helper-seed-kv">
                  <dt>${escapeHtml(t('qaAiHelper.seedSourceSection', {}, 'Section'))}</dt>
                  <dd>${escapeHtml(`${seedItem.section_id || '-'} ${seedItem.section_title || ''}`.trim())}</dd>
                  <dt>${escapeHtml(t('qaAiHelper.seedSourceItem', {}, '驗證項目'))}</dt>
                  <dd>${escapeHtml(seedItem.verification_item_summary || '-')}</dd>
                  <dt>${escapeHtml(t('qaAiHelper.seedCoverageTags', {}, 'Coverage'))}</dt>
                  <dd>${escapeHtml(coverageText)}</dd>
                </dl>
                <div class="qa-helper-seed-body">${escapeHtml(seedBodyText(seedItem))}</div>
                <div class="d-flex justify-content-between align-items-center gap-2">
                  <div class="qa-helper-comment-preview" title="${escapeHtml(comment || '')}">
                    <i class="fas fa-comment"></i>
                    <span>${escapeHtml(commentSnippet || t('qaAiHelper.noSeedComment', {}, '尚未提供註解'))}</span>
                  </div>
                  <button type="button" class="btn btn-outline-secondary btn-sm qa-helper-seed-comment-toggle" data-seed-comment-toggle="${seedItem.id}">
                    <i class="fas fa-plus me-1"></i>${escapeHtml(t('qaAiHelper.seedCommentAction', {}, '註解'))}
                  </button>
                </div>
                <div class="qa-helper-comment-editor ${expanded ? '' : 'd-none'}" data-seed-comment-editor="${seedItem.id}">
                  <label class="form-label small mb-1">${escapeHtml(t('qaAiHelper.seedCommentLabel', {}, 'Seed 註解'))}</label>
                  <textarea class="form-control form-control-sm qa-helper-seed-comment-input" data-seed-comment-input="${seedItem.id}" placeholder="${escapeHtml(t('qaAiHelper.seedCommentPlaceholder', {}, '補充這筆 seed 需要修正或強化的方向'))}">${escapeHtml(comment)}</textarea>
                </div>
              </div>
            </div>
          `;
        }).join('')
      : `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.seedListEmpty', {}, '此 section 目前沒有 seed'))}</div>`;

    renderSeedReviewSummary();
  }

  async function generateSeedSet(forceRegenerate = false) {
    const teamId = ensureTeamId();
    if (!teamId || !state.sessionId) return;
    state.seedActionInFlight = true;
    renderSeedReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/seed-sets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force_regenerate: !!forceRegenerate }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
      setActivePhaseView('plan', { force: true });
      if (forceRegenerate) {
        setFeedback('success', t('qaAiHelper.seedSetGenerated', {}, '已產生 Test Case 種子，請確認納入範圍與註解。'));
      } else {
        setFeedback('success', t('qaAiHelper.seedSetReused', {}, '已沿用既有 Test Case 種子。'));
      }
    } finally {
      state.seedActionInFlight = false;
      renderSeedReviewSummary();
    }
  }

  async function updateSeedItemInclusion(seedItemId, included) {
    const teamId = ensureTeamId();
    const seedSet = currentSeedSet();
    if (!teamId || !state.sessionId || !seedSet) return;
    state.seedActionInFlight = true;
    renderSeedReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/seed-sets/${seedSet.id}/items/${seedItemId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ included_for_testcase_generation: included }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
    } finally {
      state.seedActionInFlight = false;
      renderSeedReviewSummary();
    }
  }

  async function updateSeedSectionInclusion(included) {
    const teamId = ensureTeamId();
    const seedSet = currentSeedSet();
    const section = selectedSeedSection();
    if (!teamId || !state.sessionId || !seedSet || !section) return;
    state.seedActionInFlight = true;
    renderSeedReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/seed-sets/${seedSet.id}/sections/${encodeURIComponent(section.section_id)}/inclusion`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ included }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
    } finally {
      state.seedActionInFlight = false;
      renderSeedReviewSummary();
    }
  }

  async function updateAllSeedInclusion(included) {
    const teamId = ensureTeamId();
    const seedSet = currentSeedSet();
    if (!teamId || !state.sessionId || !seedSet) return;
    const sections = seedSections();
    if (!sections.length) return;
    state.seedActionInFlight = true;
    renderSeedReviewSummary();
    try {
      for (const section of sections) {
        const response = await authFetch(
          `/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/seed-sets/${seedSet.id}/sections/${encodeURIComponent(section.section_id)}/inclusion`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ included }) }
        );
        if (!response.ok) throw new Error(await response.text());
        updateWorkspace(await response.json());
      }
    } finally {
      state.seedActionInFlight = false;
      renderSeedReviewSummary();
    }
  }

  async function refineSeedsFromComments() {
    const teamId = ensureTeamId();
    const seedSet = currentSeedSet();
    if (!teamId || !state.sessionId || !seedSet) return;
    const items = currentSeedItems()
      .filter((item) => isSeedCommentDirty(item))
      .map((item) => ({
        seed_item_id: item.id,
        comment_text: String(seedCommentValue(item) || '').trim(),
      }))
      .filter((item) => item.comment_text);
    if (!items.length) {
      setFeedback('warning', t('qaAiHelper.seedCommentDirtyRequired', {}, '請先新增或修改至少一筆 seed 註解。'));
      return;
    }
    state.seedActionInFlight = true;
    renderSeedReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/seed-sets/${seedSet.id}/refine`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      state.seedCommentDirtyMap = {};
      updateWorkspace(await response.json());
      setFeedback('success', t('qaAiHelper.seedRefined', {}, '已依註解更新種子。'));
    } finally {
      state.seedActionInFlight = false;
      renderSeedReviewSummary();
    }
  }

  async function lockSeedSet() {
    const teamId = ensureTeamId();
    const seedSet = currentSeedSet();
    if (!teamId || !state.sessionId || !seedSet) return;
    if (hasDirtySeedComments()) {
      setFeedback('warning', t('qaAiHelper.seedDirtyPending', {}, '有未套用的註解，請先依註解更新種子。'));
      return;
    }
    state.seedActionInFlight = true;
    renderSeedReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/seed-sets/${seedSet.id}/lock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
      setFeedback('success', t('qaAiHelper.seedLocked', {}, 'Seeds 已鎖定，可進入 Test Case 產生。'));
    } finally {
      state.seedActionInFlight = false;
      renderSeedReviewSummary();
    }
  }

  async function unlockSeedSet() {
    const teamId = ensureTeamId();
    const seedSet = currentSeedSet();
    if (!teamId || !state.sessionId || !seedSet) return;
    state.seedActionInFlight = true;
    renderSeedReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/seed-sets/${seedSet.id}/unlock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
      setFeedback('success', t('qaAiHelper.seedUnlocked', {}, 'Seeds 已解鎖，可繼續調整納入範圍與註解。'));
    } finally {
      state.seedActionInFlight = false;
      renderSeedReviewSummary();
    }
  }

  function testcaseDraftBodyFromInputs(draftId) {
    const stringId = String(draftId);
    const readField = (field) => {
      const node = document.querySelector(`[data-testcase-field="${field}"][data-testcase-draft-id="${stringId}"]`);
      return node ? node.value : '';
    };
    return {
      title: String(readField('title') || '').trim(),
      priority: String(readField('priority') || 'Medium').trim() || 'Medium',
      preconditions: splitLines(readField('preconditions')),
      steps: splitLines(readField('steps')),
      expected_results: splitLines(readField('expected_results')),
    };
  }

  async function generateTestcaseDraftSet(forceRegenerate = false) {
    const teamId = ensureTeamId();
    if (!teamId || !state.sessionId) return;
    state.testcaseActionInFlight = true;
    renderTestcaseReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/testcase-draft-sets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force_regenerate: !!forceRegenerate }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
      setActivePhaseView('draft', { force: true });
      if (forceRegenerate) {
        setFeedback('success', t('qaAiHelper.testcaseDraftsGenerated', {}, '已產生 Test Case drafts，請編修內容並勾選提交項目。'));
      } else {
        setFeedback('success', t('qaAiHelper.testcaseDraftsReused', {}, '已沿用既有 Test Case drafts。'));
      }
    } finally {
      state.testcaseActionInFlight = false;
      renderTestcaseReviewSummary();
    }
  }

  async function saveTestcaseDraft(draftId) {
    const teamId = ensureTeamId();
    const draftSet = currentTestcaseDraftSet();
    if (!teamId || !state.sessionId || !draftSet || !draftId) return;
    state.testcaseActionInFlight = true;
    renderTestcaseReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/testcase-draft-sets/${draftSet.id}/drafts/${draftId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body: testcaseDraftBodyFromInputs(draftId) }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
      setFeedback('success', t('qaAiHelper.testcaseDraftSaved', {}, '已更新 testcase draft。'));
    } finally {
      state.testcaseActionInFlight = false;
      renderTestcaseReviewSummary();
    }
  }

  async function updateTestcaseDraftSelection(draftId, selectedForCommit) {
    const teamId = ensureTeamId();
    const draftSet = currentTestcaseDraftSet();
    if (!teamId || !state.sessionId || !draftSet || !draftId) return;
    state.testcaseActionInFlight = true;
    renderTestcaseReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/testcase-draft-sets/${draftSet.id}/drafts/${draftId}/selection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected_for_commit: !!selectedForCommit }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
    } finally {
      state.testcaseActionInFlight = false;
      renderTestcaseReviewSummary();
    }
  }

  async function updateTestcaseSectionSelection(selected) {
    const teamId = ensureTeamId();
    const draftSet = currentTestcaseDraftSet();
    const section = selectedTestcaseSection();
    if (!teamId || !state.sessionId || !draftSet || !section) return;
    state.testcaseActionInFlight = true;
    renderTestcaseReviewSummary();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/testcase-draft-sets/${draftSet.id}/sections/${encodeURIComponent(section.section_id)}/selection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected: !!selected }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
    } finally {
      state.testcaseActionInFlight = false;
      renderTestcaseReviewSummary();
    }
  }

  async function updateAllTestcaseSelection(selected) {
    const teamId = ensureTeamId();
    const draftSet = currentTestcaseDraftSet();
    if (!teamId || !state.sessionId || !draftSet) return;
    const sections = testcaseSections();
    if (!sections.length) return;
    state.testcaseActionInFlight = true;
    renderTestcaseReviewSummary();
    try {
      for (const section of sections) {
        const response = await authFetch(
          `/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/testcase-draft-sets/${draftSet.id}/sections/${encodeURIComponent(section.section_id)}/selection`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selected: !!selected }) }
        );
        if (!response.ok) throw new Error(await response.text());
        updateWorkspace(await response.json());
      }
    } finally {
      state.testcaseActionInFlight = false;
      renderTestcaseReviewSummary();
    }
  }

  async function initializeRequirementPlan() {
    const teamId = ensureTeamId();
    if (!teamId || !state.sessionId) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/requirement-plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const workspace = await response.json();
    updateWorkspace(workspace);
    setActivePhaseView('canonical', { force: true });
    setFeedback('success', t('qaAiHelper.screen3Ready', {}, '已進入需求驗證項目分類與填充畫面'));
  }

  async function saveRequirementPlan(options) {
    const plan = currentRequirementPlan();
    const teamId = ensureTeamId();
    if (!teamId || !state.sessionId || !plan || state.planSaveInFlight) return;
    const autosave = !!((options || {}).autosave);
    const localPlanSnapshot = autosave ? clone(plan) : null;
    const requestPlanVersion = state.planChangeVersion;
    state.planSaveInFlight = true;
    renderRequirementPlanStatus();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/requirement-plan`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          section_start_number: plan.section_start_number || '010',
          sections: plan.sections || [],
          autosave,
        }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const workspace = await response.json();
      const hasLocalChangesAfterRequest = autosave && state.planChangeVersion !== requestPlanVersion;
      if (hasLocalChangesAfterRequest && workspace && workspace.requirement_plan && localPlanSnapshot) {
        workspace.requirement_plan = localPlanSnapshot;
      }
      state.planDirty = hasLocalChangesAfterRequest;
      updateWorkspace(workspace, {
        preservePlanAutosaveState: autosave,
        renderMode: autosave ? 'requirement-plan-status' : 'full',
      });
      if (!autosave) {
        setFeedback('success', t('qaAiHelper.planSaved', {}, '已儲存需求驗證項目規劃'));
      }
    } finally {
      state.planSaveInFlight = false;
      renderRequirementPlanStatus();
    }
  }

  async function lockRequirementPlan() {
    const teamId = ensureTeamId();
    if (!teamId || !state.sessionId) return;
    if (state.planDirty) {
      await saveRequirementPlan({ autosave: false });
    }
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/requirement-plan/lock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const workspace = await response.json();
    updateWorkspace(workspace);
    setFeedback('success', t('qaAiHelper.requirementLocked', {}, '需求已鎖定，可進入種子生成'));
  }

  async function unlockRequirementPlan() {
    const teamId = ensureTeamId();
    if (!teamId || !state.sessionId) return;
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/requirement-plan/unlock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const workspace = await response.json();
    updateWorkspace(workspace);
    setFeedback('success', t('qaAiHelper.requirementUnlocked', {}, '需求已解開鎖定，可繼續編輯'));
  }

  function currentTestcaseDraftSet() {
    return (state.workspace || {}).testcase_draft_set || null;
  }

  function currentCommitResult() {
    return (state.workspace || {}).commit_result || null;
  }

  function currentScreen() {
    return String((((state.workspace || {}).session || {}).current_screen) || '').trim();
  }

  function selectedCommitDraftIds() {
    return testcaseDrafts()
      .filter((draft) => draft.selected_for_commit)
      .map((draft) => draft.id);
  }

  function selectedCommitDraftCount() {
    return selectedCommitDraftIds().length;
  }

  function commitTargetSetId() {
    return Number(state.selectedExistingTargetSetId || state.setId || 0) || null;
  }

  function isNewTargetSetValid() {
    return String((state.newTargetSetDraft.name || '')).trim().length > 0;
  }

  function canSubmitCommitTarget() {
    if (selectedCommitDraftCount() <= 0) return false;
    if (state.selectedTargetSetMode === 'new') {
      return isNewTargetSetValid();
    }
    return !!commitTargetSetId();
  }

  function testcaseDrafts() {
    return ((currentTestcaseDraftSet() || {}).drafts) || [];
  }

  function testcaseSections() {
    const sections = [];
    const byKey = new Map();
    testcaseDrafts().forEach((draft) => {
      const key = String(draft.section_key || draft.section_id || `section-${draft.id}`).trim();
      if (!byKey.has(key)) {
        const section = {
          section_key: key,
          section_id: draft.section_id || '-',
          section_title: draft.section_title || draft.section_id || '-',
          drafts: [],
        };
        byKey.set(key, section);
        sections.push(section);
      }
      byKey.get(key).drafts.push(draft);
    });
    return sections.map((section) => {
      const validCount = section.drafts.filter((draft) => (draft.validation_summary || {}).is_valid).length;
      const selectedCount = section.drafts.filter((draft) => draft.selected_for_commit).length;
      return {
        ...section,
        draft_count: section.drafts.length,
        valid_count: validCount,
        invalid_count: section.drafts.length - validCount,
        selected_count: selectedCount,
      };
    });
  }

  function ensureSelectedTestcaseSectionKey() {
    const sections = testcaseSections();
    if (!sections.length) {
      state.selectedTestcaseSectionKey = null;
      return null;
    }
    if (!state.selectedTestcaseSectionKey || !sections.some((section) => section.section_key === state.selectedTestcaseSectionKey)) {
      state.selectedTestcaseSectionKey = sections[0].section_key;
    }
    return state.selectedTestcaseSectionKey;
  }

  function selectedTestcaseSection() {
    const key = ensureSelectedTestcaseSectionKey();
    return testcaseSections().find((section) => section.section_key === key) || null;
  }

  function testcaseDraftsForSelectedSection() {
    const section = selectedTestcaseSection();
    return section ? section.drafts : [];
  }

  function testcaseValidationClass(validationSummary) {
    return validationSummary && validationSummary.is_valid ? 'text-bg-success' : 'text-bg-warning';
  }

  function renderTestcaseReviewSummary() {
    const summary = el('qaHelperTestcaseReviewSummary');
    const actionStatus = el('qaHelperTestcaseActionStatus');
    const selectSectionBtn = el('qaHelperSelectSectionDraftsBtn');
    const clearSectionBtn = el('qaHelperClearSectionDraftsBtn');
    const selectAllBtn = el('qaHelperSelectAllDraftsBtn');
    const clearAllBtn = el('qaHelperClearAllDraftsBtn');
    const nextBtn = el('qaHelperSelectTargetSetBtn');
    if (!summary) return;
    const draftSet = currentTestcaseDraftSet();
    if (!draftSet) {
      summary.innerHTML = '';
      if (actionStatus) actionStatus.textContent = t('qaAiHelper.testcaseDraftPending', {}, '請先從畫面四產生並鎖定 testcase drafts。');
      if (selectSectionBtn) selectSectionBtn.disabled = true;
      if (clearSectionBtn) clearSectionBtn.disabled = true;
      if (selectAllBtn) selectAllBtn.disabled = true;
      if (clearAllBtn) clearAllBtn.disabled = true;
      if (nextBtn) nextBtn.disabled = true;
      return;
    }
    const selectedCount = Number(draftSet.selected_for_commit_count || 0);
    const savedAt = formatUtcDate(draftSet.updated_at);
    summary.innerHTML = `
      <div class="d-flex flex-wrap align-items-center gap-3 small text-muted">
        <span>${escapeHtml(t('qaAiHelper.generatedTestcaseCount', {}, '產生 testcase 數'))} <strong class="qa-helper-mono">${draftSet.generated_testcase_count || 0}</strong></span>
        <span>${escapeHtml(t('qaAiHelper.selectedForCommitCount', {}, '已勾選提交'))} <strong class="qa-helper-mono">${selectedCount}</strong></span>
        <span class="ms-auto">${escapeHtml(t('qaAiHelper.lastSavedAt', { value: savedAt }, `最後儲存 ${savedAt}`))}</span>
      </div>
    `;
    const selectedSection = selectedTestcaseSection();
    const hasSection = !!selectedSection;
    if (selectSectionBtn) selectSectionBtn.disabled = !hasSection || state.testcaseActionInFlight;
    if (clearSectionBtn) clearSectionBtn.disabled = !hasSection || state.testcaseActionInFlight;
    if (selectAllBtn) selectAllBtn.disabled = state.testcaseActionInFlight;
    if (clearAllBtn) clearAllBtn.disabled = state.testcaseActionInFlight;
    if (nextBtn) nextBtn.disabled = state.testcaseActionInFlight || selectedCount <= 0;
    if (actionStatus) {
      actionStatus.textContent = selectedCount > 0
        ? t('qaAiHelper.testcaseDraftReady', {}, '已可進入畫面六選擇目標 Test Case Set。')
        : t('qaAiHelper.testcaseDraftPending', {}, '請至少勾選一筆通過驗證的 testcase 後，才能進入下一步。');
    }
  }

  function renderTestcaseReviewWorkspace() {
    const card = el('qaHelperTestcaseReviewCard');
    const rail = el('qaHelperTestcaseSectionRail');
    const railCount = el('qaHelperTestcaseSectionRailCount');
    const cardList = el('qaHelperTestcaseCardList');
    if (!card || !rail || !cardList) return;
    const screen = currentScreen();
    const visible = !!currentTestcaseDraftSet() && screen === 'testcase_review';
    card.classList.toggle('d-none', !visible);
    if (!visible) return;
    const sections = testcaseSections();
    if (railCount) railCount.textContent = String(sections.length);
    if (!sections.length) {
      rail.innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.testcaseSectionEmpty', {}, '尚無 testcase sections'))}</div>`;
      cardList.innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.testcaseListEmpty', {}, '尚未產生 testcase drafts'))}</div>`;
      renderTestcaseReviewSummary();
      return;
    }
    const selectedKey = ensureSelectedTestcaseSectionKey();
    rail.innerHTML = sections.map((section) => `
      <button type="button" class="btn text-start qa-helper-section-item p-3 ${section.section_key === selectedKey ? 'active' : ''}" data-testcase-section-key="${escapeHtml(section.section_key)}">
        <div class="d-flex justify-content-between gap-2">
          <div>
            <div class="qa-helper-mono fw-semibold">${escapeHtml(section.section_id)}</div>
            <div>${escapeHtml(section.section_title)}</div>
          </div>
          <span class="badge text-bg-light">${section.draft_count}</span>
        </div>
        <div class="small text-muted mt-2">${escapeHtml(t('qaAiHelper.selectedForCommitCount', {}, '已勾選提交'))}: ${section.selected_count}</div>
      </button>
    `).join('');

    const drafts = testcaseDraftsForSelectedSection();
    if (!drafts.length) {
      cardList.innerHTML = `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.testcaseListEmpty', {}, '尚未產生 testcase drafts'))}</div>`;
      renderTestcaseReviewSummary();
      return;
    }
    cardList.innerHTML = drafts.map((draft) => {
      const body = draft.body || {};
      const validationSummary = draft.validation_summary || {};
      const errors = Array.isArray(validationSummary.errors) ? validationSummary.errors : [];
      return `
        <div class="qa-helper-testcase-card ${draft.selected_for_commit ? 'is-selected' : ''}" data-testcase-draft-id="${draft.id}">
          <div class="qa-helper-testcase-card-head">
            <div class="d-flex flex-column gap-1">
              <div class="d-flex flex-wrap gap-2 align-items-center">
                <span class="qa-helper-mono fw-semibold">${escapeHtml(draft.assigned_testcase_id || draft.seed_reference_key)}</span>
                <span class="badge text-bg-light">${escapeHtml(draft.seed_reference_key)}</span>
                ${draft.is_ai_generated ? `<span class="badge text-bg-info">${escapeHtml(t('qaAiHelper.aiGenerated', {}, 'AI 產出'))}</span>` : ''}
                <span class="badge ${testcaseValidationClass(validationSummary)}">${escapeHtml(validationSummary.is_valid ? t('qaAiHelper.validationPass', {}, '可提交') : t('qaAiHelper.validationFail', {}, '待修正'))}</span>
              </div>
              <div class="small text-muted">${escapeHtml(draft.verification_item_summary || draft.section_title || '-')}</div>
            </div>
            <div class="form-check form-switch ms-lg-3">
              <input class="form-check-input qa-helper-testcase-select-toggle" type="checkbox" role="switch" data-testcase-draft-select-id="${draft.id}" ${draft.selected_for_commit ? 'checked' : ''} ${validationSummary.is_valid ? '' : 'disabled'}>
              <label class="form-check-label">${escapeHtml(t('qaAiHelper.selectForCommit', {}, '選擇提交'))}</label>
            </div>
          </div>
          <div class="qa-helper-seed-card-body">
            <div class="row g-3">
              <div class="col-lg-8">
                <label class="form-label">${escapeHtml(t('common.title', {}, '標題'))}</label>
                <input type="text" class="form-control" data-testcase-field="title" data-testcase-draft-id="${draft.id}" value="${escapeHtml(body.title || '')}">
              </div>
              <div class="col-lg-4">
                <label class="form-label">${escapeHtml(t('testCase.priority', {}, '優先級'))}</label>
                <select class="form-select" data-testcase-field="priority" data-testcase-draft-id="${draft.id}">
                  <option value="High" ${String(body.priority || 'Medium') === 'High' ? 'selected' : ''}>High</option>
                  <option value="Medium" ${String(body.priority || 'Medium') === 'Medium' ? 'selected' : ''}>Medium</option>
                  <option value="Low" ${String(body.priority || 'Medium') === 'Low' ? 'selected' : ''}>Low</option>
                </select>
              </div>
              <div class="col-12">
                <label class="form-label">${escapeHtml(t('qaAiHelper.preconditions', {}, 'Preconditions'))}</label>
                <textarea class="form-control qa-helper-textarea-sm" data-testcase-field="preconditions" data-testcase-draft-id="${draft.id}">${escapeHtml(joinLines(body.preconditions || []))}</textarea>
              </div>
              <div class="col-12">
                <label class="form-label">${escapeHtml(t('qaAiHelper.steps', {}, 'Steps'))}</label>
                <textarea class="form-control qa-helper-textarea" data-testcase-field="steps" data-testcase-draft-id="${draft.id}">${escapeHtml(joinLines(body.steps || []))}</textarea>
              </div>
              <div class="col-12">
                <label class="form-label">${escapeHtml(t('qaAiHelper.expectedResults', {}, 'Expected Results'))}</label>
                <textarea class="form-control qa-helper-textarea-sm" data-testcase-field="expected_results" data-testcase-draft-id="${draft.id}">${escapeHtml(joinLines(body.expected_results || []))}</textarea>
              </div>
            </div>
            <dl class="qa-helper-seed-kv">
              <dt>${escapeHtml(t('qaAiHelper.seedSourceSection', {}, '來源 Section'))}</dt>
              <dd>${escapeHtml(draft.section_id || '-')}</dd>
              <dt>${escapeHtml(t('qaAiHelper.seedSourceItem', {}, '來源驗證項目'))}</dt>
              <dd>${escapeHtml(draft.verification_item_summary || '-')}</dd>
            </dl>
            ${errors.length ? `<div class="alert alert-warning py-2 mb-0">${errors.map((item) => `<div>${escapeHtml(item.message || '')}</div>`).join('')}</div>` : ''}
            <div class="d-flex justify-content-end">
              <button type="button" class="btn btn-success btn-sm" data-testcase-save-id="${draft.id}">
                <i class="fas fa-floppy-disk me-1"></i><span>${escapeHtml(t('qaAiHelper.saveDraft', {}, '儲存 Draft'))}</span>
              </button>
            </div>
          </div>
        </div>
      `;
    }).join('');
    renderTestcaseReviewSummary();
  }

  function renderSetSelectionWorkspace() {
    const card = el('qaHelperSetSelectionCard');
    const existingList = el('qaHelperExistingSetList');
    const validationBox = el('qaHelperNewSetValidation');
    const commitBtn = el('qaHelperCommitSelectedBtn');
    if (!card || !existingList || !validationBox || !commitBtn) return;

    const screen = currentScreen();
    const draftSet = currentTestcaseDraftSet();
    const visible = !!draftSet && screen === 'set_selection';
    card.classList.toggle('d-none', !visible);
    if (!visible) return;

    const selectedId = commitTargetSetId();
    existingList.innerHTML = (state.sets || []).length
      ? (state.sets || []).map((item) => `
          <label class="qa-helper-target-set-option ${state.selectedTargetSetMode === 'existing' && Number(item.id) === Number(selectedId) ? 'is-active' : ''}">
            <input
              class="form-check-input me-2"
              type="radio"
              name="qaHelperTargetSetMode"
              value="existing"
              data-target-set-id="${item.id}"
              ${state.selectedTargetSetMode === 'existing' && Number(item.id) === Number(selectedId) ? 'checked' : ''}
            >
            <span class="d-flex flex-column">
              <span class="fw-semibold">${escapeHtml(item.name)}</span>
              <span class="small text-muted">${escapeHtml(item.description || t('qaAiHelper.targetSetNoDescription', {}, '無描述'))}</span>
            </span>
          </label>
        `).join('')
      : `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.targetSetListEmpty', {}, '目前沒有可用的 Test Case Set，可直接使用右側表單新建。'))}</div>`;

    const nameInput = el('qaHelperNewTargetSetName');
    const descriptionInput = el('qaHelperNewTargetSetDescription');
    const existingMode = state.selectedTargetSetMode === 'existing';
    const newMode = state.selectedTargetSetMode === 'new';
    const existingRadio = el('qaHelperExistingSetMode');
    const newRadio = el('qaHelperNewSetMode');
    if (existingRadio) existingRadio.checked = existingMode;
    if (newRadio) newRadio.checked = newMode;
    if (nameInput) {
      nameInput.value = state.newTargetSetDraft.name || '';
      nameInput.disabled = !newMode || state.commitInFlight;
    }
    if (descriptionInput) {
      descriptionInput.value = state.newTargetSetDraft.description || '';
      descriptionInput.disabled = !newMode || state.commitInFlight;
    }

    validationBox.className = `qa-helper-field-help ${newMode && !isNewTargetSetValid() ? 'text-warning' : 'text-muted'}`;
    validationBox.textContent = newMode
      ? (
        isNewTargetSetValid()
          ? t('qaAiHelper.newTargetSetValid', {}, '新 Test Case Set 欄位已完整，可直接提交。')
          : t('qaAiHelper.newTargetSetInvalid', {}, '新建模式至少需要填寫名稱。')
      )
      : t('qaAiHelper.newTargetSetHint', {}, '若選擇新建，系統會先建立 Test Case Set 再提交 testcase。');

    commitBtn.disabled = state.commitInFlight || !canSubmitCommitTarget();
  }

  function renderCommitResultWorkspace() {
    const card = el('qaHelperCommitResultCard');
    const summary = el('qaHelperCommitResultSummary');
    const detail = el('qaHelperCommitResultDetails');
    const openBtn = el('qaHelperOpenTargetSetBtn');
    if (!card || !summary || !detail || !openBtn) return;
    const screen = currentScreen();
    const result = currentCommitResult();
    const visible = screen === 'commit_result' && !!result;
    card.classList.toggle('d-none', !visible);
    if (!visible) return;

    summary.innerHTML = `
      <div><strong>${escapeHtml(t('qaAiHelper.commitTargetSet', {}, '目標 Test Case Set'))}</strong>: ${escapeHtml(result.target_test_case_set_name || '-')}</div>
      <div><strong>${escapeHtml(t('qaAiHelper.createdCount', {}, '成功建立'))}</strong>: ${Number(result.created_count || 0)}</div>
      <div><strong>${escapeHtml(t('qaAiHelper.failedCount', {}, '失敗'))}</strong>: ${Number(result.failed_count || 0)}</div>
      <div><strong>${escapeHtml(t('qaAiHelper.skippedCount', {}, '略過'))}</strong>: ${Number(result.skipped_count || 0)}</div>
    `;

    const createdRows = (result.draft_results || []).filter((item) => item.status === 'created');
    const failedRows = result.failed_drafts || [];
    const skippedRows = result.skipped_drafts || [];
    detail.innerHTML = `
      <div class="qa-helper-result-group">
        <div class="fw-semibold mb-2">${escapeHtml(t('qaAiHelper.commitCreatedCases', {}, '已建立 Test Case'))}</div>
        ${createdRows.length
          ? createdRows.map((item) => `<div class="qa-helper-result-row"><span class="qa-helper-mono">${escapeHtml(item.assigned_testcase_id || '-')}</span><span>${escapeHtml(item.seed_reference_key || '-')}</span></div>`).join('')
          : `<div class="qa-helper-empty">${escapeHtml(t('qaAiHelper.commitCreatedEmpty', {}, '本次沒有成功建立的 testcase。'))}</div>`}
      </div>
      <div class="qa-helper-result-group mt-3">
        <div class="fw-semibold mb-2">${escapeHtml(t('qaAiHelper.commitFailedDrafts', {}, '失敗項目'))}</div>
        ${failedRows.length
          ? failedRows.map((item) => `<div class="qa-helper-result-row is-failed"><span class="qa-helper-mono">${escapeHtml(item.assigned_testcase_id || item.seed_reference_key || '-')}</span><span>${escapeHtml(item.reason || '-')}</span></div>`).join('')
          : `<div class="qa-helper-empty">${escapeHtml(t('common.none', {}, '無'))}</div>`}
      </div>
      <div class="qa-helper-result-group mt-3">
        <div class="fw-semibold mb-2">${escapeHtml(t('qaAiHelper.commitSkippedDrafts', {}, '略過項目'))}</div>
        ${skippedRows.length
          ? skippedRows.map((item) => `<div class="qa-helper-result-row is-skipped"><span class="qa-helper-mono">${escapeHtml(item.assigned_testcase_id || item.seed_reference_key || '-')}</span><span>${escapeHtml(item.reason || '-')}</span></div>`).join('')
          : `<div class="qa-helper-empty">${escapeHtml(t('common.none', {}, '無'))}</div>`}
      </div>
    `;
    openBtn.disabled = !result.target_set_link;
    openBtn.setAttribute('data-target-set-link', result.target_set_link || '');
  }

  async function openSetSelection() {
    const teamId = ensureTeamId();
    const draftSet = currentTestcaseDraftSet();
    if (!teamId || !state.sessionId || !draftSet) return;
    state.commitInFlight = true;
    renderSetSelectionWorkspace();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/testcase-draft-sets/${draftSet.id}/set-selection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
    } finally {
      state.commitInFlight = false;
      renderSetSelectionWorkspace();
    }
  }

  async function backToTestcaseReview() {
    const teamId = ensureTeamId();
    const draftSet = currentTestcaseDraftSet();
    if (!teamId || !state.sessionId || !draftSet) return;
    state.commitInFlight = true;
    renderSetSelectionWorkspace();
    try {
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/testcase-draft-sets/${draftSet.id}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
    } finally {
      state.commitInFlight = false;
      renderSetSelectionWorkspace();
    }
  }

  async function commitSelectedTestcases() {
    const teamId = ensureTeamId();
    const draftSet = currentTestcaseDraftSet();
    if (!teamId || !state.sessionId || !draftSet) return;
    if (!canSubmitCommitTarget()) {
      setFeedback('warning', t('qaAiHelper.commitTargetRequired', {}, '請先選擇既有 Test Case Set，或完成新建 Test Case Set 必要欄位。'));
      return;
    }
    state.commitInFlight = true;
    renderSetSelectionWorkspace();
    try {
      const payload = {
        testcase_draft_set_id: draftSet.id,
        selected_draft_ids: selectedCommitDraftIds(),
        target_test_case_set_id: state.selectedTargetSetMode === 'existing' ? commitTargetSetId() : null,
        new_test_case_set_payload: state.selectedTargetSetMode === 'new'
          ? {
              name: String(state.newTargetSetDraft.name || '').trim(),
              description: String(state.newTargetSetDraft.description || '').trim() || null,
            }
          : null,
      };
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/testcase-draft-sets/${draftSet.id}/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      updateWorkspace(await response.json());
      await loadSets();
      await loadSessions();
      setFeedback('success', t('qaAiHelper.commitResultReady', {}, '已完成 commit，請確認新增結果。'));
    } finally {
      state.commitInFlight = false;
      renderSetSelectionWorkspace();
    }
  }

  function renderAll() {
    renderPhaseWorkflow();
    renderSessionSelect();
    renderWorkspaceSummary();
    renderTicketConfirmation();
    renderTicketValidationSummary();
    renderRequirementPlanWorkspace();
    renderSeedReviewWorkspace();
    renderTestcaseReviewWorkspace();
    renderSetSelectionWorkspace();
    renderCommitResultWorkspace();
  }

  async function fetchTicket() {
    await createSession();
    setActivePhaseView('fetch', { force: true });
    renderAll();
  }

  async function restartSession() {
    clearFeedback();
    const teamId = ensureTeamId();
    if (!teamId) return;
    if (!state.sessionId) {
      resetWorkspaceState({ clearTicketKey: true });
      renderAll();
      updateUrl();
      return;
    }
    const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${state.sessionId}/restart`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    resetWorkspaceState({ clearTicketKey: true });
    renderAll();
    await loadSessions();
    updateUrl();
    setFeedback('success', t('qaAiHelper.restartCompleted', {}, '已清除目前 session，請重新輸入 Ticket Number。'));
  }

  async function proceedToVerificationPlanning() {
    const ticketSnapshot = (state.workspace || {}).ticket_snapshot;
    const validation = (ticketSnapshot && ticketSnapshot.validation_summary) || {};
    if (!ticketSnapshot) {
      setFeedback('warning', t('qaAiHelper.ticketConfirmationEmpty', {}, '載入需求單後，這裡會顯示格式檢查結果。'));
      return;
    }
    if (!validation.is_valid) {
      setFeedback('warning', t('qaAiHelper.validationBlocked', {}, '格式檢查未通過，暫時不能進入下一步。'));
      return;
    }
    await initializeRequirementPlan();
  }

  function bindEvents() {
    bindIfPresent('qaHelperRefreshSessionsBtn', 'click', () => loadSessions().catch(handleError));
    bindIfPresent('qaHelperSessionManagerBtn', 'click', () => {
      openSessionManager();
      loadSessions().catch(handleError);
    });
    bindIfPresent('qaHelperSessionManagerRefreshBtn', 'click', () => loadSessions().catch(handleError));
    bindIfPresent('qaHelperSessionManagerSelectAllBtn', 'click', () => {
      state.sessionManagerCheckedIds = (state.sessions || []).map((item) => Number(((item || {}).session || {}).id || 0)).filter((id) => id > 0);
      renderSessionManager();
    });
    bindIfPresent('qaHelperSessionManagerResumeBtn', 'click', () => resumeManagedSession().catch(handleError));
    bindIfPresent('qaHelperSessionManagerDeleteOneBtn', 'click', async () => {
      const selected = sessionManagerSelectedItem();
      if (!selected) return;
      if (!confirmAction(t('qaAiHelper.deleteSessionConfirm', {
        ticket: String(((selected || {}).session || {}).ticket_key || '-'),
      }, '確定要刪除目前 Session 嗎？'))) return;
      await deleteSessions([selected.session.id]);
      renderSessionManager();
      setFeedback('success', t('qaAiHelper.sessionDeleted', {}, '已刪除 Session'));
    });
    bindIfPresent('qaHelperSessionManagerDeleteSelectedBtn', 'click', async () => {
      if (!(state.sessionManagerCheckedIds || []).length) return;
      const selectedCount = state.sessionManagerCheckedIds.length;
      if (!confirmAction(t('qaAiHelper.deleteSelectedSessionsConfirm', {
        count: selectedCount,
      }, '確定要刪除勾選的 Sessions 嗎？'))) return;
      await deleteSessions(state.sessionManagerCheckedIds);
      renderSessionManager();
      setFeedback('success', t('qaAiHelper.sessionsDeleted', {
        count: selectedCount,
      }, '已刪除勾選的 Sessions'));
    });
    bindIfPresent('qaHelperSessionManagerClearBtn', 'click', async () => {
      const ids = (state.sessions || []).map((item) => Number(((item || {}).session || {}).id || 0)).filter((id) => id > 0);
      if (!ids.length) return;
      if (!confirmAction(t('qaAiHelper.clearAllSessionsConfirm', {}, '確定要清空全部 Sessions 嗎？'))) return;
      await deleteSessions(ids);
      renderSessionManager();
      setFeedback('success', t('qaAiHelper.sessionsCleared', {
        count: ids.length,
      }, '已清空全部 Sessions'));
    });
    document.querySelectorAll('[data-phase-target]').forEach((button) => {
      button.addEventListener('click', (event) => {
        const phase = event.currentTarget.getAttribute('data-phase-target');
        setActivePhaseView(phase);
        renderPhaseWorkflow();
      });
    });
    bindIfPresent('qaHelperPrevPhaseBtn', 'click', () => {
      const index = PHASE_ORDER.indexOf(state.activePhaseView);
      if (index > 0) {
        setActivePhaseView(PHASE_ORDER[index - 1]);
        renderPhaseWorkflow();
      }
    });
    bindIfPresent('qaHelperNextPhaseBtn', 'click', () => {
      const index = PHASE_ORDER.indexOf(state.activePhaseView);
      const nextPhase = PHASE_ORDER[index + 1];
      if (nextPhase) {
        setActivePhaseView(nextPhase);
        renderPhaseWorkflow();
      }
    });
    bindIfPresent('qaHelperSessionSelect', 'change', (event) => {
      const value = Number(event.target.value || 0);
      if (value) {
        loadWorkspace(value).catch(handleError);
      }
    });
    bindIfPresent('qaHelperCreateSessionBtn', 'click', () => fetchTicket().catch(handleError));
    document.querySelectorAll('[data-qa-helper-restart]').forEach((button) => {
      button.addEventListener('click', () => restartSession().catch(handleError));
    });
    bindIfPresent('qaHelperProceedVerificationBtn', 'click', () => proceedToVerificationPlanning().catch(handleError));
    bindIfPresent('qaHelperBackToTicketConfirmationBtn', 'click', () => navigateToPhase('fetch'));
    bindIfPresent('qaHelperBackToRequirementPlanBtn', 'click', () => navigateToPhase('canonical'));
    bindIfPresent('qaHelperBackToSeedReviewBtn', 'click', () => navigateToPhase('plan'));
    bindIfPresent('qaHelperDeleteSessionBtn', 'click', async () => {
      const teamId = ensureTeamId();
      const sessionId = state.sessionId || Number(el('qaHelperSessionSelect').value || 0);
      if (!teamId || !sessionId) return;
      if (!confirmAction(t('qaAiHelper.deleteSessionConfirm', {}, '確定要刪除目前 Session 嗎？'))) return;
      const response = await authFetch(`/api/teams/${teamId}/qa-ai-helper/sessions/${sessionId}`, { method: 'DELETE' });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      resetWorkspaceState({ clearTicketKey: true });
      renderAll();
      await loadSessions();
      updateUrl();
      setFeedback('success', t('qaAiHelper.sessionDeleted', {}, '已刪除 Session'));
    });
    bindIfPresent('qaHelperRefDrawerToggleBtn', 'click', () => {
      const drawer = el('qaHelperRefDrawer');
      if (drawer) drawer.classList.toggle('is-open');
    });
    bindIfPresent('qaHelperRefDrawerCloseBtn', 'click', () => {
      const drawer = el('qaHelperRefDrawer');
      if (drawer) drawer.classList.remove('is-open');
    });
    bindIfPresent('qaHelperSaveRequirementPlanBtn', 'click', () => saveRequirementPlan({ autosave: false }).catch(handleError));
    bindIfPresent('qaHelperLockRequirementPlanBtn', 'click', () => lockRequirementPlan().catch(handleError));
    bindIfPresent('qaHelperUnlockRequirementPlanBtn', 'click', () => unlockRequirementPlan().catch(handleError));
    bindIfPresent('qaHelperStartSeedReviewBtn', 'click', () => generateSeedSet(true).catch(handleError));
    bindIfPresent('qaHelperRegenerateSeedsBtn', 'click', () => generateSeedSet(true).catch(handleError));
    bindIfPresent('qaHelperProceedToSeedReviewBtn', 'click', () => generateSeedSet(false).catch(handleError));
    bindIfPresent('qaHelperRefineSeedsBtn', 'click', () => refineSeedsFromComments().catch(handleError));
    bindIfPresent('qaHelperLockSeedsBtn', 'click', () => lockSeedSet().catch(handleError));
    bindIfPresent('qaHelperUnlockSeedsBtn', 'click', () => unlockSeedSet().catch(handleError));
    bindIfPresent('qaHelperIncludeSectionSeedsBtn', 'click', () => updateSeedSectionInclusion(true).catch(handleError));
    bindIfPresent('qaHelperExcludeSectionSeedsBtn', 'click', () => updateSeedSectionInclusion(false).catch(handleError));
    bindIfPresent('qaHelperIncludeAllSeedsBtn', 'click', () => updateAllSeedInclusion(true).catch(handleError));
    bindIfPresent('qaHelperExcludeAllSeedsBtn', 'click', () => updateAllSeedInclusion(false).catch(handleError));
    bindIfPresent('qaHelperStartTestcaseReviewBtn', 'click', () => generateTestcaseDraftSet(true).catch(handleError));
    bindIfPresent('qaHelperRegenerateTestcasesBtn', 'click', () => generateTestcaseDraftSet(true).catch(handleError));
    bindIfPresent('qaHelperProceedToTestcaseReviewBtn', 'click', () => generateTestcaseDraftSet(false).catch(handleError));
    bindIfPresent('qaHelperSelectSectionDraftsBtn', 'click', () => updateTestcaseSectionSelection(true).catch(handleError));
    bindIfPresent('qaHelperClearSectionDraftsBtn', 'click', () => updateTestcaseSectionSelection(false).catch(handleError));
    bindIfPresent('qaHelperSelectAllDraftsBtn', 'click', () => updateAllTestcaseSelection(true).catch(handleError));
    bindIfPresent('qaHelperClearAllDraftsBtn', 'click', () => updateAllTestcaseSelection(false).catch(handleError));
    bindIfPresent('qaHelperSelectTargetSetBtn', 'click', () => openSetSelection().catch(handleError));
    bindIfPresent('qaHelperBackToTestcaseReviewBtn', 'click', () => backToTestcaseReview().catch(handleError));
    bindIfPresent('qaHelperCommitSelectedBtn', 'click', () => commitSelectedTestcases().catch(handleError));
    bindIfPresent('qaHelperOpenTargetSetBtn', 'click', (event) => {
      const link = String(event.currentTarget.getAttribute('data-target-set-link') || '').trim();
      if (link) {
        window.location.href = link;
      }
    });
    bindIfPresent('qaHelperSessionManagerList', 'click', (event) => {
      const checkbox = event.target.closest('[data-session-manager-check-id]');
      if (checkbox) return;
      const item = event.target.closest('[data-session-manager-item-id]');
      if (!item) return;
      state.sessionManagerSelectedId = Number(item.getAttribute('data-session-manager-item-id') || 0) || null;
      renderSessionManager();
    });
    bindIfPresent('qaHelperSessionManagerList', 'change', (event) => {
      const checkbox = event.target.closest('[data-session-manager-check-id]');
      if (!checkbox) return;
      const sessionId = Number(checkbox.getAttribute('data-session-manager-check-id') || 0);
      if (!sessionId) return;
      const checked = !!checkbox.checked;
      const current = new Set((state.sessionManagerCheckedIds || []).map((id) => Number(id)));
      if (checked) current.add(sessionId);
      else current.delete(sessionId);
      state.sessionManagerCheckedIds = Array.from(current);
      if (!state.sessionManagerSelectedId) {
        state.sessionManagerSelectedId = sessionId;
      }
      renderSessionManager();
    });
    bindIfPresent('qaHelperSectionStartNumber', 'input', (event) => {
      const plan = currentRequirementPlan();
      if (!plan || isRequirementPlanLocked()) return;
      const normalized = String(event.target.value || '').replace(/[^\d]/g, '').slice(0, 3);
      event.target.value = normalized;
      if (normalized.length === 3) {
        plan.section_start_number = normalized;
        recomputeRequirementSectionIds(plan);
        markRequirementPlanDirty();
        renderRequirementPlanWorkspace();
      }
    });

    document.addEventListener('change', (event) => {
      if (event.target && event.target.name === 'qaHelperTargetSetMode') {
        const mode = String(event.target.value || 'existing').trim();
        state.selectedTargetSetMode = mode === 'new' ? 'new' : 'existing';
        const targetSetId = Number(event.target.getAttribute('data-target-set-id') || 0) || null;
        if (targetSetId) {
          state.selectedExistingTargetSetId = targetSetId;
        }
        renderSetSelectionWorkspace();
        return;
      }
      if (event.target && event.target.classList && event.target.classList.contains('qa-helper-testcase-select-toggle')) {
        const draftId = Number(event.target.getAttribute('data-testcase-draft-select-id') || 0);
        if (!draftId) return;
        updateTestcaseDraftSelection(draftId, !!event.target.checked).catch(handleError);
      }
    });
    document.addEventListener('click', (event) => {
      const seedSectionButton = event.target.closest('[data-seed-section-key]');
      if (seedSectionButton) {
        state.selectedSeedSectionKey = seedSectionButton.getAttribute('data-seed-section-key');
        renderSeedReviewWorkspace();
        return;
      }
      const seedCommentToggle = event.target.closest('[data-seed-comment-toggle]');
      if (seedCommentToggle) {
        const seedItemId = String(seedCommentToggle.getAttribute('data-seed-comment-toggle') || '').trim();
        if (!seedItemId) return;
        state.expandedSeedCommentIds[seedItemId] = !state.expandedSeedCommentIds[seedItemId];
        renderSeedReviewWorkspace();
        return;
      }
      const sectionButton = event.target.closest('[data-plan-section-key]');
      if (sectionButton) {
        state.selectedPlanSectionKey = sectionButton.getAttribute('data-plan-section-key');
        renderRequirementPlanWorkspace();
        return;
      }
      const testcaseSectionButton = event.target.closest('[data-testcase-section-key]');
      if (testcaseSectionButton) {
        state.selectedTestcaseSectionKey = testcaseSectionButton.getAttribute('data-testcase-section-key');
        renderTestcaseReviewWorkspace();
        return;
      }
      const testcaseSaveButton = event.target.closest('[data-testcase-save-id]');
      if (testcaseSaveButton) {
        const draftId = Number(testcaseSaveButton.getAttribute('data-testcase-save-id') || 0);
        if (!draftId) return;
        saveTestcaseDraft(draftId).catch(handleError);
        return;
      }
      if (event.target.closest('#qaHelperAddVerificationItemBtn')) {
        const section = selectedPlanSection();
        if (!section || isRequirementPlanLocked()) return;
        normalizePlanSectionVerificationItems(section);
        section.verification_items.push(createEmptyVerificationItem());
        markRequirementPlanDirty();
        renderRequirementPlanWorkspace();
        return;
      }
      const removeItemButton = event.target.closest('[data-plan-remove-item-index]');
      if (removeItemButton) {
        const section = selectedPlanSection();
        if (!section || isRequirementPlanLocked()) return;
        normalizePlanSectionVerificationItems(section);
        const itemIndex = Number(removeItemButton.getAttribute('data-plan-remove-item-index'));
        section.verification_items.splice(itemIndex, 1);
        markRequirementPlanDirty();
        renderRequirementPlanWorkspace();
        return;
      }
    });
    document.addEventListener('input', (event) => {
      const seedCommentInput = event.target.getAttribute('data-seed-comment-input');
      if (seedCommentInput) {
        const seedItem = currentSeedItems().find((item) => String(item.id) === String(seedCommentInput));
        if (!seedItem) return;
        const nextValue = String(event.target.value || '');
        state.seedCommentDrafts[String(seedItem.id)] = nextValue;
        state.seedCommentDirtyMap[String(seedItem.id)] = nextValue.trim() !== String(seedItem.comment_text || '').trim();
        renderSeedReviewSummary();
        return;
      }
      if (event.target && event.target.id === 'qaHelperNewTargetSetName') {
        state.newTargetSetDraft.name = String(event.target.value || '');
        renderSetSelectionWorkspace();
        return;
      }
      if (event.target && event.target.id === 'qaHelperNewTargetSetDescription') {
        state.newTargetSetDraft.description = String(event.target.value || '');
        renderSetSelectionWorkspace();
        return;
      }
      const plan = currentRequirementPlan();
      const section = selectedPlanSection();
      if (!plan || !section || isRequirementPlanLocked()) return;
      if (event.target.id === 'qaHelperSectionTitleInput') {
        section.section_title = String(event.target.value || '');
        markRequirementPlanDirty();
        return;
      }
      const itemField = event.target.getAttribute('data-plan-item-field');
      const itemIndex = Number(event.target.getAttribute('data-plan-item-index'));
      if (itemField && Number.isInteger(itemIndex)) {
        normalizePlanSectionVerificationItems(section);
        const item = (section.verification_items || [])[itemIndex];
        if (!item) return;
        if (itemField === 'summary') {
          const nextValue = String(event.target.value || '');
          item.summary = nextValue;
          const primaryCondition = ensurePrimaryCondition(item);
          primaryCondition.condition_text = nextValue;
        }
        markRequirementPlanDirty();
        return;
      }
    });
    document.addEventListener('change', (event) => {
      const seedToggleId = event.target.getAttribute('data-seed-item-id');
      if (event.target.classList && event.target.classList.contains('qa-helper-seed-include-toggle') && seedToggleId) {
        updateSeedItemInclusion(Number(seedToggleId), !!event.target.checked).catch(handleError);
        return;
      }
      const section = selectedPlanSection();
      if (!section || isRequirementPlanLocked()) return;
      const itemField = event.target.getAttribute('data-plan-item-field');
      const itemIndex = Number(event.target.getAttribute('data-plan-item-index'));
      if (itemField === 'category' && Number.isInteger(itemIndex)) {
        normalizePlanSectionVerificationItems(section);
        const item = (section.verification_items || [])[itemIndex];
        if (!item) return;
        item.category = String(event.target.value || '功能驗證');
        item.detail = {};
        markRequirementPlanDirty();
        renderRequirementPlanWorkspace();
        return;
      }
      const conditionField = event.target.getAttribute('data-plan-condition-field');
      const conditionIndex = Number(event.target.getAttribute('data-plan-condition-index'));
      if (conditionField === 'coverage_tag' && Number.isInteger(itemIndex) && Number.isInteger(conditionIndex)) {
        normalizePlanSectionVerificationItems(section);
        const item = (section.verification_items || [])[itemIndex];
        const condition = item ? ensurePrimaryCondition(item) : null;
        if (!condition) return;
        condition.coverage_tag = String(event.target.value || '');
        markRequirementPlanDirty();
      }
    });
  }

  function handleError(error) {
    console.error(error);
    const message = error && error.message ? error.message : t('common.failed', {}, '失敗');
    setFeedback('danger', message);
  }

  async function initializePage() {
    if (state.bootstrapped) return;
    state.bootstrapped = true;
    if (window.marked && typeof window.marked.setOptions === 'function') {
      window.marked.setOptions({ breaks: true, gfm: true });
    }
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

  document.addEventListener('DOMContentLoaded', initializePage);
  document.addEventListener('authReady', () => {
    loadSets().catch(handleError);
    loadSessions().catch(handleError);
  });
  document.addEventListener('i18nReady', renderAll);
  document.addEventListener('languageChanged', renderAll);
})();
