let teams = [];
let currentEditTeam = null;
let automationHubEntryEnabled = true;

document.addEventListener('DOMContentLoaded', function() {
    initTeamManagement();
    applyTeamManagementUiVisibility();
    showRelocatedFeatureNoticeIfNeeded();
});

// team-management 頁面按鈕（例如「組織與系統設定」連結）可視控制
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

        // 系統日誌入口（ui-config 對應 organization_management:manage，僅 super_admin；
        // 後端另以 require_super_admin 防護）
        const systemLogsLink = document.getElementById('systemLogsLink');
        if (systemLogsLink && map['systemLogsLink']) {
            systemLogsLink.parentElement.classList.remove('d-none');
        }

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

// 已搬遷分頁的舊錨點相容性提示：若使用者透過舊書籤/文件連結帶著
// #tab-pane-personnel 等舊 hash 進入本頁，顯示一次性提示導向新頁面，
// 避免誤以為功能消失（原本這些分頁掛在本頁「組織與系統設定」modal 內，
// 現已搬至 /organization-management）。
const RELOCATED_TAB_ANCHORS = [
    'tab-pane-personnel',
    'tab-pane-org',
    'tab-pane-service-management',
    'tab-pane-mcp-token',
    'tab-pane-org-automation-infra',
];

function showRelocatedFeatureNoticeIfNeeded() {
    const hash = (window.location.hash || '').replace(/^#/, '');
    if (!RELOCATED_TAB_ANCHORS.includes(hash)) return;
    const notice = document.getElementById('relocatedFeatureNotice');
    if (notice) notice.classList.remove('d-none');
}

function initTeamManagement() {
    // 綁定事件監聽器
    document.getElementById('createTeamBtn').addEventListener('click', showCreateTeamModal);
    document.getElementById('refreshBtn').addEventListener('click', loadTeams);
    document.getElementById('saveTeamBtn').addEventListener('click', saveTeam);
    document.getElementById('validateLarkBtn').addEventListener('click', validateLarkConnection);
    // 審計記錄和團隊統計現在使用下拉選單中的 <a> 標籤，不需要額外的事件監聽器
    // 「組織與系統設定」已改為導向 /organization-management 的連結（<a>），
    // 不再是開啟本頁 modal 的按鈕，故不需要 click listener。

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

        automationHubEntryEnabled = await AppUtils.getAutomationHubEntryEnabled();

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

    teams = [];
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
                                    ${automationHubEntryEnabled ? `<li>
                                        <button class="dropdown-item" type="button" onclick="enterTeamWithPage(${team.id}, 'automation')">
                                            <i class="fas fa-robot me-2"></i>${(window.i18n && window.i18n.isReady()) ? window.i18n.t('navigation.automationHub') : 'Automation Hub'}
                                        </button>
                                    </li>` : ''}
                                    <li>
                                        <button class="dropdown-item" type="button" onclick="enterTeamWithPage(${team.id}, 'usm')">
                                            <i class="fas fa-project-diagram me-2"></i>User Story Map
                                        </button>
                                    </li>
                                    <li><hr class="dropdown-divider"></li>
                                    <li>
                                        <button class="dropdown-item" type="button" onclick="openAppTokenModal(${team.id}, '${escapeHtml(team.name)}')">
                                            <i class="fas fa-key me-2"></i><span data-i18n="appToken.menuLabel">App Tokens</span>
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
        let url = '/api/teams/';
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
        'automation': '/automation-hub',
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
    // Coerce non-strings (ids are often numbers). Do not use !text — 0 is valid.
    if (text == null || text === '') return '';
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return String(text).replace(/[&<>"']/g, function(m) { return map[m]; });
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
