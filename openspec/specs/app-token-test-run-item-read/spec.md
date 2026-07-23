# app-token-test-run-item-read Specification

## Purpose
TBD - created by archiving change add-app-token-test-run-item-list. Update Purpose after archive.
## Requirements
### Requirement: App Token Test Run Item List
系統 SHALL 提供 `GET /api/app/teams/{team_id}/test-run-configs/{config_id}/items`，讓具備
`test_run:read` scope 且可存取該 team 的 App Token，以 pagination 讀取屬於該 Test Config
的 Test Run Items。系統 SHALL 驗證 config 屬於 path 指定 team，並以 item ID ASC 穩定排序。
response SHALL 包含 `team_id`、`config_id`、`items` 與 `page`；每筆 item 僅包含 `id`、
`test_case_number`、`test_result`、`executed_at`、`execution_duration`、`assignee_name` 與
`updated_at`，不得包含 case content、attachments、test data 或完整 assignee profile。

#### Scenario: Read a config's item snapshot
- **WHEN** 有 `test_run:read` scope 的 team-scoped App Token 呼叫 item list endpoint
- **THEN** 系統回傳該 config 的 item execution metadata 與正確的 `page.total`
- **AND** response 的 items 按 ID 遞增排列

#### Scenario: Paginate a config's item snapshot
- **WHEN** config 有超過 limit 的 items，App Token 帶 `skip` 與 `limit` 呼叫 endpoint
- **THEN** 系統只回傳該頁 items，並回傳正確的 `skip`、`limit`、`total` 與 `has_next`

#### Scenario: Deny cross-team config access
- **WHEN** App Token 對不在其 team scope 的 team 或不屬於 path team 的 config 呼叫 endpoint
- **THEN** 系統拒絕 request 且不回傳 item metadata

#### Scenario: Deny missing read scope
- **WHEN** App Token 不具 `test_run:read` scope 呼叫 endpoint
- **THEN** 系統回傳 `403 APP_TOKEN_SCOPE_DENIED`

