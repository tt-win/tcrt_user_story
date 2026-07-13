# app-token-test-run-api Specification

## MODIFIED Requirements

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
