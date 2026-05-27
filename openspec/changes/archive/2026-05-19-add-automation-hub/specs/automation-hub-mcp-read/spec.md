# automation-hub-mcp-read Specification

## Purpose
定義 Automation Hub 的 MCP 唯讀 API 暴露，讓 AI Helper / 第三方 MCP client 可讀取 script 列表、最近執行狀態、覆蓋率統計，並透過既有 test case detail 端點看到反向 linked automation 概要。

## ADDED Requirements

### Requirement: MCP MUST expose automation scripts list
端點 `GET /api/mcp/teams/{team_id}/automation-scripts` SHALL 回傳 team 內所有 automation scripts，每筆含：

- `id`, `name`, `description`, `script_format`
- `provider_name`, `provider_type`
- `ref_path`, `ref_branch`
- `linked_test_case_count`, `linked_test_case_numbers`（陣列，最多 20 筆）
- `last_run_status`, `last_run_at`, `last_run_url`, `last_run_report_url`
- `tags` (array), `updated_at`

Query params SHALL 支援 `?format=&linked_test_case_id=&q=&cursor=&limit=`（預設 50, max 200）。

#### Scenario: AI Helper queries automation inventory
- **WHEN** MCP machine token 持有 team_id=1 存取權，呼叫端點
- **THEN** SHALL 回傳全部 scripts，AI 可依此判斷 coverage 與最近健康度

#### Scenario: Filter by linked test case
- **WHEN** 呼叫 `?linked_test_case_id=5`
- **THEN** SHALL 回所有指向 case 5 的 scripts

### Requirement: MCP MUST expose recent automation runs
端點 `GET /api/mcp/teams/{team_id}/automation-runs` SHALL 回最近 N 筆 run（預設 50, max 200），每筆含：

- `id`, `automation_script_id`, `script_name`
- `status`, `triggered_by`
- `started_at`, `finished_at`, `duration_ms`
- `external_run_url`, `report_url`
- `branch`, `error_summary`

Query params SHALL 支援 `?script_id=&status=&since=ISO8601&until=ISO8601`。

#### Scenario: Find recent failures
- **WHEN** 呼叫 `?status=FAILED&since=2026-05-01T00:00:00Z`
- **THEN** 回該時間之後所有 FAILED runs

### Requirement: MCP MUST expose coverage summary
端點 `GET /api/mcp/teams/{team_id}/automation-coverage` SHALL 回：

```json
{
  "total_test_cases": 250,
  "with_primary_link": 80,
  "with_any_link": 145,
  "uncovered_count": 105,
  "uncovered_sample": [
    {"test_case_id": 1, "test_case_number": "TC-001", "title": "..."}
  ],
  "stale_scripts": [
    {"script_id": 5, "name": "...", "last_run_at": "...", "days_since_last_run": 45}
  ],
  "by_format": {
    "PLAYWRIGHT_PY_ASYNC": 30,
    "PYTEST": 15,
    "PLAYWRIGHT_JS": 5
  }
}
```

`uncovered_sample` 最多 50 筆。

#### Scenario: AI Helper plans new test cases
- **WHEN** AI 接到「為 sprint X 規劃測試案例」任務
- **THEN** 可呼叫此端點得知哪些 case 未覆蓋、哪些 script 已 stale，避免重複建議

### Requirement: All MCP automation reads MUST write audit
所有 automation 相關 MCP 端點存取 SHALL 透過 `audit_service.log_action()` 寫 audit，`resource_type ∈ {AUTOMATION_SCRIPT, AUTOMATION_RUN}`，`action_type=READ`，details 含 query params 與 result count。

#### Scenario: Audit captures MCP usage
- **WHEN** AI Helper 呼叫 `/api/mcp/teams/1/automation-scripts?q=login`
- **THEN** audit log SHALL 出現對應紀錄，details 含 `query=login` 與 `result_count`

### Requirement: MCP endpoints MUST respect machine principal team scope
所有端點 SHALL 透過 `mcp_dependencies.require_mcp_team_access` 驗證 machine token 對該 team_id 有讀取權限；無權限 SHALL 回 403。

#### Scenario: Cross-team access blocked
- **WHEN** machine token 只持有 team_id=2 存取權，呼叫 `team_id=1` 的端點
- **THEN** API SHALL 回 403 並寫 audit `MCP_UNAUTHORIZED_ACCESS`
