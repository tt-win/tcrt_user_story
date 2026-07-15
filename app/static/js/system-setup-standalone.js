        /**
         * 系統設置管理器（獨立版本）
         */
        class SystemSetupManager {
            constructor() {
                this.form = document.getElementById('setup-form');
                this.submitBtn = document.getElementById('submit-btn');
                this.submitText = document.getElementById('submit-text');
                this.alertContainer = document.getElementById('alert-container');
                
                this.init();
            }
            
            init() {
                this.setupEventListeners();
                this.checkSystemStatus();
                this.translateDynamicContent();
            }
            
            setupEventListeners() {
                this.form.addEventListener('submit', (e) => this.handleSubmit(e));
                
                // 密碼確認檢查
                const passwordInput = document.getElementById('password');
                const confirmPasswordInput = document.getElementById('confirm_password');
                
                confirmPasswordInput.addEventListener('input', () => {
                    this.validatePasswordMatch();
                });
                
                passwordInput.addEventListener('input', () => {
                    this.validatePasswordMatch();
                });
            }
            
            validatePasswordMatch() {
                const password = document.getElementById('password').value;
                const confirmPassword = document.getElementById('confirm_password').value;
                const confirmInput = document.getElementById('confirm_password');
                
                if (confirmPassword && password !== confirmPassword) {
                    confirmInput.setCustomValidity(this.t('setup.passwordMismatchShort', 'Passwords do not match'));
                    confirmInput.classList.add('is-invalid');
                } else {
                    confirmInput.setCustomValidity('');
                    confirmInput.classList.remove('is-invalid');
                }
            }
            
            async checkSystemStatus() {
                try {
                    const response = await fetch('/api/system/status');
                    const data = await response.json();
                    
                    if (data.is_initialized) {
                        this.showAlert(
                            'warning',
                            this.t('setup.alreadyInitializedTitle', 'System already initialized'),
                            this.t('setup.alreadyInitializedMsg', 'A Super Admin already exists. Redirecting to the login page.')
                        );
                        setTimeout(() => {
                            window.location.href = '/login';
                        }, 3000);
                    }
                    
                } catch (error) {
                    console.warn('檢查系統狀態時發生錯誤:', error);
                    // 不阻止設置流程，可能是首次設置
                }
            }
            
            async handleSubmit(e) {
                e.preventDefault();
                
                // 禁用提交按鈕
                this.setSubmitState(true, this.t('setup.initializing', 'Initializing system...'));
                
                try {
                    const formData = new FormData(this.form);
                    const setupData = {
                        username: formData.get('username').trim(),
                        password: formData.get('password'),
                        confirm_password: formData.get('confirm_password')
                    };
                    
                    // 前端驗證
                    const validationError = this.validateSetupData(setupData);
                    if (validationError) {
                        this.showAlert('danger', this.t('setup.validationErrorTitle', 'Validation error'), validationError);
                        this.setSubmitState(false);
                        return;
                    }
                    
                    // 發送請求
                    const response = await fetch('/api/system/initialize', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(setupData)
                    });
                    
                    const result = await response.json();
                    
                    if (response.ok && result.success) {
                        this.showAlert(
                            'success',
                            this.t('setup.initSuccessTitle', 'Initialization successful!'),
                            result.message || this.t('setup.initSuccessMsg', 'System initialized successfully. Redirecting to login.')
                        );
                        
                        // 3秒後重導向到登入頁面
                        setTimeout(() => {
                            window.location.href = '/login';
                        }, 3000);
                        
                    } else {
                        const errorMsg = result.error || this.t('setup.initFailedMsg', 'Initialization failed, please try again later');
                        this.showAlert('danger', this.t('setup.initFailedTitle', 'Initialization failed'), errorMsg);
                        this.setSubmitState(false);
                    }
                    
                } catch (error) {
                    console.error('系統初始化錯誤:', error);
                    this.showAlert(
                        'danger',
                        this.t('setup.systemErrorTitle', 'System error'),
                        this.t('setup.systemErrorMsg', 'An unknown error occurred. Please refresh and try again.')
                    );
                    this.setSubmitState(false);
                }
            }
            
            validateSetupData(data) {
                if (!data.username || data.username.length < 3) {
                    return this.t('setup.usernameMin', 'Username must be at least 3 characters');
                }
                
                if (data.username.length > 50) {
                    return this.t('setup.usernameMax', 'Username cannot exceed 50 characters');
                }
                
                if (!data.password || data.password.length < 8) {
                    return this.t('setup.passwordMin', 'Password must be at least 8 characters');
                }
                
                if (data.password !== data.confirm_password) {
                    return this.t('setup.passwordMismatch', 'Password and confirmation do not match');
                }
                
                return null;
            }
            
            setSubmitState(loading, text = null) {
                if (loading) {
                    this.submitBtn.disabled = true;
                    const loadingText = this.escapeHtml(text || this.t('setup.processing', 'Processing...'));
                    this.submitBtn.innerHTML = `
                        <i class="fas fa-spinner fa-spin me-2"></i>
                        <span>${loadingText}</span>
                    `;
                } else {
                    this.submitBtn.disabled = false;
                    this.submitBtn.innerHTML = `
                        <i class="fas fa-rocket me-2"></i>
                        <span data-i18n="setup.submit">${this.escapeHtml(this.t('setup.submit', 'Create Super Admin and initialize'))}</span>
                    `;
                }
            }
            
            showAlert(type, title, message) {
                const alertHtml = `
                    <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                        <strong><i class="fas ${this.getAlertIcon(type)} me-2"></i>${this.escapeHtml(title)}</strong>
                        <div>${this.escapeHtml(message)}</div>
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="${this.escapeHtml(this.t('common.close', 'Close'))}"></button>
                    </div>
                `;
                
                this.alertContainer.innerHTML = alertHtml;
                this.alertContainer.scrollIntoView({ behavior: 'smooth' });
            }
            
            getAlertIcon(type) {
                const icons = {
                    'success': 'fa-check-circle',
                    'danger': 'fa-exclamation-triangle',
                    'warning': 'fa-exclamation-circle',
                    'info': 'fa-info-circle'
                };
                return icons[type] || 'fa-info-circle';
            }

            t(key, fallback, params = {}) {
                return window.i18n?.t(key, params, fallback) || fallback;
            }

            escapeHtml(value) {
                return String(value || '').replace(/[&<>"']/g, (character) => ({
                    '&': '&amp;',
                    '<': '&lt;',
                    '>': '&gt;',
                    '"': '&quot;',
                    "'": '&#039;'
                }[character]));
            }

            translateDynamicContent() {
                document.title = this.t('setup.pageTitle', 'System Setup - Test Case Repository Web Tool');
                if (!this.submitBtn.disabled) {
                    this.setSubmitState(false);
                }
                this.validatePasswordMatch();
            }
        }
        
        /**
         * 切換密碼顯示/隱藏
         */
        function togglePassword(inputId) {
            const input = document.getElementById(inputId);
            const eyeIcon = document.getElementById(`${inputId}-eye`);
            
            if (input.type === 'password') {
                input.type = 'text';
                eyeIcon.className = 'fas fa-eye-slash';
            } else {
                input.type = 'password';
                eyeIcon.className = 'fas fa-eye';
            }
        }
        
        // 頁面載入完成後初始化
        document.addEventListener('DOMContentLoaded', () => {
            window.setupManager = new SystemSetupManager();
        });

        document.addEventListener('i18nReady', () => window.setupManager?.translateDynamicContent());
        document.addEventListener('languageChanged', () => window.setupManager?.translateDynamicContent());
