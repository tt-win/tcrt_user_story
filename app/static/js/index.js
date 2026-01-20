let teams = [];
let uiPermissions = {};

document.addEventListener('DOMContentLoaded', async function() {
    await applyIndexUiVisibility();
    loadTeams();
});

async function applyIndexUiVisibility() {
    try {
        if (!window.AuthClient) return;
        const resp = await window.AuthClient.fetch('/api/permissions/ui-config?page=index');
        if (!resp.ok) return;
        const config = await resp.json();
        uiPermissions = config.components || {};

        const settingsBtn = document.getElementById('teamSettingsButton');
        if (settingsBtn) {
            settingsBtn.style.display = uiPermissions.teamSettingsButton ? '' : 'none';
        }
    } catch (e) {
        console.error('Failed to apply UI visibility:', e);
        // On error, hide protected elements
        const settingsBtn = document.getElementById('teamSettingsButton');
        if (settingsBtn) settingsBtn.style.display = 'none';
    }
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
        console.error('載入團隊失敗:', error);
        const errorMsg = window.i18n ? window.i18n.t('messages.loadFailed') : '載入失敗';
        AppUtils.showError(errorMsg + '：' + error.message);
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
}

function hideLoading() {
    document.getElementById('loading-state').style.display = 'none';
    document.getElementById('teams-section').style.display = 'block';
}

function showNoTeams() {
    const noTeamsSection = document.getElementById('no-teams-section');
    if (uiPermissions.createFirstTeamCard) {
        noTeamsSection.innerHTML = `
        <div class="row justify-content-center">
            <div class="col-md-6 col-lg-4">
                <div class="card text-center add-team-card" onclick="goToTeamManagement()" style="cursor: pointer;">
                    <div class="card-body py-5">
                        <div class="bg-primary text-white rounded-circle d-flex align-items-center justify-content-center mx-auto mb-3" 
                             style="width: 64px; height: 64px; font-size: 24px;">
                            <i class="fas fa-plus"></i>
                        </div>
                        <h5 class="text-primary mb-2" data-i18n="team.createTeam">新增團隊</h5>
                        <p class="text-muted small mb-0" data-i18n="team.createFirstTeamHint">
                            建立團隊並設定 Lark 資料來源
                        </p>
                    </div>
                </div>
            </div>
        </div>`;
    } else {
        noTeamsSection.innerHTML = `
        <div class="text-center py-5">
            <i class="fas fa-users fa-3x text-muted mb-3"></i>
            <h5 class="text-muted" data-i18n="team.noTeamsViewer">尚無已建立團隊</h5>
        </div>`;
    }
    noTeamsSection.style.display = 'block';
    document.getElementById('teams-list').style.display = 'none';
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(noTeamsSection);
    }
}

function showTeamsList() {
    document.getElementById('no-teams-section').style.display = 'none';
    document.getElementById('teams-list').style.display = 'block';
}

function renderTeamCards() {
    const container = document.getElementById('teams-container');

    // 現有團隊卡片
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
                                ${escapeHtml(team.description || (window.i18n ? window.i18n.t('common.noDescription') : '無描述'))}
                            </p>
                        </div>
                    </div>
                    <div class="mt-auto pt-2">
                        <div class="mb-2">
                            <small class="text-muted">
                                <i class="fas fa-table me-1"></i><span data-i18n="team.linked">已連結 Lark 資料源</span>
                            </small>
                        </div>
                        <div class="d-grid gap-2">
                        <button class="btn btn-primary" onclick="event.stopPropagation(); selectTeamForTestCases(${team.id})">
                            <i class="fas fa-list-check me-2"></i><span data-i18n="navigation.testCaseManagement">Test Case 管理</span>
                        </button>
                        <button class="btn btn-secondary" onclick="event.stopPropagation(); selectTeamForTestRuns(${team.id})">
                            <i class="fas fa-play-circle me-2"></i><span data-i18n="navigation.testRunManagement">Test Run 管理</span>
                        </button>
                        <button class="btn btn-info" onclick="event.stopPropagation(); selectTeamForUserStoryMap(${team.id})">
                            <i class="fas fa-project-diagram me-2"></i><span data-i18n="navigation.userStoryMap">User Story Map</span>
                        </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `).join('');

    // 新增團隊卡片 (有權限才顯示)
    let addTeamCard = '';
    if (uiPermissions.addMoreTeamsCard) {
        addTeamCard = `
        <div class="col-md-6 col-lg-4 mb-4">
            <div class="card h-100 add-team-card text-center" onclick="goToTeamManagement()" style="cursor: pointer;">
                <div class="card-body d-flex flex-column justify-content-center">
                    <div class="text-primary rounded-circle d-flex align-items-center justify-content-center mx-auto mb-3" 
                         style="width: 48px; height: 48px; font-size: 18px; border: 2px dashed var(--tr-primary);">
                        <i class="fas fa-plus"></i>
                    </div>
                    <h6 class="text-primary mb-1"><span data-i18n="team.addTeams">新增團隊</span></h6>
                    <small class="text-muted"><span data-i18n="team.addTeamsHint">建立新的團隊專案</span></small>
                </div>
            </div>
        </div>
    `;
    }

    container.innerHTML = teamsHtml + addTeamCard;

    // Retranslate the newly added content
    if (window.i18n && window.i18n.isReady()) {
        window.i18n.retranslate(container);
    }
}

function selectTeamForTestCases(teamId) {
    const team = teams.find(t => t.id === teamId);
    if (!team) return;

    // 儲存選擇的團隊
    if (AppUtils && AppUtils.setCurrentTeam) {
        AppUtils.setCurrentTeam(team);
        // 先導向到 Test Case Sets 頁面讓用戶選擇 Set（不顯示 Toast）
        window.location.href = '/test-case-sets';
    }
}

function selectTeamForTestRuns(teamId) {
    const team = teams.find(t => t.id === teamId);
    if (!team) return;

    // 儲存選擇的團隊
    if (AppUtils && AppUtils.setCurrentTeam) {
        AppUtils.setCurrentTeam(team);
        // 直接導向測試執行管理（不顯示 Toast）
        window.location.href = '/test-run-management';
    }
}

function selectTeamForUserStoryMap(teamId) {
    const team = teams.find(t => t.id === teamId);
    if (!team) return;

    // 儲存選擇的團隊
    if (AppUtils && AppUtils.setCurrentTeam) {
        AppUtils.setCurrentTeam(team);
        // 直接導向 User Story Map（不顯示 Toast）
        window.location.href = `/user-story-map/${team.id}`;
    }
}

function goToTeamManagement() {
    window.location.href = '/team-management';
}

function getTeamInitials(name) {
    if (!name) return 'T';

    return name
        .split(' ')
        .map(word => word.charAt(0).toUpperCase())
        .slice(0, 2)
        .join('');
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

// 添加團隊卡片 hover 效果
document.addEventListener('DOMContentLoaded', function() {
    // CSS hover 效果將通過樣式表定義
});

// 更新頁面標題翻譯
function updatePageTitle() {
    const pageTitle = window.i18n ? window.i18n.t('common.home') : '首頁';
    const siteTitle = window.i18n ? window.i18n.t('navigation.title') : 'Test Case Repository';
    document.title = `${pageTitle} - ${siteTitle} Web Tool`;
}

// 監聽 i18n 初始化和語言變更事件
document.addEventListener('i18nReady', updatePageTitle);
document.addEventListener('languageChanged', updatePageTitle);
