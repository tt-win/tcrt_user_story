# test-run-management-ui Specification

## Purpose

規範 Test Run Management 頁面，包含 Test Run Set CRUD、Test Case Set 範圍管理、permissions、status changes、search flows，以及 **Automation Suite 觸發**（與 Automation Hub 整合；執行入口由 Test Run Set 接管）。
## Requirements
### Requirement: Read-only Test Case Set in config edit mode
When editing an existing Test Run configuration, the system SHALL allow updating the Test Case Set scope as a multi-select list instead of enforcing a read-only single set.

#### Scenario: Edit configuration updates allowed set scope
- **WHEN** the user opens Test Run configuration in edit mode
- **THEN** the UI displays multi-select Test Case Set scope for that Test Run
- **AND** the submitted payload includes all selected set IDs
- **AND** the backend rejects invalid set IDs that do not belong to the same team

### Requirement: Read-only Test Case Set in test case edit mode
When editing Test Run test cases, the system SHALL allow selecting cases across all configured Test Case Sets and SHALL NOT force a single locked set.

#### Scenario: Edit test cases across configured sets
- **WHEN** the Test Run is configured with multiple Test Case Sets
- **THEN** the case selection modal loads cases from all configured sets
- **AND** the user can filter visible cases by one set without losing current selections

### Requirement: Multi-set scope selection in create flow
The system SHALL require selecting one or more Test Case Sets when creating a Test Run and SHALL keep selection within the current team.

#### Scenario: Create Test Run with multiple sets
- **WHEN** the user creates a new Test Run and selects multiple Test Case Sets
- **THEN** the Test Run is created successfully with all selected set IDs recorded
- **AND** empty selection is rejected with a user-visible validation message

### Requirement: Automatic item cleanup on set-scope reduction
The system SHALL automatically remove invalidated Test Run items when set scope is reduced during Test Run edit flow.

#### Scenario: Remove set and prune affected items
- **WHEN** the user removes a Test Case Set from Test Run scope in edit mode
- **AND** existing Test Run items still belong to that removed set
- **THEN** the save succeeds with the new set scope
- **AND** Test Run items from removed sets are deleted from that Test Run
- **AND** the UI receives and shows a cleanup summary (removed item count)

### Requirement: Dedicated assets for Test Run Management
The system SHALL load Test Run Management styles and scripts from dedicated static files and keep the template markup free of inline CSS/JS beyond asset wiring.

#### Scenario: Page loads with external assets
- **WHEN** the user opens the Test Run Management page
- **THEN** the page loads the dedicated CSS/JS assets and renders without inline style/script blocks

### Requirement: Functional parity after asset refactor
The system SHALL preserve existing Test Run Management behaviors for permissions, status changes, set/config management, and search flows after the refactor.

#### Scenario: Core flows remain available
- **WHEN** the user views the page, updates statuses, edits configurations, and uses search
- **THEN** the UI responds as before with no missing controls or errors

### Requirement: Test Run Set MUST support automation suite membership

Test Run Set SHALL 支援把多個 `automation_script_groups`（automation suite）加為自己的成員，用新欄位 `automation_suite_ids: list[int]` 表示。此能力 SHALL 同時可由既有 JWT API 與 app-token API 操作；app-token API SHALL 強制同 team 與 `test_run:write` scope。

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

#### Scenario: App token 建立含 automation suites 的 Test Run Set
- **WHEN** app token 具備 `test_run:write` 並在 app-token payload 帶 `automation_suite_ids`
- **THEN** 系統 SHALL 套用同 team validation
- **AND** audit SHALL 記錄 app-token principal

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

Test Run Set detail 頁 SHALL 提供「Run as Automation」CTA，呼叫 `POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation`。App-token API SHALL 提供等價 automation trigger endpoint，但 SHALL 仍使用同一 Test Run Set orchestration service，不得新增平行執行通道。

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

#### Scenario: App token 觸發 automation suites
- **WHEN** app token 具備 `automation:execute` 並呼叫 app-token automation trigger endpoint
- **THEN** 系統 SHALL 觸發該 Test Run Set 的所有 automation suites
- **AND** audit SHALL 標記 app-token principal 與 `trigger_source="app-token"`

### Requirement: Test Run Set Recent Runs section MUST include automation runs

Test Run Set detail 頁的「Recent Runs」section SHALL 包含：
- 手動測試 runs（既有行為，不變）
- 由 `test_run_set_id` 對應的 automation runs

每列顯示：status badge、suite name（或 "Automation: <suite name>"）、started_at、duration、trigger_source（"Test Run Set" / "Manual"）、external_run_url、report_url。

#### Scenario: Test Run Set 觸發的 run 顯示在 Recent Runs
- **WHEN** Test Run Set 透過「Run as Automation」觸發 N 個 suite
- **THEN** Test Run Set detail 頁的「Recent Runs」section SHALL 在下次載入時顯示這 N 個新 run
- **AND** 每列 SHALL 顯示「Test Run Set」chip 標示觸發來源

### Requirement: Automation Hub Suite detail MUST surface linked Test Run Sets

Automation Hub Suite detail 頁 SHALL 顯示「Linked Test Run Sets」section，列出 `automation_suite_ids` 含此 suite 的所有 Test Run Set（顯示 set name 與連結）。讓 user 從 Hub 反向找到 Test Run Set。

#### Scenario: Suite 已被多個 Test Run Set 引用
- **WHEN** user 進入 suite detail 頁
- **THEN** 顯示「Linked Test Run Sets」section，列出所有引用此 suite 的 Test Run Set
- **AND** 每列 SHALL 為可點擊連結，跳轉到 Test Run Set detail 頁
- **WHEN** 該 suite 未被任何 Test Run Set 引用
- **THEN** 顯示「Not yet linked to any Test Run Set.」+「Go to Test Run Management」CTA

