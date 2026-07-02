## Purpose

規範 TCRT Automation Hub **集中管理自動化環境與其參數值**的契約。模型分三層：

1. **環境目錄（team 範圍、使用者自訂）**：使用者在 Automation Hub 定義自己需要幾個環境（如 `dev` / `sit` / `prod`）。
2. **環境共用參數（per-environment shared）**：每個環境帶一組共用參數值（如 `BASE_URL`、`DB_HOST`），跨該 team 的所有 script 共用。
3. **per-script 覆寫值（per-script override）**：在 Scripts 分頁的 **Script view** 以「變數設定 modal」對某支 script、某環境**覆寫**成自己的值。

某支 script 在某環境的**有效值** = 環境共用參數 ⊕ 該 script 覆寫（script 覆寫優先）。

「script 需要哪些變數」的**宣告**為 per-script、由 `init` / `pomify` 寫進源碼、由 smart-scan 逐檔發現（見 `automation-hub-script-management`）。值一律存 TCRT（不進 repo），secret 加密；執行時由 TCRT 注入 CI（注入見 `automation-hub-provider-framework`，選擇見 `test-run-management-ui`，run 紀錄見 `automation-hub-run-orchestration`）。

## ADDED Requirements

### Requirement: System MUST let users define a per-team environment catalog in Automation Hub

資料表 `automation_environments` SHALL 提供 per-team、**使用者自訂**的環境目錄：

- `id` PK
- `team_id` FK → `teams.id` ON DELETE CASCADE, NOT NULL, indexed
- `name` VARCHAR(60) NOT NULL（穩定鍵，SHALL 符合 `^[a-z0-9][a-z0-9-]*$`）
- `label` VARCHAR(100) nullable（顯示名）
- `description` TEXT nullable
- `is_default` BOOLEAN default false
- `created_by`, `updated_by`, timestamps
- UniqueConstraint `(team_id, name)`、Index `(team_id, is_default)`

環境目錄 SHALL 由使用者在 Automation Hub **Settings** tab 自訂（要幾個、叫什麼）；team 內至多一個 `is_default=true`。`database_init.py` 的「缺重要表」檢查 SHALL 涵蓋本表。

#### Scenario: User defines environments
- **WHEN** team admin 在 Automation Hub Settings 新增 `dev`、`sit`、`prod` 三個環境並把 `sit` 設為預設
- **THEN** `automation_environments` SHALL 出現三筆，`sit` 的 `is_default=true`，其餘 false

#### Scenario: Environment name uniqueness per team
- **WHEN** 同一 team 再建一個 `name="sit"`
- **THEN** UniqueConstraint SHALL 拒絕並回 409 `DUPLICATE_ENVIRONMENT`

#### Scenario: Single default per team
- **WHEN** team 已有預設環境，再把另一個設為預設
- **THEN** service SHALL 把舊預設改為 false，確保至多一個

### Requirement: System MUST store per-environment shared params and per-script override values

環境參數值 SHALL 分兩層儲存。**環境共用參數** SHALL 存於 `automation_environment_params`：

- `id` PK
- `environment_id` FK → `automation_environments.id` ON DELETE CASCADE, NOT NULL, indexed
- `key` VARCHAR(120) NOT NULL（`^[A-Za-z_][A-Za-z0-9_]*$`）
- `is_secret` BOOLEAN default false
- `value_plaintext` TEXT nullable（非 secret）
- `value_encrypted` TEXT nullable（secret，AES-256-GCM、nonce 內嵌）
- audit/timestamps、UniqueConstraint `(environment_id, key)`

**per-script 覆寫值** SHALL 存於 `automation_script_env_vars`：

- `id` PK
- `team_id` FK indexed
- `automation_script_id` FK → `automation_scripts.id` ON DELETE CASCADE, indexed（與既有 `automation_script_case_links` 一致：綁定 script 快取列）
- `script_ref_path` VARCHAR(500) NOT NULL（記錄當時 ref_path，供顯示 / audit；正常 re-sync 會更新既有 script 列（id 不變），覆寫值隨之保留）
- `environment_id` FK → `automation_environments.id` ON DELETE CASCADE, indexed
- `key` VARCHAR(120) NOT NULL（`^[A-Za-z_][A-Za-z0-9_]*$`）
- `is_secret` BOOLEAN default false
- `value_plaintext` / `value_encrypted`（同上）
- audit/timestamps、UniqueConstraint `(automation_script_id, environment_id, key)`

某 (script, environment, key) 的**有效值** SHALL 為：該 script 的覆寫值（若存在）否則該環境的共用參數值（若存在）否則「未設定」。

#### Scenario: Shared param applies to all scripts
- **WHEN** 環境 `sit` 設共用參數 `BASE_URL="https://sit..."`，且某 script 未覆寫 `BASE_URL`
- **THEN** 該 script 在 `sit` 的 `BASE_URL` 有效值 SHALL 為 `"https://sit..."`

#### Scenario: Per-script override wins
- **WHEN** 環境 `sit` 共用 `BASE_URL="https://sit..."`，但 `tests/test_b.py` 覆寫 `BASE_URL="https://b.sit..."`
- **THEN** `test_b.py` 在 `sit` 的 `BASE_URL` 有效值 SHALL 為 `"https://b.sit..."`；其他未覆寫的 script 仍用共用值

#### Scenario: Override preserved across normal re-sync
- **WHEN** script 仍存在於 repo，team 觸發 rescan（更新既有 script 列、id 不變）
- **THEN** 該 script 既有的 per-script 覆寫值 SHALL 完整保留
- **WHEN** 使用者顯式刪除該 script 快取列
- **THEN** 其覆寫值 SHALL 隨 FK CASCADE 一併移除（與 marker link 行為一致）

#### Scenario: Cascade on environment delete
- **WHEN** 刪除一個環境
- **THEN** 其共用參數與所有 script 對該環境的覆寫值 SHALL 一併 CASCADE 刪除

### Requirement: Secret values MUST be encrypted at rest and never returned in plaintext

`is_secret=true` 的值（環境共用或 script 覆寫）SHALL 透過既有 `provider_credential_service`（AES-256-GCM、金鑰 `AUTOMATION_PROVIDER_ENCRYPTION_KEY`）加密存 `value_encrypted`，`value_plaintext` 為 NULL。

API 回應 SHALL 永不含 secret 真值：secret 只回 `{is_set, fingerprint}`（末 4 碼）；非 secret 可回 plaintext。Bootstrap 啟動時若有任何 secret 值列但金鑰缺失：SHALL 比照既有 provider 規則阻擋啟動並印生成指引。

#### Scenario: Secret never returned
- **WHEN** admin 讀取環境或 script 變數設定
- **THEN** secret 參數 SHALL 只含 `{key, is_secret:true, is_set:true, fingerprint:"***wxyz"}`，不含真值

#### Scenario: Missing key blocks bootstrap
- **WHEN** 有 secret 值列但 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 缺失
- **THEN** bootstrap SHALL 拋錯並列出金鑰生成指令

### Requirement: API MUST manage environment catalog, shared params and per-script overrides

新增 team-scoped 端點（需 team 寫入權限）SHALL 提供：

- 環境目錄：`GET/POST /api/teams/{team_id}/automation-environments`、`GET/PUT/DELETE .../{env_id}`、`PUT .../{env_id}/default`
- 環境共用參數：`PUT/DELETE .../{env_id}/params/{key}`（`value`、`is_secret`）
- per-script 覆寫：`GET /api/teams/{team_id}/automation-scripts/{script_id}/env-vars`（回該 script 各環境的有效值 + 來源 shared/override + 覆蓋狀態）、`PUT/DELETE .../{script_id}/env-vars/{env_id}/{key}`
- 掃描變數建議：`GET .../automation-environments/declared-variables` 回傳該 team 各 script 由 `TCRT_VARS` 宣告的變數聚合（`name` / `secret` / `required` / `scripts[]`，distinct by name；任一 script 宣告為 secret/required 即為 true）
- YAML 匯入 / 匯出：環境共用參數可整批匯入 / 匯出（匯出時 secret 以 `"***"` 遮罩、不導出真值）

所有寫端點 SHALL 寫 audit（`ResourceType.AUTOMATION_ENVIRONMENT`），details 含 `environment_name`、`script_ref_path?`、`key`，**不**含 secret 真值。

新增環境共用參數的 UI SHALL **以 `declared-variables` 的掃描結果作為變數名稱建議清單供選擇**（挑選後依其宣告自動帶入 `is_secret`）；清單中沒有的名稱**仍允許自由輸入新增**。

#### Scenario: Read resolves effective values with source
- **WHEN** admin 呼叫 `GET .../automation-scripts/{id}/env-vars`
- **THEN** 每個 (declared var × environment) SHALL 回有效值、來源（`shared` / `override` / `unset`），secret 遮罩

#### Scenario: Add-variable suggests scanned declared variables
- **WHEN** admin 在某環境點「新增變數」，且該 team 的 script 已掃描出 `TCRT_VARS`（如 `BASE_URL`、`API_TOKEN`）
- **THEN** 變數名稱欄位 SHALL 列出這些掃描到的名稱供挑選（已在該環境設過的名稱排除）；挑 `API_TOKEN` SHALL 自動勾選 `is_secret`
- **WHEN** admin 輸入清單中沒有的名稱
- **THEN** SHALL 允許直接新增（自由輸入），不強制從清單選

#### Scenario: Export masks secrets
- **WHEN** admin 匯出某環境共用參數
- **THEN** secret 值 SHALL 為 `"***"`，非 secret 為真值；匯出內容不含任何 secret 真值

#### Scenario: Audit excludes secret values
- **WHEN** admin 更新一個 secret 值
- **THEN** audit `AUTOMATION_ENVIRONMENT` + `UPDATE` SHALL 含 `key`/`environment_name`，不含真值

### Requirement: Script view MUST provide a per-script variable-setting modal

Automation Hub **Scripts tab → Script view** SHALL 為每支 script 提供「設定變數 / Configure variables」入口，開啟 modal：

- 列出該 script 由 smart-scan 發現的 **declared variables**（見 `automation-hub-script-management`）。
- 欄為 team 的**環境目錄**（使用者自訂的那幾個環境）。
- 每格顯示有效值與來源：`shared`（來自環境共用）/ `override`（此 script 覆寫）/ `unset`；可在此設定 / 清除 **per-script 覆寫**。
- secret 欄位遮罩輸入、顯示 `is_set` + fingerprint、留空不覆寫；非 secret 顯示值。
- 標示哪些 declared `required` 變數在某環境尚未有有效值（缺 → 該環境該 script 不可觸發）。
- modal SHALL 明確標示「值存 TCRT、不進 git；script 只取用固定變數名稱」。

#### Scenario: Modal driven by declared vars × environment catalog
- **WHEN** `tests/test_login.py` 宣告 `BASE_URL`(non-secret)、`API_TOKEN`(secret, required)，team 有 `dev/sit/prod` 三環境
- **THEN** modal SHALL 顯示 2 列（變數）× 3 欄（環境），`API_TOKEN` 遮罩且標 required

#### Scenario: Cell shows shared vs override source
- **WHEN** `sit` 共用了 `BASE_URL`，此 script 未覆寫
- **THEN** `BASE_URL × sit` 格 SHALL 標示來源 `shared` 與其值；使用者按「覆寫」可改為此 script 專屬值

#### Scenario: Secret field shows is_set not value
- **WHEN** 開啟已設 `API_TOKEN` 的格
- **THEN** SHALL 顯示 `已設定 ••••wxyz`、不回填真值；留空儲存不覆寫既有值

### Requirement: System MUST validate declared-vs-effective coverage per script per environment

TCRT SHALL 對「script 的 declared variables」與「該環境的有效值（shared ⊕ override）」做對賬，產出每 (script, environment) 的覆蓋狀態：

- `missing_required`：declared `required=true` 但有效值為 unset → 管理 UI 標紅；**觸發時擋下**（見 `test-run-management-ui`）。
- `unused_value`：設了值（shared 或 override）但 script 未宣告 → 警示（不擋）。
- `secret_flag_mismatch`：declared `secret` 與儲存型態不一致 → 警示。

覆蓋狀態 SHALL 供 Script view modal、Coverage tab 與觸發前驗證共用。

#### Scenario: Missing required blocks
- **WHEN** script 宣告 `API_TOKEN required=true`，但 `sit` 既無共用值也無覆寫值
- **THEN** (script, `sit`) 覆蓋狀態 SHALL 含 `missing_required:["API_TOKEN"]`

#### Scenario: Script with no declared vars
- **WHEN** 某 script 未宣告任何變數
- **THEN** 其覆蓋狀態 SHALL 無 `missing_required`，且觸發不因環境而受限（向後相容）
