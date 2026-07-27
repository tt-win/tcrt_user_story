## ADDED Requirements

### Requirement: Test run data has no Lark HTTP surface

系統 SHALL NOT 提供任何以 Lark Bitable record 為讀寫對象的 test run 端點。test run 與其執行結果的唯一真實來源是本地資料庫（`test_run_configs`、`test_run_items` 等）。`/api/teams/{team_id}/test-runs/*` 路徑下 SHALL 僅保留與 HTML 報告有關的端點（`POST .../generate-html`、`GET .../report`），且這些端點 SHALL NOT 呼叫任何 Lark API。

#### Scenario: Lark record endpoints are absent
- **WHEN** 任何 client 呼叫 `/api/teams/{team_id}/test-runs/{config_id}/records`（或其 count／單筆／statistics／batch-update-results 變體）
- **THEN** 系統 SHALL NOT 提供該端點（回應為 4xx 客戶端錯誤，而非執行任何 Lark 查詢）

#### Scenario: Report endpoints remain and stay Lark-free
- **WHEN** 使用者於 test run 執行頁觸發 HTML 報告產生
- **THEN** `POST /api/teams/{team_id}/test-runs/{config_id}/generate-html` SHALL 正常運作
- **AND** 其執行過程 SHALL NOT 建立 Lark client 或呼叫 Lark API

### Requirement: Lark attachment write paths are removed

系統 SHALL NOT 提供任何將檔案寫入 Lark（上傳、附加 file token、從 Lark 記錄移除附件）的端點。測試案例與 test run 的附件 SHALL 一律存放於本機附件目錄，經由 `app/api/test_cases.py` 與 test run item 的既有本機路徑管理。

#### Scenario: Lark upload endpoints are absent
- **WHEN** 任何 client 呼叫 Lark 附件寫入端點（testcase upload、test-run record upload、upload-screenshot、upload-file-token、attach-token、以 file token 刪除附件）
- **THEN** 系統 SHALL NOT 提供該端點

#### Scenario: Local attachment flow is unaffected
- **WHEN** 使用者在測試案例或 test run item 上傳附件
- **THEN** 檔案 SHALL 寫入本機附件目錄，流程 SHALL NOT 涉及任何 Lark 呼叫

### Requirement: Remaining Lark egress is limited to legacy read paths

系統剩餘的 team 層級 Lark 出站路徑 SHALL 僅限於服務既有資料的兩條路徑，且兩者 SHALL 在 team 沒有 `wiki_token` 時提前返回而不對外發出請求：

1. 附件下載代理（`GET /api/attachments/teams/{team_id}/attachments/download`）在本機來源全部落空後的 Lark 回退；其對外行為契約見 `async-runtime-performance`。
2. `TestResultCleanupService` 於刪除 test run item 時，對 legacy 上傳紀錄解除 Lark 附件關聯。

移除這兩條路徑 SHALL 以「已確認生產資料中不存在帶 Lark `file_token` 的 `execution_results_json` / `upload_history_json`」為前置條件，並 SHALL 同步更新 `async-runtime-performance` 中的下載代理 requirement。

#### Scenario: New team never triggers Lark egress
- **WHEN** 對一個 `wiki_token` 為空字串的 team 觸發附件下載代理或 test run item 刪除
- **THEN** 系統 SHALL NOT 建立 Lark client、SHALL NOT 對 Lark 發出任何請求
- **AND** 下載代理 SHALL 回傳 404（附件不存在），而非回報 Lark 服務異常

#### Scenario: Legacy team can still retrieve its Lark attachments
- **WHEN** 一個仍保有歷史 `wiki_token` 的 team 下載一筆只存在於 Lark 的舊附件
- **THEN** 下載代理 SHALL 走 Lark 回退取回檔案，行為與 `async-runtime-performance` 定義的狀態碼映射一致
