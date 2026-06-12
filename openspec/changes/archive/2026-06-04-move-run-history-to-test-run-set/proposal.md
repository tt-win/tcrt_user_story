## Why

在 `move-automation-execution-to-test-run-set` 之後，Automation Hub 雖然拿掉了所有 run 觸發入口，但 `Runs` 頁籤（run history 列表）仍殘留。Run history 是 trigger 的對偶概念：執行從哪裡出發，結果就要回到同一個地方。當 trigger 已全面搬到 Test Run Set 時，run history 仍滯留在 Hub 會造成 UX 分裂 — 使用者要記得「觸發到 Set，結果卻要去 Hub 看」。

## What Changes

- 移除 Automation Hub 的 `Runs` 頁籤（HTML、JS 模組 `app/static/js/automation-hub/runs/`、相關 CSS、3 個 locale 的 i18n keys）
- 移除 Hub 內 suite 詳情／script 預覽所附帶的「Recent Runs」inline 顯示（依賴 `automation-script-groups.recent_runs` 與 `/api/teams/{team_id}/automation-runs?script_id=` 端點）
- 移除 MCP 對應的 `last_run_*` 欄位（`MCPAutomationScriptItem`、`LinkedAutomationSummary`、`MCPLinkedAutomationSummary`）— script 與 run 已不再直接耦合
- 移除公開的 run API 端點：
  - `GET /api/teams/{team_id}/automation-runs`
  - `GET /api/teams/{team_id}/automation-runs/{run_id}`
  - `POST /api/teams/{team_id}/automation-runs/{run_id}/cancel`
  - `POST /api/teams/{team_id}/automation-runs/{run_id}/reconcile`
  - `POST /api/teams/{team_id}/automation-runs/{run_id}/sync`
  - `POST /api/teams/{team_id}/automation-runs/sync-pending`
  - `POST /api/mcp/teams/{team_id}/automation-runs`
- 新增 Test Run Set 內的 run API 端點（set-scope 強制）：
  - `GET /api/teams/{team_id}/test-run-sets/{set_id}/runs`
  - `GET /api/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}`
  - `POST /api/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}/cancel`
  - `POST /api/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}/reconcile`
- 新增 MCP 端點：`GET /api/mcp/teams/{team_id}/test-run-sets/{set_id}/automation-runs`（必須帶 set id）
- Test Run Set 詳情頁新增 `Automation Runs` section，列出 `test_run_set_id == set.id` 的 runs（取消、reconcile、報表嵌入）
- Hub 已廢止的 `runSuiteModal` / `reportEmbedModal` 兩塊 modal HTML 一併移除（後者遷移到 Test Run Set 詳情頁）

## Capabilities

### Modified Capabilities
- `automation-hub-run-orchestration`：刪除 Hub 對 run history 的所有對外契約（API + UI + MCP `last_run_*` 欄位）
- `test-run-management-ui`：Test Run Set 詳情頁新增 `Automation Runs` section，承接 set-scope run list / cancel / reconcile / 報表嵌入

## Impact

- **後端 service**：`AutomationRunService.list_runs` 新增可選 `test_run_set_id` 參數；`automation_run_to_dict` 加 `test_run_set_id` 欄位
- **後端 model**：`AutomationRunResponse`、`MCPAutomationRunItem`、`MCPLinkedAutomationSummary`、`LinkedAutomationSummary` 移除 `last_run_*` 或加 `test_run_set_id` 視場景
- **前端**：刪 `runs/` JS 模組、刪 3 個 i18n 區段、新增 `app/static/js/test-run-management/run-history.js` + i18n `testRun.sets.detail.automationRuns*`
- **migration**：無（資料 schema 不變；`automation_runs.test_run_set_id` 已在 `move-automation-execution-to-test-run-set` 加入）
- **相容性**：純 API 與 UI 移除，無自動遷移；既有 webhook inbound（`/run-status`、`/allure-results`）仍更新既有 run rows，但這些 rows 會因 `test_run_set_id=NULL` 不再出現在新的 set-scope list 中
- **資料風險**：MCP / 第三方整合若仍打 `GET /api/.../automation-runs` 會 404 / 405；migration window 內需更新 client
