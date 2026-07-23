## 專案概覽

Test Case Repository Tool（TCRT）是一個以 `FastAPI + Jinja2 + 原生 JS/CSS + SQLite` 為核心的測試案例與測試執行管理系統，並已逐步整理為可支援多資料庫引擎（SQLite / MySQL / PostgreSQL）、多副本部署、排程服務、MCP 讀取 API、Automation Hub 端到端自動化測試整合，與新版 QA AI Helper 的架構。

### 核心能力
- **測試案例管理**：Test Case Set / Section / Case 管理、附件、批次操作、預設 Set、共享過濾連結、CSV 匯出。
- **測試執行管理**：Test Run / Config / Item 管理、多 Set 範圍、執行頁與 adhoc 執行 UI、Test Run Set 觸發自動化。
- **Automation Hub**：端到端自動化測試整合——Storage Provider（GitHub / Local Git）、CI Provider（Jenkins）、Result Provider（Allure）、腳本自動掃描與快取、marker-derived linkage、coverage 統計、環境變數管理（AES-256-GCM 加密）、webhook 整合、Suite CI Job 觸發與狀態回流。
- **AI Helper / QA AI Agent**：新版七畫面工作流、MAGI 多模型檢查、需求解析、驗證規劃、種子與 testcase 生成、採用率與遙測統計、session 管理。
- **團隊與系統管理**：權限（Casbin RBAC）、稽核（audit DB）、排程服務管理、team-owned app token（`/api/app/*`，涵蓋 test case / test run 完整讀寫與 automation trigger；取代原本 MCP 專用 machine token 定位，`/api/mcp/*` 保留 read-only 相容期）、組織層 Automation Hub 入口開關。
- **資料與整合**：Jira、Lark、LLM、HTML 報告輸出、跨資料庫遷移腳本（Alembic 三庫）。
- **容器化部署**：Dockerfile、docker-compose（app / MySQL / PostgreSQL）、RSA 簽章金鑰持久化、leader 選舉、bootstrap lock。

### 目前技術架構
- **後端入口**：`app/main.py`
- **API 組裝**：`app/api/__init__.py`（38+ 個 router，含 11 個 Automation Hub 路由）
- **主要資料層**：
  - 主庫 async runtime：`app/database.py`
  - 顯式資料存取邊界：`app/db_access/`（core / coordinator / guardrails / audit / usm / main）
  - USM 專屬 DB：`app/models/user_story_map_db.py`
  - Audit DB：`app/audit/`（獨立模組，含 audit_service / database / models）
  - Alembic 遷移：`alembic/`（主庫）、`alembic_audit/`（audit 庫）、`alembic_usm/`（USM 庫）
  - 多引擎支援：SQLite / MySQL 8 / PostgreSQL 16（設定範例：`config.mysql.yaml`、`config.postgresql.yaml.example`、`config.sqlite.yaml.example`）
- **前端**：Jinja2 模板、`app/static` 靜態資產、Bootstrap 5 CDN、Jinja 組件庫（`app/templates/components/`）、stylelint 護欄
- **AI Helper 實作**：
  - API：`app/api/qa_ai_helper.py`
  - 服務：`app/services/qa_ai_helper_service.py`（含 planner / preclean / prompt / runtime / metrics / llm_service）
  - 需求解析與驗證：`app/services/test_case_helper/`
  - 團隊統計：`app/api/team_statistics_qa_ai_helper.py`
- **Automation Hub 實作**：
  - 服務：`app/services/automation/`（provider_registry / script_service / script_group_service / coverage_service / environment_service / linkage_service / run_service / webhook_service / allure_proxy / background / marker_sync / scan_filters / ai_link_suggest_service）
  - Provider：`app/services/automation/providers/`（github_storage / local_git_storage / jenkins_ci / allure_result）
  - API：`app/api/automation_*.py`（providers / scripts / links / script_groups / coverage / environments / webhooks / result）
- **排程服務**：`app/services/scheduler.py`
- **MCP 讀取 API / 驗證（相容期）**：`app/api/mcp.py`、`app/auth/mcp_dependencies.py`
- **App Token 外部 API（canonical）**：`app/api/app_tokens.py`（管理）、`app/api/app_read.py`（read）、`app/api/app_test_cases.py`、`app/api/app_test_runs.py`、`app/api/app_automation.py`（mutation / trigger）、`app/auth/app_token_dependencies.py`、`app/models/app_token.py`；詳見 `docs/app_token_auth.md` 與 `openspec/changes/add-team-app-token-apis/`
- **報告儲存**：`app/services/html_report_service.py`，並由 `reports.root_dir` 控制輸出根目錄
- **容器化**：`Dockerfile`、`docker-compose.app.yml`、`docker-compose.mysql.yml`、`docker-compose.postgres.yml`、`docker/app-entrypoint.sh`
- **前端品質守衛**：stylelint（`.stylelintrc.json`）、i18n coverage linter（`scripts/check-i18n-coverage.mjs`）、inline style checker（`scripts/check-inline-styles.mjs`）

### 專案結構

```text
tcrt_user_story/
├── app/
│   ├── api/                    # FastAPI 路由（43 個檔案，38+ 個 router）
│   ├── auth/                   # JWT / MCP 驗證與授權（含 Casbin RBAC）
│   ├── audit/                  # 審計日誌獨立模組（audit_service / database / models）
│   ├── db_access/              # 資料存取邊界與 guardrails（core / coordinator / audit / usm）
│   ├── middlewares/            # 中介層（audit_middleware）
│   ├── models/                 # ORM / schema 定義（24 個檔案，含 8 個 automation 模型）
│   ├── services/               # 業務邏輯（39 個項目）
│   │   ├── automation/         # Automation Hub 服務（19 個項目）
│   │   └── test_case_helper/   # Test Case Helper 服務（7 個項目）
│   ├── static/                 # CSS / JS / locales / samples
│   │   └── js/
│   │       ├── automation-hub/ # Automation Hub 前端模組（5 子目錄）
│   │       ├── test-case-management/
│   │       ├── test-run-management/
│   │       ├── test-run-execution/
│   │       ├── qa-ai-helper/
│   │       └── team-management/
│   ├── templates/              # Jinja2 頁面
│   │   ├── components/         # Jinja 組件庫（button / data_table / modal / toolbar / status_badge）
│   │   └── _partials/          # 局部模板
│   └── testsuite/              # pytest 測試（73 個檔案）
├── ai/                         # ETL / RAG / CLI 工具
├── alembic/                    # Alembic 遷移（主庫）
├── alembic_audit/              # Alembic 遷移（audit 庫）
├── alembic_usm/                # Alembic 遷移（USM 庫）
├── config/                     # 設定檔（db_access_policy / permissions）
├── docker/                     # 容器化腳本（app-entrypoint / mysql-init / postgres-init）
├── docs/                       # 使用與功能文件（24 個項目）
├── manual/                     # 使用者手冊（9 章）
├── openspec/                   # OpenSpec 專案文件
├── prompts/                    # AI prompt 模板（ac_inspection / jira_testcase_helper）
├── scripts/                    # migration / repair / ETL / maintenance 腳本（22 個項目）
└── tools/                      # 對外工具（sample repo、可攜 AI agent skill）
    ├── sample_automation_repo/         # TCRT Automation Hub 連接示範用的範例 git repo
    └── skills/                         # 可攜 AI agent skill bundle（跨 IDE / Agent 可用）
        └── tcrt-automation-pomify/     # 把使用者 script → POM + TCRT 格式
```

#### Automation Hub 工具鏈

`tools/skills/tcrt-automation-pomify/` 是 TCRT 對外提供的可攜 AI agent skill，給使用 TCRT 的 QA / SDET 在他們**自家 automation repo** 的 IDE / agent（Claude Code、Cursor、Cline、Continue 等）中載入後，把寫好的 Playwright / Selenium 腳本一鍵整理成：

1. **Page Object Model** 結構（`pages/` 目錄、locator 與 action 分離、無 assertion）
2. **TCRT Automation Hub 規範格式**（檔名匹配掃描的 include glob、page object 放在自動排除的目錄、test function 用 `test_` 前綴）

這個 skill 的內容**直接受 `automation-hub-*` 兩份主規格約束**：

- `automation-hub-script-management` — 檔案分類與命名規則（`PLAYWRIGHT_PY_ASYNC` / `PYTEST` / `PLAYWRIGHT_JS`）、掃描的 `DEFAULT_INCLUDE_PATTERNS` / `DEFAULT_EXCLUDE_PATTERNS`（`scan_filters.py`）
- `automation-hub-provider-framework` — `infer_script_format` 的副檔名 mapping

任一 spec 中的命名規則、掃描路徑、排除規則、`script_format` 推斷邏輯有變動時，**必須**同步更新 skill 內以下檔案，否則 skill 會發出與系統不一致的指引：

- `tools/skills/tcrt-automation-pomify/SKILL.md`（步驟 2 / 步驟 4 對照表）
- `tools/skills/tcrt-automation-pomify/references/tcrt-format-rules.md`（regex 與排除路徑的逐字摘錄）
- `tools/skills/tcrt-automation-pomify/references/framework-detection.md`（template set 對照表）
- `tools/skills/tcrt-automation-pomify/templates/`（如新增支援的 framework 變體，須加新 template 子目錄並回頭更新對照表）

#### Marker-derived linkage

Automation Hub 的 script ↔ test case link 現況已收斂為 **marker-derived source of truth**：

- TCRT 不再提供人工 link 建立 UI / write API。
- Python 測試以 `@pytest.mark.tcrt(...)` 宣告 manual test case 對應。
- JS/TS 測試以緊鄰 test 宣告的 `// tcrt:` 註解提供對應資訊。
- `automation_script_case_links` 的自動同步列以 `created_by="marker-sync"` 標示；AI 建議接受後的列以 `ai-suggest:<id>` 標示來源。
- `PRIMARY` / `COVERS` / `REFERENCES` 三種 link_type 中，coverage 統計只計 `PRIMARY` 與 `COVERS`。

因此，任何會影響 marker grammar、marker 解析、`created_by` sentinel、或 link_type 行為的變更，都應同步更新：

- `openspec/specs/automation-hub-script-management/spec.md`
- `tools/skills/tcrt-automation-pomify/SKILL.md`
- `tools/skills/tcrt-automation-pomify/references/tcrt-format-rules.md`

#### 端到端 workflow 文件

`docs/automation-workflow.md` 是 TCRT 自動化測試方案的端到端流程文件，涵蓋：用工具（`ai_steps_recorder` / `element_locator_generator` / `tcrt-automation-pomify`）撰寫腳本 → 設定 Storage(GitHub) / CI(Jenkins) / Result(Allure) provider → Rescan + 建 Suite → Test Run Set 觸發執行 → 狀態與 Allure 報告回流。

此文件橫跨多份 `automation-hub-*` 規格與 provider / Test Run Set 行為，列為**追蹤修改文件**；下列任一項變動時必須同步更新（見「OpenSpec 維護原則」的 workflow 文件同步義務）：

- provider 型別或設定流程（`storage:*` / `ci:*` / `result:*`、憑證欄位、`public_base_url` 與 `TCRT_WEBHOOK_URL` 烤入）
- 腳本掃描規則（include/exclude）、`script_format` 推斷、建立 Suite 時自動產生 CI job 的行為
- marker grammar 或 marker-derived linkage 行為
- Test Run Set 觸發自動化（`automation_suite_ids`、Run as Automation）與 run 狀態流轉
- inbound / outbound webhook 路徑、Jenkins 整合、Allure proxy 報告回收流程

### OpenSpec 現況

#### 主規格（`openspec/specs/`）

目前主規格共 **45 個**，依領域分類如下：

**Automation Hub（6 個）：**
- `automation-hub-mcp-read`
- `automation-hub-provider-framework`
- `automation-hub-run-orchestration`
- `automation-hub-script-management`
- `automation-hub-webhook-integration`
- `automation-hub-entry-toggle`（由已封存 change 新增）

**Database（5 個）：**
- `database-async`
- `database-access-boundaries`
- `database-cutover-readiness`
- `database-migration`
- `database-operations`

**QA AI Helper（13 個）：**
- `helper-guided-intake`
- `helper-magi-inspection`
- `helper-ai-progress-animation`
- `helper-requirement-completeness-warning`
- `helper-requirement-editing`
- `helper-structured-requirement-schema`
- `helper-deterministic-seed-planning`
- `helper-plan-section-crud`
- `helper-final-generation-contract`
- `helper-prompt-file-loading`
- `helper-team-prompt-profiles`（退役：自訂風格 runtime 不再暴露）
- `helper-session-management`
- `helper-team-analytics`

**Test Case / Test Run UI（8 個）：**
- `test-case-management-ui`
- `test-case-management`
- `test-case-editor-ai-assist`
- `test-case-helper-config-toggle`
- `test-run-management-ui`
- `test-run-execution-ui`
- `test-run-multi-set-integrity`
- `adhoc-test-run-execution-ui`

**Infrastructure（5 個）：**
- `system-bootstrap`
- `scheduled-service-management`
- `generated-report-storage`
- `background-service-scaling`
- `container-deployment`

**MCP / Auth（3 個）：**
- `mcp-machine-auth`
- `mcp-read-api`
- `mcp-machine-token-management`（由已封存 change 新增）

**UI / Design（4 個）：**
- `ui-design-system`
- `template-asset-separation`
- `ai-assist-ui-exposure-control`
- `team-badge-nav-dropdown`（由已封存 change 新增）

**團隊與組織管理 UI（2 個，由 `redesign-team-settings-information-architecture` change 新增）：**
- `team-management-console`：縮小後的 `/team-management` 頁面契約（僅 team 資料 CRUD + App Token 入口）
- `organization-management-console`：獨立的「組織與系統設定」頁面（`/organization-management`），統整人員管理／組織同步／Service 管理／MCP Token／組織自動化基礎設施／AI 助手設定六個分頁

**其他（4 個）：**
- `etl-all-teams`
- `jira-ticket-to-test-case-poc`
- `team-default-test-case-set`
- `automation-environment-configs`（由已封存 change 新增）

#### Active changes（`openspec/changes/`）

依目前狀態：

- **進行中（早期）**：
  - `achieve-full-i18n-coverage` — 全站三語系翻譯覆蓋率推到 100%（linter 已建好，後端外部化與前端抽出未開始）
- **進行中（中期）**：
  - `unify-ui-design-tokens-and-components` — UI design token 收斂與 Jinja macro 元件庫（P0 止血完成，P1/P2 未開始）
  - `redesign-team-settings-information-architecture` — 拆分 `/team-management` 的組織層分頁至新頁面 `/organization-management`（實作完成、經紅隊審查修正，待 archive）
  - `move-assistant-admin-into-organization-tab` — 將原獨立頁面 `/assistant-admin` 併為 `/organization-management` 第 6 個分頁，並修正 `assistantAdmin.*` 三語系文案大小寫（實作完成，待 archive）
- **未開始（僅完成規劃）**：
  - `consolidate-agent-onboarding-docs` — 整併散落的啟動/設定文件
  - `make-schema-engine-portable` — DB schema 跨引擎可攜（SQLite / MySQL / PostgreSQL）
  - `optimize-core-hot-paths` — 核心熱路徑效能優化
  - `split-suite-ci-jobs-by-trigger` — Suite CI Job 依觸發源拆分
- **僅骨架（可能棄用）**：
  - `qa-ai-helper-team-prompt-presets` — 僅有 `.openspec.yaml`，缺所有工件

#### 已封存之主要功能（`openspec/changes/archive/`，共 61 個）

近期封存（2026-06）：
- Automation Hub 環境變數管理（`manage-automation-environment-configs`）
- Automation Hub 入口開關（`add-automation-hub-entry-toggle`）
- MCP API 暴露 Script Groups（`expose-automation-script-groups-in-mcp-api`）
- MCP 機器 Token 管理（`manage-mcp-machine-tokens`）
- 團隊徽章導航選單（`team-badge-navigation-menu`）
- 統一 Header 操作按鈕（`unify-header-action-buttons`）
- 容器部署加固（`harden-container-deployment`）
- Suite CI Job 依觸發源拆分 webhook（`add-webhook-suite-trigger`）
- 移除手動 automation link UI（`remove-manual-automation-link-ui-and-write-api`）
- Automation test markers（`add-automation-test-markers-and-test-view`）
- Test Run Set automation suite 管理（`improve-test-run-set-automation-suite-management`）
- Provider scope 簡化（`simplify-provider-scope-with-org-level-ci-result`）
- Automation Hub 核心（`add-automation-hub`）
- 自動化執行移轉至 Test Run Set（`move-automation-execution-to-test-run-set`）
- Run history 移轉至 Test Run Set（`move-run-history-to-test-run-set`）

### 開發與實作約定
- **程式風格**：Python 採 `snake_case`、型別提示；Pydantic / ORM 依既有模組分層。
- **資料庫策略**：
  - Web runtime 優先使用 async session。
  - 新增資料欄位或資料表時，需同時檢查 `database_init.py`、Alembic migration 流程（三庫：`alembic/`、`alembic_audit/`、`alembic_usm/`）與跨庫腳本。
  - 不做破壞性自動修補。
  - 跨引擎相容性：新增 SQL 需考慮 SQLite / MySQL / PostgreSQL 差異（參考 `app/db_types.py`、`app/db_url.py`）。
- **前端策略**：
  - HTML 在 `app/templates/`
  - JS / CSS / locales 在 `app/static/`
  - 動態文案需接既有 i18n lifecycle
  - 優先使用 Jinja 組件庫（`app/templates/components/`）
  - 新增 CSS 需通過 stylelint 護欄
- **安全與設定**：
  - 主要設定來源為 `config.yaml` + `.env`
  - 敏感資訊不可進版控
  - MCP machine token 與 team scope 需受權限控制與 audit 記錄
  - Automation 環境變數使用 AES-256-GCM 加密儲存

### 測試與驗證
- 全套後端測試：`pytest app/testsuite -q`（73 個測試檔案）
- 資料庫 / migration / scheduler / MCP / report storage / QA helper / automation hub 均已有 focused tests
- 前端品質守衛：
  - `node scripts/check-i18n-coverage.mjs` — i18n 覆蓋率檢查
  - `node scripts/check-inline-styles.mjs` — inline style 檢查
  - stylelint — CSS 規範檢查
- 新 spec 或 change 同步後，應優先補齊對應測試檔與行為驗證

### OpenSpec 維護原則
- 主規格反映**目前已存在或已接受**的系統能力。
- `changes/` 保留變更脈絡與未封存工件；完成實作後應同步主 spec，再視情況封存。
- 若 `tasks.md` 與實作現況不一致，應先修正文檔狀態，再進行 archive / sync。
- **Automation Hub 對外 skill 同步義務**：對 `openspec/specs/automation-hub-*` 任一規格的命名規則、`scan_path`、`include_patterns`、`exclude_patterns`、`infer_script_format` mapping 或對應實作（`app/services/automation/scan_filters.py`、`app/services/automation/providers/github_storage.py`）做變更時，**必須**在同一個 change / PR 中同步更新 `tools/skills/tcrt-automation-pomify/`（SKILL.md、references/、templates/ 對應檔案），否則該 change 不得 archive。
  - 對應 change 的 `tasks.md` SHALL 包含一條「同步更新 tcrt-automation-pomify skill」的 task，並在 PR 描述列出實際改了哪些 skill 檔案。
  - 若該次變更純粹是 TCRT 內部行為（不影響 QA 寫 script 的方式 / TCRT 對外看到的格式），可在 PR 描述明確 opt-out 並附理由，否則同步義務預設成立。
- **Automation Hub workflow 文件同步義務**：對「端到端 workflow 文件」所列任一行為（provider 設定流程、腳本掃描 / Suite→CI job、marker、Test Run Set 自動化執行、webhook / Jenkins / Allure 整合）的變更，**必須**在同一個 change / PR 中同步更新 `docs/automation-workflow.md`，且對應 change 的 `tasks.md` SHALL 包含一條「同步更新 automation-workflow 文件」task。純 TCRT 內部、不影響對外 workflow 的變更可在 PR 描述 opt-out 並附理由。
