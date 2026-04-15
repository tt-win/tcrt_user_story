## 1. 移除後端同步服務與 API (Remove Backend Sync Service and APIs)

- [x] 1.1 刪除 `app/services/test_case_sync_service.py` 檔案。(Delete `app/services/test_case_sync_service.py`)
- [x] 1.2 搜尋並移除 `app/api/` 目錄中呼叫 `TestCaseSyncService` 或負責觸發 Lark 同步的 API Endpoints (例如在 `test_cases.py` 或獨立的 router 中)。(Remove any API endpoints related to Lark test case sync in `app/api/`)
- [x] 1.3 搜尋專案根目錄下的 `scripts/` (例如 `scripts/sync_test_cases_interactive.py`, `scripts/sync_tcrt_to_lark.py`)，若其完全為 Lark 測試案例同步而生，則將其刪除。(Remove background or interactive sync scripts from `scripts/`)

## 2. 清理前端介面 (Clean up Frontend UI)

- [x] 2.1 在 `app/templates/` 中搜尋 "sync" 或 "同步" 等關鍵字，移除觸發 Lark 同步的按鈕、狀態顯示或模態框。(Remove sync buttons and status UI from HTML templates)
- [x] 2.2 在 `static/js/` 中搜尋並移除綁定到同步按鈕的 JavaScript 事件處理函數與 API 呼叫邏輯。(Remove sync-related JavaScript event listeners and API calls)

## 3. 清理系統配置與背景任務 (Clean up Config and Background Tasks)

- [x] 3.1 檢查 `app/database_sync_backup.py` 或 `app/main.py`，移除任何定時執行 Lark 測試案例同步的背景任務。(Remove scheduled background sync tasks from application startup or periodic runner)
- [x] 3.2 檢查 `app/config.py`，如果有專為 Test Case Sync 設定的參數 (如 specific table IDs，但非 general Lark app settings)，予以移除。(Remove Lark sync specific configurations)

## 4. 測試與驗證 (Testing and Validation)

- [x] 4.1 執行全專案的 Pytest 測試，確保移除同步邏輯後，本地 Test Case 的建立、編輯、刪除等核心功能仍能正常運作。(Run all Pytest test cases to ensure local test case CRUD is intact)
- [x] 4.2 啟動本地伺服器，手動測試 UI，確認沒有因為移除了 JS 或 HTML 元素導致頁面報錯。(Start the server and manually verify the UI to ensure no console errors or broken layouts)
