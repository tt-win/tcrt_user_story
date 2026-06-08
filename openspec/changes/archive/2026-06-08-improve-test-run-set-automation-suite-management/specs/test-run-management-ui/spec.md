## MODIFIED Requirements

### Requirement: Test Run Set MUST support automation suite membership

Test Run Set SHALL 支援把多個 `automation_script_groups`（automation suite）加為自己的成員，用新欄位 `automation_suite_ids: list[int]` 表示。

資料模型：
- `test_run_sets` 表新增 `automation_suite_ids_json TEXT`（nullable；JSON array 序列化 `[int, ...]`）
- `TestRunSetCreate` / `TestRunSetUpdate` / `TestRunSetResponse` 加 `automation_suite_ids: list[int] = []`
- POST 與 PATCH 端點 SHALL 接受 `automation_suite_ids` 欄位；每個 ID MUST 屬於同一 team（否則回 400）
- `TestRunSetDetail` response SHALL 可選擇性回傳 `automation_suites: list[{id, name, ci_job_name, ref_branch, script_count}]`，供前端直接顯示 suite summary，而不必自行對 `automation_suite_ids` 做第二次查詢

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

#### Scenario: 取得 Test Run Set 詳情回 automation suites summary
- **WHEN** client GET Test Run Set detail
- **THEN** response SHALL 包含 `automation_suite_ids: list[int]`
- **AND** 若 suite id 仍可解析，response SHALL 一併回傳 `automation_suites` summary，至少含 `id`、`name`、`script_count`

### Requirement: Test Run Set detail page MUST show Automation Suites section

Test Run Set detail 頁 SHALL 新增「Automation Suites」section，顯示與管理 `automation_suite_ids`：

- 區塊標題：「Automation Suites」
- 列表每列顯示：suite name、`ci_job_name`（若可取得）、`ref_branch`、suite 內 script 數量、移除按鈕
- create/edit Test Run Set modal SHALL 內建 suite picker，列出同 team 的所有 `automation_script_groups`，支援搜尋、勾選與回填既有選項
- detail 頁的 suite section 與 create/edit modal SHALL 共用同一組 suite summary 顯示邏輯，避免某一處只顯示 `Suite #id`
- 空狀態：「This Test Run Set has no automation suites yet. Click 'Add Suite' to link an automation suite.」

#### Scenario: 建立新 Test Run Set 時直接選 suites
- **WHEN** user 在 create modal 內輸入 set name，並勾選 1 個或多個 automation suites
- **THEN** 送出 POST 後，新 set SHALL 儲存這些 suite ids
- **AND** 新建完成後打開 detail 時，Automation Suites section SHALL 顯示 suite name 與摘要，而不是只顯示 id

#### Scenario: 編輯既有 Test Run Set 時回填 suites
- **WHEN** user 打開 edit modal 編輯既有 Test Run Set
- **THEN** modal SHALL 回填目前的 suite membership
- **AND** user 若未變更 suite 勾選，儲存 SHALL 保留既有 `automation_suite_ids`，不因表單重送而清空

#### Scenario: 從 Test Run Set 移除 automation suite
- **WHEN** user 在 detail 頁移除某個 suite
- **THEN** 跳出確認訊息，確認後送出 PATCH 更新 `automation_suite_ids`
- **AND** section 重整；若 `automation_suite_ids` 變空，「Run as Automation」CTA 變 disabled

### Requirement: Test Run Set MUST provide Run as Automation button

Test Run Set detail 頁 SHALL 提供「Run as Automation」CTA，呼叫 `POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation`：

- CTA 顯示位置：Test Run Set detail 頁頂部（與「Test Cases」section 並列）
- CTA 啟用條件：`automation_suite_ids` 非空
- CTA disabled 時顯示 tooltip：「Add at least one automation suite to enable this action.」
- 點擊 CTA → 確認 modal（顯示「將觸發 N 個 automation suite」+ 每個 suite 的 `name` / `ci_job_name` / `ref_branch` / `runner_label`（若可取得））
- 確認後呼叫 API
- 成功回應後：
  - UI 顯示「已觸發 N 個 run，正在背景執行」訊息（含 `triggered_suite_ids` 與 `run_ids`）
  - 停留在 Test Run Set detail 頁，並自動 refresh Automation Suites section 與 Recent Runs section
- 失敗回應（500 / CI Provider 拒絕）顯示明確錯誤訊息，CTA 恢復可點擊

#### Scenario: 點擊 Run as Automation 前可看見 suite summary
- **WHEN** user 點「Run as Automation」
- **THEN** 確認訊息 SHALL 顯示實際 suite name 與摘要，而不是只顯示 `Suite #id`

#### Scenario: 點擊 Run as Automation 觸發所有 suite
- **WHEN** user 點「Run as Automation」並確認
- **THEN** API 回 `{"triggered_suite_ids": [int, ...], "run_ids": [int, ...]}`
- **AND** 每個 `run_id` 對應的 `automation_runs` row SHALL `test_run_set_id` 必填
- **AND** 寫 audit `AUTOMATION_RUN` + `details.test_run_set_id` 必填、`details.trigger_source="test-run-set"`
- **AND** 觸發 outbound webhook `run.triggered`（payload 加 `test_run_set_id`）

#### Scenario: Trigger 後 Recent Runs 立即可理解
- **WHEN** API 成功回應且前端 refresh detail
- **THEN** Recent Runs section SHALL 以 suite name 與 trigger source 呈現新 run，而不是只讓使用者從 toast 中看到一串 run ids
