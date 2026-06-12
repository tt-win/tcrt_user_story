# Tasks — move-run-history-to-test-run-set

> 順序由上往下；每個 task 完成後 commit 一次以利 review 與回滾。

## 1. 後端：移除 Automation Hub run API

- [x] 1.1 刪 `app/api/automation_runs.py`（含 list/get/cancel/reconcile/sync/sync-pending 6 個 endpoint）
- [x] 1.2 從 `app/api/__init__.py` 移除 `from .automation_runs import ...` 與 `include_router(automation_runs_router)`
- [x] 1.3 `app/services/automation/script_group_service.py`：移除 `load_recent_runs` 與 `recent_runs` 欄位（dict helper 與 ORM `recent_runs: list[AutomationRunResponse]` 欄位）
- [x] 1.4 `app/api/automation_script_groups.py`：suite detail 不再 load 與傳遞 `recent_runs`
- [x] 1.5 `app/services/automation/run_service.py`：在 `list_runs` 加可選 `test_run_set_id` 過濾；`automation_run_to_dict` 加 `test_run_set_id` 欄位
- [x] 1.6 `app/models/automation_run.py`：`AutomationRunResponse` 加 `test_run_set_id: Optional[int] = None`

## 2. 後端：新增 Test Run Set runs API（set-scope）

- [x] 2.1 `app/api/test_run_sets.py`：新增 `GET /{set_id}/runs`（list with status/branch filter）
- [x] 2.2 新增 `GET /{set_id}/runs/{run_id}`（含 set-scope 檢查：run.test_run_set_id == set_id，否則 404 `AUTOMATION_RUN_NOT_IN_SET`）
- [x] 2.3 新增 `POST /{set_id}/runs/{run_id}/cancel`（set-scope + audit + lifecycle event）
- [x] 2.4 新增 `POST /{set_id}/runs/{run_id}/reconcile`（set-scope + audit + lifecycle event）
- [x] 2.5 共用 helpers（`_run_write`、`_run_not_found_in_set`、`_log_run_action`、`_fire_run_lifecycle_events`、`AutomationRunReconcileRequest`）

## 3. MCP：把 automation-runs 改成 set-scope

- [x] 3.1 `app/api/mcp.py`：把 `GET /teams/{team_id}/automation-runs` 改成 `GET /teams/{team_id}/test-run-sets/{set_id}/automation-runs`（filter 限縮為 `status` / `branch`）
- [x] 3.2 `app/models/mcp.py`：`MCPAutomationRunItem` 加 `test_run_set_id`；`MCPLinkedAutomationSummary` 移除 `last_run_*`；`MCPAutomationScriptItem` 移除 `last_run_*`
- [x] 3.3 `app/services/automation/linkage_service.py`：`list_linked_automation` 不再帶 `last_run_*`；刪除 `_latest_run`
- [x] 3.4 `app/models/automation_link.py`：`LinkedAutomationSummary` 移除 `last_run_*`

## 4. 前端：移除 Hub Runs tab + script/suite 內的 inline runs

- [x] 4.1 `app/templates/automation_hub.html`：刪 `runs-tab` / `runs-pane` / `runSuiteModal` / `reportEmbedModal` / 對應 script tag
- [x] 4.2 刪 `app/static/js/automation-hub/runs/` 整個目錄
- [x] 4.3 `app/static/js/automation-hub/suites/main.js`：`renderScriptPreview` 不再呼叫 `renderScriptRuns`；移除 `loadScriptRuns` 與 `scriptRuns*` state；`renderSuiteDetail` 改顯示「Run history lives in Test Run Set detail」訊息
- [x] 4.4 `app/static/css/automation-hub.css`：刪 `automation-runs-wrap` / `automation-run-table` / `automation-run-filters` 等 run table 相關 CSS
- [x] 4.5 `app/static/js/test-case-management/automation-panel.js`：移除 case panel 中的 last_run_status / last_run_at / last_run_url 顯示，僅保留 link 與來源 chip
- [x] 4.6 i18n 清理（`automationHub.tabs.runs`、`automationHub.runs.*`、`automationHub.scripts.lastRuns/noRuns/runsPending/runsLoadFailed/openInCi/report`、`automationHub.suites.detailRecentRuns`）+ 新增 `automationHub.suites.runsMoved`（× 3 locale）

## 5. 前端：Test Run Set 詳情頁加 Runs section

- [x] 5.1 `app/templates/test_run_management.html`：新增 `setDetailAutomationRuns*` section + `reportEmbedModal`
- [x] 5.2 新檔 `app/static/js/test-run-management/run-history.js`：`TestRunSetRunHistory` 全域（loadForSet / clear / cancelRun / reconcileRun / openReport）
- [x] 5.3 `set-modal.js`：`openTestRunSetDetail` 結束時呼叫 `TestRunSetRunHistory.loadForSet(setId, teamId)`；modal close 時呼叫 `clear()`
- [x] 5.4 i18n 新增 `testRun.sets.detail.automationRuns*` 13 個 key（× 3 locale）

## 6. 測試

- [x] 6.1 `app/testsuite/test_mcp_automation.py`：seed 改用 `test_run_set_id`、換新端點、移除 `last_run_status` 斷言
- [x] 6.2 新檔 `app/testsuite/test_test_run_set_run_history_api.py`：11 個 case（list / status filter / branch filter / cross-set exclusion / get in set / cross-set 404 / unknown run 404 / cancel / cross-set cancel 404 / reconcile / cross-set reconcile 404）
- [x] 6.3 `app/testsuite/test_test_run_set_run_automation_api.py` 與 `test_automation_run_service.py` 既有測試仍全綠

## 7. 文檔與 Archive

- [x] 7.1 `docs/automation-hub-overview.md`：刪 Runs tab 描述；說明 run history 移到 Test Run Set
- [x] 7.2 `docs/user_manual.md`：Test Run Sets 段落加註「Run history also lives here」
- [x] 7.3 `openspec archive move-run-history-to-test-run-set --yes --skip-specs`（主 spec 已在 §1-§6 實作時手動同步）
