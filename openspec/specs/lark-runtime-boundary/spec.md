# lark-runtime-boundary Specification

## Purpose
定義 TCRT 與 Lark 之間的執行期邊界：team 層級（測試案例、test run、附件）已完全不再與 Lark 互動，僅組織層功能（人員／部門同步、Test Run 群組通知、Lark 使用者查詢）保留整合並使用全域 app 憑證。本 spec 的作用是防止已移除的 Lark 端點與出站路徑日後回流。
## Requirements
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

### Requirement: No team-level Lark egress remains

系統 SHALL NOT 在任何 team 層級的請求處理路徑上呼叫 Lark。附件下載代理 SHALL 只從本機附件目錄取檔（DB 記錄的路徑、`/attachments` 相對路徑、檔名遞迴搜尋），三者皆落空時 SHALL 回傳 404，SHALL NOT 建立 Lark client、SHALL NOT 代理任何外部下載。test run 相關的刪除流程 SHALL NOT 對外部服務發出附件解除關聯請求。

系統中僅存的 Lark 整合為組織層功能（人員／部門同步、Test Run 群組通知、Lark 使用者查詢），一律使用全域 `settings.lark.app_id` / `app_secret`，與 `teams.wiki_token` 無關。`teams.wiki_token` / `teams.test_case_table_id` 欄位與其歷史值 SHALL 保留於資料庫，但 SHALL NOT 被任何程式碼路徑讀取用於對外請求。

#### Scenario: Attachment download falls back to 404, not to Lark
- **WHEN** 下載代理在本機三種來源都找不到指定附件
- **THEN** 系統 SHALL 回傳 404
- **AND** 處理過程 SHALL NOT 建立 Lark client 或發出任何外部 HTTP 請求

#### Scenario: Deleting test run data performs no external calls
- **WHEN** 使用者刪除 test run config、test run set 或單一 test run item
- **THEN** 系統 SHALL 僅操作本地資料庫與本機檔案，SHALL NOT 對 Lark 發出任何請求

#### Scenario: Legacy Lark test case attachments are unaffected
- **WHEN** 某些歷史 test case 的 `attachments_json` 仍帶有 Lark `file_token` 與 `open.larksuite.com` URL
- **THEN** UI SHALL 維持既有行為，以該 URL 直接連往 Lark（不經過本系統代理）
- **AND** 本系統 SHALL NOT 因此保留任何 Lark client 程式碼

