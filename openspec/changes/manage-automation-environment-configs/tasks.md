## 1. 資料模型 + migration

- [x] 1.1 `app/models/database_models.py` 新增 `AutomationEnvironment`（`team_id` FK CASCADE、`name`、`label`、`description`、`is_default`、audit/ts、`UNIQUE(team_id,name)`、`INDEX(team_id,is_default)`）
- [x] 1.2 新增 `AutomationEnvironmentParam`（環境共用參數：`environment_id` FK CASCADE、`key`、`is_secret`、`value_plaintext`、`value_encrypted`、`UNIQUE(environment_id,key)`）
- [x] 1.3 新增 `AutomationScriptEnvVar`（per-script 覆寫：`team_id`、`automation_script_id` FK CASCADE、`script_ref_path`、`environment_id` FK CASCADE、`key`、`is_secret`、`value_*`、`UNIQUE(automation_script_id,environment_id,key)`、`INDEX(team_id,script_ref_path)`）
- [x] 1.4 `AutomationScript` 新增 `declared_vars_json`；`AutomationRun` 新增 `environment`；`TestRunSet` 新增 `default_automation_environment`
- [x] 1.5 新增 Alembic migration（chained 到 head `d7f2a9c4e1b8` → `a7c1e9b3d5f2`）：create 三新表 + add 三新欄位；`downgrade` drop（全附加式、非破壞，已驗證 up/down）
- [x] 1.6 `database_init.py`：create_all 涵蓋三新表（model 已定義），並加入 bootstrap「缺重要表」檢查（MAIN_REQUIRED_TABLES）

## 2. 加密 + bootstrap 守門

- [x] 2.1 環境共用參數與 per-script 覆寫的 secret 值重用 `provider_credential_service`（新增 `encrypt_value`/`decrypt_value`/`value_fingerprint`/`encrypted_value_fingerprint`，AES-256-GCM、`AUTOMATION_PROVIDER_ENCRYPTION_KEY`）
- [x] 2.2 `database_init.verify_automation_provider_encryption_key` 擴充：`automation_environment_params` / `automation_script_env_vars` 有 `value_encrypted` 列時也要求金鑰，缺則阻擋啟動並印生成指引
- [x] 2.3 序列化層對 secret 一律輸出 `{is_set, fingerprint}`、非 secret 輸出 plaintext；確保無路徑回傳 secret 真值（`EnvParamResponse` / `ScriptEnvVarCell` 遮罩、export 以 `***`）

## 3. smart-scan：發現 per-script 變數宣告

- [x] 3.1 `marker_parse._extract_declared_vars`：module-level `TCRT_VARS` 的 AST 解析（字串 / dict 兩形式 → `{name, secret, required, description}`）
- [x] 3.2 非字面量 / 不合法 name fail-open，記入 `var_warnings[]`（`non_literal_var` / `invalid_var_name` / `parse_error`）；`script_to_dict` 增 `declared_vars` + `var_warnings`
- [x] 3.3 `_sync_one_repo` 寫 `automation_scripts.declared_vars_json`（create + 每次 sync recompute、含 backfill）

## 4. 環境管理 service + API

- [x] 4.1 `AutomationEnvironmentService`：環境目錄 CRUD、設 team 預設（確保至多一個 default）、環境共用參數 set/clear、per-script 覆寫 set/clear、有效值解析（共用 ⊕ 覆寫）、覆蓋對賬、YAML 匯入匯出（遮罩 secret）
- [x] 4.2 router `app/api/automation_environments.py`：`/automation-environments`（list/create/get/put/delete、`/{env_id}/default`、`/{env_id}/params/{key}`）、`/automation-scripts/{script_id}/env-vars`（read 有效值+來源、`/{env_id}/{key}` put/delete）、YAML import/export
- [x] 4.3 `app/api/__init__.py` 註冊 router（environments + script env-vars 兩個）
- [x] 4.4 新增 `ResourceType.AUTOMATION_ENVIRONMENT`；所有寫端點寫 audit（含 environment_name / script_id / key，**不**含 secret 值）

## 5. 觸發：環境解析 + 注入

- [x] 5.1 `app/api/test_run_sets.py` `run-automation` payload 新增可選 `environment`（端點路徑與其餘 payload 不變）；新增 422 `ENVIRONMENT_REQUIRED` / `ENVIRONMENT_INCOMPLETE` 對映
- [x] 5.2 `TestRunSetAutomationService.trigger_automation_suites` 透傳 `environment`（request→set.default）並於觸發前逐 suite 預驗證（fail-fast）
- [x] 5.3 `trigger_group_run.resolve_env_bundle`：算 declared required 聯集 → 為空則 `(None,None)`；否則解析（指定名 → 目錄 default）
- [x] 5.4 逐 script 算有效值（共用 ⊕ 覆寫、解密 secret），組 namespaced `TCRT_ENV_BUNDLE`（`{ref_path:{key:value}}`）併入 `run_inputs`
- [x] 5.5 驗證：未解析出環境 → `AutomationEnvironmentRequiredError`(422)；required 變數缺值 → `AutomationEnvironmentIncompleteError`(422，列 script×缺項)；未宣告變數走現況
- [x] 5.6 寫 `automation_runs.environment`（只記名）；`inputs_json` 持久化前把 `TCRT_ENV_BUNDLE` 遮罩為 `"***"`；audit details 加 `environment`

## 6. CI provider：bundle 注入 + 模板

- [x] 6.1 `providers/jenkins_ci.py` `trigger_run`：`TCRT_ENV_BUNDLE`（及既有 `GIT_TOKEN`）改以 form-encoded **body**（`data=`）傳 `buildWithParameters`，移出 query string；非敏感 inputs 仍走 query（行為不變）
- [x] 6.2 `templates/jenkins-suite-config.xml.j2` 新增 `TCRT_ENV_BUNDLE` `PasswordParameterDefinition`；新增 `Env config` stage 把非空值寫 `repo/tcrt-env.json`（`set +x` 不 echo、不 export、空值略過）
- [~] 6.3 GHA：**N/A** — 此 codebase 未 ship GitHub Actions CI provider（`providers/` 僅 `github_storage` + `jenkins_ci`）；provider spec 的 GHA 段保留為協定前瞻契約
- [x] 6.4 既有 `update_suite_job` 每次觸發都跑（self-heal），含 bundle 參數的新模板因此自動套用到既有 job；未帶環境時 `TCRT_ENV_BUNDLE` 空 → stage 略過，行為不變
- [x] 6.5 單一 `TCRT_ENV_BUNDLE` 參數，模板靜態：各 script 宣告變數數量變動時 job 模板不需重生（已驗證 55 tests 綠）

## 7. 序列化 + UI

- [x] 7.1 `TestRunSet` 序列化（Base/Update/Detail/Response）增 `default_automation_environment`（create/update/detail 已 thread，`""` 清除）
- [x] 7.2 Automation Hub **Settings**：`environments/settings.js` + automation_hub.html 環境管理卡 + 6 modals（CRUD、共用參數 secret 遮罩、設預設、YAML 匯入匯出、「不進 git」提示）
- [x] 7.3 Automation Hub **Scripts tab → Script view**：`environments/script-vars.js` + `renderScriptItem` 「設定變數(N)」入口 + declared vars × 環境 matrix modal（shared/override/unset、覆寫、缺必填）
- [x] 7.4 Test Run Set detail：環境 `<select>` + 預選（set default→目錄 default）+ payload `environment` + 422 `ENVIRONMENT_REQUIRED`/`INCOMPLETE` 處理 + set 表單存 `default_automation_environment`
- [x] 7.5（後端）`AutomationRunResponse` + 兩個 `automation_run_to_dict` + `run_service.list_runs` 增 `environment`；run-list route 加 `?environment=`（chip 由前端 agent）
- [x] 7.6 新增環境共用參數時帶入掃描變數建議：`EnvironmentService.list_declared_variables` + `GET .../automation-environments/declared-variables`；Settings 新增變數欄位用 datalist 帶 `TCRT_VARS` 掃描清單（排除已設、挑選自動帶 is_secret + 提示），清單外仍可自由輸入；`declaredVarHint` i18n 三語

## 8. i18n

- [x] 8.1 `automationHub.environments.*`（92 keys）+ `testRun.sets.form/detail.*` env keys，en-US / zh-TW / zh-CN 三語 key set 一致；用 `t()` + `data-i18n` + `retranslate`

## 9. 對外 skill 同步（同步義務，缺則不得 archive）

- [x] 9.1 `tools/skills/tcrt-automation-pomify/SKILL.md`：新增 Step 7「Normalize environment config」+ 自驗 checklist + safety rule（步驟重編號）
- [x] 9.2 `tools/skills/tcrt-automation-pomify/references/environment-config.md`：`TCRT_VARS` 文法、shared/override 兩層、`TCRT_ENV_BUNDLE`→`tcrt-env.json`（依 `ref_path` namespace）、值存 TCRT 不進 repo
- [x] 9.3 `templates/python/{tcrt_vars_declaration,settings_loader_conftest,tcrt_env_helper}.py` + `templates/config/env.yaml.example`（已用真實 parser round-trip 驗證 TCRT_VARS 範本）
- [x] 9.4 `tools/skills/tcrt-automation-init/` 對應範本 + SKILL Step 6 + references §7 同步

## 10. 端到端 workflow 文件同步（同步義務）

- [x] 10.1 `docs/automation-workflow.md` 新增 §10「環境與變數設定」端到端流程 + §3 標準 layout 更新（尾段重編號 11/12）

## 11. 測試

- [x] 11.1 環境目錄 / 共用參數 / per-script 覆寫 CRUD、設預設唯一性、有效值解析（覆寫優先）（`test_automation_environment_config.py`）
- [x] 11.2 secret 加密遮罩、API 永不回 plaintext、匯出遮罩、bootstrap 金鑰守門（env secret 列）
- [x] 11.3 `TCRT_VARS` 發現（字串/dict）、非字面量 fail-open、declared-vs-effective 覆蓋對賬
- [x] 11.4 觸發解析順序（指定/default）、無宣告變數走現況、缺環境 `Required`、缺必填 `Incomplete`（列 script×缺項）
- [x] 11.5 `test_trigger_group_run_injects_env_bundle_and_masks_inputs`：解密 namespaced `TCRT_ENV_BUNDLE` 進 CI inputs、`automation_runs.environment` 記名、`inputs_json` 遮罩；Jenkins body split 由 6.1 + provider 測試覆蓋
- [x] 11.6 既有 suite 模板升級 / 不帶環境不碰：由 55 template-rendering 測試覆蓋（空 bundle → stage 略過）
- [x] 11.7 run 列表 `?environment=` 篩選（route + run_service）/ env chip（run-history.js）/ audit `environment`（test_run_sets `_audit_run_for_test_run_set`）

## 12. 驗證

- [x] 12.1 automation / environment / test-run-set / mcp / database_init 相關 pytest 全綠（139 passed）
- [x] 12.2 `openspec validate manage-automation-environment-configs --strict` 通過
