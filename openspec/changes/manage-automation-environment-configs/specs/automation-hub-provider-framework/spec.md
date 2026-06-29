## ADDED Requirements

### Requirement: CIProvider MUST inject per-script effective env values as a namespaced masked bundle

當觸發帶有環境選擇時，呼叫端 SHALL 在 `inputs` 內提供單一鍵 `TCRT_ENV_BUNDLE`，其值為 **依 script 路徑 namespace 的 JSON 物件字串**：

```json
{ "tests/test_login.py": {"BASE_URL": "...", "API_TOKEN": "..."},
  "tests/test_checkout.py": {"BASE_URL": "..."} }
```

每支 script 的內層物件為該 script 在選定環境的**有效值**（環境共用 ⊕ per-script 覆寫，secret 已解密置入）。namespace 讓同一 suite 多支 script 即使同名變數值不同也不會互相覆蓋。

`CIProvider.trigger_run` SHALL 把 `TCRT_ENV_BUNDLE` 視為**敏感參數**：

- 採用**單一** namespaced bundle 參數（而非每變數一個 build parameter），使 suite job 模板維持靜態、變數集隨各 script 的宣告動態。
- 敏感參數（`TCRT_ENV_BUNDLE`、既有 `git_token`/`GIT_TOKEN`）SHALL 透過 **HTTP request body（form-encoded）** 傳給 CI，**不得**置於 URL query string。
- 非敏感 inputs（`runner_label`/`NODE_LABEL`、`test_paths`）行為不變。

未帶環境的觸發 SHALL 不含 `TCRT_ENV_BUNDLE`，行為與本變更前一致。

#### Scenario: Bundle namespaced per script
- **WHEN** suite 含兩支 script、各自在 `sit` 有不同 `BASE_URL`，以 `sit` 觸發
- **THEN** `TCRT_ENV_BUNDLE` SHALL 含兩個以 ref_path 為鍵的 namespace，各帶該 script 的有效值，互不覆蓋

#### Scenario: Jenkins receives bundle via body as password parameter
- **WHEN** TCRT 以含 `TCRT_ENV_BUNDLE` 的 inputs 觸發 Jenkins suite job
- **THEN** `jenkins_ci.trigger_run` SHALL 以 form-encoded body 送 `TCRT_ENV_BUNDLE`（及 `GIT_TOKEN`），不放 query string
- **AND** 對應 job 參數 SHALL 為 `PasswordParameterDefinition`（UI / log 遮罩）

#### Scenario: No environment keeps current behavior
- **WHEN** 觸發未帶環境（inputs 無 `TCRT_ENV_BUNDLE`）
- **THEN** 參數組裝 SHALL 與本變更前一致，不新增環境參數

#### Scenario: GitHub Actions masks bundle
- **WHEN** TCRT 以含 `TCRT_ENV_BUNDLE` 觸發 GHA workflow_dispatch
- **THEN** workflow 內 SHALL 以 `::add-mask::` 遮罩後再使用，log 不顯示真值

### Requirement: Suite job templates MUST accept the bundle and materialize it to the workspace

Jenkins（`jenkins-suite-config.xml.j2`）與 GitHub Actions 的 suite job 模板 SHALL 新增**單一**環境 bundle 參數，並把其值**物化成 workspace 檔**（`tcrt-env.json`）供測試端的 settings loader 讀取，而**非**以 `export` 灌入 shell 環境（避免 `set -x` / 子行程外漏）。

- Jenkins：`TCRT_ENV_BUNDLE` 為 `PasswordParameterDefinition`（預設空）；pipeline 在 `pytest` 前把非空值寫 workspace `tcrt-env.json`（空值略過）。
- GitHub Actions：新增 `tcrt_env_bundle` input；step 內遮罩後寫 `tcrt-env.json`。
- 模板其餘內容（NODE_LABEL / GIT_* / 安裝步驟 / 通知 webhook）SHALL 不變。
- bundle 參數為**單一且靜態宣告**：無論各 script 宣告幾個變數，job 模板皆不需隨之重生。
- 測試端由 skill 產生的 settings loader 讀 `tcrt-env.json`，**依當下測試檔的 ref_path 選取對應 namespace**，把變數以固定名稱提供給 script 取用。

#### Scenario: Bundle written to workspace, not exported
- **WHEN** Jenkins suite build 以非空 `TCRT_ENV_BUNDLE` 執行
- **THEN** pipeline SHALL 把值寫 workspace `tcrt-env.json`，且 `pytest` 前不以 `export` 將 secret 注入 shell 環境
- **WHEN** `TCRT_ENV_BUNDLE` 為空（未選環境）
- **THEN** pipeline SHALL 略過寫檔，行為與本變更前一致

#### Scenario: Template static across declaration changes
- **WHEN** 某 script 的 `TCRT_VARS` 從 2 個增為 5 個
- **THEN** suite job 模板 SHALL 不需重生（仍只有單一 `TCRT_ENV_BUNDLE` 參數）

### Requirement: Triggering with an environment MUST ensure the suite job template is env-aware first

既有 suite 的 CI job 可能尚無 bundle 參數。當觸發**帶環境**時，run orchestration SHALL 在 `trigger_run` 前，先以含 bundle 參數的最新模板對該 suite job `update_suite_job`（重用既有 self-heal：update→404→create），再觸發。未帶環境的觸發 SHALL **不**碰模板。

#### Scenario: Legacy suite job upgraded on first env-enabled trigger
- **WHEN** 一個本變更前建立、job 無 `TCRT_ENV_BUNDLE` 參數的 suite，首次被帶環境觸發
- **THEN** orchestration SHALL 先 `update_suite_job` 升級模板，再 `trigger_run`
- **WHEN** 同一 suite 之後被不帶環境觸發
- **THEN** SHALL 不因此變更而改動模板或行為
