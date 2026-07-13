# app-token-test-case-api Specification

## ADDED Requirements

### Requirement: Test Case Batch Operations
App-token API SHALL 提供 `POST /api/app/teams/{team_id}/test-cases/batch-operations`，支援與 JWT `/batch` 相同的批次操作：`delete`、`update_priority`、`update_tcg`、`update_section`、`update_test_set`，並與 JWT 路徑共用同一批次執行邏輯。`delete` SHALL 要求 `test_case:admin`，其餘操作 SHALL 要求 `test_case:write`。`record_ids` SHALL 接受本地 id、`lark_record_id` 或 test case number。找不到的記錄 SHALL 逐項回報錯誤而不使整批失敗；`update_test_set` SHALL 套用既有 Test Run scope cleanup 並回傳 cleanup summary。

#### Scenario: 批次更新優先級
- **WHEN** token 具備 `test_case:write` 並以 `update_priority` 批次更新多筆案例
- **THEN** 系統 SHALL 更新所有可解析的案例並回報 success/error counts

#### Scenario: 批次刪除需要 admin scope
- **WHEN** token 只有 `test_case:write` 並提交 `delete` 批次操作
- **THEN** 系統 SHALL 回 403 `APP_TOKEN_SCOPE_DENIED` 且不刪除任何案例

#### Scenario: 不支援的操作
- **WHEN** 提交未定義的 operation 名稱
- **THEN** 系統 SHALL 回 400

#### Scenario: 部分記錄不存在
- **WHEN** `record_ids` 混合存在與不存在的記錄
- **THEN** 存在的記錄 SHALL 被處理，且不存在的 SHALL 逐項列於 error messages

### Requirement: Test Case Bulk Clone
App-token API SHALL 提供 `POST /api/app/teams/{team_id}/test-cases/bulk-clone`，需要 `test_case:write`，語意與 JWT `/bulk_clone` 一致：從來源案例複製 title（可覆寫）、priority、precondition、steps、expected_result 到新的 test case number；不複製 TCG、附件、測試結果。任一新編號與既有編號重複時 SHALL 拒絕整批並回報 duplicates。

#### Scenario: 批次複製成功
- **WHEN** token 具備 `test_case:write` 並提供有效來源與未使用的新編號
- **THEN** 系統 SHALL 建立複本並回報 created_count

#### Scenario: 重複編號整批拒絕
- **WHEN** 任一新 test case number 已存在
- **THEN** 系統 SHALL 不建立任何複本並回報 duplicates 清單
