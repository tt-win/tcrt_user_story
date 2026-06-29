## Why

Automation Hub 目前能跟 Storage(GitHub/LocalGit) / CI(Jenkins) / Result(Allure) provider 互動，但**無法讓使用者依環境（Prod / SIT / dev）餵不同的參數給 script**。觸發 run 時 `trigger_group_run` 組出的 `run_inputs` 只含 `runner_label`、`test_paths` 與 git context，沒有任何「環境參數」概念；`tcrt-automation.yml` 的 `paths.config` 雖存在，但 `config/` 只被 `scan_filters` 排除、**沒有任何程式讀取或注入其內容**。

後果：同一支 script 要對不同環境跑，使用者只能在 script 裡硬寫、或自己在 CI 端管環境變數，TCRT 完全不知情、也無法治理。

依與需求方確認的設計方向：

- **設定值集中存 TCRT、不進 repo**：script 只依賴**固定變數名稱**；值存 TCRT、執行時傳給 CI。secrets 因此**不進版控**（符合既有 P0），改以 AES-256-GCM 加密存 TCRT。
- **變數規範在 `init` / `pomify`**：撰寫腳本當下就把「這支 script 需要哪些變數」規範進源碼，TCRT 的 smart-scan 逐檔發現，於是知道每支 script 有幾個變數要設。
- **環境由使用者在 Automation Hub 自訂**：在 Settings 定義要幾個環境，每個環境帶一組**共用參數**。
- **值 by script 設定**：在 Scripts 分頁的 **Script view** 以「變數設定 modal」對每支 script、每個環境設值；未覆寫者吃環境共用值（per-script 覆寫優先）。
- **環境在 Test Run Set 觸發時選**：沿用唯一執行入口，Set 記預設、每次可覆寫。
- **正規格式為 YAML**：環境共用參數的匯入 / 匯出用 YAML；script 變數宣告（`TCRT_VARS`）為源碼正規形式，由 `pomify` 產生。

## What Changes

- **新增 capability `automation-hub-environment-config`**（三層模型）：
  - **環境目錄**（`automation_environments`，team 範圍、使用者自訂）。
  - **環境共用參數**（`automation_environment_params`，per-environment）。
  - **per-script 覆寫值**（`automation_script_env_vars`，per script × environment × key）。
  - secret AES-256-GCM 加密、CRUD / YAML 匯入匯出 API、Script view 的 per-script 變數設定 modal、Settings 的環境管理 UI、declared-vs-effective 覆蓋驗證。
- **per-script 變數宣告**：smart-scan 從源碼 module-level `TCRT_VARS` 逐檔發現，存進 `automation_scripts.declared_vars_json`；Script view 顯示變數數並提供「設定變數」入口。
- **執行時注入**：`trigger_group_run` 依選定環境，對 suite 內每支 script 算有效值（共用 ⊕ 覆寫），組成**依 script 路徑 namespace** 的 bundle，透過 `CIProvider.trigger_run` 注入；secret 以遮罩參數 + HTTP body 傳遞、物化成 workspace `tcrt-env.json`，由 skill 產生的 loader 依測試檔取對應 namespace。
- **環境選擇**：`test_run_sets` 新增 `default_automation_environment`；`run-automation` 接受可選 `environment`；Test Run Set detail 觸發 UI 出現環境選單（僅在相關時）。
- **執行紀錄**：`automation_runs` 新增 `environment`（只記名）；run 列表 / 詳情顯示 chip、支援 `?environment=`、audit 記錄環境名。
- **技能與文件同步**：更新 `tools/skills/tcrt-automation-pomify/`（`TCRT_VARS` 文法 + settings loader + 環境正規化步驟）與 `tools/skills/tcrt-automation-init/`，並更新 `docs/automation-workflow.md`。

### 非目標（Non-Goals）

- **不把設定值存進 repo**：repo 端只有源碼的 `TCRT_VARS` 宣告（無值）與選擇性 `*.yaml.example` 範本；真值一律存 TCRT。
- **不提供 TCRT 內編輯 / 回寫 git script 內容**（既有原則不變）。
- **不改 run-automation 端點路徑與既有 payload 形狀**（僅新增可選 `environment`，未帶時行為同現況）。
- **不對「未宣告變數的 script / 未定義環境的 team」改變現有行為**（向後相容）。
- **不引入新的 secret 後端 / KMS**（重用 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 與 `provider_credential_service`）。

## Capabilities

### New Capabilities

- `automation-hub-environment-config`：TCRT 集中管理環境目錄、環境共用參數與 per-script 覆寫值（含加密、驗證、YAML 匯入匯出、Settings 環境管理 UI 與 Script view 變數設定 modal）。

### Modified Capabilities

- `automation-hub-script-management`：smart-scan 從源碼 `TCRT_VARS` 逐檔發現 declared variables 存進 `declared_vars_json`；Script view 顯示變數並提供設定入口；新增變數宣告文法的 skill 同步義務。
- `automation-hub-provider-framework`：`CIProvider.trigger_run` 注入**依 script namespace** 的環境參數 bundle；Jenkins / GHA suite job 模板新增單一遮罩 bundle 參數並物化於 workspace、secret 改走 HTTP body。
- `automation-hub-run-orchestration`：`automation_runs` 新增 `environment`；run 列表 / 詳情 / 篩選 / audit 納入環境（只記名、不記值）。
- `test-run-management-ui`：Test Run Set 持久化 `default_automation_environment`；run-automation 解析環境並以「suite 內各 script 的 declared required × 有效值」驗證、缺則擋；觸發 UI 新增環境選單。

## Impact

- **資料庫**：
  - 新表 `automation_environments`、`automation_environment_params`、`automation_script_env_vars`（後兩者含 secret 加密欄位）。
  - `automation_scripts` +`declared_vars_json`；`automation_runs` +`environment VARCHAR(60) NULL`；`test_run_sets` +`default_automation_environment VARCHAR(60) NULL`。
  - 新 Alembic migration（chained 到 head），全部**附加式、非破壞**；既有 row 維持 NULL / 空。`downgrade` 為 drop。
  - `database_init.py` bootstrap schema 與「缺重要表」檢查 SHALL 涵蓋三張新表。
- **安全 / Bootstrap**：secret 值 AES-256-GCM 加密、重用 `AUTOMATION_PROVIDER_ENCRYPTION_KEY`；有 secret 值但金鑰缺失 SHALL 比照 provider 規則阻擋啟動。API 永不回 plaintext，只回 `is_set` + fingerprint。
- **服務 / Provider**：`script_service`（`TCRT_VARS` 發現 + 覆蓋對賬）、`script_group_service.trigger_group_run`（算有效值 → namespaced bundle → 注入）、`test_run_set_automation_service`（透傳 environment）、`jenkins_ci` / `github_actions_ci`（bundle 參數、secret 走 body、模板升級）。
- **既有 suite 相容性**：未選環境的觸發完全不變；選環境時先把 suite job 同步成含 bundle 參數的模板（重用 self-heal），不需 backfill。覆寫值以 `script_ref_path` 穩定鍵保存，re-scan 不遺失。
- **MCP / 序列化**：環境**值**一律不經 MCP 揭露；至多揭露環境名稱（預設不揭露）。
- **Rollback**：drop 三新表與新欄位、還原模板；注入停止、run 退回無環境行為，run 歷史不受影響。被 drop 的 secret 值遺失（可重輸，可接受）。
- **測試 / 文件**：新增環境 / 共用參數 / 覆寫值 CRUD、加密遮罩、`TCRT_VARS` 發現、觸發注入與驗證擋關、模板升級的測試；更新 `docs/automation-workflow.md` 與兩個 skill bundle。
