class LoginManager {
    constructor() {
        this.form = document.getElementById('loginForm');
        this.submitButton = document.getElementById('loginBtn');
        this.buttonText = document.getElementById('loginBtnText');
        this.buttonLoading = document.getElementById('loginBtnLoading');
        this.usernameInput = document.getElementById('username');
        this.passwordInput = document.getElementById('password');
        this.togglePasswordBtn = document.getElementById('togglePassword');
        this.togglePasswordIcon = document.getElementById('togglePasswordIcon');
        this.usernameStep = document.getElementById('usernameStep');
        this.passwordStep = document.getElementById('passwordStep');
        this.stepIndicator = document.getElementById('loginStepIndicator');
        this.backButton = document.getElementById('backToUsername');
        this.alertContainer = document.getElementById('alert-container');

        this.currentStep = 1;
        this.selectedAccount = null;
        if (this.submitButton) {
            this.submitButton.dataset.loading = 'false';
        }

        this.init();
    }

    async init() {
        const needsSetup = await this.checkSystemInitialization();
        if (needsSetup) {
            return;
        }

        this.switchToStep(1, { reset: true, focus: true });
        this.initializeEventListeners();
        this.checkExistingAuth();
    }

    initializeEventListeners() {
        this.form.addEventListener('submit', (event) => this.handleSubmit(event));

        if (this.togglePasswordBtn) {
            this.togglePasswordBtn.addEventListener('click', () => this.togglePasswordVisibility());
        }

        if (this.passwordInput) {
            this.passwordInput.addEventListener('keypress', (e) => {
                if (this.currentStep === 2 && e.key === 'Enter' && !this.isLoading()) {
                    this.handleLogin();
                }
            });
            this.passwordInput.addEventListener('input', () => {
                this.passwordInput.classList.remove('is-invalid');
            });
        }

        if (this.usernameInput) {
            this.usernameInput.addEventListener('keypress', (e) => {
                if (this.currentStep === 1 && e.key === 'Enter') {
                    e.preventDefault();
                    this.processUsernameStage();
                }
            });
            this.usernameInput.addEventListener('input', () => {
                this.usernameInput.classList.remove('is-invalid');
            });
        }

        if (this.backButton) {
            this.backButton.addEventListener('click', () => {
                this.switchToStep(1, { focus: true });
            });
        }
    }

    async handleSubmit(event) {
        event.preventDefault();
        if (this.currentStep === 1) {
            await this.processUsernameStage();
        } else {
            await this.handleLogin();
        }
    }

    async checkExistingAuth() {
        try {
            const response = await window.AuthClient.fetch('/api/auth/me', {
                headers: {
                    'Authorization': `Bearer ${window.AuthClient?.getToken() || ''}`
                }
            });

            if (response.ok) {
                const urlParams = new URLSearchParams(window.location.search);
                const redirectTo = urlParams.get('redirect') || '/';
                window.location.href = redirectTo;
            }
        } catch (error) {
            console.log('用戶未登入，顯示登入頁面');
        }
    }

    async processUsernameStage() {
        if (this.isLoading()) return;

        const username = (this.usernameInput.value || '').trim();
        this.clearErrors();

        if (!username) {
            this.showFieldError(this.usernameInput, 'Please enter username or email');
            return;
        }

        this.setLoading(true, { showSpinner: false });

        try {
            const response = await fetch('/api/auth/pre-login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username_or_email: username })
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Unable to verify account status');
            }

            if (!data.user_exists) {
                this.showFieldError(this.usernameInput, data.message || 'Corresponding account not found');
                return;
            }

            if (!data.is_active) {
                this.showAlert(data.message || 'Account has been deactivated, please contact administrator', 'danger');
                return;
            }

            const normalizedUsername = data.username || username;

            if (data.first_login) {
                const redirectUsername = encodeURIComponent(normalizedUsername);
                window.location.href = `/first-login-setup?username=${redirectUsername}`;
                return;
            }

            this.selectedAccount = {
                username: normalizedUsername,
                full_name: data.full_name || ''
            };

            this.usernameInput.value = normalizedUsername;
            this.usernameInput.readOnly = true;
            this.passwordInput.value = '';
            this.switchToStep(2, { focus: true });

        } catch (error) {
            console.error('登入前檢查失敗:', error);
            this.showAlert(error.message || 'Pre-login check failed, please try later', 'danger');
        } finally {
            this.setLoading(false);
        }
    }

    async handleLogin() {
        if (this.isLoading()) return;

        const username = (this.selectedAccount?.username || this.usernameInput.value || '').trim();
        const password = this.passwordInput.value;

        this.clearErrors();

        if (!username) {
            this.showAlert('Please enter username first', 'danger');
            this.switchToStep(1, { focus: true });
            return;
        }

        if (!password) {
            this.showFieldError(this.passwordInput, 'Please enter password');
            return;
        }

        this.setLoading(true);

        try {
            // 檢查是否支援 Web Crypto API
            const useEncryption = window.CryptoUtils && window.CryptoUtils.isWebCryptoAvailable();

            let requestBody = {
                username_or_email: username,
                remember_me: this.form.querySelector('#rememberMe')?.checked || false
            };

            if (useEncryption) {
                // 使用加密方式
                console.log('[Login] 使用加密認證方式');

                // 步驟 1: 取得 challenge
                const challengeResponse = await fetch('/api/auth/challenge', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username_or_email: username })
                });

                if (!challengeResponse.ok) {
                    throw new Error('Failed to get challenge');
                }

                const challengeData = await challengeResponse.json();

                // 檢查是否支援加密登入
                if (challengeData.supports_encryption && challengeData.salt && challengeData.iterations) {
                    console.log('[Login] 使用者支援加密登入');

                    const challenge = challengeData.challenge;
                    const salt = challengeData.salt;
                    const iterations = challengeData.iterations;

                    // 步驟 2: 計算 password_hash
                    const passwordHash = await window.CryptoUtils.calculateChallengeResponse(
                        password,
                        salt,
                        challenge,
                        iterations
                    );

                    // 使用加密方式登入
                    requestBody.password = '';  // 不傳送明文密碼
                    requestBody.password_hash = passwordHash;
                    requestBody.challenge = challenge;
                } else {
                    // 使用者尚未升級到 PBKDF2，降級到明文登入
                    console.warn('[Login] 使用者尚未支援加密登入，使用明文方式 (將自動升級)');
                    requestBody.password = password;
                }
            } else {
                // 降級到明文方式 (舊版相容)
                console.warn('[Login] Web Crypto API 不可用，使用明文認證方式 (不安全)');
                requestBody.password = password;
            }

            const response = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody)
            });
            const data = await response.json();

            if (response.ok && data.access_token) {
                if (data.first_login) {
                    const redirectUsername = encodeURIComponent(username);
                    window.location.href = `/first-login-setup?username=${redirectUsername}`;
                    return;
                }

                if (window.AuthClient) {
                    window.AuthClient.setToken(data.access_token, data.expires_in);
                }
                
                // Save user role to localStorage for permission checks
                if (data.user && data.user.role) {
                    localStorage.setItem('user_role', data.user.role);
                }

                this.showAlert('Login successful! Redirecting...', 'success');
                setTimeout(() => {
                    const urlParams = new URLSearchParams(window.location.search);
                    const redirectTo = urlParams.get('redirect') || '/';
                    window.location.href = redirectTo;
                }, 600);

            } else {
                this.handleLoginError(response.status, data);
            }

        } catch (error) {
            console.error('登入請求失敗:', error);
            this.showAlert('Network error, check connection and retry', 'danger');
        } finally {
            this.setLoading(false);
        }
    }

    handleLoginError(status, data) {
        switch (status) {
            case 401:
                this.showAlert('Username or password incorrect', 'danger');
                this.passwordInput.focus();
                break;
            case 403:
                this.showAlert('Account deactivated, contact administrator', 'warning');
                break;
            case 429:
                this.showAlert('Too many login attempts, try later', 'warning');
                break;
            case 500:
                this.showAlert('Server error, contact administrator', 'danger');
                break;
            default:
                this.showAlert(data?.detail || 'Login failed, please retry', 'danger');
        }
    }

    togglePasswordVisibility() {
        const isPassword = this.passwordInput.type === 'password';
        this.passwordInput.type = isPassword ? 'text' : 'password';
        if (this.togglePasswordIcon) {
            this.togglePasswordIcon.className = isPassword ? 'fas fa-eye-slash' : 'fas fa-eye';
        }
    }

    setLoading(loading, options = {}) {
        this.submitButton.disabled = loading;
        this.submitButton.dataset.loading = loading ? 'true' : 'false';

        const useSpinner = this.currentStep === 2 && options.showSpinner !== false;
        this.buttonText.classList.toggle('d-none', loading);
        if (useSpinner) {
            this.buttonLoading.classList.toggle('d-none', !loading);
        } else {
            this.buttonLoading.classList.add('d-none');
        }
    }

    isLoading() {
        return this.submitButton.dataset.loading === 'true';
    }

    clearErrors() {
        [this.usernameInput, this.passwordInput].forEach(input => {
            input.classList.remove('is-invalid');
        });
    }

    showFieldError(input, message) {
        input.classList.add('is-invalid');
        this.showAlert(message, 'danger');
        input.focus();
    }

    showAlert(message, type = 'info') {
        if (!this.alertContainer) return;
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} alert-floating alert-dismissible fade show`;
        alert.innerHTML = `
            <i class="fas fa-${this.getAlertIcon(type)} me-2"></i>
            ${this.escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        this.alertContainer.appendChild(alert);
        setTimeout(() => {
            if (alert.parentElement) {
                alert.remove();
            }
        }, 5000);
    }

    getAlertIcon(type) {
        const iconMap = {
            success: 'check-circle',
            danger: 'exclamation-circle',
            warning: 'exclamation-triangle',
            info: 'info-circle'
        };
        return iconMap[type] || 'info-circle';
    }

    async checkSystemInitialization() {
        try {
            const response = await fetch('/api/system/initialization-check');
            const data = await response.json();
            if (data.needs_setup) {
                this.showAlert('System needs initialization, redirecting to setup...', 'info');
                setTimeout(() => {
                    window.location.href = '/setup';
                }, 1200);
                return true;
            }
        } catch (error) {
            console.warn('檢查系統初始化狀態時發生錯誤:', error);
        }
        return false;
    }

    switchToStep(step, options = {}) {
        this.currentStep = step;
        const isStep2 = step === 2;

        this.passwordStep.classList.toggle('d-none', !isStep2);
        this.backButton.classList.toggle('d-none', !isStep2);
        if (this.togglePasswordBtn) {
            this.togglePasswordBtn.classList.toggle('d-none', !isStep2);
        }

        if (this.stepIndicator) {
            if (isStep2) {
                const displayName = this.selectedAccount?.full_name || this.selectedAccount?.username || '';
                const suffix = displayName ? `(${this.escapeHtml(displayName)})` : '';
                this.stepIndicator.innerHTML = `<i class="fas fa-circle me-2"></i>Step 2: Enter Password ${suffix}`;
            } else {
                this.stepIndicator.innerHTML = '<i class="fas fa-circle me-2"></i>Step 1: Enter Account';
            }
        }

        if (isStep2) {
            this.buttonText.innerHTML = '<i class="fas fa-sign-in-alt me-2"></i>登入';
            if (options.focus) {
                setTimeout(() => this.passwordInput?.focus(), 60);
            }
        } else {
            this.usernameInput.readOnly = false;
            if (options.reset) {
                this.usernameInput.value = '';
                this.selectedAccount = null;
            }
            this.passwordInput.value = '';
            this.buttonText.innerHTML = '<i class="fas fa-arrow-right me-2"></i>下一步';
            if (options.focus !== false) {
                setTimeout(() => this.usernameInput?.focus(), 60);
            }
        }
    }

    escapeHtml(str) {
        return String(str || '').replace(/[&<>"']/g, (m) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        }[m]));
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new LoginManager();
});