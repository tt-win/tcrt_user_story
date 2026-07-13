# app-token-test-run-api Specification

## ADDED Requirements

### Requirement: Test Run Config Status Transition
App-token API SHALL 提供 `PUT /api/app/teams/{team_id}/test-run-configs/{config_id}/status`，以受控狀態機變更 test run config 狀態，需要 `test_run:write`。允許的轉換、`start_date`/`end_date` 副作用與所屬 Test Run Set 狀態重算 SHALL 與既有 JWT `/status` 端點一致，並共用同一 transition helper，不得在兩條 auth 路徑各自實作。非法轉換 SHALL 回 400。既有一般 `PUT /api/app/teams/{team_id}/test-run-configs/{config_id}` 的直接 status 設定行為 SHALL 保持不變。

#### Scenario: 合法轉換並套用日期副作用
- **WHEN** token 具備 `test_run:write` 並將 draft 的 config 轉為 active
- **THEN** 系統 SHALL 更新狀態為 active 並設定 `start_date`
- **AND** 再轉為 completed 時 SHALL 設定 `end_date`

#### Scenario: 非法轉換被拒絕
- **WHEN** token 嘗試將 completed 的 config 轉回 active
- **THEN** 系統 SHALL 回 400 且不變更狀態

#### Scenario: 轉換後重算所屬 set 狀態
- **WHEN** config 屬於某 Test Run Set 且其狀態轉換使成員全部完成
- **THEN** 系統 SHALL 重算並更新該 set 狀態

#### Scenario: 缺 write scope 不可轉換
- **WHEN** token 只有 `test_run:read` 並呼叫 `/status`
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`

### Requirement: Test Run Item Result File Upload
App-token API SHALL 提供 `POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/upload-results`，以 multipart 上傳測試執行結果檔案，需要 `test_run:execute`。檔案 SHALL 儲存於既有 attachments 根目錄下 `test-runs/{team_id}/{config_id}/{item_id}/`，並更新該 item 的 `execution_results_json`、`result_files_uploaded`、`result_files_count` 與 `upload_history_json`，其 schema SHALL 與 JWT `/upload-results` 一致。上傳 SHALL 寫入 app-token audit，且 audit details 不得包含檔案內容。

#### Scenario: 具 execute scope 上傳成功
- **WHEN** token 具備 `test_run:execute` 並對存在的 item 上傳一或多個檔案
- **THEN** 系統 SHALL 儲存檔案並更新 item 的結果與上傳歷史欄位
- **AND** 回應 SHALL 包含上傳檔數與明細

#### Scenario: 缺 execute scope 不可上傳
- **WHEN** token 只有 `test_run:write` 並呼叫 upload-results
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`

#### Scenario: item 不存在
- **WHEN** token 對不存在的 item 上傳
- **THEN** 系統 SHALL 回 404
