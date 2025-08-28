/*!
 * AssigneeSelector - Lark 通訊錄聯絡人選擇元件
 * 提供下拉式搜尋選單，支援即時搜尋和本地快取
 */

class AssigneeSelector {
    constructor(element, options = {}) {
        this.element = typeof element === 'string' ? document.querySelector(element) : element;
        if (!this.element) {
            throw new Error('AssigneeSelector: 找不到目標元素');
        }
        
        // 預設選項
        this.options = {
            teamId: null,
            placeholder: window.i18n?.t('testRun.enterAssigneeName') || '輸入執行者姓名',
            searchPlaceholder: window.i18n?.t('testRun.searchContacts') || '搜尋聯絡人...',
            noResultsText: window.i18n?.t('testRun.noContactsFound') || '找不到符合條件的聯絡人',
            loadingText: window.i18n?.t('common.loading') || '載入中...',
            minSearchLength: 1,
            maxResults: 10,
            debounceMs: 300,
            allowCustomValue: false,  // 是否允許輸入自訂值（非聯絡人）
            showAvatar: true,
            onSelect: null,
            onClear: null,
            onError: null,
            ...options
        };
        
        // 內部狀態
        this.contacts = [];
        this.filteredContacts = [];
        this.selectedContact = null;
        this.isOpen = false;
        this.searchTerm = '';
        this.currentIndex = -1;
        this.loading = false;
        this.debounceTimer = null;
        this.cache = new Map(); // API 結果快取
        this.originalValue = ''; // 存儲原來的值
        
        // 初始化
        this.init();
        this.setupI18nWatch();
    }
    
    init() {
        this.createHTML();
        this.bindEvents();
        // 保存原來的值
        this.originalValue = this.originalInput.value || '';
        // 將原始 input 既有的值同步到顯示輸入框，避免初始化後顯示為空白
        if (this.originalInput && typeof this.originalInput.value === 'string' && this.originalInput.value.trim() !== '') {
            this.setValue(this.originalInput.value);
        }
        this.loadContacts(); // 預載聯絡人列表
    }
    
    createHTML() {
        // 隱藏原始 input
        this.originalInput = this.element;
        this.originalInput.style.display = 'none';
        
        // 創建容器
        this.container = document.createElement('div');
        this.container.className = 'assignee-selector-container position-relative';
        
        // 創建顯示輸入框
        this.displayInput = document.createElement('input');
        this.displayInput.type = 'text';
        this.displayInput.className = this.originalInput.className || 'form-control form-control-sm';
        this.displayInput.placeholder = this.options.placeholder;
        this.displayInput.autocomplete = 'off';
        
        // 創建下拉選單容器
        this.dropdown = document.createElement('div');
        this.dropdown.className = 'assignee-selector-dropdown position-absolute w-100 bg-white border rounded shadow-sm';
        this.dropdown.style.cssText = `
            top: 100%;
            left: 0;
            z-index: 1050;
            max-height: 300px;
            overflow-y: auto;
            display: none;
        `;
        
        // 創建載入指示器
        this.loadingIndicator = document.createElement('div');
        this.loadingIndicator.className = 'p-2 text-center text-muted small';
        this.loadingIndicator.innerHTML = `
            <i class="fas fa-spinner fa-spin me-1"></i>
            ${this.options.loadingText}
        `;
        
        // 組裝 HTML
        this.container.appendChild(this.displayInput);
        this.container.appendChild(this.dropdown);
        
        // 插入到原始 input 後面
        this.originalInput.parentNode.insertBefore(this.container, this.originalInput.nextSibling);
        
        // 添加 CSS 樣式
        this.addStyles();
    }

    updateLocalizedTexts() {
        try {
            if (window.i18n && typeof window.i18n.t === 'function') {
                // 重新抓取多語字串
                this.options.placeholder = window.i18n.t('testRun.enterAssigneeName') || this.options.placeholder;
                this.options.searchPlaceholder = window.i18n.t('testRun.searchContacts') || this.options.searchPlaceholder;
                this.options.noResultsText = window.i18n.t('testRun.noContactsFound') || this.options.noResultsText;
                this.options.loadingText = window.i18n.t('common.loading') || this.options.loadingText;
                // 套用到輸入框與載入指示器
                if (this.displayInput) this.displayInput.placeholder = this.options.placeholder;
                if (this.loadingIndicator) this.loadingIndicator.innerHTML = `
                    <i class="fas fa-spinner fa-spin me-1"></i>
                    ${this.options.loadingText}
                `;
                // 若下拉開啟中，重新渲染以更新「無結果」文字
                if (this.isOpen) this.renderDropdown();
            }
        } catch (_) {}
    }

    setupI18nWatch() {
        try {
            const maybeUpdate = () => this.updateLocalizedTexts();
            // 立即嘗試一次（處理 i18n 已就緒的情況）
            maybeUpdate();
            // 若提供 isReady，等就緒後更新一次
            if (window.i18n && typeof window.i18n.isReady === 'function' && !window.i18n.isReady()) {
                const timer = setInterval(() => {
                    if (window.i18n.isReady && window.i18n.isReady()) {
                        clearInterval(timer);
                        maybeUpdate();
                    }
                }, 200);
                // 最多等 5 秒
                setTimeout(() => clearInterval(timer), 5000);
            }
            // 若有事件 API，監聽語言切換
            if (window.i18n && typeof window.i18n.on === 'function') {
                try { window.i18n.on('languageChanged', maybeUpdate); } catch (_) {}
                try { window.i18n.on('loaded', maybeUpdate); } catch (_) {}
            }
        } catch (_) {}
    }
    
    addStyles() {
        // 動態添加必要的 CSS 樣式
        const styleId = 'assignee-selector-styles';
        if (!document.getElementById(styleId)) {
            const style = document.createElement('style');
            style.id = styleId;
            style.textContent = `
                .assignee-selector-container {
                    position: relative;
                }
                
                .assignee-selector-dropdown {
                    border-top: none !important;
                    border-top-left-radius: 0 !important;
                    border-top-right-radius: 0 !important;
                }
                
                .assignee-selector-item {
                    padding: 0.5rem 0.75rem;
                    cursor: pointer;
                    border-bottom: 1px solid #f8f9fa;
                    transition: background-color 0.15s ease;
                }
                
                .assignee-selector-item:hover,
                .assignee-selector-item.active {
                    background-color: #e9ecef;
                }
                
                .assignee-selector-item:last-child {
                    border-bottom: none;
                }
                
                .assignee-selector-avatar {
                    width: 24px;
                    height: 24px;
                    border-radius: 50%;
                    object-fit: cover;
                    flex-shrink: 0;
                }
                
                .assignee-selector-info {
                    flex-grow: 1;
                    min-width: 0;
                }
                
                 .assignee-selector-name {
                     font-weight: 500;
                     color: #212529;
                     margin-bottom: 0.125rem;
                     white-space: nowrap;
                     overflow: hidden;
                     text-overflow: ellipsis;
                     text-align: left;
                 }
                
                .assignee-selector-email {
                    font-size: 0.875rem;
                    color: #6c757d;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }
                
                .assignee-selector-no-results {
                    padding: 1rem;
                    text-align: center;
                    color: #6c757d;
                    font-style: italic;
                }
            `;
            document.head.appendChild(style);
        }
    }
    
    bindEvents() {
        // 輸入事件
        this.displayInput.addEventListener('input', (e) => {
            this.handleInput(e.target.value);
        });
        
        // 焦點事件
        this.displayInput.addEventListener('focus', () => {
            this.handleFocus();
        });
        
        // 鍵盤導航
        this.displayInput.addEventListener('keydown', (e) => {
            this.handleKeydown(e);
        });

        // 失焦時處理輸入值
        this.displayInput.addEventListener('blur', () => {
            const val = (this.displayInput.value || '').trim();
            if (!val) {
                // 如果輸入為空，恢復原來的值
                this.restoreOriginalValue();
            } else if (!this.selectedContact) {
                // 如果有輸入但沒有選擇聯絡人，恢復原來的值
                this.restoreOriginalValue();
            } else if (this.options.allowCustomValue && (this.selectedContact.name !== val && this.selectedContact.display_name !== val)) {
                // 若允許自訂值且輸入值與選擇的聯絡人不匹配，提交目前值
                this.setValue(val);
                if (this.options.onSelect) {
                    this.options.onSelect({ id: null, name: val, display_name: val });
                }
                this.originalInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });
        
        // 點擊外部關閉
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) {
                this.close();
            }
        });
        
        // 下拉選單點擊
        this.dropdown.addEventListener('click', (e) => {
            const item = e.target.closest('.assignee-selector-item');
            if (item && item.dataset.contactId) {
                this.selectContact(item.dataset.contactId);
            }
        });
        
        // 響應視窗調整
        window.addEventListener('resize', () => {
            if (this.isOpen) {
                this.updateDropdownPosition();
            }
        });
    }
    
    async loadContacts(query = '') {
        if (!this.options.teamId) {
            console.warn('AssigneeSelector: teamId 未設定');
            return;
        }
        
        // 檢查快取
        const cacheKey = `contacts_${this.options.teamId}_${query}`;
        if (this.cache.has(cacheKey)) {
            this.contacts = this.cache.get(cacheKey);
            this.filterContacts(query);
            return;
        }
        
        this.setLoading(true);
        
        try {
            const url = query 
                ? `/api/teams/${this.options.teamId}/contacts/search/suggestions?q=${encodeURIComponent(query)}&limit=${this.options.maxResults}`
                : `/api/teams/${this.options.teamId}/contacts?limit=${this.options.maxResults}`;
            
            const response = await fetch(url);
            const result = await response.json();
            
            if (result.success) {
                const contacts = query ? result.data.suggestions : result.data.contacts;
                this.contacts = contacts || [];
                
                // 快取結果
                this.cache.set(cacheKey, this.contacts);
                
                this.filterContacts(query);
            } else {
                this.handleError(result.message || '載入聯絡人失敗');
            }
        } catch (error) {
            console.error('AssigneeSelector: 載入聯絡人失敗', error);
            this.handleError('載入聯絡人失敗');
        } finally {
            this.setLoading(false);
        }
    }
    
    handleInput(value) {
        this.searchTerm = value;
        
        // 清除之前的計時器
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
        }
        
        // 防抖搜尋
        this.debounceTimer = setTimeout(() => {
            if (this.searchTerm.length >= this.options.minSearchLength) {
                this.loadContacts(this.searchTerm);
            } else {
                this.filterContacts('');
            }
            this.open();
        }, this.options.debounceMs);
        
        // 清空輸入時不立即恢復，等待 blur 事件處理
    }
    
    handleFocus() {
        // 如果有原值，用原值進行搜尋
        if (this.originalValue.trim()) {
            this.searchTerm = this.originalValue;
            this.loadContacts(this.originalValue);
        } else {
            // 如果沒有原值，載入所有聯絡人
            if (!this.contacts.length) {
                this.loadContacts();
            }
        }
        this.open();
    }
    
    handleKeydown(e) {
        if (!this.isOpen) {
            if (e.key === 'ArrowDown' || e.key === 'Enter') {
                e.preventDefault();
                this.open();
            }
            return;
        }
        
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.navigateDown();
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.navigateUp();
                break;
            case 'Enter':
                e.preventDefault();
                if (this.currentIndex >= 0 && this.filteredContacts[this.currentIndex]) {
                    this.selectContact(this.filteredContacts[this.currentIndex].id);
                }
                break;
            case 'Escape':
                e.preventDefault();
                this.close();
                break;
            case 'Tab':
                this.close();
                break;
        }
    }
    
    filterContacts(query) {
        if (!query) {
            this.filteredContacts = this.contacts.slice(0, this.options.maxResults);
        } else {
            const lowerQuery = query.toLowerCase();
            this.filteredContacts = this.contacts.filter(contact => 
                contact.name.toLowerCase().includes(lowerQuery) ||
                contact.email.toLowerCase().includes(lowerQuery)
            ).slice(0, this.options.maxResults);
        }
        
        this.renderDropdown();
    }
    
    renderDropdown() {
        this.dropdown.innerHTML = '';
        
        if (this.loading) {
            this.dropdown.appendChild(this.loadingIndicator);
            return;
        }
        
        if (!this.filteredContacts.length) {
            const noResults = document.createElement('div');
            noResults.className = 'assignee-selector-no-results';
            noResults.textContent = this.options.noResultsText;
            this.dropdown.appendChild(noResults);
            return;
        }
        
        this.filteredContacts.forEach((contact, index) => {
            const item = document.createElement('div');
            item.className = 'assignee-selector-item d-flex align-items-center gap-2';
            item.dataset.contactId = contact.id;
            
            if (index === this.currentIndex) {
                item.classList.add('active');
            }
            
            // 頭像
            if (this.options.showAvatar && contact.avatar) {
                const avatar = document.createElement('img');
                avatar.src = contact.avatar;
                avatar.className = 'assignee-selector-avatar';
                avatar.alt = contact.name;
                avatar.onerror = () => {
                    avatar.style.display = 'none';
                };
                item.appendChild(avatar);
            } else if (this.options.showAvatar) {
                // 預設頭像
                const defaultAvatar = document.createElement('div');
                defaultAvatar.className = 'assignee-selector-avatar bg-secondary d-flex align-items-center justify-content-center text-white';
                defaultAvatar.style.fontSize = '0.75rem';
                defaultAvatar.textContent = contact.name.charAt(0).toUpperCase();
                item.appendChild(defaultAvatar);
            }
            
            // 聯絡人資訊
            const info = document.createElement('div');
            info.className = 'assignee-selector-info';
            
            const name = document.createElement('div');
            name.className = 'assignee-selector-name';
            name.textContent = contact.name;
            
            const email = document.createElement('div');
            email.className = 'assignee-selector-email';
            email.textContent = contact.email;
            
            info.appendChild(name);
            if (contact.email) {
                info.appendChild(email);
            }
            
            item.appendChild(info);
            this.dropdown.appendChild(item);
        });
    }
    
    open() {
        if (this.isOpen) return;
        
        this.isOpen = true;
        this.dropdown.style.display = 'block';
        this.updateDropdownPosition();
        
        // 重置導航索引
        this.currentIndex = -1;
    }
    
    close() {
        if (!this.isOpen) return;
        
        this.isOpen = false;
        this.dropdown.style.display = 'none';
        this.currentIndex = -1;
    }
    
    updateDropdownPosition() {
        // 這裡可以添加智慧定位邏輯，例如檢查視窗邊界
        // 目前使用 CSS 的 position: absolute 即可
    }
    
    navigateDown() {
        this.currentIndex = Math.min(this.currentIndex + 1, this.filteredContacts.length - 1);
        this.renderDropdown();
    }
    
    navigateUp() {
        this.currentIndex = Math.max(this.currentIndex - 1, -1);
        this.renderDropdown();
    }
    
    selectContact(contactId) {
        const contact = this.filteredContacts.find(c => c.id === contactId) ||
                      this.contacts.find(c => c.id === contactId);

        if (!contact) return;

        this.selectedContact = contact;
        this.displayInput.value = contact.display_name || contact.name;
        this.originalInput.value = contact.name; // 存儲姓名到原始 input
        this.originalValue = contact.name; // 更新原來的值

        this.close();

        // 觸發選擇事件
        if (this.options.onSelect) {
            this.options.onSelect(contact);
        }

        // 觸發原始 input 的 change 事件
        this.originalInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
    
    clearSelection() {
        this.selectedContact = null;
        this.originalInput.value = '';

        if (this.options.onClear) {
            this.options.onClear();
        }
    }

    restoreOriginalValue() {
        // 恢復原來的值到顯示輸入框和原始輸入框
        this.displayInput.value = this.originalValue;
        this.originalInput.value = this.originalValue;
        this.selectedContact = null; // 清空選擇狀態，因為我們恢復了原值

        // 如果原值不為空，嘗試找到對應的聯絡人
        if (this.originalValue.trim()) {
            const contact = this.contacts.find(c =>
                c.name === this.originalValue ||
                c.display_name === this.originalValue ||
                c.email === this.originalValue
            );
            if (contact) {
                this.selectedContact = contact;
            }
        }

        // 關閉下拉選單
        this.close();
    }
    
    setLoading(loading) {
        this.loading = loading;
        if (this.isOpen) {
            this.renderDropdown();
        }
    }
    
    handleError(message) {
        console.error('AssigneeSelector:', message);
        
        if (this.options.onError) {
            this.options.onError(message);
        }
        
        // 可以在這裡顯示錯誤提示
        this.filteredContacts = [];
        this.renderDropdown();
    }
    
    // 公開方法
    setValue(value) {
        this.displayInput.value = value;
        this.originalInput.value = value;
        this.originalValue = value; // 更新原來的值
        this.selectedContact = null;
    }
    
    getValue() {
        return this.originalInput.value;
    }
    
    getSelectedContact() {
        return this.selectedContact;
    }
    
    refresh() {
        this.cache.clear();
        this.loadContacts(this.searchTerm);
    }
    
    destroy() {
        // 清理事件監聽器和DOM
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
        }
        
        this.originalInput.style.display = '';
        this.container.remove();
        
        // 移除樣式（如果沒有其他實例）
        const selectors = document.querySelectorAll('.assignee-selector-container');
        if (selectors.length === 0) {
            const style = document.getElementById('assignee-selector-styles');
            if (style) style.remove();
        }
    }
}

// 工具函數：批次初始化頁面上的所有 assignee selector
window.initAssigneeSelectors = function(teamId) {
    document.querySelectorAll('[data-assignee-selector]').forEach(element => {
        if (element._assigneeSelector) {
            element._assigneeSelector.destroy();
        }
        
        const options = {
            teamId: teamId,
            ...JSON.parse(element.dataset.assigneeSelectorOptions || '{}')
        };
        
        element._assigneeSelector = new AssigneeSelector(element, options);
    });
};

// 導出到全域
window.AssigneeSelector = AssigneeSelector;
