/* ============================================================
   TEST RUN MANAGEMENT - SET MODAL
   ============================================================ */

function getSetSuiteSearchInput() {
    return document.getElementById('testRunSetAutomationSuiteSearch');
}

function getSetSuiteListContainer() {
    return document.getElementById('testRunSetAutomationSuiteList');
}

function getSetSuiteEmptyHint() {
    return document.getElementById('testRunSetAutomationSuiteEmpty');
}

function getSetSuiteSelectedSummary() {
    return document.getElementById('testRunSetAutomationSuiteSelected');
}

function escapeAttr(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
}

function normalizeSuiteOption(option) {
    if (!option || !option.id) {
        return null;
    }
    return {
        id: Number(option.id),
        name: option.name || `Suite #${option.id}`,
        script_count: Number(option.script_count || 0),
        ci_job_name: option.ci_job_name || '',
        ref_branch: option.ref_branch || '',
    };
}

function mergeAutomationSuiteOptions(options) {
    const merged = new Map();
    (Array.isArray(currentSetAutomationSuiteOptions) ? currentSetAutomationSuiteOptions : []).forEach((item) => {
        const normalized = normalizeSuiteOption(item);
        if (normalized) merged.set(normalized.id, normalized);
    });
    (Array.isArray(options) ? options : []).forEach((item) => {
        const normalized = normalizeSuiteOption(item);
        if (normalized) merged.set(normalized.id, normalized);
    });
    currentSetAutomationSuiteOptions = Array.from(merged.values()).sort((a, b) => a.name.localeCompare(b.name));
}

function renderAutomationSuiteSelectedSummary() {
    const container = getSetSuiteSelectedSummary();
    if (!container) return;

    const selected = currentSetAutomationSuiteIds
        .map((id) => currentSetAutomationSuiteOptions.find((option) => option.id === id) || { id, name: `Suite #${id}`, script_count: 0, ci_job_name: '' })
        .filter(Boolean);

    if (!selected.length) {
        container.innerHTML = `<span class="text-muted" data-i18n="testRun.sets.form.automationSuitesSelectedEmpty">尚未選取任何 Automation Suite</span>`;
        return;
    }

    container.innerHTML = selected.map((suite) => `
        <span class="badge rounded-pill text-bg-light border d-inline-flex align-items-center gap-2">
            <span>${escapeHtml(suite.name)}</span>
            <span class="text-muted">${escapeHtml(String(suite.script_count || 0))}</span>
        </span>
    `).join('');
}

function renderAutomationSuitePicker() {
    const listContainer = getSetSuiteListContainer();
    const emptyHint = getSetSuiteEmptyHint();
    if (!listContainer || !emptyHint) return;

    const keyword = (currentSetAutomationSuiteSearch || '').trim().toLowerCase();
    const visibleOptions = currentSetAutomationSuiteOptions.filter((suite) => {
        if (!keyword) return true;
        return [suite.name, suite.ci_job_name, suite.ref_branch]
            .filter(Boolean)
            .some((value) => String(value).toLowerCase().includes(keyword));
    });

    if (!visibleOptions.length) {
        listContainer.innerHTML = '';
        emptyHint.classList.remove('d-none');
    } else {
        emptyHint.classList.add('d-none');
        listContainer.innerHTML = visibleOptions.map((suite) => {
            const checked = currentSetAutomationSuiteIds.includes(suite.id) ? 'checked' : '';
            const scriptCountText = window.i18n?.t('testRun.sets.common.scriptsCount', { count: suite.script_count || 0 })
                || `${suite.script_count || 0} scripts`;
            const meta = [
                scriptCountText,
                suite.ci_job_name ? `${window.i18n?.t('testRun.sets.common.ciJobLabel') || 'CI'}: ${suite.ci_job_name}` : '',
                suite.ref_branch ? `${window.i18n?.t('testRun.sets.common.branchLabel') || 'Branch'}: ${suite.ref_branch}` : '',
            ].filter(Boolean).join(' · ');
            return `
                <label class="list-group-item d-flex align-items-start gap-3">
                    <input class="form-check-input mt-1" type="checkbox" value="${suite.id}" data-suite-picker-checkbox ${checked}>
                    <div class="flex-grow-1">
                        <div class="fw-semibold">${escapeHtml(suite.name)}</div>
                        <div class="small text-muted">${escapeHtml(meta)}</div>
                    </div>
                </label>
            `;
        }).join('');
    }

    renderAutomationSuiteSelectedSummary();

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(listContainer.parentElement || listContainer);
    }
}

async function loadAutomationSuiteOptions() {
    if (!currentTeamId) return;

    const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/automation-script-groups?limit=200`);
    if (!response.ok) {
        const payload = await response.json().catch(() => ({ detail: null }));
        throw new Error(payload?.detail || (window.i18n?.t('testRun.sets.form.automationSuitesLoadFailed') || '載入 Automation Suites 失敗'));
    }

    const payload = await response.json();
    mergeAutomationSuiteOptions(payload?.items || []);
}

function bindAutomationSuitePickerEvents() {
    const searchInput = getSetSuiteSearchInput();
    const listContainer = getSetSuiteListContainer();

    if (searchInput && !searchInput.dataset.bound) {
        searchInput.dataset.bound = 'true';
        searchInput.addEventListener('input', (event) => {
            currentSetAutomationSuiteSearch = event.target.value || '';
            renderAutomationSuitePicker();
        });
    }

    if (listContainer && !listContainer.dataset.bound) {
        listContainer.dataset.bound = 'true';
        listContainer.addEventListener('change', (event) => {
            const checkbox = event.target.closest('[data-suite-picker-checkbox]');
            if (!checkbox) return;
            const suiteId = Number(checkbox.value);
            if (!suiteId) return;
            if (checkbox.checked) {
                if (!currentSetAutomationSuiteIds.includes(suiteId)) {
                    currentSetAutomationSuiteIds = [...currentSetAutomationSuiteIds, suiteId];
                }
            } else {
                currentSetAutomationSuiteIds = currentSetAutomationSuiteIds.filter((id) => id !== suiteId);
            }
            renderAutomationSuitePicker();
        });
    }
}

function resetAutomationSuitePicker() {
    currentSetAutomationSuiteIds = [];
    currentSetAutomationSuiteOptions = [];
    currentSetAutomationSuiteSearch = '';
    const searchInput = getSetSuiteSearchInput();
    if (searchInput) searchInput.value = '';
    renderAutomationSuitePicker();
}

function openTestRunSetFormModal(setId = null) {
    const permissions = window._testRunPermissions || testRunPermissions || {};
    if (setId) {
        if (!permissions.canUpdate) {
            showPermissionDenied();
            return;
        }
    } else if (!permissions.canCreate) {
        showPermissionDenied();
        return;
    }

    const modalElement = document.getElementById('testRunSetFormModal');
    if (!testRunSetFormModalInstance) {
        testRunSetFormModalInstance = new bootstrap.Modal(modalElement);
        modalElement.addEventListener('hidden.bs.modal', async () => {
            const form = document.getElementById('testRunSetForm');
            if (form) form.reset();
            const idInput = document.getElementById('testRunSetId');
            if (idInput) idInput.value = '';
            clearAllSetTpTickets();
            clearSetTpInputError();
            resetAutomationSuitePicker();

            // 檢查是否為儲存成功後關閉
            if (window._setFormSavedSuccessfully) {
                const savedSetId = window._savedSetId;
                const shouldReopen = window._shouldReopenDetailAfterSave;
                const newSetId = window._newSetId;

                // 清除標記
                window._setFormSavedSuccessfully = false;
                window._savedSetId = null;
                window._shouldReopenDetailAfterSave = false;
                window._newSetId = null;
                reopenSetDetailAfterForm = false;

                // 根據情況重新打開 Detail Modal
                if (newSetId) {
                    // 新建：打開新建的 Set Detail
                    await openTestRunSetDetail(newSetId);
                } else if (savedSetId && shouldReopen) {
                    // 編輯：重新打開原本的 Set Detail
                    await openTestRunSetDetail(savedSetId);
                }
            } else {
                // 取消或其他情況：檢查是否需要重新打開
                if (reopenSetDetailAfterForm && currentSetContext?.id) {
                    reopenSetDetailAfterForm = false;
                    openTestRunSetDetail(currentSetContext.id);
                } else {
                    reopenSetDetailAfterForm = false;
                }
            }
        });
    }

    const form = document.getElementById('testRunSetForm');
    form.reset();
    const idInput = document.getElementById('testRunSetId');
    idInput.value = setId ? String(setId) : '';

    const titleEl = document.getElementById('testRunSetFormTitle');
    const nameInput = document.getElementById('testRunSetName');
    const descInput = document.getElementById('testRunSetDescription');

    clearAllSetTpTickets();
    initSetTpTicketInput();
    bindAutomationSuitePickerEvents();

    const detailModalEl = document.getElementById('testRunSetDetailModal');
    const detailInstanceVisible = detailModalEl && detailModalEl.classList.contains('show');
    if (detailInstanceVisible && testRunSetDetailModalInstance) {
        reopenSetDetailAfterForm = true;
        testRunSetDetailModalInstance.hide();
    } else {
        reopenSetDetailAfterForm = false;
    }

    if (setId) {
        const setData = (testRunSets || []).find(s => s.id === setId) || currentSetContext || null;
        titleEl.setAttribute('data-i18n', 'testRun.sets.form.editTitle');
        titleEl.textContent = window.i18n?.t('testRun.sets.form.editTitle') || '編輯 Test Run Set';
        nameInput.value = setData ? (setData.name || '') : '';
        descInput.value = setData ? (setData.description || '') : '';
        if (setData && Array.isArray(setData.related_tp_tickets)) {
            setSetTpTickets(setData.related_tp_tickets);
        }
        currentSetAutomationSuiteIds = setData
            ? (Array.isArray(setData.automation_suite_ids) ? [...setData.automation_suite_ids] : [])
            : [];
        mergeAutomationSuiteOptions(setData?.automation_suites || []);
    } else {
        titleEl.setAttribute('data-i18n', 'testRun.sets.form.createTitle');
        titleEl.textContent = window.i18n?.t('testRun.sets.form.createTitle') || '新增 Test Run Set';
        currentSetAutomationSuiteIds = [];
    }

    currentSetAutomationSuiteSearch = '';
    const searchInput = getSetSuiteSearchInput();
    if (searchInput) searchInput.value = '';
    renderAutomationSuitePicker();

    loadAutomationSuiteOptions()
        .then(() => renderAutomationSuitePicker())
        .catch((error) => {
            console.error('Load automation suites failed:', error);
            AppUtils.showError(error.message);
        });

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(modalElement);
    }

    testRunSetFormModalInstance.show();
}

async function handleSaveTestRunSet() {
    const form = document.getElementById('testRunSetForm');
    if (!form) return;

    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }

    const setId = form.querySelector('#testRunSetId').value || null;
    const name = form.querySelector('#testRunSetName').value.trim();
    const description = form.querySelector('#testRunSetDescription').value.trim();

    const permissions = window._testRunPermissions || testRunPermissions || {};
    if (setId && !permissions.canUpdate) {
        showPermissionDenied();
        return;
    }
    if (!setId && !permissions.canCreate) {
        showPermissionDenied();
        return;
    }

    const payload = { name };
    if (description) {
        payload.description = description;
    }
    payload.related_tp_tickets = [...currentSetTpTickets];
    // automation_suite_ids: preserve existing value on update; default to [] on create.
    // Full suite-picker UI is a follow-up; for now, automation suites can be
    // managed via the API directly. This guards against accidentally nulling
    // the field on every save.
    payload.automation_suite_ids = currentSetAutomationSuiteIds.slice();

    const endpoint = setId
        ? `/api/teams/${currentTeamId}/test-run-sets/${setId}`
        : `/api/teams/${currentTeamId}/test-run-sets/`;
    const method = setId ? 'PUT' : 'POST';

    const saveBtn = document.getElementById('saveTestRunSetBtn');
    try {
        saveBtn.disabled = true;
        const response = await window.AuthClient.fetch(endpoint, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorPayload = await response.json().catch(() => ({ detail: null }));
            throw new Error(errorPayload?.detail || (window.i18n?.t('messages.saveFailed') || '儲存失敗'));
        }

        const data = await response.json();
        const successMsg = setId
            ? (window.i18n?.t('testRun.sets.form.updateSuccess') || 'Test Run Set 已更新')
            : (window.i18n?.t('testRun.sets.form.createSuccess') || 'Test Run Set 建立成功');
        AppUtils.showSuccess(successMsg);

        // 標記為成功儲存，之後 hidden 事件中會手動處理重新打開
        const shouldReopenDetail = reopenSetDetailAfterForm && setId;
        window._setFormSavedSuccessfully = true;
        window._savedSetId = setId;
        window._shouldReopenDetailAfterSave = shouldReopenDetail;
        window._newSetId = !setId ? data?.id : null;

        testRunSetFormModalInstance?.hide();
        await loadTestRunConfigs();
    } catch (error) {
        console.error('Save Test Run Set failed:', error);
        AppUtils.showError(error.message);
    } finally {
        saveBtn.disabled = false;
    }
}

async function openTestRunSetDetail(setId) {
    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${setId}`);
        if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || '無法載入 Test Run Set 詳細資訊');
        }
        currentSetContext = await response.json();

        const modalElement = document.getElementById('testRunSetDetailModal');
        if (!testRunSetDetailModalInstance) {
            testRunSetDetailModalInstance = new bootstrap.Modal(modalElement);
            modalElement.addEventListener('hidden.bs.modal', () => {
                if (!preserveSetContextOnHide) {
                    currentSetContext = null;
                }
                preserveSetContextOnHide = false;
                if (window.TestRunSetRunHistory && window.TestRunSetRunHistory.clear) {
                    window.TestRunSetRunHistory.clear();
                }
            });
        }

        renderTestRunSetDetail(currentSetContext, currentStatusFilter);

        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(modalElement);
        }

        testRunSetDetailModalInstance.show();
    } catch (error) {
        console.error('Open Test Run Set detail failed:', error);
        AppUtils.showError(error.message);
    }
}

function renderTestRunSetDetail(setData, filterStatus = 'all') {
    if (!setData) return;

    const titleEl = document.getElementById('testRunSetDetailTitle');
    const descEl = document.getElementById('testRunSetDetailDescription');
    const statusEl = document.getElementById('testRunSetDetailStatus');
    const metaEl = document.getElementById('testRunSetDetailMeta');
    const headerActions = document.getElementById('testRunSetHeaderActions');
    const runsContainer = document.getElementById('testRunSetRunsContainer');
    const perms = window._testRunPermissions || testRunPermissions || {};

    titleEl.textContent = setData.name || '';

    if (setData.description) {
        descEl.innerHTML = escapeHtml(setData.description).replace(/\n/g, '<br>');
    } else {
        descEl.innerHTML = '<span class="text-muted" data-i18n="testRun.sets.detail.noDescription">尚未填寫描述</span>';
    }

    statusEl.innerHTML = getSetStatusBadge(setData.status);

    const metrics = summarizeSetMetrics(setData.test_runs || []);
    const suiteCount = Array.isArray(setData.automation_suites) ? setData.automation_suites.length : 0;
    // 總案例 = 手動 Test Run 案例數 + Automation Suites 涵蓋的不重複案例數
    const automationCoveredCount = Number(setData.automation_covered_case_count || 0);
    let totalCasesText = String(metrics.totalCases + automationCoveredCount);
    if (automationCoveredCount > 0) {
        totalCasesText += window.i18n?.t('testRun.sets.detail.totalCasesBreakdown', {
            manual: metrics.totalCases,
            automation: automationCoveredCount,
        }) || `（手動 ${metrics.totalCases} · 自動化涵蓋 ${automationCoveredCount}）`;
    }
    const metaText = `${window.i18n?.t('testRun.sets.detail.totalRuns') || 'Test Run 數'}: ${setData.test_runs?.length || 0} · ${window.i18n?.t('testRun.sets.detail.totalSuites') || 'Automation Suites'}: ${suiteCount} · ${window.i18n?.t('testRun.sets.detail.totalCases') || '總案例'}: ${totalCasesText}`;
    metaEl.textContent = metaText;
    renderSetDetailTpTags(setData.related_tp_tickets || []);

    // Automation Suites + Run as Automation trigger (move-automation-execution-to-test-run-set)
    window._currentTestRunSetId = setData.id;

    // Run history for this set (move-run-history-to-test-run-set)
    if (window.TestRunSetRunHistory && window.TestRunSetRunHistory.loadForSet) {
      window.TestRunSetRunHistory.loadForSet(setData.id, currentTeamId);
    }

    const editBtn = document.getElementById('setDetailEditBtn');
    const archiveBtn = document.getElementById('setDetailArchiveBtn');
    const reportBtn = document.getElementById('setDetailReportBtn');
    const deleteBtn = document.getElementById('setDetailDeleteBtn');
    const moreActions = document.getElementById('setDetailMoreActions');
    const deleteDivider = document.getElementById('setDetailDeleteDivider');

    setElementVisibility('setDetailEditBtn', perms.canUpdate);
    setElementVisibility('setDetailArchiveBtn', perms.canUpdate);
    setElementVisibility('setDetailReportBtn', true);
    setElementVisibility('setDetailDeleteBtn', perms.canDelete);
    if (moreActions) {
        moreActions.classList.toggle('d-none', !perms.canUpdate && !perms.canDelete);
    }
    if (deleteDivider) {
        deleteDivider.classList.toggle('d-none', !(perms.canUpdate && perms.canDelete));
    }

    if (editBtn) {
        editBtn.disabled = !perms.canUpdate;
        editBtn.onclick = () => openTestRunSetFormModal(setData.id);
    }

    if (archiveBtn) {
        archiveBtn.disabled = !perms.canUpdate;
        if (setData.status === 'archived') {
            archiveBtn.innerHTML = '<i class="fas fa-undo me-2"></i><span data-i18n="testRun.sets.detail.unarchive">取消 Archive</span>';
            archiveBtn.onclick = () => toggleArchiveTestRunSet(setData, 'active');
        } else {
            archiveBtn.innerHTML = '<i class="fas fa-archive me-2"></i><span data-i18n="testRun.sets.detail.archive">Archive</span>';
            archiveBtn.onclick = () => toggleArchiveTestRunSet(setData, 'archived');
        }
    }

    if (reportBtn) {
        reportBtn.disabled = false;
        reportBtn.onclick = () => openTestRunSetReport(setData);
    }

    if (deleteBtn) {
        deleteBtn.disabled = !perms.canDelete;
        const newDeleteBtn = deleteBtn.cloneNode(true);
        deleteBtn.parentNode.replaceChild(newDeleteBtn, deleteBtn);

        newDeleteBtn.addEventListener('click', () => {
            const deleteModalEl = document.getElementById('deleteTestRunSetModal');
            if (deleteModalEl) {
                const deleteModal = new bootstrap.Modal(deleteModalEl);
                const confirmBtn = document.getElementById('confirmDeleteTestRunSetBtn');
                
                const handleConfirm = () => {
                    deleteTestRunSet(setData.id);
                    deleteModal.hide();
                };
                
                const newConfirmBtn = confirmBtn.cloneNode(true);
                confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
                newConfirmBtn.addEventListener('click', handleConfirm);
                
                deleteModal.show();
            } else if (confirm(window.i18n ? window.i18n.t('testRun.sets.deleteConfirm') : '確定要刪除此 Test Run Set 嗎？此操作將刪除其下所有 Test Run，且無法復原。')) {
                deleteTestRunSet(setData.id);
            }
        });
    }

    const allRuns = Array.isArray(setData.test_runs) ? setData.test_runs : [];
    const runs = filterTestRunsByStatus(allRuns, filterStatus);
    const suites = Array.isArray(setData.automation_suites) ? setData.automation_suites : [];

    runsContainer.innerHTML = [
        buildSetDetailItemSection({
            titleKey: 'testRun.sets.detail.manualTestRuns',
            titleFallback: 'Manual Test Runs',
            count: runs.length,
            actionsHtml: buildManualSectionActions(setData, perms),
            itemsHtml: runs.map(run => buildSetRunDetailRow(run, setData)).join(''),
            emptyKey: filterStatus === 'all'
                ? 'testRun.sets.detail.manualTestRunsEmpty'
                : 'testRun.sets.detail.noFilterMatches',
            emptyFallback: filterStatus === 'all'
                ? '尚未加入任何 Manual Test Run'
                : '目前沒有符合篩選條件的 Test Run',
        }),
        buildSetDetailItemSection({
            titleKey: 'testRun.sets.detail.automationSuites',
            titleFallback: 'Automation Suites',
            count: suites.length,
            actionsHtml: buildAutomationSectionActions(setData, perms, suites.length),
            itemsHtml: suites.map(suite => buildAutomationSuiteDetailRow(suite, setData)).join(''),
            emptyKey: 'testRun.sets.detail.automationSuitesEmpty',
            emptyFallback: '尚未關聯任何 Automation Suite',
        }),
    ].join('');

    const createBtn = document.getElementById('setDetailCreateConfigBtn');
    const addExistingRunBtn = document.getElementById('setDetailAddExistingRunBtn');
    const addAutomationSuiteBtn = document.getElementById('setDetailAddAutomationSuiteBtn');
    const runAutomationBtn = document.getElementById('setDetailRunAutomationBtn');

    if (createBtn) {
        createBtn.disabled = setData.status === 'archived' || !perms.canCreate;
        createBtn.onclick = () => openConfigFormModal(null, { setId: setData.id });
    }

    if (addExistingRunBtn) {
        addExistingRunBtn.disabled = setData.status === 'archived' || !perms.canUpdate;
        addExistingRunBtn.onclick = () => openAddExistingRunToSetModal(setData);
    }

    if (addAutomationSuiteBtn) {
        addAutomationSuiteBtn.disabled = setData.status === 'archived' || !perms.canUpdate;
        addAutomationSuiteBtn.onclick = () => openAddExistingToSetModal(setData);
    }

    if (runAutomationBtn && window.TestRunSetAutomation?.runAllAutomationSuites) {
        runAutomationBtn.onclick = async (event) => {
            event.preventDefault();
            event.stopPropagation();
            await window.TestRunSetAutomation.runAllAutomationSuites(runAutomationBtn);
        };
    }

    if (window.TestRunSetAutomation && window.TestRunSetAutomation.setAutomationSuites) {
        const automationSuiteIds = Array.isArray(setData.automation_suite_ids)
            ? setData.automation_suite_ids
            : suites.map((suite) => Number(suite.id)).filter(Boolean);
        window.TestRunSetAutomation.setAutomationSuites(
            automationSuiteIds,
            suites
        );
    }

    // 「⋯」選單在可捲動的 modal-body 內會被 overflow 裁切，改用 fixed 定位
    if (window.bootstrap?.Dropdown) {
        runsContainer.querySelectorAll('[data-bs-toggle="dropdown"]').forEach((toggle) => {
            bootstrap.Dropdown.getOrCreateInstance(toggle, {
                popperConfig(defaultConfig) {
                    return { ...defaultConfig, strategy: 'fixed' };
                },
            });
        });
    }

    runsContainer.querySelectorAll('[data-remove-suite-id]').forEach((button) => {
        button.addEventListener('click', async (event) => {
            event.preventDefault();
            event.stopPropagation();
            const suiteId = Number(button.dataset.removeSuiteId);
            const suiteName = button.dataset.removeSuiteName || `Suite #${suiteId}`;
            if (suiteId) {
                await removeAutomationSuiteFromSet(setData, suiteId, suiteName);
            }
        });
    });
    runsContainer.querySelectorAll('[data-run-suite-id]').forEach((button) => {
        button.addEventListener('click', async (event) => {
            event.preventDefault();
            event.stopPropagation();
            const suiteId = Number(button.dataset.runSuiteId);
            if (suiteId && window.TestRunSetAutomation?.runAutomationSuite) {
                await window.TestRunSetAutomation.runAutomationSuite(suiteId, button);
            }
        });
    });

    if (window.i18n && window.i18n.isReady()) {
        if (headerActions) window.i18n.retranslate(headerActions);
        window.i18n.retranslate(runsContainer);
    }
}

function buildSetDetailItemSection({
    titleKey,
    titleFallback,
    count,
    actionsHtml = '',
    itemsHtml,
    emptyKey,
    emptyFallback,
}) {
    const hasItems = Boolean(itemsHtml);
    return `
        <section class="test-run-set-detail-section">
            <div class="test-run-set-section-heading">
                <div class="test-run-set-section-title">
                    <h6 class="mb-0" data-i18n="${titleKey}">${escapeHtml(titleFallback)}</h6>
                    <span class="badge bg-secondary">${count}</span>
                </div>
                ${actionsHtml ? `<div class="test-run-set-section-actions">${actionsHtml}</div>` : ''}
            </div>
            ${hasItems ? itemsHtml : `
                <div class="text-muted small py-1" data-i18n="${emptyKey}">
                    ${escapeHtml(emptyFallback)}
                </div>
            `}
        </section>
    `;
}

function buildManualSectionActions(setData, perms) {
    const disabledAttr = setData.status === 'archived' ? ' disabled' : '';
    const addExistingButton = perms.canUpdate
        ? `
            <button type="button" class="btn btn-outline-primary btn-sm" id="setDetailAddExistingRunBtn"${disabledAttr}>
                <i class="fas fa-link me-1"></i><span data-i18n="testRun.sets.detail.addExisting">加入既有 Test Run</span>
            </button>
        `
        : '';
    const createButton = perms.canCreate
        ? `
            <button type="button" class="btn btn-primary btn-sm" id="setDetailCreateConfigBtn"${disabledAttr}>
                <i class="fas fa-plus me-1"></i><span data-i18n="testRun.sets.detail.createTestRun">新增 Test Run</span>
            </button>
        `
        : '';
    return [addExistingButton, createButton].filter(Boolean).join('');
}

function buildAutomationSectionActions(setData, perms, suiteCount) {
    const disabledAttr = setData.status === 'archived' ? ' disabled' : '';
    const addButton = perms.canUpdate
        ? `
            <button type="button" class="btn btn-outline-primary btn-sm" id="setDetailAddAutomationSuiteBtn"${disabledAttr}>
                <i class="fas fa-link me-1"></i><span data-i18n="testRun.sets.detail.addAutomationSuiteCompact">加入 Suite</span>
            </button>
        `
        : '';
    const runDisabledAttr = suiteCount > 0 ? '' : ' disabled';
    const runButton = `
        <button type="button" class="btn btn-success btn-sm" id="setDetailRunAutomationBtn"${runDisabledAttr}
                title="${escapeAttr(window.i18n?.t('testRun.sets.detail.runAutomationHint') || '依序觸發每個 Automation Suite 內所有 scripts（透過 CIProvider）')}">
            <i class="fas fa-play me-1"></i><span data-i18n="testRun.sets.detail.runAutomationCompact">執行 Suites</span>
        </button>
    `;
    return [addButton, runButton].filter(Boolean).join('');
}

function buildDetailCardActions(buttons) {
    const renderedButtons = buttons.filter(Boolean);
    if (!renderedButtons.length) return '';
    return `<div class="testRunDetailRunActions">${renderedButtons.join('')}</div>`;
}

async function removeAutomationSuiteFromSet(setData, suiteId, suiteName) {
    const nextSuiteIds = (Array.isArray(setData.automation_suite_ids) ? setData.automation_suite_ids : [])
        .filter((id) => id !== suiteId);
    const confirmed = await AppUtils.showConfirm(
        window.i18n?.t('testRun.sets.removeAutomationSuiteConfirm', { name: suiteName })
        || `確定要移除「${suiteName}」Automation Suite？`
    );
    if (!confirmed) return;

    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${setData.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ automation_suite_ids: nextSuiteIds })
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || (window.i18n?.t('testRun.sets.removeAutomationSuiteFailed') || '移除 Automation Suite 失敗'));
        }

        AppUtils.showSuccess(window.i18n?.t('testRun.sets.removeAutomationSuiteSuccess') || 'Automation Suite 已移除');
        await loadTestRunConfigs();
        await refreshCurrentSetDetail();
    } catch (error) {
        console.error('Remove automation suite from set failed:', error);
        AppUtils.showError(error.message);
    }
}

function buildSetRunDetailRow(run, setData) {
    const statusClass = getStatusClass(run.status);
    const statusText = getStatusText(run.status);
    const metricsText = `${run.executed_cases || 0}/${run.total_test_cases || 0}`;
    const createdText = run.created_at ? AppUtils.formatDate(run.created_at, 'datetime') : '';
    const otherSets = (testRunSets || []).filter(s => s.id !== setData.id);
    const perms = window._testRunPermissions || testRunPermissions || {};

    const lockedForConfigEdit = run.status === 'archived';
    const lockedForCasesEdit = run.status === 'completed' || run.status === 'archived';
    const lockedConfigMessage = (window.i18n && window.i18n.isReady())
        ? window.i18n.t('testRun.cannotEditArchived')
        : 'Cannot edit archived Test Run';
    const lockedCasesMessage = (window.i18n && window.i18n.isReady())
        ? window.i18n.t(run.status === 'archived' ? 'testRun.cannotEditArchived' : 'testRun.cannotEditCompleted')
        : (run.status === 'archived' ? 'Cannot edit archived Test Run' : 'Cannot edit Test Cases in completed Test Run');
    const lockedConfigAttrs = lockedForConfigEdit
        ? ` disabled title="${escapeHtml(lockedConfigMessage)}"`
        : '';
    const lockedCasesAttrs = lockedForCasesEdit
        ? ` disabled title="${escapeHtml(lockedCasesMessage)}"`
        : '';

    // 收斂列上的操作：只留「進入」，其餘進「⋯」選單
    const menuItems = [];

    if (perms.canUpdate) {
        menuItems.push(`
            <li><button type="button" class="dropdown-item${lockedForConfigEdit ? ' disabled' : ''}"${lockedConfigAttrs}
                    onclick="event.stopPropagation(); editBasicSettings(${run.id})">
                <i class="fas fa-edit me-2"></i><span data-i18n="testRun.editBasicSettings">編輯基本設定</span>
            </button></li>
        `);
        menuItems.push(`
            <li><button type="button" class="dropdown-item${lockedForCasesEdit ? ' disabled' : ''}"${lockedCasesAttrs}
                    onclick="event.stopPropagation(); editTestCases(${run.id})">
                <i class="fas fa-list me-2"></i><span data-i18n="testRun.editTestCases">編輯 Test Case</span>
            </button></li>
        `);
    }

    if (perms.canChangeStatus) {
        const statusItems = generateStatusDropdownItems(run);
        if (statusItems) {
            menuItems.push('<li><hr class="dropdown-divider"></li>');
            menuItems.push('<li><h6 class="dropdown-header" data-i18n="testRun.changeStatus">變更狀態</h6></li>');
            menuItems.push(statusItems);
        }
    }

    if (perms.canUpdate) {
        if (otherSets.length > 0) {
            menuItems.push('<li><hr class="dropdown-divider"></li>');
            menuItems.push('<li><h6 class="dropdown-header" data-i18n="testRun.sets.detail.actionMove">搬移</h6></li>');
            otherSets.forEach((s) => {
                menuItems.push(`
                    <li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); moveTestRunToSet(${run.id}, ${s.id});">
                        <i class="fas fa-random me-2"></i>${escapeHtml(s.name)}
                    </button></li>
                `);
            });
        }
        menuItems.push(`
            <li><button type="button" class="dropdown-item" onclick="event.stopPropagation(); removeTestRunFromSet(${run.id}, '${escapeHtml(run.name)}')">
                <i class="fas fa-unlink me-2"></i><span data-i18n="testRun.sets.detail.actionRemove">移出</span>
            </button></li>
        `);
    }

    if (perms.canDelete) {
        menuItems.push('<li><hr class="dropdown-divider"></li>');
        menuItems.push(`
            <li><button type="button" class="dropdown-item text-danger" onclick="event.stopPropagation(); deleteTestRun(${run.id}, '${escapeHtml(run.name)}')">
                <i class="fas fa-trash me-2"></i><span data-i18n="common.delete">刪除</span>
            </button></li>
        `);
    }

    const enterButton = `
        <button class="btn btn-sm btn-outline-primary" onclick="event.stopPropagation(); enterTestRun(${run.id})">
            <i class="fas fa-arrow-right me-1"></i><span data-i18n="testRun.sets.detail.actionOpen">進入</span>
        </button>
    `;
    const kebabMenu = menuItems.length ? `
        <div class="dropdown" onclick="event.stopPropagation()">
            <button type="button" class="btn btn-sm test-run-kebab-btn" data-bs-toggle="dropdown" aria-expanded="false" aria-label="More actions">
                <i class="fas fa-ellipsis-v"></i>
            </button>
            <ul class="dropdown-menu dropdown-menu-end test-run-row-menu">${menuItems.join('')}</ul>
        </div>
    ` : '';

    const actionsHtml = buildDetailCardActions([enterButton, kebabMenu]);

    return `
        <div class="card test-run-set-detail-card">
            <div class="card-body">
                <div class="test-run-detail-item-row">
                    <div class="test-run-detail-item-content">
                        <h6 class="test-run-detail-item-title text-primary" title="${escapeAttr(run.name)}">${escapeHtml(run.name)}</h6>
                        <div class="test-run-detail-item-meta">
                            <span class="status-badge ${statusClass}">${statusText}</span>
                            <span class="text-muted"><i class="fas fa-list-ul me-1"></i>${metricsText}</span>
                            ${createdText ? `<span class="text-muted"><i class="fas fa-clock me-1\"></i>${createdText}</span>` : ''}
                        </div>
                    </div>
                    ${actionsHtml || ''}
                </div>
            </div>
        </div>
    `;
}

function buildAutomationSuiteDetailRow(suite, setData) {
    const perms = window._testRunPermissions || testRunPermissions || {};
    const isArchived = setData.status === 'archived';
    const scriptCountText = window.i18n?.t('testRun.sets.common.scriptsCount', { count: suite.script_count || 0 })
        || `${suite.script_count || 0} scripts`;
    const typeLabel = window.i18n?.t('testRun.sets.detail.automationSuiteType') || 'Test Automation Suite';
    const ciLabel = suite.ci_job_name
        ? `<span class="text-muted"><i class="fas fa-cogs me-1"></i>${escapeHtml(suite.ci_job_name)}</span>`
        : '';

    const runButton = `
        <button class="btn btn-sm btn-outline-success flex-shrink-0"
                data-run-suite-id="${suite.id}" data-run-suite-name="${escapeAttr(suite.name)}">
            <i class="fas fa-play me-1"></i><span data-i18n="testRun.sets.detail.runAutomationSuite">執行</span>
        </button>
    `;
    const kebabMenu = perms.canUpdate
        ? `
            <div class="dropdown" onclick="event.stopPropagation()">
                <button type="button" class="btn btn-sm test-run-kebab-btn" data-bs-toggle="dropdown" aria-expanded="false" aria-label="More actions">
                    <i class="fas fa-ellipsis-v"></i>
                </button>
                <ul class="dropdown-menu dropdown-menu-end">
                    <li><button type="button" class="dropdown-item text-danger${isArchived ? ' disabled' : ''}" ${isArchived ? 'disabled' : ''}
                            data-remove-suite-id="${suite.id}" data-remove-suite-name="${escapeAttr(suite.name)}">
                        <i class="fas fa-unlink me-2"></i><span data-i18n="testRun.sets.detail.actionRemoveSuite">移除</span>
                    </button></li>
                </ul>
            </div>
        `
        : '';
    const actionButtons = buildDetailCardActions([runButton, kebabMenu]);

    return `
        <div class="card test-run-set-detail-card">
            <div class="card-body">
                <div class="test-run-detail-item-row">
                    <div class="test-run-detail-item-content">
                        <h6 class="test-run-detail-item-title text-primary" title="${escapeAttr(suite.name)}">${escapeHtml(suite.name)}</h6>
                        <div class="test-run-detail-item-meta">
                            <span class="badge bg-info-subtle text-info-emphasis border border-info-subtle">${escapeHtml(typeLabel)}</span>
                            <span class="text-muted"><i class="fas fa-code-branch me-1"></i>${escapeHtml(scriptCountText)}</span>
                            ${ciLabel}
                        </div>
                    </div>
                    ${actionButtons || ''}
                </div>
            </div>
        </div>
    `;
}

// Suite-only: existing Test Runs join a set via create-in-set or the per-run
// "搬移至其他 Set" dropdown, so this modal only offers automation suites.
function openAddExistingToSetModal(setData) {
    if (!addExistingToSetModalInstance) {
        const modalEl = document.getElementById('addExistingToSetModal');
        addExistingToSetModalInstance = new bootstrap.Modal(modalEl);
    }

    const modalEl = document.getElementById('addExistingToSetModal');
    const listContainer = document.getElementById('addExistingToSetList');
    const emptyHint = document.getElementById('addExistingToSetEmpty');
    const confirmBtn = document.getElementById('confirmAddExistingToSetBtn');
    listContainer.innerHTML = '';
    modalEl.dataset.targetSetId = String(setData.id);

    const renderSuiteList = async () => {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/automation-script-groups?limit=200`);
        if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || '載入 Automation Suites 失敗');
        }
        const payload = await response.json();
        const suites = Array.isArray(payload?.items) ? payload.items : [];
        const selectedSuiteIds = Array.isArray(setData.automation_suite_ids) ? setData.automation_suite_ids : [];
        const availableSuites = suites.filter((suite) => !selectedSuiteIds.includes(suite.id));

        if (!availableSuites.length) {
            emptyHint.style.display = 'block';
            confirmBtn.disabled = true;
            return;
        }

        emptyHint.style.display = 'none';
        confirmBtn.disabled = false;
        listContainer.innerHTML = availableSuites.map((suite) => `
            <label class="list-group-item d-flex align-items-center justify-content-between">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" value="${suite.id}" id="add-existing-suite-${suite.id}">
                    <label class="form-check-label" for="add-existing-suite-${suite.id}">
                        <strong>${escapeHtml(suite.name)}</strong>
                        <div class="small text-muted">${escapeHtml(window.i18n?.t('testRun.sets.detail.automationSuiteType') || 'Test Automation Suite')} · ${escapeHtml(String(suite.script_count || 0))} scripts</div>
                    </label>
                </div>
            </label>
        `).join('');
    };

    renderSuiteList().catch((error) => {
        console.error('Open add-suite modal failed:', error);
        AppUtils.showError(error.message);
    });

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(modalEl);
    }

    addExistingToSetModalInstance.show();
}

async function confirmAddExistingToSet() {
    const modalEl = document.getElementById('addExistingToSetModal');
    const targetSetId = parseInt(modalEl.dataset.targetSetId || '0', 10);
    if (!targetSetId) {
        addExistingToSetModalInstance.hide();
        return;
    }

    const selected = Array.from(document.querySelectorAll('#addExistingToSetList input[type="checkbox"]:checked'))
        .map(input => parseInt(input.value, 10));

    if (!selected.length) {
        AppUtils.showWarning(window.i18n?.t('testRun.sets.addExisting.selectWarningSuites') || '請至少選擇一個 Test Automation Suite');
        return;
    }

    try {
        const setResponse = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${targetSetId}`);
        if (!setResponse.ok) {
            const payload = await setResponse.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || '載入 Test Run Set 失敗');
        }
        const setData = await setResponse.json();
        const existingSuiteIds = Array.isArray(setData.automation_suite_ids) ? setData.automation_suite_ids : [];
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${targetSetId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ automation_suite_ids: [...existingSuiteIds, ...selected] })
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || '加入成員失敗');
        }

        addExistingToSetModalInstance.hide();
        AppUtils.showSuccess(window.i18n?.t('testRun.sets.addExisting.successSuites') || '已將選定的 Automation Suite 加入 Set');
        await loadTestRunConfigs();
        await refreshCurrentSetDetail();
    } catch (error) {
        console.error('Add automation suite failed:', error);
        AppUtils.showError(error.message);
    }
}

// Add already-existing (unassigned) Test Runs into a set. Mirrors the suite
// picker above but lists ungrouped manual Test Runs and posts to /members.
function openAddExistingRunToSetModal(setData) {
    if (!addExistingRunToSetModalInstance) {
        const modalEl = document.getElementById('addExistingRunToSetModal');
        addExistingRunToSetModalInstance = new bootstrap.Modal(modalEl);
    }

    const modalEl = document.getElementById('addExistingRunToSetModal');
    const listContainer = document.getElementById('addExistingRunToSetList');
    const emptyHint = document.getElementById('addExistingRunToSetEmpty');
    const confirmBtn = document.getElementById('confirmAddExistingRunToSetBtn');
    listContainer.innerHTML = '';
    modalEl.dataset.targetSetId = String(setData.id);

    const availableRuns = Array.isArray(unassignedTestRuns) ? unassignedTestRuns : [];
    if (!availableRuns.length) {
        emptyHint.classList.remove('d-none');
        confirmBtn.disabled = true;
    } else {
        emptyHint.classList.add('d-none');
        confirmBtn.disabled = false;
        listContainer.innerHTML = availableRuns.map(run => `
            <label class="list-group-item d-flex align-items-center justify-content-between">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" value="${run.id}" id="add-existing-run-${run.id}">
                    <label class="form-check-label" for="add-existing-run-${run.id}">
                        <strong>${escapeHtml(run.name)}</strong>
                        <div class="small text-muted">${getStatusText(run.status)} · ${run.executed_cases || 0}/${run.total_test_cases || 0}</div>
                    </label>
                </div>
            </label>
        `).join('');
    }

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(modalEl);
    }

    addExistingRunToSetModalInstance.show();
}

async function confirmAddExistingRunToSet() {
    const modalEl = document.getElementById('addExistingRunToSetModal');
    const targetSetId = parseInt(modalEl.dataset.targetSetId || '0', 10);
    if (!targetSetId) {
        addExistingRunToSetModalInstance.hide();
        return;
    }

    const selected = Array.from(document.querySelectorAll('#addExistingRunToSetList input[type="checkbox"]:checked'))
        .map(input => parseInt(input.value, 10));

    if (!selected.length) {
        AppUtils.showWarning(window.i18n?.t('testRun.sets.addExisting.selectWarning') || 'Select at least one Test Run');
        return;
    }

    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${targetSetId}/members`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config_ids: selected })
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || '加入既有 Test Run 失敗');
        }

        addExistingRunToSetModalInstance.hide();
        AppUtils.showSuccess(window.i18n?.t('testRun.sets.addExisting.success') || 'Selected Test Runs added to Set');
        await loadTestRunConfigs();
        await refreshCurrentSetDetail();
    } catch (error) {
        console.error('Add existing Test Run failed:', error);
        AppUtils.showError(error.message);
    }
}

// Per-card "加入 Set" picker for ungrouped Test Runs. Uses a fixed-position
// dropdown (same pattern as the status dropdown) to avoid card clipping.
function toggleAddToSetDropdown(button, configId) {
    const permissions = window._testRunPermissions || testRunPermissions || {};
    if (!permissions.canUpdate) {
        showPermissionDenied();
        return;
    }

    const dropdown = document.getElementById('addToSetDropdown');
    const overlay = document.getElementById('addToSetDropdownOverlay');
    if (!dropdown || !overlay) return;

    if (dropdown.classList.contains('show')) {
        hideAddToSetDropdown();
        return;
    }

    currentAddToSetConfigId = configId;
    generateAddToSetDropdownItems(dropdown);

    const rect = button.getBoundingClientRect();
    dropdown.style.left = rect.left + 'px';
    dropdown.style.top = (rect.bottom + 5) + 'px';

    overlay.classList.add('show');
    dropdown.classList.add('show');

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(dropdown);
    }
}

function hideAddToSetDropdown() {
    const dropdown = document.getElementById('addToSetDropdown');
    const overlay = document.getElementById('addToSetDropdownOverlay');
    if (dropdown) dropdown.classList.remove('show');
    if (overlay) overlay.classList.remove('show');
    currentAddToSetConfigId = null;
}

function generateAddToSetDropdownItems(dropdown) {
    const sets = (Array.isArray(testRunSets) ? testRunSets : []).filter(s => s.status !== 'archived');
    if (!sets.length) {
        dropdown.innerHTML = `<div class="custom-status-dropdown-item text-muted" data-i18n="testRun.sets.addToSetEmpty">尚無可加入的 Set</div>`;
        return;
    }
    dropdown.innerHTML = sets.map(s => `
        <div class="custom-status-dropdown-item" onclick="handleAddToSetSelection(${s.id})">
            <i class="fas fa-layer-group me-2"></i>${escapeHtml(s.name)}
        </div>
    `).join('');
}

function handleAddToSetSelection(setId) {
    const configId = currentAddToSetConfigId;
    hideAddToSetDropdown();
    if (configId && setId) {
        moveTestRunToSet(configId, setId);
    }
}

async function moveTestRunToSet(configId, targetSetId) {
    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/members/${configId}/move`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_set_id: targetSetId })
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || '搬移 Test Run 失敗');
        }

        const targetName = targetSetId
            ? (testRunSets.find(s => s.id === targetSetId)?.name || '其他 Set')
            : (window.i18n?.t('testRun.sets.moveToUnassigned') || '未歸組 Test Run');
        AppUtils.showSuccess(`${window.i18n?.t('testRun.sets.moveSuccess') || '搬移成功'}：${targetName}`);

        await loadTestRunConfigs();
        await refreshCurrentSetDetail();
    } catch (error) {
        console.error('Move Test Run between sets failed:', error);
        AppUtils.showError(error.message);
    }
}

async function removeTestRunFromSet(configId, configName) {
    const confirmed = await AppUtils.showConfirm(window.i18n?.t('testRun.sets.removeConfirm', { name: configName }) || `確定要將 ${configName} 移出目前的 Test Run Set？`);
    if (!confirmed) return;
    await moveTestRunToSet(configId, null);
}

async function toggleArchiveTestRunSet(setData, targetStatus) {
    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${setData.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: targetStatus })
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || '更新狀態失敗');
        }

        const successMsg = targetStatus === 'archived'
            ? (window.i18n?.t('testRun.sets.archiveSuccess') || 'Test Run Set 已 Archive')
            : (window.i18n?.t('testRun.sets.unarchiveSuccess') || 'Test Run Set 已啟用');
        AppUtils.showSuccess(successMsg);

        await loadTestRunConfigs();
        await refreshCurrentSetDetail();
    } catch (error) {
        console.error('Toggle archive Test Run Set failed:', error);
        AppUtils.showError(error.message);
    }
}

async function deleteTestRunSet(setId) {
    const currentTeamId = AppUtils.getCurrentTeamId();
    if (!currentTeamId) {
        console.error('No team selected');
        return;
    }

    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${setId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || '刪除失敗');
        }

        AppUtils.showSuccess(window.i18n?.t('testRun.sets.deleteSuccess') || 'Test Run Set 已刪除');
        
        // Close modals if open
        const deleteModalEl = document.getElementById('deleteTestRunSetModal');
        if (deleteModalEl) {
            const modal = bootstrap.Modal.getInstance(deleteModalEl);
            if (modal) modal.hide();
        }
        
        // Close detail modal if open
        if (testRunSetDetailModalInstance) {
            testRunSetDetailModalInstance.hide();
        }

        await loadTestRunConfigs();
    } catch (error) {
        console.error('Delete Test Run Set failed:', error);
        AppUtils.showError(error.message);
    }
}

async function confirmDeleteTestRunSet(setData) {
    const confirmed = await AppUtils.showConfirm(window.i18n?.t('testRun.sets.deleteConfirm', { name: setData.name }) || `確定要刪除「${setData.name}」以及底下的所有 Test Run？`);
    if (!confirmed) return;

    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${setData.id}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const payload = await response.json().catch(() => ({ detail: null }));
            throw new Error(payload?.detail || '刪除失敗');
        }

        AppUtils.showSuccess(window.i18n?.t('testRun.sets.deleteSuccess') || 'Test Run Set 已刪除');
        testRunSetDetailModalInstance?.hide();
        await loadTestRunConfigs();
    } catch (error) {
        console.error('Delete Test Run Set failed:', error);
        AppUtils.showError(error.message);
    }
}

async function refreshCurrentSetDetail() {
    const modalEl = document.getElementById('testRunSetDetailModal');
    if (!modalEl || !modalEl.classList.contains('show') || !currentSetContext) {
        return;
    }

    try {
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-sets/${currentSetContext.id}`);
        if (!response.ok) {
            throw new Error('Refresh failed');
        }
        currentSetContext = await response.json();
        renderTestRunSetDetail(currentSetContext, currentStatusFilter);
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(modalEl);
        }
    } catch (error) {
        console.warn('Refresh Test Run Set detail failed:', error);
    }
}

window.refreshCurrentSetDetail = refreshCurrentSetDetail;
