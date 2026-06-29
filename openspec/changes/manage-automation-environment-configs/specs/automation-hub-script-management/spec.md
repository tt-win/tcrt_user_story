## ADDED Requirements

### Requirement: smart-scan MUST discover each script's declared variables from source

每支 script 需要哪些變數 SHALL 由 `init` / `pomify` 規範進**源碼宣告**，並由 smart-scan **逐檔 AST 發現**（與既有 `@pytest.mark.tcrt` marker 發現一致），使 TCRT 知道「這支 script 有幾個變數要設」。

- Python 正規宣告為 module-level `TCRT_VARS`，元素為字串或 dict：
  ```python
  TCRT_VARS = [
      "BASE_URL",                                  # 等同 {name:"BASE_URL", secret:false, required:true}
      {"name": "API_TOKEN", "secret": True, "required": True, "description": "..."},
  ]
  ```
- smart-scan SHALL 把發現結果存進 `automation_scripts` 新增欄位 `declared_vars_json`（list of `{name, secret, required, description}`）。
- `name` SHALL 符合 `^[A-Za-z_][A-Za-z0-9_]*$`；非字面量 / 不合法 name SHALL **fail-open**：不阻斷掃描、記入 scan response 的 `var_warnings[]`（如 `non_literal_var` / `invalid_var_name`），該項略過。
- 未宣告 `TCRT_VARS` 的 script：`declared_vars_json` SHALL 為空（環境功能不對該 script 啟用，行為向後相容）。
- 此宣告 SHALL **只宣告變數名稱與 metadata、不含值**；值存 TCRT（見 `automation-hub-environment-config`）。

#### Scenario: Declared vars discovered into script row
- **WHEN** `tests/test_login.py` 含 `TCRT_VARS = ["BASE_URL", {"name":"API_TOKEN","secret":True,"required":True}]`，team 觸發 rescan
- **THEN** 該 script 的 `declared_vars_json` SHALL 為 `[{name:"BASE_URL",secret:false,required:true},{name:"API_TOKEN",secret:true,required:true}]`

#### Scenario: Non-literal declaration fails open
- **WHEN** `TCRT_VARS = SOME_LIST`（變數而非字面量）
- **THEN** 掃描 SHALL 不中斷，記 `var_warnings[]` `{type:"non_literal_var"}`，該 script 視為未宣告

#### Scenario: Script without declaration
- **WHEN** script 未宣告 `TCRT_VARS`
- **THEN** `declared_vars_json` SHALL 為空；掃描與既有行為不變

### Requirement: Script view MUST surface declared variables and a configure-variables entry

Scripts tab 的 **Script view** 每支 script SHALL 顯示其 declared variables 數量 / 摘要，並提供「設定變數」入口開啟 per-script 變數設定 modal（modal 行為見 `automation-hub-environment-config`）。未宣告變數的 script SHALL **不**顯示此入口（畫面與本變更前一致）。

#### Scenario: Configure-variables entry shown when declared
- **WHEN** 某 script 的 `declared_vars_json` 非空
- **THEN** Script view 該檔列 SHALL 顯示變數數量與「設定變數」入口
- **WHEN** 某 script 未宣告變數
- **THEN** SHALL 不顯示該入口

### Requirement: Variable declaration grammar changes MUST sync the automation authoring skills

任何對「per-script 變數宣告對外文法」造成行為差異的變更——`TCRT_VARS` 文法 / 欄位、變數名稱規則、secret 旗標語意、或 TCRT 注入 CI 的 bundle 約定（`TCRT_ENV_BUNDLE` 結構與 workspace 物化檔名）——SHALL 在同一個 OpenSpec change / PR 中同步更新 automation 撰寫技能，否則該 change 不得 archive、PR 不得 merge。

需同步檔案至少包含：

- `tools/skills/tcrt-automation-pomify/SKILL.md`（新增「變數規範 + 環境設定正規化」步驟）
- `tools/skills/tcrt-automation-pomify/references/`（`TCRT_VARS` 文法、settings loader 約定、值存 TCRT 不進 repo）
- `tools/skills/tcrt-automation-pomify/templates/`（`TCRT_VARS` 宣告、settings loader）
- `tools/skills/tcrt-automation-init/` 對應範本（兩 skill 一致）

純 TCRT 內部、不影響「QA 如何撰寫 script」或對外文法的變更，MAY 於 PR 描述 opt-out 並附理由。

#### Scenario: Var grammar change requires skill sync
- **WHEN** 開發者為 `TCRT_VARS` 新增影響對外文法的欄位（如 `default`），未同步 skill 範本
- **THEN** `openspec validate` / code review SHALL 標示「skill 未同步」並阻擋 archive

#### Scenario: Internal-only change opts out
- **WHEN** 變更僅調整 TCRT 內部值儲存細節（不影響源碼文法與注入約定）
- **THEN** skill 同步義務 NOT applicable，PR 描述註明即可
