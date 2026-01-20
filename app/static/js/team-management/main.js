let teams = [];
let currentEditTeam = null;

// 依據後端 UI 能力控制組織頁籤可視
async function applyOrganizationUiVisibility() {
    try {
        if (!window.AuthClient) return;
        const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=organization');
        if (!resp.ok) return;
        const json = await resp.json();
        const map = json.components || {};
        const show = (id, isLi=false) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (isLi) { el.style.display = map[id] ? '' : 'none'; }
            else {
                // 對於 button，隱藏其父 li
                const li = el.closest('li');
                if (li) li.style.display = map[id] ? '' : 'none';
                else el.style.display = map[id] ? '' : 'none';
            }
        };
        // 人員管理分頁（Admin/SuperAdmin 應允許）
        show('tab-personnel-li', true);
        // 進階分頁（僅 Super Admin）
        show('tab-org');
        show('tab-test-cases');
    } catch (_) {}
}

// team-management 頁面按鈕（例如同步組織）可視控制
async function applyTeamManagementUiVisibility() {
    try {
        if (!window.AuthClient) return;
        const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=team_management');
        if (!resp.ok) return;
        const json = await resp.json();
        const map = json.components || {};

        const createBtn = document.getElementById('createTeamBtn');
        if (createBtn) createBtn.style.display = map['createTeamBtn'] ? '' : 'none';

        const syncBtn = document.getElementById('syncOrgBtn');
        if (syncBtn) syncBtn.style.display = map['syncOrgBtn'] ? '' : 'none';

        // 數據與記錄選單的顯示控制
        const dataMenuGroup = document.getElementById('dataMenuGroup');
        if (dataMenuGroup) dataMenuGroup.style.display = map['auditLogBtn'] ? '' : 'none';

        // 控制團隊數據統計連結的顯示（僅 admin 及以上可見）
        const teamStatsLink = document.getElementById('teamStatsLink');
        if (teamStatsLink && window.currentUser) {
            const userRole = window.currentUser.role;
            if (userRole === 'admin' || userRole === 'super_admin') {
                teamStatsLink.parentElement.style.display = '';
            } else {
                teamStatsLink.parentElement.style.display = 'none';
            }
        }
    } catch (_) {}
}

document.addEventListener('DOMContentLoaded', function() {
    initTeamManagement();
    applyOrganizationUiVisibility();
    applyTeamManagementUiVisibility();
});

function initTeamManagement() {
    // 綁定事件監聽器
    document.getElementById('createTeamBtn').addEventListener('click', showCreateTeamModal);
    document.getElementById('refreshBtn').addEventListener('click', loadTeams);
    document.getElementById('saveTeamBtn').addEventListener('click', saveTeam);
    document.getElementById('validateLarkBtn').addEventListener('click', validateLarkConnection);
    // 審計記錄和團隊統計現在使用下拉選單中的 <a> 標籤，不需要額外的事件監聽器
    document.getElementById('syncOrgBtn').addEventListener('click', openSyncModal);
    
    // USM 匯入功能事件監聽器
    document.getElementById('importUSMBtn').addEventListener('click', openUSMImportModal);
    document.getElementById('preprocessLarkTableBtn').addEventListener('click', preprocessLarkTable);
    document.getElementById('confirmUSMImportBtn').addEventListener('click', confirmUSMImport);
    
    // 同步功能框事件監聽器
    document.getElementById('startSyncBtn').addEventListener('click', () => startSyncFromModal('full'));
    document.getElementById('startDeptSyncBtn').addEventListener('click', () => startSyncFromModal('departments'));
    document.getElementById('startUserSyncBtn').addEventListener('click', () => startSyncFromModal('users'));
    const refreshSyncBtn = document.getElementById('refreshSyncDataBtn');
    if (refreshSyncBtn) refreshSyncBtn.addEventListener('click', refreshSyncModalData);

    // 載入團隊列表
    loadTeams();
}

async function loadTeams() {
    try {
        showLoading();
        
        // 確保 AuthClient 已經初始化
        if (!window.AuthClient) {
            throw new Error('AuthClient 尚未初始化');
        }
        
        const response = await window.AuthClient.fetch('/api/teams/');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        teams = await response.json();
        renderTeams();
        
    } catch (error) {
        console.error('Load teams failed:', error);
        if (AppUtils && AppUtils.showError) {
            const errorMsg = window.i18n ? window.i18n.t('messages.loadFailed') : '載入失敗';
            AppUtils.showError(errorMsg + '：' + error.message);
        } else {
            console.error('AppUtils not available:', error.message);
        }
        showNoTeams();
    } finally {
        hideLoading();
    }
}

function renderTeams() {
    if (!teams || teams.length === 0) {
        showNoTeams();
        return;
    }
    
    showTeamsList();
    renderTeamCards();
}

function showLoading() {
    document.getElementById('loading-state').style.display = 'block';
    document.getElementById('teams-section').style.display = 'none';
    document.getElementById('no-teams-section').style.display = 'none';
}

function hideLoading() {
    // 僅隱藏載入狀態，實際可見區域由 renderTeams()/showNoTeams() 控制
    document.getElementById('loading-state').style.display = 'none';
}

async function showNoTeams() {
    document.getElementById('loading-state').style.display = 'none';
    document.getElementById('teams-section').style.display = 'none';
    document.getElementById('no-teams-section').style.display = 'block';

    // 根據權限決定提示文字
    const hintElement = document.querySelector('#no-teams-section p');
    try {
        const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=team_management');
        const config = await resp.json();
        if (config.components.createTeamHint) {
            hintElement.setAttribute('data-i18n', 'team.noTeamsHint');
            hintElement.textContent = window.i18n ? window.i18n.t('team.noTeamsHint') : '點擊上方「新增團隊」按鈕開始建立第一個團隊';
        } else {
            hintElement.setAttribute('data-i18n', 'team.noTeamsViewer');
            hintElement.textContent = window.i18n ? window.i18n.t('team.noTeamsViewer') : '尚無已建立團隊';
        }
    } catch (e) {
        // 發生錯誤時，顯示預設的無權限提示
        hintElement.setAttribute('data-i18n', 'team.noTeamsViewer');
        hintElement.textContent = window.i18n ? window.i18n.t('team.noTeamsViewer') : '尚無已建立團隊';
    }

    // 清空舊的卡片內容，避免殘留
    const container = document.getElementById('teams-container');
    if (container) container.innerHTML = '';
}

function showTeamsList() {
    document.getElementById('loading-state').style.display = 'none';
    document.getElementById('no-teams-section').style.display = 'none';
    document.getElementById('teams-section').style.display = 'block';
}

function renderTeamCards() {
    const container = document.getElementById('teams-container');
    
    const teamsHtml = teams.map(team => `
        <div class="col-md-6 col-lg-4 mb-4">
            <div class="card h-100 team-card">
                <div class="card-body d-flex flex-column h-100">
                    <div class="d-flex align-items-start mb-3">
                        <div class="flex-shrink-0 me-3">
                            <div class="bg-primary text-white rounded-circle d-flex align-items-center justify-content-center" 
                                 style="width: 48px; height: 48px; font-size: 18px; font-weight: bold;">
                                ${getTeamInitials(team.name)}
                            </div>
                        </div>
                        <div class="flex-grow-1">
                            <h5 class="card-title text-primary mb-1">${escapeHtml(team.name)}</h5>
                            <p class="card-text text-muted small mb-0">
                                ${escapeHtml(team.description || ((window.i18n && window.i18n.isReady()) ? window.i18n.t('common.noDescription') : '無描述'))}
                            </p>
                        </div>
                    </div>
                    <div class="mt-auto pt-2">
                        <div class="mb-2">
                            <div class="d-flex align-items-center mb-1">
                                <i class="fas fa-table me-2 text-success"></i>
                                <small class="text-muted">Lark: ${team.is_lark_configured ? 
                                    ((window.i18n && window.i18n.isReady()) ? window.i18n.t('team.configured') : '已設定') : 
                                    ((window.i18n && window.i18n.isReady()) ? window.i18n.t('team.notConfigured') : '未設定')}</small>
                            </div>
                        </div>
                        <div class="d-flex gap-2">
                            <div class="dropdown" style="flex: 1;">
                                <button class="btn btn-primary btn-sm w-100 dropdown-toggle" type="button" id="enterTeamDropdown${team.id}" data-bs-toggle="dropdown" aria-expanded="false">
                                    <i class="fas fa-arrow-right me-1"></i><span>${(window.i18n && window.i18n.isReady()) ? window.i18n.t('team.enterTeam') : '進入團隊'}</span>
                                </button>
                                <ul class="dropdown-menu" aria-labelledby="enterTeamDropdown${team.id}">
                                    <li>
                                        <button class="dropdown-item" type="button" onclick="enterTeamWithPage(${team.id}, 'test-cases')">
                                            <i class="fas fa-list-check me-2"></i>Test Cases
                                        </button>
                                    </li>
                                    <li>
                                        <button class="dropdown-item" type="button" onclick="enterTeamWithPage(${team.id}, 'test-runs')">
                                            <i class="fas fa-play-circle me-2"></i>Test Runs
                                        </button>
                                    </li>
                                    <li>
                                        <button class="dropdown-item" type="button" onclick="enterTeamWithPage(${team.id}, 'usm')">
                                            <i class="fas fa-project-diagram me-2"></i>User Story Map
                                        </button>
                                    </li>
                                </ul>
                            </div>
                            <button class="btn btn-secondary btn-sm" style="flex: 1;" onclick="editTeam(${team.id})">
                                <i class="fas fa-edit me-1"></i><span>${(window.i18n && window.i18n.isReady()) ? window.i18n.t('common.edit') : '編輯'}</span>
                            </button>
                            <button class="btn btn-danger btn-sm" style="flex: 1;" onclick="openDeleteTeamModal(${team.id})">
                                <i class="fas fa-trash me-1"></i><span>${(window.i18n && window.i18n.isReady()) ? window.i18n.t('common.delete') : '刪除'}</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `).join('');
    
    container.innerHTML = teamsHtml;

    // Retranslate the newly added content only within container
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(container);
    }

    // 下拉選單開啟時，將對應卡片提升 z-index，避免被其他卡片遮住
    const dropdownElements = container.querySelectorAll('[data-bs-toggle="dropdown"]');
    dropdownElements.forEach(btn => {
        const card = btn.closest('.team-card');
        btn.addEventListener('show.bs.dropdown', () => {
            if (card) {
                card.classList.add('dropdown-open');
            }
        });

        btn.addEventListener('hidden.bs.dropdown', () => {
            if (card) {
                card.classList.remove('dropdown-open');
            }
        });
    });
}

function showCreateTeamModal() {
    currentEditTeam = null;
    const modalTitle = window.i18n ? window.i18n.t('team.createTeam') : '新增團隊';
    document.getElementById('teamModalLabel').textContent = modalTitle;
    document.getElementById('teamForm').reset();
    
    const modal = new bootstrap.Modal(document.getElementById('teamModal'));
    modal.show();
}

function editTeam(teamId) {
    const team = teams.find(t => t.id === teamId);
    if (!team) return;
    
    currentEditTeam = team;
    const modalTitle = window.i18n ? window.i18n.t('team.editTeam') : '編輯團隊';
    document.getElementById('teamModalLabel').textContent = modalTitle;
    
    // 填入表單資料
    document.getElementById('teamName').value = team.name;
    document.getElementById('teamDescription').value = team.description || '';
    document.getElementById('wikiToken').value = team.lark_config.wiki_token;
    document.getElementById('testCaseTableId').value = team.lark_config.test_case_table_id;
    
    
    const modal = new bootstrap.Modal(document.getElementById('teamModal'));
    modal.show();
}

async function saveTeam() {
    const form = document.getElementById('teamForm');
    const formData = new FormData(form);
    
    // 構建團隊資料
    const teamData = {
        name: formData.get('name'),
        description: formData.get('description') || null,
        lark_config: {
            wiki_token: formData.get('wiki_token'),
            test_case_table_id: formData.get('test_case_table_id')
        },
        settings: {
            default_priority: 'Medium'
        }
    };
    
    // 驗證必填欄位
    if (!teamData.name || !teamData.lark_config.wiki_token || !teamData.lark_config.test_case_table_id) {
        const errorMsg = window.i18n ? window.i18n.t('messages.fillRequiredFields') : '請填寫所有必填欄位';
        AppUtils.showError(errorMsg);
        return;
    }
    
    try {
        let url = '/api/teams';
        let method = 'POST';
        
        if (currentEditTeam) {
            url = `/api/teams/${currentEditTeam.id}`;
            method = 'PUT';
        }
        
        const response = await window.AuthClient.fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(teamData)
        });
        
        if (!response.ok) {
            let errMsg = '';
            try {
                const error = await response.clone().json();
                if (Array.isArray(error?.detail)) {
                    errMsg = error.detail.map(e => {
                        const field = e.loc && e.loc.length > 0 ? e.loc[e.loc.length - 1] : 'Unknown field';
                        return `${field}: ${e.msg}`;
                    }).join('; ');
                } else {
                    errMsg = error?.detail || error?.message || '';
                }
            } catch (_) {
                try {
                    errMsg = (await response.text()) || '';
                } catch (_) {
                    errMsg = '';
                }
            }
            const defaultMsg = window.i18n ? window.i18n.t('messages.saveFailed') : '儲存失敗';
            throw new Error(errMsg || `${defaultMsg} (HTTP ${response.status})`);
        }
        
        const successMsg = currentEditTeam ? 
            (window.i18n ? window.i18n.t('team.teamUpdated') : '團隊更新成功') :
            (window.i18n ? window.i18n.t('team.teamSaved') : '團隊建立成功');
        AppUtils.showSuccess(successMsg);
        
        // 關閉模態視窗
        const modal = bootstrap.Modal.getInstance(document.getElementById('teamModal'));
        modal.hide();
        
        // 重新載入團隊列表
        await loadTeams();
        
    } catch (error) {
        console.error('Save team failed:', error);
        const errorMsg = window.i18n ? window.i18n.t('messages.saveFailed') : '儲存失敗';
        AppUtils.showError(errorMsg + '：' + error.message);
    }
}

async function validateLarkConnection() {
    const wikiToken = document.getElementById('wikiToken').value;
    const testCaseTableId = document.getElementById('testCaseTableId').value;
    const resultDiv = document.getElementById('larkValidationResult');
    
    if (!wikiToken || !testCaseTableId) {
        const warningMsg = window.i18n ? window.i18n.t('team.pleaseEnterToken') : '請先填寫 Wiki Token 和 Test Case 表格 ID';
        showValidationMessage(warningMsg, 'warning');
        return;
    }
    
    const validateBtn = document.getElementById('validateLarkBtn');
    validateBtn.disabled = true;
    const validatingMsg = window.i18n ? window.i18n.t('team.validating') : '驗證中...';
    validateBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>${validatingMsg}`;
    
    try {
        const response = await window.AuthClient.fetch('/api/teams/validate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: 'test',
                lark_config: {
                    wiki_token: wikiToken,
                    test_case_table_id: testCaseTableId
                },
                settings: {
                    default_priority: 'Medium'
                }
            })
        });
        
        const result = await response.json();
        
        if (result.valid) {
            const successMsg = window.i18n ? window.i18n.t('team.connectionValid') : '連線驗證成功';
            showValidationMessage(successMsg, 'success');
        } else {
            const failMsg = window.i18n ? window.i18n.t('team.connectionInvalid') : '連線驗證失敗';
            showValidationMessage(failMsg, 'danger');
        }
        
    } catch (error) {
        console.error('Validation failed:', error);
        const errorMsg = window.i18n ? window.i18n.t('team.connectionError') : '驗證過程發生錯誤';
        showValidationMessage(errorMsg, 'danger');
    } finally {
        validateBtn.disabled = false;
        const validateText = window.i18n ? window.i18n.t('team.validateConnection') : '驗證 Lark 連線';
        validateBtn.innerHTML = `<i class="fas fa-check me-2"></i>${validateText}`;
    }
}

function selectTeam(teamId) {
    const team = teams.find(t => t.id === teamId);
    if (!team) return;

    // 儲存選擇的團隊，直接導向（不顯示 Toast）
    if (AppUtils && AppUtils.setCurrentTeam) {
        AppUtils.setCurrentTeam(team);
        window.location.href = '/test-case-management';
    }
}

function enterTeamWithPage(teamId, page) {
    const team = teams.find(t => t.id === teamId);
    if (!team) return;

    // 儲存選擇的團隊
    if (AppUtils && AppUtils.setCurrentTeam) {
        AppUtils.setCurrentTeam(team);
    }

    // 根據選擇導向到不同頁面，帶上 team_id 參數
    const urlMap = {
        'test-cases': '/test-case-management',
        'test-runs': '/test-run-management',
        'usm': `/user-story-map/${teamId}`
    };
    const base = urlMap[page] || urlMap['test-cases'];
    const needsQuery = !base.includes('/user-story-map/');
    window.location.href = needsQuery ? `${base}?team_id=${encodeURIComponent(teamId)}` : base;
}

let pendingDeleteTeamId = null;

function openDeleteTeamModal(teamId) {
    const team = teams.find(t => t.id === teamId);
    if (!team) return;

    pendingDeleteTeamId = teamId;

    const modalEl = document.getElementById('deleteTeamModal');
    const msgEl = document.getElementById('deleteTeamConfirmMessage');
    msgEl.textContent = window.i18n ?
        window.i18n.t('team.confirmDelete', { name: team.name }) :
        `確定要刪除團隊「${team.name}」嗎？此操作無法復原。`;

    // 綁定確認事件（覆寫確保單一監聽）
    const confirmBtn = document.getElementById('confirmDeleteTeamBtn');
    confirmBtn.onclick = handleConfirmDeleteTeam;

    // 套用翻譯並開啟
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(modalEl);
    }
    const inst = bootstrap.Modal.getOrCreateInstance(modalEl);
    inst.show();
}

async function handleConfirmDeleteTeam() {
    if (!pendingDeleteTeamId) return;
    const modalEl = document.getElementById('deleteTeamModal');
    const inst = bootstrap.Modal.getInstance(modalEl);
    try {
        await performDeleteTeam(pendingDeleteTeamId);
        if (inst) inst.hide();
    } finally {
        pendingDeleteTeamId = null;
    }
}

async function performDeleteTeam(teamId) {
    try {
        const response = await window.AuthClient.fetch(`/api/teams/${teamId}`, { method: 'DELETE' });
        if (!response.ok) {
            const errorMsg = window.i18n ? window.i18n.t('messages.deleteFailed') : '刪除失敗';
            throw new Error(errorMsg);
        }
        const successMsg = window.i18n ? window.i18n.t('team.teamDeleted') : '團隊刪除成功';
        AppUtils.showSuccess(successMsg);
        // 若刪除的是目前選取的團隊，清除選取並隱藏徽章
        try {
            const current = AppUtils.getCurrentTeam && AppUtils.getCurrentTeam();
            if (current && current.id === teamId && AppUtils.clearCurrentTeam) {
                AppUtils.clearCurrentTeam();
                AppUtils.hideTeamNameBadge && AppUtils.hideTeamNameBadge();
            }
        } catch (_) {}
        await loadTeams();
    } catch (error) {
        console.error('Delete team failed:', error);
        const errorMsg = window.i18n ? window.i18n.t('messages.deleteFailed') : '刪除失敗';
        AppUtils.showError(errorMsg + '：' + error.message);
    }
}

function getTeamInitials(name) {
    if (!name) return 'T';
    
    return name
        .split(' ')
        .map(word => word.charAt(0).toUpperCase())
        .slice(0, 2)
        .join('');
}

function showValidationMessage(message, type) {
    const resultDiv = document.getElementById('larkValidationResult');
    
    // 設定顏色和圖示
    let iconClass, textClass;
    switch(type) {
        case 'success':
            iconClass = 'fas fa-check-circle';
            textClass = 'text-success';
            break;
        case 'danger':
            iconClass = 'fas fa-times-circle';
            textClass = 'text-danger';
            break;
        case 'warning':
            iconClass = 'fas fa-exclamation-triangle';
            textClass = 'text-warning';
            break;
        default:
            iconClass = 'fas fa-info-circle';
            textClass = 'text-info';
    }
    
    // 顯示訊息
    resultDiv.innerHTML = `<small class="${textClass}"><i class="${iconClass} me-1"></i>${message}</small>`;
    
    // 3秒後自動清除
    setTimeout(() => {
        resultDiv.innerHTML = '';
    }, 3000);
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

// 更新頁面標題翻譯
function updatePageTitle() {
    const pageTitle = window.i18n ? window.i18n.t('team.management') : '團隊管理';
    const siteTitle = window.i18n ? window.i18n.t('navigation.title') : 'Test Case Repository';
    document.title = `${pageTitle} - ${siteTitle} Web Tool`;
}

// 監聽 i18n 初始化和語言變更事件
document.addEventListener('i18nReady', updatePageTitle);
document.addEventListener('languageChanged', updatePageTitle);

// ===== 組織架構同步功能 =====

// ===== 同步功能框模態視窗管理 =====

// 模態視窗狀態管理
let syncModalInstance = null;
let syncPollingInterval = null;

// 開啟同步功能框
async function openSyncModal() {

    const modal = document.getElementById('syncModal');
    if (!syncModalInstance) {
        syncModalInstance = new bootstrap.Modal(modal);
        
        // 監聽模態框關閉事件，保存狀態到localStorage
        modal.addEventListener('hidden.bs.modal', saveSyncModalState);
        modal.addEventListener('shown.bs.modal', loadSyncModalState);
    }

    // 載入模態框數據
    await loadSyncModalData();

    // 套用翻譯至整個 Modal（包含所有分頁，即使是隱藏的）
    try {
        if (window.i18n && window.i18n.isReady()) {
            console.log('[Modal Translation] Translating entire modal');
            // 強制翻譯所有分頁內容，包括隱藏的
            window.i18n.retranslate(modal);
            
            // 特別確保測試案例分頁的翻譯
            const tcPane = document.getElementById('tab-pane-test-cases');
            if (tcPane) {
                console.log('[Modal Translation] Specifically translating test cases pane');
                const tcLabel = tcPane.querySelector('[data-i18n="tcSync.selectTeam"]');
                if (tcLabel) {
                    console.log('[Modal Translation] Found tcSync.selectTeam label:', tcLabel.textContent);
                    const translatedText = window.i18n.t('tcSync.selectTeam');
                    console.log('[Modal Translation] Translated text:', translatedText);
                    tcLabel.textContent = translatedText;
                }
                window.i18n.retranslate(tcPane);
            }
        } else {
            console.warn('[Modal Translation] i18n not ready');
        }
    } catch (e) {
        console.error('[Modal Translation] Error:', e);
    }
    
    syncModalInstance.show();
}

// 載入同步功能框所有數據
async function loadSyncModalData() {
    await Promise.all([
        loadSyncStatus(),
        loadOrgStats()
    ]);
}

// 重新整理同步功能框數據
async function refreshSyncModalData() {
    const refreshBtn = document.getElementById('refreshSyncDataBtn');
    const originalHtml = refreshBtn.innerHTML;
    
    refreshBtn.disabled = true;
    refreshBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>重新整理中...';
    
    try {
        await loadSyncModalData();
    } finally {
        refreshBtn.disabled = false;
        refreshBtn.innerHTML = originalHtml;
    }
}

// 載入同步狀態
async function loadSyncStatus() {
    const loadingDiv = document.getElementById('syncStatusLoading');
    const idleDiv = document.getElementById('syncStatusIdle');
    const runningDiv = document.getElementById('syncStatusRunning');
    
    // 顯示載入狀態（使用 Bootstrap d-none 以避免 d-flex !important 影響）
    loadingDiv.classList.remove('d-none');
    idleDiv.classList.add('d-none');
    runningDiv.classList.add('d-none');
    
    try {
        const response = await window.AuthClient.fetch('/api/organization/sync/status');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const result = await response.json();
        if (result.success && result.data) {
            const data = result.data;
            
            loadingDiv.classList.add('d-none');
            
            if (data.is_syncing) {
                // 同步進行中
                setSyncStatus('running');
                
                // 更新進度信息
                const progressText = document.getElementById('syncProgressText');
                const progressBar = document.getElementById('syncProgressBar');
                
                // 僅顯示狀態，不顯示進度條或百分比
                
                // 開始輪詢狀態
                startSyncPolling();
                
                // 按鈕狀態由 setSyncStatus 控制
            } else {
                // 系統空閒
                setSyncStatus('idle');
                
                // 顯示最後同步時間
                if (data.last_sync_end) {
                    const lastSyncDiv = document.getElementById('lastSyncTime');
                    const lastPrefix = getI18n('orgSync.lastSyncPrefix', '最後同步:');
                    lastSyncDiv.textContent = `${lastPrefix} ${new Date(data.last_sync_end).toLocaleString()}`;
                }
                
                // 按鈕狀態由 setSyncStatus 控制
            }
        }
    } catch (error) {
        console.error('載入同步狀態失敗:', error);
        loadingDiv.classList.add('d-none');
        setSyncStatus('idle');
    }
}

function setSyncStatus(mode) {
    const idleDiv = document.getElementById('syncStatusIdle');
    const runningDiv = document.getElementById('syncStatusRunning');
    const startBtn = document.getElementById('startSyncBtn');
    const deptBtn = document.getElementById('startDeptSyncBtn');
    const userBtn = document.getElementById('startUserSyncBtn');

    if (mode === 'running') {
        idleDiv.classList.add('d-none');
        runningDiv.classList.remove('d-none');
        if (startBtn) startBtn.disabled = true;
        if (deptBtn) deptBtn.disabled = true;
        if (userBtn) userBtn.disabled = true;
    } else if (mode === 'idle') {
        runningDiv.classList.add('d-none');
        idleDiv.classList.remove('d-none');
        if (startBtn) startBtn.disabled = false;
        if (deptBtn) deptBtn.disabled = false;
        if (userBtn) userBtn.disabled = false;
        // 在同步完成後恢復按鈕原始內容（避免仍然顯示「啟動中…」並丟失 i18n 標籤）
        restoreSyncActionButtons();
        // 重新套用翻譯到剛恢復的按鈕文字
        try {
            const modal = document.getElementById('syncModal');
            if (window.i18n && window.i18n.isReady() && modal) {
                window.i18n.retranslate(modal);
            }
        } catch (_) {}
    } else {
        runningDiv.classList.add('d-none');
        idleDiv.classList.add('d-none');
        if (startBtn) startBtn.disabled = false;
        if (deptBtn) deptBtn.disabled = false;
        if (userBtn) userBtn.disabled = false;
    }
}

// 恢復同步操作按鈕的原始圖示與文字（含 i18n 標籤）
function restoreSyncActionButtons() {
    const deptBtn = document.getElementById('startDeptSyncBtn');
    const userBtn = document.getElementById('startUserSyncBtn');
    const startBtn = document.getElementById('startSyncBtn');

    if (deptBtn) {
        deptBtn.innerHTML = '<i class="fas fa-sitemap me-2"></i><span data-i18n="orgSync.departmentsSync">部門同步</span>';
        // 重新應用翻譯到按鈕內容
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(deptBtn);
        }
    }
    if (userBtn) {
        userBtn.innerHTML = '<i class="fas fa-address-book me-2"></i><span data-i18n="orgSync.contactsSync">用戶同步</span>';
        // 重新應用翻譯到按鈕內容
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(userBtn);
        }
    }
    if (startBtn) {
        startBtn.innerHTML = '<i class="fas fa-play me-2"></i><span data-i18n="orgSync.fullSync">完整同步</span>';
        // 重新應用翻譯到按鈕內容
        if (window.i18n && window.i18n.isReady()) {
            window.i18n.retranslate(startBtn);
        }
    }
}

// 載入組織統計
async function loadOrgStats() {
    const loadingDiv = document.getElementById('orgStatsLoading');
    const dataDiv = document.getElementById('orgStatsData');
    const errorDiv = document.getElementById('orgStatsError');
    
    // 顯示載入狀態
    loadingDiv.style.display = 'block';
    dataDiv.style.display = 'none';
    errorDiv.style.display = 'none';
    
    try {
        // 加上時間戳避免瀏覽器快取造成數字不更新
        const response = await window.AuthClient.fetch(`/api/organization/stats?t=${Date.now()}`);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const result = await response.json();
        if (result.success && result.data) {
            const data = result.data;
            
            // 更新部門統計
            document.getElementById('totalDepartments').textContent = data.departments?.total_departments || 0;
            // 更新用戶統計
            document.getElementById('totalUsers').textContent = data.users?.total_users || 0;
            
            loadingDiv.style.display = 'none';
            dataDiv.style.display = 'block';
        } else {
            throw new Error('API 返回錯誤');
        }
    } catch (error) {
        console.error('載入組織統計失敗:', error);
        loadingDiv.style.display = 'none';
        errorDiv.style.display = 'block';
    }
}


// 從模態框開始同步
async function startSyncFromModal(syncType = 'full') {
    const startBtn = syncType === 'full' ? document.getElementById('startSyncBtn') : 
        (syncType === 'departments' ? document.getElementById('startDeptSyncBtn') : document.getElementById('startUserSyncBtn'));
    const originalHtml = startBtn.innerHTML;
    
    startBtn.disabled = true;
    startBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>啟動中...';
    
    try {
        // Guard: ensure not already syncing
        try {
            const statusResp = await window.AuthClient.fetch('/api/organization/sync/status');
            if (statusResp.ok) {
                const statusJson = await statusResp.json();
                if (statusJson.success && statusJson.data && statusJson.data.is_syncing) {
                    AppUtils.showWarning(getI18n('orgSync.syncing', '同步進行中'));
                    startBtn.disabled = false;
                    startBtn.innerHTML = originalHtml;
                    return;
                }
            }
        } catch (_) {}
        
        const response = await window.AuthClient.fetch(`/api/organization/sync?sync_type=${syncType}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const result = await response.json();
        
        if (result.success) {
            // 同步啟動成功，重新載入狀態
            await loadSyncStatus();
            
            // 保存觸發用戶到localStorage，用於後續的Toast通知
            localStorage.setItem('sync_trigger_user', 'user-sync-modal');
            
            AppUtils.showSuccess(getI18n('orgSync.syncStarted', '組織架構同步已啟動'));
        } else {
            throw new Error(result.message || '同步啟動失敗');
        }
    } catch (error) {
        console.error('啟動同步失敗:', error);
        AppUtils.showError(getI18n('orgSync.startFailedPrefix', '啟動同步失敗') + '：' + error.message);
        
        startBtn.disabled = false;
        startBtn.innerHTML = originalHtml;
    }
}

// 開始同步狀態輪詢
function startSyncPolling() {
    if (syncPollingInterval) {
        clearInterval(syncPollingInterval);
    }
    
    let pollCount = 0;
    const maxPolls = 120; // 10分鐘最大輪詢時間
    
    const poll = async () => {
        try {
            const response = await window.AuthClient.fetch('/api/organization/sync/status');
            
            if (response.ok) {
                const result = await response.json();
                
                if (result.success && result.data) {
                    const data = result.data;
                    
                    if (!data.is_syncing) {
                        // 同步完成
                        clearInterval(syncPollingInterval);
                        syncPollingInterval = null;
                        
                        // 重新載入所有數據
                        await loadSyncModalData();
                        // 再次刷新統計以確保數字最新（繞過快取）
                        try { await loadOrgStats(); } catch (_) {}
                        
                        // 檢查是否是當前用戶觸發的同步
                        const triggerUser = localStorage.getItem('sync_trigger_user');
                        if (triggerUser === 'user-sync-modal') {
                            AppUtils.showSuccess(getI18n('orgSync.syncCompleted', '組織架構同步已完成！'));
                            localStorage.removeItem('sync_trigger_user');
                        }
                    } else {
                        // 僅顯示狀態指示
                        setSyncStatus('running');
                    }
                }
            }
            
            pollCount++;
                    if (pollCount >= maxPolls) {
                // 超時停止輪詢
                clearInterval(syncPollingInterval);
                syncPollingInterval = null;
                AppUtils.showWarning(getI18n('orgSync.statusTimeout', '同步狀態檢查超時，請手動刷新查看結果'));
                // 恢復按鈕
                document.getElementById('startSyncBtn').disabled = false;
                const deptBtn = document.getElementById('startDeptSyncBtn');
                const userBtn = document.getElementById('startUserSyncBtn');
                if (deptBtn) deptBtn.disabled = false;
                if (userBtn) userBtn.disabled = false;
                // 嘗試刷新統計
                try { await loadOrgStats(); } catch (_) {}
            }
        } catch (error) {
            console.error('輪詢同步狀態失敗:', error);
        }
    };
    
    // 每5秒輪詢一次
    syncPollingInterval = setInterval(poll, 5000);
}

// 保存模態框狀態到localStorage
function saveSyncModalState() {
    const modalState = {
        lastClosed: Date.now(),
        wasPolling: syncPollingInterval !== null
    };
    localStorage.setItem('sync_modal_state', JSON.stringify(modalState));
}

// 從localStorage載入模態框狀態
function loadSyncModalState() {
    try {
        const savedState = localStorage.getItem('sync_modal_state');
        if (savedState) {
            const state = JSON.parse(savedState);
            
            // 如果之前在輪詢且關閉時間不超過30秒，繼續輪詢
            const timeSinceClose = Date.now() - state.lastClosed;
            if (state.wasPolling && timeSinceClose < 30000) {
                // 先載入一次狀態，如果仍在同步則開始輪詢
                loadSyncStatus();
            }
        }
    } catch (error) {
        console.error('載入模態框狀態失敗:', error);
    }
}

// ===== 測試案例同步（UI 綁定） =====
let tcSyncSelectedTeamId = null;

async function loadTcSyncTeams() {
    try {
        const res = await window.AuthClient.fetch('/api/teams');
        if (!res.ok) return;
        const teams = await res.json();
        const sel = document.getElementById('tcSyncTeamSelect');
        sel.innerHTML = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = (window.i18n ? window.i18n.t('tcSync.pleaseSelectTeam') : '請先選擇團隊');
        sel.appendChild(placeholder);
        for (const t of teams) {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.textContent = t.name;
            sel.appendChild(opt);
        }
        sel.addEventListener('change', () => {
            tcSyncSelectedTeamId = sel.value ? parseInt(sel.value, 10) : null;
            const disabled = !tcSyncSelectedTeamId;
            document.getElementById('btn-tc-init').disabled = disabled;
            document.getElementById('btn-tc-diff').disabled = disabled;
            document.getElementById('btn-tc-full').disabled = disabled;
        });
    } catch (e) {
        console.error('載入團隊清單失敗', e);
    }
}

async function runTcSync(mode) {
    const statusEl = document.getElementById('tcSyncStatus');
    if (mode === 'diff') {
        if (!tcSyncSelectedTeamId) {
            statusEl.textContent = (window.i18n ? window.i18n.t('tcSync.pleaseSelectTeam') : '請先選擇團隊');
            return;
        }
        await loadTcDiff();
        return;
    }
    // 非 diff 模式：透過 /sync 呼叫對應模式
    if (!tcSyncSelectedTeamId) {
        statusEl.textContent = (window.i18n ? window.i18n.t('tcSync.pleaseSelectTeam') : '請先選擇團隊');
        return;
    }
    const btnMap = {
        'init': document.getElementById('btn-tc-init'),
        'diff': document.getElementById('btn-tc-diff'),
        'full-update': document.getElementById('btn-tc-full')
    };
    const btn = btnMap[mode];
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>' + (window.i18n ? window.i18n.t('tcSync.actions.running') : '執行中...');
    try {
        const url = `/api/teams/${tcSyncSelectedTeamId}/testcases/sync?mode=${encodeURIComponent(mode)}`;
        const resp = await window.AuthClient.fetch(url, { method: 'POST' });
        const json = await resp.json();
        if (resp.ok && json.success) {
            statusEl.textContent = (window.i18n ? window.i18n.t('tcSync.result.success') : '同步完成');
        } else {
            statusEl.textContent = (window.i18n ? window.i18n.t('tcSync.result.failure') : '同步失敗') + (json.detail ? `：${json.detail}` : '');
        }
    } catch (e) {
        statusEl.textContent = (window.i18n ? window.i18n.t('tcSync.result.failure') : '同步失敗') + `：${e}`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = original;
    }
}

async function loadTcDiff() {
    const statusEl = document.getElementById('tcSyncStatus');
    const container = document.getElementById('tcDiffContainer');
    container.innerHTML = '';
    try {
        statusEl.textContent = (window.i18n ? window.i18n.t('tcSync.actions.running') : '執行中...');
        const url = `/api/teams/${tcSyncSelectedTeamId}/testcases/diff`;
        const resp = await window.AuthClient.fetch(url, { method: 'GET' });
        const json = await resp.json();
        if (!resp.ok || !json.success) {
            statusEl.textContent = (window.i18n ? window.i18n.t('tcSync.result.failure') : '同步失敗') + (json.detail ? `：${json.detail}` : '');
            return;
        }
        statusEl.textContent = '';
        renderTcDiff(json);
    } catch (e) {
        statusEl.textContent = (window.i18n ? window.i18n.t('tcSync.result.failure') : '同步失敗') + `：${e}`;
    }
}

function renderTcDiff(data) {
    const escapeHtml = (s) => {
        if (s === null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };
    const container = document.getElementById('tcDiffContainer');
    const diffs = data.diffs || [];
    if (!diffs.length) {
        container.innerHTML = `<div class="alert alert-success">沒有差異</div>`;
        return;
    }
    // 轉成逐欄位的列
    const entries = [];
    diffs.forEach(d => {
        const changed = (d.fields || []).filter(f => f.different);
        const list = changed.length ? changed : (d.fields || []);
        list.forEach((f, idx) => {
            entries.push({
                test_case_number: d.test_case_number,
                status: d.status,
                field: f,
                isFirst: idx === 0
            });
        });
    });

    const rows = entries.map(e => {
        const statusLabel = e.status === 'only_local' ? '僅本地' : e.status === 'only_lark' ? '僅 Lark' : '雙方皆有變更';
        const name = `pick-${e.test_case_number}-${e.field.name}`;
        const larkChecked = e.status === 'only_lark' ? 'checked' : '';
        const localChecked = e.status === 'only_local' ? 'checked' : '';
        const lvRaw = e.field && e.field.local !== undefined ? e.field.local : null;
        const rvRaw = e.field && e.field.lark !== undefined ? e.field.lark : null;
        const lv = (lvRaw === null || lvRaw === undefined || lvRaw === '') ? '<span class="text-muted">—</span>' : (e.field.different ? `<span class="text-danger diff-value">${escapeHtml(lvRaw)}</span>` : `<span class="diff-value">${escapeHtml(lvRaw)}</span>`);
        const rv = (rvRaw === null || rvRaw === undefined || rvRaw === '') ? '<span class="text-muted">—</span>' : (e.field.different ? `<span class="text-danger diff-value">${escapeHtml(rvRaw)}</span>` : `<span class="diff-value">${escapeHtml(rvRaw)}</span>`);
        const chooseCell = `
            <div class="form-check form-check-inline">
              <input class="form-check-input" type="radio" name="${name}" value="lark" ${larkChecked}>
              <label class="form-check-label">採用 Lark</label>
            </div>
            <div class="form-check form-check-inline">
              <input class="form-check-input" type="radio" name="${name}" value="local" ${localChecked}>
              <label class="form-check-label">採用本地</label>
            </div>`;

        return `
            <tr data-tc="${e.test_case_number}" data-field="${escapeHtml(e.field.name)}">
              <td>${e.test_case_number}</td>
              <td>${statusLabel}</td>
              <td><code>${escapeHtml(e.field.name)}</code></td>
              <td>${lv}</td>
              <td>${rv}</td>
              <td>${chooseCell}</td>
            </tr>`;
    }).join('');

    container.innerHTML = `
      <div class="card">
        <div class="card-header bg-light d-flex justify-content-between align-items-center">
          <div><strong>差異清單</strong></div>
          <div class="btn-group btn-group-sm" role="group" id="tcDiffBulkActions">
            <button class="btn btn-primary" id="tcDiffSelectLark">全選採用 Lark</button>
            <button class="btn btn-secondary" id="tcDiffSelectLocal">全選採用本地</button>
          </div>
        </div>
        <div class="table-responsive">
          <table class="table table-sm table-hover mb-0">
            <thead>
              <tr><th>Test Case</th><th>狀態</th><th>欄位</th><th>本地</th><th>Lark</th><th>選擇</th></tr>
            </thead>
            <tbody>
              ${rows}
            </tbody>
          </table>
        </div>
        <div class="card-footer d-flex justify-content-end">
          <button class="btn btn-success" id="btn-tc-apply-diff">套用</button>
        </div>
      </div>`;

    // 綁定全選
    document.getElementById('tcDiffSelectLark').addEventListener('click', () => {
        container.querySelectorAll('input[type=radio][value=lark]').forEach(el => { el.checked = true; });
    });
    document.getElementById('tcDiffSelectLocal').addEventListener('click', () => {
        container.querySelectorAll('input[type=radio][value=local]').forEach(el => { el.checked = true; });
    });
    document.getElementById('btn-tc-apply-diff').addEventListener('click', applyTcDiff);
}

async function applyTcDiff() {
    const container = document.getElementById('tcDiffContainer');
    const rows = Array.from(container.querySelectorAll('tbody tr'));
    // 聚合為每個 test case 的欄位決策
    const byTc = {};
    rows.forEach(tr => {
        const tc = tr.dataset.tc;
        const field = tr.dataset.field;
        if (!tc || !field) return;
        const name = `pick-${tc}-${field}`;
        const picked = container.querySelector(`input[name=\"${name}\"]:checked`);
        if (!picked) return;
        if (!byTc[tc]) byTc[tc] = { test_case_number: tc, fields: {} };
        byTc[tc].fields[field] = picked.value; // 'lark' or 'local'
    });
    const decisions = Object.values(byTc);
    if (!decisions.length) {
        AppUtils.showWarning('請至少選擇一個欄位的採用來源');
        return;
    }
    const url = `/api/teams/${tcSyncSelectedTeamId}/testcases/diff/apply`;
    const resp = await window.AuthClient.fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decisions })
    });
    const json = await resp.json();
    if (resp.ok && json) {
        AppUtils.showSuccess(`已套用 ${json.applied || 0} 筆差異`);
        // 套用後可重新計算一次差異
        await loadTcDiff();
    } else {
        AppUtils.showError('套用差異失敗');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // 啟用按鈕事件
    const initBtn = document.getElementById('btn-tc-init');
    const diffBtn = document.getElementById('btn-tc-diff');
    const fullBtn = document.getElementById('btn-tc-full');
    if (initBtn) initBtn.addEventListener('click', () => runTcSync('init'));
    if (diffBtn) diffBtn.addEventListener('click', () => runTcSync('diff'));
    if (fullBtn) fullBtn.addEventListener('click', () => runTcSync('full-update'));

    // 當切到測試案例分頁時載入團隊清單（只載一次）
    const tcTabBtn = document.getElementById('tab-test-cases');
    const tcPane = document.getElementById('tab-pane-test-cases');
    if (tcTabBtn && tcPane) {
        tcTabBtn.addEventListener('shown.bs.tab', () => {
            console.log('[Tab Switch] Test cases tab shown');
            // 立即重新應用翻譯
            try {
                if (window.i18n && window.i18n.isReady()) {
                    console.log('[Tab Switch] Retranslating test cases pane');
                    const tcLabel = tcPane.querySelector('[data-i18n="tcSync.selectTeam"]');
                    if (tcLabel) {
                        console.log('[Tab Switch] Before translation:', tcLabel.textContent);
                        window.i18n.retranslate(tcPane);
                        console.log('[Tab Switch] After translation:', tcLabel.textContent);
                    } else {
                        console.warn('[Tab Switch] tcSync.selectTeam label not found');
                        window.i18n.retranslate(tcPane);
                    }
                } else {
                    console.warn('[Tab Switch] i18n not ready');
                }
            } catch (e) {
                console.error('[Tab Switch] Error:', e);
            }
            
            if (!tcPane.dataset.loaded) {
                loadTcSyncTeams();
                tcPane.dataset.loaded = '1';
            }
        });
    }
    
    // 當切到組織分頁時重新應用翻譯
    const orgTabBtn = document.getElementById('tab-org');
    const orgPane = document.getElementById('tab-pane-org');
    if (orgTabBtn && orgPane) {
        orgTabBtn.addEventListener('shown.bs.tab', () => {
            try {
                if (window.i18n && window.i18n.isReady()) {
                    window.i18n.retranslate(orgPane);
                }
            } catch (_) {}
        });
    }
});

// ===== 全域組織架構同步功能 =====

// 觸發全域同步
async function triggerGlobalSync() {
    const syncBtn = document.getElementById('syncOrgBtn');
    const statusDiv = document.getElementById('global-sync-status');
    
    try {
        // 顯示同步中狀態
        syncBtn.disabled = true;
        statusDiv.style.display = 'block';
        
        // 觸發全域組織同步
        const response = await window.AuthClient.fetch('/api/organization/sync?sync_type=full', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 同步開始成功
            AppUtils.showSuccess(getI18n('orgSync.syncStarted', '組織架構同步已開始'));
            
            // 開始輪詢同步狀態
            pollGlobalSyncStatus();
            
        } else {
            // 同步開始失敗
            AppUtils.showError(getI18n('orgSync.syncFailedPrefix', '同步失敗') + `: ${result.message}`);
            syncBtn.disabled = false;
            statusDiv.style.display = 'none';
        }
        
    } catch (error) {
        console.error('觸發全域同步失敗:', error);
        AppUtils.showError(getI18n('orgSync.triggerFailedPrefix', '觸發全域同步失敗') + `: ${error.message}`);
        syncBtn.disabled = false;
        statusDiv.style.display = 'none';
    }
}

// 輪詢全域同步狀態
async function pollGlobalSyncStatus() {
    const maxPolls = 60; // 最多輪詢 60 次 (5 分鐘)
    let pollCount = 0;
    
    const poll = async () => {
        try {
            const response = await window.AuthClient.fetch('/api/organization/sync/status');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const result = await response.json();
            
            if (result.success && result.data) {
                const data = result.data;
                
                if (!data.is_syncing) {
                    // 同步完成
                    const syncBtn = document.getElementById('syncOrgBtn');
                    const statusDiv = document.getElementById('global-sync-status');
                    
                    syncBtn.disabled = false;
                    statusDiv.style.display = 'none';
                    
                    // 檢查最後結果
                    if (data.last_result && data.last_result.success) {
                        AppUtils.showSuccess(getI18n('orgSync.syncCompleted', '組織架構同步完成'));
                    } else {
                        AppUtils.showWarning(getI18n('orgSync.syncCompletedWithIssues', '同步完成，但可能有部分錯誤'));
                    }
                    // 若同步管理模態框開啟，刷新其中的統計與狀態
                    const modalEl = document.getElementById('syncModal');
                    if (modalEl && modalEl.classList.contains('show')) {
                        try {
                            await loadSyncModalData();
                            await loadOrgStats();
                        } catch (_) {}
                    }
                    
                    return; // 停止輪詢
                }
                
                // 繼續輪詢
                pollCount++;
                if (pollCount < maxPolls) {
                    setTimeout(poll, 5000); // 5秒後再次檢查
                } else {
                    // 超時停止
                    document.getElementById('syncOrgBtn').disabled = false;
                    document.getElementById('global-sync-status').style.display = 'none';
                    AppUtils.showWarning(getI18n('orgSync.statusTimeout', '同步狀態檢查超時，請手動刷新頁面查看結果'));
                }
            }
            
        } catch (error) {
            console.error('檢查全域同步狀態失敗:', error);
            // 發生錯誤時也停止輪詢
            document.getElementById('syncOrgBtn').disabled = false;
            document.getElementById('global-sync-status').style.display = 'none';
        }
    };
    
    // 開始第一次輪詢
    setTimeout(poll, 2000); // 2秒後開始檢查
}





// ===== i18n helper without calling window.i18n.t =====
function getI18n(key, fallback = '') {
    const container = document.getElementById('org-sync-i18n');
    if (!container) return fallback || key;
    const el = container.querySelector(`[data-i18n="${key}"]`);
    if (el && el.textContent && el.textContent.trim().length > 0) {
        return el.textContent.trim();
    }
    return fallback || key;
}
