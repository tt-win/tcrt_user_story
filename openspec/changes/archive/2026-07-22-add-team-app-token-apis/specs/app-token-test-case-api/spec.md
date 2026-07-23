# app-token-test-case-api Specification

## ADDED Requirements

### Requirement: App Token Test Case API Namespace
系統 SHALL 在 `/api/app/teams/{team_id}` 下提供正式 app-token test case API surface。該 namespace SHALL 使用 app-token principal 驗證與 scope guard，不得依賴 `get_current_user` 或人類 JWT session。

#### Scenario: app token 呼叫 test case API
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/test-cases`
- **THEN** 系統 SHALL 以 app-token principal 驗證 team scope 與 operation scope

#### Scenario: JWT API 行為不變
- **WHEN** 既有前端呼叫 `/api/teams/{team_id}/testcases`
- **THEN** 既有 JWT API SHALL 保持原契約，不因 app-token API 改動而改變

### Requirement: Test Case Read Operations
App-token API SHALL 提供 test case read operations，涵蓋列表、lookup、detail、sections、sets、linked automation summary 與 test data include flag。Read response SHALL 與現有 MCP read model 或既有 UI API 語意一致，並以 `/api/app/*` 作為正式路徑。

#### Scenario: 列表支援既有 filters
- **WHEN** app token 呼叫 test case list 並帶 `set_id`、`search`、`priority`、`test_result`、`assignee`、`tcg`、`ticket`、`include_content`、`include_test_data`、`skip`、`limit`
- **THEN** 系統 SHALL 以相同 filter 語意回傳 team-scoped results

#### Scenario: detail 可帶出 test_data
- **WHEN** token 具備 `test_case:read` 並取得單筆 test case detail
- **THEN** response SHALL 可包含 test_data
- **AND** audit SHALL redacted credential 類 test_data value

### Requirement: Test Case Create and Update Operations
App-token API SHALL 支援建立與更新 test case，並沿用本地 test case 管理的驗證規則、default set 規則、section scope 規則與 local-only persistence。外部 app token mutation SHALL 不觸發 Lark 或其他外部 test case sync。

#### Scenario: 建立 test case
- **WHEN** token 具備 `test_case:write` 並提交有效 test case payload
- **THEN** 系統 SHALL 在指定 team 建立本地 test case
- **AND** 若 payload 未指定 set，系統 SHALL 使用該 team default test case set

#### Scenario: 更新 test case
- **WHEN** token 具備 `test_case:write` 並更新同 team 的 test case
- **THEN** 系統 SHALL 更新本地 DB
- **AND** SHALL NOT 呼叫外部同步 API

#### Scenario: 拒絕跨 team section 或 set
- **WHEN** payload 指向不屬於該 team 的 test case set 或 section
- **THEN** 系統 SHALL 回 400 `APP_TOKEN_VALIDATION_ERROR`
- **AND** mutation SHALL NOT 執行

### Requirement: Test Case Delete and Batch Operations
App-token API SHALL 支援刪除與批次 mutation，但 destructive operation（單筆刪除、批次刪除、set/section 刪除）SHALL 要求 `test_case:admin`，並回傳 impact summary。批次操作 SHALL 對每筆 item 回報成功、失敗與原因。

#### Scenario: 刪除 test case
- **WHEN** token 具備 `test_case:admin` 且刪除同 team test case
- **THEN** 系統 SHALL 刪除該 test case 或依既有 local 管理語意處理
- **AND** response SHALL 包含影響到的 test run item / attachment cleanup summary

#### Scenario: 批次更新部分失敗
- **WHEN** batch payload 中部分 test cases 不存在或不屬於 team
- **THEN** response SHALL 回報 per-item failure
- **AND** 已成功項目與失敗項目 SHALL 可被 caller 明確區分

### Requirement: Test Case Sets, Sections, Test Data, and Attachments
App-token API SHALL 覆蓋 test case set、section、test data 與 attachment 的必要管理操作。所有操作 SHALL 強制 team boundary，並在 audit 中記錄 app-token actor。

#### Scenario: 管理 test case set 與 section
- **WHEN** token 具備 `test_case:admin` 並建立、更新、刪除 set 或 section
- **THEN** 系統 SHALL 套用既有 team boundary 與 impact preview / cleanup 規則

#### Scenario: 管理 test data
- **WHEN** token 具備 `test_case:write` 並新增或更新 test_data
- **THEN** 系統 SHALL 儲存完整 value
- **AND** audit SHALL redacted credential 類 value

#### Scenario: 上傳附件
- **WHEN** token 具備 `test_case:write` 並上傳 test case attachment
- **THEN** 檔案 SHALL 寫入既有 attachments root 與 team/test case 目錄規則
- **AND** response SHALL 不暴露 server 端絕對路徑
