/* Test Run Execution - Test Results */
// ================== Test Results 功能 ==================
class TestResultsManager {
    constructor(testRunItemId, testCaseNumber, teamId, configId) {
        this.testRunItemId = testRunItemId;
        this.testCaseNumber = testCaseNumber;
        this.teamId = teamId;
        this.configId = configId;
        this.currentFiles = [];
        this.isUploading = false;
        this.handleUploadButtonClick = null;
        this.handleDropzoneDragOver = null;
        this.handleDropzoneDragLeave = null;
        this.handleDropzoneDrop = null;
        this.handleDropzoneClick = null;
        this.handleFileInputChange = null;
        
        this.initializeElements();
        this.bindEvents();
        this.loadExistingResults();
    }
    
    initializeElements() {
        this.uploadBtn = document.getElementById('uploadTestResultsBtn');
        this.uploadArea = document.getElementById('testResultsUploadArea');
        this.fileInput = document.getElementById('testResultsFileInput');
        this.dropzone = document.querySelector('.upload-dropzone');
        this.progressArea = document.getElementById('uploadProgressArea');
        this.progressBar = document.getElementById('uploadProgressBar');
        this.uploadStatus = document.getElementById('uploadStatus');
        this.resultsList = document.getElementById('testResultsList');
        this.filesList = document.getElementById('testResultsList'); // 檔案列表區域引用
        this.loading = document.getElementById('testResultsLoading');
        this.empty = document.getElementById('testResultsEmpty');

        this.resetViewState();
    }
    
    bindEvents() {
        this.unbindEvents();

        const canUpload = getTrePermissions().canUploadResults;

        if (this.uploadBtn) {
            if (canUpload) {
                this.handleUploadButtonClick = () => this.toggleUploadArea();
                this.uploadBtn.addEventListener('click', this.handleUploadButtonClick);
            } else {
                this.uploadBtn.classList.add('disabled');
                this.uploadBtn.setAttribute('aria-disabled', 'true');
            }
        }

        if (this.dropzone) {
            if (canUpload) {
                this.handleDropzoneDragOver = (e) => this.handleDragOver(e);
                this.handleDropzoneDragLeave = (e) => this.handleDragLeave(e);
                this.handleDropzoneDrop = (e) => this.handleDrop(e);
                this.handleDropzoneClick = () => this.fileInput?.click();

                this.dropzone.addEventListener('dragover', this.handleDropzoneDragOver);
                this.dropzone.addEventListener('dragleave', this.handleDropzoneDragLeave);
                this.dropzone.addEventListener('drop', this.handleDropzoneDrop);
                this.dropzone.addEventListener('click', this.handleDropzoneClick);
            } else {
                this.dropzone.classList.add('disabled');
            }
        }

        if (this.fileInput) {
            if (canUpload) {
                this.handleFileInputChange = (e) => this.handleFileSelect(e);
                this.fileInput.addEventListener('change', this.handleFileInputChange);
            } else {
                this.fileInput.setAttribute('disabled', 'true');
            }
        }
    }

    unbindEvents() {
        if (this.uploadBtn && this.handleUploadButtonClick) {
            this.uploadBtn.removeEventListener('click', this.handleUploadButtonClick);
        }
        if (this.dropzone) {
            if (this.handleDropzoneDragOver) this.dropzone.removeEventListener('dragover', this.handleDropzoneDragOver);
            if (this.handleDropzoneDragLeave) this.dropzone.removeEventListener('dragleave', this.handleDropzoneDragLeave);
            if (this.handleDropzoneDrop) this.dropzone.removeEventListener('drop', this.handleDropzoneDrop);
            if (this.handleDropzoneClick) this.dropzone.removeEventListener('click', this.handleDropzoneClick);
        }
        if (this.fileInput && this.handleFileInputChange) {
            this.fileInput.removeEventListener('change', this.handleFileInputChange);
        }

        this.handleUploadButtonClick = null;
        this.handleDropzoneDragOver = null;
        this.handleDropzoneDragLeave = null;
        this.handleDropzoneDrop = null;
        this.handleDropzoneClick = null;
        this.handleFileInputChange = null;
    }

    resetViewState() {
        if (this.uploadArea) {
            this.uploadArea.style.display = 'none';
        }
        if (this.filesList) {
            this.filesList.style.display = 'block';
        }
        if (this.empty) {
            this.empty.style.display = 'none';
        }
        if (this.uploadBtn && this.uploadBtn.querySelector('i')) {
            this.uploadBtn.querySelector('i').className = 'fas fa-upload';
        }
    }
    
    async loadTestCaseAttachments_REMOVED() {
        try {
            if (!this.tcAttachmentsContainer) return;
            const listDiv = this.tcAttachmentsContainer.querySelector('[data-role="attachments-list"]');
            if (listDiv) listDiv.innerHTML = `<div class="text-muted small">${window.i18n ? window.i18n.t('messages.loading') : '載入中...'}</div>`;
            const resp = await window.AuthClient.fetch(`/api/teams/${this.teamId}/testcases/by-number/${encodeURIComponent(this.testCaseNumber)}`);
            if (!resp.ok) {
                if (listDiv) listDiv.innerHTML = `<div class="text-muted small">${window.i18n ? window.i18n.t('errors.noAttachments') : '尚無附件'}</div>`;
                return;
            }
            const data = await resp.json();
            const attachments = Array.isArray(data.attachments) ? data.attachments : [];
            if (!attachments.length) {
                if (listDiv) listDiv.innerHTML = `<div class="text-muted small">${window.i18n ? window.i18n.t('errors.noAttachments') : '尚無附件'}</div>`;
                return;
            }
            const html = attachments.map(att => {
                const name = att.name || att.file_token || 'file';
                const size = att.size || 0;
                const url = att.url || '#';
                return `
                    <a class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" href="${url}" target="_blank">
                        <span><i class="fas fa-file text-primary me-2"></i>${name}</span>
                        <small class="text-muted">${(size/1024/1024).toFixed(2)} MB</small>
                    </a>
                `;
            }).join('');
            if (listDiv) listDiv.innerHTML = html;
        } catch (e) {
            console.error('載入 Test Case 附件失敗:', e);
        }
    }
    
    async loadExistingResults() {
        try {
            this.showLoading(true);
            
            const response = await window.AuthClient.fetch(`/api/teams/${this.teamId}/test-run-configs/${this.configId}/items/${this.testRunItemId}/test-results`);
            
            if (response.ok) {
                const data = await response.json();
                const files = Array.isArray(data.test_results_files) ? data.test_results_files : [];
                this.renderResultsList(files);
            } else {
                console.error('載入測試結果失敗:', response.statusText);
                this.renderResultsList([]);
            }
        } catch (error) {
            console.error('載入測試結果異常:', error);
            this.renderResultsList([]);
        } finally {
            this.showLoading(false);
        }
    }
    
    toggleUploadArea() {
        if (!getTrePermissions().canUploadResults) {
            showExecutionPermissionDenied();
            return;
        }
        if (!this.uploadArea) {
            return;
        }
        // 修正判斷邏輯：只有明確設定為 'block' 才算可見
        const isVisible = this.uploadArea.style.display === 'block';
        const hasFiles = Array.isArray(this.currentFiles) && this.currentFiles.length > 0;

        if (!isVisible) {
            // 顯示上傳區域，隱藏檔案列表
            if (this.filesList) this.filesList.style.display = 'none';
            if (this.empty) this.empty.style.display = 'none';
            if (this.uploadArea) this.uploadArea.style.display = 'block';
            const icon = this.uploadBtn?.querySelector('i');
            if (icon) icon.className = 'fas fa-times';
        } else {
            // 隱藏上傳區域，重新顯示檔案列表
            if (this.uploadArea) this.uploadArea.style.display = 'none';
            if (this.filesList) this.filesList.style.display = hasFiles ? 'block' : 'none';
            if (this.empty) this.empty.style.display = hasFiles ? 'none' : 'block';
            const icon = this.uploadBtn?.querySelector('i');
            if (icon) icon.className = 'fas fa-upload';
        }
    }
    
    async handleFileSelect(event) {
        const files = Array.from(event.target.files);
        if (files.length > 0) {
            await this.uploadFiles(files);
        }
    }
    
    async handleDrop(event) {
        event.preventDefault();
        this.dropzone.classList.remove('drag-over');
        
        const files = Array.from(event.dataTransfer.files);
        if (files.length > 0) {
            await this.uploadFiles(files);
        }
    }
    
    handleDragOver(event) {
        event.preventDefault();
        this.dropzone.classList.add('drag-over');
    }
    
    handleDragLeave(event) {
        event.preventDefault();
        this.dropzone.classList.remove('drag-over');
    }
    
    async uploadFiles(files) {
        if (!getTrePermissions().canUploadResults) {
            showExecutionPermissionDenied();
            this.showProgress(false);
            return;
        }
        if (this.isUploading) {
            AppUtils.showWarning(i18n.t('testRun.uploadInProgress'));
            return;
        }
        
        this.isUploading = true;
        this.showProgress(true);
        
        try {
            const formData = new FormData();
            files.forEach(file => formData.append('files', file));
            
            const response = await window.AuthClient.fetch(`/api/teams/${this.teamId}/test-run-configs/${this.configId}/items/${this.testRunItemId}/upload-results`, {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (response.ok && result.success) {
                AppUtils.showSuccess(i18n.t('testRun.uploadSuccess'));
                this.loadExistingResults();
                this.toggleUploadArea();

                if (window.updateStatistics) {
                    window.updateStatistics();
                }

                // 重新載入 Test Run Items 數據以更新附件相關資訊
                if (window.loadTestRunItemsWithoutLoading) {
                    window.loadTestRunItemsWithoutLoading();
                }
            } else {
                const errorMsg = result.error_messages?.join('; ') || i18n.t('testRun.uploadFailed');
                AppUtils.showError(errorMsg);
            }
        } catch (error) {
            console.error('上傳異常:', error);
            AppUtils.showError(i18n.t('testRun.uploadError'));
        } finally {
            this.isUploading = false;
            this.showProgress(false);
            this.fileInput.value = '';
        }
    }
    
    renderResultsList(files) {
        const safeFiles = Array.isArray(files) ? files : [];
        this.currentFiles = safeFiles;
        this.canManageFiles = getTrePermissions().canUploadResults;

        if (!safeFiles.length) {
            if (this.resultsList) {
                this.resultsList.innerHTML = '';
            }
            this.showEmpty(true);
            return;
        }
        
        this.showEmpty(false);
        const filesHtml = safeFiles.map((file, index) => this.renderFileItem(file, index)).join('');
        if (this.resultsList) {
            this.resultsList.innerHTML = filesHtml;
        }

        this.bindFileItemEvents();
    }

    renderFileItem(file, fileIndex) {
        const fileIcon = this.getFileIcon(file.name);
        const canManageFiles = !!this.canManageFiles;
        const actionsHtml = canManageFiles ? `
                <div class="file-actions">
                    <button type="button" class="btn btn-xs btn-danger delete-file-btn" 
                            data-file-token="${file.file_token}"
                            data-file-name="${this.escapeHtml(file.name)}" 
                            data-i18n-title="testRun.deleteFile"
                            style="font-size: 0.6rem; padding: 2px 4px;"
                            onclick="event.stopPropagation();">
                        <i class="fas fa-trash" style="font-size: 0.7rem;"></i>
                    </button>
                </div>` : '';
        
        return `
            <div class="test-result-file-item clickable-file"
                 data-file-token="${file.file_token}"
                 data-file-name="${this.escapeHtml(file.name)}"
                 data-file-index="${fileIndex}"
                 data-config-id="${this.configId}"
                 data-item-id="${this.testRunItemId}"
                 style="cursor: pointer;"
                 title="點擊下載 ${this.escapeHtml(file.name)}">
                <div class="file-info">
                    <i class="${fileIcon} file-icon"></i>
                    <div>
                        <div class="fw-medium">${this.escapeHtml(file.name)}</div>
                    </div>
                </div>
                ${actionsHtml}
            </div>
        `;
    }
    
    getFileIcon(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        const iconMap = {
            'png': 'fas fa-image text-primary',
            'jpg': 'fas fa-image text-primary',
            'jpeg': 'fas fa-image text-primary',
            'gif': 'fas fa-image text-primary',
            'pdf': 'fas fa-file-pdf text-danger',
            'txt': 'fas fa-file-alt text-secondary',
            'log': 'fas fa-file-alt text-secondary',
            'json': 'fas fa-file-code text-warning',
            'xml': 'fas fa-file-code text-warning',
            'zip': 'fas fa-file-archive text-info',
            'rar': 'fas fa-file-archive text-info'
        };
        return iconMap[ext] || 'fas fa-file text-secondary';
    }
    
    bindFileItemEvents() {
        // 檔案項目點擊下載事件
        document.querySelectorAll('.clickable-file').forEach(item => {
            item.addEventListener('click', (e) => {
                const fileToken = e.currentTarget.dataset.fileToken;
                const fileIndex = parseInt(e.currentTarget.dataset.fileIndex);
                const configId = parseInt(e.currentTarget.dataset.configId);
                const itemId = parseInt(e.currentTarget.dataset.itemId);
                this.downloadFile(fileToken, fileIndex, configId, itemId);
            });
        });

        // 刪除按鈕事件
        if (this.canManageFiles) {
            document.querySelectorAll('.delete-file-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const fileToken = e.currentTarget.dataset.fileToken;
                    const fileName = e.currentTarget.dataset.fileName;
                    this.deleteFile(fileToken, fileName);
                });
            });
        }
    }

    async downloadFile(fileToken, fileIndex = null, configId = null, itemId = null) {
        try {
            const downloadUrl = new URL(`/api/attachments/teams/${this.teamId}/attachments/download`, window.location.origin);

            // 優先使用 config_id + item_id + file_index（快速路徑，無遞迴搜尋）
            if (fileIndex !== null && configId !== null && itemId !== null) {
                downloadUrl.searchParams.set('config_id', configId);
                downloadUrl.searchParams.set('item_id', itemId);
                downloadUrl.searchParams.set('file_index', fileIndex);
            } else {
                // 降級到舊的方法（較慢）
                downloadUrl.searchParams.set('file_token', fileToken);
            }

            window.open(downloadUrl.toString(), '_blank');
        } catch (error) {
            console.error('下載檔案失敗:', error);
            AppUtils.showError('下載檔案失敗');
        }
    }
    
    async deleteFile(fileToken, fileName) {
        if (!getTrePermissions().canUploadResults) {
            showExecutionPermissionDenied();
            return;
        }
        const confirmed = await AppUtils.showConfirm(
            i18n.t('testRun.confirmDeleteFile', { fileName })
        );
        
        if (!confirmed) return;
        
        try {
            const response = await window.AuthClient.fetch(`/api/teams/${this.teamId}/test-run-configs/${this.configId}/items/${this.testRunItemId}/test-results/${fileToken}`, {
                method: 'DELETE'
            });
            
            const result = await response.json();
            
            if (response.ok && result.success) {
                AppUtils.showSuccess(i18n.t('testRun.fileDeleteSuccess'));
                
                const fileItem = document.querySelector(`[data-file-token="${fileToken}"]`);
                if (fileItem) {
                    fileItem.remove();
                }

                if (Array.isArray(this.currentFiles)) {
                    this.currentFiles = this.currentFiles.filter(file => file && file.file_token !== fileToken);
                    if (this.currentFiles.length === 0) {
                        this.showEmpty(true);
                    }
                }
                
                setTimeout(() => {
                    this.loadExistingResults();
                }, 1000);

                if (window.updateStatistics) {
                    window.updateStatistics();
                }

                // 重新載入 Test Run Items 數據以更新附件相關資訊
                if (window.loadTestRunItemsWithoutLoading) {
                    window.loadTestRunItemsWithoutLoading();
                }
            } else {
                const errorMsg = result.error || i18n.t('testRun.fileDeleteFailed');
                AppUtils.showError(errorMsg);
            }
        } catch (error) {
            console.error('刪除檔案異常:', error);
            AppUtils.showError(i18n.t('testRun.fileDeleteFailed'));
        }
    }
    
    showLoading(show) {
        this.loading.style.display = show ? 'block' : 'none';
        if (show) {
            this.showEmpty(false);
            this.resultsList.style.display = 'none';
        } else {
            this.resultsList.style.display = 'block';
        }
    }
    
    showEmpty(show) {
        if (this.empty) {
            this.empty.style.display = show ? 'block' : 'none';
        }
        if (this.resultsList) {
            this.resultsList.style.display = show ? 'none' : 'block';
        }
    }
    
    showProgress(show) {
        this.progressArea.style.display = show ? 'block' : 'none';
        if (!show) {
            this.progressBar.style.width = '0%';
            this.uploadStatus.textContent = '';
        }
    }
    
    escapeHtml(unsafe) {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // 清理 DOM 狀態方法
    cleanup() {
        this.unbindEvents();
        this.currentFiles = [];
        this.isUploading = false;

        // 清理檔案列表
        if (this.resultsList) {
            this.resultsList.innerHTML = '';
        }

        // 重置上傳區域和檔案列表的顯示狀態
        if (this.uploadArea) {
            this.uploadArea.style.display = 'none';
        }
        if (this.filesList) {
            this.filesList.style.display = 'block';
        }

        // 顯示空狀態
        this.showEmpty(true);
        this.showLoading(false);
        this.showProgress(false);

        // 重置上傳按鈕狀態
        if (this.uploadBtn && this.uploadBtn.querySelector('i')) {
            this.uploadBtn.querySelector('i').className = 'fas fa-upload';
        }

        // 清理檔案輸入
        if (this.fileInput) {
            this.fileInput.value = '';
        }

        // 重置拖放區域狀態
        if (this.dropzone) {
            this.dropzone.classList.remove('drag-over');
        }

        // 重置內部狀態
        this.currentFiles = [];
        this.isUploading = false;
    }
}

// 全局變量
let currentTestResultsManager = null;

// 初始化 Test Results 管理器 (with setTimeout fix)
function initializeTestResults(testRunItemId, testCaseNumber, teamId, configId) {
    // 清理前一個 manager 的 DOM 狀態
    if (currentTestResultsManager) {
        currentTestResultsManager.cleanup();
        currentTestResultsManager = null;
    }

    // 確保 DOM 元素存在後再初始化
    setTimeout(() => {
        currentTestResultsManager = new TestResultsManager(
            testRunItemId,
            testCaseNumber,
            teamId,
            configId
        );
    }, 100);
}
