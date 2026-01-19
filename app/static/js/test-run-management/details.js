/* ============================================================
   TEST RUN MANAGEMENT - DETAILS
   ============================================================ */

function showConfigDetails(configId) {
    const config = testRunConfigs.find(c => c.id === configId);
    if (!config) return;

    const modalElement = document.getElementById('configDetailModal');
    if (!configDetailModalInstance) {
        configDetailModalInstance = new bootstrap.Modal(modalElement);
    }
    
    document.getElementById('configDetailTitle').textContent = config.name;
    document.getElementById('configDetailContent').innerHTML = createConfigDetailContent(config);
    
    // 手動觸發翻譯處理動態插入的內容
    if (window.i18n && window.i18n.isReady()) {
        const detailContent = document.getElementById('configDetailContent');
        window.i18n.retranslate(detailContent);
    }
    
    const deleteBtn = document.getElementById('deleteConfigBtn');
    deleteBtn.setAttribute('data-config-id', configId);
    deleteBtn.onclick = handleDeleteConfig;

    const editBtn = document.getElementById('editConfigBtn');
    editBtn.setAttribute('data-config-id', configId);
    editBtn.onclick = handleEditConfig;

    const permissions = window._testRunPermissions || testRunPermissions || {};
    setElementVisibility('editConfigBtn', permissions.canUpdate);
    setElementVisibility('deleteConfigBtn', permissions.canDelete);
    
    configDetailModalInstance.show();
}

function handleEditConfig(event) {
    const permissions = window._testRunPermissions || testRunPermissions || {};
    if (!permissions.canUpdate) {
        showPermissionDenied();
        return;
    }
    const configId = parseInt(event.currentTarget.getAttribute('data-config-id'));
    if (configDetailModalInstance) {
        configDetailModalInstance.hide();
    }
    setTimeout(() => {
        openConfigFormModal(configId);
    }, 150);
}

async function handleDeleteConfig(event) {
    const permissions = window._testRunPermissions || testRunPermissions || {};
    if (!permissions.canDelete) {
        showPermissionDenied();
        return;
    }

    const configId = event.currentTarget.getAttribute('data-config-id');
    const config = testRunConfigs.find(c => c.id === parseInt(configId));
    if (!config) return;
    // Show custom modal
    const modal = document.getElementById('deleteConfigModal');
    const msgEl = document.getElementById('deleteConfirmMessage');
    msgEl.textContent = window.i18n ? window.i18n.t('testRun.confirmDelete', { name: escapeHtml(config.name) }) : `您確定要刪除 Test Run 配置 "${escapeHtml(config.name)}" 嗎？此操作無法復原。`;
    const inst = bootstrap.Modal.getOrCreateInstance(modal);
    // Rebind confirm handler
    const btnOld = document.getElementById('confirmDeleteConfigBtn');
    const btnNew = btnOld.cloneNode(true);
    btnOld.parentNode.replaceChild(btnNew, btnOld);
    document.getElementById('confirmDeleteConfigBtn').addEventListener('click', async () => {
        try {
            const resp = await window.AuthClient.fetch(`/api/teams/${currentTeamId}/test-run-configs/${configId}`, { method: 'DELETE' });
            if (resp.ok || resp.status === 204) {
                if (configDetailModalInstance) configDetailModalInstance.hide();
                inst.hide();
                const successMsg = window.i18n ? window.i18n.t('testRun.deleteSuccess', { name: config.name }) : `成功刪除 "${config.name}"`;
                AppUtils.showSuccess(successMsg);
                await loadTestRunConfigs();
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
            console.error('Error deleting Test Run configuration:', error);
            const errorMsg = window.i18n ? window.i18n.t('messages.deleteFailed') : '刪除失敗';
            AppUtils.showError(`${errorMsg}: ${error.message}`);
        }
    });
    if (window.i18n && window.i18n.isReady()) window.i18n.retranslate(modal);
    inst.show();
}

function createConfigDetailContent(config) {
    return `
        <div class="row">
            <div class="col-md-6">
                <h6 data-i18n="testRun.configBasicInfo">基本資訊</h6>
                <table class="table table-sm">
                    <tr><td data-i18n="testRun.configNameLabel">名稱</td><td>${escapeHtml(config.name)}</td></tr>
                    <tr><td data-i18n="testRun.testEnvironment">測試環境</td><td>${escapeHtml(config.test_environment || '')}</td></tr>
                    <tr><td data-i18n="testRun.buildNumber">建置版本</td><td>${escapeHtml(config.build_number || '')}</td></tr>
                    <tr><td data-i18n="testRun.configStatusLabel">狀態</td><td><span class="status-badge ${getStatusClass(config.status)}">${getStatusText(config.status)}</span></td></tr>
                </table>
            </div>
            <div class="col-md-6">
                <h6 data-i18n="testRun.configStatsInfo">統計資訊</h6>
                <table class="table table-sm">
                    <tr><td data-i18n="testRun.configTotalCasesLabel">總測試案例</td><td>${config.total_test_cases}</td></tr>
                    <tr><td data-i18n="testRun.configExecutedLabel">已執行</td><td>${config.executed_cases}</td></tr>
                    <tr><td data-i18n="testRun.configExecutionRateLabel">執行率</td><td>${config.execution_rate.toFixed(1)}%</td></tr>
                    <tr><td data-i18n="testRun.configPassRateLabel">Pass Rate</td><td>${config.pass_rate.toFixed(1)}%</td></tr>
                    <tr><td data-i18n="testRun.configCreatedLabel">建立時間</td><td>${AppUtils.formatDate(config.created_at, 'datetime-tz')}</td></tr>
                </table>
            </div>
        </div>
        ${config.description ? `
            <div class="mt-3">
                <h6 data-i18n="common.description">描述</h6>
                <p class="text-muted">${escapeHtml(config.description)}</p>
            </div>
        ` : ''}
    `;
}

function escapeHtml(text) {
    if (!text) return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

function updatePageTitle() {
    const pageTitle = window.i18n ? window.i18n.t('testRun.management') : '測試執行管理';
    const siteTitle = window.i18n ? window.i18n.t('navigation.title') : 'Test Case Repository';
    document.title = `${pageTitle} - ${siteTitle} Web Tool`;
}

// Test Run entry function
function enterTestRun(configId) {
    const config = testRunConfigs.find(c => c.id === configId);
    if (!config) {
        console.error('Test Run configuration not found:', configId);
        AppUtils.showError(window.i18n ? window.i18n.t('testRun.notFound') : '找不到測試執行配置');
        return;
    }
    
    // 導向 Test Run 執行頁面
    window.location.href = `/test-run-execution?config_id=${configId}`;
}

document.addEventListener('i18nReady', updatePageTitle);
document.addEventListener('languageChanged', updatePageTitle);
