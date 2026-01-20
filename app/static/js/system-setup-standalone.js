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
                    confirmInput.setCustomValidity('密碼不一致');
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
                        this.showAlert('warning', '系統已初始化', '系統已經有 Super Admin，將重導向到登入頁面。');
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
                this.setSubmitState(true, '正在初始化系統...');
                
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
                        this.showAlert('danger', '驗證錯誤', validationError);
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
                        this.showAlert('success', '初始化成功！', result.message);
                        
                        // 3秒後重導向到登入頁面
                        setTimeout(() => {
                            window.location.href = '/login';
                        }, 3000);
                        
                    } else {
                        const errorMsg = result.error || '初始化失敗，請稍後再試';
                        this.showAlert('danger', '初始化失敗', errorMsg);
                        this.setSubmitState(false);
                    }
                    
                } catch (error) {
                    console.error('系統初始化錯誤:', error);
                    this.showAlert('danger', '系統錯誤', '初始化時發生未知錯誤，請重新整理頁面後再試');
                    this.setSubmitState(false);
                }
            }
            
            validateSetupData(data) {
                if (!data.username || data.username.length < 3) {
                    return '使用者名稱至少需要3個字符';
                }
                
                if (data.username.length > 50) {
                    return '使用者名稱不能超過50個字符';
                }
                
                if (!data.password || data.password.length < 8) {
                    return '密碼至少需要8個字符';
                }
                
                if (data.password !== data.confirm_password) {
                    return '密碼與確認密碼不一致';
                }
                
                return null;
            }
            
            setSubmitState(loading, text = null) {
                if (loading) {
                    this.submitBtn.disabled = true;
                    this.submitBtn.innerHTML = `
                        <i class="fas fa-spinner fa-spin me-2"></i>
                        <span>${text || '處理中...'}</span>
                    `;
                } else {
                    this.submitBtn.disabled = false;
                    this.submitBtn.innerHTML = `
                        <i class="fas fa-rocket me-2"></i>
                        <span>建立 Super Admin 並初始化系統</span>
                    `;
                }
            }
            
            showAlert(type, title, message) {
                const alertHtml = `
                    <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                        <strong><i class="fas ${this.getAlertIcon(type)} me-2"></i>${title}</strong>
                        <div>${message}</div>
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
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
