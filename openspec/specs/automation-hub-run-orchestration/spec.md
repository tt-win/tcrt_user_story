# automation-hub-run-orchestration Specification

## Purpose

規範 TCRT Automation Hub 對 automation run 資料的儲存、查詢、cancel、reconcile 契約。**執行入口已於 `move-automation-execution-to-test-run-set` 全面移轉到 Test Run Set**；Automation Hub 對外**不暴露任何 trigger 端點或 UI**。
## Requirements
### Requirement: System MUST store run metadata as external references

資料表 `automation_runs` SHALL 紀錄每次執行（不論觸發來源為何），schema MUST 包含：

- `id` PK
- `team_id` FK NOT NULL
- `automation_script_id` FK nullable（**legacy 欄位**，新 run 永遠 NULL；僅保留以相容既有 row）
- `script_group_id` FK → `automation_script_groups.id` nullable（automation suite 觸發時必填）
- `test_run_set_id` FK → `test_run_sets.id` nullable（本 change 後的主要觸發識別；Test Run Set 觸發時必填，legacy row 為 NULL）
- `provider_id` FK → `team_automation_providers.id`（CI slot 的 provider）
- `external_run_id` VARCHAR(120) nullable, indexed（CI 端的 run id；可能在 trigger 後一段時間才填上）
- `external_run_url` VARCHAR(500) nullable
- `status` ENUM(`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`, `UNKNOWN`)
- `triggered_by` ENUM(`USER`, `WEBHOOK`, `SCHEDULE`, `MCP`)
- `triggered_by_user_id` VARCHAR(64) nullable
- `triggered_by_webhook_id` FK nullable
- `tcrt_correlation_id` VARCHAR(36) NOT NULL, unique（uuid4，注入 CI workflow 的 input 用於配對）
- `ci_correlation_id` VARCHAR(120) nullable（外部呼叫端提供的 id，如 GH commit sha）
- `workflow_id` VARCHAR(200) NOT NULL（CIProvider 端的 workflow 識別）
- `branch` VARCHAR(200) NOT NULL
- `inputs_json` TEXT nullable（觸發時帶的 inputs）
- `runner_label` VARCHAR(100) nullable（實際使用的 runner label，如 "self-hosted-staging"）
- `report_url` VARCHAR(500) nullable（ResultProvider 解析後寫入）
- `started_at` DATETIME nullable
- `finished_at` DATETIME nullable
- `duration_ms` INT nullable
- `error_summary` TEXT nullable
- `last_synced_at` DATETIME nullable
- timestamps

Indexes: `(team_id, started_at)`, `(automation_script_id, started_at)`, `(script_group_id, started_at)`, `(test_run_set_id, started_at)`, `(status, last_synced_at)`, `(tcrt_correlation_id)`.

#### Scenario: tcrt_correlation_id uniqueness
- **WHEN** TCRT 觸發 2 次 run
- **THEN** 兩筆 `tcrt_correlation_id` SHALL 為不同 uuid4，且 DB 唯一索引保證

#### Scenario: external_run_id may be empty initially
- **WHEN** 剛觸發 GH Actions workflow_dispatch，API 立即回應，但 GH 尚未產生 run id
- **THEN** `automation_runs` 紀錄 SHALL 先寫入 `external_run_id=null, status=QUEUED, tcrt_correlation_id=<uuid>`，後續 sync 配對成功才填 external_run_id

#### Scenario: Test Run Set 觸發的 run 必填 test_run_set_id 與 script_group_id
- **WHEN** Test Run Set 透過 `POST .../test-run-sets/{id}/run-automation` 觸發 N 個 automation suite
- **THEN** 每個寫入的 `automation_runs` row SHALL：
  - `test_run_set_id` 為觸發的 set id（必填）
  - `script_group_id` 為該 suite id（必填）
  - `automation_script_id` 為 NULL

#### Scenario: 歷史 single-script run row 仍可查詢
- **WHEN** 查詢既有 `automation_script_id IS NOT NULL` 的歷史 row
- **THEN** API 仍回該 row（含該 legacy `automation_script_id`），UI 標示「Legacy single-script run」chip

### Requirement: System MUST NOT expose any run trigger UI or API on Automation Hub

Automation Hub 對外契約 SHALL **僅**包含 read / sync / metadata CRUD；app-token automation trigger SHALL 仍以 Test Run Set 作為入口，不得在 Automation Hub script 或 suite endpoint 重新引入 run trigger。

- ✅ 允許：
  - `GET /api/teams/{team_id}/automation-scripts`：列表
  - `GET .../automation-scripts/{id}`：詳情
  - `GET .../automation-scripts/sync`：scan trigger
  - `GET /api/teams/{team_id}/automation-script-groups`：列表
  - `GET .../automation-script-groups/{id}`：詳情
  - `POST/PATCH .../automation-scripts/{id}`：更新 metadata
  - `POST/PATCH .../automation-script-groups/{id}`：更新 suite metadata
- ❌ 禁用：
  - `POST .../automation-scripts/{id}/runs`（已移除）
  - `POST .../automation-script-groups/{id}/runs`（已移除）
  - Hub 任何 UI 內的「Run」/「Run Now」/「Run Suite」CTA

執行入口 SHALL 完全位於 Test Run Set detail 頁或其 app-token 等價 endpoint。

#### Scenario: Hub 不再觸發 run
- **WHEN** user 在 Automation Hub 任何頁面想執行 script 或 suite
- **THEN** Hub SHALL NOT 提供「Run」CTA
- **AND** UI 引導使用者到 Test Run Set 觸發（訊息內含「Add this suite to a Test Run Set」CTA 連結）

#### Scenario: 對已移除的 trigger 端點直接打
- **WHEN** client 對 `POST /automation-scripts/{id}/runs` 或 `POST /automation-script-groups/{id}/runs` 送 request
- **THEN** API SHALL 回 404 / 405
- **AND** response detail SHALL 含 `{"code": "RUN_TRIGGER_REMOVED", "message": "Use POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation instead."}`

#### Scenario: App token 不可透過 Hub endpoint 觸發
- **WHEN** app token 對 Automation Hub script 或 suite endpoint 嘗試觸發 run
- **THEN** 系統 SHALL 拒絕
- **AND** response SHALL 指向 `/api/app/teams/{team_id}/test-run-sets/{set_id}/run-automation`

### Requirement: System MUST mark automation_script_id as a legacy column

`automation_runs.automation_script_id` FK 保留為 nullable，但本 change 之後的新 run **永遠** SHALL `automation_script_id IS NULL`。UI 對歷史 legacy row 加灰色「legacy single-script」chip。

#### Scenario: 新 run 不寫 automation_script_id
- **WHEN** 本 change 之後觸發任何新的 automation run
- **THEN** 該 run 的 `automation_script_id` SHALL 為 NULL
- **WHEN** UI 顯示歷史 legacy run（`automation_script_id` 非 NULL）
- **THEN** 該列 SHALL 顯示灰色「legacy single-script」chip

### Requirement: System MUST mark test_run_set_id as the canonical trigger source

`automation_runs.test_run_set_id` SHALL 為本 change 後 run 的**主要識別欄位**：

- Test Run Set 觸發的 run：`test_run_set_id` 必填
- Legacy hub 觸發的 run（archive 前既有）：`test_run_set_id` 為 NULL
- Future webhook / schedule / MCP / app-token 觸發的 run：若 context 有 Test Run Set，`test_run_set_id` 必填

#### Scenario: 列表 query 篩選 Test Run Set 觸發
- **WHEN** 查詢 `?test_run_set_id=42`
- **THEN** API SHALL 回該 set 觸發的所有 run

#### Scenario: App token 觸發保留 canonical source
- **WHEN** app token 透過 Test Run Set 觸發 automation
- **THEN** 每筆 automation run SHALL 寫入 `test_run_set_id`
- **AND** `triggered_by` 或 details SHALL 可識別 app-token actor

### Requirement: System MUST reconcile external_run_id via correlation polling

觸發後 60 秒內，背景任務 SHALL 對 `external_run_id=null` 的 runs 反覆呼叫 `CIProvider.list_workflows`/`get_recent_runs`（或 vendor-specific 配對 method），用 `inputs.tcrt_run_id == automation_runs.tcrt_correlation_id` 配對；找到 → 寫入 external_run_id + external_run_url；60 秒仍未找到 → 標 `status=UNKNOWN` 並提供 UI 手動關聯按鈕。

#### Scenario: Successful correlation within window
- **WHEN** 觸發後 15 秒，CI 已產生 run
- **THEN** background poll SHALL 配對成功，automation_runs.external_run_id 填上 + status 同步

#### Scenario: Failed correlation
- **WHEN** 60 秒過後仍找不到對應 run（CI 可能拒絕觸發）
- **THEN** status 標 UNKNOWN；UI run detail 顯示「無法自動關聯到 CI run」+「手動關聯」按鈕，user 可貼上 external_run_id

### Requirement: System MUST sync run status periodically for non-terminal runs

背景 scheduler 任務 SHALL 每 60 秒掃描 `status ∈ {QUEUED, RUNNING}` 且 `last_synced_at < now - 60s` 的 runs，呼叫 `CIProvider.get_run_status` 取最新 status，更新 DB。候選 runs SHALL 以尚未同步（`last_synced_at IS NULL`）優先，其次依 `last_synced_at ASC` 與 `id ASC` 排序；該 query SHALL 在 SQLite、MySQL 8 與 PostgreSQL 16 上可執行。

到達終態（SUCCEEDED / FAILED / CANCELLED / UNKNOWN）後 sync SHALL 停止；同時 TCRT SHALL 呼叫 `ResultProvider.get_run_report_url` 填 `report_url`。

#### Scenario: RUNNING to SUCCEEDED transition
- **WHEN** run 在 CI 完成
- **THEN** 下次 sync SHALL 更新 status=SUCCEEDED、finished_at、duration_ms、report_url，並觸發 outbound webhook event `run.completed`

#### Scenario: 未同步 runs 跨引擎優先排序
- **WHEN** background sync 在 SQLite、MySQL 8 或 PostgreSQL 16 查詢同時含 NULL 與非 NULL `last_synced_at` 的候選 runs
- **THEN** query 不使用目標引擎不支援的 `NULLS FIRST` 語法
- **AND** NULL `last_synced_at` 的 runs 先於非 NULL runs，順序以 `last_synced_at` 與 `id` 穩定決定

### Requirement: System MUST allow cancelling runs

端點 `POST /api/teams/{team_id}/automation-runs/{run_id}/cancel` SHALL 呼叫 `CIProvider.cancel_run(external_run_id)`；成功則 status=CANCELLED、寫 audit。CIProvider 不支援 cancel 時 SHALL 回 400 並提示「Provider 不支援 cancel」。

#### Scenario: Cancel succeeds
- **WHEN** 使用者點 cancel，CI 確認取消
- **THEN** TCRT 端 status 更新為 CANCELLED；audit 紀錄 actor + 原因（user 可選填）

### Requirement: API MUST provide run list and detail

API SHALL 提供下列端點，所有端點 SHALL 要求 team 讀取權限：

- `GET /api/teams/{team_id}/automation-runs`：列表，SHALL 支援篩選 `?test_run_set_id=&script_group_id=&script_id=&status=&branch=&since=&until=&triggered_by=`，cursor 分頁（預設 50，max 200），排序 `started_at DESC`
- `GET /api/teams/{team_id}/automation-runs/{run_id}`：詳情，SHALL 含完整 metadata + report_url + 跳轉到 external_run_url

#### Scenario: Locate run by CI correlation
- **WHEN** 查詢 `?ci_correlation_id=abc123`
- **THEN** API SHALL 回對應 run（若存在）

### Requirement: UI MUST list runs and embed report links

`automation_run_history.html` SHALL 顯示 run 列表，每行：status badge、suite name（或 legacy single-script 名稱）、started_at、duration、trigger_source、external_run_url 連結、report_url 連結。

- Test Run Set 觸發的 run：顯示「Test Run Set: <set name>」chip
- Legacy single-script run：顯示「Legacy: <script name>」chip
- 純 suite run：顯示 suite name（無 chip）

點開單筆 run SHALL 顯示「在 CI 中查看 logs」「在 Allure 中查看 report」兩個按鈕，**不嘗試在 TCRT 內顯示 stdout/stderr**（讓 CI 自己處理）。

iframe embed mode（若 ResultProvider 設定）SHALL 直接在 run detail 內嵌入 `<iframe src="{report_url}">`。

#### Scenario: Click-through to CI
- **WHEN** 使用者點「View on GitHub Actions」
- **THEN** 新分頁開啟 `external_run_url`，顯示 GH 原生介面

#### Scenario: Test Run Set 觸發的 run 顯示來源
- **WHEN** 列表顯示 `test_run_set_id IS NOT NULL` 的 run
- **THEN** 該 row SHALL 顯示「Test Run Set: <set name>」chip
- **WHEN** 列表顯示 `automation_script_id IS NOT NULL` 的 legacy run
- **THEN** 該 row SHALL 顯示「Legacy: <script name>」chip

### Requirement: Script preview MUST surface recent runs (read-only)

Script preview（嵌入在 Suites tab 檔案樹展開區塊或 case detail）SHALL 顯示「Recent Runs」（最近 5 筆，showing status / started_at），**read-only** 顯示，**不再提供「Run Now」按鈕**。

Preview 區頂端 SHALL 顯示引導訊息：「To run this script, add its suite to a Test Run Set.」

#### Scenario: Read-only run history in script preview
- **WHEN** 使用者展開 script preview
- **THEN** 顯示該 script 關聯的歷史 runs（**僅** history，無 trigger CTA）
- **WHEN** 該 script 從未執行（無 `automation_runs.automation_script_id` 對應）
- **THEN** preview 顯示「No runs yet. Add this suite to a Test Run Set to run it.」訊息

### Requirement: Manual run reconcile MUST be supported

端點 `POST /api/teams/{team_id}/automation-runs/{run_id}/reconcile` SHALL 接受 user 提供的 `external_run_id`，呼叫 `CIProvider.get_run_status(external_run_id)` 驗證；驗證通過則寫入 + 更新 status。

#### Scenario: Manual link after correlation failed
- **WHEN** run 標 UNKNOWN，user 從 CI UI 找到真正的 run id 貼回 TCRT
- **THEN** TCRT SHALL 驗證並關聯，後續 sync 繼續運作

### Requirement: Audit MUST record trigger / cancel / reconcile

所有 run 相關寫操作 SHALL 寫 audit `ResourceType.AUTOMATION_RUN`，details 含 `test_run_set_id`（nullable）、`script_group_id`（nullable）、`suite_name`、`workflow_id`、`branch`、`actor`、`external_run_id`（若已知）、`trigger_source` enum（`test-run-set` / `webhook` / `schedule` / `mcp` / `app-token` / `legacy-hub-script` / `legacy-hub-suite`）。

凡經 app-token principal 觸發的 run（含 `tcrt_mcp` write tools 透過 app token 呼叫）SHALL 一律記 `trigger_source="app-token"`；`mcp` 保留為 legacy 值，新程式碼 SHALL NOT 再寫入。

#### Scenario: Test Run Set 觸發寫 audit
- **WHEN** Test Run Set 觸發 automation suite
- **THEN** audit `AUTOMATION_RUN` + `CREATE` 紀錄 SHALL：
  - `details.test_run_set_id` 必填
  - `details.script_group_id` 必填
  - `details.trigger_source="test-run-set"`
  - `details.suite_name` 必填
  - `details.workflow_id` 與 `details.branch` 必填

#### Scenario: App token 觸發寫 audit
- **WHEN** app token 觸發 automation suite
- **THEN** audit SHALL 包含 app credential id/name
- **AND** `details.trigger_source="app-token"`
- **AND** raw token 與 token hash SHALL NOT 出現在 audit

### Requirement: System MUST reject any future attempt to re-introduce Hub trigger

為防止誤植，後續程式碼 SHALL NOT 再於 `app/api/automation_scripts.py` / `app/api/automation_script_groups.py` 加 `trigger_*` 公開 endpoint，或在 `AutomationRunService` 加 `trigger_script` / `trigger_group` 公開方法。Code review 與本 spec SHALL 拒絕此類變更。

#### Scenario: Defensive code review guard
- **WHEN** 開發者嘗試新增 `trigger_automation_script_run` / `trigger_automation_script_group_run` 公開 endpoint，或新增 `trigger_script` / `trigger_group` 公開方法
- **THEN** code review SHALL 拒絕（依本 spec）

### Requirement: Run orchestration MUST resolve CI and Result providers from org-level table
觸發 run、查 status、reconcile、取 report URL 等流程使用的 `get_active_provider_record(team_id, slot, session)` SHALL 對 `slot == CI` 與 `slot == RESULT` 解析至 `system_automation_providers`；`team_id` 參數僅用於 storage slot。

呼叫端不需修改簽名，但 SHALL 透過明確的 slot enum 表達意圖；硬編 `"ci"` / `"result"` 字串 SHALL 視為 lint 違規（tasks 階段加 grep check）。

#### Scenario: Trigger run uses org-level CI provider regardless of caller team
- **WHEN** team A user 與 team B user 各自觸發一支 script
- **THEN** 兩個 run record SHALL 共用同一個 `system_automation_providers.id`（org-level）作為 CI provider 來源
- **AND** `automation_runs.provider_id` SHALL 指向該 org provider row

#### Scenario: Result URL fetched via org-level Result provider
- **WHEN** UI 渲染某 run 的「Open report」連結
- **THEN** `get_run_report_url(external_run_id)` SHALL 由 org-level Allure provider 提供，無論 run 屬於哪個 team

#### Scenario: Org CI provider missing blocks trigger across all teams
- **WHEN** Super Admin 尚未建立任何 org-level CI provider
- **THEN** 任何 team 觸發 run SHALL 失敗回 412 `PROVIDER_NOT_CONFIGURED`，錯誤 SHALL 指向「同步組織架構」modal 設定指引

