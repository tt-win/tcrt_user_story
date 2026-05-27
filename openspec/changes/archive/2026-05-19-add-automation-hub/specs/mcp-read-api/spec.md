# mcp-read-api Specification (MODIFIED)

## Purpose
此 delta 修改既有 `mcp-read-api` capability，將 test case detail schema 擴充以攜帶 linked automation scripts 概要，讓 AI Helper / MCP client 可在單次取得測試案例詳情時得知該 case 的自動化覆蓋情況。

## ADDED Requirements

### Requirement: MCP test case detail schema MUST include linked automation scripts
既有 `MCPTestCaseDetailItem` SHALL 追加兩個欄位：

- `linked_automation_script_count`：integer，該 case 被連結的 automation script 總數
- `linked_automation_scripts`：array，每筆包含：
  - `script_id`：integer
  - `name`：string
  - `script_format`：string（`PLAYWRIGHT_PY_ASYNC` / `PYTEST` / `PLAYWRIGHT_JS` / `OTHER`）
  - `link_type`：string（`PRIMARY` / `COVERS` / `REFERENCES`）
  - `last_run_status`：string（`SUCCEEDED` / `FAILED` / `RUNNING` / `QUEUED` / `CANCELLED` / `UNKNOWN` / `null`）
  - `last_run_at`：string (ISO 8601) or null
  - `last_run_url`：string or null（CI 端 run URL）
  - `report_url`：string or null（ResultProvider 提供）

當該 case 無 linked script 時 `linked_automation_script_count=0`、`linked_automation_scripts=[]`。

#### Scenario: Existing clients remain compatible
- **WHEN** 既有 MCP client 取得 test case detail，無視新欄位
- **THEN** 回應 SHALL 保留所有原欄位，client SHALL 不受影響

#### Scenario: Test case with multiple linked automation scripts
- **WHEN** test case 同時被 1 支 PRIMARY + 2 支 COVERS automation script 連結
- **THEN** `linked_automation_script_count=3`，`linked_automation_scripts` SHALL 為 3 筆，各帶對應 `link_type` 與最新 run 狀態

#### Scenario: Linked script with no run yet
- **WHEN** linked script 從未執行過
- **THEN** 該筆的 `last_run_status`, `last_run_at`, `last_run_url`, `report_url` SHALL 全為 `null`

#### Scenario: Audit records remain unchanged
- **WHEN** MCP client 取得擴充後的 test case detail
- **THEN** 既有 audit 紀錄行為 SHALL 不變（仍為單筆 READ on TEST_CASE），新欄位 SHALL 不額外觸發 audit
