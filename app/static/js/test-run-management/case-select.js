/* ============================================================
   TEST RUN MANAGEMENT - CASE SELECTION
   ============================================================ */

// ---- Test Case 選擇流程 ----
let caseSelectModalInstance = null;
let currentSelectingConfigId = null;
let availableCases = [];
let selectedCaseMap = new Map(); // key: test_case_number, value: case object
let pendingCreate = false; // true only for newly created config awaiting items
let createdItemsInSession = false; // set true when items are created
let modalMode = 'create'; // 'create' | 'edit'
let existingItemIdByCaseNumber = new Map(); // for edit mode: case_number -> item_id
let currentCaseFilter = 'all'; // 'all' | 'selected' | 'unselected'
let isPreselectedFromTestCaseSet = false; // 標記是否從 Test Case Set 預選的流程
let currentScopeSetIdsForCaseSelection = []; // Test Run 允許的 Test Case Set 範圍
let currentSetIdForCaseSelection = null; // Case Select 視窗目前的 Set 篩選（可為空）
let currentSectionFilterId = null; // 依 Section 過濾
let currentSectionTree = [];
let sectionTreeContainer = null;
let caseSelectData = { sections: [], testCases: [], filteredCases: [], selectedCaseIds: new Set() };

function normalizeSetIds(values) {
  const normalized = [];
  const seen = new Set();
  (Array.isArray(values) ? values : []).forEach(raw => {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed) || parsed <= 0 || seen.has(parsed)) return;
    seen.add(parsed);
    normalized.push(parsed);
  });
  return normalized;
}

function getSelectedConfigSetIds() {
  const configSelect = document.getElementById('testCaseSetSelector');
  if (!configSelect) return [];
  const selected = Array.from(configSelect.selectedOptions || []).map(opt => Number(opt.value));
  return normalizeSetIds(selected);
}

function setSelectedConfigSetIds(setIds) {
  const configSelect = document.getElementById('testCaseSetSelector');
  if (!configSelect) return;
  const setIdSet = new Set(normalizeSetIds(setIds));
  Array.from(configSelect.options || []).forEach(option => {
    option.selected = setIdSet.has(Number(option.value));
  });
}

function getTestRunSetDisplayName(setId) {
  const set = (testCaseSets || []).find(item => String(item.id) === String(setId));
  if (set && set.name) return set.name;
  return setId ? `Set #${setId}` : '';
}

function getTestRunSetDisplayNames(setIds) {
  const normalized = normalizeSetIds(setIds);
  if (!normalized.length) return '';
  return normalized.map(id => getTestRunSetDisplayName(id)).join('、');
}

function updateTestRunSetReadOnlyDisplay(setIds, mode) {
  const selectedLabel = getTestRunSetDisplayNames(setIds);
  const configSelectGroup = document.getElementById('testCaseSetSelectorGroup');
  const configReadOnlyGroup = document.getElementById('testCaseSetReadOnlyGroup');
  const configReadOnlyText = document.getElementById('testCaseSetReadOnlyText');
  const caseSelectGroup = document.getElementById('caseSelectSetSelectorGroup');
  const caseReadOnlyGroup = document.getElementById('caseSelectSetReadOnlyGroup');
  const caseReadOnlyText = document.getElementById('caseSelectSetReadOnlyText');

  // 多 Set 模式下，建立與編輯都允許調整範圍，read-only 區塊僅保留相容性（預設不顯示）
  if (configSelectGroup) configSelectGroup.classList.remove('d-none');
  if (configReadOnlyGroup) configReadOnlyGroup.classList.add('d-none');
  if (configReadOnlyText) configReadOnlyText.textContent = selectedLabel;

  if (caseSelectGroup) caseSelectGroup.classList.remove('d-none');
  if (caseReadOnlyGroup) caseReadOnlyGroup.classList.add('d-none');
  if (caseReadOnlyText) caseReadOnlyText.textContent = selectedLabel;
}

async function resolveConfigTestCaseSetIds(configId) {
  if (!configId || !currentTeamId) return [];
  try {
    const configResp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${configId}`);
    if (configResp.ok) {
      const config = await configResp.json();
      const configScope = normalizeSetIds(config?.test_case_set_ids || []);
      if (configScope.length) {
        return configScope;
      }
    }
    const resp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${configId}/items?limit=10000`);
    if (!resp.ok) return [];
    const items = await resp.json();
    if (!Array.isArray(items) || items.length === 0) return [];
    return normalizeSetIds(items.map(item => item?.test_case_set_id));
  } catch (error) {
    console.warn('resolveConfigTestCaseSetIds failed:', error);
    return [];
  }
}

function renderSectionTree() {
  renderCaseSelectList();
}

function getCasesInCurrentSetFilter() {
  if (!Array.isArray(caseSelectData.testCases)) return [];
  if (!currentSetIdForCaseSelection) return [];
  return caseSelectData.testCases.filter(tc => Number(tc.test_case_set_id) === Number(currentSetIdForCaseSelection));
}

function updateCurrentSetSelectAllState() {
  const checkbox = document.getElementById('selectAllCurrentSetCheckbox');
  const hintEl = document.getElementById('selectAllCurrentSetHint');
  if (!checkbox) return;

  const chooseHint = (window.i18n && window.i18n.isReady())
    ? window.i18n.t('testRun.caseSelect.selectAllCurrentSetChooseHint', {}, '請先選擇單一 Test Case Set')
    : '請先選擇單一 Test Case Set';

  if (!currentSetIdForCaseSelection) {
    checkbox.checked = false;
    checkbox.indeterminate = false;
    checkbox.disabled = true;
    if (hintEl) hintEl.textContent = chooseHint;
    return;
  }

  const scopedCases = getCasesInCurrentSetFilter();
  const selectedCount = scopedCases.reduce((count, testCase) => {
    return count + (selectedCaseMap.has(getCaseKey(testCase)) ? 1 : 0);
  }, 0);

  checkbox.disabled = scopedCases.length === 0;
  checkbox.checked = scopedCases.length > 0 && selectedCount === scopedCases.length;
  checkbox.indeterminate = selectedCount > 0 && selectedCount < scopedCases.length;

  if (hintEl) {
    const setName = getTestRunSetDisplayName(currentSetIdForCaseSelection) || `Set #${currentSetIdForCaseSelection}`;
    const readyHint = (window.i18n && window.i18n.isReady())
      ? window.i18n.t(
          'testRun.caseSelect.selectAllCurrentSetHint',
          { set_name: setName, selected: selectedCount, total: scopedCases.length },
          `${setName}：已選 ${selectedCount}/${scopedCases.length}`
        )
      : `${setName}：已選 ${selectedCount}/${scopedCases.length}`;
    hintEl.textContent = readyHint;
  }
}

function bindSelectAllCurrentSetCheckbox() {
  const checkbox = document.getElementById('selectAllCurrentSetCheckbox');
  if (!checkbox) return;

  checkbox.onchange = () => {
    if (!currentSetIdForCaseSelection) return;
    const scopedCases = getCasesInCurrentSetFilter();
    if (!scopedCases.length) return;

    scopedCases.forEach(testCase => {
      const key = getCaseKey(testCase);
      if (checkbox.checked) {
        selectedCaseMap.set(key, testCase);
      } else {
        selectedCaseMap.delete(key);
      }
    });

    updateSelectedCount();
    renderCaseSelectList();
  };

  updateCurrentSetSelectAllState();
}

function renderTestCaseSetOptions(scopeIdsOverride = null) {
  const configSelect = document.getElementById('testCaseSetSelector');
  const modalSelect = document.getElementById('caseSelectTestCaseSet');
  const sets = Array.isArray(testCaseSets) ? testCaseSets : [];

  const selectedScopeIds = normalizeSetIds(
    Array.isArray(scopeIdsOverride)
      ? scopeIdsOverride
      : (scopeIdsOverride ? [scopeIdsOverride] : currentScopeSetIdsForCaseSelection)
  );
  currentScopeSetIdsForCaseSelection = selectedScopeIds;

  if (configSelect) {
    configSelect.innerHTML = sets
      .map(set => {
        const selected = selectedScopeIds.includes(Number(set.id)) ? 'selected' : '';
        return `<option value="${escapeHtml(String(set.id))}" ${selected}>${escapeHtml(set.name || `Set #${set.id}`)}</option>`;
      })
      .join('');
    configSelect.multiple = true;
    const hidden = document.getElementById('configTestCaseSetId');
    if (hidden) hidden.value = selectedScopeIds.join(',');
  }

  if (modalSelect) {
    const allSetsLabel = (window.i18n && window.i18n.isReady())
      ? (window.i18n.t('testRun.sets.allSelectedSets', {}, '全部已選 Set'))
      : '全部已選 Set';

    const scopeSet = new Set(selectedScopeIds.map(id => String(id)));
    const options = [`<option value="">${escapeHtml(allSetsLabel)}</option>`];
    sets.forEach(set => {
      if (!scopeSet.has(String(set.id))) return;
      const selected = currentSetIdForCaseSelection && String(currentSetIdForCaseSelection) === String(set.id)
        ? 'selected'
        : '';
      options.push(`<option value="${escapeHtml(String(set.id))}" ${selected}>${escapeHtml(set.name || `Set #${set.id}`)}</option>`);
    });
    modalSelect.innerHTML = options.join('');
    if (currentSetIdForCaseSelection && !scopeSet.has(String(currentSetIdForCaseSelection))) {
      currentSetIdForCaseSelection = null;
      modalSelect.value = '';
    }
  }

  if (configSelect) {
    configSelect.onchange = () => {
      currentScopeSetIdsForCaseSelection = getSelectedConfigSetIds();
      const hidden = document.getElementById('configTestCaseSetId');
      if (hidden) hidden.value = currentScopeSetIdsForCaseSelection.join(',');
      if (currentScopeSetIdsForCaseSelection.length === 1) {
        currentSetIdForCaseSelection = currentScopeSetIdsForCaseSelection[0];
      } else if (!currentScopeSetIdsForCaseSelection.includes(currentSetIdForCaseSelection)) {
        currentSetIdForCaseSelection = null;
      }
      renderTestCaseSetOptions(currentScopeSetIdsForCaseSelection);
      updateTestRunSetReadOnlyDisplay(currentScopeSetIdsForCaseSelection, modalMode === 'edit' ? 'edit' : 'create');
    };
  }
  if (modalSelect) {
    modalSelect.onchange = () => {
      currentSetIdForCaseSelection = modalSelect.value ? parseInt(modalSelect.value, 10) : null;
      updateTestRunSetReadOnlyDisplay(currentScopeSetIdsForCaseSelection, modalMode === 'edit' ? 'edit' : 'create');
      renderCaseSelectList();
    };
  }

  bindSelectAllCurrentSetCheckbox();
}

async function loadTestCaseSets() {
  if (!currentTeamId) return;
  try {
    const resp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-case-sets`);
    if (resp.ok) {
      testCaseSets = await resp.json();
    } else {
      testCaseSets = [];
    }
  } catch (e) {
    console.warn('loadTestCaseSets failed', e);
    testCaseSets = [];
  }
}

async function loadSectionTreeForCurrentSet() {
  const scopeIds = normalizeSetIds(currentScopeSetIdsForCaseSelection);
  if (!scopeIds.length) {
    currentSectionTree = [];
    renderSectionTree();
    return;
  }
  try {
    const responses = await Promise.all(
      scopeIds.map(setId => window.AuthClient.fetch(`/api/test-case-sets/${setId}/sections`))
    );
    const sectionTrees = [];
    for (const resp of responses) {
      if (!resp.ok) continue;
      const sections = await resp.json();
      if (Array.isArray(sections)) sectionTrees.push(...sections);
    }
    currentSectionTree = sectionTrees;
  } catch (e) {
    console.warn('loadSectionTreeForCurrentSet failed', e);
    currentSectionTree = [];
  }
  renderSectionTree();
}

async function loadCaseSelectData() {
  const scopeIds = normalizeSetIds(currentScopeSetIdsForCaseSelection);
  if (!scopeIds.length) return;
  try {
    const sectionResponses = await Promise.all(
      scopeIds.map(setId => window.AuthClient.fetch(`/api/test-case-sets/${setId}/sections`))
    );
    const mergedSections = [];
    for (const sectionsResp of sectionResponses) {
      if (!sectionsResp.ok) continue;
      const sections = await sectionsResp.json();
      if (Array.isArray(sections)) mergedSections.push(...sections);
    }
    caseSelectData.sections = mergedSections;
    currentSectionTree = mergedSections;

    const casesResponses = await Promise.all(
      scopeIds.map(setId => window.AuthClient.fetch(`/api/teams/${currentTeamId}/testcases?set_id=${setId}&limit=10000`))
    );
    const mergedCases = [];
    for (const casesResp of casesResponses) {
      if (!casesResp.ok) continue;
      const cases = await casesResp.json();
      if (Array.isArray(cases)) mergedCases.push(...cases);
    }

    const caseMap = new Map();
    mergedCases.forEach(item => {
      const key = item?.test_case_number || String(item?.record_id || item?.id || '');
      if (!key) return;
      if (!caseMap.has(key)) caseMap.set(key, item);
    });
    caseSelectData.testCases = Array.from(caseMap.values());
    sortTestCasesByNumber(caseSelectData.testCases);
    caseSelectData.filteredCases = caseSelectData.testCases;
    availableCases = caseSelectData.testCases; // 兼容既有流程

    // 套用預選（從 Test Case Set 卡片）
    if (window._preselectedCaseIds && window._preselectedCaseIds.size > 0) {
      isPreselectedFromTestCaseSet = true;
      for (const c of caseSelectData.testCases) {
        const caseId = c.record_id || c.id;
        if (window._preselectedCaseIds.has(caseId)) {
          selectedCaseMap.set(c.test_case_number, c);
        }
      }
      window._preselectedCaseIds = null;
    }
  } catch (e) {
    console.warn('loadCaseSelectData failed', e);
    caseSelectData.sections = [];
    caseSelectData.testCases = [];
    caseSelectData.filteredCases = [];
    availableCases = [];
  }
}

// Removed confirmation step; open modal directly and rely on hidden handler for rollback
function openCaseSelectModalWithConfirm(configId) {
  pendingCreate = true;
  createdItemsInSession = false;
  modalMode = 'create';
  openCaseSelectModal(configId);
}

async function openCaseSelectModal(configId) {
  const permissions = window._testRunPermissions || testRunPermissions || {};
  if (modalMode === 'edit' && !permissions.canUpdate) {
    showPermissionDenied();
    return;
  }
  if (modalMode !== 'edit' && !permissions.canCreate) {
    showPermissionDenied();
    return;
  }

  if (!currentScopeSetIdsForCaseSelection.length) {
    const formSetIds = getSelectedConfigSetIds();
    if (formSetIds.length) {
      currentScopeSetIdsForCaseSelection = formSetIds;
    }
  }
  if (!currentScopeSetIdsForCaseSelection.length) {
    const cfg = testRunConfigs.find(c => c.id === configId);
    const cfgScope = normalizeSetIds(cfg?.test_case_set_ids || []);
    if (cfgScope.length) {
      currentScopeSetIdsForCaseSelection = cfgScope;
    }
  }
  if (!currentScopeSetIdsForCaseSelection.length) {
    const warn = window.i18n ? (window.i18n.t('testRun.sets.selectSetFirst') || '請先選擇至少一個 Test Case Set') : '請先選擇至少一個 Test Case Set';
    AppUtils.showWarning(warn);
    return;
  }
  if (!currentScopeSetIdsForCaseSelection.includes(currentSetIdForCaseSelection)) {
    currentSetIdForCaseSelection = currentScopeSetIdsForCaseSelection[0] || null;
  }

  currentSelectingConfigId = configId;
  const modalEl = document.getElementById('caseSelectModal');
  if (!caseSelectModalInstance) caseSelectModalInstance = new bootstrap.Modal(modalEl);
  if (!testCaseSets.length && currentTeamId) {
    await loadTestCaseSets();
  }
  renderTestCaseSetOptions(currentScopeSetIdsForCaseSelection);
  updateTestRunSetReadOnlyDisplay(currentScopeSetIdsForCaseSelection, modalMode === 'edit' ? 'edit' : 'create');
  await loadCaseSelectData();
  // reset
    if (modalMode === 'create') {
      existingItemIdByCaseNumber.clear();
      // 若沒有預選，保持空集合；有預選則保留 loadCaseSelectData 套用的選取
      if (!isPreselectedFromTestCaseSet) {
        selectedCaseMap.clear();
      }
    } else {
      // 編輯模式
      isPreselectedFromTestCaseSet = false;
    }
  document.getElementById('selectedCount').textContent = String(selectedCaseMap.size || 0);
  document.getElementById('caseListContainer').innerHTML = `
    <div class="text-center text-muted py-4">
      <div class="spinner-border spinner-border-sm" role="status">
        <span class="visually-hidden" data-i18n="common.loading">載入中...</span>
      </div>
    </div>`;
  const searchInput = document.getElementById('caseSearchInput');
  if (searchInput) searchInput.value = '';
  const infoEl = document.getElementById('caseSelectInfo');
  if (infoEl) infoEl.textContent = '';
  currentCaseFilter = 'all';
  // set modal title and confirm button text/handler per mode
  const titleSpan = modalEl.querySelector('.modal-title [data-i18n]');
  if (titleSpan) {
    if (modalMode === 'edit') {
      titleSpan.setAttribute('data-i18n', 'testRun.caseSelect.editTitle');
      titleSpan.textContent = (window.i18n && window.i18n.isReady()) ? window.i18n.t('testRun.caseSelect.editTitle') : '新增／修改 Test Case';
    } else {
      titleSpan.setAttribute('data-i18n', 'testRun.caseSelect.title');
      titleSpan.textContent = (window.i18n && window.i18n.isReady()) ? window.i18n.t('testRun.caseSelect.title') : '選擇要加入的 Test Case';
    }
  }
  const confirmBtn = document.getElementById('confirmCreateItemsBtn');
  const confirmTextSpan = confirmBtn.querySelector('span');
  if (modalMode === 'edit') {
    confirmTextSpan.setAttribute('data-i18n', 'common.update');
    confirmTextSpan.textContent = (window.i18n && window.i18n.isReady()) ? window.i18n.t('common.update') : '更新';
  } else {
    confirmTextSpan.setAttribute('data-i18n', 'common.create');
    confirmTextSpan.textContent = (window.i18n && window.i18n.isReady()) ? window.i18n.t('common.create') : '建立';
  }
  const newBtn = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);
  document.getElementById('confirmCreateItemsBtn').addEventListener('click', async () => {
    if (modalMode === 'edit') {
      await saveEditedItems();
    } else {
      await createItemsFromSelection();
    }
  });
  const detailModalEl = document.getElementById('testRunSetDetailModal');
  const detailWasOpen = detailModalEl && detailModalEl.classList.contains('show');
  if (detailWasOpen && testRunSetDetailModalInstance) {
    preserveSetContextOnHide = true;
    testRunSetDetailModalInstance.hide();
    reopenSetDetailAfterCaseModal = true;
  } else {
    reopenSetDetailAfterCaseModal = false;
  }
  caseSelectModalInstance.show();
  // ensure we bind a one-time hide handler for rollback if pending
  const modalDom = document.getElementById('caseSelectModal');
  // Remove previous listener if any by cloning (simple way to avoid multiple bindings)
  modalDom.addEventListener('hidden.bs.modal', async function onHidden() {
    // This will be called whenever modal hides. If pending and no items created, rollback
    if (pendingCreate && !createdItemsInSession && currentSelectingConfigId) {
      try {
        await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentSelectingConfigId}`, { method: 'DELETE' });
        const warnMsg = window.i18n ? window.i18n.t('testRun.configDeletedDueToCancel') : '已取消選擇，設定已刪除';
        AppUtils.showInfo(warnMsg);
        await loadTestRunConfigs();
      } catch (e) {
        AppUtils.showError((window.i18n ? window.i18n.t('messages.deleteFailed') : '刪除失敗') + `: ${e.message}`);
      } finally {
        pendingCreate = false;
        createdItemsInSession = false;
        currentSelectingConfigId = null;
      }
    } else {
      // Clear flags when modal hides in any case
      pendingCreate = false;
      createdItemsInSession = false;
      currentSelectingConfigId = null;
    }
    if (reopenSetDetailAfterCaseModal && testRunSetDetailModalInstance) {
      testRunSetDetailModalInstance.show();
    }
    reopenSetDetailAfterCaseModal = false;
    isPreselectedFromTestCaseSet = false;
    updateTestRunSetReadOnlyDisplay(currentScopeSetIdsForCaseSelection, 'create');
    // remove this handler after execution
    modalDom.removeEventListener('hidden.bs.modal', onHidden);
  }, { once: true });
  // load first page (資料已載入，僅渲染)
  renderCaseSelectList();
  if (window.i18n && window.i18n.isReady()) window.i18n.retranslate(document.getElementById('caseSelectModal'));
  updateCurrentSetSelectAllState();
  // bind search/clear once per open
  bindCaseSearchBarEvents();
}

// 在卡片上提供「編輯基本設定」
function editBasicSettings(configId) {
  const permissions = window._testRunPermissions || testRunPermissions || {};
  if (!permissions.canUpdate) {
    showPermissionDenied();
    return;
  }
  // 檢查 Test Run 狀態，已完成或已歸檔的不允許編輯
  const config = testRunConfigs.find(c => c.id === configId);
  if (config && (config.status === 'completed' || config.status === 'archived')) {
    const completedEditMsg = window.i18n && window.i18n.isReady() 
      ? window.i18n.t('testRun.cannotEditCompleted')
      : '已完成或已歸檔的 Test Run 不可編輯';
    AppUtils.showWarning(completedEditMsg);
    return;
  }
  openConfigFormModal(configId);
}

// 在卡片上提供「編輯 Test Case」
async function editTestCases(configId) {
  const permissions = window._testRunPermissions || testRunPermissions || {};
  if (!permissions.canUpdate) {
    showPermissionDenied();
    return;
  }
  // 檢查 Test Run 狀態，已完成的不允許編輯
  const config = testRunConfigs.find(c => c.id === configId);
  if (config && config.status === 'completed') {
    const completedEditMsg = window.i18n && window.i18n.isReady() 
      ? window.i18n.t('testRun.cannotEditCompleted')
      : '已完成的 Test Run 不可編輯 Test Case';
    AppUtils.showWarning(completedEditMsg);
    return;
  }
  try {
    modalMode = 'edit';
    pendingCreate = false;
    createdItemsInSession = false;
    currentSelectingConfigId = configId;
    // 讀取現有 items，預設勾選
    const resp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${configId}/items?limit=10000`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const items = await resp.json();

    const deducedScope = normalizeSetIds((items || []).map(it => it?.test_case_set_id));
    const configScope = normalizeSetIds(config?.test_case_set_ids || []);
    currentScopeSetIdsForCaseSelection = configScope.length ? configScope : deducedScope;
    currentSetIdForCaseSelection = currentScopeSetIdsForCaseSelection[0] || null;

    if (!currentScopeSetIdsForCaseSelection.length) {
        const warn = window.i18n ? (window.i18n.t('testRun.sets.selectSetFirst') || '請先選擇至少一個 Test Case Set') : '請先選擇至少一個 Test Case Set';
        AppUtils.showWarning(warn);
        return;
    }

    renderTestCaseSetOptions(currentScopeSetIdsForCaseSelection);

    selectedCaseMap.clear();
    existingItemIdByCaseNumber.clear();
    for (const it of items) {
      existingItemIdByCaseNumber.set(it.test_case_number, it.id);
      selectedCaseMap.set(it.test_case_number, { test_case_number: it.test_case_number, title: it.title, priority: it.priority });
    }
    openCaseSelectModal(configId);
  } catch (e) {
    AppUtils.showError((window.i18n ? window.i18n.t('messages.loadFailed') : '載入失敗') + `: ${e.message}`);
  }
}

async function loadTeamTestCases(search) {
  try {
    if (!currentScopeSetIdsForCaseSelection.length) {
      const warn = window.i18n ? (window.i18n.t('testRun.sets.selectSetFirst') || '請先選擇至少一個 Test Case Set') : '請先選擇至少一個 Test Case Set';
      AppUtils.showWarning(warn);
      return;
    }
    const searchInput = document.getElementById('caseSearchInput');
    if (searchInput && typeof search === 'string') {
      searchInput.value = search;
    }
    await loadCaseSelectData();
    renderCaseSelectList();
  } catch (e) {
    console.error('Load test cases error:', e);
    AppUtils.showError((window.i18n ? window.i18n.t('messages.loadFailed') : '載入失敗') + `: ${e.message}`);
  }
}

function isUnassignedCaseSection(section) {
  if (!section || !section.name) return false;
  return section.name.trim().toLowerCase() === 'unassigned';
}

function sortCaseSectionsForDisplay(sections) {
  if (!sections || sections.length === 0) return [];
  const unassigned = [];
  const normal = [];
  sections.forEach(sec => {
    if (isUnassignedCaseSection(sec)) unassigned.push(sec);
    else normal.push(sec);
  });
  return [...normal, ...unassigned];
}

function getCaseSectionId(testCase) {
  return testCase.test_case_section_id ?? testCase.test_case_section?.id ?? null;
}

function getCaseKey(testCase) {
  return testCase.test_case_number || String(testCase.record_id || testCase.id || '');
}

function parseCaseNumberSegments(str) {
  try {
    if (!str) return [];
    const matches = String(str).match(/\d+/g);
    return matches ? matches.map(s => parseInt(s, 10)) : [];
  } catch (_) { return []; }
}

function compareCaseNumbersByNumericParts(aStr, bStr) {
  const aSeg = parseCaseNumberSegments(aStr);
  const bSeg = parseCaseNumberSegments(bStr);
  const len = Math.min(aSeg.length, bSeg.length);
  for (let i = 0; i < len; i++) {
    if (aSeg[i] !== bSeg[i]) return aSeg[i] - bSeg[i];
  }
  return aSeg.length - bSeg.length;
}

function sortTestCasesByNumber(list) {
  if (!Array.isArray(list)) return;
  list.sort((a, b) => {
    const aNum = a?.test_case_number || '';
    const bNum = b?.test_case_number || '';
    return compareCaseNumbersByNumericParts(aNum, bNum);
  });
}

function renderCaseSelectList() {
  const container = document.getElementById('caseListContainer');
  if (!container) return;
  const searchVal = (document.getElementById('caseSearchInput')?.value || '').toLowerCase();

  caseSelectData.filteredCases = caseSelectData.testCases.filter(tc => {
    const inSetScope = !currentSetIdForCaseSelection || Number(tc.test_case_set_id) === Number(currentSetIdForCaseSelection);
    if (!inSetScope) return false;
    const num = (tc.test_case_number || '').toLowerCase();
    const title = (tc.title || '').toLowerCase();
    return num.includes(searchVal) || title.includes(searchVal);
  });

  const casesBySectionId = {};
  caseSelectData.filteredCases.forEach(tc => {
    const sid = getCaseSectionId(tc) ?? 'unassigned';
    if (!casesBySectionId[sid]) casesBySectionId[sid] = [];
    casesBySectionId[sid].push(tc);
  });

  const hasUnassigned = (casesBySectionId['unassigned'] || []).length > 0;
  const filterSectionsByData = (sections) => {
    if (!Array.isArray(sections) || sections.length === 0) return [];
    return sections.reduce((acc, sec) => {
      const childFiltered = filterSectionsByData(sec.children || []);
      const hasOwnCases = (casesBySectionId[sec.id] || []).length > 0;
      if (hasOwnCases || childFiltered.length > 0) {
        acc.push({ ...sec, children: childFiltered });
      }
      return acc;
    }, []);
  };
  let sectionsToRender = sortCaseSectionsForDisplay(filterSectionsByData(caseSelectData.sections || []));
  if (hasUnassigned) {
    sectionsToRender = [...sectionsToRender, { id: 'unassigned', name: 'Unassigned', children: [] }];
  }

  function collectSubtreeCases(sec) {
    const sid = sec.id;
    const subtree = [...(casesBySectionId[sid] || [])];
    (sec.children || []).forEach(child => {
      subtree.push(...collectSubtreeCases(child));
    });
    return subtree;
  }

  function sectionContentId(id) {
    return `case-section-content-${id}`;
  }

  function renderSectionTree(sections, level = 0) {
    if (!sections || sections.length === 0) return '';
    return sections.map(section => {
      const sid = section.id;
      const isUnassigned = sid === 'unassigned';
      const sectionKey = `case-section-${sid}`;
      const isExpanded = sessionStorage.getItem(sectionKey) !== 'collapsed';
      const sectionCases = casesBySectionId[sid] || [];
      const childSections = section.children || [];
      const subtreeCases = isUnassigned ? sectionCases : collectSubtreeCases(section);
      const allSelected = subtreeCases.length > 0 && subtreeCases.every(tc => selectedCaseMap.has(getCaseKey(tc)));
      const someSelected = subtreeCases.length > 0 && subtreeCases.some(tc => selectedCaseMap.has(getCaseKey(tc)));
      const indent = level * 20;

      return `
        <div class="section-group" style="margin-left: ${indent}px;">
          <div class="section-header d-flex align-items-center py-2 px-2 border-bottom" style="background-color: #e8eef5;">
            <input type="checkbox"
                   class="section-checkbox me-2"
                   data-section-id="${sid}"
                   ${allSelected ? 'checked' : ''}
                   ${someSelected && !allSelected ? 'data-indeterminate="true"' : ''}>
            <button class="btn btn-link btn-sm p-0 me-2 toggle-section-btn"
                    data-section-id="${sid}"
                    style="width: 24px; height: 24px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; text-decoration: none;"
                    onmouseover="this.style.textDecoration='none'"
                    onmouseout="this.style.textDecoration='none'">
              <i class="fas fa-chevron-${isExpanded ? 'down' : 'right'}"></i>
            </button>
            <span class="fw-500 flex-grow-1">${escapeHtml(section.name || (isUnassigned ? 'Unassigned' : `Section #${sid}`))}</span>
            <small class="text-muted">(${subtreeCases.length})</small>
          </div>
          <div class="section-content ${isExpanded ? '' : 'd-none'}" id="${sectionContentId(sid)}">
            ${sectionCases.map(testCase => {
              const key = getCaseKey(testCase);
              const checked = selectedCaseMap.has(key) ? 'checked' : '';
              return `
                <div class="case-item d-flex align-items-center py-2 px-3" style="background-color: #f8f9fa; border-bottom: 1px solid #e9ecef;">
                  <input type="checkbox"
                         class="case-checkbox me-3"
                         data-case-num="${escapeHtml(key)}"
                         ${checked}>
                  <code class="me-2" style="min-width: 100px; flex-shrink: 0; color: rgb(194, 54, 120); font-size: inherit; font-weight: 500;">${escapeHtml(testCase.test_case_number || '')}</code>
                  <div class="flex-grow-1 text-truncate">${escapeHtml(testCase.title || '')}</div>
                  ${testCase.priority ? `<span class="badge bg-secondary ms-2">${escapeHtml(testCase.priority)}</span>` : ''}
                </div>
              `;
            }).join('')}
            ${renderSectionTree(childSections, level + 1)}
          </div>
        </div>
      `;
    }).join('');
  }

  let html = '<div class="set-case-list">';
  if (!sectionsToRender.length) {
    const noMsg = window.i18n && window.i18n.isReady()
      ? window.i18n.t('testCase.noTestCases', {}, '沒有符合的測試案例')
      : '沒有符合的測試案例';
    html += `<div class="alert alert-info">${noMsg}</div>`;
  } else {
    html += renderSectionTree(sectionsToRender);
  }
  html += '</div>';

  container.innerHTML = html;

  container.querySelectorAll('[data-indeterminate="true"]').forEach(cb => { cb.indeterminate = true; });

  container.querySelectorAll('.case-checkbox').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const num = e.target.getAttribute('data-case-num');
      handleCaseCheckboxChange(num, e.target.checked);
    });
  });

  container.querySelectorAll('.section-checkbox').forEach(cb => {
    cb.addEventListener('change', (e) => {
      const sid = e.target.getAttribute('data-section-id');
      handleSectionCheckboxChange(sid, e.target.checked);
    });
  });

  container.querySelectorAll('.toggle-section-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const sid = btn.getAttribute('data-section-id');
      toggleSectionExpand(sid);
    });
  });

  updateCaseSelectionSummary();
  updateCurrentSetSelectAllState();
  if (window.i18n && window.i18n.isReady()) window.i18n.retranslate(container);
}

function handleSectionCheckboxChange(sectionId, isChecked) {
  if (sectionId === null || typeof sectionId === 'undefined') return;
  const searchVal = (document.getElementById('caseSearchInput')?.value || '').toLowerCase();
  const matchesSearch = (tc) => {
    const num = (tc.test_case_number || '').toLowerCase();
    const title = (tc.title || '').toLowerCase();
    return num.includes(searchVal) || title.includes(searchVal);
  };

  const collectIds = (sec, acc = new Set()) => {
    acc.add(sec.id);
    (sec.children || []).forEach(child => collectIds(child, acc));
    return acc;
  };

  let sectionIds = new Set();
  if (sectionId === 'unassigned') {
    sectionIds.add('unassigned');
  } else {
    const target = (function find(sections, targetId) {
      for (const sec of sections) {
        if (String(sec.id) === String(targetId)) return sec;
        const child = find(sec.children || [], targetId);
        if (child) return child;
      }
      return null;
    })(caseSelectData.sections || [], sectionId);
    if (!target) return;
    sectionIds = collectIds(target);
  }

  const affectedCases = caseSelectData.testCases.filter(tc => {
    const sid = getCaseSectionId(tc) ?? 'unassigned';
    return sectionIds.has(sid) && matchesSearch(tc);
  });

  affectedCases.forEach(tc => {
    const key = getCaseKey(tc);
    if (isChecked) {
      selectedCaseMap.set(key, tc);
    } else {
      selectedCaseMap.delete(key);
    }
  });

  updateSelectedCount();
  renderCaseSelectList();
}

function handleCaseCheckboxChange(caseNum, isChecked) {
  const targetCase = caseSelectData.testCases.find(c => getCaseKey(c) === caseNum);
  if (isChecked) {
    if (targetCase) selectedCaseMap.set(getCaseKey(targetCase), targetCase);
  } else {
    selectedCaseMap.delete(caseNum);
  }
  updateSelectedCount();
  updateCaseSelectionSummary();
  updateCurrentSetSelectAllState();
}

function toggleSectionExpand(sectionId) {
  const key = `case-section-${sectionId}`;
  const isCollapsed = sessionStorage.getItem(key) === 'collapsed';
  if (isCollapsed) {
    sessionStorage.removeItem(key);
  } else {
    sessionStorage.setItem(key, 'collapsed');
  }
  renderCaseSelectList();
}

function wireCaseCheckHandlers() {
  // handled in renderCaseSelectList via explicit listeners
}

function bindCaseSearchBarEvents() {
  const input = document.getElementById('caseSearchInput');
  if (!input) return;
  input.addEventListener('input', () => {
    renderCaseSelectList();
  });
}

function updateSelectedCount() {
  const count = selectedCaseMap.size;
  const selectedEl = document.getElementById('selectedCount');
  if (selectedEl) selectedEl.textContent = String(count);
}

function updateCaseSelectionSummary() {
  const count = selectedCaseMap.size;
  const summaryEl = document.getElementById('caseSelectionSummary');
  const infoEl = document.getElementById('caseSelectInfo');
  const total = caseSelectData.testCases.length;
  const filtered = caseSelectData.filteredCases.length;
  const searchVal = (document.getElementById('caseSearchInput')?.value || '').trim();
  const setFilterLabel = currentSetIdForCaseSelection ? getTestRunSetDisplayName(currentSetIdForCaseSelection) : '';
  const summaryText = (window.i18n && window.i18n.isReady())
    ? window.i18n.t('testCaseSet.selectedCount', { count }, `已選 ${count} 個測試案例`)
    : `已選 ${count} 個測試案例`;
  if (summaryEl) summaryEl.textContent = summaryText;
  if (infoEl) {
    if (searchVal) {
      infoEl.textContent = `搜尋 "${searchVal}" ，共 ${filtered} 筆${setFilterLabel ? `（${setFilterLabel}）` : ''}`;
    } else {
      if (setFilterLabel) {
        infoEl.textContent = `共 ${filtered} 筆（目前篩選：${setFilterLabel}，全部 ${total} 筆）`;
      } else {
        infoEl.textContent = `共 ${filtered} 筆`;
      }
    }
  }
}

// 預設綁定為建立；開啟 modal 時會依模式改寫處理器
document.getElementById('confirmCreateItemsBtn').addEventListener('click', createItemsFromSelection);

async function createItemsFromSelection() {
  const permissions = window._testRunPermissions || testRunPermissions || {};
  if (modalMode === 'edit' && !permissions.canUpdate) {
    showPermissionDenied();
    return;
  }
  if (modalMode !== 'edit' && !permissions.canCreate) {
    showPermissionDenied();
    return;
  }
  
  if (selectedCaseMap.size === 0) {
    const warn = window.i18n ? window.i18n.t('errors.pleaseSelectTestCases') : '請先選擇至少一筆 Test Case';
    AppUtils.showWarning ? AppUtils.showWarning(warn) : alert(warn);
    return;
  }
  
  if (!currentSelectingConfigId) return;
  
  const items = Array.from(selectedCaseMap.values()).map(c => ({
    test_case_number: c.test_case_number,
    title: c.title,
    priority: c.priority || 'Medium',
    precondition: c.precondition || null,
    steps: c.steps || null,
    expected_result: c.expected_result || null,
    assignee: c.assignee ? { id: c.assignee.id, name: c.assignee.name, en_name: c.assignee.en_name, email: c.assignee.email } : null,
    attachments: (c.attachments || []).map(a => ({ file_token: a.file_token, name: a.name, size: a.size, type: a.type })),
    user_story_map: c.user_story_map || [],
    tcg: c.tcg || [],
    parent_record: c.parent_record || [],
    raw_fields: c.raw_fields || null,
  }));

  try {
    const url = `/api/teams/${currentTeamId}/test-run-configs/${currentSelectingConfigId}/items`;
    const resp = await window.AuthClient.fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }) });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const res = await resp.json();
    createdItemsInSession = true;
    pendingCreate = false;
    caseSelectModalInstance.hide();
    const msg = window.i18n ? window.i18n.t('testRun.itemsCreated', { count: res.created_count || items.length }) : `建立成功 (${res.created_count || items.length} 筆)`;
    AppUtils.showSuccess(msg);
    // 同步統計後刷新管理頁
    try { await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentSelectingConfigId}/sync`); } catch(e) {}
    await loadTestRunConfigs();
  } catch (e) {
    AppUtils.showError((window.i18n ? window.i18n.t('messages.saveFailed') : '建立失敗') + `: ${e.message}`);
  }
}

// 儲存「編輯 Test Case」的差異：新增選入、刪除取消勾選
async function saveEditedItems() {
  const permissions = window._testRunPermissions || testRunPermissions || {};
  if (!permissions.canUpdate) {
    showPermissionDenied();
    return;
  }
  if (!currentSelectingConfigId) return;
  // 計算差異
  const selectedNumbers = new Set(Array.from(selectedCaseMap.keys()));
  const existingNumbers = new Set(Array.from(existingItemIdByCaseNumber.keys()));
  const toAdd = Array.from(selectedNumbers).filter(n => !existingNumbers.has(n));
  const toRemove = Array.from(existingNumbers).filter(n => !selectedNumbers.has(n));

  try {
    // 先新增
    if (toAdd.length > 0) {
      const items = toAdd.map(n => selectedCaseMap.get(n)).map(c => ({
        test_case_number: c.test_case_number,
        title: c.title,
        priority: c.priority || 'Medium',
        precondition: c.precondition || null,
        steps: c.steps || null,
        expected_result: c.expected_result || null,
        assignee: c.assignee ? { id: c.assignee.id, name: c.assignee.name, en_name: c.assignee.en_name, email: c.assignee.email } : null,
        attachments: (c.attachments || []).map(a => ({ file_token: a.file_token, name: a.name, size: a.size, type: a.type })),
        user_story_map: c.user_story_map || [],
        tcg: c.tcg || [],
        parent_record: c.parent_record || [],
        raw_fields: c.raw_fields || null,
      }));
      const url = `/api/teams/${currentTeamId}/test-run-configs/${currentSelectingConfigId}/items`;
      const resp = await window.AuthClient.fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }) });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      await resp.json();
    }
    // 再刪除（包含執行歷程刪除由後端處理）
    for (const n of toRemove) {
      const itemId = existingItemIdByCaseNumber.get(n);
      if (!itemId) continue;
      const url = `/api/teams/${currentTeamId}/test-run-configs/${currentSelectingConfigId}/items/${itemId}`;
      const resp = await window.AuthClient.fetch(url, { method: 'DELETE' });
      if (!resp.ok && resp.status !== 204) {
        // 若已不存在則忽略
        console.warn('Failed to delete item', itemId, 'status', resp.status);
      }
    }
    // 完成
    caseSelectModalInstance.hide();
    const msg = window.i18n ? window.i18n.t('testRun.itemsUpdated') : '已更新 Test Run 的 Test Case';
    AppUtils.showSuccess(msg);
    try { await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${currentSelectingConfigId}/sync`); } catch(e) {}
    await loadTestRunConfigs();
  } catch (e) {
    AppUtils.showError((window.i18n ? window.i18n.t('messages.saveFailed') : '儲存失敗') + `: ${e.message}`);
  }
}

// 卡片上的刪除按鈕（不進入詳情也可刪除）
function deleteTestRun(configId, name) {
  const permissions = window._testRunPermissions || testRunPermissions || {};
  if (!permissions.canDelete) {
    showPermissionDenied();
    return;
  }
  const modal = document.getElementById('deleteConfigModal');
  const msgEl = document.getElementById('deleteConfirmMessage');
  const safeName = escapeHtml(name || '');
  msgEl.textContent = window.i18n ? window.i18n.t('testRun.confirmDelete', { name: safeName }) : `您確定要刪除 Test Run 配置 "${safeName}" 嗎？此操作無法復原。`;
  const inst = bootstrap.Modal.getOrCreateInstance(modal);
  // Rebind confirm handler
  const btnOld = document.getElementById('confirmDeleteConfigBtn');
  const btnNew = btnOld.cloneNode(true);
  btnOld.parentNode.replaceChild(btnNew, btnOld);
  document.getElementById('confirmDeleteConfigBtn').addEventListener('click', async () => {
    try {
      const resp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${configId}`, { method: 'DELETE' });
      if (resp.ok || resp.status === 204) {
        inst.hide();
        const successMsg = window.i18n ? window.i18n.t('testRun.deleteSuccess', { name: safeName }) : `成功刪除 "${safeName}"`;
        AppUtils.showSuccess(successMsg);
        await loadTestRunConfigs();
        await refreshCurrentSetDetail();
      } else {
        let detail = '';
        try {
          const text = await resp.text();
          try { detail = JSON.parse(text).detail || text; } catch { detail = text; }
        } catch { detail = ''; }
        const fallbackMsg = window.i18n ? window.i18n.t('messages.deleteFailed') : '刪除失敗';
        throw new Error(detail || fallbackMsg);
      }
    } catch (error) {
      const errorMsg = window.i18n ? window.i18n.t('messages.deleteFailed') : '刪除失敗';
      AppUtils.showError(`${errorMsg}: ${error.message}`);
    }
  });
  if (window.i18n && window.i18n.isReady()) window.i18n.retranslate(modal);
  inst.show();
}

// ===== TP 標籤管理功能 =====

// 存儲當前的 TP 票號列表
let currentTpTickets = [];

// TP 票號格式驗證函數
