/**
 * 個人資料頁面管理器
 * 處理個人資料顯示、編輯基本資料、修改密碼等功能
 */
class ProfileManager {
    constructor() {
        this.authClient = null;
        this.userData = null;
        
        // 表單元素
        this.profileForm = null;
        this.passwordForm = null;
        
        // 按鈕和載入狀態
        this.saveProfileBtn = null;
        this.changePasswordBtn = null;
        
        // 密碼欄位
        this.currentPasswordInput = null;
        this.newPasswordInput = null;
        this.confirmPasswordInput = null;
        
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
     * 設置
     */
    async setup() {
        try {
            console.log('[ProfileManager] 開始設置');
            
            // 等待 AuthClient 載入
            let attempts = 0;
            while (!window.AuthClient) {
                attempts++;
                console.log(`[ProfileManager] 等待 AuthClient (嘗試 ${attempts})`);
                if (attempts > 50) { // 5秒後超時
                    throw new Error('AuthClient 載入超時');
                }
                await this.sleep(100);
            }

            console.log('[ProfileManager] AuthClient 已載入');
            this.authClient = window.AuthClient;
            
            console.log('[ProfileManager] 設置 DOM 元素');
            this.setupElements();
            
            console.log('[ProfileManager] 設置事件監聽器');
            this.setupEventListeners();
            
            // 檢查登入狀態並載入資料
            console.log('[ProfileManager] 開始載入用戶資料');
            await this.loadUserProfile();
            
        } catch (error) {
            console.error('ProfileManager setup error:', error);
            this.showError('初始化失敗，請重新載入頁面');
        }
    }

    /**
     * 設置 DOM 元素
     */
    setupElements() {
        // 表單
        this.profileForm = document.getElementById('profileForm');
        this.passwordForm = document.getElementById('passwordForm');
        
        // 按鈕
        this.saveProfileBtn = document.getElementById('saveProfileBtn');
        this.changePasswordBtn = document.getElementById('changePasswordBtn');
        
        // 密碼欄位
        this.currentPasswordInput = document.getElementById('currentPassword');
        this.newPasswordInput = document.getElementById('newPassword');
        this.confirmPasswordInput = document.getElementById('confirmPassword');
        
        // 密碼顯示切換按鈕
        this.setupPasswordToggles();
    }

    /**
     * 設置密碼顯示/隱藏切換
     */
    setupPasswordToggles() {
        const toggles = [
            { btn: 'toggleCurrentPassword', input: 'currentPassword', icon: 'toggleCurrentPasswordIcon' },
            { btn: 'toggleNewPassword', input: 'newPassword', icon: 'toggleNewPasswordIcon' },
            { btn: 'toggleConfirmPassword', input: 'confirmPassword', icon: 'toggleConfirmPasswordIcon' }
        ];

        toggles.forEach(toggle => {
            const btn = document.getElementById(toggle.btn);
            const input = document.getElementById(toggle.input);
            const icon = document.getElementById(toggle.icon);
            
            if (btn && input && icon) {
                btn.addEventListener('click', () => {
                    const isPassword = input.type === 'password';
                    input.type = isPassword ? 'text' : 'password';
                    icon.className = isPassword ? 'fas fa-eye-slash' : 'fas fa-eye';
                });
            }
        });
    }

    /**
     * 設置事件監聽器
     */
    setupEventListeners() {
        // 個人資料表單提交
        if (this.profileForm) {
            this.profileForm.addEventListener('submit', (e) => this.handleProfileSubmit(e));
        }

        // 修改密碼表單提交
        if (this.passwordForm) {
            this.passwordForm.addEventListener('submit', (e) => this.handlePasswordSubmit(e));
        }

        // 密碼欄位變更監聽
        if (this.newPasswordInput) {
            this.newPasswordInput.addEventListener('input', () => this.validatePassword());
        }
        
        if (this.confirmPasswordInput) {
            this.confirmPasswordInput.addEventListener('input', () => this.validatePassword());
        }

        // 清除錯誤狀態
        this.setupErrorClearListeners();
    }

    /**
     * 設置錯誤清除監聽器
     */
    setupErrorClearListeners() {
        const formInputs = document.querySelectorAll('.form-control');
        formInputs.forEach(input => {
            input.addEventListener('input', () => {
                input.classList.remove('is-invalid');
                const feedback = input.parentElement.querySelector('.invalid-feedback');
                if (feedback) {
                    feedback.textContent = '';
                }
            });
        });
    }

    /**
     * 載入使用者資料
     */
    async loadUserProfile() {
        try {
            console.log('[ProfileManager] 檢查認證狀態');
            
            if (!this.authClient.isAuthenticated()) {
                console.log('[ProfileManager] 使用者未登入，重導向到登入頁面');
                // 未登入，重導向到登入頁面
                this.authClient.redirectToLogin();
                return;
            }

            console.log('[ProfileManager] 使用者已認證，開始載入資料');
            this.showLoadingState();

            const response = await this.authClient.fetch('/api/users/me');
            console.log('[ProfileManager] API 回應狀態:', response.status);
            
            if (!response.ok) {
                if (response.status === 401) {
                    console.log('[ProfileManager] 收到 401，重導向到登入頁面');
                    this.authClient.redirectToLogin();
                    return;
                }
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            this.userData = await response.json();
            console.log('[ProfileManager] 成功載入使用者資料:', this.userData);
            
            this.displayUserProfile(this.userData);
            this.populateProfileForm(this.userData);

        } catch (error) {
            console.error('載入使用者資料失敗:', error);
            this.showError('載入使用者資料失敗，請稍後再試');
        } finally {
            this.hideLoadingState();
        }
    }

    /**
     * 顯示使用者資料
     */
    displayUserProfile(userData) {
        console.log('[ProfileManager] 開始顯示用戶資料:', userData);
        
        // 基本資訊顯示
        const displayName = userData.full_name || userData.username;
        const username = `@${userData.username}`;
        const email = userData.email || '未設定';
        
        console.log('[ProfileManager] 設定顯示名稱:', displayName);
        this.setElementText('profile-display-name', displayName);
        
        console.log('[ProfileManager] 設定用戶名:', username);
        this.setElementText('profile-username', username);
        
        console.log('[ProfileManager] 設定電子信箱:', email);
        this.setElementText('profile-email', email);
        
        // 角色顯示
        console.log('[ProfileManager] 設定用戶角色:', userData.role);
        this.displayUserRole(userData.role);
        
        // 團隊顯示
        const teams = userData.teams && userData.teams.length > 0 
            ? userData.teams.join(', ') 
            : '無';
        console.log('[ProfileManager] 設定團隊:', teams);
        this.setElementText('profile-teams', teams);
        
        // 時間顯示
        const createdAt = this.formatDateTime(userData.created_at);
        const lastLogin = userData.last_login_at 
            ? this.formatDateTime(userData.last_login_at) 
            : '從未登入';
            
        console.log('[ProfileManager] 設定註冊時間:', createdAt);
        this.setElementText('profile-created-at', createdAt);
        
        console.log('[ProfileManager] 設定最後登入:', lastLogin);
        this.setElementText('profile-last-login', lastLogin);
        
        console.log('[ProfileManager] 用戶資料顯示完成');
    }

    /**
     * 顯示使用者角色
     */
    displayUserRole(role) {
        console.log('[ProfileManager] displayUserRole 被呼叫，角色:', role);
        
        const roleBadge = document.getElementById('profile-role-badge');
        console.log('[ProfileManager] profile-role-badge 元素:', roleBadge);
        
        if (!roleBadge) {
            console.warn('[ProfileManager] 找不到 profile-role-badge 元素');
            return;
        }

        const roleMap = {
            'super_admin': { text: '超級管理員', class: 'badge-admin' },
            'admin': { text: '管理員', class: 'badge-admin' },
            'manager': { text: '管理者', class: 'badge-manager' },
            'user': { text: '使用者', class: 'badge-user' },
            'viewer': { text: '檢視者', class: 'badge-viewer' }
        };

        const roleInfo = roleMap[role] || { text: role, class: 'badge-user' };
        console.log('[ProfileManager] 角色資訊:', roleInfo);
        
        // 移除 data-i18n 屬性以防止翻譯系統覆蓋內容
        if (roleBadge.hasAttribute('data-i18n')) {
            console.log('[ProfileManager] 移除 profile-role-badge 的 data-i18n 屬性:', roleBadge.getAttribute('data-i18n'));
            roleBadge.removeAttribute('data-i18n');
        }
        
        roleBadge.textContent = roleInfo.text;
        roleBadge.className = `badge badge-role ${roleInfo.class}`;
        
        console.log('[ProfileManager] 角色設定完成，內容:', roleBadge.textContent, '類型:', roleBadge.className);
    }

    /**
     * 填入個人資料表單
     */
    populateProfileForm(userData) {
        if (!this.profileForm) return;

        const fullNameInput = this.profileForm.querySelector('#fullName');
        const emailInput = this.profileForm.querySelector('#email');

        if (fullNameInput) {
            fullNameInput.value = userData.full_name || '';
        }
        
        if (emailInput) {
            emailInput.value = userData.email || '';
        }
    }

    /**
     * 處理個人資料表單提交
     */
    async handleProfileSubmit(e) {
        e.preventDefault();
        
        if (this.isSubmitting('profile')) return;

        try {
            this.setSubmittingState('profile', true);
            this.clearFormErrors(this.profileForm);

            const formData = new FormData(this.profileForm);
            const data = {
                full_name: formData.get('full_name')?.trim() || null,
                email: formData.get('email')?.trim() || null
            };

            const response = await this.authClient.fetch('/api/users/me', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (!response.ok) {
                this.handleApiError(response.status, result, this.profileForm);
                return;
            }

            // 更新成功
            this.userData = result;
            this.displayUserProfile(result);
            this.showSuccess('個人資料更新成功');

        } catch (error) {
            console.error('更新個人資料失敗:', error);
            this.showError('更新個人資料失敗，請稍後再試');
        } finally {
            this.setSubmittingState('profile', false);
        }
    }

    /**
     * 處理密碼修改表單提交
     */
    async handlePasswordSubmit(e) {
        e.preventDefault();
        
        if (this.isSubmitting('password')) return;

        // 客戶端驗證
        if (!this.validatePasswordForm()) {
            return;
        }

        try {
            this.setSubmittingState('password', true);
            this.clearFormErrors(this.passwordForm);

            const formData = new FormData(this.passwordForm);
            const data = {
                current_password: formData.get('current_password'),
                new_password: formData.get('new_password')
            };

            const response = await this.authClient.fetch('/api/users/me/password', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();

            if (!response.ok) {
                this.handleApiError(response.status, result, this.passwordForm);
                return;
            }

            // 密碼修改成功
            this.passwordForm.reset();
            this.hidePasswordStrength();
            this.showSuccess('密碼修改成功');

        } catch (error) {
            console.error('修改密碼失敗:', error);
            this.showError('修改密碼失敗，請稍後再試');
        } finally {
            this.setSubmittingState('password', false);
        }
    }

    /**
     * 驗證密碼表單
     */
    validatePasswordForm() {
        const currentPassword = this.currentPasswordInput.value;
        const newPassword = this.newPasswordInput.value;
        const confirmPassword = this.confirmPasswordInput.value;

        let isValid = true;

        // 檢查目前密碼
        if (!currentPassword) {
            this.showFieldError(this.currentPasswordInput, '請輸入目前密碼');
            isValid = false;
        }

        // 檢查新密碼長度
        if (newPassword.length < 8) {
            this.showFieldError(this.newPasswordInput, '新密碼至少需要 8 個字符');
            isValid = false;
        }

        // 檢查密碼確認
        if (newPassword !== confirmPassword) {
            this.showFieldError(this.confirmPasswordInput, '兩次輸入的密碼不相符');
            isValid = false;
        }

        // 檢查新舊密碼是否相同
        if (currentPassword && newPassword && currentPassword === newPassword) {
            this.showFieldError(this.newPasswordInput, '新密碼不能與目前密碼相同');
            isValid = false;
        }

        return isValid;
    }

    /**
     * 驗證密碼強度（即時）
     */
    validatePassword() {
        const currentPassword = this.currentPasswordInput.value;
        const newPassword = this.newPasswordInput.value;
        const confirmPassword = this.confirmPasswordInput.value;

        // 顯示/隱藏密碼強度指示器
        const strengthDiv = document.getElementById('passwordStrength');
        if (newPassword || confirmPassword) {
            strengthDiv?.classList.remove('d-none');
        } else {
            strengthDiv?.classList.add('d-none');
            this.changePasswordBtn.disabled = true;
            return;
        }

        // 檢查各項要求
        this.updateRequirement('req-length', newPassword.length >= 8);
        this.updateRequirement('req-different', 
            currentPassword && newPassword && currentPassword !== newPassword);
        this.updateRequirement('req-match', 
            newPassword && confirmPassword && newPassword === confirmPassword);

        // 更新按鈕狀態
        const allValid = this.checkAllRequirements();
        this.changePasswordBtn.disabled = !allValid || !currentPassword;
    }

    /**
     * 更新需求項目狀態
     */
    updateRequirement(reqId, isValid) {
        const req = document.getElementById(reqId);
        if (!req) return;

        const icon = req.querySelector('i');
        if (isValid) {
            req.classList.add('valid');
            req.classList.remove('invalid');
            icon.className = 'fas fa-check-circle';
        } else {
            req.classList.add('invalid');
            req.classList.remove('valid');
            icon.className = 'fas fa-times-circle';
        }
    }

    /**
     * 檢查所有密碼需求是否滿足
     */
    checkAllRequirements() {
        const requirements = ['req-length', 'req-different', 'req-match'];
        return requirements.every(reqId => {
            const req = document.getElementById(reqId);
            return req && req.classList.contains('valid');
        });
    }

    /**
     * 隱藏密碼強度指示器
     */
    hidePasswordStrength() {
        const strengthDiv = document.getElementById('passwordStrength');
        strengthDiv?.classList.add('d-none');
        this.changePasswordBtn.disabled = true;
    }

    /**
     * 處理 API 錯誤
     */
    handleApiError(status, result, form) {
        switch (status) {
            case 400:
                // 驗證錯誤或密碼錯誤
                if (result.detail) {
                    if (result.detail.includes('目前密碼')) {
                        this.showFieldError(this.currentPasswordInput, result.detail);
                    } else if (result.detail.includes('email') || result.detail.includes('電子信箱')) {
                        const emailInput = form.querySelector('#email');
                        if (emailInput) {
                            this.showFieldError(emailInput, result.detail);
                        }
                    } else {
                        this.showError(result.detail);
                    }
                } else {
                    this.showError('請求格式錯誤');
                }
                break;
            case 409:
                // 衝突錯誤（如 email 重複）
                const emailInput = form.querySelector('#email');
                if (emailInput) {
                    this.showFieldError(emailInput, result.detail || '電子信箱已被使用');
                }
                break;
            case 422:
                // 驗證錯誤
                if (result.detail && Array.isArray(result.detail)) {
                    result.detail.forEach(error => {
                        const field = error.loc && error.loc.length > 1 ? error.loc[1] : null;
                        const input = form.querySelector(`[name="${field}"]`);
                        if (input) {
                            this.showFieldError(input, error.msg);
                        }
                    });
                } else {
                    this.showError('輸入資料格式錯誤');
                }
                break;
            default:
                this.showError(result.detail || '操作失敗，請稍後再試');
        }
    }

    /**
     * 顯示欄位錯誤
     */
    showFieldError(input, message) {
        input.classList.add('is-invalid');
        const feedback = input.parentElement.querySelector('.invalid-feedback');
        if (feedback) {
            feedback.textContent = message;
        }
        input.focus();
    }

    /**
     * 清除表單錯誤
     */
    clearFormErrors(form) {
        const inputs = form.querySelectorAll('.form-control.is-invalid');
        inputs.forEach(input => {
            input.classList.remove('is-invalid');
            const feedback = input.parentElement.querySelector('.invalid-feedback');
            if (feedback) {
                feedback.textContent = '';
            }
        });
    }

    /**
     * 設置提交狀態
     */
    setSubmittingState(type, submitting) {
        if (type === 'profile') {
            this.saveProfileBtn.disabled = submitting;
            const textSpan = document.getElementById('saveProfileBtnText');
            const loadingSpan = document.getElementById('saveProfileBtnLoading');
            
            if (submitting) {
                textSpan?.classList.add('d-none');
                loadingSpan?.classList.remove('d-none');
            } else {
                textSpan?.classList.remove('d-none');
                loadingSpan?.classList.add('d-none');
            }
        } else if (type === 'password') {
            this.changePasswordBtn.disabled = submitting;
            const textSpan = document.getElementById('changePasswordBtnText');
            const loadingSpan = document.getElementById('changePasswordBtnLoading');
            
            if (submitting) {
                textSpan?.classList.add('d-none');
                loadingSpan?.classList.remove('d-none');
            } else {
                textSpan?.classList.remove('d-none');
                loadingSpan?.classList.add('d-none');
                // 重新評估按鈕狀態
                this.validatePassword();
            }
        }
    }

    /**
     * 檢查是否正在提交
     */
    isSubmitting(type) {
        if (type === 'profile') {
            return this.saveProfileBtn.disabled;
        } else if (type === 'password') {
            return this.changePasswordBtn.disabled;
        }
        return false;
    }

    /**
     * 顯示載入狀態
     */
    showLoadingState() {
        // 可以在這裡添加全域載入指示器
        console.log('Loading user profile...');
    }

    /**
     * 隱藏載入狀態
     */
    hideLoadingState() {
        // 隱藏全域載入指示器
        console.log('User profile loaded.');
    }

    /**
     * 設置元素文字內容
     */
    setElementText(elementId, text) {
        const element = document.getElementById(elementId);
        console.log(`[ProfileManager] setElementText('${elementId}', '${text}') - element found:`, !!element);
        if (element) {
            // 移除 data-i18n 屬性以防止翻譯系統覆蓋內容
            if (element.hasAttribute('data-i18n')) {
                console.log(`[ProfileManager] 移除 ${elementId} 的 data-i18n 屬性:`, element.getAttribute('data-i18n'));
                element.removeAttribute('data-i18n');
            }
            
            element.textContent = text;
            console.log(`[ProfileManager] 已設置 ${elementId} 的內容為:`, text);
        } else {
            console.warn(`[ProfileManager] 找不到元素 ID: ${elementId}`);
        }
    }

    /**
     * 格式化日期時間
     */
    formatDateTime(dateTimeString) {
        try {
            const date = new Date(dateTimeString);
            return date.toLocaleString('zh-TW', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch (error) {
            return dateTimeString;
        }
    }

    /**
     * 顯示成功訊息
     */
    showSuccess(message) {
        if (window.AppUtils && typeof window.AppUtils.showSuccess === 'function') {
            window.AppUtils.showSuccess(message);
        } else {
            console.log('SUCCESS:', message);
            // 簡單的成功提示
            this.showSimpleToast(message, 'success');
        }
    }

    /**
     * 顯示錯誤訊息
     */
    showError(message) {
        if (window.AppUtils && typeof window.AppUtils.showError === 'function') {
            window.AppUtils.showError(message);
        } else {
            console.error('ERROR:', message);
            // 簡單的錯誤提示
            this.showSimpleToast(message, 'error');
        }
    }

    /**
     * 簡單的 Toast 提示
     */
    showSimpleToast(message, type = 'info') {
        // 創建簡單的 toast 提示
        const toast = document.createElement('div');
        toast.className = `alert alert-${type === 'error' ? 'danger' : type === 'success' ? 'success' : 'info'} 
                         position-fixed top-0 end-0 m-3`;
        toast.style.zIndex = '1070';
        toast.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="fas fa-${type === 'error' ? 'exclamation-circle' : 'check-circle'} me-2"></i>
                ${message}
                <button type="button" class="btn-close ms-auto" onclick="this.parentElement.parentElement.remove()"></button>
            </div>
        `;
        
        document.body.appendChild(toast);
        
        // 自動移除
        setTimeout(() => {
            if (toast.parentElement) {
                toast.remove();
            }
        }, 5000);
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
    window.profileManager = new ProfileManager();
});