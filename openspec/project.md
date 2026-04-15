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
├── docs/                       # 使用與功能文件
└── openspec/                   # OpenSpec 專案文件
```

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
