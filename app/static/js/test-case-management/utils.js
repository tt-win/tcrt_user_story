/* ============================================================
   TEST CASE MANAGEMENT - UTILITIES
   ============================================================ */

// 通用工具函數
function showSuccess(message) {
    if (AppUtils && AppUtils.showSuccess) {
        AppUtils.showSuccess(message);
    } else {
        alert(message);
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

function showError(message) {
    if (AppUtils && AppUtils.showError) {
        AppUtils.showError(message);
    } else {
        alert(message);
    }
    // 工具列顯示狀態可能改變整體高度，需重新計算列表高度
    adjustTestCasesScrollHeight();
}

function formatDate(dateString, format) {
    if (AppUtils && AppUtils.formatDate) {
        return AppUtils.formatDate(dateString, format);
    } else {
        // 備用方案：使用瀏覽器的預設 locale，符合地區標準格式
        const date = new Date(dateString);
        if (isNaN(date.getTime())) return '';
        const browserLocale = navigator.language || navigator.userLanguage || 'en-US';

        if (format === 'date') {
            return date.toLocaleDateString(browserLocale);
        } else if (format === 'datetime') {
            return date.toLocaleString(browserLocale);
        } else if (format === 'time') {
            return date.toLocaleTimeString(browserLocale);
        }

        return date.toLocaleDateString(browserLocale);
    }
}
