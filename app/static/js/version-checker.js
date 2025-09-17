/**
 * 版本檢查器
 * 負責定期檢查伺服器版本並提醒用戶更新
 */

class VersionChecker {
    constructor() {
        this.CHECK_INTERVAL = 60 * 60 * 1000; // 每小時檢查一次 (60分鐘)
        this.STORAGE_KEY = 'client_server_timestamp';
        this.checkTimer = null;
        this.isChecking = false;

        // 綁定方法
        this.checkVersion = this.checkVersion.bind(this);
        this.handleUpdateClick = this.handleUpdateClick.bind(this);

        console.log('版本檢查器初始化');
    }

    /**
     * 啟動版本檢查
     */
    start() {
        console.log('啟動版本檢查服務');

        // 立即進行一次檢查
        this.checkVersion();

        // 設定定期檢查
        this.checkTimer = setInterval(this.checkVersion, this.CHECK_INTERVAL);

        // 當頁面重新獲得焦點時也檢查一次（處理離線重連情況）
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) {
                console.log('頁面重新獲得焦點，檢查版本');
                setTimeout(this.checkVersion, 1000);
            }
        });
    }

    /**
     * 停止版本檢查
     */
    stop() {
        if (this.checkTimer) {
            clearInterval(this.checkTimer);
            this.checkTimer = null;
            console.log('版本檢查服務已停止');
        }
    }

    /**
     * 檢查伺服器版本
     */
    async checkVersion() {
        if (this.isChecking) {
            return;
        }

        this.isChecking = true;

        try {
            console.log('正在檢查伺服器版本...');

            const response = await fetch('/api/version/', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            const serverTimestamp = data.server_timestamp;

            console.log(`伺服器時間戳: ${serverTimestamp} (${data.server_time})`);

            // 取得本地儲存的時間戳
            const clientTimestamp = this.getClientTimestamp();
            console.log(`本地時間戳: ${clientTimestamp || '無'}`);

            if (clientTimestamp === null) {
                // 首次使用或清空了 storage，強制 reload
                console.log('首次使用或無本地時間戳，強制重新載入');
                this.saveClientTimestamp(serverTimestamp);
                this.forceReload();
                return;
            }

            if (serverTimestamp > clientTimestamp) {
                // 伺服器版本較新，顯示更新按鈕
                console.log('發現新版本，顯示更新提醒');
                this.showUpdateButton(serverTimestamp);
            } else {
                // 版本一致，隱藏更新按鈕
                this.hideUpdateButton();
            }

        } catch (error) {
            console.error('版本檢查失敗:', error);
            // 檢查失敗不影響正常使用，僅記錄錯誤
        } finally {
            this.isChecking = false;
        }
    }

    /**
     * 取得本地儲存的時間戳
     */
    getClientTimestamp() {
        const stored = localStorage.getItem(this.STORAGE_KEY);
        return stored ? parseInt(stored, 10) : null;
    }

    /**
     * 儲存時間戳到本地
     */
    saveClientTimestamp(timestamp) {
        localStorage.setItem(this.STORAGE_KEY, timestamp.toString());
        console.log(`已儲存時間戳: ${timestamp}`);
    }

    /**
     * 顯示更新按鈕
     */
    showUpdateButton(newTimestamp) {
        // 儲存新的時間戳
        this.newTimestamp = newTimestamp;

        // 尋找或建立更新按鈕
        let updateBtn = document.getElementById('version-update-btn');
        if (!updateBtn) {
            updateBtn = this.createUpdateButton();
        }

        // 顯示按鈕並開始閃爍動畫
        updateBtn.style.display = 'inline-block';
        updateBtn.classList.add('version-update-pulse');

        console.log('更新按鈕已顯示');
    }

    /**
     * 隱藏更新按鈕
     */
    hideUpdateButton() {
        const updateBtn = document.getElementById('version-update-btn');
        if (updateBtn) {
            updateBtn.style.display = 'none';
            updateBtn.classList.remove('version-update-pulse');
        }
    }

    /**
     * 建立更新按鈕
     */
    createUpdateButton() {
        const button = document.createElement('button');
        button.id = 'version-update-btn';
        button.type = 'button';
        button.className = 'btn btn-outline-info btn-sm';
        button.innerHTML = '<i class="fas fa-sync-alt me-1"></i><span data-i18n="version.updateAvailable">有新版本</span>';
        button.title = '點擊更新到最新版本';
        button.style.display = 'none';

        // 綁定點擊事件
        button.addEventListener('click', this.handleUpdateClick);

        // 插入到 footer 語言切換器左邊
        const footerContainer = document.querySelector('.app-footer .container-fluid');
        const languageSwitcher = document.getElementById('language-switcher');

        console.log('createUpdateButton 調試信息:');
        console.log('footerContainer:', footerContainer);
        console.log('languageSwitcher:', languageSwitcher);

        if (footerContainer && languageSwitcher) {
            // 插入到語言切換器前面
            footerContainer.insertBefore(button, languageSwitcher);
            console.log('按鈕已插入到語言切換器前面');

            // 添加間距
            button.style.marginRight = '1rem';
        } else if (footerContainer) {
            // 如果找不到語言切換器，就插入到 footer 最前面
            footerContainer.insertBefore(button, footerContainer.firstChild);
            console.log('按鈕已插入到 footer 最前面');
            button.style.marginRight = '1rem';
        } else {
            console.error('無法找到 footer 容器');
        }

        return button;
    }

    /**
     * 處理更新按鈕點擊
     */
    handleUpdateClick() {
        console.log('用戶點擊更新按鈕');

        // 更新本地時間戳
        if (this.newTimestamp) {
            this.saveClientTimestamp(this.newTimestamp);
        }

        const reloadPromise = this.forceReload();
        if (reloadPromise && typeof reloadPromise.catch === 'function') {
            reloadPromise.catch(err => console.error('重新載入最新版本失敗:', err));
        }
    }

    /**
     * 強制重新載入頁面
     */
    async forceReload() {
        console.log('強制重新載入頁面');

        if (window.AppUtils && window.AppUtils.showInfo) {
            window.AppUtils.showInfo('正在更新到最新版本...');
        }

        try {
            if (window.caches && typeof caches.keys === 'function') {
                const cacheNames = await caches.keys();
                await Promise.all(cacheNames.map(name => caches.delete(name)));
                console.log('已清除瀏覽器 Cache Storage');
            }
        } catch (cacheError) {
            console.warn('清除 Cache Storage 失敗:', cacheError);
        }

        try {
            if (navigator.serviceWorker && typeof navigator.serviceWorker.getRegistrations === 'function') {
                const registrations = await navigator.serviceWorker.getRegistrations();
                await Promise.all(registrations.map(reg => reg.unregister()));
                console.log('已註銷 Service Workers');
            }
        } catch (swError) {
            console.warn('註銷 Service Worker 失敗:', swError);
        }

        setTimeout(() => {
            const url = new URL(window.location.href);
            url.searchParams.set('_v', Date.now().toString());
            window.location.replace(url.toString());
        }, 500);
    }

    /**
     * 手動觸發版本檢查（用於測試）
     */
    manualCheck() {
        console.log('手動觸發版本檢查');
        this.checkVersion();
    }

    /**
     * 重置本地時間戳（用於測試）
     */
    resetClientTimestamp() {
        localStorage.removeItem(this.STORAGE_KEY);
        console.log('已重置本地時間戳');
    }

    /**
     * 測試版本檢查功能（用於調試）
     */
    testVersionCheck() {
        console.log('手動觸發版本檢查測試');
        this.checkVersion();
    }

    /**
     * 強制顯示更新按鈕（用於測試）
     */
    testShowUpdateButton() {
        console.log('測試顯示更新按鈕');
        this.newTimestamp = Date.now();

        // 先隱藏現有按鈕（如果有的話）
        this.hideUpdateButton();

        // 強制顯示新按鈕
        this.showUpdateButton(this.newTimestamp);

        console.log('測試完成，檢查 footer 是否出現更新按鈕');
    }
}

// 全域實例
window.versionChecker = new VersionChecker();

// 當 DOM 載入完成後自動啟動
document.addEventListener('DOMContentLoaded', () => {
    window.versionChecker.start();
});

// 在頁面卸載前停止檢查
window.addEventListener('beforeunload', () => {
    window.versionChecker.stop();
});
