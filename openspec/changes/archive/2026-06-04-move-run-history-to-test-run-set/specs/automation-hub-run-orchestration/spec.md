# Delta Spec — automation-hub-run-orchestration

> 對 `openspec/specs/automation-hub-run-orchestration/spec.md` 的 delta，記錄「Automation Hub 全面退出 run history 領域」對既有 requirement 的影響。

> 註：原主 spec 已被 §1-§6 實作手動改寫；本 delta 保留以 archive 流程可同步 ADDED 為主。`REMOVED Requirements` 段刻意省略 — 對應的舊 requirement 已在主 spec 直接刪除。

## MODIFIED Requirements

### Requirement: System MUST store run metadata as external references

`automation_runs` 表 SHALL 為每筆 run 紀錄帶 `test_run_set_id` 欄位（nullable FK → `test_run_sets.id`）。`test_run_set_id` 為「此 set 是否觸發了該 run」的唯一識別 — Test Run Set 觸發的 run `test_run_set_id` 必填，webhook 觸發的 run `test_run_set_id` 為 NULL（不透過 set 觸發）。

#### Scenario: Test Run Set 觸發的 run 必填 test_run_set_id 與 script_group_id
- **WHEN** Test Run Set 透過 `POST .../test-run-sets/{id}/run-automation` 觸發 N 個 automation suite
- **THEN** 每個寫入的 `automation_runs` row SHALL：
  - `test_run_set_id` 為觸發的 set id（必填）
  - `script_group_id` 為該 suite id（必填）
  - `automation_script_id` 為 NULL

#### Scenario: Webhook / 手動觸發的 run
- **WHEN** webhook inbound（`POST /api/v1/webhooks/ci/{token}/trigger`）或非 Test Run Set 來源觸發 suite run
- **THEN** 該 run SHALL `test_run_set_id` 為 NULL，且 SHALL NOT 出現在任何 set-scope list API 中

---

## ADDED Requirements

### Requirement: System MUST expose run history only through Test Run Set endpoints

Automation Hub 對外契約 SHALL **僅**包含 read / sync / metadata CRUD，**不**包含 run history list / detail / cancel / reconcile。原本的 `GET /api/teams/{team_id}/automation-runs` 等 6 個端點 SHALL 從 API 表面完全移除。

對應的新端點 SHALL 收斂在 Test Run Set 路徑下：

- `GET /api/teams/{team_id}/test-run-sets/{set_id}/runs` — 列出此 set 觸發的 runs
- `GET /api/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}` — 詳情（run 必須 `test_run_set_id == set_id`，否則 404 `AUTOMATION_RUN_NOT_IN_SET`）
- `POST .../runs/{run_id}/cancel` — 取消
- `POST .../runs/{run_id}/reconcile` — 對齊

#### Scenario: 對已移除的 run 端點直接打
- **WHEN** client 對 `GET/POST /api/teams/{team_id}/automation-runs[/...]` 任何變體送 request
- **THEN** API SHALL 回 404 / 405
- **AND** response detail SHALL 含 `{"code": "RUN_HISTORY_REMOVED", "message": "Use GET /api/teams/{team_id}/test-run-sets/{set_id}/runs instead."}`

#### Scenario: Test Run Set run list 強制 set-scope
- **WHEN** user 查詢 `GET /api/teams/{team_id}/test-run-sets/{set_id}/runs`
- **THEN** 結果 SHALL 僅含 `test_run_set_id == {set_id}` 的 runs（不洩漏其他 set 或 webhook-only 的 runs）

#### Scenario: Cross-set run 詳情拒絕
- **WHEN** 對 `GET .../test-run-sets/{set_id}/runs/{run_id}` 但該 run 不屬於 `{set_id}`
- **THEN** API SHALL 回 404 `{"code": "AUTOMATION_RUN_NOT_IN_SET"}`，且不洩漏該 run 的存在

### Requirement: MCP MUST scope automation-runs to a Test Run Set

MCP 端點 `GET /api/mcp/teams/{team_id}/test-run-sets/{set_id}/automation-runs` SHALL 取代原本的 `GET /api/mcp/teams/{team_id}/automation-runs`。新端點 SHALL 強制帶 `set_id` 路徑參數，filter 僅保留 `status` / `branch`。

#### Scenario: 對未帶 set id 的舊 MCP 端點
- **WHEN** client 對 `GET /api/mcp/teams/{team_id}/automation-runs` 送 request
- **THEN** API SHALL 回 404

#### Scenario: 未知 set id
- **WHEN** `set_id` 在指定 team 不存在
- **THEN** API SHALL 回 404 `{"code": "TEST_RUN_SET_NOT_FOUND"}`

### Requirement: System MUST reject any future attempt to re-introduce Hub run history

為防止誤植，後續程式碼 SHALL NOT 在 `app/api/` 加 `automation-runs` 前綴的公開 endpoint，或在 MCP 端點加 team-scope 的 automation-runs。Code review 與本 spec SHALL 拒絕此類變更。

#### Scenario: Defensive code review guard
- **WHEN** 開發者嘗試新增 `GET /api/teams/{team_id}/automation-runs` 或類似的 Hub-scope run 端點
- **THEN** code review SHALL 拒絕（依本 spec）
