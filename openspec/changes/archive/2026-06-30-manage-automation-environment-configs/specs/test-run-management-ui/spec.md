## ADDED Requirements

### Requirement: Test Run Set MUST persist a default automation environment

`test_run_sets` SHALL 新增 `default_automation_environment VARCHAR(60) nullable`，記住該 Set 觸發 automation 時的預設環境名（須對應該 team 環境目錄中存在的環境）。NULL 表示無預設，可透過既有編輯路徑設定。

#### Scenario: Set remembers default environment
- **WHEN** 使用者把某 Test Run Set 的預設環境設為 `sit`
- **THEN** `test_run_sets.default_automation_environment` SHALL 為 `"sit"`，下次觸發 UI 預選 `sit`

#### Scenario: Backward compatible nullable
- **WHEN** 既有 Set 未設預設環境
- **THEN** 欄位 SHALL 為 NULL，觸發行為與本變更前一致

### Requirement: Run-automation trigger MUST resolve environment and validate per-script declared coverage

`POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation` payload SHALL 新增**可選** `environment`（環境名）。端點路徑與其餘 payload 形狀 SHALL 不變。

觸發流程 SHALL：

1. 計算該 suite 內各 script 的 declared required 變數聯集（來自 `automation_scripts.declared_vars_json`）。
2. 若聯集為空 → **不**要求環境、不注入，照現況觸發（向後相容）。
3. 否則解析環境，順序為：`request.environment` → `test_run_sets.default_automation_environment` → team 環境目錄的 `is_default` 環境。
   - 三層皆無 → 回 422 `ENVIRONMENT_REQUIRED`，訊息列出可選環境。
4. 對解析出的環境 E，逐 script 計算有效值（環境共用 ⊕ per-script 覆寫）；若任一 script 的 declared required 變數在 E 為 unset → 回 422 `ENVIRONMENT_INCOMPLETE`，列出 (script, 缺哪些變數) 並導引至 Script view 變數設定。
5. 通過後，service SHALL 組 namespaced `TCRT_ENV_BUNDLE` 注入觸發（見 `automation-hub-provider-framework`），並記 `automation_runs.environment`（只記名）。

#### Scenario: Request environment overrides set default
- **WHEN** Set 預設 `sit`，觸發 payload 帶 `environment="prod"`，suite scripts 在 `prod` 必填齊備
- **THEN** run SHALL 以 `prod` 有效值觸發，`automation_runs.environment="prod"`

#### Scenario: Falls back to set default then catalog default
- **WHEN** payload 未帶 `environment`、Set 預設為 NULL、team 環境目錄 `sit` 為 default
- **THEN** run SHALL 以 `sit` 觸發

#### Scenario: Block when environment required but unresolved
- **WHEN** suite scripts 有 declared required 變數，但三層解析都得不到環境
- **THEN** API SHALL 回 422 `ENVIRONMENT_REQUIRED`，不觸發

#### Scenario: Block when required vars missing for a script
- **WHEN** 解析出 `sit`，但 `tests/test_login.py` 的 required `API_TOKEN` 在 `sit` 既無共用值也無覆寫值
- **THEN** API SHALL 回 422 `ENVIRONMENT_INCOMPLETE`，detail 列 `{"tests/test_login.py": ["API_TOKEN"]}` 並導引變數設定

#### Scenario: Scripts without declared vars keep current behavior
- **WHEN** suite 內所有 script 都未宣告變數
- **THEN** 觸發 SHALL 不要求環境、不注入，行為與本變更前一致

### Requirement: Test Run Set trigger UI MUST present an environment selector when relevant

Test Run Set detail 的 automation 觸發 UI SHALL 在「該 Set 對應 suite 內有 script 宣告變數」且「team 已定義環境」時顯示環境選單：

- 預選依解析順序（set 預設 → 目錄 default）。
- 各環境選項 SHALL 顯示覆蓋狀態；對該 suite 有缺必填變數者標示不可直接觸發並導引補齊。
- 無宣告變數 / team 無環境時 SHALL **不**顯示選單（畫面與本變更前一致）。

#### Scenario: Selector shown only when relevant
- **WHEN** suite 內 script 宣告了變數且 team 有環境目錄
- **THEN** 觸發 UI SHALL 顯示環境選單，預選依解析順序
- **WHEN** suite 內無 script 宣告變數，或 team 未定義任何環境
- **THEN** 觸發 UI SHALL 不顯示環境選單

#### Scenario: Incomplete environment surfaced
- **WHEN** `prod` 對該 suite 有 script 缺必填變數
- **THEN** 選單中 `prod` SHALL 標「缺必填變數」並導引先到 Script view 補齊
