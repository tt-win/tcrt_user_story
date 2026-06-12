# Delta Spec — automation-hub-run-orchestration

> 對 `openspec/specs/automation-hub-run-orchestration/spec.md` 的 delta，記錄「Automation Hub 拿掉所有 run trigger（含 single + suite），執行入口全面移轉到 Test Run Set」對既有 requirement 的影響。

> 註：原主 spec 已被 §1-§4 實作手動改寫；本 delta 保留以 archive 流程可同步 ADDED 與 MODIFIED 為主。`REMOVED Requirements` 段刻意省略 — 對應的舊 requirement 已在主 spec 直接刪除。

## MODIFIED Requirements

### Requirement: System MUST store run metadata as external references

資料表 `automation_runs` SHALL 紀錄每次執行，schema MUST 包含 `test_run_set_id` FK → `test_run_sets.id` nullable（本 change 後的主要觸發識別；Test Run Set 觸發時必填，legacy row 為 NULL）。`automation_script_id` FK 保留為 nullable（**純 legacy 欄位**，新 run 永遠 NULL）。index list 加 `(test_run_set_id, started_at)` 與 `(script_group_id, started_at)`。

#### Scenario: Test Run Set 觸發的 run 必填 test_run_set_id 與 script_group_id
- **WHEN** Test Run Set 透過 `POST .../test-run-sets/{id}/run-automation` 觸發 N 個 automation suite
- **THEN** 每個寫入的 `automation_runs` row SHALL：
  - `test_run_set_id` 為觸發的 set id（必填）
  - `script_group_id` 為該 suite id（必填）
  - `automation_script_id` 為 NULL

#### Scenario: 歷史 single-script run row 仍可查詢
- **WHEN** 查詢既有 `automation_script_id IS NOT NULL` 的歷史 row
- **THEN** API SHALL 仍回該 row（含該 legacy `automation_script_id`），UI SHALL 標示「Legacy: <script name>」並加灰色 chip

### Requirement: UI MUST list runs and embed report links

Run history 列表 SHALL 新增「Trigger source」column，顯示「Test Run Set: <set name>」/「Legacy: <script name>」/ suite name（純 suite run）等來源。Legacy single-script run SHALL 顯示「Legacy: <script name>」chip；純 suite run SHALL 顯示 suite name（無 chip）。原本「Run Now」相關的 quick-trigger 段 SHALL 已刪除。

#### Scenario: Test Run Set 觸發的 run 在 history 顯示來源
- **WHEN** 列表顯示 `test_run_set_id IS NOT NULL` 的 run
- **THEN** 該 row SHALL 顯示「Test Run Set: <set name>」chip
- **AND** 列表顯示 `automation_script_id IS NOT NULL` 的 legacy run SHALL 顯示「Legacy: <script name>」chip

### Requirement: Audit MUST record trigger / cancel / reconcile

Audit 寫入 SHALL 在 `details` 物件加 `test_run_set_id`（nullable，Test Run Set 觸發時必填）與 `trigger_source` enum（`"test-run-set"` / `"legacy-hub-script"` / `"legacy-hub-suite"` / `"webhook"` / `"schedule"` / `"mcp"`）。

#### Scenario: Test Run Set 觸發寫 audit
- **WHEN** Test Run Set 觸發 automation suite
- **THEN** audit `AUTOMATION_RUN` + `CREATE` 紀錄 SHALL：
  - `details.test_run_set_id` 必填
  - `details.trigger_source="test-run-set"`
  - `details.suite_name`、`details.workflow_id`、`details.branch` 必填

---

## ADDED Requirements

### Requirement: System MUST mark automation_script_id as a legacy column

`automation_runs.automation_script_id` FK SHALL 保留為 nullable，但本 change 之後的新 run **永遠** SHALL `automation_script_id IS NULL`。UI 對歷史 legacy row SHALL 加灰色「legacy single-script」chip。

#### Scenario: New run 永遠 IS NULL
- **WHEN** 任何 trigger 路徑（Test Run Set / webhook / schedule / MCP）寫入 `automation_runs`
- **THEN** `automation_script_id` SHALL 為 NULL

### Requirement: System MUST NOT expose any run trigger UI or API on Automation Hub

Automation Hub 對外契約 SHALL **僅**包含 read / sync / metadata CRUD；`POST /automation-scripts/{id}/runs` 與 `POST /automation-script-groups/{id}/runs` SHALL 回 404。執行入口 SHALL 完全位於 Test Run Set detail 頁。

#### Scenario: Hub 不再觸發 run
- **WHEN** user 在 Automation Hub 任何頁面想執行 script 或 suite
- **THEN** Hub SHALL NOT 提供「Run」CTA
- **AND** UI SHALL 引導使用者到 Test Run Set 觸發

#### Scenario: 對已移除的 trigger 端點直接打
- **WHEN** client 對 `POST /automation-scripts/{id}/runs` 或 `POST /automation-script-groups/{id}/runs` 送 request
- **THEN** API SHALL 回 404 / 405
- **AND** response detail SHALL 含 `{"code": "RUN_TRIGGER_REMOVED", "message": "Use POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation instead."}`

### Requirement: System MUST mark test_run_set_id as the canonical trigger source

`automation_runs.test_run_set_id` SHALL 為本 change 後 run 的**主要識別欄位**。Test Run Set 觸發的 run SHALL `test_run_set_id` 必填；legacy hub 觸發的 run `test_run_set_id` 為 NULL。

#### Scenario: 列表 query 篩選 Test Run Set 觸發
- **WHEN** 查詢 `?test_run_set_id=42`
- **THEN** API SHALL 回該 set 觸發的所有 run

### Requirement: System MUST reject any future attempt to re-introduce Hub trigger

後續程式碼 SHALL NOT 再於 `app/api/automation_scripts.py` / `app/api/automation_script_groups.py` 加 `trigger_*` 公開 endpoint，或在 `AutomationRunService` 加 `trigger_script` / `trigger_group` 公開方法。Code review 與本 spec SHALL 拒絕此類變更。

#### Scenario: Defensive code review guard
- **WHEN** 開發者嘗試新增 `trigger_automation_script_run` / `trigger_automation_script_group_run` 公開 endpoint，或新增 `trigger_script` / `trigger_group` 公開方法
- **THEN** code review SHALL 拒絕（依本 spec）
