/* ============================================================
   TEST CASE MANAGEMENT - MODAL
   ============================================================ */

/* ============================================================
   12. 測試案例 Modal (Test Case Modal)
   ============================================================ */

// NOTE: originalFormData, isFormChanged, testCaseModalInstance 已統一定義於 Section 2

/**
 * 顯示測試案例 Modal
 * @param {object|null} testCase - 測試案例資料，null 表示新增
 */
function showTestCaseModal(testCase = null) {
    const modal = document.getElementById('testCaseModal');
    const title = document.getElementById('testCaseModalTitle');
    const form = document.getElementById('testCaseForm');
    const saveBtn = document.getElementById('saveTestCaseBtn');
    const saveAndAddNextBtn = document.getElementById('saveAndAddNextBtn');
    const isCopyMode = (modal && modal.dataset && modal.dataset.copyMode === '1');

    // 重設表單和狀態
    form.reset();
    isFormChanged = false;
    saveBtn.disabled = false; // 儲存按鈕始終啟用

    // 每次開啟 modal 重置暫存上傳 id（避免跨記錄汙染）
    currentTempUploadId = null;

    if (testCase) {
        // 編輯現有測試案例時，初始化附件資料
        if (Array.isArray(testCase.attachments) && testCase.attachments.length > 0) {
            uploadedAttachments = testCase.attachments.map(att => ({
                file_token: att.file_token,
                name: att.name,
                size: att.size,
                type: att.type || 'application/octet-stream',
                url: att.url || '',
                stored_name: att.file_token || att.stored_name || att.name || ''
            }));
        } else {
            uploadedAttachments = [];
        }
    } else {
        // 新增測試案例時，重設附件資料
        uploadedAttachments = [];
    }

    if (testCase) {
        // 找到當前測試案例在導航清單中的索引
        const navigationList = getNavigationTestCases();
        currentTestCaseIndex = navigationList.findIndex(tc => tc.record_id === testCase.record_id);
        updateNavigationButtons();
        title.textContent = window.i18n ? window.i18n.t('testCase.viewTestCase') : '檢視測試案例';
        title.setAttribute('data-i18n', 'testCase.viewTestCase');
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(title);
        }

        // 填入資料
        document.getElementById('testCaseId').value = testCase.record_id;

        // 設定 modal 的 recordId dataset 供刪除附件使用
        modal.dataset.recordId = testCase.record_id;
        document.getElementById('title').value = testCase.title || '';
        document.getElementById('testCaseNumber').value = testCase.test_case_number || '';
        document.getElementById('priority').value = testCase.priority || 'Medium';
        // 初始化 TCG 欄位 - tcg 現在是簡單的字串陣列
        const tcgList = Array.isArray(testCase.tcg) ? [...testCase.tcg] : [];
        const tcgValue = tcgList.join(', ');
        console.log('📌 showTestCaseModal: 載入 TCG 值:', tcgList);
        document.getElementById('tcg').value = tcgValue;

        // 初始化 Modal TCG 多選顯示（每一個單號一個 tag）
        modalTCGSelected = tcgList;
        renderModalTCGDisplay();
        document.getElementById('precondition').value = testCase.precondition || '';
        document.getElementById('test_steps').value = testCase.steps || '';
        document.getElementById('expected_result').value = testCase.expected_result || '';

        // 填充 section 選擇
        populateTestCaseSectionSelect();
        const sectionSelect = document.getElementById('testCaseSectionSelect');
        if (sectionSelect && testCase.test_case_section_id) {
            sectionSelect.value = testCase.test_case_section_id;
        }

        // 渲染附件列表（若列表資料沒有附件，補打一筆詳情以取得附件）
        renderAttachmentsList();
        try {
            const currentTeam = AppUtils.getCurrentTeam();
            if (currentTeam && currentTeam.id && (!Array.isArray(testCase.attachments) || testCase.attachments.length === 0)) {
                window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${encodeURIComponent(testCase.record_id)}`)
                    .then(r => r.ok ? r.json() : null)
                    .then(data => {
                        if (data && Array.isArray(data.attachments)) {
                            uploadedAttachments = data.attachments.map(att => ({
                                file_token: att.file_token,
                                name: att.name,
                                size: att.size,
                                type: att.type || 'application/octet-stream',
                                url: att.url || '',
                                stored_name: att.file_token || att.stored_name || att.name || ''
                            }));
                            renderAttachmentsList();
                        }
                    })
                    .catch(() => {});
            }
        } catch (_) {}

        // 儲存原始資料用於比較
        originalFormData = {
            title: testCase.title || '',
            test_case_number: testCase.test_case_number || '',
            priority: testCase.priority || 'Medium',
            tcg: testCase.tcg ? testCase.tcg.map(t => t.text || t).join(', ') : '',
            precondition: testCase.precondition || '',
            steps: testCase.steps || '',
            expected_result: testCase.expected_result || ''
        };

        // 初始化 Test Data
        currentTestData = Array.isArray(testCase.test_data) ? testCase.test_data.map(td => ({...td})) : [];
        renderTestDataList();

        // 初始化 Markdown 預覽內容
        markdownFields.forEach(fieldId => {
            updateMarkdownPreview(fieldId);
        });

        // 檢視模式下預設為預覽模式，Viewer 強制為預覽模式
        if (hasTestCasePermission('splitModeBtn')) {
            setEditorMode('preview');
        } else {
            // Viewer 模式：強制預覽模式，不允許切換
            setEditorMode('preview');
            // 移除編輯模式相關的事件處理
            disableEditingFeatures();
        }

        // 隱藏「儲存並新增下一筆」按鈕（編輯模式不需要）
        saveAndAddNextBtn.style.display = 'none';

        // 隱藏「複製並新增下一筆」按鈕（編輯模式不需要）
        const cloneAndAddNextBtn = document.getElementById('cloneAndAddNextBtn');
        if (cloneAndAddNextBtn) cloneAndAddNextBtn.style.display = 'none';

    } else {
        title.textContent = window.i18n ? window.i18n.t('testCase.createTestCase') : '新增測試案例';
        title.setAttribute('data-i18n', 'testCase.createTestCase');
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(title);
        }

        // 清空所有表單欄位
        document.getElementById('testCaseId').value = '';
        document.getElementById('title').value = '';
        document.getElementById('testCaseNumber').value = '';
        document.getElementById('priority').value = 'Medium';
        document.getElementById('tcg').value = '';
        document.getElementById('precondition').value = '';
        document.getElementById('test_steps').value = '';
        document.getElementById('expected_result').value = '';

        // 填充並清空 section 選擇
        populateTestCaseSectionSelect();
        const sectionSelect = document.getElementById('testCaseSectionSelect');
        if (sectionSelect) {
            sectionSelect.value = '';
        }

        // 清空 Modal TCG 多選顯示
        modalTCGSelected = [];
        renderModalTCGDisplay();

        // 清除 modal 的 recordId dataset
        modal.dataset.recordId = '';

        originalFormData = {};
        saveBtn.disabled = false; // 儲存按鈕始終啟用
        // 獲取「複製並新增下一筆」按鈕
        const cloneAndAddNextBtn = document.getElementById('cloneAndAddNextBtn');

        if (isCopyMode) {
            // 複製模式移除「儲存並新增下一筆」
            saveAndAddNextBtn.disabled = true;
            saveAndAddNextBtn.style.display = 'none';
            // 複製模式也隱藏「複製並新增下一筆」按鈕
            if (cloneAndAddNextBtn) cloneAndAddNextBtn.style.display = 'none';
        } else {
            saveAndAddNextBtn.disabled = false; // 新增模式下「儲存並新增下一筆」按鈕啟用
            saveAndAddNextBtn.style.display = 'inline-block'; // 顯示「儲存並新增下一筆」按鈕
            // 重置按鈕文字為正常狀態
            const saveAndNextText = window.i18n ? window.i18n.t('form.saveAndNext') : '儲存並新增下一筆';
            saveAndAddNextBtn.innerHTML = `<i class="fas fa-plus me-2"></i>${saveAndNextText}`;
            // 新增模式顯示「複製並新增下一筆」按鈕
            if (cloneAndAddNextBtn) cloneAndAddNextBtn.style.display = 'inline-block';
        }
        currentTestCaseIndex = -1;
        updateNavigationButtons();

        // 渲染附件列表（新增模式下為空）
        renderAttachmentsList();

        // 初始化 Test Data（新增模式為空）
        currentTestData = [];
        renderTestDataList();

        // 清空所有 Markdown 預覽內容
        markdownFields.forEach(fieldId => {
            const previewElement = document.querySelector(`.markdown-preview[data-target="${fieldId}"]`);
            if (previewElement) {
                const previewPlaceholder = window.i18n ? window.i18n.t('errors.previewPlaceholder') : '預覽內容會在這裡顯示';
                previewElement.innerHTML = `<p class="text-muted">${previewPlaceholder}</p>`;
            }
        });

        // 新增模式下預設為編輯模式
        setEditorMode('split');
    }

    // 啟用所有欄位（檢視/編輯合一）
    form.querySelectorAll('input, textarea, select').forEach(el => el.disabled = false);

    // 綁定變更監聽器
    bindFormChangeListeners();

    // 為三個 Markdown 編輯區域添加快捷鍵支持
    setupMarkdownHotkeys(document.getElementById('precondition'));
    setupMarkdownHotkeys(document.getElementById('test_steps'));
    setupMarkdownHotkeys(document.getElementById('expected_result'));

    // 在顯示 modal 前，確保所有滾動位置都在頂部
    // 這樣做可以避免 modal 顯示時的跳動效果
    resetModalScrollPositions(modal);

    // 只創建一次 Modal 實例，避免 backdrop 累積
    if (!testCaseModalInstance) {
        const modalOptions = window.__MINIMAL_MODE__ ? { backdrop: false, keyboard: true, focus: true } : undefined;
        testCaseModalInstance = new bootstrap.Modal(modal, modalOptions);

        // 只綁定一次事件監聽器
        // 顯示前立即重置滾動，並暫時隱藏內容避免進場彈跳
        modal.addEventListener('show.bs.modal', function() {
            modal.classList.add('modal-preparing');
            resetModalScrollPositions(modal);
        });
        // 顯示後完成高度計算，再解除隱藏（整體觀感無彈跳）
        modal.addEventListener('shown.bs.modal', function() {
            calculateDynamicHeights();
            resetModalScrollPositions(modal);
            modal.classList.remove('modal-preparing');
            // 綁定鍵盤左右鍵支援（僅檢視狀態觸發）
            document.addEventListener('keydown', handleTestCaseModalKeydown);
        });
        // 關閉時移除鍵盤事件監聽
        modal.addEventListener('hidden.bs.modal', function() {
            document.removeEventListener('keydown', handleTestCaseModalKeydown);
            // 離開時重置 copyMode 標記
            try { modal.dataset.copyMode = '0'; } catch (_) {}
            // 最小模式：在 Modal 關閉後一併關閉彈出視窗
            if (window.__MINIMAL_MODE__) {
                try { window.close(); } catch (e) {}
            }
        });

        // 最小模式：點擊關閉按鈕時一併關閉彈出視窗
        if (window.__MINIMAL_MODE__) {
            const closeBtn = modal.querySelector('.btn-close');
            if (closeBtn && !closeBtn._closeWindowBound) {
                closeBtn.addEventListener('click', function() {
                    setTimeout(function(){ try { window.close(); } catch (e) {} }, 0);
                });
                closeBtn._closeWindowBound = true;
            }
        }
    }

    // 綁定複製連結按鈕（使用當前測試案例/表單值）
    try {
        const btn = document.getElementById('copyTcmCaseLinkBtn');
        if (btn) {
            btn.onclick = () => {
                const teamId = getCurrentTeamId_TCM();
                // 優先從 testCase 物件，其次從表單欄位讀取
                const tcNumber = (testCase && testCase.test_case_number) || document.getElementById('testCaseNumber')?.value || '';
                const url = buildTcmUrl(teamId, tcNumber);
                if (window.AppUtils && typeof AppUtils.showCopyModal === 'function') {
                    AppUtils.showCopyModal(url);
                } else {
                    // 最簡回退
                    const promptLabel = (window.i18n && typeof window.i18n.t === 'function')
                        ? window.i18n.t('copyModal.prompt', {}, '請手動複製此連結：')
                        : '請手動複製此連結：';
                    window.prompt(promptLabel, url);
                }
            };
        }
    } catch (_) {}

    testCaseModalInstance.show();

    // 確保按鈕狀態正確（解決可能的時序問題）
    setTimeout(() => {
        const saveBtn = document.getElementById('saveTestCaseBtn');
        const saveAndAddNextBtn = document.getElementById('saveAndAddNextBtn');
        if (saveBtn) saveBtn.disabled = false;
        if (saveAndAddNextBtn && saveAndAddNextBtn.style.display !== 'none') {
            saveAndAddNextBtn.disabled = false;
        }
    }, 50);
}

// 鍵盤支援：在檢視 Test Case Modal 時使用左右鍵切換
function handleTestCaseModalKeydown(e) {
    try {
        const modal = document.getElementById('testCaseModal');
        if (!modal || !modal.classList.contains('show')) return;
        // 避免在輸入元件或可編輯區域觸發
        const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
        const isEditable = e.target && (e.target.isContentEditable || tag === 'input' || tag === 'textarea' || tag === 'select');
        if (isEditable) return;
        // 編輯模式時不觸發
        if (typeof currentEditorMode !== 'undefined' && currentEditorMode !== 'preview') return;
        if (e.key === 'ArrowLeft') {
            e.preventDefault();
            showPrevTestCase();
        } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            showNextTestCase();
        }
    } catch (_) {}
}

function viewTestCase(id) {
    const localCase = testCases.find(tc => tc.record_id === id);
    if (localCase) {
        showTestCaseModal(localCase);
        adjustTestCasesScrollHeight();
        return;
    }
    // 若本地沒有，嘗試後端取回避免誤判為新增
    const currentTeam = AppUtils.getCurrentTeam ? AppUtils.getCurrentTeam() : null;
    if (!currentTeam || !currentTeam.id) {
        adjustTestCasesScrollHeight();
        return;
    }
    (async () => {
        try {
            const resp = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${encodeURIComponent(id)}`);
            if (resp.ok) {
                const data = await resp.json();
                if (data && data.record_id) {
                    showTestCaseModal(data);
                }
            }
        } catch (e) {
            console.error('load test case failed', e);
        } finally {
            adjustTestCasesScrollHeight();
        }
    })();
}

// 表單變更監聽器
function bindFormChangeListeners() {
    const form = document.getElementById('testCaseForm');
    const saveBtn = document.getElementById('saveTestCaseBtn');
    const saveAndAddNextBtn = document.getElementById('saveAndAddNextBtn');

    // 為所有表單欄位綁定變更事件
    form.querySelectorAll('input, textarea, select').forEach(element => {
        element.addEventListener('input', checkFormChanges);
        element.addEventListener('change', checkFormChanges);
    });
}

// 檢查表單是否有變更
function checkFormChanges() {
    const form = document.getElementById('testCaseForm');
    const saveBtn = document.getElementById('saveTestCaseBtn');
    const saveAndAddNextBtn = document.getElementById('saveAndAddNextBtn');
    const formData = new FormData(form);

    // 儲存按鈕始終保持啟用狀態
    saveBtn.disabled = false;
    saveAndAddNextBtn.disabled = false;

    // 檢查新增模式
    if (!document.getElementById('testCaseId').value) {
        // 新增模式：所有儲存按鈕都保持啟用
        return;
    }

    // 編輯模式：比較與原始資料的差異（僅用於追蹤，不影響按鈕狀態）
    let hasChanges = false;

    for (const [key, value] of Object.entries(originalFormData)) {
        const currentValue = formData.get(key) || '';
        if (currentValue !== value) {
            hasChanges = true;
            break;
        }
    }

    isFormChanged = hasChanges;
    // 編輯模式下不再禁用儲存按鈕
}

// 檢查是否有未儲存的變更
function hasUnsavedChanges() {
    const form = document.getElementById('testCaseForm');
    if (!form) return false;

    const testCaseId = document.getElementById('testCaseId').value;

    // 新增模式：檢查是否有輸入任何內容
    if (!testCaseId) {
        const formData = new FormData(form);
        const title = formData.get('title') || '';
        const testCaseNumber = formData.get('test_case_number') || '';
        const steps = formData.get('steps') || '';
        const expectedResults = formData.get('expected_results') || '';

        // 如果任何欄位有內容，就認為有變更
        return title.trim() || testCaseNumber.trim() || steps.trim() || expectedResults.trim();
    }

    // 編輯模式：比較與原始資料的差異
    const formData = new FormData(form);
    for (const [key, value] of Object.entries(originalFormData)) {
        const currentValue = formData.get(key) || '';
        if (currentValue !== value) {
            return true;
        }
    }

    return false;
}

function deleteTestCase(id) {
    const testCase = testCases.find(tc => tc.record_id === id);
    if (!testCase) return;

    // 設置刪除確認 Modal 的內容
    const deleteList = document.getElementById('deleteList');
    deleteList.innerHTML = `
        <div class="mb-3">
            <p class="mb-2">確定要刪除以下測試案例嗎？</p>
            <div class="border rounded p-3 bg-light">
                <strong class="text-primary">${testCase.test_case_number || testCase.record_id}: ${testCase.title}</strong>
            </div>
        </div>
    `;

    // 顯示刪除確認 Modal
    const deleteModal = new bootstrap.Modal(document.getElementById('deleteConfirmModal'));
    deleteModal.show();

    // 設置確認刪除的處理
    document.getElementById('confirmDeleteBtn').onclick = async function() {
        try {
            // 獲取當前團隊
            const currentTeam = AppUtils.getCurrentTeam();
            if (!currentTeam || !currentTeam.id) {
                throw new Error('請先選擇團隊');
            }

            // 發送刪除請求
            const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${id}`, {
                method: 'DELETE'
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '刪除失敗');
            }

            // 關閉 Modal
            deleteModal.hide();

            // 從本地陣列移除已刪除的項目
            testCases = testCases.filter(tc => tc.record_id !== id);
            // 依目前過濾器重新渲染
            applyCurrentFiltersAndRender();

            // 從快取中移除
            removeTestCaseFromCache(id, testCase);

            // 重新渲染表格和分頁
            renderTestCasesTable();
            updatePagination();

            // 用 toast 通知成功
            AppUtils.showSuccess(window.i18n ? window.i18n.t('messages.testCaseDeleted') : '測試案例刪除成功');

        } catch (error) {
            console.error('刪除測試案例失敗:', error);
            const message = window.i18n ? window.i18n.t('errors.deleteFailed') : '刪除失敗';
            showError(message + '：' + error.message);
        }
    };
}

async function saveTestCase() {
    const form = document.getElementById('testCaseForm');
    const formData = new FormData(form);

    // 收集 Test Data
    const testData = currentTestData.map(td => ({
        id: td.id || crypto.randomUUID(),
        name: td.name || '',
        value: td.value || ''
    })).filter(td => td.name.trim() !== '');

    const testCaseData = {
        title: formData.get('title'),
        test_case_number: formData.get('test_case_number'),
        priority: formData.get('priority'),
        test_case_section_id: formData.get('test_case_section_id') ? parseInt(formData.get('test_case_section_id')) : null,
        precondition: document.getElementById('precondition').value,
        steps: document.getElementById('test_steps').value,
        expected_result: document.getElementById('expected_result').value,
        tcg: document.getElementById('tcg').value,  // 從隱藏欄位取得 TCG（由 Modal 多選系統維護）
        test_data: testData,
        // 新增：包含當前選擇的 Test Case Set ID
        ...(currentSetId && { test_case_set_id: currentSetId })
        // 注意：不再包含 attachments，因為附件現在是立即附加到記錄的
    };

    // 若存在暫存上傳，帶入 temp_upload_id 讓後端在建立/更新後搬移到正式資料夾
    if (currentTempUploadId) {
        testCaseData.temp_upload_id = currentTempUploadId;
    }

    // 除錯：檢查 test_steps 是否被正確收集
    const testStepsElement = document.getElementById('test_steps');
    console.log('test_steps element:', testStepsElement);
    console.log('test_steps element value:', testStepsElement ? testStepsElement.value : 'element not found');
    console.log('FormData test_steps:', formData.get('test_steps'));
    console.log('All form entries:');
    for (let [key, value] of formData.entries()) {
        console.log(`  ${key}: ${value}`);
    }
    console.log('testCaseData:', testCaseData);

    // 表單驗證
    if (!testCaseData.title) {
        showError(window.i18n ? window.i18n.t('errors.testCaseTitleRequired') : '請填寫測試案例標題');
        return;
    }
    if (!testCaseData.test_case_number || !testCaseData.test_case_number.trim()) {
        showError(window.i18n ? window.i18n.t('errors.testCaseNumberRequired') : '請填寫測試案例編號');
        return;
    }

    // 檢查測試案例編號唯一性
    if (testCaseData.test_case_number) {
        const currentTestCaseId = document.getElementById('testCaseId').value;
        const isDuplicate = testCases.some(tc =>
            tc.test_case_number === testCaseData.test_case_number &&
            tc.record_id !== currentTestCaseId // 排除當前編輯的記錄
        );

        if (isDuplicate) {
            const errorMessage = window.i18n ?
                window.i18n.t('errors.testCaseNumberDuplicate', {number: testCaseData.test_case_number}, `測試案例編號 '${testCaseData.test_case_number}' 已存在，請使用其他編號`) :
                `測試案例編號 '${testCaseData.test_case_number}' 已存在，請使用其他編號`;
            showError(errorMessage);
            return;
        }
    }

    // 獲取當前選擇的團隊
    const currentTeam = AppUtils.getCurrentTeam();
    if (!currentTeam || !currentTeam.id) {
        showError(window.i18n ? window.i18n.t('errors.pleaseSelectTeam') : '請先選擇團隊');
        return;
    }

    const testCaseId = document.getElementById('testCaseId').value;

    // 不關閉 Modal，保持編輯窗開啟以支持快速編輯
    // 重置變更狀態並禁用儲存按鈕
    isFormChanged = false;
    const saveBtn = document.getElementById('saveTestCaseBtn');
    saveBtn.disabled = true;
    const savingText = window.i18n ? window.i18n.t('messages.saving') : '儲存中...';
    saveBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>${savingText}`;

    // 顯示儲存中訊息
    const savingMessage = testCaseId ?
        (window.i18n ? window.i18n.t('messages.testCaseSaving') : '測試案例更新中...') :
        (window.i18n ? window.i18n.t('messages.testCaseSaving') : '測試案例新增中...');
    showSuccess(savingMessage);

    // 背景處理儲存
    setTimeout(async () => {
        try {
            let response;

            if (testCaseId) {
                // 更新現有測試案例
                response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${testCaseId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        ...testCaseData,
                        // 後端需要 section_id 包含 UNASSIGNED_SECTION_ID 時亦需傳遞
                        test_case_section_id: formData.get('test_case_section_id') ? parseInt(formData.get('test_case_section_id')) : null,
                    })
                });
            } else {
                // 新增測試案例
                // 建立 API 不支援 tcg 字串（僅 update 支援），避免 422 將其移除
                const tcgNumberForCreate = testCaseData.tcg ? String(testCaseData.tcg).trim() : '';
                try { delete testCaseData.tcg; } catch (_) {}
                response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        ...testCaseData,
                        test_case_section_id: formData.get('test_case_section_id') ? parseInt(formData.get('test_case_section_id')) : null,
                    })
                });
            }

            if (!response.ok) {
                let msg = '儲存失敗';
                try {
                    const errorData = await response.json();
                    if (errorData && errorData.detail) {
                        if (Array.isArray(errorData.detail)) {
                            msg = errorData.detail.map(d => d.msg || d.detail || JSON.stringify(d)).join('; ');
                        } else if (typeof errorData.detail === 'string') {
                            msg = errorData.detail;
                        } else {
                            msg = JSON.stringify(errorData.detail);
                        }
                    }
                } catch (_) {}
                throw new Error(msg);
            }

            // 如果是新增測試案例，需要取得新的記錄ID並轉為編輯模式
            if (!testCaseId) {
                const newTestCase = await response.json();
                if (newTestCase && newTestCase.record_id) {
                    document.getElementById('testCaseId').value = newTestCase.record_id;
                    document.getElementById('testCaseModalTitle').textContent = window.i18n ? window.i18n.t('testCase.viewTestCase') : '檢視測試案例';

                    // 如果使用者有輸入 TCG，於建立後立即更新一次（後端支援字串）
                    try {
                        const tcgInputEl = document.getElementById('tcg');
                        const tcgStr = (tcgInputEl && tcgInputEl.value) ? tcgInputEl.value.trim() : '';
                        if (tcgStr) {
                            await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${newTestCase.record_id}`, {
                                method: 'PUT',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ tcg: tcgStr })
                            });
                        }
                    } catch (e) {
                        console.warn('建立後更新 TCG 失敗（將繼續流程）:', e);
                    }
                }
            }

            // 清快取並重載，但保留目前的排序/篩選/區段狀態
            clearTestCasesCache();
            await loadTestCases(false, null, true, true);
            // 重新載入 section 清單（更新數量顯示）
            if (typeof window.testCaseSectionList !== 'undefined' && window.testCaseSectionList?.loadSections) {
                try {
                    await window.testCaseSectionList.loadSections({ reloadTestCases: false });
                } catch (e) {
                    console.warn('[TCM] reload sections after save failed', e);
                }
            }

            // 恢復儲存按鈕狀態
            const saveBtn = document.getElementById('saveTestCaseBtn');
            saveBtn.disabled = false; // 儲存按鈕始終啟用
            const saveText = window.i18n ? window.i18n.t('common.save') : '儲存';
            saveBtn.innerHTML = `<i class="fas fa-save me-2"></i>${saveText}`;

            // 如果是編輯模式，更新 originalFormData 以反映當前保存的狀態
            if (testCaseId) {
                const form = document.getElementById('testCaseForm');
                const currentFormData = new FormData(form);
                originalFormData = {
                    title: currentFormData.get('title') || '',
                    test_case_number: currentFormData.get('test_case_number') || '',
                    priority: currentFormData.get('priority') || 'Medium',
                    tcg: document.getElementById('tcg') ? document.getElementById('tcg').value : '',
                    precondition: document.getElementById('precondition') ? document.getElementById('precondition').value : '',
                    steps: document.getElementById('test_steps') ? document.getElementById('test_steps').value : '',
                    expected_result: document.getElementById('expected_result') ? document.getElementById('expected_result').value : ''
                };
            }

            // 成功後清空暫存上傳識別碼（避免影響下一次操作）
            currentTempUploadId = null;

            // 更新成功訊息
            const completedMessage = testCaseId ?
                (window.i18n ? window.i18n.t('messages.testCaseUpdated') : '測試案例更新完成') :
                (window.i18n ? window.i18n.t('messages.testCaseCreated') : '測試案例新增完成');
            showSuccess(completedMessage);

        } catch (error) {
            console.error('儲存測試案例失敗:', error);

            // 恢復儲存按鈕狀態
            const saveBtn = document.getElementById('saveTestCaseBtn');
            saveBtn.disabled = false;
            const saveText = window.i18n ? window.i18n.t('common.save') : '儲存';
            saveBtn.innerHTML = `<i class="fas fa-save me-2"></i>${saveText}`;

            const saveFailedMessage = window.i18n ? window.i18n.t('errors.saveFailed') : '儲存失敗';
            showError(saveFailedMessage + '：' + error.message);
        }
    }, 100); // 100ms 延遲確保 UI 響應
}

// 儲存並新增下一筆測試案例
async function saveAndAddNext() {
    const form = document.getElementById('testCaseForm');
    const formData = new FormData(form);

    const testCaseData = {
        title: formData.get('title'),
        test_case_number: formData.get('test_case_number'),
        priority: formData.get('priority'),
        test_case_section_id: formData.get('test_case_section_id') ? parseInt(formData.get('test_case_section_id')) : null,
        precondition: document.getElementById('precondition').value,
        steps: document.getElementById('test_steps').value,
        expected_result: document.getElementById('expected_result').value,
        // 直接取用 tcg 的字串（單號或多號逗號分隔），建立後再以 PUT 更新
        tcg: document.getElementById('tcg').value,
        // 新增：包含當前選擇的 Test Case Set ID
        ...(currentSetId && { test_case_set_id: currentSetId })
    };

    // 若存在暫存上傳，帶入 temp_upload_id
    if (currentTempUploadId) {
        testCaseData.temp_upload_id = currentTempUploadId;
    }

    // 表單驗證
    if (!testCaseData.title) {
        showError(window.i18n ? window.i18n.t('errors.testCaseTitleRequired') : '請填寫測試案例標題');
        return;
    }
    if (!testCaseData.test_case_number || !testCaseData.test_case_number.trim()) {
        showError(window.i18n ? window.i18n.t('errors.testCaseNumberRequired') : '請填寫測試案例編號');
        return;
    }

    // 檢查測試案例編號唯一性（新增模式不需要排除任何記錄）
    if (testCaseData.test_case_number) {
        const isDuplicate = testCases.some(tc =>
            tc.test_case_number === testCaseData.test_case_number
        );

        if (isDuplicate) {
            const errorMessage = window.i18n ?
                window.i18n.t('errors.testCaseNumberDuplicate', {number: testCaseData.test_case_number}, `測試案例編號 '${testCaseData.test_case_number}' 已存在，請使用其他編號`) :
                `測試案例編號 '${testCaseData.test_case_number}' 已存在，請使用其他編號`;
            showError(errorMessage);
            return;
        }
    }

    // 獲取當前選擇的團隊
    const currentTeam = AppUtils.getCurrentTeam();
    if (!currentTeam || !currentTeam.id) {
        showError(window.i18n ? window.i18n.t('errors.pleaseSelectTeam') : '請先選擇團隊');
        return;
    }

    // 禁用按鈕並顯示載入狀態
    const saveBtn = document.getElementById('saveTestCaseBtn');
    const saveAndAddNextBtn = document.getElementById('saveAndAddNextBtn');
    saveBtn.disabled = true;
    saveAndAddNextBtn.disabled = true;
    const savingText = window.i18n ? window.i18n.t('messages.saving') : '儲存中...';
    saveAndAddNextBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>${savingText}`;

    showSuccess(window.i18n ? window.i18n.t('messages.testCaseSaving') : '測試案例新增中...');

    try {
        // 新增測試案例
        // 建立 API 不支援 tcg 字串（僅 update 支援），避免 422 將其移除
        const tcgNumberForCreate = testCaseData.tcg ? String(testCaseData.tcg).trim() : '';
        try { delete testCaseData.tcg; } catch (_) {}
        const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(testCaseData)
        });

        if (!response.ok) {
            let msg = '儲存失敗';
            try {
                const errorData = await response.json();
                if (errorData && errorData.detail) {
                    if (Array.isArray(errorData.detail)) {
                        msg = errorData.detail.map(d => d.msg || d.detail || JSON.stringify(d)).join('; ');
                    } else if (typeof errorData.detail === 'string') {
                        msg = errorData.detail;
                    } else {
                        msg = JSON.stringify(errorData.detail);
                    }
                }
            } catch (_) {}
            throw new Error(msg);
        }

        // 取得新建記錄資訊以便更新 TCG（若有）
        let createdRecordId = null;
        try {
            const createdJson = await response.json();
            createdRecordId = createdJson && createdJson.record_id ? createdJson.record_id : null;
        } catch (_) {}

        // 若有 TCG 輸入，建立完成後立即更新 TCG（以字串）
        if (createdRecordId && tcgNumberForCreate) {
            try {
                await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${createdRecordId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tcg: tcgNumberForCreate })
                });
            } catch (e) {
                console.warn('建立後更新 TCG 失敗（將繼續流程）:', e);
            }
        }

        // 重新載入測試案例以取得新建立的記錄
        await loadTestCases(false, null, true);

        // 將新建的案例寫入執行頁快取
        try {
            const created = testCases.find(tc => tc.test_case_number === testCaseData.test_case_number);
            if (created && created.test_case_number) {
                // 新記錄會在 setTestCasesCache 中自動更新，這裡確保執行頁快取一致
                setExecCachedTestCase(created.test_case_number, created);
            }
        } catch (e) { console.debug('set exec cache (create) skipped:', e); }

        showSuccess(window.i18n ? window.i18n.t('messages.testCaseCreatedNext') : '測試案例新增完成，準備下一筆');

        // 保存當前資料用於產生下一筆
        const currentNumber = testCaseData.test_case_number;
        const currentTitle = testCaseData.title;
        const currentPrecondition = testCaseData.precondition;
        const currentSteps = testCaseData.steps;
        const currentExpectedResult = testCaseData.expected_result;
        const currentSectionId = testCaseData.test_case_section_id || '';
        // 重要：在重置表單前先暫存當前 TCG 單號（建立時不傳，建立後會用於 PUT）
        const currentTCG = (typeof tcgNumberForCreate === 'string' && tcgNumberForCreate.trim()) ? tcgNumberForCreate.trim() : '';

        // 成功新增後清空暫存上傳識別碼
        currentTempUploadId = null;
        // 重置表單為新增下一筆狀態
        showTestCaseModal(null); // 呼叫新增模式，會自動清空所有欄位並設定為編輯模式

        // 產生下一筆的預填資料
        const nextNumber = generateNextTestCaseNumber(currentNumber);
        const titlePrefix = extractTitlePrefix(currentTitle);

        // 設定預填值
        setTimeout(() => {
            if (nextNumber !== currentNumber) {
                document.getElementById('testCaseNumber').value = nextNumber;
            }
            if (titlePrefix) {
                document.getElementById('title').value = titlePrefix;
            }
            // 保留 Precondition, Steps, Expected Results
            if (currentPrecondition) {
                document.getElementById('precondition').value = currentPrecondition;
            }
            if (currentSteps) {
                document.getElementById('test_steps').value = currentSteps;
            }
            if (currentExpectedResult) {
                document.getElementById('expected_result').value = currentExpectedResult;
            }
            // 保留 Section 選擇
            const sectionSelect = document.getElementById('testCaseSectionSelect');
            if (sectionSelect && currentSectionId) {
                sectionSelect.value = currentSectionId;
                sectionSelect.dispatchEvent(new Event('change', { bubbles: true }));
            }
            // 保留相同 TCG 單號
            const tcgDisplayNext = document.getElementById('tcg');
            if (tcgDisplayNext) {
                tcgDisplayNext.value = currentTCG || '';
            }
            // 同步更新多選標籤狀態，確保 UI 與隱藏欄位一致
            if (typeof currentTCG === 'string' && currentTCG.trim()) {
                modalTCGSelected = currentTCG.split(',').map(t => t.trim()).filter(Boolean);
            } else {
                modalTCGSelected = [];
            }
            renderModalTCGDisplay();
        }, 100);

    } catch (error) {
        console.error('儲存測試案例失敗:', error);

        // 恢復按鈕狀態
        saveBtn.disabled = false;
        saveAndAddNextBtn.disabled = false;
        const saveAndNextText = window.i18n ? window.i18n.t('testCase.saveAndNext') : '儲存並新增下一筆';
        saveAndAddNextBtn.innerHTML = `<i class="fas fa-plus me-2"></i>${saveAndNextText}`;

        const saveFailedMessage = window.i18n ? window.i18n.t('errors.saveFailed') : '儲存失敗';
        showError(saveFailedMessage + '：' + error.message);
    }
}

// NOTE: generateNextTestCaseNumber 已統一定義於 Section 16 (複製/克隆)

function extractTitlePrefix(title) {
    // 找到最後一個 hyphen 並保留前面部分
    const lastHyphenIndex = title.lastIndexOf(' - ');
    if (lastHyphenIndex > 0) {
        return title.substring(0, lastHyphenIndex + 3);  // 保留 " - "
    }
    return '';  // 沒有 hyphen 則返回空字串
}

function getPriorityBadgeClass(priority) {
    const classes = {
        'High': 'bg-danger',
        'Medium': 'bg-warning',
        'Low': 'bg-info'
    };
    return classes[priority] || 'bg-secondary';
}

function getPriorityText(priority) {
    return priority || '';
}

function getTCGTags(testCase) {
    if (!testCase.tcg || testCase.tcg.length === 0) {
        return '';
    }

    // 提取所有 TCG 顯示文字（若 text 內含多個以逗號/空白/頓號/豎線分隔，拆成多個）
    const tcgNumbers = [];
    const pushSplit = (text) => {
        String(text || '')
            .split(/[\s,，、|/]+/)
            .map(s => s.trim())
            .filter(Boolean)
            .forEach(s => tcgNumbers.push(s));
    };
    for (const tcgRecord of testCase.tcg) {
        if (tcgRecord && Array.isArray(tcgRecord.text_arr) && tcgRecord.text_arr.length) {
            tcgRecord.text_arr.forEach(pushSplit);
        } else if (tcgRecord && tcgRecord.text) {
            pushSplit(tcgRecord.text);
        } else if (typeof tcgRecord === 'string') {
            pushSplit(tcgRecord);
        }
    }

    if (tcgNumbers.length === 0) {
        return '';
    }

    // 創建柔和的 tag（每一個單號一個 tag）
    return tcgNumbers.map(tcg =>
        `<span class=\"tcg-tag\">${tcg}</span>`
    ).join('');
}

function applyFilters() {
    const testCaseNumberSearchEl = document.getElementById('testCaseNumberSearch');
    const searchEl = document.getElementById('searchInput');
    const tcgEl = document.getElementById('tcgFilter');
    const priorityEl = document.getElementById('priorityFilter');

    // 更新記憶體中的過濾器
    tcmCurrentFilters.testCaseNumberSearch = testCaseNumberSearchEl ? (testCaseNumberSearchEl.value || '') : '';
    tcmCurrentFilters.searchInput = searchEl ? (searchEl.value || '') : '';
    tcmCurrentFilters.tcgFilter = tcgEl ? (tcgEl.value || '') : '';
    tcmCurrentFilters.priorityFilter = priorityEl ? (priorityEl.value || '') : '';

    // 保存到持久化儲存（依 team 隔離）
    saveTcmFiltersToStorage({
        testCaseNumberSearch: tcmCurrentFilters.testCaseNumberSearch,
        searchInput: tcmCurrentFilters.searchInput,
        tcgFilter: tcmCurrentFilters.tcgFilter,
        priorityFilter: tcmCurrentFilters.priorityFilter
    });

    // 依記憶體過濾器重新計算
    filteredTestCases = computeFilteredTestCases(testCases);

    currentPage = 1;
    renderTestCasesTable();
    updatePagination();
    updateFilterStatus();
}

function clearFilters() {
    const elNum = document.getElementById('testCaseNumberSearch');
    const elSearch = document.getElementById('searchInput');
    const elTCG = document.getElementById('tcgFilter');
    const elPri = document.getElementById('priorityFilter');
    if (elNum) elNum.value = '';
    if (elSearch) elSearch.value = '';
    if (elTCG) elTCG.value = '';
    if (elPri) elPri.value = '';

    // 清除此 team 的持久化篩選
    clearTcmFiltersInStorage();

    // 重置記憶體過濾器
    tcmCurrentFilters = { testCaseNumberSearch: '', searchInput: '', tcgFilter: '', priorityFilter: '' };

    filteredTestCases = [...testCases];
    currentPage = 1;
    renderTestCasesTable();
    updatePagination();
    updateFilterStatus();
}

/**
 * Serialize current filter values to URLSearchParams (only non-empty).
 * Param names: f_num, f_kw, f_tcg, f_pri
 */
function serializeFiltersToParams() {
    const params = new URLSearchParams();
    const num = (document.getElementById('testCaseNumberSearch')?.value || '').trim();
    const kw  = (document.getElementById('searchInput')?.value || '').trim();
    const tcg = (document.getElementById('tcgFilter')?.value || '').trim();
    const pri = (document.getElementById('priorityFilter')?.value || '').trim();
    if (num) params.set('f_num', num);
    if (kw)  params.set('f_kw', kw);
    if (tcg) params.set('f_tcg', tcg);
    if (pri) params.set('f_pri', pri);
    return params;
}

/**
 * Build full shareable URL with current page path + set context + filter params.
 * 確保 team_id 與 set_id 一定包含在連結中，使接收者能正確導向目標 team/set。
 */
function buildShareFilterURL() {
    const base = new URL(window.location.href);
    const filterParams = serializeFiltersToParams();
    const merged = new URLSearchParams(base.search);

    // 確保 team_id 與 set_id 存在（從 URL 或當前 context 補齊）
    let teamId = merged.get('team_id') || merged.get('teamId') || merged.get('team');
    let setId = merged.get('set_id') || merged.get('setId');
    if (!teamId && typeof getTeamIdForCache === 'function') {
        teamId = getTeamIdForCache(false);
    }
    if (!teamId && typeof AppUtils !== 'undefined' && AppUtils.getCurrentTeam) {
        const t = AppUtils.getCurrentTeam();
        if (t && t.id) teamId = String(t.id);
    }
    if (!setId && typeof currentSetId !== 'undefined' && currentSetId) {
        setId = String(currentSetId);
    }
    if (!setId && typeof testCaseSetIntegration !== 'undefined' && testCaseSetIntegration?.currentSetId) {
        setId = String(testCaseSetIntegration.currentSetId);
    }
    if (teamId) merged.set('team_id', teamId);
    if (setId) merged.set('set_id', setId);

    // Remove old filter params first
    ['f_num', 'f_kw', 'f_tcg', 'f_pri'].forEach(k => merged.delete(k));
    // Merge new filter params
    for (const [k, v] of filterParams) {
        merged.set(k, v);
    }
    base.search = merged.toString();
    return base.toString();
}

/**
 * Read filter params from URL and restore to UI elements + memory.
 * Returns true if any filter was restored.
 */
function restoreFiltersFromQueryString() {
    const params = new URLSearchParams(window.location.search);
    const num = params.get('f_num') || '';
    const kw  = params.get('f_kw') || '';
    const tcg = params.get('f_tcg') || '';
    const pri = params.get('f_pri') || '';
    if (!num && !kw && !tcg && !pri) return false;

    const elNum = document.getElementById('testCaseNumberSearch');
    const elSearch = document.getElementById('searchInput');
    const elTCG = document.getElementById('tcgFilter');
    const elPri = document.getElementById('priorityFilter');
    if (elNum) elNum.value = num;
    if (elSearch) elSearch.value = kw;
    if (elTCG) elTCG.value = tcg;
    if (elPri) elPri.value = pri;

    tcmCurrentFilters.testCaseNumberSearch = num;
    tcmCurrentFilters.searchInput = kw;
    tcmCurrentFilters.tcgFilter = tcg;
    tcmCurrentFilters.priorityFilter = pri;
    return true;
}

/**
 * Handler for "Generate Link" button.
 */
function generateShareFilterLink() {
    const url = buildShareFilterURL();
    const input = document.getElementById('shareFilterLinkInput');
    if (input) input.value = url;

    const feedback = document.getElementById('shareFilterLinkFeedback');
    if (feedback) feedback.style.display = 'none';

    const modal = new bootstrap.Modal(document.getElementById('shareFilterLinkModal'));
    modal.show();

    if (window.i18n) window.i18n.translateDOM(document.getElementById('shareFilterLinkModal'));
}

/**
 * Copy share link to clipboard.
 */
function copyShareFilterLink() {
    const input = document.getElementById('shareFilterLinkInput');
    if (!input) return;
    const url = input.value;
    const feedback = document.getElementById('shareFilterLinkFeedback');

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => {
            if (feedback) feedback.style.display = 'block';
        }).catch(() => {
            input.select();
            document.execCommand('copy');
            if (feedback) feedback.style.display = 'block';
        });
    } else {
        input.select();
        document.execCommand('copy');
        if (feedback) feedback.style.display = 'block';
    }
}

function updateFilterStatus() {
    const applyBtn = document.getElementById('applyFiltersBtn');
    const clearBtn = document.getElementById('clearFiltersBtn');

    // 檢查是否有任何篩選條件
    const hasFilters = hasAnyFilters();

    if (hasFilters) {
        // 有篩選條件時，更新按鈕樣式和文字
        const filteredText = window.i18n ? window.i18n.t('common.filtered', {count: filteredTestCases.length}) : `已篩選 (${filteredTestCases.length})`;
        applyBtn.innerHTML = '<i class="fas fa-filter me-2"></i>' + filteredText;
        applyBtn.className = 'btn btn-success me-2';
        clearBtn.style.display = 'inline-block';
    } else {
        // 無篩選條件時，恢復原始樣式
        const applyFilterText = window.i18n ? window.i18n.t('common.applyFilter') : '套用篩選';
        applyBtn.innerHTML = '<i class="fas fa-filter me-2"></i>' + applyFilterText;
        applyBtn.className = 'btn btn-primary me-2';
        clearBtn.style.display = testCases.length === filteredTestCases.length ? 'none' : 'inline-block';
    }
}

function toggleSelectAll() {
    const selectAllEl = document.getElementById('selectAllCheckbox');
    if (!selectAllEl) return;
    const selectAll = selectAllEl.checked;
    document.querySelectorAll('.test-case-checkbox').forEach(checkbox => {
        checkbox.checked = selectAll;
        const id = checkbox.value;
        if (selectAll) {
            selectedTestCases.add(id);
        } else {
            selectedTestCases.delete(id);
        }
    });
    updateBatchToolbar();
    lastCaseCheckboxIndex = null;
}

function updateBatchToolbar() {
    const toolbar = document.getElementById('batchInlineToolbar');
    if (!toolbar) return;

    const selectedCount = selectedTestCases ? selectedTestCases.size : 0;

    // 更新選中數量顯示
    const countWrapper = document.getElementById('selectedCountWrapper');
    if (countWrapper) {
        // 更新 data-i18n-params
        countWrapper.setAttribute('data-i18n-params', JSON.stringify({count: selectedCount}));

        // 如果 i18n 已載入，重新翻譯此元素
        if (window.i18n && window.i18n.updateElement) {
            window.i18n.updateElement(countWrapper);
        } else {
            // 如果 i18n 還未載入或無法更新，手動更新內容
            const currentLang = localStorage.getItem('preferredLanguage') || 'zh-TW';
            if (currentLang === 'zh-TW') {
                countWrapper.textContent = `已選取 ${selectedCount} 個項目`;
            } else {
                countWrapper.textContent = `${selectedCount} items selected`;
            }
        }
    }

    // 顯示/隱藏工具列
    if (!toolbar.dataset.defaultDisplay || toolbar.dataset.defaultDisplay === 'none') {
        const computed = window.getComputedStyle(toolbar).display;
        toolbar.dataset.defaultDisplay = (computed && computed !== 'none') ? computed : 'flex';
    }

    if (selectedCount > 0 && toolbar.dataset.permissionsEnabled !== 'false') {
        toolbar.classList.remove('d-none');
        const displayValue = toolbar.dataset.defaultDisplay || 'flex';
        toolbar.style.setProperty('display', displayValue, 'important');
    } else {
        toolbar.classList.add('d-none');
        toolbar.style.setProperty('display', 'none', 'important');
    }

    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

function deselectAll() {
    selectedTestCases.clear();
    document.querySelectorAll('.test-case-checkbox').forEach(cb => cb.checked = false);
    const globalSelectAll = document.getElementById('selectAllCheckbox');
    if (globalSelectAll) globalSelectAll.checked = false;
    updateBatchToolbar();
    lastCaseCheckboxIndex = null;
}

// 批次修改相關函數
function openTestCaseBatchModifyModal() {
    if (selectedTestCases.size === 0) {
        const msg = window.i18n ? window.i18n.t('errors.pleaseSelectForModify') : '請先選擇要修改的測試案例';
        AppUtils.showError(msg);
        return;
    }

    // 更新選中項目數量顯示
    document.getElementById('testCaseBatchModifyCount').textContent = selectedTestCases.size;

    // 重置表單
    document.getElementById('batchModifyTCG').checked = false;
    document.getElementById('batchTCGInput').value = '';
    document.getElementById('batchModifyPriority').checked = false;
    document.getElementById('batchPrioritySelect').value = '';
    document.getElementById('batchPrioritySelect').disabled = true;
    const batchModifySectionCheckbox = document.getElementById('batchModifySection');
    const batchSectionSelect = document.getElementById('batchSectionSelect');
    if (batchModifySectionCheckbox) batchModifySectionCheckbox.checked = false;
    if (batchSectionSelect) {
        batchSectionSelect.value = '';
        batchSectionSelect.disabled = true;
        populateBatchSectionSelect();
    }
    const batchModifyTestSetCheckbox = document.getElementById('batchModifyTestSet');
    const batchTestSetSelect = document.getElementById('batchTestSetSelect');
    if (batchModifyTestSetCheckbox) batchModifyTestSetCheckbox.checked = false;
    if (batchTestSetSelect) {
        batchTestSetSelect.value = '';
        batchTestSetSelect.disabled = true;
    }

    // 初始化批次 TCG 編輯器
    initializeBatchTCGEditor();

    // 顯示模態框
    const modal = new bootstrap.Modal(document.getElementById('testCaseBatchModifyModal'));
    modal.show();

    // 模態框顯示後確保 TCG 容器正確顯示
    setTimeout(() => {
        const container = document.getElementById('batchTCGContainer');
        if (container) {
            container.style.border = '1px solid #ced4da';
            container.style.borderRadius = '0.375rem';
            container.style.padding = '0.375rem';
            container.style.backgroundColor = '#ffffff';
            container.style.cursor = 'pointer';
            container.setAttribute('title', '點擊編輯 TCG 單號');

            // 新增一個提示文字當沒有選擇時
            if (batchTCGSelected.length === 0) {
                container.innerHTML = '<span class="text-muted small">點擊此處填寫 TCG 單號...</span>';
            }

            // **關鍵修正**：重新綁定點擊事件，因為 innerHTML 會清除事件監聽器
            container.removeEventListener('click', openBatchTCGEditor); // 移除舊的（如果有）
            container.addEventListener('click', openBatchTCGEditor); // 重新綁定
        }

        // 綁定模態框關閉事件
        const modal = document.getElementById('testCaseBatchModifyModal');
        if (modal) {
            modal.addEventListener('hidden.bs.modal', function() {
                // 清理 TCG 編輯器狀態
                if (batchTCGEditing) {
                    finishBatchTCGEdit();
                }
                // 隱藏下拉選單
                const dropdown = document.getElementById('batchTCGDropdown');
                if (dropdown) {
                    dropdown.style.display = 'none';
                }
            }, { once: true });
        }
    }, 100);
}

// NOTE: batchTCGSearchTimeout, batchTCGEditing, batchTCGSelected 已統一定義於 Section 2

// 初始化批次 TCG 編輯器
function initializeBatchTCGEditor() {
    console.log('Initializing batch TCG editor...'); // 調試用
    // 重置狀態
    batchTCGSelected = [];
    batchTCGEditing = false;

    // 清理任何存在的監聽器
    document.removeEventListener('click', handleBatchTCGOutsideClick, true);

    // 重置顯示
    renderBatchTCGDisplay();

    // 確保點擊事件正確綁定
    const container = document.getElementById('batchTCGContainer');
    if (container) {
        container.removeEventListener('click', openBatchTCGEditor);
        container.addEventListener('click', openBatchTCGEditor);
        console.log('Batch TCG container click event bound'); // 調試用
    } else {
        console.error('Batch TCG container not found!'); // 調試用
    }
}

function renderBatchTCGDisplay() {
    const container = document.getElementById('batchTCGContainer');
    if (!container) return;

    if (!Array.isArray(batchTCGSelected) || batchTCGSelected.length === 0) {
        // 顯示提示文字當沒有選擇時
        container.innerHTML = '<span class="text-muted small">點擊此處填寫 TCG 單號...</span>';
        // 重新綁定點擊事件（因為 innerHTML 會清除事件）
        container.removeEventListener('click', openBatchTCGEditor);
        container.addEventListener('click', openBatchTCGEditor);
        return;
    }

    const tags = batchTCGSelected.map(t => `<span class="tcg-tag">${t}</span>`).join(' ');
    container.innerHTML = tags;
    // 重新綁定點擊事件（因為 innerHTML 會清除事件）
    container.removeEventListener('click', openBatchTCGEditor);
    container.addEventListener('click', openBatchTCGEditor);
}

function openBatchTCGEditor() {
    console.log('openBatchTCGEditor called');
    const container = document.getElementById('batchTCGContainer');
    if (!container) {
        console.error('Batch TCG container not found!');
        return;
    }
    if (batchTCGEditing) {
        console.log('Already editing, skipping...');
        return;
    }
    batchTCGEditing = true;

    // 簡化為文字輸入 - 逗號分隔的單號
    const searchHtml = `
        <div class="tcg-search-container position-relative" style="min-height: 32px; height: 32px; display: flex; align-items: center; overflow: hidden;">
            <input type="text" class="form-control form-control-sm tcg-search-input"
                   placeholder="輸入 TCG 單號（逗號分隔）" autocomplete="off"
                   onkeydown="handleBatchTCGSearchKeydown(event)"
                   onclick="event.stopPropagation()"
                   style="height: 28px; width: 100%; font-size: 0.75rem; padding: 0.125rem 0.375rem; border: 1px solid #dee2e6; box-shadow: none; outline: none;">
        </div>`;
    container.innerHTML = searchHtml;
    const input = container.querySelector('.tcg-search-input');
    input.value = batchTCGSelected.join(', ');
    input.focus();
    input.select();

    // 監聽外部點擊以結束編輯
    setTimeout(() => { document.addEventListener('click', handleBatchTCGOutsideClick, true); }, 50);
}


function handleBatchTCGOutsideClick(e) {
    const container = document.getElementById('batchTCGContainer');
    if (!container) return;
    const insideContainer = container.contains(e.target);
    if (!insideContainer) {
        // 點擊在外部：結束編輯
        finishBatchTCGEdit();
    }
}

function finishBatchTCGEdit() {
    document.removeEventListener('click', handleBatchTCGOutsideClick, true);
    batchTCGEditing = false;

    // 從輸入框讀取值並解析
    const container = document.getElementById('batchTCGContainer');
    const input = container?.querySelector('.tcg-search-input');
    if (input) {
        const inputValue = input.value.trim();
        if (inputValue) {
            // 解析逗號分隔的 TCG 單號
            batchTCGSelected = inputValue
                .split(',')
                .map(t => t.trim())
                .filter(t => t);
        } else {
            batchTCGSelected = [];
        }
    }

    // 回寫隱藏 input 值
    const hidden = document.getElementById('batchTCGInput');
    if (hidden) hidden.value = batchTCGSelected.join(', ');

    renderBatchTCGDisplay();
}

function handleBatchTCGSearchKeydown(event) {
    if (event.key === 'Enter') {
        event.preventDefault();
        finishBatchTCGEdit();
    } else if (event.key === 'Escape') {
        event.preventDefault();
        // 取消變更
        finishBatchTCGEdit();
    }
}

// 立即更新本地測試案例資料
function updateLocalTestCasesAfterBatchModify(selectedIds, updateData) {
    // 記錄被修改的舊 section ID
    const affectedSectionIds = new Set();

    // 更新本地 testCases 陣列
    testCases.forEach(testCase => {
        if (selectedIds.includes(testCase.record_id)) {
            // 更新 TCG
            if (updateData.tcg !== undefined) {
                if (updateData.tcg === '') {
                    // 清空 TCG
                    testCase.tcg = [];
                } else if (Array.isArray(updateData.tcg)) {
                    testCase.tcg = updateData.tcg.map(n => ({ text: n, text_arr: [n], display_text: n, type: 'text' }));
                } else {
                    // 單一值
                    testCase.tcg = [{ text: updateData.tcg, text_arr: [updateData.tcg], display_text: updateData.tcg, type: 'text' }];
                }
            }

            // 更新優先級
            if (updateData.priority !== undefined) {
                testCase.priority = updateData.priority;
            }

            // 更新區段
            if (updateData.section) {
                // 記錄舊的 section ID，用於更新計數
                if (testCase.test_case_section_id) {
                    affectedSectionIds.add(testCase.test_case_section_id);
                }
                testCase.test_case_section_id = updateData.section.id;
                testCase.section_name = updateData.section.name;
                testCase.section_path = updateData.section.path;
                testCase.section_level = updateData.section.level;
                // 新的 section 也需要更新計數
                affectedSectionIds.add(updateData.section.id);
            }

            // 更新 Test Set（移動後 section 由後端重設為 Unassigned）
            if (updateData.test_set_id !== undefined) {
                if (testCase.test_case_section_id) {
                    affectedSectionIds.add(testCase.test_case_section_id);
                }
                testCase.test_case_set_id = updateData.test_set_id;
                testCase.test_case_section_id = null;
                testCase.section_name = null;
                testCase.section_path = null;
                testCase.section_level = null;
            }
        }
    });

    // 更新篩選後的陣列
    filteredTestCases.forEach(testCase => {
        if (selectedIds.includes(testCase.record_id)) {
            // 更新 TCG
            if (updateData.tcg !== undefined) {
                if (updateData.tcg === '') {
                    testCase.tcg = [];
                } else if (Array.isArray(updateData.tcg)) {
                    testCase.tcg = updateData.tcg.map(n => ({ text: n, text_arr: [n], display_text: n, type: 'text' }));
                } else {
                    testCase.tcg = [{ text: updateData.tcg, text_arr: [updateData.tcg], display_text: updateData.tcg, type: 'text' }];
                }
            }

            // 更新優先級
            if (updateData.priority !== undefined) {
                testCase.priority = updateData.priority;
            }

            if (updateData.section) {
                testCase.test_case_section_id = updateData.section.id;
                testCase.section_name = updateData.section.name;
                testCase.section_path = updateData.section.path;
                testCase.section_level = updateData.section.level;
            }

            if (updateData.test_set_id !== undefined) {
                testCase.test_case_set_id = updateData.test_set_id;
                testCase.test_case_section_id = null;
                testCase.section_name = null;
                testCase.section_path = null;
                testCase.section_level = null;
            }
        }
    });

    // 更新受影響的 section 計數
    if (updateData.section && testCaseSectionList && testCaseSectionList.sections) {
        affectedSectionIds.forEach(sectionId => {
            // 遞迴查找和更新 section 計數
            const updateSectionCount = (sections) => {
                for (const section of sections) {
                    if (section.id === sectionId) {
                        // 計算該 section 中現在有多少個測試案例
                        const count = testCases.filter(tc => tc.test_case_section_id === sectionId).length;
                        section.test_case_count = count;
                        return true;
                    }
                    if (section.children && section.children.length > 0) {
                        if (updateSectionCount(section.children)) {
                            return true;
                        }
                    }
                }
                return false;
            };
            updateSectionCount(testCaseSectionList.sections);
        });

        // 重新渲染 section list 以更新計數顯示
        testCaseSectionList.render();
    }

    // 立即依目前過濾器重新渲染
    applyCurrentFiltersAndRender();
}

/**
 * 填充批次設定 Test Set 的下拉選單
 * @param {number} teamId - 當前團隊 ID
 */
async function populateBatchTestSetSelect(teamId) {
    const select = document.getElementById('batchTestSetSelect');
    if (!select) return;

    try {
        // 獲取當前團隊的所有 Test Sets
        const response = await window.AuthClient.fetch(`/api/teams/${teamId}/test-case-sets`);
        if (!response.ok) {
            const msg = window.i18n ? window.i18n.t('errors.failedToLoadTestSets', {}, '無法載入 Test Sets') : '無法載入 Test Sets';
            AppUtils.showError(msg);
            select.disabled = true;
            return;
        }

        const testSets = await response.json();
        if (!Array.isArray(testSets) || testSets.length === 0) {
            const msg = window.i18n ? window.i18n.t('errors.noTestSets', {}, '此團隊沒有 Test Sets') : '此團隊沒有 Test Sets';
            select.innerHTML = `<option value="" disabled>${msg}</option>`;
            select.disabled = true;
            return;
        }

        // 只排除當前 Set（如果有指定的話）
        const filteredSets = currentSetId ? testSets.filter(s => s.id !== currentSetId) : testSets;

        const defaultOption = '<option value="" data-i18n="testCase.selectTestSet" data-i18n-fallback="請選擇 Test Set">請選擇 Test Set</option>';
        const optionsHtml = filteredSets.map(set =>
            `<option value="${set.id}">${set.name} (${set.test_case_count || 0})</option>`
        ).join('');

        select.innerHTML = defaultOption + optionsHtml;
        select.value = '';
        select.disabled = false;

        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(select);
        }
    } catch (error) {
        console.error('Error populating test sets:', error);
        const msg = window.i18n ? window.i18n.t('errors.failedToLoadTestSets', {}, '無法載入 Test Sets') : '無法載入 Test Sets';
        AppUtils.showError(msg);
        select.disabled = true;
    }
}

function buildMoveImpactWarningMessage(preview) {
    const impactedCount = Number(preview?.impacted_item_count || 0);
    const impactedRuns = Array.isArray(preview?.impacted_test_runs) ? preview.impacted_test_runs : [];
    if (!impactedCount || impactedRuns.length === 0) {
        return '';
    }

    const title = window.i18n
        ? window.i18n.t(
            'testCase.moveSetImpactWarning',
            { impacted_count: impactedCount },
            `此操作會影響 ${impactedCount} 筆 Test Run 項目。`
        )
        : `此操作會影響 ${impactedCount} 筆 Test Run 項目。`;
    const confirmHint = window.i18n
        ? window.i18n.t('testCase.moveSetImpactConfirmHint', {}, '是否確認繼續移動？')
        : '是否確認繼續移動？';

    const topRuns = impactedRuns.slice(0, 10).map((run, idx) => {
        const runName = run.config_name || `Test Run #${run.config_id}`;
        const removedCount = Number(run.removed_item_count || 0);
        return `${idx + 1}. ${runName}（${removedCount}）`;
    });
    if (impactedRuns.length > 10) {
        topRuns.push(`...還有 ${impactedRuns.length - 10} 個 Test Run`);
    }

    return `${title}\n\n${topRuns.join('\n')}\n\n${confirmHint}`;
}

async function fetchMoveImpactPreview(teamId, recordIds, targetSetId) {
    const previewResp = await window.AuthClient.fetch(`/api/teams/${teamId}/testcases/impact-preview/move-test-set`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            record_ids: recordIds,
            target_test_set_id: targetSetId,
        }),
    });

    if (!previewResp.ok) {
        const errorData = await previewResp.json().catch(() => ({}));
        const detail = errorData?.detail || '無法取得影響預覽';
        throw new Error(detail);
    }
    return await previewResp.json();
}

async function performTestCaseBatchModify() {
    const modifyTCG = document.getElementById('batchModifyTCG').checked;
    const modifyPriority = document.getElementById('batchModifyPriority').checked;
    const modifySection = document.getElementById('batchModifySection').checked;
    const modifyTestSet = document.getElementById('batchModifyTestSet').checked;

    if (!modifyTCG && !modifyPriority && !modifySection && !modifyTestSet) {
        const msg = window.i18n ? window.i18n.t('errors.selectModifyFields') : '請至少選擇一個要修改的欄位';
        AppUtils.showError(msg);
        return;
    }

    // 檢查區段和 Test Set 互斥性
    if (modifySection && modifyTestSet) {
        const msg = window.i18n ? window.i18n.t('errors.sectionAndTestSetMutuallyExclusive', {}, '區段設定和 Test Set 設定不可同時使用') : '區段設定和 Test Set 設定不可同時使用';
        AppUtils.showError(msg);
        return;
    }

    const selectedIds = Array.from(selectedTestCases);
    const updateData = {};
    let sectionIdForBatch = null;
    let testSetIdForBatch = null;

    // 收集要修改的資料
    if (modifyTCG) {
        const raw = document.getElementById('batchTCGInput').value || '';
        const parts = raw.replace(/\n/g, ',').replace(/\s+/g, ',').split(',').map(s => s.trim()).filter(Boolean);
        if (parts.length === 0) {
            updateData.tcg = '';
        } else if (parts.length === 1) {
            updateData.tcg = parts[0];
        } else {
            updateData.tcg = parts;
        }
    }

    if (modifyPriority) {
        const priorityValue = document.getElementById('batchPrioritySelect').value;
        if (!priorityValue) {
            const msg = window.i18n ? window.i18n.t('errors.selectPriorityValue') : '請選擇優先級';
            AppUtils.showError(msg);
            return;
        }
        updateData.priority = priorityValue;
    }

    if (modifySection) {
        const sectionSelect = document.getElementById('batchSectionSelect');
        const sectionValue = sectionSelect ? sectionSelect.value : '';
        if (!sectionValue) {
            const msg = window.i18n ? window.i18n.t('errors.selectSectionValue', {}, '請選擇區段') : '請選擇區段';
            AppUtils.showError(msg);
            return;
        }
        const sectionMeta = getSectionMetaByValue(sectionValue);
        if (!sectionMeta || sectionMeta.id === undefined || sectionMeta.id === null) {
            const msg = window.i18n ? window.i18n.t('errors.invalidSection', {}, '區段資訊無效，請重新載入') : '區段資訊無效，請重新載入';
            AppUtils.showError(msg);
            return;
        }
        const parsedSectionId = Number(sectionMeta.id);
        if (!Number.isFinite(parsedSectionId)) {
            const msg = window.i18n ? window.i18n.t('errors.invalidSection', {}, '區段資訊無效，請重新載入') : '區段資訊無效，請重新載入';
            AppUtils.showError(msg);
            return;
        }
        sectionIdForBatch = parsedSectionId;
        updateData.section = {
            id: sectionMeta.id,
            name: sectionMeta.name || '',
            path: sectionMeta.path || sectionMeta.name || '',
            level: sectionMeta.level || 1,
        };
    }

    if (modifyTestSet) {
        const testSetSelect = document.getElementById('batchTestSetSelect');
        const testSetValue = testSetSelect ? testSetSelect.value : '';
        if (!testSetValue) {
            const msg = window.i18n ? window.i18n.t('errors.selectTestSetValue', {}, '請選擇 Test Set') : '請選擇 Test Set';
            AppUtils.showError(msg);
            return;
        }
        const parsedTestSetId = Number(testSetValue);
        if (!Number.isFinite(parsedTestSetId)) {
            const msg = window.i18n ? window.i18n.t('errors.invalidTestSet', {}, 'Test Set 資訊無效') : 'Test Set 資訊無效';
            AppUtils.showError(msg);
            return;
        }
        testSetIdForBatch = parsedTestSetId;
        updateData.test_set_id = testSetIdForBatch;
    }

    try {
        // 獲取當前團隊
        const currentTeam = AppUtils.getCurrentTeam();
        if (!currentTeam || !currentTeam.id) {
            const msg = window.i18n ? window.i18n.t('errors.pleaseSelectTeam') : '請先選擇團隊';
            AppUtils.showError(msg);
            return;
        }

        let batchCleanupSummary = null;
        if (modifyTestSet && testSetIdForBatch !== null) {
            const preview = await fetchMoveImpactPreview(currentTeam.id, selectedIds, testSetIdForBatch);
            const warningMessage = buildMoveImpactWarningMessage(preview);
            if (warningMessage) {
                const confirmed = await AppUtils.showConfirm(warningMessage);
                if (!confirmed) {
                    return;
                }
            }
        }

        // 顯示載入狀態
        const confirmBtn = document.getElementById('confirmTestCaseBatchModifyBtn');
        const originalBtnText = confirmBtn.innerHTML;
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>修改中...';

        // 呼叫後端 API - 需要先擴展 API 支援更多欄位
        let success = true;
        let errorMessages = [];

        // 分別處理 TCG 和 Priority（因為現有 API 只支援個別處理）
        if (modifyTCG) {
            const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/batch`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    operation: 'update_tcg',
                    record_ids: selectedIds,
                    update_data: { tcg: updateData.tcg }
                })
            });

            const result = await response.json();
            if (!result.success) {
                success = false;
                errorMessages.push(...(result.error_messages || ['TCG 更新失敗']));
            }
        }

        if (modifyPriority) {
            const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/batch`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    operation: 'update_priority',
                    record_ids: selectedIds,
                    update_data: { priority: updateData.priority }
                })
            });

            const result = await response.json();
            if (!result.success) {
                success = false;
                errorMessages.push(...(result.error_messages || ['優先級更新失敗']));
            }
        }

        if (modifySection && sectionIdForBatch !== null) {
            const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/batch`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    operation: 'update_section',
                    record_ids: selectedIds,
                    update_data: { section_id: sectionIdForBatch },
                }),
            });

            const result = await response.json();
            if (!result.success) {
                success = false;
                errorMessages.push(...(result.error_messages || ['區段更新失敗']));
            }
        }

        if (modifyTestSet && testSetIdForBatch !== null) {
            const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/batch`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    operation: 'update_test_set',
                    record_ids: selectedIds,
                    update_data: { test_set_id: testSetIdForBatch },
                }),
            });

            const result = await response.json();
            if (!result.success) {
                success = false;
                errorMessages.push(...(result.error_messages || ['Test Set 更新失敗']));
            } else if (result.cleanup_summary) {
                batchCleanupSummary = result.cleanup_summary;
            }
        }

        // 恢復按鈕狀態
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = originalBtnText;

        if (success) {
            // 關閉模態框
            const modal = bootstrap.Modal.getInstance(document.getElementById('testCaseBatchModifyModal'));
            if (modal) modal.hide();

            // 立即更新本地資料顯示（不顯示載入動畫）
            updateLocalTestCasesAfterBatchModify(selectedIds, updateData);

            // 清除選擇
            deselectAll();

            let successMsg = window.i18n ?
                window.i18n.t('messages.batchModifySuccess', { count: selectedIds.length }) :
                `成功修改 ${selectedIds.length} 個測試案例`;
            const removedItemCount = Number(batchCleanupSummary?.removed_item_count || 0);
            if (removedItemCount > 0) {
                const impactedRunCount = Array.isArray(batchCleanupSummary?.impacted_test_runs)
                    ? batchCleanupSummary.impacted_test_runs.length
                    : 0;
                successMsg += `；影響 ${impactedRunCount} 個 Test Run，移除 ${removedItemCount} 筆項目`;
            }
            AppUtils.showSuccess(successMsg);

            // 背景重新同步資料（強制刷新快取）
            setTimeout(async () => {
                try {
                    clearTestCasesCache(); // 清除快取確保資料同步
                    await loadTestCases(false, null, true); // 強制從伺服器重新載入

                    // 如果修改了 Test Set 或 Section，需要刷新 Section List 以更新 test case 計數
                    if ((modifyTestSet || modifySection) && typeof window.testCaseSectionList !== 'undefined' && window.testCaseSectionList?.loadSections) {
                        console.log('[TCM] Refreshing section list after batch modify (test set or section changed)');
                        try {
                            await window.testCaseSectionList.loadSections({ reloadTestCases: false });
                        } catch (error) {
                            console.warn('刷新 Section List 失敗:', error);
                        }
                    }
                } catch (error) {
                    console.warn('背景同步資料失敗:', error);
                }
            }, 1000);

        } else {
            const errorMsg = window.i18n ? window.i18n.t('errors.batchModifyFailed') : '批次修改失敗';
            AppUtils.showError(errorMsg + ': ' + errorMessages.join(', '));
        }

    } catch (error) {
        console.error('批次修改錯誤:', error);

        // 恢復按鈕狀態
        const confirmBtn = document.getElementById('confirmTestCaseBatchModifyBtn');
        confirmBtn.disabled = false;
        confirmBtn.innerHTML = '<i class="fas fa-edit me-2"></i><span data-i18n="testCase.confirmModify">確認修改</span>';

        // 重新應用翻譯到按鈕內容
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(confirmBtn);
        }

        const errorMsg = window.i18n ? window.i18n.t('errors.batchModifyFailed') : '批次修改失敗';
        AppUtils.showError(errorMsg + ': ' + error.message);
    }
}

function batchDeleteTestCases() {
    if (selectedTestCases.size === 0) {
        showError(window.i18n ? window.i18n.t('errors.pleaseSelectForDelete') : '請先選擇要刪除的測試案例');
        return;
    }

    // 獲取選中的測試案例
    const selectedIds = Array.from(selectedTestCases);
    const selectedCases = testCases.filter(tc => selectedIds.includes(tc.record_id));

    // 設置批次刪除確認 Modal 的內容
    const deleteList = document.getElementById('deleteList');
    deleteList.innerHTML = `
        <div class="mb-3">
            <p class="mb-2">確定要刪除以下 ${selectedCases.length} 個測試案例嗎？</p>
            <div class="border rounded p-3 bg-light" style="max-height: 300px; overflow-y: auto;">
                ${selectedCases.map(tc => `
                    <div class="mb-2">
                        <strong class="text-primary">${tc.test_case_number || tc.record_id}: ${tc.title}</strong>
                    </div>
                `).join('')}
            </div>
        </div>
    `;

    // 顯示刪除確認 Modal
    const deleteModal = new bootstrap.Modal(document.getElementById('deleteConfirmModal'));
    deleteModal.show();

    // 設置確認刪除的處理
    document.getElementById('confirmDeleteBtn').onclick = async function() {
        try {
            // 獲取當前團隊
            const currentTeam = AppUtils.getCurrentTeam();
            if (!currentTeam || !currentTeam.id) {
                throw new Error('請先選擇團隊');
            }

            // 發送批次刪除請求
            const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/batch`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    operation: 'delete',
                    record_ids: selectedIds
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '批次刪除失敗');
            }

            // 關閉 Modal
            deleteModal.hide();

            // 清除選擇
            deselectAll();

            // 從本地陣列移除已刪除的項目（背景處理，不顯示載入動畫）
            const deletedIds = Array.from(selectedIds);
            testCases = testCases.filter(tc => !deletedIds.includes(tc.record_id));
            filteredTestCases = filteredTestCases.filter(tc => !deletedIds.includes(tc.record_id));

            // 重新渲染表格和分頁
            renderTestCasesTable();
            updatePagination();

            // 用 toast 通知成功
            const batchDeleteMessage = window.i18n ?
                window.i18n.t('messages.batchDeleteSuccess', {count: selectedCases.length}) :
                `成功刪除 ${selectedCases.length} 個測試案例`;
            AppUtils.showSuccess(batchDeleteMessage);

        } catch (error) {
            console.error('批次刪除測試案例失敗:', error);
            const batchDeleteFailedMessage = window.i18n ? window.i18n.t('errors.batchDeleteFailed') : '批次刪除失敗';
            showError(batchDeleteFailedMessage + '：' + error.message);
        }
    };
}

function showLoadingState() {
    const stack = document.getElementById('testCasesStack');
    if (!stack) return;
    stack.innerHTML = `
        <div class="text-center py-4">
            <div class="spinner-border text-primary" role="status" style="width: 2.5rem; height: 2.5rem;">
                <span class="visually-hidden">載入中...</span>
            </div>
            <div class="mt-2 text-muted fs-6">載入測試案例中...</div>
        </div>
    `;
}

function hideLoadingState() {
    // hideLoadingState 現在由 renderTestCasesTable 來處理
}

function ensurePaginationControls() {
    const cardBody = document.querySelector('#testCasesCard .card-body');
    if (!cardBody) return null;
    let controls = document.getElementById('testCasesPagination');
    if (!controls) {
        controls = document.createElement('div');
        controls.id = 'testCasesPagination';
        controls.className = 'd-flex align-items-center justify-content-between mt-2 flex-wrap gap-2';
        controls.innerHTML = `
            <div id="tcmPageInfo" class="text-muted small"></div>
            <div class="d-flex gap-2">
                <button class="btn btn-outline-secondary btn-sm" id="tcmPrevPageBtn" type="button">
                    <i class="fas fa-chevron-left"></i>
                </button>
                <button class="btn btn-outline-secondary btn-sm" id="tcmNextPageBtn" type="button">
                    <i class="fas fa-chevron-right"></i>
                </button>
            </div>
        `;
        cardBody.appendChild(controls);
        const prevBtn = controls.querySelector('#tcmPrevPageBtn');
        const nextBtn = controls.querySelector('#tcmNextPageBtn');
        if (prevBtn) {
            prevBtn.addEventListener('click', () => {
                if (currentPage > 1) {
                    currentPage -= 1;
                    renderTestCasesTable();
                    updatePagination();
                }
            });
        }
        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                const total = filteredTestCases.length;
                const totalPages = Math.max(1, Math.ceil(total / pageSize));
                if (currentPage < totalPages) {
                    currentPage += 1;
                    renderTestCasesTable();
                    updatePagination();
                }
            });
        }
    }
    return controls;
}

// ===== Test Data 管理功能 =====
let currentTestData = [];

function renderTestDataList() {
    const container = document.getElementById('testDataList');
    if (!container) return;

    if (!currentTestData || currentTestData.length === 0) {
        container.innerHTML = '<p class="text-muted small mb-0"><i class="fas fa-info-circle me-1"></i><span data-i18n="form.noTestData">尚無 Test Data</span></p>';
        return;
    }

    container.innerHTML = currentTestData.map((td, idx) => `
        <div class="d-flex align-items-center gap-2 mb-2 test-data-item" data-idx="${idx}">
            <input type="text" class="form-control form-control-sm test-data-name"
                   placeholder="Name" value="${escapeHtml(td.name || '')}" style="flex: 1;">
            <input type="text" class="form-control form-control-sm test-data-value"
                   placeholder="Value" value="${escapeHtml(td.value || '')}" style="flex: 2;">
            <button type="button" class="btn btn-sm btn-outline-danger remove-test-data-btn" data-idx="${idx}">
                <i class="fas fa-trash-alt"></i>
            </button>
        </div>
    `).join('');

    // 綁定變更事件
    container.querySelectorAll('.test-data-name, .test-data-value').forEach(input => {
        input.addEventListener('change', updateTestDataFromDOM);
        input.addEventListener('input', updateTestDataFromDOM);
    });

    // 綁定刪除事件
    container.querySelectorAll('.remove-test-data-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const idx = parseInt(e.currentTarget.dataset.idx);
            currentTestData.splice(idx, 1);
            renderTestDataList();
            isFormChanged = true;
        });
    });
}

function updateTestDataFromDOM() {
    const container = document.getElementById('testDataList');
    if (!container) return;

    const items = container.querySelectorAll('.test-data-item');
    items.forEach((item, idx) => {
        if (currentTestData[idx]) {
            currentTestData[idx].name = item.querySelector('.test-data-name').value;
            currentTestData[idx].value = item.querySelector('.test-data-value').value;
        }
    });
    isFormChanged = true;
}

function addTestData() {
    currentTestData.push({
        id: crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(),
        name: '',
        value: ''
    });
    renderTestDataList();
    isFormChanged = true;

    // 聚焦到新項目的 name 輸入框
    const container = document.getElementById('testDataList');
    if (container) {
        const lastItem = container.querySelector('.test-data-item:last-child');
        if (lastItem) {
            const nameInput = lastItem.querySelector('.test-data-name');
            if (nameInput) nameInput.focus();
        }
    }
}

// 初始化 Test Data 新增按鈕事件
document.addEventListener('DOMContentLoaded', function() {
    const addBtn = document.getElementById('addTestDataBtn');
    if (addBtn) {
        addBtn.addEventListener('click', addTestData);
    }
});

function updatePagination() {
    // 分頁控制已停用；僅重新計算列表高度
    if (typeof adjustTestCasesScrollHeight === 'function') {
        adjustTestCasesScrollHeight();
    }
}
