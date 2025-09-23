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
            
            // 在設置頁面完全禁用認證檢查（用於建立第一個使用者）
            if (currentPath === '/setup') {
                this.hideUserInfo();
                return;
            }
            
            // 先檢查系統是否需要初始化（只在非設置和非登入頁面檢查）
            if (currentPath !== '/login') {
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
                if (currentPath !== '/login') {
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
        const displayName = userInfo.name || userInfo.username || '使用者';
        const role = userInfo.role || 'user';
        const teams = Array.isArray(userInfo.teams) ? userInfo.teams : [];
        
        // 更新主要顯示區域
        if (this.userDisplayName) {
            this.userDisplayName.textContent = displayName;
        }
        
        if (this.userRoleBadge) {
            this.userRoleBadge.textContent = this.getRoleDisplayName(role);
            this.userRoleBadge.className = `badge ${this.getRoleBadgeClass(role)}`;
        }
        
        // 更新下拉選單詳細資訊
        if (this.userInfoName) {
            this.userInfoName.textContent = displayName;
        }
        
        if (this.userInfoEmail) {
            this.userInfoEmail.textContent = userInfo.email || '';
        }
        
        if (this.userInfoRole) {
            this.userInfoRole.textContent = this.getRoleDisplayName(role);
        }
        
        if (this.userInfoTeams) {
            if (teams.length > 0) {
                this.userInfoTeams.textContent = teams.join(', ');
            } else {
                this.userInfoTeams.textContent = '無';
            }
        }
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
            'admin': '管理員',
            'manager': '管理者',
            'user': '使用者',
            'guest': '訪客'
        };
        return roleMap[role] || role;
    }

    /**
     * 取得角色徽章樣式
     */
    getRoleBadgeClass(role) {
        const classMap = {
            'admin': 'bg-danger',
            'manager': 'bg-warning',
            'user': 'bg-primary',
            'guest': 'bg-secondary'
        };
        return classMap[role] || 'bg-secondary';
    }

    /**
     * 處理登出
     */
    async handleLogout() {
        try {
            // 顯示確認對話框
            if (!confirm('確定要登出嗎？')) {
                return;
            }

            // 禁用登出按鈕，避免重複點擊
            if (this.logoutBtn) {
                this.logoutBtn.disabled = true;
                this.logoutBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>登出中...';
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
                this.logoutBtn.innerHTML = '<i class="fas fa-sign-out-alt me-2"></i>登出';
            }
            
            // 顯示錯誤訊息
            this.showError('登出時發生錯誤，請稍後再試');
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