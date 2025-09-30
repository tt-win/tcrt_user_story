/**
 * 基礎頁面認證狀態管理
 * 處理使用者資訊顯示、登出功能等全域認證相關 UI
 */

class BaseAuthManager {
    constructor() {
        this.authClient = null;
        this.userInfoContainer = null;
        this.logoutBtn = null;
        
        this.init();
    }

    /**
     * 初始化
     */
    async init() {
        // 確保 DOM 載入完成
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setup());
        } else {
            this.setup();
        }
    }

    /**
     * 設置基礎功能
     */
    async setup() {
        try {
            // 等待 auth.js 載入
            while (!window.AuthClient) {
                await this.sleep(100);
            }

            this.authClient = window.AuthClient;
            this.setupElements();
            this.setupEventListeners();
            
            // 檢查登入狀態並更新 UI
            await this.updateAuthState();
            
        } catch (error) {
            console.error('BaseAuthManager setup error:', error);
        }
    }

    /**
     * 設置 DOM 元素
     */
    setupElements() {
        this.userInfoContainer = document.getElementById('user-info-container');
        this.logoutBtn = document.getElementById('logoutBtn');
        
        // 使用者資訊顯示元素
        this.userDisplayName = document.getElementById('user-display-name');
        this.userRoleBadge = document.getElementById('user-role-badge');
        this.userInfoName = document.getElementById('user-info-name');
        this.userInfoEmail = document.getElementById('user-info-email');
        this.userInfoRole = document.getElementById('user-info-role');
        this.userInfoTeams = document.getElementById('user-info-teams');
        this.userAvatarIcon = document.getElementById('user-avatar-icon');
    }

    /**
     * 設置事件監聽器
     */
    setupEventListeners() {
        // 登出按鈕
        if (this.logoutBtn) {
            this.logoutBtn.addEventListener('click', () => this.handleLogout());
        }

        // 監聽認證狀態變化
        window.addEventListener('authStateChanged', (event) => {
            this.updateAuthState();
        });

        // 監聽 storage 變化（跨頁籤同步）
        window.addEventListener('storage', (event) => {
            if (event.key === 'access_token' || event.key === 'user_info') {
                this.updateAuthState();
            }
        });
    }

    /**
     * 更新認證狀態
     */
    async updateAuthState() {
        try {
            const currentPath = window.location.pathname;
            const relaxedPaths = ['/login', '/first-login-setup'];
            
            // 在設置頁面完全禁用認證檢查（用於建立第一個使用者）
            if (currentPath === '/setup') {
                this.hideUserInfo();
                return;
            }
            
            // 先檢查系統是否需要初始化（只在非設置和非登入頁面檢查）
            if (!relaxedPaths.includes(currentPath)) {
                const needsSetup = await this.checkSystemInitialization();
                if (needsSetup) {
                    return; // 已經重導向到設置頁面
                }
            }
            
            // 檢查認證狀態
            const isAuthenticated = this.authClient.isAuthenticated();
            
            if (isAuthenticated) {
                await this.showUserInfo();
            } else {
                this.hideUserInfo();
                // 如果不在登入頁面，則重導向到登入頁面
                if (!relaxedPaths.includes(currentPath)) {
                    this.authClient.redirectToLogin();
                }
            }
            
        } catch (error) {
            console.error('更新認證狀態時發生錯誤:', error);
            this.hideUserInfo();
        }
    }

    /**
     * 顯示使用者資訊
     */
    async showUserInfo() {
        try {
            const userInfo = await this.authClient.getUserInfo();
            
            if (userInfo) {
                this.updateUserInfoDisplay(userInfo);
                this.userInfoContainer?.classList.remove('d-none');
            } else {
                this.hideUserInfo();
            }
            
        } catch (error) {
            console.error('取得使用者資訊時發生錯誤:', error);
            this.hideUserInfo();
        }
    }

    /**
     * 更新使用者資訊顯示
     */
    updateUserInfoDisplay(userInfo) {
        console.log('[BaseAuthManager] 更新用戶資訊顯示:', userInfo);
        
        // 優先使用 Lark 名稱，否則使用 full_name 或 username
        const displayName = userInfo.lark_name || userInfo.full_name || userInfo.name || userInfo.username || '使用者';
        const role = userInfo.role || 'user';
        const teams = Array.isArray(userInfo.accessible_teams) ? userInfo.accessible_teams :
                     Array.isArray(userInfo.teams) ? userInfo.teams : [];
        
        console.log('[BaseAuthManager] 處理後的數據 - displayName:', displayName, 'role:', role, 'teams:', teams);
        
        // 更新主要顯示區域 (header 按鈕)
        if (this.userDisplayName) {
            // 移除 data-i18n 屬性以防止翻譯系統覆蓋內容
            if (this.userDisplayName.hasAttribute('data-i18n')) {
                console.log('[BaseAuthManager] 移除 user-display-name 的 data-i18n 屬性');
                this.userDisplayName.removeAttribute('data-i18n');
            }
            this.userDisplayName.textContent = displayName;
            console.log('[BaseAuthManager] 設定 user-display-name:', displayName);
        }
        
        if (this.userRoleBadge) {
            // 移除 data-i18n 屬性以防止翻譯系統覆蓋內容
            if (this.userRoleBadge.hasAttribute('data-i18n')) {
                console.log('[BaseAuthManager] 移除 user-role-badge 的 data-i18n 屬性');
                this.userRoleBadge.removeAttribute('data-i18n');
            }
            this.userRoleBadge.textContent = this.getRoleDisplayName(role);
            this.userRoleBadge.className = `badge ${this.getRoleBadgeClass(role)}`;
            console.log('[BaseAuthManager] 設定 user-role-badge:', this.getRoleDisplayName(role));
        }
        
        // 更新下拉選單詳細資訊 (不變更，按任務要求)
        if (this.userInfoName) {
            if (this.userInfoName.hasAttribute('data-i18n')) {
                this.userInfoName.removeAttribute('data-i18n');
            }
            const dropdownName = userInfo.full_name || userInfo.name || userInfo.username || '使用者';
            this.userInfoName.textContent = dropdownName;
        }
        
        if (this.userInfoEmail) {
            if (this.userInfoEmail.hasAttribute('data-i18n')) {
                this.userInfoEmail.removeAttribute('data-i18n');
            }
            this.userInfoEmail.textContent = userInfo.email || '未設定';
        }
        
        if (this.userInfoRole) {
            if (this.userInfoRole.hasAttribute('data-i18n')) {
                this.userInfoRole.removeAttribute('data-i18n');
            }
            this.userInfoRole.textContent = this.getRoleDisplayName(role);
        }
        
        if (this.userInfoTeams) {
            if (this.userInfoTeams.hasAttribute('data-i18n')) {
                this.userInfoTeams.removeAttribute('data-i18n');
            }
            if (teams.length > 0) {
                this.userInfoTeams.textContent = teams.join(', ');
            } else {
                this.userInfoTeams.textContent = '無';
            }
        }
        
        console.log('[BaseAuthManager] 用戶資訊顯示更新完成');
    }

    /**
     * 隱藏使用者資訊
     */
    hideUserInfo() {
        this.userInfoContainer?.classList.add('d-none');
    }

    /**
     * 取得角色顯示名稱
     */
    getRoleDisplayName(role) {
        const roleMap = {
            'super_admin': '超級管理員',
            'admin': '管理員',
            'manager': '管理者',
            'user': '使用者',
            'viewer': '檢視者',
            'guest': '訪客'
        };
        return roleMap[role] || role;
    }

    /**
     * 取得角色徽章樣式
     */
    getRoleBadgeClass(role) {
        const classMap = {
            'super_admin': 'bg-danger',
            'admin': 'bg-danger',
            'manager': 'bg-warning text-dark',
            'user': 'bg-primary',
            'viewer': 'bg-info',
            'guest': 'bg-secondary'
        };
        return classMap[role] || 'bg-secondary';
    }

    /**
     * 處理登出
     */
    async handleLogout() {
        try {
            // 顯示確認對話框（優先使用 Bootstrap Modal，回退到 confirm）
            const confirmed = await this.showLogoutConfirm();
            if (!confirmed) {
                return;
            }

            // 禁用登出按鈕，避免重複點擊
            if (this.logoutBtn) {
                this.logoutBtn.disabled = true;
                const loadingText = this.getI18nText('user.menu.loggingOut', '登出中...');
                this.logoutBtn.innerHTML = `<i class="fas fa-spinner fa-spin me-2"></i>${loadingText}`;
            }

            // 執行登出
            await this.authClient.logout();
            
            // 隱藏使用者資訊
            this.hideUserInfo();
            
            // 重導向到登入頁面
            this.authClient.redirectToLogin();
            
        } catch (error) {
            console.error('登出時發生錯誤:', error);
            
            // 恢復登出按鈕
            if (this.logoutBtn) {
                this.logoutBtn.disabled = false;
                const logoutText = this.getI18nText('user.menu.logout', '登出');
                this.logoutBtn.innerHTML = `<i class="fas fa-sign-out-alt me-2"></i>${logoutText}`;
            }
            
            // 顯示錯誤訊息
            const errorMsg = this.getI18nText('user.menu.logoutError', '登出時發生錯誤，請稍後再試');
            this.showError(errorMsg);
        }
    }

    /**
     * 顯示錯誤訊息
     */
    showError(message) {
        // 使用 Bootstrap toast 或 alert 顯示錯誤
        console.error(message);
        
        // 簡單的 alert，之後可以改用更優雅的方式
        alert(message);
    }

    /**
     * 檢查系統初始化狀態
     */
    async checkSystemInitialization() {
        try {
            const response = await fetch('/api/system/initialization-check');
            const data = await response.json();
            
            if (data.needs_setup) {
                console.log('系統需要初始化，重導向到設置頁面');
                window.location.href = '/setup';
                return true;
            }
            
            return false;
            
        } catch (error) {
            console.warn('檢查系統初始化狀態時發生錯誤:', error);
            // 出錯時不阻止正常流程
            return false;
        }
    }
    
    /**
     * 顯示登出確認對話框
     */
    async showLogoutConfirm() {
        // 嘗試使用 Bootstrap Modal
        if (window.bootstrap && typeof window.bootstrap.Modal !== 'undefined') {
            return new Promise((resolve) => {
                const modalHtml = `
                    <div class="modal fade" id="logoutConfirmModal" tabindex="-1" aria-labelledby="logoutConfirmModalLabel" aria-hidden="true">
                        <div class="modal-dialog modal-dialog-centered">
                            <div class="modal-content">
                                <div class="modal-header">
                                    <h5 class="modal-title" id="logoutConfirmModalLabel">
                                        <i class="fas fa-sign-out-alt me-2 text-warning"></i>
                                        ${this.getI18nText('user.menu.confirmLogout', '確認登出')}
                                    </h5>
                                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                                </div>
                                <div class="modal-body">
                                    <p class="mb-0">${this.getI18nText('user.menu.confirmLogoutMessage', '您確定要登出嗎？')}</p>
                                </div>
                                <div class="modal-footer">
                                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                                        <i class="fas fa-times me-1"></i>
                                        ${this.getI18nText('common.cancel', '取消')}
                                    </button>
                                    <button type="button" class="btn btn-danger" id="confirmLogoutBtn">
                                        <i class="fas fa-sign-out-alt me-1"></i>
                                        ${this.getI18nText('user.menu.logout', '登出')}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
                
                // 創建模态框元素
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = modalHtml;
                const modal = tempDiv.firstElementChild;
                document.body.appendChild(modal);
                
                // 初始化 Bootstrap Modal
                const bsModal = new window.bootstrap.Modal(modal);
                
                // 設定事件監聽器
                modal.querySelector('#confirmLogoutBtn').addEventListener('click', () => {
                    bsModal.hide();
                    resolve(true);
                });
                
                modal.addEventListener('hidden.bs.modal', () => {
                    document.body.removeChild(modal);
                    resolve(false);
                });
                
                // 顯示模态框
                bsModal.show();
            });
        } else {
            // 回退到原生 confirm
            const message = this.getI18nText('user.menu.confirmLogoutMessage', '您確定要登出嗎？');
            return confirm(message);
        }
    }
    
    /**
     * 取得 i18n 文字
     */
    getI18nText(key, fallback) {
        try {
            // 嘗試使用全域 i18n
            if (window.i18n && typeof window.i18n.t === 'function') {
                const text = window.i18n.t(key);
                if (text && text !== key) {
                    return text;
                }
            }
            
            // 嘗試從 DOM 元素取得 data-i18n 屬性
            const element = document.querySelector(`[data-i18n="${key}"]`);
            if (element && element.textContent.trim()) {
                return element.textContent.trim();
            }
            
            // 返回預設值
            return fallback;
        } catch (error) {
            console.warn(`Failed to get i18n text for key: ${key}`, error);
            return fallback;
        }
    }
    
    /**
     * 顯示錯誤訊息（改善版）
     */
    showError(message) {
        console.error(message);
        
        // 嘗試使用 AppUtils 顯示 Toast
        if (window.AppUtils && typeof window.AppUtils.showError === 'function') {
            window.AppUtils.showError(message);
            return;
        }
        
        // 嘗試使用 Bootstrap Toast
        try {
            this.showBootstrapToast(message, 'error');
            return;
        } catch (error) {
            console.warn('Bootstrap Toast failed:', error);
        }
        
        // 回退到 alert
        alert(message);
    }
    
    /**
     * 顯示 Bootstrap Toast
     */
    showBootstrapToast(message, type = 'info') {
        try {
            const toastHtml = `
                <div class="toast align-items-center text-bg-${type === 'error' ? 'danger' : type} border-0" role="alert" aria-live="assertive" aria-atomic="true">
                    <div class="d-flex">
                        <div class="toast-body">
                            <i class="fas fa-${type === 'error' ? 'exclamation-circle' : 'info-circle'} me-2"></i>
                            ${message}
                        </div>
                        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                    </div>
                </div>
            `;
            
            // 尋找或創建 Toast 容器
            let toastContainer = document.getElementById('toast-container');
            if (!toastContainer) {
                toastContainer = document.createElement('div');
                toastContainer.id = 'toast-container';
                toastContainer.className = 'toast-container position-fixed top-0 end-0 p-3';
                toastContainer.style.zIndex = '1070';
                document.body.appendChild(toastContainer);
            }
            
            // 創建 Toast 元素
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = toastHtml;
            const toast = tempDiv.firstElementChild;
            toastContainer.appendChild(toast);
            
            // 初始化並顯示 Toast
            if (window.bootstrap && typeof window.bootstrap.Toast !== 'undefined') {
                const bsToast = new window.bootstrap.Toast(toast, {
                    autohide: true,
                    delay: 5000
                });
                
                toast.addEventListener('hidden.bs.toast', () => {
                    toastContainer.removeChild(toast);
                });
                
                bsToast.show();
            }
        } catch (error) {
            console.error('Failed to show Bootstrap toast:', error);
            // 回退到 alert
            alert(message);
        }
    }

    /**
     * 延遲函數
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// 頁面載入時初始化
document.addEventListener('DOMContentLoaded', () => {
    window.baseAuthManager = new BaseAuthManager();
});
