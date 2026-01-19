/* ============================================================
   TEST RUN MANAGEMENT - CONFIG MODAL
   ============================================================ */

function openConfigFormModal(configId = null, options = {}) {
    const permissions = window._testRunPermissions || testRunPermissions || {};
    if (configId && !permissions.canUpdate) {
        showPermissionDenied();
        return;
    }
    if (!configId && !permissions.canCreate) {
        showPermissionDenied();
        return;
    }

    // 如果 Test Run Set Detail Modal 正在顯示，先隱藏它
    const setDetailModalElement = document.getElementById('testRunSetDetailModal');
    const wasSetDetailModalOpen = setDetailModalElement && setDetailModalElement.classList.contains('show');
    if (wasSetDetailModalOpen && testRunSetDetailModalInstance) {
        preserveSetContextOnHide = true;
        testRunSetDetailModalInstance.hide();
    }
    suppressSetDetailReopen = false;

    const modalElement = document.getElementById('configFormModal');
    if (!configFormModalInstance) {
        configFormModalInstance = new bootstrap.Modal(modalElement);
    }

    const form = document.getElementById('testRunConfigForm');
    form.reset();
    document.getElementById('configId').value = '';
    // 優先使用顯式傳入的 setId；若有從 Test Case Set 預選流程也帶入
    if (!options.setId && window._testCaseSetIdSource) {
        options.setId = window._testCaseSetIdSource;
    }
    pendingSetIdForNewConfig = options.setId ?? null;
    document.getElementById('configSetId').value = pendingSetIdForNewConfig ? String(pendingSetIdForNewConfig) : '';
    renderTestCaseSetOptions(pendingSetIdForNewConfig);
    currentSetIdForCaseSelection = pendingSetIdForNewConfig ?? null;

    const titleEl = document.getElementById('configFormModalTitle');
    const saveBtnTextEl = document.getElementById('saveConfigBtnText');

    if (configId) {
        // Edit mode
        const config = testRunConfigs.find(c => c.id === configId);
        if (config) {
            titleEl.setAttribute('data-i18n', 'testRun.editConfig');
            saveBtnTextEl.setAttribute('data-i18n', 'common.update');
            document.getElementById('configId').value = config.id;
            document.getElementById('configName').value = config.name;
            document.getElementById('configDescription').value = config.description || '';
            document.getElementById('configSetId').value = config.set_id ? String(config.set_id) : '';
            currentSetIdForCaseSelection = null;
            document.getElementById('configTestCaseSetId').value = '';
            updateTestRunSetReadOnlyDisplay(null, 'edit');
            resolveConfigTestCaseSetId(configId).then(deducedSetId => {
                currentSetIdForCaseSelection = deducedSetId;
                if (deducedSetId) {
                    document.getElementById('configTestCaseSetId').value = String(deducedSetId);
                }
                renderTestCaseSetOptions(deducedSetId);
                updateTestRunSetReadOnlyDisplay(deducedSetId, 'edit');
            });
            // 嘗試載入詳細配置以填入可選欄位和 TP 票號
            window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${configId}`)
              .then(r => r.ok ? r.json() : null)
              .then(full => {
                if (full) {
                  const descriptionInput = document.getElementById('configDescription');
                  if (descriptionInput && !descriptionInput.value.trim()) {
                    descriptionInput.value = full.description || '';
                  }
                  document.getElementById('testEnvironment').value = full.test_environment || '';
                  document.getElementById('buildNumber').value = full.build_number || '';
                  // 載入 TP 票號
                  const tpTickets = full.related_tp_tickets || [];
                  setTpTickets(tpTickets);
                  // 載入通知設定
                  loadNotificationSettings(full.notifications_enabled || false, full.notify_chat_ids || [], full.notify_chat_names_snapshot || []);
                }
              }).catch(() => {});
        }
    } else {
        // Create mode
        titleEl.setAttribute('data-i18n', 'testRun.createConfig');
        saveBtnTextEl.setAttribute('data-i18n', 'common.create');
        // 清空 TP 票號
        clearAllTpTickets();
        renderTestCaseSetOptions(pendingSetIdForNewConfig);
        updateTestRunSetReadOnlyDisplay(pendingSetIdForNewConfig, 'create');
    }
    
    // 初始化 TP 標籤輸入功能
    initTpTicketInput();
    
    // 初始化通知設定功能
    initNotificationSettings();
    
    // 監聽 Modal 關閉事件，清理 TP 標籤狀態和通知設定
    modalElement.addEventListener('hidden.bs.modal', function() {
        clearAllTpTickets();
        clearNotificationSettings();
        pendingSetIdForNewConfig = null;
        document.getElementById('configSetId').value = '';
        updateTestRunSetReadOnlyDisplay(null, 'create');

        // 如果之前 Test Run Set Detail Modal 是打開的，重新顯示它
        if (!suppressSetDetailReopen && wasSetDetailModalOpen && testRunSetDetailModalInstance) {
            testRunSetDetailModalInstance.show();
        }
        suppressSetDetailReopen = false;
    }, { once: true }); // 只監聽一次，避免重複綁定

    if (window.i18n) window.i18n.retranslate(modalElement);
    configFormModalInstance.show();
}

async function handleSaveConfig() {
    const form = document.getElementById('testRunConfigForm');
    
    // 執行綜合表單驗證
    const validationResult = validateTestRunConfigForm();
    if (!validationResult.isValid) {
        // 顯示第一個錯誤並聚焦到對應欄位
        showFormValidationError(validationResult);
        return;
    }
    
    // HTML5 基礎驗證
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }

    const configId = document.getElementById('configId').value;
    const isEdit = !!configId;

    const permissions = window._testRunPermissions || testRunPermissions || {};
    if (isEdit && !permissions.canUpdate) {
        showPermissionDenied();
        return;
    }
    if (!isEdit && !permissions.canCreate) {
        showPermissionDenied();
        return;
    }

    const configData = { name: document.getElementById('configName').value };
    const descVal = (document.getElementById('configDescription').value || '').trim();
    const envVal = (document.getElementById('testEnvironment').value || '').trim();
    const buildVal = (document.getElementById('buildNumber').value || '').trim();
    const tpTickets = getCurrentTpTickets(); // 獲取當前 TP 票號列表
    const notificationSettings = getCurrentNotificationSettings(); // 獲取當前通知設定
    
    if (descVal) configData.description = descVal;
    if (envVal) configData.test_environment = envVal;
    if (buildVal) configData.build_number = buildVal;
    configData.related_tp_tickets = tpTickets;  // 總是傳送，即使是空陣列
    // 加入通知設定
    configData.notifications_enabled = notificationSettings.enabled;
    if (notificationSettings.enabled && notificationSettings.chatIds.length > 0) {
        configData.notify_chat_ids = notificationSettings.chatIds;
        configData.notify_chat_names_snapshot = notificationSettings.chatNames;
    }

  if (!isEdit) {
    const testCaseSetId = document.getElementById('configTestCaseSetId').value;
    if (!testCaseSetId) {
      const msg = window.i18n ? (window.i18n.t('testRun.sets.selectSetFirst') || '請先選擇一個 Test Case Set 再建立 Test Run') : '請先選擇一個 Test Case Set 再建立 Test Run';
      AppUtils.showWarning(msg);
      return;
    }
    currentSetIdForCaseSelection = parseInt(testCaseSetId, 10);
    window._lastTestCaseSetIdForRun = currentSetIdForCaseSelection;
    renderTestCaseSetOptions(currentSetIdForCaseSelection);
    // 保留原有 Test Run Set 功能（若有選擇）
    const setIdValue = document.getElementById('configSetId').value;
    if (setIdValue) {
      configData.set_id = parseInt(setIdValue, 10);
    }
    }

    const url = isEdit
      ? `/api/teams/${currentTeamId}/test-run-configs/${configId}`
      : `/api/teams/${currentTeamId}/test-run-configs`;
    const method = isEdit ? 'PUT' : 'POST';

    const saveBtn = document.getElementById('saveConfigBtn');
    try {
        saveBtn.disabled = true;
        const response = await window.AuthClient.fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configData)
        });

        if (!response.ok) {
            const errorData = await response.json();
            const fallbackMsg = window.i18n ? window.i18n.t('messages.saveFailed') : '儲存失敗';
            throw new Error(errorData.detail || fallbackMsg);
        }

        const data = await response.json();
        if (!isEdit) {
            suppressSetDetailReopen = true;
        }
        configFormModalInstance.hide();
        if (isEdit) {
            const msg = window.i18n ? window.i18n.t('testRun.updateSuccess') : '更新成功';
            AppUtils.showSuccess(msg);
            await loadTestRunConfigs();
        } else {
            const msg = window.i18n ? window.i18n.t('testRun.createConfigSuccessSelectCases') : '建立成功，請選擇要加入的 Test Case';
            AppUtils.showSuccess(msg);
            currentSetIdForCaseSelection = window._lastTestCaseSetIdForRun || parseInt(document.getElementById('configTestCaseSetId').value || '0', 10) || null;
            renderTestCaseSetOptions(currentSetIdForCaseSelection);
            // 進入 Test Case 選擇流程（直接開啟，取消時自動回滾）
            pendingCreate = true;
            createdItemsInSession = false;
            // 確保為全新建立流程，清空任何編輯殘留選取狀態
            modalMode = 'create';
            selectedCaseMap.clear();
            existingItemIdByCaseNumber.clear();
            
            // 檢查是否有從 Test Case Set 預選的 Test Cases
            if (window._preselectedCaseIdsFromSet) {
              window._preselectedCaseIds = new Set(window._preselectedCaseIdsFromSet.split(',').map(id => id.trim()));
              isPreselectedFromTestCaseSet = true;
              // 清除臨時變數
              window._preselectedCaseIdsFromSet = null;
              window._testCaseSetIdSource = null;
            } else {
              isPreselectedFromTestCaseSet = false;
            }
            
            openCaseSelectModal(data.id);
        }

    } catch (error) {
        AppUtils.showError(error.message);
    } finally {
        saveBtn.disabled = false;
        pendingSetIdForNewConfig = null;
        document.getElementById('configSetId').value = '';
    }
}
