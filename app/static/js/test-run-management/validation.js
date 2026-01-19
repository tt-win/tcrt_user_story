/* ============================================================
   TEST RUN MANAGEMENT - VALIDATION
   ============================================================ */

function validateTestRunConfigForm() {
    const errors = [];
    
    // 1. 必填欄位驗證
    const configName = document.getElementById('configName').value.trim();
    if (!configName) {
        errors.push({
            field: 'configName',
            message: '測試執行配置名稱為必填欄位',
            type: 'required'
        });
    } else if (configName.length < 2) {
        errors.push({
            field: 'configName',
            message: '配置名稱至少需要2個字元',
            type: 'minLength'
        });
    } else if (configName.length > 100) {
        errors.push({
            field: 'configName',
            message: '配置名稱不能超過100個字元',
            type: 'maxLength'
        });
    }
    
    // 2. TP 票號綜合驗證
    const tpTickets = getCurrentTpTickets();
    const tpValidationResult = validateAllTpTickets(tpTickets);
    if (!tpValidationResult.isValid) {
        errors.push(...tpValidationResult.errors);
    }
    
    // 3. 可選欄位格式驗證
    const description = document.getElementById('configDescription').value.trim();
    if (description && description.length > 1000) {
        errors.push({
            field: 'configDescription',
            message: '描述不能超過1000個字元',
            type: 'maxLength'
        });
    }
    
    const testEnvironment = document.getElementById('testEnvironment').value.trim();
    if (testEnvironment && testEnvironment.length > 100) {
        errors.push({
            field: 'testEnvironment',
            message: '測試環境名稱不能超過100個字元',
            type: 'maxLength'
        });
    }
    
    const buildNumber = document.getElementById('buildNumber').value.trim();
    if (buildNumber && buildNumber.length > 100) {
        errors.push({
            field: 'buildNumber',
            message: '建置版本號不能超過100個字元',
            type: 'maxLength'
        });
    }
    
    return {
        isValid: errors.length === 0,
        errors: errors
    };
}

// 驗證所有 TP 票號
function validateAllTpTickets(tpTickets) {
    const errors = [];
    
    if (tpTickets.length > 100) {
        errors.push({
            field: 'tpTickets',
            message: 'TP 票號數量不能超過100個',
            type: 'maxCount'
        });
    }
    
    // 驗證每個票號格式
    const invalidTickets = [];
    const duplicateTickets = [];
    const ticketCounts = {};
    
    tpTickets.forEach(ticket => {
        // 格式驗證
        if (!validateTpTicketFormat(ticket)) {
            invalidTickets.push(ticket);
        }
        
        // 重複檢查
        if (ticketCounts[ticket]) {
            duplicateTickets.push(ticket);
        } else {
            ticketCounts[ticket] = 1;
        }
    });
    
    if (invalidTickets.length > 0) {
        errors.push({
            field: 'tpTickets',
            message: `以下 TP 票號格式無效：${invalidTickets.join(', ')}`,
            type: 'invalidFormat',
            details: invalidTickets
        });
    }
    
    if (duplicateTickets.length > 0) {
        errors.push({
            field: 'tpTickets',
            message: `發現重複的 TP 票號：${duplicateTickets.join(', ')}`,
            type: 'duplicate',
            details: duplicateTickets
        });
    }
    
    return {
        isValid: errors.length === 0,
        errors: errors
    };
}

// 顯示表單驗證錯誤
function showFormValidationError(validationResult) {
    if (validationResult.errors.length === 0) return;
    
    const firstError = validationResult.errors[0];
    
    // 清除所有現有的錯誤樣式
    clearAllFormErrors();
    
    // 根據錯誤類型處理
    if (firstError.field === 'tpTickets') {
        // TP 票號相關錯誤
        showTpInputError(firstError.message);
        const tpInput = document.getElementById('relatedTpTicketsInput');
        if (tpInput) tpInput.focus();
    } else {
        // 其他欄位錯誤
        const fieldElement = document.getElementById(firstError.field);
        if (fieldElement) {
            fieldElement.classList.add('is-invalid');
            fieldElement.focus();
            
            // 創建或更新錯誤訊息
            let errorElement = document.getElementById(`${firstError.field}Error`);
            if (!errorElement) {
                errorElement = document.createElement('div');
                errorElement.id = `${firstError.field}Error`;
                errorElement.className = 'invalid-feedback d-block';
                fieldElement.parentNode.appendChild(errorElement);
            }
            errorElement.textContent = firstError.message;
            
            // 自動清除錯誤（當用戶開始輸入時）
            const clearErrorHandler = () => {
                fieldElement.classList.remove('is-invalid');
                if (errorElement) errorElement.remove();
                fieldElement.removeEventListener('input', clearErrorHandler);
            };
            fieldElement.addEventListener('input', clearErrorHandler);
        }
    }
    
    // 顯示綜合錯誤訊息（如果有多個錯誤）
    if (validationResult.errors.length > 1) {
        const remainingErrors = validationResult.errors.length - 1;
        setTimeout(() => {
            const message = `發現 ${validationResult.errors.length} 個驗證錯誤，請檢查表單內容`;
            showNotification(message, 'warning');
        }, 100);
    }
}

// 清除所有表單錯誤樣式
function clearAllFormErrors() {
    // 清除一般欄位錯誤
    const errorFields = ['configName', 'configDescription', 'testEnvironment', 'buildNumber'];
    errorFields.forEach(fieldId => {
        const fieldElement = document.getElementById(fieldId);
        const errorElement = document.getElementById(`${fieldId}Error`);
        
        if (fieldElement) {
            fieldElement.classList.remove('is-invalid');
        }
        if (errorElement) {
            errorElement.remove();
        }
    });
    
    // 清除 TP 票號錯誤
    clearTpInputError();
}

// 顯示通知訊息
function showNotification(message, type = 'info') {
    if (window.AppUtils) {
        if (type === 'success' && typeof window.AppUtils.showSuccess === 'function') {
            window.AppUtils.showSuccess(message);
            return;
        }
        if (type === 'warning' && typeof window.AppUtils.showWarning === 'function') {
            window.AppUtils.showWarning(message);
            return;
        }
        if (type === 'error' && typeof window.AppUtils.showError === 'function') {
            window.AppUtils.showError(message);
            return;
        }
        if (typeof window.AppUtils.showInfo === 'function') {
            window.AppUtils.showInfo(message);
            return;
        }
    }
    if (type === 'error') {
        alert(message);
    }
}

// ===== 快速搜尋 TP 票號功能 (T024 + T027 快取優化) =====

// T027: 搜尋結果快取機制
class TPSearchCache {
    constructor(ttl = 5 * 60 * 1000) { // 5分鐘 TTL
        this.cache = new Map();
        this.ttl = ttl;
    }
    
    // 生成快取鍵
    generateKey(query, teamId, limit) {
        return `${query.toLowerCase()}_${teamId}_${limit}`;
    }
    
    // 獲取快取結果
    get(query, teamId, limit) {
        const key = this.generateKey(query, teamId, limit);
        const item = this.cache.get(key);
        
        if (!item) return null;
        
        // 檢查是否過期
        if (Date.now() - item.timestamp > this.ttl) {
            this.cache.delete(key);
            return null;
        }
        
        return item.data;
    }
    
    // 設定快取
    set(query, teamId, limit, data) {
        const key = this.generateKey(query, teamId, limit);
        this.cache.set(key, {
            data: data,
            timestamp: Date.now()
        });
        
        // 限制快取大小 (最多100個項目)
        if (this.cache.size > 100) {
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
        }
    }
    
    // 清除過期快取
    cleanup() {
        const now = Date.now();
        for (const [key, item] of this.cache.entries()) {
            if (now - item.timestamp > this.ttl) {
                this.cache.delete(key);
            }
        }
    }
    
    // 清除所有快取
    clear() {
        this.cache.clear();
    }
}

// 全域搜尋快取實例
const tpSearchCache = new TPSearchCache();

// 定期清理過期快取
setInterval(() => tpSearchCache.cleanup(), 60000); // 每分鐘清理一次

// T028: 執行狀態處理函數 (與現有 UI 風格一致)
