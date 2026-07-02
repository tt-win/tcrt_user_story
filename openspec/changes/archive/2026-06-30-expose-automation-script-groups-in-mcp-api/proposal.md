## Why

`AutomationScriptGroup`（執行用的 suite，[`app/models/database_models.py:1860`](app/models/database_models.py:1860)）是 Automation Hub「可執行套件」的核心單位：每個 suite 綁定一組 script ref_paths 與一個 CI job（`ci_job_name`），並由 Test Run Set 觸發。

目前 MCP 唯讀面已暴露 automation **scripts**、**coverage**，以及某個 Test Run Set 的 **automation-runs**；automation-run item 也帶 `script_group_id`。但**沒有任何端點能反查 suite 本身**——MCP consumer 拿到 run 的 `script_group_id` 後，無法得知該 suite 的名稱、由哪些 script 組成、對應哪個 CI job，只能從零散的 run / script 反推。

實務影響：透過 MCP 連進來的 AI agent 無法回答「team X 有哪些可執行 suite？」「`script_group_id=12` 是什麼套件、含哪些 script？」這類導覽問題。

同時，本 spec 的 "recent automation runs" requirement 仍停在 `move-run-history-to-test-run-set` 之前的舊路徑 `GET .../automation-runs`，與實作（已 set-scoped 的 `GET .../test-run-sets/{set_id}/automation-runs`）不符，一併校正。

## What Changes

- 新增唯讀端點 `GET /api/mcp/teams/{team_id}/automation-script-groups`（命名對齊既有 `automation-scripts`、`automation-coverage`）：
  - Query params：`skip`（≥0, 預設 0）、`limit`（1–200, 預設 50）、`keyword`（對 `name` / `description` partial match）。
  - Response：`team_id` + `items[]` + `page{skip,limit,total,has_next}`（與既有 scripts / runs 端點分頁模型一致）。
  - 每筆 item 含 `id / name / description / ref_repo / script_paths / script_count / script_ids / ci_job_name / ci_job_type / created_at / updated_at`。
  - `script_paths` 為 suite 儲存的組成（ref_path 清單）；`script_ids` 為這些 path 解析回同 team 現存 script id 後的結果（保留 stored 順序、無法解析的 stale path 略過），`script_count == len(script_paths)`。此設計讓 consumer 能沿 `run.script_group_id → suite → 成員 script id → /automation-scripts` 串起 int-key 導覽。
  - Auth 沿用 `require_mcp_team_access`；不存在的 team 回 404；超出 scope 回 403。
- 新增 Pydantic 模型於 [`app/models/mcp.py`](app/models/mcp.py)：`MCPAutomationScriptGroupItem`、`MCPTeamAutomationScriptGroupsResponse`。
- **校正** `automation-hub-mcp-read` 既有 "MCP MUST expose recent automation runs" requirement：路徑、query params 與回傳欄位對齊已實作的 set-scoped 端點 `GET /api/mcp/teams/{team_id}/test-run-sets/{set_id}/automation-runs`。

## 非目標 (Non-goals)

- **不**提供 suite 的 mutate API（建立 / 更新 / 刪除 / 觸發維持在 user JWT 與 Test Run Set 端點）；MCP 維持唯讀。
- **不**在 item 內嵌入完整 script 物件（name / format 等）——那是 `/automation-scripts` 端點職責；本端點只回 `script_ids` + `script_paths` 作為 join key 與組成。
- **不**處理本 spec 內 "automation scripts list" requirement 的另一處 drift（仍列著已於 `move-run-history-to-test-run-set` 移除的 `last_run_*`、`provider_name` / `provider_type` 欄位與 cursor 參數）。該段與本 change 的 groups / runs 無耦合，留待後續 sync change 一併校正，以免擴大此次 diff。
- **不**改動 `automation-hub-run-orchestration` spec（非-MCP 的 `GET /api/teams/{team_id}/automation-runs` 列表 / 詳情契約不在範圍）。

## Capabilities

### Modified Capabilities
- `automation-hub-mcp-read`：新增 automation script groups（suites）唯讀端點與對應 Pydantic 模型；並校正 automation-runs requirement 至 set-scoped 實作。

## Impact

### Code（已實作）
- [app/api/mcp.py](app/api/mcp.py)：新增 `list_team_automation_script_groups` route handler（含單次 batch query 解析 ref_path → script id）；新增 `AutomationScriptGroup` import。
- [app/models/mcp.py](app/models/mcp.py)：新增 `MCPAutomationScriptGroupItem`、`MCPTeamAutomationScriptGroupsResponse`。

### Docs
- [docs/mcp_api_interface.md](docs/mcp_api_interface.md)：新增「Automation 唯讀端點」章節，補上 scripts / script-groups / test-run-set automation-runs / coverage 四支（此前完全未記錄）。

### Tests（已實作）
- [app/testsuite/test_mcp_automation.py](app/testsuite/test_mcp_automation.py)：`_seed` 增一個 suite（含一條 stale path）；新增測試驗證列表、成員 id 解析、stale path 略過。

### Migration / 相容性
- 純新增端點 + 既有 runs requirement 的文字校正；無 DB migration、無實際路由破壞（runs 端點程式早已 set-scoped，本 change 只讓 spec 追上）。
- 舊 MCP consumer 不感知新端點，行為不變。

### 解析正確性
- `ref_path` 在 team 內**不唯一**（unique key 含 `ref_repo`：`team_id+provider_id+ref_repo+ref_path+ref_branch`）。`script_ids` 解析以 `(ref_repo, ref_path)` 為 key 並 scoped 到 suite 自身的 `ref_repo`，比照 canonical `AutomationScriptGroupService.load_group_scripts`，避免跨 repo 同名 path 誤解析到別的 repo 的 script。
- 解析 `script_paths_json` 改用 canonical `_load_script_paths`（會 strip／丟空白項），與 Test Run Set 觸發路徑對「suite 組成」的認定一致。
