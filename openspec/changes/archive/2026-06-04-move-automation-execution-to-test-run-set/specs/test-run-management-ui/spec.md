# Delta Spec — test-run-management-ui

> 對 `openspec/specs/test-run-management-ui/spec.md` 的 delta，記錄「Test Run Set 新增 automation suite 觸發能力」對既有 requirement 的影響。

## ADDED Requirements

### Requirement: Test Run Set MUST support automation suite membership

Test Run Set SHALL 支援把多個 `automation_script_groups`（automation suite）加為自己的成員，用新欄位 `automation_suite_ids: list[int]` 表示。

資料模型：
- `test_run_sets` 表新增 `automation_suite_ids_json TEXT`（nullable；JSON array 序列化 `[int, ...]`）
- `TestRunSetCreate` / `TestRunSetUpdate` / `TestRunSetResponse` 加 `automation_suite_ids: list[int] = []`
- POST 與 PATCH 端點 SHALL 接受 `automation_suite_ids` 欄位；每個 ID MUST 屬於同一 team（否則回 400）

#### Scenario: 建立 Test Run Set 含 automation suites
- **WHEN** user 建立新 Test Run Set 並在 payload 帶 `automation_suite_ids=[1, 5, 7]`
- **THEN** Test Run Set 建立成功，`automation_suite_ids` 儲存為 `[1, 5, 7]`
- **WHEN** 任一 suite ID 屬於其他 team
- **THEN** API SHALL 回 400 並列出不合法的 IDs

#### Scenario: 更新既有 Test Run Set 的 automation suites
- **WHEN** user PATCH 既有 Test Run Set 並帶 `automation_suite_ids=[3, 9]`
- **THEN** 該 set 的 `automation_suite_ids` 改為 `[3, 9]`
- **WHEN** 帶 `automation_suite_ids=[]`
- **THEN** 該 set 變成「無 automation suite 關聯」，`Run as Automation` CTA 變 disabled

#### Scenario: 取得 Test Run Set 詳情回 automation suites
- **WHEN** client GET `TestRunSetResponse`
- **THEN** response SHALL 包含 `automation_suite_ids: list[int]`
- **AND** 可選擇性展開 `automation_suites: list[{id, name, ci_job_name, ref_branch, script_count}]`（避免前端再多打一次 GET）

### Requirement: Test Run Set detail page MUST show Automation Suites section

Test Run Set detail 頁 SHALL 新增「Automation Suites」section，顯示與管理 `automation_suite_ids`：

- 區塊標題：「Automation Suites」
- 列表每列顯示：suite name、`ci_job_name`（若可取得）、`ref_branch`、suite 內 script 數量、移除按鈕
- 「Add Suite」按鈕 → 開 modal 列出同 team 的所有 `automation_script_groups`（不分頁，預設按 name 排序），user 勾選後送出 PATCH
- 「Remove」按鈕 → 確認後送出 PATCH（`automation_suite_ids` 移除該 ID）
- 空狀態：「This Test Run Set has no automation suites yet. Click 'Add Suite' to link an automation suite.」

#### Scenario: 新增 automation suite 到 Test Run Set
- **WHEN** user 點「Add Suite」並勾選 1 個或多個 suite
- **THEN** 送出 PATCH → response 成功 → section 重整顯示新 suite
- **AND** 自動啟用「Run as Automation」CTA（若先前因空而 disabled）

#### Scenario: 從 Test Run Set 移除 automation suite
- **WHEN** user 點某 suite 的「Remove」
- **THEN** 跳出確認 modal：「Remove <suite name> from this Test Run Set?」→ 確認後 PATCH
- **AND** section 重整；若 `automation_suite_ids` 變空，「Run as Automation」CTA 變 disabled

### Requirement: Test Run Set MUST provide Run as Automation button

Test Run Set detail 頁 SHALL 提供「Run as Automation」CTA，呼叫 `POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation`：

- CTA 顯示位置：Test Run Set detail 頁頂部（與「Test Cases」section 並列）
- CTA 啟用條件：`automation_suite_ids` 非空
- CTA disabled 時顯示 tooltip：「Add at least one automation suite to enable this action.」
- 點擊 CTA → 確認 modal（顯示「將觸發 N 個 automation suite」+ 顯示每個 suite 的 `name` / `ci_job_name` / `ref_branch` / `runner_label`）
- 確認後呼叫 API
- 成功回應後：
  - UI 顯示「已觸發 N 個 run，正在背景執行」訊息（含 `triggered_suite_ids` 與 `run_ids`）
  - 跳轉（或停留在）Test Run Set detail 頁的「Recent Runs」section
- 失敗回應（500 / CI Provider 拒絕）顯示明確錯誤訊息，CTA 恢復可點擊

#### Scenario: 點擊 Run as Automation 觸發所有 suite
- **WHEN** user 點「Run as Automation」並確認 modal
- **THEN** API 回 `{"triggered_suite_ids": [int, ...], "run_ids": [int, ...]}`
- **AND** 每個 `run_id` 對應的 `automation_runs` row SHALL `test_run_set_id` 必填
- **AND** 寫 audit `AUTOMATION_RUN` + `details.test_run_set_id` 必填、`details.trigger_source="test-run-set"`
- **AND** 觸發 outbound webhook `run.triggered`（payload 加 `test_run_set_id`）

#### Scenario: 空 automation suite 集合
- **WHEN** `automation_suite_ids` 為空 list
- **THEN**「Run as Automation」CTA SHALL 為 disabled
- **WHEN** client 仍對 API 送 `POST .../test-run-sets/{id}/run-automation`（繞過 UI）
- **THEN** API SHALL 回 400 並附 `{"code": "NO_AUTOMATION_SUITES", "message": "Test Run Set has no automation suites."}`

#### Scenario: 觸發時 suite 已不存在
- **WHEN** `automation_suite_ids` 內含已被刪除的 suite ID
- **THEN** API SHALL 回 400 並列出已不存在的 IDs

#### Scenario: 觸發時 suite 屬於其他 team
- **WHEN** `automation_suite_ids` 內含其他 team 的 suite ID（資料不一致）
- **THEN** API SHALL 回 400 並附 `{"code": "CROSS_TEAM_SUITE", "message": "Suite <id> does not belong to this team."}`

### Requirement: Test Run Set Recent Runs section MUST include automation runs

Test Run Set detail 頁的「Recent Runs」section SHALL 包含：
- 手動測試 runs（既有行為，不變）
- **新增**：由 `test_run_set_id` 對應的 automation runs

每列顯示：status badge、suite name（或 "Automation: <suite name>"）、started_at、duration、trigger_source（"Test Run Set" / "Manual"）、external_run_url、report_url。

#### Scenario: Test Run Set 觸發的 run 顯示在 Recent Runs
- **WHEN** Test Run Set 透過「Run as Automation」觸發 N 個 suite
- **THEN** Test Run Set detail 頁的「Recent Runs」section SHALL 在下次載入時顯示這 N 個新 run
- **AND** 每列 SHALL 顯示「Test Run Set」chip 標示觸發來源

### Requirement: Automation Hub Suite detail MUST surface linked Test Run Sets

（跨 capability 整合）Automation Hub Suite detail 頁 SHALL 顯示「Linked Test Run Sets」section，列出 `automation_suite_ids` 含此 suite 的所有 Test Run Set（顯示 set name 與連結）。讓 user 從 Hub 反向找到 Test Run Set。

#### Scenario: Suite 已被多個 Test Run Set 引用
- **WHEN** user 進入 suite detail 頁
- **THEN** 顯示「Linked Test Run Sets」section，列出所有引用此 suite 的 Test Run Set
- **AND** 每列 SHALL 為可點擊連結，跳轉到 Test Run Set detail 頁
- **WHEN** 該 suite 未被任何 Test Run Set 引用
- **THEN** 顯示「Not yet linked to any Test Run Set.」+「Go to Test Run Management」CTA

---

## Capability Impact Summary

| Requirement | 動作 |
|---|---|
| Read-only Test Case Set in config edit mode | 不變 |
| Read-only Test Case Set in test case edit mode | 不變 |
| Multi-set scope selection in create flow | 不變 |
| Automatic item cleanup on set-scope reduction | 不變 |
| Dedicated assets for Test Run Management | 不變 |
| Functional parity after asset refactor | 不變（Automation Suites 為新增，不破壞既有）|
| **Test Run Set MUST support automation suite membership** | **ADDED** |
| **Test Run Set detail page MUST show Automation Suites section** | **ADDED** |
| **Test Run Set MUST provide Run as Automation button** | **ADDED** |
| **Test Run Set Recent Runs section MUST include automation runs** | **ADDED** |
| **Automation Hub Suite detail MUST surface linked Test Run Sets** | **ADDED**（跨 capability）|
