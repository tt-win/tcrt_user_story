/**
 * 認證客戶端
 * 
 * 處理使用者認證、Token 管理、自動刷新等功能
 */
class AuthClient {
    constructor() {
        this.token = null;
        this.refreshTimer = null;
        this.tokenExpiry = null;
        this.refreshThreshold = 5 * 60 * 1000; // 5分鐘前開始刷新
        this.maxRetries = 3;
        this.retryCount = 0;
        
        // 初始化
        this.loadTokenFromStorage();
        this.startTokenRefreshCycle();
        
        // 監聽頁面可見性變化
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && this.token) {
                this.checkTokenExpiry();
            }
        });
        
        // 監聽storage變化（多分頁同步）
        window.addEventListener('storage', (e) => {
            if (e.key === 'access_token' || e.key === 'token_expiry') {
                this.loadTokenFromStorage();
                this.startTokenRefreshCycle();
            }
        });
        
        console.log('[AuthClient] 認證客戶端初始化完成');
    }
    
    /**
     * 從本地儲存載入 Token
     */
    loadTokenFromStorage() {
        try {
            const token = localStorage.getItem('access_token');
            const expiry = localStorage.getItem('token_expiry');
            
            if (token && expiry) {
                this.token = token;
                this.tokenExpiry = new Date(parseInt(expiry));
                
                // 檢查 Token 是否已過期
                if (this.tokenExpiry <= new Date()) {
                    console.log('[AuthClient] Token 已過期，清除本地儲存');
                    this.clearToken();
                } else {
                    console.log('[AuthClient] 從本地儲存載入 Token 成功');
                }
            }
        } catch (error) {
            console.error('[AuthClient] 載入 Token 失敗:', error);
            this.clearToken();
        }
    }
    
    /**
     * 設定 Token
     * @param {string} token - Access Token
     * @param {number} expiresIn - 過期時間（秒）
     */
    setToken(token, expiresIn) {
        this.token = token;
        this.tokenExpiry = new Date(Date.now() + (expiresIn * 1000));
        this.retryCount = 0;
        
        // 儲存到本地儲存
        localStorage.setItem('access_token', token);
        localStorage.setItem('token_expiry', this.tokenExpiry.getTime().toString());
        
        // 重新開始刷新週期
        this.startTokenRefreshCycle();
        
        // 觸發事件
        this.dispatchAuthEvent('tokenSet', { token, expiresIn });
        
        console.log('[AuthClient] Token 已設定，過期時間:', this.tokenExpiry);
    }
    
    /**
     * 取得 Token
     * @returns {string|null} Access Token
     */
    getToken() {
        if (!this.token || !this.tokenExpiry) {
            return null;
        }
        
        // 檢查是否過期
        if (this.tokenExpiry <= new Date()) {
            console.log('[AuthClient] Token 已過期');
            this.clearToken();
            return null;
        }
        
        return this.token;
    }
    
    /**
     * 清除 Token
     */
    clearToken() {
        this.token = null;
        this.tokenExpiry = null;
        this.retryCount = 0;
        
        // 清除本地儲存
        localStorage.removeItem('access_token');
        localStorage.removeItem('token_expiry');
        
        // 停止刷新週期
        if (this.refreshTimer) {
            clearTimeout(this.refreshTimer);
            this.refreshTimer = null;
        }
        
        // 觸發事件
        this.dispatchAuthEvent('tokenCleared');
        
        console.log('[AuthClient] Token 已清除');
    }
    
    /**
     * 檢查是否已登入
     * @returns {boolean}
     */
    isAuthenticated() {
        return !!this.getToken();
    }
    
    /**
     * 檢查 Token 過期時間
     * @returns {boolean} 是否需要刷新
     */
    shouldRefreshToken() {
        if (!this.token || !this.tokenExpiry) {
            return false;
        }
        
        const now = new Date();
        const timeUntilExpiry = this.tokenExpiry.getTime() - now.getTime();
        
        return timeUntilExpiry <= this.refreshThreshold;
    }
    
    /**
     * 檢查 Token 過期並處理
     */
    checkTokenExpiry() {
        if (!this.isAuthenticated()) {
            return;
        }
        
        if (this.shouldRefreshToken()) {
            console.log('[AuthClient] Token 即將過期，開始刷新');
            this.refreshToken();
        }
    }
    
    /**
     * 開始 Token 刷新週期
     */
    startTokenRefreshCycle() {
        // 停止現有的定時器
        if (this.refreshTimer) {
            clearTimeout(this.refreshTimer);
            this.refreshTimer = null;
        }
        
        if (!this.tokenExpiry) {
            return;
        }
        
        const now = new Date();
        const timeUntilRefresh = Math.max(0, 
            this.tokenExpiry.getTime() - now.getTime() - this.refreshThreshold
        );
        
        this.refreshTimer = setTimeout(() => {
            if (this.isAuthenticated()) {
                console.log('[AuthClient] 定時刷新 Token');
                this.refreshToken();
            }
        }, timeUntilRefresh);
        
        console.log(`[AuthClient] Token 刷新週期已啟動，${Math.round(timeUntilRefresh / 1000)}秒後刷新`);
    }
    
    /**
     * 刷新 Token
     */
    async refreshToken() {
        if (!this.token) {
            console.log('[AuthClient] 無 Token，跳過刷新');
            return false;
        }
        
        if (this.retryCount >= this.maxRetries) {
            console.error('[AuthClient] Token 刷新重試次數過多，清除 Token');
            this.clearToken();
            this.redirectToLogin();
            return false;
        }
        
        try {
            console.log('[AuthClient] 開始刷新 Token...');
            
            const response = await fetch('/api/auth/refresh', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    refresh_token: this.token // 使用當前 token 作為 refresh token
                })
            });
            
            if (response.ok) {
                const data = await response.json();
                this.setToken(data.access_token, data.expires_in);
                console.log('[AuthClient] Token 刷新成功');
                
                // 觸發刷新成功事件
                this.dispatchAuthEvent('tokenRefreshed', data);
                
                return true;
            } else {
                throw new Error(`刷新失敗: ${response.status} ${response.statusText}`);
            }
            
        } catch (error) {
            this.retryCount++;
            console.error(`[AuthClient] Token 刷新失敗 (重試 ${this.retryCount}/${this.maxRetries}):`, error);
            
            if (this.retryCount >= this.maxRetries) {
                console.error('[AuthClient] Token 刷新失敗次數過多，清除 Token');
                this.clearToken();
                this.redirectToLogin();
            } else {
                // 重試延遲
                const delay = Math.min(1000 * Math.pow(2, this.retryCount), 30000);
                setTimeout(() => this.refreshToken(), delay);
            }
            
            return false;
        }
    }
    
    /**
     * 登出
     */
    async logout() {
        const token = this.getToken();
        
        if (token) {
            try {
                // 呼叫登出 API
                await fetch('/api/auth/logout', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`,
                        'Content-Type': 'application/json',
                    }
                });
                console.log('[AuthClient] 遠程登出成功');
            } catch (error) {
                console.error('[AuthClient] 遠程登出失敗:', error);
                // 繼續執行本地登出
            }
        }
        
        // 清除本地 Token
        this.clearToken();
        
        // 觸發登出事件
        this.dispatchAuthEvent('logout');
        
        console.log('[AuthClient] 登出完成');
    }
    
    /**
     * 取得使用者資訊
     */
    async getUserInfo() {
        const token = this.getToken();
        if (!token) {
            return null;
        }
        
        try {
            const response = await fetch('/api/auth/me', {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            
            if (response.ok) {
                const userInfo = await response.json();
                console.log('[AuthClient] 取得使用者資訊成功');
                return userInfo;
            } else if (response.status === 401) {
                // Token 無效，清除並重新登入
                console.log('[AuthClient] Token 無效，清除本地 Token');
                this.clearToken();
                this.redirectToLogin();
                return null;
            } else {
                throw new Error(`取得使用者資訊失敗: ${response.status}`);
            }
        } catch (error) {
            console.error('[AuthClient] 取得使用者資訊失敗:', error);
            return null;
        }
    }
    
    /**
     * 發送認證請求
     * @param {string} url - 請求 URL
     * @param {object} options - fetch 選項
     * @returns {Promise<Response>}
     */
    async fetch(url, options = {}) {
        const token = this.getToken();
        
        if (!token) {
            throw new Error('無認證 Token');
        }
        
        const headers = {
            ...options.headers,
            'Authorization': `Bearer ${token}`
        };
        
        const response = await fetch(url, { ...options, headers });
        
        // 如果回傳 401，嘗試刷新 Token 並重試一次
        if (response.status === 401 && this.shouldRefreshToken()) {
            console.log('[AuthClient] 收到 401 回應，嘗試刷新 Token');
            
            const refreshSuccess = await this.refreshToken();
            if (refreshSuccess) {
                const newToken = this.getToken();
                const newHeaders = {
                    ...options.headers,
                    'Authorization': `Bearer ${newToken}`
                };
                
                console.log('[AuthClient] 使用新 Token 重試請求');
                return fetch(url, { ...options, headers: newHeaders });
            }
        }
        
        return response;
    }
    
    /**
     * 重導向到登入頁面
     */
    redirectToLogin() {
        const currentPath = window.location.pathname + window.location.search;
        const loginUrl = `/login?redirect=${encodeURIComponent(currentPath)}`;
        
        console.log('[AuthClient] 重導向到登入頁面:', loginUrl);
        window.location.href = loginUrl;
    }
    
    /**
     * 檢查頁面是否需要認證
     */
    checkAuthRequired() {
        // 登入頁面不需要檢查認證
        const relaxedPaths = ['/login', '/first-login-setup'];
        if (relaxedPaths.includes(window.location.pathname)) {
            return;
        }

        // 如果未認證，重導向到登入頁面
        if (!this.isAuthenticated()) {
            console.log('[AuthClient] 頁面需要認證，重導向到登入頁面');
            this.redirectToLogin();
            return;
        }
        
        // 檢查 Token 是否需要刷新
        this.checkTokenExpiry();
    }
    
    /**
     * 初始化認證狀態
     */
    async initAuth() {
        try {
            // 檢查認證是否必要
            this.checkAuthRequired();
            
            if (this.isAuthenticated()) {
                // 取得並快取使用者資訊
                const userInfo = await this.getUserInfo();
                if (userInfo) {
                    this.dispatchAuthEvent('authReady', userInfo);
                    return userInfo;
                }
            }
        } catch (error) {
            console.error('[AuthClient] 初始化認證失敗:', error);
        }
        
        return null;
    }
    
    /**
     * 觸發認證事件
     * @param {string} eventName - 事件名稱
     * @param {*} detail - 事件詳情
     */
    dispatchAuthEvent(eventName, detail = null) {
        const event = new CustomEvent(eventName, { detail });
        document.dispatchEvent(event);
        console.log(`[AuthClient] 觸發事件: ${eventName}`, detail);
    }
    
    /**
     * 銷毀認證客戶端
     */
    destroy() {
        if (this.refreshTimer) {
            clearTimeout(this.refreshTimer);
            this.refreshTimer = null;
        }
        
        console.log('[AuthClient] 認證客戶端已銷毀');
    }
}

// 創建全域認證客戶端實例
window.AuthClient = new AuthClient();

// 當 DOM 載入完成時初始化認證狀態
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.AuthClient.initAuth();
    });
} else {
    window.AuthClient.initAuth();
}

// 匯出供其他模組使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AuthClient;
}
