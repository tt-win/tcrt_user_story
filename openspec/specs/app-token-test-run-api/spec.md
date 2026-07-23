# app-token-test-run-api Specification

## Purpose
TBD - created by archiving change add-app-token-batch-operations. Update Purpose after archive.
## Requirements
### Requirement: Test Run Item Batch Result Updates
App-token API SHALL 提供 `POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items/batch-update-results`，需要 `test_run:execute`，一次更新多筆 run item 的執行結果。每筆 update SHALL 支援與 JWT batch 相同欄位（`test_result`、`assignee_name`、`executed_at`、`comment`），並透過與 JWT 路徑共用的逐項更新邏輯寫入相同的 result history。無效或不存在的項目 SHALL 逐項回報錯誤而不使整批失敗；回應 SHALL 包含 processed/success/error counts。

#### Scenario: 批次更新多筆結果
- **WHEN** token 具備 `test_run:execute` 並提交多筆 `{id, test_result}` updates
- **THEN** 系統 SHALL 更新每筆 item、寫入 result history，並回報 success_count

#### Scenario: 缺 execute scope 不可批次更新
- **WHEN** token 只有 `test_run:write` 並呼叫 batch-update-results
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED` 且不更新任何項目

#### Scenario: 部分項目不存在
- **WHEN** updates 內含不存在的 item id
- **THEN** 其餘項目 SHALL 正常更新，該筆 SHALL 列於 error messages

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

### Requirement: App Token Test Run API Namespace
系統 SHALL 在 `/api/app/teams/{team_id}` 下提供正式 app-token test run API surface，使用 app-token principal、team scope 與 operation scope guard。既有 `/api/teams/{team_id}` JWT API SHALL 保持不變。

#### Scenario: app token 呼叫 test run API
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/test-runs`
- **THEN** 系統 SHALL 驗證 token、team scope 與 `test_run:*` operation scope

#### Scenario: 缺少 execute scope 不可執行
- **WHEN** token 只有 `test_run:read` 卻呼叫 execution 或 automation trigger
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`

### Requirement: Test Run Config CRUD
App-token API SHALL 支援 test run config 的建立、讀取、更新、刪除與搜尋。Mutation SHALL 沿用既有 multi-set validation 與 team boundary。建立與更新需要 `test_run:write`；刪除為破壞性操作，需要 `test_run:admin`。更新 SHALL 能修改 `related_tp_tickets`（沿用既有 `TP-\d+` 格式驗證），使其與建立時可設定的 TP 票號一致；請求未提供該欄位時 SHALL 保持原值不變。建立與更新的 response SHALL 包含目前的 `related_tp_tickets`。

#### Scenario: 建立 test run config
- **WHEN** token 具備 `test_run:write` 並提供有效 set scope
- **THEN** 系統 SHALL 建立 test run config
- **AND** response SHALL 包含 persisted set scope

#### Scenario: 更新 test run config scope
- **WHEN** token 更新 test run config 並移除某些 set scope
- **THEN** 系統 SHALL 套用既有 out-of-scope cleanup
- **AND** response SHALL 包含 cleanup summary

#### Scenario: 更新 test run config 的 TP 票號
- **WHEN** token 具備 `test_run:write` 並在更新請求提供 `related_tp_tickets`
- **THEN** 系統 SHALL 以既有 TP 格式驗證後儲存新的票號清單
- **AND** response SHALL 回傳更新後的 `related_tp_tickets`

#### Scenario: 更新省略 TP 票號時保留原值
- **WHEN** token 更新 test run config 但未提供 `related_tp_tickets`
- **THEN** 系統 SHALL 保持既有 TP 票號不變

### Requirement: Test Run Set CRUD and Membership
App-token API SHALL 支援 test run set 的建立、讀取、更新、刪除、archive、membership attach/detach/move，以及 automation suite membership。所有 suite、config 與 case references SHALL 限制在同 team。建立、更新與 membership 變更需要 `test_run:write`；刪除與 archive 為破壞性操作，需要 `test_run:admin`。

#### Scenario: 建立 test run set
- **WHEN** token 具備 `test_run:write` 並建立 test run set
- **THEN** 系統 SHALL 建立 set 並保存 initial config ids 與 automation suite ids

#### Scenario: 更新 membership
- **WHEN** token 移動 config 到另一個 test run set
- **THEN** 系統 SHALL 驗證 source 與 target set 屬於同 team
- **AND** response SHALL 反映最新 membership

#### Scenario: 刪除或 archive set
- **WHEN** token 具備 `test_run:admin` 並刪除或 archive test run set
- **THEN** 系統 SHALL 套用既有 cleanup 與 audit 行為

#### Scenario: 只有 write scope 不可刪除 set
- **WHEN** token 只有 `test_run:write` 卻刪除或 archive test run set
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`
- **AND** mutation SHALL NOT 執行

### Requirement: Test Run Items and Execution Result Updates
App-token API SHALL 支援 test run items 的讀取、建立、批次建立、更新 result/status/assignee/bug references、刪除與批次操作。Execution updates SHALL 維持既有 test run execution semantics。

#### Scenario: 批次建立 run items
- **WHEN** token 具備 `test_run:write` 並新增多個 test run items
- **THEN** 系統 SHALL 建立屬於該 test run configured set scope 的 items
- **AND** 不合法 item SHALL 回報 per-item failure

#### Scenario: 更新 execution result
- **WHEN** token 具備 `test_run:execute` 並更新 run item test_result
- **THEN** 系統 SHALL 儲存結果並更新必要 aggregate counters

#### Scenario: 拒絕 scope 外 case
- **WHEN** token 嘗試加入不在 test run configured set scope 內的 case
- **THEN** 系統 SHALL 拒絕該 item 並回報 scope mismatch

### Requirement: Reports and Automation Trigger
App-token API SHALL 支援 test run report generation / lookup，以及透過 Test Run Set 觸發 automation suite。Report generation 會在 server 端產生檔案，屬寫入類操作，SHALL 要求 `test_run:write`；report metadata lookup SHALL 只要求 `test_run:read`。Automation trigger SHALL 使用既有 `POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation` 的 orchestration 語意，不得新增平行執行通道。

#### Scenario: 產生 report
- **WHEN** token 具備 `test_run:write` 並請求 report generation
- **THEN** 系統 SHALL 使用既有 report service 產生 report 並回傳 metadata

#### Scenario: read scope 只能查 report
- **WHEN** token 只有 `test_run:read` 並請求 report generation
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED`
- **AND** 既有 report metadata lookup SHALL 仍可用

#### Scenario: 觸發 automation
- **WHEN** token 具備 `automation:execute` 並呼叫 app-token automation trigger endpoint
- **THEN** 系統 SHALL 透過 Test Run Set orchestration 建立 automation runs
- **AND** audit `details.trigger_source` SHALL 標示 app-token 來源與 test_run_set_id

### Requirement: Run Cancel and Reconcile
App-token API SHALL 支援 automation run cancel / reconcile，兩者 SHALL 要求 `automation:execute`。Provider 不支援或 run 不屬於 team 時 SHALL 拒絕。

#### Scenario: cancel run
- **WHEN** token 具備 `automation:execute` 並取消同 team non-terminal run
- **THEN** 系統 SHALL 呼叫既有 provider cancel flow
- **AND** 寫入 app-token audit

#### Scenario: reconcile run
- **WHEN** token 具備 `automation:execute` 並提交 external_run_id
- **THEN** 系統 SHALL 驗證 provider status 並更新 run metadata

