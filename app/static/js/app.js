// 全域應用程式物件
const AppUtils = {
    // 當前選中的團隊
    currentTeam: null,

    // 設定當前團隊
    setCurrentTeam: function(team) {
        this.currentTeam = team;
        localStorage.setItem('currentTeam', JSON.stringify(team));
        console.log('團隊已設定為:', team.name);
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
        console.log('團隊選擇已清除');
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
    onTeamChange: null
};

// 應用程式初始化
document.addEventListener('DOMContentLoaded', function() {
    console.log('應用程式初始化完成');
    
    // 載入儲存的團隊選擇
    AppUtils.getCurrentTeam();
    
    // Debug: 顯示瀏覽器 locale 資訊
    const browserLocale = AppUtils.getBrowserLocale();
    console.log('瀏覽器 Locale:', browserLocale);
    
    // Debug: 測試日期格式化
    const testDate = new Date('2024-08-22T14:30:00');
    console.log('測試日期格式化:');
    console.log('- 日期:', AppUtils.formatDate(testDate, 'date'));
    console.log('- 時間:', AppUtils.formatDate(testDate, 'time'));
    console.log('- 日期時間:', AppUtils.formatDate(testDate, 'datetime'));
    if (window.DateTimeFormatter) {
        console.log('- 相對時間:', AppUtils.formatRelativeTime(testDate));
    }
});

// 全域函數 (向後兼容)
function selectTeamGlobally(teamId) {
    // 這個函數會在需要時被其他頁面使用
    console.log('全域團隊選擇:', teamId);
}

// 全域刷新當前頁面資料的函數
function refreshCurrentPageData() {
    // 這個函數會被各個頁面根據需要實作
    console.log('刷新當前頁面資料');
}