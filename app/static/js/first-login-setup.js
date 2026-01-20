class FirstLoginSetupManager {
    constructor() {
        this.form = document.getElementById('firstLoginForm');
        this.usernameInput = document.getElementById('username');
        this.infoBox = document.getElementById('firstLoginInfo');
        this.newPasswordInput = document.getElementById('newPassword');
        this.confirmPasswordInput = document.getElementById('confirmPassword');
        this.submitButton = document.getElementById('setupBtn');
        this.buttonText = document.getElementById('setupBtnText');
        this.buttonLoading = document.getElementById('setupBtnLoading');
        this.alertContainer = document.getElementById('alert-container');
        this.username = '';
        this.init();
    }

    async init() {
        if (await this.checkSystemInitialization()) {
            return;
        }

        this.username = new URLSearchParams(window.location.search).get('username') || '';
        if (!this.username) {
            this.showAlert('danger', 'Missing user information, please start from login page');
            this.disableForm();
            return;
        }

        this.usernameInput.value = this.username;
        this.infoBox.innerHTML = `<strong>Account:</strong> ${this.escapeHtml(this.username)}<br>Please set the new password for the account.`;

        this.attachEvents();
    }

    attachEvents() {
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));

        document.querySelectorAll('[data-toggle="password"]').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetId = btn.getAttribute('data-target');
                const input = document.getElementById(targetId);
                if (!input) return;
                const isPassword = input.type === 'password';
                input.type = isPassword ? 'text' : 'password';
                const icon = btn.querySelector('i');
                if (icon) {
                    icon.className = isPassword ? 'fas fa-eye-slash' : 'fas fa-eye';
                }
            });
        });

        // 即時密碼驗證
        this.newPasswordInput.addEventListener('input', () => this.validatePassword());
        this.confirmPasswordInput.addEventListener('input', () => this.validatePassword());
    }

    async checkSystemInitialization() {
        try {
            const response = await fetch('/api/system/initialization-check');
            const data = await response.json();
            if (data.needs_setup) {
                window.location.href = '/setup';
                return true;
            }
        } catch (error) {
            console.warn('初始化檢查失敗', error);
        }
        return false;
    }

    validatePassword() {
        const newPassword = this.newPasswordInput.value;
        const confirmPassword = this.confirmPasswordInput.value;

        // 更新長度要求
        this.updateRequirement('req-length', newPassword.length >= 8);

        // 更新複雜度要求：至少一個大寫、一個小寫、一個數字
        const hasUpper = /[A-Z]/.test(newPassword);
        const hasLower = /[a-z]/.test(newPassword);
        const hasDigit = /\d/.test(newPassword);
        const meetsComplexity = hasUpper && hasLower && hasDigit;
        this.updateRequirement('req-complexity', meetsComplexity);

        // 更新確認匹配（如果有確認密碼）
        if (confirmPassword) {
            const matches = newPassword === confirmPassword;
            // 可以添加一個額外的 li 來顯示匹配，但為了簡單，只在提交時檢查
        }

        // 更新提交按鈕狀態
        const allValid = this.checkAllRequirements();
        this.submitButton.disabled = !allValid || !newPassword || newPassword !== confirmPassword;
    }

    updateRequirement(reqId, isValid) {
        const req = document.getElementById(reqId);
        if (!req) return;

        const icon = req.querySelector('i');
        if (isValid) {
            req.classList.add('text-success');
            req.classList.remove('text-danger');
            icon.className = 'fas fa-check-circle';
        } else {
            req.classList.add('text-danger');
            req.classList.remove('text-success');
            icon.className = 'fas fa-times-circle';
        }
    }

    checkAllRequirements() {
        const requirements = ['req-length', 'req-complexity'];
        return requirements.every(reqId => {
            const req = document.getElementById(reqId);
            return req && req.classList.contains('text-success');
        });
    }

    async handleSubmit(event) {
        event.preventDefault();
        if (this.isLoading()) return;

        const newPassword = this.newPasswordInput.value.trim();
        const confirmPassword = this.confirmPasswordInput.value.trim();

        if (!newPassword || newPassword.length < 8) {
            this.showAlert('danger', 'New password must be at least 8 characters long');
            this.newPasswordInput.focus();
            return;
        }

        // 檢查複雜度
        const hasUpper = /[A-Z]/.test(newPassword);
        const hasLower = /[a-z]/.test(newPassword);
        const hasDigit = /\d/.test(newPassword);
        if (!hasUpper || !hasLower || !hasDigit) {
            this.showAlert('warning', 'Recommended to use a mix of uppercase, lowercase, and numbers for better security');
            // 不強制，但可以選擇是否繼續
        }

        if (newPassword !== confirmPassword) {
            this.showAlert('danger', 'The two password entries do not match');
            this.confirmPasswordInput.focus();
            return;
        }

        this.setLoading(true);

        try {
            const response = await fetch('/api/auth/first-login/setup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: this.username,
                    new_password: newPassword,
                    confirm_password: confirmPassword
                })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Setup failed, please check input data');
            }

            this.showAlert('success', 'Password set successfully! Logging you in...', 2000);

            if (window.AuthClient && data.access_token) {
                window.AuthClient.setToken(data.access_token, data.expires_in);
            }

            setTimeout(() => {
                window.location.href = '/';
            }, 800);
        } catch (error) {
            console.error('首次登入設定失敗', error);
            this.showAlert('danger', error.message || 'Setup failed, please try later');
        } finally {
            this.setLoading(false);
        }
    }

    disableForm() {
        this.form.querySelectorAll('input, button').forEach(el => el.disabled = true);
    }

    setLoading(loading) {
        this.submitButton.disabled = loading;
        this.buttonText.classList.toggle('d-none', loading);
        this.buttonLoading.classList.toggle('d-none', !loading);
    }

    isLoading() {
        return this.submitButton.disabled && !this.buttonLoading.classList.contains('d-none');
    }

    showAlert(level, message, timeout = 4000) {
        if (!this.alertContainer) return;
        const wrapper = document.createElement('div');
        wrapper.className = `alert alert-${level} alert-dismissible fade show alert-floating`;
        wrapper.innerHTML = `
            <div>${this.escapeHtml(message)}</div>
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        this.alertContainer.appendChild(wrapper);
        if (timeout > 0) {
            setTimeout(() => {
                const alert = new bootstrap.Alert(wrapper);
                alert.close();
            }, timeout);
        }
    }

    escapeHtml(str) {
        return String(str || '').replace(/[&<>"']/g, (m) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
        }[m]));
    }
}

window.addEventListener('DOMContentLoaded', () => {
    new FirstLoginSetupManager();
});
