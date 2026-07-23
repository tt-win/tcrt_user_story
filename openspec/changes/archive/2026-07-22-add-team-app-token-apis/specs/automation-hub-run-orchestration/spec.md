# automation-hub-run-orchestration Specification

## MODIFIED Requirements

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
