# Tasks — move-automation-execution-to-test-run-set

> 順序由上往下；每個 task 完成後 commit 一次以利 review 與回滾。

## 1. 後端 service 收斂（Automation Hub）

- [x] 1.1 從 `app/services/automation/run_service.py` 刪除 `trigger_script` 公開方法
- [x] 1.2 從 `app/services/automation/run_service.py` 刪除 `trigger_group` 公開方法（若存在）
- [x] 1.3 確認內部 helper（`_resolve_tcrt_webhook_url_for_team`、`_resolve_script_workflow`、`_build_git_context_for_script`）的呼叫者：
  - 若僅被 trigger_script / trigger_group 使用 → 移轉到 `test_run_set_service.trigger_automation_suites` 後刪
  - 若仍有其他呼叫者 → 保留
- [x] 1.4 從 `app/models/automation_run.py` 刪除 `AutomationScriptRunCreate` schema
- [x] 1.5 從 `app/models/automation_run.py` 刪除 `AutomationSuiteRunCreate` schema（若存在）
- [x] 1.6 在 `run_service.py` docstring 明確標註「Automation Hub 不再對外暴露 trigger；由 Test Run Set 呼叫內部 helper」

## 2. 後端 API 移除（Automation Hub 觸發端點）

- [x] 2.1 從 `app/api/automation_scripts.py` 刪除 `trigger_automation_script_run` handler
- [x] 2.2 從 `app/api/automation_script_groups.py` 刪除 `trigger_automation_script_group_run` handler
- [x] 2.3 移除兩個 handler 對應的 `dispatch_event_async("run.triggered", ...)` 觸發
- [x] 2.4 移除兩個 handler 對應的 `_log_run_action(...)` 觸發
- [x] 2.5 清理 `app/api/automation_scripts.py` 與 `app/api/automation_script_groups.py` 已無用的 import
- [x] 2.6 確認 `app/api/__init__.py` 仍可運作（router 仍註冊，僅內容縮減）

## 3. 後端 DB schema：Test Run Set 加 `automation_suite_ids`

- [x] 3.1 在 `app/models/database_models.py` 的 `TestRunSet` ORM class 新增 `automation_suite_ids_json: str | None` 欄位（nullable TEXT，JSON array 序列化）
- [x] 3.2 在 `app/models/test_run_set.py` 的 `TestRunSetBase` / `TestRunSetCreate` / `TestRunSetUpdate` / `TestRunSetResponse` 加 `automation_suite_ids: list[int] = []` 欄位（Pydantic 自動序列化 / 反序列化 JSON）
- [x] 3.3 新增 alembic revision：對 `test_run_sets` 加 `automation_suite_ids_json` 欄位
- [x] 3.4 跑 `alembic upgrade head` 驗證 migration 成功

## 4. 後端 service 與 API：Test Run Set 觸發 automation suite

- [x] 4.1 在 `app/services/test_run_set_service.py` 新增 `trigger_automation_suites(team_id, set_id, actor)` 方法：
  - 載入 `TestRunSet`，驗證存在
  - 對每個 `automation_suite_id`（解析 `automation_suite_ids_json`）：
    - 載入 `AutomationScriptGroup`，驗證存在於同一 team
    - 呼叫 CIProvider.trigger_run(workflow_id, branch, inputs={...test_paths, tcrt_run_id, runner_label, test_run_set_id})
    - 寫入 `automation_runs` 紀錄（`script_group_id` 必填、`test_run_set_id` 必填 — 後者需先加到 `automation_runs` 表）
- [x] 4.2 **若 `automation_runs` 表尚無 `test_run_set_id` FK**：在 `app/models/database_models.py` 的 `AutomationRun` ORM class 新增 `test_run_set_id: int | None` 欄位；新增 alembic revision 加 FK
- [x] 4.3 在 `app/api/test_run_sets.py` 新增 endpoint `POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation`：
  - 要求 `team_admin` 權限
  - 呼叫 `test_run_set_service.trigger_automation_suites`
  - 回傳 `{"triggered_suite_ids": [int, ...], "run_ids": [int, ...]}`（每個 suite 對應一個 run id）
  - 寫 audit `AUTOMATION_RUN` + `details.test_run_set_id`
  - 觸發 outbound webhook `run.triggered`（payload 加 `test_run_set_id`）
- [x] 4.4 確認 `POST /test-run-sets/{set_id}` 與 `PATCH /test-run-sets/{set_id}` 接受 `automation_suite_ids` 欄位並驗證每個 ID 都屬於同一 team
- [x] 4.5 在 `TestRunSetResponse`（GET 詳情）回傳 `automation_suite_ids` 與展開後的 `automation_suites` 詳細資料（避免前端再多打一次 GET）

## 5. 前端：Automation Hub 移除所有執行按鈕

- [x] 5.1 從 `app/static/js/automation-hub/suites/main.js` 刪除：
  - `data-script-run` / `data-script-run-now` / `data-suite-run` / `data-suite-run-now` click handler
  - 對應的 `state.runScriptId` / `state.runSuiteId` 等欄位
- [x] 5.2 從 `app/static/js/automation-hub/coverage/main.js` 刪除「Run Now / Run」按鈕綁定
- [x] 5.3 從 `app/static/js/test-case-management/automation-panel.js` 刪除「Run」CTA（若仍有）
- [x] 5.4 從 `app/templates/automation_hub.html` 刪除：
  - Script preview 內的「Run Now」按鈕 markup
  - Suite detail 內的「Run Suite」與「Run this script only」按鈕 markup
  - Coverage tab script row 的「Run」按鈕 markup
- [x] 5.5 從 `app/static/css/automation-hub.css` 刪除 `.automation-run-script-button` / `.automation-run-suite-button` 等樣式
- [x] 5.6 確認 `app/static/locales/{en-US,zh-TW,zh-CN}.json` 刪除 `automationHub.runNow.*` / `automationHub.runSuite.*` 等 i18n key
- [x] 5.7 確認 Hub 整體仍可載入（無 JS 錯誤、無 dangling event handler）

## 6. 前端：Test Run Set 新增 Automation Suites section

- [x] 6.1 在 `app/templates/test_run_management.html`（或對應的 set detail template）新增「Automation Suites」section
- [x] 6.2 section 顯示當前 `automation_suite_ids` 對應的 suite 列表（name、ci_job_name、ref_branch、script count）
- [x] 6.3 section 提供「Add Suite」按鈕 → 開 modal 列出同 team 的所有 `automation_script_groups`（不分頁，預設按 name 排序）
- [x] 6.4 section 提供每個 suite 的「Remove」按鈕
- [x] 6.5 在 Test Run Set detail 頁加「Run as Automation」CTA（disabled 當 `automation_suite_ids` 為空）
- [x] 6.6 點擊「Run as Automation」→ 確認 modal（顯示「將觸發 N 個 automation suite」與 runner_label / branch）→ 確認後送 `POST .../test-run-sets/{set_id}/run-automation`
- [x] 6.7 觸發成功後跳轉到 Test Run Set 詳情頁並顯示「已觸發 N 個 run，正在背景執行」訊息
- [x] 6.8 在 `app/static/locales/{en-US,zh-TW,zh-CN}.json` 加 `testRunSet.automationSuites.*` / `testRunSet.runAsAutomation.*` i18n key
- [x] 6.9 在 `app/static/css/test-run-management.css` 加對應樣式

## 7. i18n 清理

- [x] 7.1 從 `app/static/locales/en-US.json` 刪除 `automationHub.runNow.*` / `automationHub.runSuite.*` 全系列 key
- [x] 7.2 同步刪除 `zh-TW.json` / `zh-CN.json` 對應 key
- [x] 7.3 在三語系新增 `testRunSet.automationSuites.*` / `testRunSet.runAsAutomation.*` key

## 8. 測試清理與新增

- [x] 8.1 從 `app/testsuite/test_automation_script_runs_api.py` 刪除 `trigger_automation_script_run` 測試
- [x] 8.2 從 `app/testsuite/test_automation_group_runs_api.py` 刪除 `trigger_automation_script_group_run` 測試
- [x] 8.3 從 `app/testsuite/test_automation_script_runs_api.py` 與 `test_automation_group_runs_api.py` 確認沒有殘留 import
- [x] 8.4 從 `app/testsuite/test_automation_run_service.py` 刪除 `trigger_script` / `trigger_group` 直接呼叫測試
- [x] 8.5 **新檔** `app/testsuite/test_test_run_set_automation.py`：
  - 測 Test Run Set 設定 `automation_suite_ids`（create / update / GET）
  - 測 `POST .../test-run-sets/{id}/run-automation` 觸發後 `automation_runs` 寫入正確（`script_group_id` 與 `test_run_set_id` 必填）
  - 測 suite 屬於其他 team → 400
  - 測 suite 已被刪除 → 400
  - 測空 `automation_suite_ids` → 400（無 suite 可觸發）
- [x] 8.6 跑 `pytest app/testsuite -k "automation or test_run_set" -q` 確認綠

## 9. 跨 change 同步（**本 change archive 前必做**）

- [x] 9.1 編修 `openspec/changes/add-webhook-suite-trigger/proposal.md`：移除「automation_script_id 為 webhook event 必填錨點」段落
- [x] 9.2 編修 `add-webhook-suite-trigger/design.md`：webhook payload 的 `automation_script_id` 改為「nullable legacy」；`script_group_id` 與 `test_run_set_id` 為主要識別
- [x] 9.3 編修 `add-webhook-suite-trigger/specs/automation-hub-webhook-integration/spec.md`：
  - `run.triggered` contract：payload 必有 `script_group_id` 與 `test_run_set_id`
  - 加 scenario：「WHEN Test Run Set 觸發 automation suite THEN payload SHALL NOT 包含非 NULL `automation_script_id`」
- [x] 9.4 確認 `add-webhook-suite-trigger` 的 webhook payload 範例與本 change 一致

## 10. 文檔更新

- [x] 10.1 更新 `docs/automation-hub-overview.md`：把「Trigger automation runs」從 Automation Hub 描述中刪除，改寫為「Sync hub: scan / link / metadata only」
- [x] 10.2 更新 `docs/automation-security.md`：`AUTOMATION_SCRIPT` 從「CRUD + 觸發」改為「CRUD」；`AUTOMATION_SCRIPT_GROUP` 從「CRUD + 觸發」改為「CRUD」；`TEST_RUN_SET` 從「CRUD」改為「CRUD + 觸發 automation suite」
- [x] 10.3 更新 `docs/test-run-management.md`（若存在）：新增「Automation Suites」section 與「Run as Automation」CTA 描述
- [x] 10.4 README 的 Automation Hub 區段同步刪除單 script / suite 觸發示意；Test Run Set 區段加 automation trigger 描述
- [x] 10.5 補一段「Automation execution now goes through Test Run Set」的 release notes 段落，明確說明新行為與遷移路徑

## 11. 驗證

- [x] 11.1 `openspec validate move-automation-execution-to-test-run-set --strict` 通過
- [x] 11.2 `pytest app/testsuite -q` 全綠
- [x] 11.3 `rg "trigger_script|trigger_automation_script_run|trigger_automation_script_group_run|trigger_group" app/` 確認程式碼無殘留
- [x] 11.4 `rg "data-script-run|data-suite-run|run-script-button|run-suite-button" app/static/ app/templates/` 確認前端無殘留
- [x] 11.5 啟動服務（`./start.sh`）手動驗證：
  - Automation Hub Suites tab script row 展開無「Run Now」按鈕
  - Automation Hub Coverage tab script row 無「Run」按鈕
  - Automation Hub Suite detail 無「Run Suite」按鈕
  - Test Case 詳情 Automation 面板 linked script 無「Run」CTA，但 linked scripts 列表與 recent runs 仍顯示
  - Test Run Set detail 有「Automation Suites」section 與「Run as Automation」按鈕
  - 點擊「Run as Automation」→ 確認 modal → 觸發成功 → 跳轉顯示
  - 對已移除的 API 路徑（`POST /automation-scripts/{id}/runs`、`POST /automation-script-groups/{id}/runs`）直接打，回 404 / 405
  - 新的 API 路徑 `POST /test-run-sets/{id}/run-automation` 正常運作

## 12. Archive 流程

- [x] 12.1 確認 1-11 全部 ✓
- [x] 12.2 確認 `add-webhook-suite-trigger` 跨 change 編修已 commit
- [x] 12.3 跑 `openspec archive move-automation-execution-to-test-run-set --yes` 封存
- [x] 12.4 封存後驗證 `openspec/specs/automation-hub-run-orchestration/spec.md` 與 `openspec/specs/test-run-management-ui/spec.md` 已反映新行為
