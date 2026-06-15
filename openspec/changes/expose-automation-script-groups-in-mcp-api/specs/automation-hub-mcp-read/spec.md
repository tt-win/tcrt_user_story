# automation-hub-mcp-read Specification

## ADDED Requirements

### Requirement: MCP MUST expose automation script groups (suites)
端點 `GET /api/mcp/teams/{team_id}/automation-script-groups` SHALL 回傳 team 內所有 automation script groups（可執行 suite），維持唯讀（不接受 POST / PUT / PATCH / DELETE）。回應 SHALL 含頂層 `team_id`、`items`（陣列）、`page`（`skip` / `limit` / `total` / `has_next`），與既有 `automation-scripts` 端點分頁模型一致。

每筆 `items[i]` SHALL 含：

- `id`, `name`, `description`, `ref_repo`
- `script_paths`（suite 儲存的組成，ref_path 字串陣列）
- `script_count`（等於 `len(script_paths)`）
- `script_ids`（`script_paths` 解析回現存 script id 的結果，保留 stored 順序；以 `(ref_repo, ref_path)` 解析、scoped 到 suite 自身的 `ref_repo`，因 `ref_path` 在 team 內不唯一）
- `ci_job_name`, `ci_job_type`
- `created_at`, `updated_at`

Query params SHALL 支援 `?skip=（≥0, 預設 0）&limit=（1–200, 預設 50）&keyword=`（對 `name` / `description` partial match）。Auth SHALL 沿用 `require_mcp_team_access`；不存在的 `team_id` SHALL 回 404。

#### Scenario: AI Helper 列出可執行 suite 與成員 script
- **WHEN** MCP machine token 持有該 team 存取權，呼叫 `GET /api/mcp/teams/{team_id}/automation-script-groups`
- **THEN** SHALL 回傳該 team 全部 suite，每筆含 `script_paths` 與解析後的 `script_ids`，consumer 可沿 `run.script_group_id → suite → script_ids → /automation-scripts` 導覽

#### Scenario: 無法解析的 stale path 保留於 script_paths 但不計入 script_ids
- **WHEN** 某 suite 的 `script_paths` 含一條已被改名／刪除、在 team 內查不到對應 script 的 ref_path
- **THEN** 該 path SHALL 仍出現在 `script_paths`（且計入 `script_count`），但 SHALL NOT 出現在 `script_ids`；其餘可解析的 path 仍依 stored 順序解析為 id

#### Scenario: 同 ref_path 跨 repo 不誤解析
- **WHEN** team 內另有一個 script 的 `ref_path` 與某 suite 的某條 path 相同、但 `ref_repo` 不同
- **THEN** 該 suite 的 `script_ids` SHALL 只解析到與 suite `ref_repo` 相符的 script，不得混入其他 repo 的同名 path script

#### Scenario: keyword 過濾
- **WHEN** 呼叫 `?keyword=login`
- **THEN** SHALL 僅回 `name` 或 `description` 含 `login` 的 suite

#### Scenario: 端點僅支援 GET
- **WHEN** 對 `/api/mcp/teams/{team_id}/automation-script-groups` 發出 POST / PUT / DELETE
- **THEN** API SHALL 回 `405 Method Not Allowed` 或 `404`（依 FastAPI router 配置），不執行任何寫入

## MODIFIED Requirements

### Requirement: MCP MUST expose recent automation runs
端點 `GET /api/mcp/teams/{team_id}/test-run-sets/{set_id}/automation-runs` SHALL 回傳指定 Test Run Set（須屬於該 team）所觸發的 automation runs。run 已於 `move-run-history-to-test-run-set` 全面 scoped 至其所屬 Test Run Set，故 MCP 唯讀面**不再**提供 team-wide 的 `GET .../automation-runs`。回應 SHALL 含頂層 `team_id`、`items`、`page`（`skip` / `limit` / `total` / `has_next`）。

每筆 `items[i]` SHALL 含：

- `id`, `automation_script_id`, `script_group_id`, `test_run_set_id`
- `workflow_id`, `branch`, `status`
- `triggered_by`, `triggered_by_user_id`
- `external_run_id`, `external_run_url`, `report_url`, `runner_label`
- `started_at`, `finished_at`, `duration_ms`
- `tcrt_correlation_id`, `error_summary`, `created_at`, `updated_at`

Query params SHALL 支援 `?status=&branch=&skip=（≥0, 預設 0）&limit=（1–200, 預設 50）`。

#### Scenario: 列出某 Test Run Set 的 runs
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-run-sets/{set_id}/automation-runs`
- **THEN** SHALL 回該 set 觸發的所有 run，每筆 `test_run_set_id == set_id` 並含完整 metadata

#### Scenario: status 過濾
- **WHEN** 呼叫 `?status=RUNNING` 而該 set 無 RUNNING 的 run
- **THEN** SHALL 回 `items: []`、`page.total == 0`

#### Scenario: set 不存在於該 team 回 404
- **WHEN** 呼叫的 `set_id` 不存在於目標 team
- **THEN** API SHALL 回 `404`，detail code 為 `TEST_RUN_SET_NOT_FOUND`
