# automation-hub-run-orchestration Specification

## Purpose
定義 TCRT 觸發、追蹤、顯示自動化執行的能力。實際執行由 CIProvider 委派到外部 CI（GH Actions / GitLab / Jenkins）；TCRT 只記錄 external_run_id、同步狀態、整合 ResultProvider 提供報表跳轉。

## ADDED Requirements

### Requirement: System MUST store run metadata as external references
資料表 `automation_runs` SHALL 紀錄每次執行，schema MUST 包含：

- `id` PK
- `team_id` FK NOT NULL
- `automation_script_id` FK
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
- `report_url` VARCHAR(500) nullable（ResultProvider 解析後寫入）
- `started_at` DATETIME nullable
- `finished_at` DATETIME nullable
- `duration_ms` INT nullable
- `error_summary` TEXT nullable
- `last_synced_at` DATETIME nullable
- timestamps

Indexes: `(team_id, started_at)`, `(automation_script_id, started_at)`, `(status, last_synced_at)`, `(tcrt_correlation_id)`.

#### Scenario: tcrt_correlation_id uniqueness
- **WHEN** TCRT 觸發 2 次 run
- **THEN** 兩筆 `tcrt_correlation_id` SHALL 為不同 uuid4，且 DB 唯一索引保證

#### Scenario: external_run_id may be empty initially
- **WHEN** 剛觸發 GH Actions workflow_dispatch，API 立即回應，但 GH 尚未產生 run id
- **THEN** `automation_runs` 紀錄 SHALL 先寫入 `external_run_id=null, status=QUEUED, tcrt_correlation_id=<uuid>`，後續 sync 配對成功才填 external_run_id

### Requirement: System MUST trigger runs via CIProvider with tcrt_run_id injection
端點 `POST /api/teams/{team_id}/automation-scripts/{script_id}/runs` SHALL：

1. 解析 script 的 CI workflow（從 script.tags 或 query param `?workflow_id=`；若未指定且 team 只有一個 workflow → 使用該唯一）
2. 產生 `tcrt_correlation_id = uuid4()`
3. 呼叫 `CIProvider.trigger_run(workflow_id, branch, inputs={**user_inputs, "tcrt_run_id": tcrt_correlation_id})`
4. 取得 `ExternalRunRef`（可能僅含 acknowledged=true、external_run_id 未知）
5. 建立 `automation_runs` 紀錄
6. 回傳 `{run_id, tcrt_correlation_id, status: "QUEUED", status_url}`

Payload 可選欄位：`workflow_id`, `branch`（預設用 script.ref_branch）, `inputs`（用 workflow 的 dispatch inputs）。

#### Scenario: Single workflow auto-selected
- **WHEN** team 只配置一個 GH Actions workflow，使用者點「執行」未指定 workflow
- **THEN** TCRT SHALL 自動用該 workflow，無需 user 選擇

#### Scenario: Multiple workflows require explicit choice
- **WHEN** team 有多個 workflow，使用者點「執行」未指定
- **THEN** UI SHALL 跳 modal 讓 user 選 workflow + branch + inputs；API 缺 `workflow_id` SHALL 回 400 並列出可選 workflows

### Requirement: System MUST reconcile external_run_id via correlation polling
觸發後 60 秒內，背景任務 SHALL 對 `external_run_id=null` 的 runs 反覆呼叫 `CIProvider.list_workflows`/`get_recent_runs`（或 vendor-specific 配對 method），用 `inputs.tcrt_run_id == automation_runs.tcrt_correlation_id` 配對；找到 → 寫入 external_run_id + external_run_url；60 秒仍未找到 → 標 `status=UNKNOWN` 並提供 UI 手動關聯按鈕。

#### Scenario: Successful correlation within window
- **WHEN** 觸發後 15 秒，CI 已產生 run
- **THEN** background poll SHALL 配對成功，automation_runs.external_run_id 填上 + status 同步

#### Scenario: Failed correlation
- **WHEN** 60 秒過後仍找不到對應 run（CI 可能拒絕觸發）
- **THEN** status 標 UNKNOWN；UI run detail 顯示「無法自動關聯到 CI run」+「手動關聯」按鈕，user 可貼上 external_run_id

### Requirement: System MUST sync run status periodically for non-terminal runs
背景 scheduler 任務 SHALL 每 60 秒掃描 `status ∈ {QUEUED, RUNNING}` 且 `last_synced_at < now - 60s` 的 runs，呼叫 `CIProvider.get_run_status` 取最新 status，更新 DB。

到達終態（SUCCEEDED / FAILED / CANCELLED / UNKNOWN）後 sync SHALL 停止；同時 TCRT SHALL 呼叫 `ResultProvider.get_run_report_url` 填 `report_url`。

#### Scenario: RUNNING to SUCCEEDED transition
- **WHEN** run 在 CI 完成
- **THEN** 下次 sync SHALL 更新 status=SUCCEEDED、finished_at、duration_ms、report_url，並觸發 outbound webhook event `run.completed`

### Requirement: System MUST allow cancelling runs
端點 `POST /api/teams/{team_id}/automation-runs/{run_id}/cancel` SHALL 呼叫 `CIProvider.cancel_run(external_run_id)`；成功則 status=CANCELLED、寫 audit。CIProvider 不支援 cancel 時 SHALL 回 400 並提示「Provider 不支援 cancel」。

#### Scenario: Cancel succeeds
- **WHEN** 使用者點 cancel，CI 確認取消
- **THEN** TCRT 端 status 更新為 CANCELLED；audit 紀錄 actor + 原因（user 可選填）

### Requirement: API MUST provide run list and detail
API SHALL 提供下列端點，所有端點 SHALL 要求 team 讀取權限：

- `GET /api/teams/{team_id}/automation-runs`：列表，SHALL 支援篩選 `?script_id=&status=&branch=&since=&until=&triggered_by=`，cursor 分頁（預設 50，max 200），排序 `started_at DESC`
- `GET /api/teams/{team_id}/automation-runs/{run_id}`：詳情，SHALL 含完整 metadata + report_url + 跳轉到 external_run_url

#### Scenario: Locate run by CI correlation
- **WHEN** 查詢 `?ci_correlation_id=abc123`
- **THEN** API SHALL 回對應 run（若存在）

### Requirement: UI MUST list runs and embed report links
`automation_run_history.html` SHALL 顯示 run 列表，每行：status badge、script name、started_at、duration、triggered_by、branch、external_run_url 連結、report_url 連結。

點開單筆 run SHALL 顯示「在 CI 中查看 logs」「在 Allure 中查看 report」兩個按鈕，**不嘗試在 TCRT 內顯示 stdout/stderr**（讓 CI 自己處理）。

iframe embed mode（若 ResultProvider 設定）SHALL 直接在 run detail 內嵌入 `<iframe src="{report_url}">`。

#### Scenario: Click-through to CI
- **WHEN** 使用者點「View on GitHub Actions」
- **THEN** 新分頁開啟 `external_run_url`，顯示 GH 原生介面

### Requirement: Script detail MUST surface recent runs and quick-run button
Script detail 頁 SHALL 在側欄或下方顯示「Recent Runs」（最近 5 筆，showing status / started_at），與顯眼的「Run Now」按鈕。

「Run Now」按鈕點擊 SHALL 觸發 modal：
- 顯示可選 workflow（從 CIProvider 列表）
- branch（預設 script.ref_branch，可改）
- workflow inputs（從 workflow YAML 解析；v1 可不解析，user 自填 key=value pairs）
- 「Trigger」按鈕送出

#### Scenario: Quick run from script detail
- **WHEN** 使用者於 script detail 點 Run Now、確認 modal
- **THEN** API 觸發 run，UI 立即跳轉到 run detail 頁顯示 status=QUEUED 並輪詢 status 變化

### Requirement: Manual run reconcile MUST be supported
端點 `POST /api/teams/{team_id}/automation-runs/{run_id}/reconcile` SHALL 接受 user 提供的 `external_run_id`，呼叫 `CIProvider.get_run_status(external_run_id)` 驗證；驗證通過則寫入 + 更新 status。

#### Scenario: Manual link after correlation failed
- **WHEN** run 標 UNKNOWN，user 從 CI UI 找到真正的 run id 貼回 TCRT
- **THEN** TCRT SHALL 驗證並關聯，後續 sync 繼續運作

### Requirement: Audit MUST record trigger / cancel / reconcile
所有 run 相關寫操作 SHALL 寫 audit `ResourceType.AUTOMATION_RUN`，details 含 script name、workflow_id、branch、actor、external_run_id（若已知）。

#### Scenario: Audit on trigger
- **WHEN** 使用者觸發 run
- **THEN** audit log SHALL 出現一筆 `AUTOMATION_RUN` + `CREATE`，details 含 `script_name`、`workflow_id`、`branch`、`tcrt_correlation_id`
