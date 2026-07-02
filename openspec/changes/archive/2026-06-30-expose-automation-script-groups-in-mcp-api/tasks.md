## 1. Pydantic 模型

- [x] 1.1 在 [`app/models/mcp.py`](app/models/mcp.py) 新增 `MCPAutomationScriptGroupItem(BaseModel)`，欄位：`id: int`、`name: str`、`description: Optional[str] = None`、`ref_repo: Optional[str] = None`、`script_ids: List[int]`、`script_paths: List[str]`、`script_count: int = 0`、`ci_job_name: Optional[str] = None`、`ci_job_type: Optional[str] = None`、`created_at: Optional[datetime] = None`、`updated_at: Optional[datetime] = None`。
- [x] 1.2 新增 `MCPTeamAutomationScriptGroupsResponse(BaseModel)`，欄位：`team_id: int`、`items: List[MCPAutomationScriptGroupItem]`、`page: MCPPageMeta`。

## 2. Route Handler

- [x] 2.1 在 [`app/api/mcp.py`](app/api/mcp.py) 新增 import：`AutomationScriptGroup as AutomationScriptGroupDB`，以及兩個新模型。
- [x] 2.2 新增 route handler `list_team_automation_script_groups`，路徑 `@router.get("/teams/{team_id}/automation-script-groups", response_model=MCPTeamAutomationScriptGroupsResponse)`，沿用 `require_mcp_team_access`。
- [x] 2.3 在 handler 內：`_ensure_team_exists`、`keyword` 過濾（name/description ilike）、`skip`/`limit` 分頁、`order_by(id.desc())`。
- [x] 2.4 用**單次** batch query 把所有 group 的 `script_paths` 解析為 `path → script id`（`team_id` + `ref_path IN (...)`），per-group 依 stored 順序映射、跳過無法解析的 path。

## 3. URL 一致性

- [x] 3.1 確認最終 URL 為 `/api/mcp/teams/{team_id}/automation-script-groups`，命名與既有 `/automation-scripts`、`/automation-coverage` 對齊。

## 4. Tests

- [x] 4.1 在 [`app/testsuite/test_mcp_automation.py`](app/testsuite/test_mcp_automation.py) 的 `_seed` 新增一個 `AutomationScriptGroup`（含兩條可解析 path + 一條 stale path），回傳 `suite_id`。
- [x] 4.2 撰寫測試：列表回傳 suite，`script_paths` 完整保留（含 stale），`script_count == 3`，`script_ids` 依序為兩個可解析 script id（stale 略過）。
- [x] 4.3 驗證 `ci_job_name` / `ci_job_type`（"JENKINS"）/ `ref_repo` 正確序列化。

## 5. Spec 校正（runs）

- [x] 5.1 在 delta spec MODIFY 既有 "MCP MUST expose recent automation runs"：路徑改為 set-scoped `GET /api/mcp/teams/{team_id}/test-run-sets/{set_id}/automation-runs`，query params 改 `status/branch/skip/limit`，回傳欄位對齊 `MCPAutomationRunItem`，並補 `set 不存在回 404 TEST_RUN_SET_NOT_FOUND` scenario。

## 6. Docs

- [x] 6.1 在 [`docs/mcp_api_interface.md`](docs/mcp_api_interface.md) 新增「3.6 Automation 唯讀端點」，記錄 scripts / script-groups / test-run-set automation-runs / coverage 四支。

## 7. 驗收

- [x] 7.1 `pytest app/testsuite/test_mcp_automation.py app/testsuite/test_mcp_api.py -q` 全綠。
- [ ] 7.2 `openspec validate expose-automation-script-groups-in-mcp-api --strict` 通過。
- [ ] 7.3 PR description 附 curl 範例：`curl -H "Authorization: Bearer <token>" .../api/mcp/teams/1/automation-script-groups`。
