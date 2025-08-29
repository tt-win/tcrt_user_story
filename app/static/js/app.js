// 全域應用程式物件
const AppUtils = {
    // 當前選中的團隊
    currentTeam: null,

    // 設定當前團隊
    setCurrentTeam: function(team) {
        this.currentTeam = team;
        localStorage.setItem('currentTeam', JSON.stringify(team));
        this.triggerTeamChangeEvent();
    },

    // 獲取當前團隊
    getCurrentTeam: function() {
        if (!this.currentTeam) {
            const stored = localStorage.getItem('currentTeam');
            if (stored) {
                this.currentTeam = JSON.parse(stored);
            }
        }
        return this.currentTeam;
    },

    // 獲取當前團隊 ID
    getCurrentTeamId: function() {
        const team = this.getCurrentTeam();
        return team ? team.id.toString() : null;
    },

    // 清除當前團隊
    clearCurrentTeam: function() {
        this.currentTeam = null;
        localStorage.removeItem('currentTeam');
        this.triggerTeamClearEvent();
    },

    // 觸發團隊變更事件
    triggerTeamChangeEvent: function() {
        const event = new CustomEvent('teamChanged', { 
            detail: { team: this.currentTeam } 
        });
        window.dispatchEvent(event);
    },

    // 觸發團隊清除事件
    triggerTeamClearEvent: function() {
        const event = new CustomEvent('teamCleared');
        window.dispatchEvent(event);
    },

    // 顯示成功訊息
    showSuccess: function(message) {
        this.showMessage(message, 'success');
    },

    // 顯示錯誤訊息
    showError: function(message) {
        this.showMessage(message, 'danger');
    },

    // 顯示資訊訊息
    showInfo: function(message) {
        this.showMessage(message, 'info');
    },

    // 顯示警告訊息
    showWarning: function(message) {
        this.showMessage(message, 'warning');
    },

    // 通用訊息顯示函數
    showMessage: function(message, type = 'info') {
        const container = document.getElementById('flash-messages');
        if (!container) return;

        const alertId = 'alert-' + Date.now();
        const alertHtml = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert" id="${alertId}">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;

        container.insertAdjacentHTML('beforeend', alertHtml);

        // 3 秒後自動移除訊息
        setTimeout(() => {
            const alertElement = document.getElementById(alertId);
            if (alertElement) {
                const bsAlert = bootstrap.Alert.getOrCreateInstance(alertElement);
                bsAlert.close();
            }
        }, 3000);
    },

    // 格式化日期 - 使用瀏覽器的 locale 設定，不依賴介面語言
    formatDate: function(dateString, format = 'datetime') {
        if (!dateString) return '';
        
        // 使用新的 DateTimeFormatter 模組，它會自動使用瀏覽器的 locale 設定
        if (window.DateTimeFormatter) {
            return window.DateTimeFormatter.format(dateString, format);
        }
        
        // 備用方案：如果 DateTimeFormatter 尚未載入，使用瀏覽器預設 locale
        let date;
        // Handle UTC time strings without timezone identifier (support both 'T' and ' ' separators)
        if (typeof dateString === 'string' && dateString.match(/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?$/) && !dateString.endsWith('Z')) {
            const isoString = dateString.includes('T') ? dateString + 'Z' : dateString.replace(' ', 'T') + 'Z';
            date = new Date(isoString);
        } else {
            date = new Date(dateString);
        }
        if (isNaN(date.getTime())) return '';
        
        // 使用瀏覽器的預設 locale 而非硬編碼的 'zh-TW'
        const browserLocale = navigator.language || navigator.userLanguage || 'en-US';
        
        // 使用地區標準格式，讓各地區顯示符合當地慣例的格式
        if (format === 'date') {
            return date.toLocaleDateString(browserLocale);
        } else if (format === 'datetime') {
            return date.toLocaleString(browserLocale);
        } else if (format === 'datetime-tz') {
            // 顯示包含時區資訊的日期時間格式
            return date.toLocaleString(browserLocale, {
                year: 'numeric',
                month: 'numeric', 
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                timeZoneName: 'short'
            });
        } else if (format === 'time') {
            return date.toLocaleTimeString(browserLocale);
        }

        return date.toLocaleString(browserLocale);
    },

    // 格式化相對時間 (e.g., "2 hours ago", "in 3 days")
    formatRelativeTime: function(dateString) {
        if (window.DateTimeFormatter) {
            return window.DateTimeFormatter.formatRelative(dateString);
        }
        
        // 簡單備用方案
        return this.formatDate(dateString, 'datetime');
    },

    // 獲取瀏覽器的 locale 設定
    getBrowserLocale: function() {
        if (window.DateTimeFormatter) {
            return window.DateTimeFormatter.getBrowserLocale();
        }
        return navigator.language || navigator.userLanguage || 'en-US';
    },

    // 團隊變更回調函數 (可由外部設定)
    onTeamChange: null,

    // 顯示團隊名稱標籤
    showTeamNameBadge: function() {
        const team = this.getCurrentTeam();
        const badge = document.getElementById('team-name-badge');
        const text = document.getElementById('team-name-text');

        if (team && badge && text) {
            text.textContent = team.name;
            badge.classList.remove('d-none');
        } else if (badge) {
            badge.classList.add('d-none');
        }
    },

    // 更新團隊名稱標籤
    updateTeamNameBadge: function() {
        const team = this.getCurrentTeam();
        if (team) {
            this.showTeamNameBadge();
        } else {
            this.hideTeamNameBadge();
        }
    },

    // 隱藏團隊名稱標籤
    hideTeamNameBadge: function() {
        const badge = document.getElementById('team-name-badge');
        if (badge) {
            badge.classList.add('d-none');
        }
    }
};

// 全域翻譯監視器 - 處理動態內容的翻譯
class TranslationObserver {
    constructor() {
        this.observer = null;
        this.debounceTimer = null;
        this.init();
    }

    init() {
        // 監視 DOM 變化
        this.observer = new MutationObserver((mutations) => {
            let needsTranslation = false;

            mutations.forEach((mutation) => {
                if (mutation.type === 'childList') {
                    mutation.addedNodes.forEach((node) => {
                        if (node.nodeType === Node.ELEMENT_NODE) {
                            const element = node;
                            if (element.hasAttribute && (
                                element.hasAttribute('data-i18n') ||
                                element.querySelector && element.querySelector('[data-i18n]')
                            )) {
                                needsTranslation = true;
                            }
                        }
                    });
                } else if (mutation.type === 'attributes') {
                    if (mutation.attributeName && mutation.attributeName.startsWith('data-i18n')) {
                        needsTranslation = true;
                    }
                }
            });

            if (needsTranslation) {
                this.scheduleRetranslation();
            }
        });

        // 開始監視
        if (document.body) {
            this.observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['data-i18n', 'data-i18n-params', 'data-i18n-placeholder']
            });
        }
    }

    scheduleRetranslation() {
        // 防抖處理，避免頻繁重新翻譯
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
        }

        this.debounceTimer = setTimeout(() => {
            if (window.i18n && window.i18n.isReady()) {
                console.log('Retranslating page due to dynamic content changes');
                window.i18n.retranslate(document);
            }
        }, 100);
    }

    disconnect() {
        if (this.observer) {
            this.observer.disconnect();
        }
        if (this.debounceTimer) {
            clearTimeout(this.debounceTimer);
        }
    }
}

// 全域翻譯監視器實例
let translationObserver = null;

// 應用程式初始化
document.addEventListener('DOMContentLoaded', function() {
    // 載入儲存的團隊選擇
    AppUtils.getCurrentTeam();

    // 顯示團隊名稱標籤
    AppUtils.updateTeamNameBadge();

    // 初始化翻譯監視器
    if (!translationObserver) {
        translationObserver = new TranslationObserver();
    }
});

// 監聽 i18n 準備完成事件
document.addEventListener('i18nReady', function() {
    // 確保初始翻譯完成
    if (window.i18n) {
        window.i18n.retranslate(document);
    }
});

// 監聽語言變更事件
document.addEventListener('languageChanged', function() {
    // 語言變更後重新翻譯
    if (window.i18n) {
        setTimeout(() => window.i18n.retranslate(document), 50);
    }
});

// 全域函數 (向後兼容)
function selectTeamGlobally(teamId) {
    // 這個函數會在需要時被其他頁面使用
    AppUtils.setCurrentTeam({ id: teamId });
}

// 全域刷新當前頁面資料的函數
function refreshCurrentPageData() {
    // 觸發頁面資料刷新事件
    const event = new CustomEvent('refreshPageData');
    window.dispatchEvent(event);
}