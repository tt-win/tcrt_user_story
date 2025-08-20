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

    // 格式化日期
    formatDate: function(dateString, format = 'datetime') {
        if (!dateString) return '';
        
        const date = new Date(dateString);
        const options = {};

        if (format === 'date') {
            options.year = 'numeric';
            options.month = '2-digit';
            options.day = '2-digit';
        } else if (format === 'datetime') {
            options.year = 'numeric';
            options.month = '2-digit';
            options.day = '2-digit';
            options.hour = '2-digit';
            options.minute = '2-digit';
        } else if (format === 'time') {
            options.hour = '2-digit';
            options.minute = '2-digit';
        }

        return date.toLocaleString('zh-TW', options);
    },

    // 團隊變更回調函數 (可由外部設定)
    onTeamChange: null
};

// 應用程式初始化
document.addEventListener('DOMContentLoaded', function() {
    console.log('應用程式初始化完成');
    
    // 載入儲存的團隊選擇
    AppUtils.getCurrentTeam();
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