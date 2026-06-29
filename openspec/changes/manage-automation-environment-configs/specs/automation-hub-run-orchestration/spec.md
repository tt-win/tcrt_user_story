## ADDED Requirements

### Requirement: Run record MUST capture the selected automation environment by name only

`automation_runs` SHALL 新增 `environment VARCHAR(60) nullable` 欄位，記錄該 run 使用的環境**名稱**（如 `sit`）。此欄位 SHALL **只存環境名、不存任何參數值**；參數值（含 secret）SHALL NOT 寫入 `automation_runs`。

- 帶環境觸發的 run：`environment` 為選定環境名。
- 未帶環境 / 無環境宣告的 run：`environment` 為 NULL（與既有 row 相容）。
- `inputs_json` 內若含 `TCRT_ENV_BUNDLE`，SHALL 在持久化前以遮罩值（如 `"***"`）取代真值，確保 run 紀錄不落地 secret。

#### Scenario: Environment name recorded, values not
- **WHEN** 以環境 `sit` 觸發一個 suite run
- **THEN** 對應 `automation_runs` row 的 `environment` SHALL 為 `"sit"`
- **AND** `inputs_json` SHALL NOT 含任何環境參數的真值（`TCRT_ENV_BUNDLE` 已遮罩）

#### Scenario: Legacy and no-environment runs
- **WHEN** 觸發未帶環境的 run，或查詢本變更前的既有 row
- **THEN** `environment` SHALL 為 NULL，run 行為與顯示不受影響

### Requirement: Run list and detail MUST surface the environment

`GET /api/teams/{team_id}/automation-runs` SHALL 新增篩選 `?environment=<name>`；run 列表與詳情 SHALL 顯示環境（有值時以 chip 呈現，如「Env: sit」；NULL 時不顯示）。

#### Scenario: Filter runs by environment
- **WHEN** 查詢 `?environment=prod`
- **THEN** API SHALL 只回 `environment="prod"` 的 run

#### Scenario: Environment chip in run history
- **WHEN** run 列表顯示一筆 `environment="sit"` 的 run
- **THEN** 該列 SHALL 顯示「Env: sit」chip
- **WHEN** run `environment` 為 NULL
- **THEN** 該列 SHALL 不顯示環境 chip

### Requirement: Audit MUST record the run environment name

run 觸發的 audit（`ResourceType.AUTOMATION_RUN`）details SHALL 新增 `environment`（環境名，nullable）。SHALL **不**記錄任何環境參數值。

#### Scenario: Trigger audit includes environment name
- **WHEN** Test Run Set 以環境 `sit` 觸發 automation suite
- **THEN** audit `AUTOMATION_RUN` + `CREATE` 的 details SHALL 含 `environment="sit"`，且不含任何參數真值
