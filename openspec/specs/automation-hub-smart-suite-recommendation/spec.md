# automation-hub-smart-suite-recommendation Specification

## Purpose
TBD - created by archiving change add-automation-hub. Update Purpose after archive.
## Requirements
### Requirement: System MUST run Smart Scan as an asynchronous scan run
Smart Scan SHALL 以非同步 scan run 執行，避免大型 repo、GitHub API latency 或 LLM timeout 阻塞 request。系統 SHALL 新增 scan run 持久化模型，至少包含：

- `id` PK
- `team_id` FK indexed
- `provider_id` FK -> `team_automation_providers.id`
- `status` ENUM(`QUEUED`, `SCANNING`, `ENRICHING`, `READY`, `FAILED`, `CANCELLED`)
- `scan_config_hash` VARCHAR(64)
- `progress_json` TEXT nullable（目前步驟、完成數、總數）
- `result_json` MEDIUMTEXT nullable（entry points、excluded reasons、suggested suites）
- `error_summary` TEXT nullable
- `created_by`, `created_at`, `updated_at`, `finished_at`

#### Scenario: Smart Scan starts and returns scan_run_id
- **WHEN** 使用者點擊 Smart Scan
- **THEN** API SHALL 建立 scan run 並立即回 `202 Accepted` + `scan_run_id`
- **THEN** 前端 SHALL 輪詢 scan run 狀態，而不是等待 GitHub + LLM 全部完成

#### Scenario: Existing ready scan can be reused
- **WHEN** 相同 team、provider、branch、script etags、prompt version、model id、scan_config_hash 的 scan run 已是 `READY`
- **THEN** API MAY 直接回可重用的 `scan_run_id`，避免重複打 GitHub 或 LLM

### Requirement: System MUST support an Automation Repo Contract manifest
Smart Scan SHALL support a repo-root manifest named `tcrt-automation.yml` by default。Manifest 的目的 SHALL 是讓 QA repo 使用固定且可驗證的結構，避免 TCRT 只靠 heuristic 猜測測試檔、POM、fixtures、resources 與 config。

標準 repo structure SHOULD 為：

```text
automation-repo/
  tcrt-automation.yml
  tests/                 # test entry points only
  pages/                 # POM / Page Object Model
  flows/                 # reusable business flows / scenario steps
  fixtures/              # pytest fixtures / setup helpers
  resources/
    data/
    files/
    locators/
  config/
    envs/
    config.example.yaml
  scripts/               # local helper scripts
  reports/               # generated artifacts, should not be committed
```

Manifest v1 SHALL support at least:

```yaml
version: 1
framework: pytest
paths:
  tests: tests/
  pages: pages/
  flows: flows/
  fixtures: fixtures/
  resources: resources/
  config: config/
scan:
  include:
    - "test_*.py"
    - "*_test.py"
    - "*.spec.ts"
    - "*.test.ts"
  exclude:
    - "*conftest*"
    - "*/pages/*"
    - "*/flows/*"
    - "*/fixtures/*"
    - "*/resources/*"
    - "*/config/*"
suites:
  grouping: first_level_directory
  default_suite: Full Regression
commands:
  smoke: "pytest tests/smoke --junitxml=reports/junit/smoke.xml"
  regression: "pytest tests/regression --junitxml=reports/junit/regression.xml"
artifacts:
  junit: reports/junit/
  html: reports/html/
  traces: reports/traces/
```

Smart Scan SHALL resolve the effective scan configuration in this order:

1. Provider config values explicitly marked as admin-enforced
2. Valid `tcrt-automation.yml` manifest
3. Provider `smart_scan` defaults

Manifest parsing SHALL be non-destructive：invalid or missing manifest SHALL NOT block Smart Scan unless provider config sets `smart_scan.require_manifest=true` or `smart_scan.enforce_repo_contract=true`。

Scan result SHALL include `repo_contract` metadata:
- `manifest_path`
- `manifest_found`
- `manifest_etag`
- `contract_status` ENUM(`VALID`, `WARNING`, `INVALID`, `MISSING`)
- `framework`
- `effective_tests_path`
- `support_paths`
- `missing_paths`
- `violations`

#### Scenario: Manifest defines test and support paths
- **WHEN** repo root contains valid `tcrt-automation.yml` with `paths.tests=tests/` and `paths.pages=pages/`
- **THEN** Smart Scan SHALL scan only the effective tests path for entry points
- **THEN** `pages/` SHALL be treated as support path and excluded from suite suggestions

#### Scenario: Manifest is missing but not required
- **WHEN** repo has no `tcrt-automation.yml` and provider config has `require_manifest=false`
- **THEN** Smart Scan SHALL fallback to provider `smart_scan` defaults
- **THEN** `repo_contract.contract_status` SHALL be `MISSING` with a warning message

#### Scenario: Repo contract is enforced
- **WHEN** provider config has `require_manifest=true` and repo has no valid manifest
- **THEN** scan run SHALL stop with `FAILED`
- **THEN** UI SHALL show a repo contract error instead of returning heuristic suite suggestions

### Requirement: System MUST detect test script entry points deterministically
Smart Scan SHALL 以 deterministic path filtering + structural content analysis 判斷 entry points。LLM SHALL NOT be required for entry point detection.

**Phase 1 - Path filtering:**
- 掃描範圍：`StorageProvider.list_scripts(path=effective_tests_path, recursive=True)`；`effective_tests_path` 優先來自 `tcrt-automation.yml` 的 `paths.tests`，缺省時 fallback 為 provider config 的 `smart_scan.scan_path`，再缺省則為 `"tests/"`
- 納入條件：檔案名稱符合 `test_*`、`*_test.py`、`*.spec.*`、`*.test.*`
- 排除條件：
  - `__init__.py`、`conftest.py`、`conftest.js`、`conftest.ts`
  - 路徑含 `pages/`、`page_objects/`、`pom/`、`flows/`、`utils/`、`helpers/`、`fixtures/`、`mocks/`、`resources/`、`testdata/`、`data/`、`config/`、`scripts/`、`reports/`
  - 路徑含 `.github/`、`.git/`、`node_modules/`、`venv/`、`env/`、`__pycache__/`
  - 副檔名非 `.py`、`.js`、`.ts`、`.jsx`、`.tsx`

**Phase 2 - Structural content validation:**
- 對 Phase 1 通過的檔案，service SHALL 讀取可接受大小內的 content（預設 `max_scan_bytes=262144`）
- Python SHALL 使用 `ast` 判斷 `def test_*`、`async def test_*`、`class Test*`
- JS/TS SHALL 先以 bounded lexical scan 判斷 `test(`、`test.describe(`、`test.only(`、`test.skip(`、`it(`、`describe(`；未來 MAY 改用 JS parser
- 若內容不含任何 test pattern，SHALL 標記為 `false_positive` 並排除
- 若檔案超過 `max_scan_bytes`，SHALL 不送 LLM，並 MAY 以 Phase 1 結果保守納入且標記 `content_unverified=true`

回傳 entry point 每筆 SHALL 包含：`ref_path`、`ref_branch`、`etag`、`detected_format`、`test_names`、`test_count`、`content_unverified`。

#### Scenario: Mixed repo with helpers and real tests
- **WHEN** repo 結構含 `tests/auth/test_login.py`、`tests/pages/login_page.py`、`tests/conftest.py`
- **THEN** Smart Scan SHALL 只把 `tests/auth/test_login.py` 納入 entry points
- **THEN** 被排除檔案 SHALL 在 result 中提供 reason，例如 `helper_path`、`conftest`、`unsupported_extension`

#### Scenario: Python false positive is filtered by AST
- **WHEN** `tests/auth/test_data_builder.py` 檔名符合 `test_*` 但 AST 內沒有 test function 或 `class Test*`
- **THEN** Smart Scan SHALL 將它標記為 `false_positive`，不納入 suite 建議

### Requirement: System MUST group entry points by deterministic rules
Smart Scan SHALL 先以 deterministic rule-based grouping 產生 suite suggestions，不依賴 LLM。

分組演算法：
1. 取所有 entry points 的 `ref_path`
2. 若 effective tests path 下有第一層子目錄，每個子目錄形成一個 candidate suite
3. 若為 flat 結構，所有 entry points 形成 `Full Regression`
4. effective tests path 根目錄下零散檔案形成 `General`
5. 每個 group SHALL 有 deterministic `rule_based_name`、`rule_based_description`、`script_paths`、`estimated_test_count`

#### Scenario: Nested directory structure
- **WHEN** repo 有 `tests/auth/test_login.py`、`tests/checkout/test_cart.py`、`tests/admin/test_user.py`
- **THEN** Smart Scan SHALL 產生 Auth、Checkout、Admin 三個 deterministic groups

#### Scenario: Flat directory structure
- **WHEN** repo 只有 `tests/test_login.py`、`tests/test_logout.py`、`tests/test_api.py`
- **THEN** Smart Scan SHALL 產生單一 `Full Regression` group

### Requirement: System MUST keep LLM enrichment optional and privacy-bounded
LLM enrichment SHALL 只用於改善 suite name / description / confidence，不得影響 entry point 是否成立。當 `enable_llm=false`、OpenRouter key 缺失、LLM timeout、或 LLM 回傳格式錯誤時，Smart Scan SHALL fallback 到 rule-based suggestions。

預設 LLM input SHALL 只包含：
- `directory_path`
- `script_paths`
- `test_names`
- `detected_format`
- `estimated_test_count`

LLM input SHALL NOT include source snippets by default。若 admin 明確設定 `send_source_snippets_to_llm=true`，才 MAY 傳送每個檔案經過截斷與 masking 的 snippet。

LLM 設定 SHALL 先使用既有 app-level QA AI Helper / OpenRouter 設定；不得在規格中宣稱 team-level AI provider，除非另行新增 team-level AI provider capability。

#### Scenario: LLM disabled still returns suggestions
- **WHEN** provider config 設定 `smart_scan.enable_llm=false`
- **THEN** Smart Scan SHALL 回傳 rule-based suite suggestions，且 `enrichment_source` SHALL 為 `rule_based`

#### Scenario: LLM enriches only metadata
- **WHEN** `send_source_snippets_to_llm=false`
- **THEN** prompt SHALL 只包含 ref paths、test names、formats、estimated counts
- **THEN** prompt SHALL 不包含完整 script content 或 preview snippet

#### Scenario: LLM failure falls back
- **WHEN** LLM 呼叫 timeout 或回傳非 JSON
- **THEN** 該 group SHALL 使用 rule-based name / description
- **THEN** scan run SHALL 保持 `READY`，並在 result 中記錄 enrichment warning

### Requirement: System MUST provide Smart Scan suggestion UI
Suites tab SHALL 顯示「Smart Scan」按鈕，點擊後開啟 suggestion modal。Modal SHALL 顯示 scan progress、repo contract validation、entry point summary、excluded reasons、suggested suites。

每個 suggestion SHALL 顯示：
- Suite 名稱（可 inline 編輯）
- 描述（可 inline 編輯）
- 組成 scripts
- `enrichment_source`（`rule_based` 或 `llm`）
- confidence indicator（若沒有 LLM，顯示 rule-based）
- checkbox 是否建立

#### Scenario: User reviews and modifies suggestions
- **WHEN** Smart Scan 建議 3 個 suites，使用者把其中一個 suite 名稱從 "Authentication Flows" 改為 "Login & Auth"
- **THEN** 點擊「建立」後，以修改後的名稱建立 suite

#### Scenario: User sees excluded files
- **WHEN** Smart Scan 排除 5 個檔案
- **THEN** UI SHALL 提供 excluded files 展開區，顯示 ref_path 與排除原因

#### Scenario: User sees repo contract validation
- **WHEN** Smart Scan 使用 manifest 且發現 `resources/` 存在、`config/` 不存在
- **THEN** UI SHALL 顯示 manifest 狀態、effective tests path、support paths 與 missing optional paths
- **THEN** missing optional paths SHALL be warning, not fatal

### Requirement: System MUST support incremental Smart Scan by etag and config hash
Smart Scan SHALL 以 `ref_path + ref_branch + etag + scan_config_hash` 判斷增量變更。不得依賴 Git commit time 作為唯一依據，因 GitHub contents API 不保證提供 commit time。

scan_config_hash SHALL 至少包含：
- `manifest_path`
- `manifest_etag`
- `effective_tests_path`
- `scan_depth`
- include/exclude patterns
- support paths from repo contract
- `max_scan_bytes`
- LLM prompt version
- model id（若 `enable_llm=true`）
- `send_source_snippets_to_llm`

#### Scenario: Only one script changed
- **WHEN** 上次 scan run 已記錄 20 個 entry point etags，而本次只有 `tests/auth/test_login.py` etag 改變
- **THEN** Smart Scan MAY reuse 未變更檔案的 detection result，只重新分析變更檔案與受影響 group

#### Scenario: Scan config changes
- **WHEN** admin 修改 include patterns 或 `send_source_snippets_to_llm`
- **THEN** scan_config_hash SHALL 改變，Smart Scan SHALL 不重用舊 enrichment cache

### Requirement: System MUST persist Smart Scan result and audit
Smart Scan 每次執行 SHALL 寫入 scan run result，並在完成時寫 audit。

Audit details SHALL 包含：
- `scan_run_id`
- `scanned_path`
- `manifest_found`
- `repo_contract_status`
- `entry_points_found`
- `entry_points_excluded`
- `groups_suggested`
- `groups_created`
- `llm_enabled`
- `enrichment_source_counts`
- `duration_ms`

#### Scenario: Smart Scan writes audit record
- **WHEN** 使用者執行 Smart Scan 並建立 2 個 suites
- **THEN** audit log SHALL 寫入 `AUTOMATION_SCRIPT_GROUP` + `SMART_SCAN`，details SHALL 包含 scan_run_id 與摘要數字

### Requirement: System MUST allow custom scan configuration
Provider config schema SHALL 支援 `smart_scan` 欄位：

```json
{
  "manifest_path": "tcrt-automation.yml",
  "use_manifest": true,
  "require_manifest": false,
  "enforce_repo_contract": false,
  "scan_path": "tests/",
  "scan_depth": 3,
  "include_patterns": ["test_*.py", "*_test.py", "*.spec.ts", "*.test.ts"],
  "exclude_patterns": ["*conftest*", "*/pages/*", "*/page_objects/*", "*/pom/*", "*/flows/*", "*/fixtures/*", "*/resources/*", "*/config/*", "*/utils/*"],
  "max_scan_bytes": 262144,
  "enable_llm": true,
  "llm_timeout_seconds": 10,
  "llm_max_concurrency": 3,
  "send_source_snippets_to_llm": false
}
```

Admin 可在 Settings tab 的 provider 編輯頁面調整這些設定。

#### Scenario: Admin customizes Smart Scan filters
- **WHEN** admin 將 `smart_scan.include_patterns` 設為 `["*.spec.ts"]` 且 `enable_llm=false`
- **THEN** Smart Scan SHALL 只納入符合 include pattern 的檔案，並 SHALL 使用 rule-based 分組而不呼叫 LLM

#### Scenario: Admin requires manifest
- **WHEN** admin 將 `smart_scan.require_manifest=true`
- **THEN** 沒有 valid `tcrt-automation.yml` 的 repo SHALL 無法產生 Smart Scan suggestions
- **THEN** UI SHALL 提供缺少 manifest 的錯誤與 expected structure summary

### Requirement: Changes to scan defaults / manifest schema MUST sync the tcrt-automation-pomify skill
`DEFAULT_INCLUDE_PATTERNS`、`DEFAULT_EXCLUDE_PATTERNS`、`DEFAULT_SCAN_PATH`、`STANDARD_REPO_PATHS`、`SUPPORT_PATH_TAGS` 與 `tcrt-automation.yml` 的 schema 為 TCRT 對外暴露的「可掃描契約」。任何對這些常數或 manifest schema 的變更 SHALL 在同一 change / PR 同步更新可攜 skill 與 manifest 範本，否則該 change 不得 archive。

需同步檔案：

- `tools/skills/tcrt-automation-pomify/references/tcrt-format-rules.md` 的 §1（scan root）、§2（include regex）、§3（exclusion list）、§5（standard repo layout）、§6（manifest schema）
- `tools/skills/tcrt-automation-pomify/SKILL.md` 步驟 4 的檔名規則表與步驟 7 的 manifest 段落
- `tools/skills/tcrt-automation-pomify/templates/manifest/tcrt-automation.yml`（如 schema 加欄位或改鍵名）

#### Scenario: New helper path excluded
- **WHEN** 開發者把 `support/` 加入 `DEFAULT_EXCLUDE_PATTERNS`
- **THEN** 同 PR SHALL 更新 skill references 的排除清單；如新目錄屬於 page-object family（如 `screens/`、`views/`），skill 的 POM conventions SHALL 同步增列為可選輸出位置

#### Scenario: Manifest gains a new top-level key
- **WHEN** manifest 增加 `suites_dir: <path>` 鍵
- **THEN** 同 PR SHALL 更新 `templates/manifest/tcrt-automation.yml` 加入註解掉的範例，並更新 SKILL.md 步驟 7 的描述

