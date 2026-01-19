/* ============================================================
   TEST RUN MANAGEMENT - SET MODAL
   ============================================================ */

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
    } else {
        titleEl.setAttribute('data-i18n', 'testRun.sets.form.createTitle');
        titleEl.textContent = window.i18n?.t('testRun.sets.form.createTitle') || '新增 Test Run Set';
    }

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

    const endpoint = setId
        ? `/api/teams/${currentTeamId}/test-run-sets/${setId}`
        : `/api/teams/${currentTeamId}/test-run-sets`;
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
    const actionsContainer = document.getElementById('testRunSetDetailActions');
    const runsContainer = document.getElementById('testRunSetRunsContainer');

    titleEl.textContent = setData.name || '';

    if (setData.description) {
        descEl.innerHTML = escapeHtml(setData.description).replace(/\n/g, '<br>');
    } else {
        descEl.innerHTML = '<span class="text-muted" data-i18n="testRun.sets.detail.noDescription">尚未填寫描述</span>';
    }

    statusEl.innerHTML = getSetStatusBadge(setData.status);

    const metrics = summarizeSetMetrics(setData.test_runs || []);
    const metaText = `${window.i18n?.t('testRun.sets.detail.totalRuns') || 'Test Run 數'}: ${setData.test_runs?.length || 0} · ${window.i18n?.t('testRun.sets.detail.totalCases') || '總案例'}: ${metrics.totalCases}`;
    metaEl.textContent = metaText;
    renderSetDetailTpTags(setData.related_tp_tickets || []);

    const perms = window._testRunPermissions || testRunPermissions || {};

    const createBtn = document.getElementById('setDetailCreateConfigBtn');
    const addExistingBtn = document.getElementById('setDetailAddExistingBtn');
    const editBtn = document.getElementById('setDetailEditBtn');
    const archiveBtn = document.getElementById('setDetailArchiveBtn');
    const reportBtn = document.getElementById('setDetailReportBtn');
    const deleteBtn = document.getElementById('setDetailDeleteBtn');

    setElementVisibility('setDetailCreateConfigBtn', perms.canCreate);
    setElementVisibility('setDetailAddExistingBtn', perms.canCreate);
    setElementVisibility('setDetailEditBtn', perms.canUpdate);
    setElementVisibility('setDetailArchiveBtn', perms.canUpdate);
    setElementVisibility('setDetailReportBtn', true);
    setElementVisibility('setDetailDeleteBtn', perms.canDelete);

    if (createBtn) {
        createBtn.disabled = setData.status === 'archived' || !perms.canCreate;
        createBtn.onclick = () => openConfigFormModal(null, { setId: setData.id });
    }

    if (addExistingBtn) {
        addExistingBtn.disabled = setData.status === 'archived' || !perms.canCreate;
        addExistingBtn.onclick = () => openAddExistingToSetModal(setData);
    }

    if (editBtn) {
        editBtn.disabled = !perms.canUpdate;
        editBtn.onclick = () => openTestRunSetFormModal(setData.id);
    }

    if (archiveBtn) {
        archiveBtn.disabled = !perms.canUpdate;
        if (setData.status === 'archived') {
            archiveBtn.innerHTML = '<i class="fas fa-undo me-1"></i><span data-i18n="testRun.sets.detail.unarchive">取消 Archive</span>';
            archiveBtn.onclick = () => toggleArchiveTestRunSet(setData, 'active');
        } else {
            archiveBtn.innerHTML = '<i class="fas fa-archive me-1"></i><span data-i18n="testRun.sets.detail.archive">Archive</span>';
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

    const runs = filterTestRunsByStatus(setData.test_runs || [], filterStatus);
    if (!runs.length) {
        const emptyKey = filterStatus === 'all' ? 'testRun.sets.detail.noRuns' : 'testRun.sets.detail.noFilterMatches';
        const fallbackText = filterStatus === 'all' ? '尚未加入任何 Test Run' : '目前沒有符合篩選條件的 Test Run';
        runsContainer.innerHTML = `
            <div class="text-center text-muted py-4" data-i18n="${emptyKey}">
                ${fallbackText}
            </div>
        `;
    } else {
        runsContainer.innerHTML = runs.map(run => buildSetRunDetailRow(run, setData)).join('');
    }

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(actionsContainer);
        window.i18n.retranslate(runsContainer);
    }
}

function buildSetRunDetailRow(run, setData) {
    const statusClass = getStatusClass(run.status);
    const statusText = getStatusText(run.status);
    const metricsText = `${run.executed_cases || 0}/${run.total_test_cases || 0}`;
    const createdText = run.created_at ? AppUtils.formatDate(run.created_at, 'datetime') : '';
    const otherSets = (testRunSets || []).filter(s => s.id !== setData.id);
    const perms = window._testRunPermissions || testRunPermissions || {};
    const moveLabel = window.i18n?.t('testRun.sets.detail.moveToOther') || '搬移至其他 Set';
    const moveDropdown = (perms.canUpdate && otherSets.length > 0) ? `
        <div class="dropdown" onclick="event.stopPropagation()">
            <button class="btn btn-sm btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                <i class="fas fa-random me-1"></i><span data-i18n="testRun.sets.detail.moveToOther">${escapeHtml(moveLabel)}</span>
            </button>
            <ul class="dropdown-menu dropdown-menu-end">
                ${otherSets.map(s => `
                    <li>
                        <button class="dropdown-item" type="button" onclick="event.stopPropagation(); moveTestRunToSet(${run.id}, ${s.id});">
                            ${escapeHtml(s.name)}
                        </button>
                    </li>
                `).join('')}
            </ul>
        </div>
    ` : '';

    const lockedForConfigEdit = run.status === 'completed' || run.status === 'archived';
    const lockedForCasesEdit = run.status === 'completed';
    const lockedConfigMessage = (window.i18n && window.i18n.isReady())
        ? window.i18n.t('testRun.cannotEditCompleted')
        : '已完成或已歸檔的 Test Run 不可編輯';
    const lockedCasesMessage = (window.i18n && window.i18n.isReady())
        ? window.i18n.t('testRun.cannotEditCompleted')
        : '已完成的 Test Run 不可編輯 Test Case';
    const lockedConfigTitle = lockedForConfigEdit ? ` title="${escapeHtml(lockedConfigMessage)}"` : '';
    const lockedCasesTitle = (lockedForConfigEdit || lockedForCasesEdit) ? ` title="${escapeHtml(lockedCasesMessage)}"` : '';

    const primaryActionButtons = [];
    const secondaryActionButtons = [];

    primaryActionButtons.push(`
        <button class="btn btn-sm btn-primary" onclick="event.stopPropagation(); enterTestRun(${run.id})">
            <i class="fas fa-arrow-right me-1"></i><span data-i18n="testRun.enterButton">進入</span>
        </button>
    `);

    if (perms.canUpdate) {
        primaryActionButtons.push(`
            <button class="btn btn-sm btn-secondary${lockedForConfigEdit ? ' disabled' : ''}" ${lockedForConfigEdit ? 'disabled' : ''}${lockedConfigTitle}
                    onclick="event.stopPropagation(); editBasicSettings(${run.id})">
                <i class="fas fa-edit me-1"></i><span data-i18n="testRun.editBasicSettings">編輯基本設定</span>
            </button>
        `);

        primaryActionButtons.push(`
            <button class="btn btn-sm btn-info${(lockedForConfigEdit || lockedForCasesEdit) ? ' disabled' : ''}" ${(lockedForConfigEdit || lockedForCasesEdit) ? 'disabled' : ''}${lockedCasesTitle}
                    onclick="event.stopPropagation(); editTestCases(${run.id})">
                <i class="fas fa-list me-1"></i><span data-i18n="testRun.editTestCases">編輯 Test Case</span>
            </button>
        `);
    }

    if (perms.canChangeStatus) {
        secondaryActionButtons.push(`
            <div class="position-relative" onclick="event.stopPropagation()">
                <button type="button" class="btn btn-sm btn-warning custom-status-btn"
                        data-config-id="${run.id}"
                        onclick="event.stopPropagation(); toggleCustomStatusDropdown(this, ${run.id})">
                    <i class="fas fa-exchange-alt me-1"></i><span data-i18n="testRun.changeStatus">狀態</span>
                    <i class="fas fa-chevron-down ms-1"></i>
                </button>
            </div>
        `);
    }

    if (perms.canUpdate) {
        secondaryActionButtons.push(`
            <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); removeTestRunFromSet(${run.id}, '${escapeHtml(run.name)}')">
                <i class="fas fa-unlink me-1"></i><span data-i18n="testRun.sets.detail.remove">移出 Test Run Set</span>
            </button>
        `);
    }

    if (perms.canDelete) {
        secondaryActionButtons.push(`
            <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteTestRun(${run.id}, '${escapeHtml(run.name)}')">
                <i class="fas fa-trash me-1"></i><span data-i18n="common.delete">刪除</span>
            </button>
        `);
    }

    if (moveDropdown) {
        secondaryActionButtons.unshift(moveDropdown);
    }

    const actionsHtml = (() => {
        const merged = [...primaryActionButtons, ...secondaryActionButtons];
        if (!merged.length) return '';
        return `<div class="testRunDetailRunActions">${merged.join('')}</div>`;
    })();

    return `
        <div class="card mb-3">
            <div class="card-body">
                <!-- Test Run 名稱 -->
                <h6 class="mb-2 text-primary">${escapeHtml(run.name)}</h6>
                <!-- Test Run 狀態資訊 -->
                <div class="mb-3 small">
                    <div class="d-flex gap-2 align-items-center flex-wrap">
                        <span class="status-badge ${statusClass}">${statusText}</span>
                        <span class="text-muted"><i class="fas fa-list-ul me-1"></i>${metricsText}</span>
                        ${createdText ? `<span class="text-muted"><i class="fas fa-clock me-1\"></i>${createdText}</span>` : ''}
                    </div>
                </div>
                <!-- 按鈕區域 -->
                ${actionsHtml || ''}
            </div>
        </div>
    `;
}

function openAddExistingToSetModal(setData) {
    if (!addExistingToSetModalInstance) {
        const modalEl = document.getElementById('addExistingToSetModal');
        addExistingToSetModalInstance = new bootstrap.Modal(modalEl);
    }

    const listContainer = document.getElementById('addExistingToSetList');
    const emptyHint = document.getElementById('addExistingToSetEmpty');
    const confirmBtn = document.getElementById('confirmAddExistingToSetBtn');
    listContainer.innerHTML = '';

    const availableRuns = Array.isArray(unassignedTestRuns) ? unassignedTestRuns : [];
    if (!availableRuns.length) {
        emptyHint.style.display = 'block';
        confirmBtn.disabled = true;
    } else {
        emptyHint.style.display = 'none';
        confirmBtn.disabled = false;
        listContainer.innerHTML = availableRuns.map(run => `
            <label class="list-group-item d-flex align-items-center justify-content-between">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" value="${run.id}" id="add-existing-${run.id}">
                    <label class="form-check-label" for="add-existing-${run.id}">
                        <strong>${escapeHtml(run.name)}</strong>
                        <div class="small text-muted">${getStatusText(run.status)} · ${run.executed_cases || 0}/${run.total_test_cases || 0}</div>
                    </label>
                </div>
            </label>
        `).join('');
    }

    const modalEl = document.getElementById('addExistingToSetModal');
    modalEl.dataset.targetSetId = String(setData.id);

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
        AppUtils.showWarning(window.i18n?.t('testRun.sets.addExisting.selectWarning') || '請至少選擇一個 Test Run');
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

        addExistingToSetModalInstance.hide();
        AppUtils.showSuccess(window.i18n?.t('testRun.sets.addExisting.success') || '已將選定的 Test Run 加入 Set');
        await loadTestRunConfigs();
        await refreshCurrentSetDetail();
    } catch (error) {
        console.error('Add existing Test Run failed:', error);
        AppUtils.showError(error.message);
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
