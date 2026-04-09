# AGENTS.md

本檔提供本專案代理（AI coding agent）協作規範，內容以目前程式碼現況為準。

## 1) 回覆語言與工具規則

- 回覆語言：一律使用台灣繁體中文。
- 尋找檔案：必須使用 `fd`（不要用 `find`、`ls -R`）。
- 搜尋文字：必須使用 `rg`（不要用 `grep`、`ag`）。
- 程式結構分析：優先使用 `ast-grep`（不要用純文字 grep/sed 取代語法層分析）。
- 互動式選取：使用 `fzf`。
- JSON 處理：使用 `jq`。
- YAML/XML 處理：使用 `yq`。

## 2) 專案現況摘要（2026-02）

- 技術棧：`FastAPI + Jinja2 + 原生 JS/CSS + SQLite`。
- 後端主入口：`app/main.py`。
- API 路由集合：`app/api/__init__.py`。
- 前端無 Node build 流程（主要用模板 + `app/static` 資產 + CDN）。
- 主要資料庫：
  - 主庫：`test_case_repo.db`（`app/database.py`，async aiosqlite）。
  - USM 庫：`userstorymap.db`（`app/models/user_story_map_db.py`，獨立 async engine）。
  - Audit 庫：`audit.db`（由 audit 模組與初始化流程管理）。
- 設定來源：`config.yaml`（可由 `config.yaml.example` 複製）+ `.env` 環境變數。

## 3) 目錄重點

- `app/`：FastAPI 應用（API、服務、模型、模板、靜態檔）。
- `app/testsuite/`：主要 pytest 測試。
- `scripts/`：資料修補、遷移、ETL、整合腳本。
- `ai/`：RAG/ETL/CLI 工具（Qdrant + Embedding + LLM）。
- `openspec/`：規格變更流程資料（含 `project.md`、`config.yaml`、`specs/`、`changes/`）。
- `docs/`：使用與功能文件。

## 4) 本機開發標準流程

1. 建立環境並安裝：
   - `uv sync`
2. 建立設定：
   - `cp config.yaml.example config.yaml`
   - 設定 `JWT_SECRET_KEY`（必要）。
3. 啟動服務（會先做 DB 初始化/修補）：
   - `./start.sh`
4. 停止服務：
   - `./stop.sh`
5. 健康檢查：
   - `GET /health`（預設 `http://127.0.0.1:9999/health`）。

## 5) 測試與驗證

- 全套後端測試：`pytest app/testsuite -q`
- 指定測試檔：
  - `pytest app/testsuite/test_test_run_set_api.py -q`
  - `pytest app/testsuite/test_test_run_multi_set_api.py -q`
  - `pytest app/testsuite/test_test_run_item_update_without_snapshot.py -q`
- USM parser 測試：
  - `python test_usm_parser.py`

## 6) 變更守則（依現況）

- 資料庫相關變更：
  - 優先遵循 async DB 模式（`app/database.py`）。
  - 若新增欄位/索引，需同步檢視 `database_init.py` 的補欄與安全遷移邏輯。
  - 避免破壞性 schema 變更（現有初始化腳本設計偏向非破壞修補）。
- API 變更：
  - 新端點需掛到對應 router，並確保 `app/api/__init__.py` 或 `app/main.py` 有 include。
  - 有權限邏輯時，對齊 `app/auth/`、`config/permissions/*.yaml`。
- 前端變更：
  - 以「模板 + 靜態資產分離」為原則：HTML 在 `app/templates/`，JS/CSS 在 `app/static/`。
  - 優先沿用既有頁面模組切分（例如 `app/static/js/test-run-management/`）。
- i18n：
  - 新增文案需同步更新 `app/static/locales/` 對應語系檔。
- 安全：
  - 不要提交密鑰、憑證、真實 token（`config.yaml`、`.env`、`keys/` 內容需特別小心）。

## 7) OpenSpec 現況與建議

- 目前無 active change。
- 已完成並封存（archive）之主要功能（位於 `openspec/changes/archive/`）：
  - JIRA Ticket 轉 Test Case PoC 與 Helper 工作流整合（2026-02）
  - AI 輔助產生 Test Case 功能統一更新（2026-02）
  - 測試執行多集合（Multi Test Case Sets）支援（2026-02）
  - 後端 DB Async 化重構（2026-01）
  - 測試案例與執行管理介面之資產分離與重構（2026-01）
- 涉及「需求/行為/跨模組契約」的修改，建議先補齊或更新 OpenSpec 變更工件，再進入實作。

## 8) 代理工作原則

- 先最小範圍閱讀，再動手修改；避免一次大面積重構。
- 優先做精準修補（surgical fix），並補上對應測試。
- 任何會影響資料完整性的操作，先提出風險與回滾方案。
- 不要自行清理或覆寫與任務無關的既有變更。

## 9) 版本控管補充

- 目前 `.gitignore` 會忽略大部分根目錄 `*.md`，也會影響多數 OpenSpec 文檔的預設搜尋可見性。
- 若要搜尋被 ignore 的規格檔，請使用 `fd -I`、`rg -uu`（或等效「包含 ignored 檔案」參數）。
- 若要將本檔納入版本控制，需在 `.gitignore` 明確加入 `!AGENTS.md`。
