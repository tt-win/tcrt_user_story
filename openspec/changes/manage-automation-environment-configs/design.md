## Context

執行鏈現況（已查證）：

- 唯一觸發入口：`POST /api/teams/{team_id}/test-run-sets/{set_id}/run-automation`（`app/api/test_run_sets.py`）→ `TestRunSetAutomationService.trigger_automation_suites` → 對每個 suite 呼叫 `AutomationScriptGroupService.trigger_group_run`（`app/services/automation/script_group_service.py`）。
- `trigger_group_run` 組 `run_inputs = {**(inputs or {}), "runner_label": ..., "test_paths": json.dumps(paths)}` + git context，呼叫 `provider.trigger_run(job_name, branch, run_inputs)`，整包存 `automation_runs.inputs_json`。
- Jenkins adapter（`providers/jenkins_ci.py`）`trigger_run` 把 `inputs` 每個 key 當 build parameter，以 **query string** POST `/job/{name}/buildWithParameters`；suite job 由 `jenkins-suite-config.xml.j2` 宣告 `NODE_LABEL / GIT_URL / GIT_BRANCH / GIT_TOKEN`。
- smart-scan 已逐檔 AST 解析 Python（test 名、`@pytest.mark.tcrt` markers）；script 快取為 `automation_scripts`（UNIQUE `(team_id, provider_id, ref_path, ref_branch)`）。
- secrets 既有處理：provider credentials 以 `provider_credential_service`（AES-256-GCM、`AUTOMATION_PROVIDER_ENCRYPTION_KEY`）加密；API 只回 `credentials_set` + fingerprint。

**約束**：CI/Result provider 為 org-scoped、Storage/script/suite/run 為 team-scoped；既有原則「TCRT 不回寫 git script、`cached_content` 唯讀」；P0「secrets 不進版控」；未宣告變數 / 未定義環境者行為不可變（向後相容）。

## Goals / Non-Goals

**Goals**
- 同一支 script 能對多環境跑：值集中存 TCRT、執行時傳 CI；script 只取固定變數名稱。
- 撰寫腳本當下（init/pomify）就規範變數，TCRT 逐檔知道每支 script 要設幾個變數。
- 環境由使用者自訂；常見參數以環境共用、特例以 per-script 覆寫。
- secrets 不進 repo、加密存 TCRT、不外漏 log / query string / API。
- 向後相容：未宣告變數 / 未定義環境 = 現況行為。

**Non-Goals**
- 不在 repo 存值、不回寫 git script。
- 不引入 KMS / 新 secret 後端。
- 不改觸發端點路徑與既有 payload 形狀（僅新增可選欄位）。

## Decisions

### D1. 三層值模型：環境目錄 → 環境共用參數 → per-script 覆寫

- **環境目錄**（`automation_environments`，team 範圍）：使用者在 Automation Hub Settings 自訂要幾個環境。
- **環境共用參數**（`automation_environment_params`，per-environment）：跨 script 共用（如 `BASE_URL`）。
- **per-script 覆寫**（`automation_script_env_vars`，per script × environment × key）：在 Script view modal 設定。
- 有效值 = 共用 ⊕ 覆寫（覆寫優先）。
- **理由**：需求方要「by script 設定」又要「共用參數放環境設定」；三層同時滿足，並解掉 suite 多 script 同名變數的撞名問題。
- **Alternative（否決）**：純 per-script 值（無共用層）。否決：常見參數要在每支 script 重複填、易漂移。
- **Alternative（否決）**：純 team-level 同名共用（無覆寫）。否決：無法表達 script 專屬差異。

### D2. 變數「宣告」在源碼、由 smart-scan 逐檔發現

- Python module-level `TCRT_VARS`（字串或 `{name, secret, required, description}`）；smart-scan AST 解析，存 `automation_scripts.declared_vars_json`。
- 非字面量 / 不合法 fail-open（記 `var_warnings[]`），不阻斷掃描。
- `init` / `pomify` 產生此宣告（撰寫當下規範變數）。
- **理由**：與既有「marker 由源碼 AST 發現」一致；宣告隨檔案移動；TCRT 因此知道「這支 script 有幾個變數要設」。值不在這裡（宣告只列名稱與 metadata）。
- **Alternative（否決）**：在 `tcrt-automation.yml` 用 `scripts: {<path>: {vars}}` map。否決：與源碼分離、pomify 要回頭改 manifest、易漂移。

### D3. 值存 TCRT、加密、API 遮罩

- secret 值以 `provider_credential_service`（AES-256-GCM、`AUTOMATION_PROVIDER_ENCRYPTION_KEY`）加密存 `value_encrypted`；非 secret 存 `value_plaintext`。
- API 永不回 secret 真值，只回 `is_set` + fingerprint；匯出時 secret 遮罩。
- Bootstrap：有 secret 值列但金鑰缺失 → 比照既有 provider 阻擋啟動並印生成指引。
- **理由**：需求方明示「值存 TCRT」；以既有機制收斂 secret 風險，且 secrets 不進版控（達成 P0）。

### D4. 注入：依 script 路徑 namespace 的單一遮罩 bundle

- `trigger_group_run` 解析環境後，對 suite 內每支 script 算有效值，組 `bundle = {ref_path: {KEY: value}}`（secret 解密後置入），序列化為 JSON 放進 `run_inputs["TCRT_ENV_BUNDLE"]`（單一鍵）。
- `CIProvider.trigger_run` 把 `TCRT_ENV_BUNDLE`（及 `GIT_TOKEN`）以 **HTTP body（form-encoded）** 傳、Jenkins 宣告 `PasswordParameterDefinition`、GHA `::add-mask::`。
- suite job（靜態模板步驟）把 bundle 物化成 workspace `tcrt-env.json`（不 `export`、不 `set -x`）；skill 產生的 loader 依當下測試檔 ref_path 取對應 namespace，暴露固定變數名稱給 script。
- **理由**：namespace 解掉「一個 suite 多 script、同名變數不同值」的撞名；單一 bundle 讓 job 模板靜態、變數集隨宣告動態、只有一個遮罩點；query string→body 修掉現有 GIT_TOKEN 外漏面。
- **Alternative（否決）**：每變數一個 build parameter。否決：模板要隨宣告重生、遮罩分散。
- **Alternative（否決）**：TCRT 端讀 repo `config/<env>.yaml` 注入。否決：需求方要求值存 TCRT、repo 不存。

### D5. 環境選擇與解析順序

- `test_run_sets.default_automation_environment` 記預設；`run-automation` 接受可選 `environment`。
- 解析順序：`request.environment` → `set.default_automation_environment` → team 環境目錄的 `is_default`。
- 觸發門檻以「suite 內各 script 的 declared required 變數」為準：
  - 聯集為空 → 不要求環境、不注入（向後相容）。
  - 非空但解析不出環境 → 422 `ENVIRONMENT_REQUIRED`。
  - 解析出環境但某 script required 變數無有效值 → 422 `ENVIRONMENT_INCOMPLETE`（列 script × 缺項）。
- **理由**：沿用唯一執行入口（Test Run Set）；以實際 script 宣告驅動，未用環境者零影響。

### D6. 既有 suite job 模板採 on-demand 升級

- 既有 suite job 無 `TCRT_ENV_BUNDLE` 參數。**只有帶環境觸發時**先以含 bundle 參數的新模板 `update_suite_job`（重用 self-heal）再觸發；未帶環境不碰模板。
- **理由**：零 backfill、對沒用環境的 suite 零成本零行為變動。

### D7. 覆寫值綁 script 快取列（與既有 marker link 一致）

- `automation_script_env_vars.automation_script_id` FK ON DELETE CASCADE，並另存 `script_ref_path` 供顯示 / audit。
- 正常 re-sync 會**更新既有 script 列（id 不變）**，覆寫值隨之保留；只有**顯式刪除 script 快取**才連帶 CASCADE 移除（與 `automation_script_case_links` 行為一致）。
- **理由**：與既有 link cascade 語意一致、最簡；正常掃描不刪列故不誤刪值。環境**共用參數**（非綁 script）不受 script 刪除影響，是常見值的主要存放層。
- **Alternative（否決）**：以 `(team_id, script_ref_path, …)` 穩定鍵讓覆寫值在顯式刪除後仍重關聯。否決：需每次 sync 額外 reconcile、且與既有 link cascade 不一致；常見值改放環境共用層即可避免遺失痛點。

### D8. 正規格式 = YAML（匯入匯出）+ 源碼宣告（變數）

- 環境共用參數的批次匯入 / 匯出用扁平 YAML（`{key: value}`，匯出 secret 遮罩）。
- 變數**宣告**的正規形式為源碼 `TCRT_VARS`（由 pomify 產生）。
- pomify 另可產 `config/<env>.yaml.example`（佔位、無真值）作文件，並把真值檔加進 `.gitignore`，引導使用者到 TCRT 輸入值。
- **理由**：符合 Q3（YAML）且與 TCRT 既有 YAML 設定風格一致。

## Risks / Trade-offs

- **[secret 經 query string 外漏]** → secret 參數（含 `TCRT_ENV_BUNDLE`）改走 HTTP body；Jenkins password parameter；物化成檔不 export。
- **[secret 進 TCRT DB]** → 需求方明示取捨（換 secrets 不進版控）；AES-256-GCM、API 遮罩、audit、bootstrap 守門收斂。
- **[suite 多 script 同名變數撞名]** → bundle 依 ref_path namespace，loader 依測試檔取對應 namespace。
- **[既有 suite job 缺 bundle 參數]** → D6 帶環境觸發時 on-demand 升級模板（self-heal 冪等）。
- **[覆寫值因 cache 刪除遺失]** → 正常 re-sync 不刪列故保留；常見值放環境共用層（不綁 script）避免痛點；顯式刪除才 cascade（與 marker link 一致）。
- **[向後相容]** → 未宣告變數 / 未定義環境 / 未選環境 = 現況；新欄位皆 nullable/空。
- **[skill / 文件漂移]** → 受 `automation-hub-script-management` 同步義務拘束；tasks 含 skill 與 `docs/automation-workflow.md` 同步項。

## Migration Plan

1. Alembic migration（chained 到 head）：
   - create `automation_environments`、`automation_environment_params`、`automation_script_env_vars`。
   - `automation_scripts` add `declared_vars_json`；`automation_runs` add `environment`；`test_run_sets` add `default_automation_environment`。
   - 全附加式；既有 row 維持 NULL / 空。
2. `database_init.py`：create_all 涵蓋新表；「缺重要表」檢查納入三張新表。
3. 部署後：既有 suite 不需 backfill；環境功能對「未宣告變數 / 未定義環境」者不啟用。
4. **Rollback**：`downgrade` drop 三新表 + 三新欄位；還原 suite job 模板。注入停止、run 退回無環境行為；run 歷史不受影響。被 drop 的 secret 值遺失（可重輸，可接受）。

## Open Questions

- 環境範圍 v1 = team。若未來「同 team 多 repo、各自變數集不同」需求出現，是否下放到 storage provider / repo 範圍？（暫不做）
- pomify 偵測既有設定（hardcoded URL / `.env` / `settings.py` / `config.ini`）轉成 `TCRT_VARS` 的覆蓋率到哪？v1 先支援常見幾種，無法判定以 `TODO(pomify)` 標記，不臆測。
- MCP 是否需揭露環境名稱 / 覆蓋狀態給唯讀工具？預設先不揭露。
- 環境共用參數是否需要「跨 team / org-level 共用環境」？v1 為 team-scoped；org-level 留後續。
