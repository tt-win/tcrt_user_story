/* ============================================================
   TEST CASE MANAGEMENT - ATTACHMENTS
   ============================================================ */

/* ============================================================
   19. 附件處理 (Attachments)
   ============================================================ */

// NOTE: uploadedAttachments, currentTempUploadId 已統一定義於 Section 2

/**
 * 處理附件上傳
 */
function handleAttachmentUpload(event) {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    // 驗證檔案
    for (let file of files) {
        if (file.size > 10 * 1024 * 1024) { // 10MB 限制
            const errorMessage = window.i18n ?
                window.i18n.t('errors.fileSizeLimitExceeded', {fileName: file.name}, `檔案 "${file.name}" 超過10MB大小限制`) :
                `檔案 "${file.name}" 超過10MB大小限制`;
            showError(errorMessage);
            return;
        }
    }

    // 顯示上傳中狀態
    const attachmentsList = document.getElementById('attachmentsList');
    const uploadingHtml = Array.from(files).map(file => `
        <div class="attachment-item d-flex align-items-center justify-content-between p-2 border rounded mb-2">
            <div class="d-flex align-items-center">
                <i class="fas fa-file me-2 text-muted"></i>
                <span>${file.name}</span>
                <small class="text-muted ms-2">(${formatFileSize(file.size)})</small>
            </div>
            <div class="spinner-border spinner-border-sm text-primary" role="status">
                <span class="visually-hidden">上傳中...</span>
            </div>
        </div>
    `).join('');

    attachmentsList.innerHTML = uploadingHtml;

    // 實際上傳檔案到伺服器
    uploadFilesToServer(Array.from(files));
}

async function uploadFilesToServer(files) {
    const currentTeam = AppUtils.getCurrentTeam();
    if (!currentTeam || !currentTeam.id) {
        showError(window.i18n ? window.i18n.t('errors.pleaseSelectTeam') : '請先選擇團隊');
        return;
    }

    const attachmentsList = document.getElementById('attachmentsList');
    const uploadedFiles = [];
    let totalFiles = files.length;
    let completedFiles = 0;

    try {
        // 顯示上傳進度區域
        attachmentsList.innerHTML = `
            <div class="upload-progress-container mb-3 p-3 border rounded bg-light">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <span class="fw-medium">正在上傳附件...</span>
                    <span class="text-muted">${completedFiles}/${totalFiles}</span>
                </div>
                <div class="progress">
                    <div class="progress-bar" role="progressbar" style="width: 0%"></div>
                </div>
                <div class="mt-2">
                    <small class="text-muted">請稍等，正在處理您的檔案</small>
                </div>
            </div>
        `;

        const progressBar = attachmentsList.querySelector('.progress-bar');
        const progressText = attachmentsList.querySelector('span.text-muted');

        const isEditingExisting = !!(document.getElementById('testCaseId') && document.getElementById('testCaseId').value);
        const rid = getCurrentRecordId();
        const tcNumberEl2 = document.getElementById('testCaseNumber');
        const tcn = tcNumberEl2 && tcNumberEl2.value ? tcNumberEl2.value.trim() : '';

        if (isEditingExisting) {
            // 舊邏輯：已存在的記錄，直接附加到該記錄
            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                const statusText = attachmentsList.querySelector('.mt-2 small');
                const uploadingMessage = window.i18n ? window.i18n.t('messages.uploadingFile') : '正在上傳';
                statusText.textContent = `${uploadingMessage}: ${file.name}`;
                try {
                    const currentRecordKey = getCurrentRecordKeyForUpload();
                    if (!currentRecordKey) throw new Error('請先填寫 Test Case Number 再上傳附件');
                    const fd = new FormData();
                    fd.append('files', file);
                    const isNumericId = /^\d+$/.test(String(currentRecordKey));
                    const url = isNumericId
                        ? `/api/teams/${currentTeam.id}/testcases/${encodeURIComponent(currentRecordKey)}/attachments`
                        : `/api/teams/${currentTeam.id}/testcases/by-number/${encodeURIComponent(currentRecordKey)}/attachments`;
                    const response = await window.AuthClient.fetch(url, { method: 'POST', body: fd });
                    if (response.ok) {
                        const result = await response.json();
                        const statusText = attachmentsList.querySelector('.mt-2 small');
                        const attachingMessage = window.i18n ? window.i18n.t('messages.attachingFile') : '正在附加';
                        statusText.textContent = `${attachingMessage}: ${file.name}`;
                        const meta = Array.isArray(result.files) ? result.files.find(m => m.name === file.name || (m.stored_name && m.stored_name.includes(file.name))) : null;
                        const metaEntry = meta || { name: file.name, size: file.size, type: file.type || 'application/octet-stream' };
                        uploadedFiles.push(metaEntry);
                        let testCaseIndex = -1;
                        if (rid) testCaseIndex = testCases.findIndex(tc => tc.record_id === rid);
                        if (testCaseIndex === -1 && tcn) testCaseIndex = testCases.findIndex(tc => tc.test_case_number === tcn);
                        if (testCaseIndex !== -1) {
                            if (!testCases[testCaseIndex].attachments) testCases[testCaseIndex].attachments = [];
                            testCases[testCaseIndex].attachments.push(metaEntry);
                        }
                        let filteredIndex = -1;
                        if (rid) filteredIndex = filteredTestCases.findIndex(tc => tc.record_id === rid);
                        if (filteredIndex === -1 && tcn) filteredIndex = filteredTestCases.findIndex(tc => tc.test_case_number === tcn);
                        if (filteredIndex !== -1) {
                            if (!filteredTestCases[filteredIndex].attachments) filteredTestCases[filteredIndex].attachments = [];
                            filteredTestCases[filteredIndex].attachments.push(metaEntry);
                        }
                        completedFiles++;
                        const progress = (completedFiles / totalFiles) * 100;
                        if (progressBar) progressBar.style.width = progress + '%';
                        if (progressText) progressText.textContent = `${completedFiles}/${totalFiles}`;
                    } else {
                        let errorText = '上傳失敗';
                        try { const err = await response.json(); errorText = err.detail || errorText; } catch (_e) {}
                        throw new Error(`${errorText}`);
                    }
                } catch (fileError) {
                    console.error(`上傳檔案 ${file.name} 失敗:`, fileError);
                    const uploadFailedMessage = window.i18n ? window.i18n.t('errors.uploadFailed') : '上傳失敗';
                    showError(`${uploadFailedMessage} "${file.name}": ${fileError.message}`);
                }
            }
        } else {
            // 新邏輯：新增模式，先暫存上傳，待建立/更新成功後由後端搬移到正式位置
            const fd = new FormData();
            for (let i = 0; i < files.length; i++) {
                fd.append('files', files[i]);
            }
            if (currentTempUploadId) fd.append('temp_upload_id', currentTempUploadId);
            const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/staging/upload`, { method: 'POST', body: fd });
            if (!response.ok) {
                let errorText = '上傳失敗';
                try { const err = await response.json(); errorText = err.detail || errorText; } catch (_e) {}
                throw new Error(errorText);
            }
            const result = await response.json();
            currentTempUploadId = result.temp_upload_id || currentTempUploadId;
            const newFiles = Array.isArray(result.files) ? result.files.map(m => ({
                name: m.name,
                stored_name: m.stored_name || m.name,
                size: m.size || 0,
                type: m.type || 'application/octet-stream',
                url: m.url || m.tmp_url || '',
            })) : [];
            uploadedFiles.push(...newFiles);
            completedFiles = totalFiles; // 暫存上傳為一次性批次
            const progress = (completedFiles / totalFiles) * 100;
            if (progressBar) progressBar.style.width = progress + '%';
            if (progressText) progressText.textContent = `${completedFiles}/${totalFiles}`;
        }

        // 將上傳成功的檔案加到全域變數
        uploadedAttachments = uploadedAttachments.concat(uploadedFiles);

        // 更新附件列表顯示
        renderAttachmentsList();

        if (uploadedFiles.length > 0) {
            const attachmentsUploadedMessage = window.i18n ?
                window.i18n.t('messages.attachmentsUploaded', {count: uploadedFiles.length}) :
                `成功上傳並附加 ${uploadedFiles.length} 個附件`;
            showSuccess(attachmentsUploadedMessage);
            // 注意：現在不需要觸發表單變更檢查，因為附件已經立即附加到記錄
        }

    } catch (error) {
        console.error('上傳附件過程發生錯誤:', error);
        const uploadAttachmentFailedMessage = window.i18n ? window.i18n.t('errors.uploadAttachmentFailed') : '上傳附件失敗';
        showError(uploadAttachmentFailedMessage + '：' + error.message);

        // 上傳失敗時顯示錯誤狀態
        attachmentsList.innerHTML = `
            <div class="alert alert-danger d-flex align-items-center">
                <i class="fas fa-exclamation-triangle me-2"></i>
                <div>附件上傳失敗，請重試</div>
            </div>
        `;
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

function renderAttachmentsList() {
    const attachmentsList = document.getElementById('attachmentsList');
    if (!uploadedAttachments || uploadedAttachments.length === 0) {
        const noAttachmentsMessage = window.i18n ? window.i18n.t('errors.noAttachments') : '尚無附件';
        attachmentsList.innerHTML = `<p class="text-muted small mb-0">${noAttachmentsMessage}</p>`;
        return;
    }

    const attachmentsHtml = uploadedAttachments.map((attachment, index) => {
        const stored = attachment.stored_name || attachment.file_token || attachment.name;
        const link = attachment.url ? `<a href="${attachment.url}" target="_blank" class="text-decoration-none me-2"><i class=\"fas fa-link\"></i></a>` : '';
        return `
        <div class="attachment-item d-flex align-items-center justify-content-between p-2 border rounded mb-2 bg-light">
            <div class="d-flex align-items-center">
                <i class="fas fa-file me-2 text-primary"></i>
                <div>
                    <div class="fw-medium">${attachment.name}</div>
                    <div class="small text-muted">${formatFileSize(attachment.size || 0)}</div>
                </div>
            </div>
            <div>
                ${link}
                <button type="button" class="btn btn-sm btn-danger"
                        onclick="removeAttachment('${stored}', '${attachment.name}', ${index})" data-i18n-title="tooltips.removeAttachment">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        </div>`;
    }).join('');

    attachmentsList.innerHTML = `
        <div class="attachments-header mb-2">
            <h6 class="mb-0 text-secondary">${window.i18n ? window.i18n.t('form.uploadedAttachments') : '已上傳的附件'} (${uploadedAttachments.length})</h6>
        </div>
        ${attachmentsHtml}
    `;
}

function removeAttachment(index) {
    uploadedAttachments.splice(index, 1);
    renderAttachmentsList();
    checkFormChanges(); // 觸發表單變更檢查
}

// 格式化檔案大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 下載附件
function downloadAttachment(storedName) {
    try {
        const currentTeam = AppUtils.getCurrentTeam();
        const tcNumberEl = document.getElementById('testCaseNumber');
        if (!currentTeam || !currentTeam.id || !tcNumberEl || !tcNumberEl.value) {
            showError('無法判定附件路徑');
            return;
        }
        const url = `/attachments/test-cases/${encodeURIComponent(currentTeam.id)}/${encodeURIComponent(tcNumberEl.value.trim())}/${encodeURIComponent(storedName)}`;
        window.open(url, '_blank');
    } catch (e) {
        console.error('downloadAttachment error:', e);
    }
}

// 移除附件
async function removeAttachment(fileToken, filename, index) {
    const confirmMessage = window.i18n ?
        window.i18n.t('confirm.deleteAttachment', {filename: filename}) :
        `確定要刪除附件 "${filename}" 嗎？`;
    if (confirm(confirmMessage)) {
        try {
            console.log(`正在刪除附件: ${filename}...`);

            // 取得當前記錄的 ID
            const currentRecordId = getCurrentRecordId();
            if (!currentRecordId) {
                throw new Error('無法取得當前記錄 ID');
            }

            // 呼叫後端 API 刪除附件
            const currentTeam = AppUtils.getCurrentTeam();
            if (!currentTeam || !currentTeam.id) {
                throw new Error('請先選擇團隊');
            }
            const response = await window.AuthClient.fetch(`/api/teams/${currentTeam.id}/testcases/${currentRecordId}/attachments/${encodeURIComponent(filename)}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || '刪除附件失敗');
            }

            const result = await response.json();

            if (result.success) {
                // 從本地陣列中移除
                uploadedAttachments.splice(index, 1);

                // 同時更新原始 testCases 資料中的附件資訊
                const currentRecordId = getCurrentRecordId();
                if (currentRecordId) {
                    // 更新 testCases 陣列中對應記錄的附件
                    const testCaseIndex = testCases.findIndex(tc => tc.record_id === currentRecordId);
                    if (testCaseIndex !== -1) {
                        if (!testCases[testCaseIndex].attachments) {
                            testCases[testCaseIndex].attachments = [];
                        }
                        // 從原始資料中移除該附件
                        testCases[testCaseIndex].attachments = testCases[testCaseIndex].attachments.filter(
att => (att.stored_name !== filename && att.name !== filename)
                        );
                    }

                    // 同時更新 filteredTestCases 中的資料
                    const filteredIndex = filteredTestCases.findIndex(tc => tc.record_id === currentRecordId);
                    if (filteredIndex !== -1) {
                        if (!filteredTestCases[filteredIndex].attachments) {
                            filteredTestCases[filteredIndex].attachments = [];
                        }
                        filteredTestCases[filteredIndex].attachments = filteredTestCases[filteredIndex].attachments.filter(
att => (att.stored_name !== filename && att.name !== filename)
                        );
                    }
                }

                // 重新渲染附件列表
                renderAttachmentsList();
                const attachmentDeletedMessage = window.i18n ?
                    window.i18n.t('messages.attachmentDeleted') : '已成功刪除附件';
                showSuccess(`${attachmentDeletedMessage}: ${filename}`);
            } else {
                throw new Error(result.message || '刪除附件失敗');
            }

        } catch (error) {
            console.error('刪除附件錯誤:', error);
            const attachmentDeleteFailedMessage = window.i18n ? window.i18n.t('errors.attachmentDeleteFailed') : '刪除附件失敗';
            showError(`${attachmentDeleteFailedMessage}: ${error.message}`);
        }
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

// 重置 modal 內所有滾動位置的輔助函數
function resetModalScrollPositions(modal) {
    // 立即重置主要滾動容器
    const modalBody = modal.querySelector('.modal-body');
    if (modalBody) {
        modalBody.scrollTop = 0;
    }

    const scrollableContent = modal.querySelector('.scrollable-content');
    if (scrollableContent) {
        scrollableContent.scrollTop = 0;
    }

    // 重置所有 textarea 和其他可滾動元素
    const textareas = modal.querySelectorAll('textarea');
    textareas.forEach(textarea => {
        textarea.scrollTop = 0;
    });

    // 重置所有 markdown 預覽區域
    const markdownPreviews = modal.querySelectorAll('.markdown-preview');
    markdownPreviews.forEach(preview => {
        preview.scrollTop = 0;
    });

    // 重置任何其他可能的滾動容器
    const scrollableElements = modal.querySelectorAll('[style*="overflow-y: auto"], .overflow-auto');
    scrollableElements.forEach(el => {
        el.scrollTop = 0;
    });
}

// 取得當前記錄 ID 的輔助函數
function getCurrentRecordId() {
    // 從 modal 或其他地方取得當前記錄的 ID（可能是 lark_record_id 或本地 id）
    const modal = document.getElementById('testCaseModal');
    if (modal && modal.dataset.recordId) {
        return modal.dataset.recordId;
    }
    const recordIdElement = document.querySelector('[data-record-id]');
    if (recordIdElement) {
        return recordIdElement.dataset.recordId;
    }
    return null;
}

// 供附件上傳使用的記錄識別：一律使用測試案例編號（與後端規則一致）
function getCurrentRecordKeyForUpload() {
    // 首選：若當前記錄有本地 id（record_id 為純數字），就用本地 id
    try {
        const modal = document.getElementById('testCaseModal');
        const rid = modal && modal.dataset ? modal.dataset.recordId : null;
        if (rid && /^\d+$/.test(String(rid))) {
            return rid;
        }
    } catch (_) {}
    // 次選：使用 Test Case Number（後端兼容）
    const tcNumberEl = document.getElementById('testCaseNumber');
    const val = tcNumberEl && tcNumberEl.value ? tcNumberEl.value.trim() : '';
    return val || null;
}

// 計算動態高度
function calculateDynamicHeights() {
    const modal = document.getElementById('testCaseModal');
    const modalContent = modal.querySelector('.modal-content');
    const fixedSection = modal.querySelector('.fixed-section');
    const fixedButtons = modal.querySelector('.fixed-buttons');
    const scrollableContent = modal.querySelector('.scrollable-content');

    // 取得視窗高度
    const viewportHeight = window.innerHeight;

    // 設定模態框高度為視窗高度的 90%
    const modalHeight = Math.floor(viewportHeight * 0.9);
    const modalDialog = modal.querySelector('.modal-dialog');
    modalDialog.style.height = modalHeight + 'px';
    modalDialog.style.maxHeight = modalHeight + 'px';

    // 等待DOM更新後計算
    setTimeout(() => {
        // 計算固定區域高度
        const modalHeader = modal.querySelector('.modal-header');
        const headerHeight = modalHeader ? modalHeader.offsetHeight : 0;
        const fixedSectionHeight = fixedSection ? fixedSection.offsetHeight : 0;
        const fixedButtonsHeight = fixedButtons ? fixedButtons.offsetHeight : 0;

        // 計算可滾動內容區域的可用高度
        const availableHeight = modalHeight - headerHeight - fixedSectionHeight - fixedButtonsHeight - 2; // 2px for borders

        if (scrollableContent) {
            scrollableContent.style.height = availableHeight + 'px';
            scrollableContent.style.maxHeight = availableHeight + 'px';
        }

        // 根據可用空間決定是否需要滾動
        if (scrollableContent) {
            const contentHeight = scrollableContent.scrollHeight;
            if (contentHeight <= availableHeight) {
                // 內容夠小，不需要滾動
                scrollableContent.style.overflowY = 'hidden';
            } else {
                // 內容太大，需要滾動
                scrollableContent.style.overflowY = 'auto';
            }
        }
    }, 100);
}

// 監聽視窗大小變化
window.addEventListener('resize', function() {
    const modal = document.getElementById('testCaseModal');
    if (modal && modal.classList.contains('show')) {
        calculateDynamicHeights();
    }
    // 視窗尺寸改變時，調整列表高度
    adjustTestCasesScrollHeight();
});

// 當 i18n 準備就緒或語言變更時，強制刷新 placeholder
try {
    document.addEventListener('i18nReady', function(){ updateTcmPlaceholders(); });
    document.addEventListener('languageChanged', function(){ updateTcmPlaceholders(); });
} catch (_) {}

function buildNavigationTestCasesFromGroups(grouped, sortedSectionIds) {
    const ordered = [];
    if (!Array.isArray(sortedSectionIds) || !grouped) return ordered;
    sortedSectionIds.forEach(sectionId => {
        const group = grouped[sectionId];
        if (group && Array.isArray(group.testCases) && group.testCases.length) {
            ordered.push(...group.testCases);
        }
    });
    return ordered;
}

function rebuildNavigationTestCases() {
    if (!Array.isArray(filteredTestCases) || filteredTestCases.length === 0) {
        tcmNavigationTestCases = [];
        return tcmNavigationTestCases;
    }
    const grouped = groupTestCasesBySection(filteredTestCases);
    const sortedSectionIds = sortSectionIds(Object.keys(grouped), grouped);
    tcmNavigationTestCases = buildNavigationTestCasesFromGroups(grouped, sortedSectionIds);
    return tcmNavigationTestCases;
}

function getNavigationTestCases() {
    if (Array.isArray(tcmNavigationTestCases) && tcmNavigationTestCases.length > 0) {
        return tcmNavigationTestCases;
    }
    if (!Array.isArray(filteredTestCases) || filteredTestCases.length === 0) {
        return [];
    }
    return rebuildNavigationTestCases();
}

function getModalTestCaseRecordId() {
    const modal = document.getElementById('testCaseModal');
    const recordId = modal && modal.dataset ? modal.dataset.recordId : '';
    return recordId || '';
}

function resolveNavigationIndex(navigationList) {
    if (!Array.isArray(navigationList) || navigationList.length === 0) {
        currentTestCaseIndex = -1;
        return -1;
    }
    const recordId = getModalTestCaseRecordId();
    if (recordId) {
        const idx = navigationList.findIndex(tc => tc.record_id === recordId);
        if (idx !== -1) {
            currentTestCaseIndex = idx;
            return idx;
        }
    }
    if (currentTestCaseIndex >= 0 && currentTestCaseIndex < navigationList.length) {
        return currentTestCaseIndex;
    }
    currentTestCaseIndex = -1;
    return -1;
}

// 更新導航按鈕狀態
function updateNavigationButtons() {
    const prevBtn = document.getElementById('prevTestCaseBtn');
    const nextBtn = document.getElementById('nextTestCaseBtn');
    const navigationList = getNavigationTestCases();
    const navigationIndex = resolveNavigationIndex(navigationList);

    if (navigationIndex === -1 || navigationList.length <= 1) {
        // 新增模式或只有一筆資料時，隱藏導航按鈕
        prevBtn.style.display = 'none';
        nextBtn.style.display = 'none';
    } else {
        prevBtn.style.display = 'inline-block';
        nextBtn.style.display = 'inline-block';

        // 第一筆時，上一隻按鈕反灰
        if (navigationIndex === 0) {
            prevBtn.disabled = true;
            prevBtn.classList.add('disabled');
        } else {
            prevBtn.disabled = false;
            prevBtn.classList.remove('disabled');
        }

        // 最後一筆時，下一隻按鈕反灰
        if (navigationIndex === navigationList.length - 1) {
            nextBtn.disabled = true;
            nextBtn.classList.add('disabled');
        } else {
            nextBtn.disabled = false;
            nextBtn.classList.remove('disabled');
        }
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

// 顯示上一隻測試案例
function showPrevTestCase() {
    const navigationList = getNavigationTestCases();
    const navigationIndex = resolveNavigationIndex(navigationList);
    if (navigationIndex > 0) {
        const prevTestCase = navigationList[navigationIndex - 1];
        showTestCaseModal(prevTestCase);
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

// 只讓 Test Case 列表區域可滾動：依據可視高度調整列表容器高度
function adjustTestCasesScrollHeight() {
    try {
        const scrollBox = document.getElementById('testCasesScroll');
        if (!scrollBox) return;

        const page = document.getElementById('testCasesPage');
        const paginationHeight = 0;

        const boundary = page
            ? page.getBoundingClientRect().bottom
            : (window.innerHeight || document.documentElement.clientHeight);
        const rect = scrollBox.getBoundingClientRect();
        const top = rect.top;

        const gap = 16; // 預留與分頁/頁尾間距
        let available = boundary - top - paginationHeight - gap;
        if (available < 0) {
            available = 0;
        }

        scrollBox.style.height = available + 'px';
        scrollBox.style.maxHeight = available + 'px';
        scrollBox.style.overflowY = 'auto';
        scrollBox.style.paddingBottom = (paginationHeight + gap) + 'px';
    } catch (e) {
        console.warn('adjustTestCasesScrollHeight failed:', e);
    }
}

function sortSectionsForDisplayGeneric(sections) {
    if (!Array.isArray(sections)) return [];
    const normal = [];
    const unassigned = [];
    sections.forEach(section => {
        if (!section) return;
        if (isUnassignedSectionName(section.name)) {
            unassigned.push(section);
        } else {
            normal.push(section);
        }
    });
    return normal.concat(unassigned);
}

function rebuildBatchSectionMeta() {
    tcmSectionMetaMap = new Map();
    tcmSectionOrder = [];
    tcmUnassignedSectionIds = new Set();

    function traverse(sections, depth = 0, parentPath = '') {
        if (!Array.isArray(sections)) return;
        const orderedSections = sortSectionsForDisplayGeneric(sections);
        orderedSections.forEach(section => {
            const name = section?.name || '';
            const currentPath = parentPath ? `${parentPath}/${name}` : name;
            const meta = {
                id: section?.id ?? null,
                name,
                path: currentPath,
                level: section?.level ?? (depth + 1),
            };
            if (meta.id !== null && meta.id !== undefined) {
                tcmSectionMetaMap.set(meta.id, meta);
                if (isUnassignedSectionName(name)) {
                    tcmUnassignedSectionIds.add(String(meta.id));
                } else {
                    tcmSectionOrder.push(String(meta.id));
                }
            }
            // 檢查多種可能的子節點屬性名稱
            const children = section?.children || section?.child_sections || [];
            if (Array.isArray(children) && children.length > 0) {
                traverse(children, depth + 1, currentPath);
            }
        });
    }

    traverse(tcmSectionsTree, 0, '');
    console.log('[rebuildBatchSectionMeta] Built section order:', tcmSectionOrder);
    const seenOrder = new Set();
    tcmSectionOrder = tcmSectionOrder.filter(id => {
        if (seenOrder.has(id)) return false;
        seenOrder.add(id);
        return true;
    });
    tcmUnassignedSectionIds.forEach(id => {
        if (!seenOrder.has(id)) {
            seenOrder.add(id);
            tcmSectionOrder.push(id);
        }
    });
    if (!seenOrder.has(UNASSIGNED_SECTION_ID)) {
        tcmSectionOrder.push(UNASSIGNED_SECTION_ID);
    }
}

function buildBatchSectionOptionsHtml() {
    const parts = [];

    function flatten(sections, depth = 0) {
        if (!Array.isArray(sections)) return;
        const orderedSections = sortSectionsForDisplayGeneric(sections);
        orderedSections.forEach(section => {
            const name = section?.name || '';
            const isUnassigned = isUnassignedSectionName(name);
            if (section?.id !== undefined && section?.id !== null) {
                const prefix = depth > 0 ? '┣ '.repeat(depth) : '';
                const displayName = isUnassigned ? `${name} (系統)` : name;
                parts.push(`<option value="${section.id}">${prefix}${escapeHtml(displayName)}</option>`);
            }
            // 檢查多種可能的子節點屬性名稱
            const children = section?.children || section?.child_sections || [];
            if (Array.isArray(children) && children.length > 0) {
                flatten(children, depth + 1);
            }
        });
    }

    flatten(tcmSectionsTree, 0);
    console.log('[buildBatchSectionOptionsHtml] Generated', parts.length, 'section options');
    return parts.join('');
}

function populateTestCaseSectionSelect() {
    const select = document.getElementById('testCaseSectionSelect');
    if (!select) return;

    if (!Array.isArray(tcmSectionsTree) || tcmSectionsTree.length === 0) {
        select.innerHTML = '<option value="" data-i18n="testCase.selectSection">請選擇區段</option>';
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(select);
        }
        return;
    }

    const defaultOption = '<option value="" data-i18n="testCase.selectSection">請選擇區段</option>';
    const optionsHtml = buildSectionOptionsForTestCase();
    select.innerHTML = defaultOption + optionsHtml;

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(select);
    }
}

function buildSectionOptionsForTestCase() {
    const parts = [];

    function flatten(sections, depth = 0) {
        if (!Array.isArray(sections)) return;
        const orderedSections = sortSectionsForDisplayGeneric(sections);
        orderedSections.forEach(section => {
            const name = section?.name || '';
            const isUnassigned = isUnassignedSectionName(name);
            if (section?.id !== undefined && section?.id !== null) {
                const prefix = depth > 0 ? '　'.repeat(depth) + '└─ ' : '';
                const displayName = isUnassigned ? `${name} (系統)` : name;
                parts.push(`<option value="${section.id}">${prefix}${escapeHtml(displayName)}</option>`);
            }
            // 檢查多種可能的子節點屬性名稱
            const children = section?.children || section?.child_sections || [];
            if (Array.isArray(children) && children.length > 0) {
                flatten(children, depth + 1);
            }
        });
    }

    flatten(tcmSectionsTree, 0);
    console.log('[buildSectionOptionsForTestCase] Generated', parts.length, 'section options');
    return parts.join('');
}

function populateBatchSectionSelect() {
    const select = document.getElementById('batchSectionSelect');
    if (!select) return;

    if (!Array.isArray(tcmSectionsTree) || tcmSectionsTree.length === 0) {
        select.innerHTML = '<option value="" disabled data-i18n="testCase.sectionsLoading" data-i18n-fallback="尚未載入區段">尚未載入區段</option>';
        select.value = '';
        select.disabled = true;
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(select);
        }
        return;
    }

    const defaultOption = '<option value="" data-i18n="testCase.selectSection" data-i18n-fallback="請選擇區段">請選擇區段</option>';
    const optionsHtml = buildBatchSectionOptionsHtml();
    select.innerHTML = defaultOption + optionsHtml;
    select.value = '';

    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(select);
    }
}

function getSectionMetaByValue(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
        return null;
    }
    return tcmSectionMetaMap.get(parsed) || null;
}

function isUnassignedSectionName(name) {
    if (!name) return false;
    return String(name).trim().toLowerCase() === 'unassigned';
}

// 顯示下一隻測試案例
function showNextTestCase() {
    const navigationList = getNavigationTestCases();
    const navigationIndex = resolveNavigationIndex(navigationList);
    if (navigationIndex !== -1 && navigationIndex < navigationList.length - 1) {
        const nextTestCase = navigationList[navigationIndex + 1];
        showTestCaseModal(nextTestCase);
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

// 更新頁面標題翻譯
function updatePageTitle() {
    const pageTitle = window.i18n ? window.i18n.t('testCase.management') : '測試案例管理';
    const siteTitle = window.i18n ? window.i18n.t('navigation.title') : 'Test Case Repository';
    document.title = `${pageTitle} - ${siteTitle} Web Tool`;
}

// ===== 深連結與剪貼簿工具（TCM） =====
function getCurrentTeamId_TCM() {
    try {
        const cur = AppUtils.getCurrentTeam && AppUtils.getCurrentTeam();
        if (cur && cur.id) return cur.id;
    } catch (_) {}
    const p = new URLSearchParams(window.location.search);
    const t = p.get('team_id') || p.get('teamId') || p.get('team');
    return t ? parseInt(t) : undefined;
}

function buildTcmUrl(teamId, tcNumber) {
    const origin = window.location.origin;
    const params = new URLSearchParams();
    if (teamId) params.set('team_id', teamId);
    if (tcNumber) params.set('tc', tcNumber);
    return `${origin}/test-case-management?${params.toString()}`;
}


function ensureTeamIdInUrl_TCM(teamId) {
    try {
        const url = new URL(window.location.href);
        const before = url.searchParams.get('team_id');
        if (String(before || '') !== String(teamId)) {
            url.searchParams.set('team_id', teamId);
            history.replaceState(null, '', `${url.pathname}?${url.searchParams.toString()}`);
        }
    } catch (_) {}
}

// 監聽 i18n 初始化和語言變更事件
document.addEventListener('i18nReady', updatePageTitle);
document.addEventListener('languageChanged', updatePageTitle);
