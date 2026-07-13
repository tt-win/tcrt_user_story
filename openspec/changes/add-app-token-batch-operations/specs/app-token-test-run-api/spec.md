# app-token-test-run-api Specification

## ADDED Requirements

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
