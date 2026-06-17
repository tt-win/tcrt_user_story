## 專案概覽

Test Case Repository Tool（TCRT）是一個以 `FastAPI + Jinja2 + 原生 JS/CSS + SQLite` 為核心的測試案例與測試執行管理系統，並已逐步整理為可支援多資料庫遷移、排程服務、MCP 讀取 API 與新版 QA AI Helper 的架構。

### 核心能力
- **測試案例管理**：Test Case Set / Section / Case 管理、附件、批次操作、預設 Set、共享過濾連結。
- **測試執行管理**：Test Run / Config / Item 管理、多 Set 範圍、執行頁與 adhoc 執行 UI。
- **AI Helper / QA AI Agent**：新版七畫面工作流、需求解析、驗證規劃、種子與 testcase 生成、採用率與遙測統計。
- **團隊與系統管理**：權限、稽核、排程服務管理、MCP machine token 管理。
- **資料與整合**：Jira、Lark、Qdrant / embedding / LLM、HTML 報告輸出、跨資料庫遷移腳本。

### 目前技術架構
- **後端入口**：`app/main.py`
- **API 組裝**：`app/api/__init__.py`
- **主要資料層**：
  - 主庫 async runtime：`app/database.py`
  - 顯式資料存取邊界：`app/db_access/`
  - USM 專屬 DB：`app/models/user_story_map_db.py`
  - Audit DB：由 audit / migration 流程管理
- **前端**：Jinja2 模板、`app/static` 靜態資產、Bootstrap 5 CDN、既有 TCRT/TestRail 設計 token
- **AI Helper 實作**：
  - API：`app/api/qa_ai_helper.py`
  - 服務：`app/services/qa_ai_helper_service.py`
  - 需求解析與驗證：`app/services/test_case_helper/`
  - 團隊統計：`app/api/team_statistics_qa_ai_helper.py`
- **排程服務**：`app/services/scheduler.py`
- **MCP 讀取 API / 驗證**：`app/api/mcp.py`、`app/auth/mcp_dependencies.py`
- **報告儲存**：`app/services/html_report_service.py`，並由 `reports.root_dir` 控制輸出根目錄

### 專案結構

```text
tcrt_user_story/
├── app/
│   ├── api/                    # FastAPI 路由
│   ├── auth/                   # JWT / MCP 驗證與授權
│   ├── db_access/              # 資料存取邊界與 guardrails
│   ├── models/                 # ORM / schema 定義
│   ├── services/               # 業務邏輯、scheduler、report、AI helper
│   ├── static/                 # CSS / JS / locales / samples
│   ├── templates/              # Jinja2 頁面
│   └── testsuite/              # pytest 測試
├── ai/                         # ETL / RAG / CLI 工具
├── scripts/                    # migration / repair / ETL / maintenance 腳本
├── tools/                      # 對外工具（sample repo、可攜 AI agent skill）
│   ├── sample_automation_repo/         # TCRT Automation Hub 連接示範用的範例 git repo
│   └── skills/                         # 可攜 AI agent skill bundle（跨 IDE / Agent 可用）
│       └── tcrt-automation-pomify/     # 把使用者 script → POM + TCRT 格式
├── docs/                       # 使用與功能文件
└── openspec/                   # OpenSpec 專案文件
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

目前主規格除原有測試管理、資料庫與 UI 能力外，已涵蓋下列現況能力：

- `database-async`
- `database-access-boundaries`
- `database-migration`
- `database-cutover-readiness`
- `database-operations`
- `system-bootstrap`
- `test-case-management-ui`
- `test-run-management-ui`
- `test-run-execution-ui`
- `test-run-multi-set-integrity`
- `adhoc-test-run-execution-ui`
- `team-default-test-case-set`
- `generated-report-storage`
- `scheduled-service-management`
- `mcp-machine-auth`
- `mcp-read-api`
- `jira-ticket-to-test-case-poc`
- `helper-guided-intake`
- `helper-structured-requirement-schema`
- `helper-requirement-completeness-warning`
- `helper-deterministic-seed-planning`
- `helper-final-generation-contract`
- `helper-prompt-file-loading`
- `helper-session-management`
- `helper-team-analytics`
- `test-case-helper-config-toggle`
- 以及既有 `template-asset-separation`、`ui-design-system`、`etl-all-teams`、`test-case-editor-ai-assist` 等能力

#### Active changes（`openspec/changes/`）

依目前 `openspec list --json` 狀態：

- 已完成但尚未封存：
  - `rewrite-qa-ai-agent`
  - `manage-scheduled-services`
  - `manage-team-default-test-case-set`
  - `complete-db-access-abstraction`
  - `complete-cross-db-migration-readiness`
  - `refactor-database-init`
  - `add-mcp-read-machine-auth`
  - `add-test-case-helper-config-toggle`
  - `add-qa-helper-team-analytics-tab`
  - `add-test-case-helper-session-management`
- 原本標為進行中，但實作已存在且需要同步文件：
  - `configure-generated-report-root-dir`

### 開發與實作約定
- **程式風格**：Python 採 `snake_case`、型別提示；Pydantic / ORM 依既有模組分層。
- **資料庫策略**：
  - Web runtime 優先使用 async session。
  - 新增資料欄位或資料表時，需同時檢查 `database_init.py`、Alembic / migration 流程與跨庫腳本。
  - 不做破壞性自動修補。
- **前端策略**：
  - HTML 在 `app/templates/`
  - JS / CSS / locales 在 `app/static/`
  - 動態文案需接既有 i18n lifecycle
- **安全與設定**：
  - 主要設定來源為 `config.yaml` + `.env`
  - 敏感資訊不可進版控
  - MCP machine token 與 team scope 需受權限控制與 audit 記錄

### 測試與驗證
- 全套後端測試：`pytest app/testsuite -q`
- 資料庫 / migration / scheduler / MCP / report storage / QA helper 均已有 focused tests
- 新 spec 或 change 同步後，應優先補齊對應測試檔與行為驗證

### OpenSpec 維護原則
- 主規格反映**目前已存在或已接受**的系統能力。
- `changes/` 保留變更脈絡與未封存工件；完成實作後應同步主 spec，再視情況封存。
- 若 `tasks.md` 與實作現況不一致，應先修正文檔狀態，再進行 archive / sync。
- **Automation Hub 對外 skill 同步義務**：對 `openspec/specs/automation-hub-*` 任一規格的命名規則、`scan_path`、`include_patterns`、`exclude_patterns`、`infer_script_format` mapping 或對應實作（`app/services/automation/scan_filters.py`、`app/services/automation/providers/github_storage.py`）做變更時，**必須**在同一個 change / PR 中同步更新 `tools/skills/tcrt-automation-pomify/`（SKILL.md、references/、templates/ 對應檔案），否則該 change 不得 archive。
  - 對應 change 的 `tasks.md` SHALL 包含一條「同步更新 tcrt-automation-pomify skill」的 task，並在 PR 描述列出實際改了哪些 skill 檔案。
  - 若該次變更純粹是 TCRT 內部行為（不影響 QA 寫 script 的方式 / TCRT 對外看到的格式），可在 PR 描述明確 opt-out 並附理由，否則同步義務預設成立。
- **Automation Hub workflow 文件同步義務**：對「端到端 workflow 文件」所列任一行為（provider 設定流程、腳本掃描 / Suite→CI job、marker、Test Run Set 自動化執行、webhook / Jenkins / Allure 整合）的變更，**必須**在同一個 change / PR 中同步更新 `docs/automation-workflow.md`，且對應 change 的 `tasks.md` SHALL 包含一條「同步更新 automation-workflow 文件」task。純 TCRT 內部、不影響對外 workflow 的變更可在 PR 描述 opt-out 並附理由。
