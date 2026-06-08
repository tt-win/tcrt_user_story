## MODIFIED Requirements

### Requirement: Provider registry MUST support type-based lookup and slot-aware scope dispatch
`app/services/automation/provider_registry.py` SHALL 維護 `{provider_type: provider_class}` 對照表，類型格式為 `<slot>:<vendor>`（如 `storage:github`、`ci:jenkins`、`result:allure`）。

`get_active_provider_record(team_id, slot, session)` SHALL 依 slot 分流查詢來源：

1. `slot == AutomationProviderSlot.STORAGE` → 從 `team_automation_providers` 查該 `team_id` 的 active provider
2. `slot in (AutomationProviderSlot.CI, AutomationProviderSlot.RESULT)` → 從 `system_automation_providers` 查 org-level active provider（`team_id` 參數忽略）
3. 解密 credentials
4. 實例化對應 provider class，注入 config + credentials
5. 回傳實例（可選擇 cache 一段時間）

簽名保持 `(team_id, slot, session)` 不變以維持 9 個既有呼叫端零改動；helper `is_system_scoped_slot(slot) -> bool` SHALL 暴露給其他需區分 scope 的程式碼（如 audit logging）。

#### Scenario: Unknown provider_type rejected at config time
- **WHEN** admin 嘗試建立 `provider_type=storage:unknown` 的 config
- **THEN** API SHALL 回 400，錯誤訊息 SHALL 列出可用的 provider types

#### Scenario: Team without storage provider configured
- **WHEN** team 未配置 storage provider 但前端嘗試 list scripts
- **THEN** API SHALL 回 412 `PROVIDER_NOT_CONFIGURED`，UI SHALL 顯示引導至 settings 頁

#### Scenario: Org without CI provider configured
- **WHEN** team 觸發 run、但 org-level CI provider 未設定
- **THEN** API SHALL 回 412 `PROVIDER_NOT_CONFIGURED`，錯誤訊息 SHALL 提示「請 Super Admin 至『同步組織架構』設定 CI provider」

#### Scenario: Slot-scope dispatch is transparent to caller
- **WHEN** `run_service` 呼叫 `get_active_provider_record(team_id=5, slot=CI, session)` 與 `get_active_provider_record(team_id=7, slot=CI, session)`
- **THEN** 兩次呼叫 SHALL 解析到**同一份** org-level CI provider，`team_id` 參數被內部忽略

### Requirement: System MUST store per-team storage provider configuration only
資料表 `team_automation_providers` SHALL 包含：

- `id` PK
- `team_id` FK NOT NULL, indexed
- `provider_slot` enum(`STORAGE`/`CI`/`RESULT`) NOT NULL — **但 CHECK constraint `ck_team_provider_storage_only` SHALL 限制 `provider_slot = 'storage'`**
- `provider_type` VARCHAR(60) NOT NULL（如 `storage:github`）
- `name` VARCHAR(100) NOT NULL
- `config_json` TEXT NOT NULL（plaintext config，含 owner / repo 等）
- `credentials_encrypted` TEXT nullable（AES-256-GCM；含 PAT / SSH key；nonce 內嵌）
- `is_active` BOOLEAN default true
- `last_health_check_at` DATETIME nullable
- `last_health_status` VARCHAR(40) nullable
- `created_by`, `updated_by`, timestamps
- UniqueConstraint `(team_id, provider_slot, name)`
- Index `(team_id, provider_slot, is_active)`

#### Scenario: Inserting ci / result row rejected at DB level
- **WHEN** code 嘗試 `INSERT INTO team_automation_providers (..., provider_slot = 'ci', ...)`
- **THEN** DB SHALL 違反 CHECK constraint 並拋 `IntegrityError`，service 層攔截後回 400 `WRONG_PROVIDER_SCOPE`

#### Scenario: One active storage provider per team (recommended, not enforced)
- **WHEN** team 有兩筆 `provider_slot=STORAGE, is_active=true` 的 provider
- **THEN** 系統 SHALL 允許（可能用於不同 repo），但 `get_active_provider_record(team_id, STORAGE)` SHALL 取最新 `updated_at` 的；admin UI SHALL 警示「建議只保留一個 active storage provider」

## ADDED Requirements

### Requirement: System MUST store org-level CI and Result provider configuration
資料表 `system_automation_providers` SHALL 包含與 `team_automation_providers` **相同的欄位集合，但無 `team_id`**：

- `id` PK
- `provider_slot` enum(`CI`/`RESULT`) NOT NULL — **CHECK constraint `ck_system_provider_ci_or_result_only` SHALL 限制 `provider_slot IN ('ci', 'result')`**
- `provider_type` VARCHAR(60) NOT NULL（如 `ci:jenkins`、`result:allure`）
- `name` VARCHAR(100) NOT NULL
- `config_json` TEXT NOT NULL
- `credentials_encrypted` TEXT nullable
- `is_active` BOOLEAN default true
- `last_health_check_at` DATETIME nullable
- `last_health_status` VARCHAR(40) nullable
- `created_by`, `updated_by`, timestamps
- UniqueConstraint `(provider_slot, name)`
- Index `(provider_slot, is_active)`

ORM class `SystemAutomationProvider` SHALL 共用一份欄位 mixin 與 `TeamAutomationProvider` 以避免漂移。

Bootstrap 啟動時「主資料庫缺重要表」檢查 SHALL 包含 `system_automation_providers`。

#### Scenario: Inserting storage row into system table rejected
- **WHEN** code 嘗試 `INSERT INTO system_automation_providers (..., provider_slot = 'storage', ...)`
- **THEN** DB SHALL 違反 CHECK constraint 並拋 `IntegrityError`

#### Scenario: Org-level uniqueness independent of team
- **WHEN** Super Admin 嘗試新增第二筆 `provider_slot=CI, name='production-jenkins'`
- **THEN** UniqueConstraint SHALL 拒絕並回 409 `DUPLICATE_NAME`

### Requirement: Per-team provider API MUST reject ci and result slot at app layer
`POST /api/teams/{team_id}/automation-providers` 與 `PUT /api/teams/{team_id}/automation-providers/{id}` SHALL：

1. 驗證 payload 的 `provider_slot` 與 `provider_type` 的 slot prefix 都是 `storage`
2. 嘗試指定 `ci` / `result` slot SHALL 回 400 `WRONG_PROVIDER_SCOPE`，錯誤訊息 SHALL 指引至「同步組織架構」modal

#### Scenario: Team admin posts ci provider rejected
- **WHEN** team admin 對 `/api/teams/5/automation-providers` POST `{"provider_slot": "ci", "provider_type": "ci:jenkins", ...}`
- **THEN** API SHALL 回 `400 WRONG_PROVIDER_SCOPE`，訊息 SHALL 包含「請 Super Admin 至『同步組織架構』設定」

#### Scenario: Team admin posts storage provider accepted
- **WHEN** team admin 對 `/api/teams/5/automation-providers` POST `{"provider_slot": "storage", "provider_type": "storage:github", ...}`
- **THEN** API SHALL 接受並建立 row（既有行為不變）

### Requirement: Org-level provider API MUST require Super Admin
新增 router `/api/system/automation-providers` SHALL 提供與 team-scoped router 對等的端點集合（list / get / create / update / delete / test-connection / test-config / discover-runners / types）。全部端點 SHALL `Depends(require_super_admin)`。

非 Super Admin 呼叫 SHALL 回 `403 INSUFFICIENT_PERMISSION`。

#### Scenario: Super Admin creates Jenkins org provider
- **WHEN** Super Admin 對 `/api/system/automation-providers` POST `{"provider_slot": "ci", "provider_type": "ci:jenkins", "name": "company-jenkins", ...}`
- **THEN** API SHALL 接受並建立 row

#### Scenario: Team admin attempts to call system endpoint
- **WHEN** 非 Super Admin user 對 `/api/system/automation-providers` GET
- **THEN** API SHALL 回 `403 INSUFFICIENT_PERMISSION`

#### Scenario: System endpoint accepts only ci or result slot
- **WHEN** Super Admin 對 `/api/system/automation-providers` POST `{"provider_slot": "storage", ...}`
- **THEN** API SHALL 回 400 `WRONG_PROVIDER_SCOPE`，訊息 SHALL 指引「Storage provider 請至 team 設定頁」

### Requirement: Org-level provider UI MUST live in team management's org-sync modal
`/team-management` 頁面既有的「同步組織架構」modal SHALL 新增一個 tab `tab-org-automation-infra`，顯示 Jenkins / Allure provider 管理表格與 Add Provider modal。整個 tab SHALL 沿用 modal 既有的 Super Admin 守門。

`/automation-provider-settings` 頁面 SHALL：

1. 頁面標題改為「Git 來源設定」(i18n key `gitSourceSettings.title`)
2. `CANONICAL_TYPES` 在 JS 端僅保留 `storage:github`
3. 編輯既有非 canonical type（如 `storage:local_git`）的 row 仍允許，但 slot dropdown 不顯示 ci/result 選項
4. UI 不再暴露 Jenkins / Allure 的 Add Provider 路徑

#### Scenario: Git Source Settings page only lists storage providers
- **WHEN** team admin 開啟 `/automation-provider-settings`
- **THEN** 頁面標題 SHALL 顯示「Git 來源設定」；Provider table SHALL 只列 `provider_slot = storage` 的 row

#### Scenario: Org Automation Infra tab visible to Super Admin only
- **WHEN** Super Admin 在 `/team-management` 開啟「同步組織架構」modal
- **THEN** modal SHALL 包含 `tab-org-automation-infra` tab，展開後 SHALL 看到既有的 org-level CI / Result provider 列表 + Add Provider 按鈕
- **WHEN** 非 Super Admin user 進入同一頁
- **THEN** 整個「同步組織架構」按鈕 SHALL 不可見（既有行為）

### Requirement: Provider audit log MUST identify scope
provider CRUD 的 audit log SHALL 透過獨立的 `ResourceType.SYSTEM_AUTOMATION_PROVIDER` 與既有 `ResourceType.AUTOMATION_PROVIDER` 區分；team-scoped 紀錄保留 `team_id`，org-scoped 紀錄 `team_id` 欄位為 NULL。

#### Scenario: Org provider create logs system-scope resource type
- **WHEN** Super Admin 建立一個 org-level Jenkins provider
- **THEN** audit log SHALL 寫入 `resource_type = SYSTEM_AUTOMATION_PROVIDER`、`team_id = NULL`、`actor = super_admin_user_id`
