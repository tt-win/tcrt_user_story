# TCRT Project Agent Supplement

最後整理日期：2026-07-07

本檔是 `tcrt_user_story` 的專案層補充。先遵守全域 `AGENTS.md` / `CLAUDE.md` / `QWEN.md` / `GEMINI.md` / Copilot 類指令；本檔只記錄這個 repo 的特殊約束。若有衝突，資料安全、秘密保護、破壞性動作核准與使用者最新指示優先。

## 專案輪廓

- TCRT 是測試案例、Test Run、User Story Map、Automation Hub、QA AI Helper 與 Jira/Lark/LLM 整合的 FastAPI 系統。
- 後端主要是 Python 3.10+、FastAPI、Pydantic 2、SQLAlchemy 2 async、Alembic、Casbin、pytest；套件管理以 `uv` 與 `uv.lock` 為準。
- 前端是 Jinja2 模板、Bootstrap 5 CDN、原生 JS/CSS 與 `app/static/locales/` i18n；`package.json` 只提供 stylelint / template guard，不是前端 build pipeline。
- 資料庫支援 SQLite、本機/容器 MySQL 8、PostgreSQL 16。不要寫只在單一引擎可用的 SQL，除非該路徑明確限定引擎並有測試。

## 重要入口

- App 啟動：`app/main.py`
- Router 組裝：`app/api/__init__.py`
- API：`app/api/`
- 服務層：`app/services/`
- ORM / schema：`app/models/`
- 顯式 DB access boundary：`app/db_access/`
- Audit 模組：`app/audit/`
- 模板與元件：`app/templates/`、`app/templates/components/`
- 靜態資產與三語系：`app/static/js/`、`app/static/css/`、`app/static/locales/`
- 測試：`app/testsuite/`
- OpenSpec：`openspec/project.md`、`openspec/specs/`、`openspec/changes/`
- 對外 automation skill：`tools/skills/tcrt-automation-pomify/`

## 變更流程補充

- 行為、API contract、schema、權限、安全、跨模組流程、使用者可見 UX 的變更，先檢查 `openspec/project.md` 與相關 `openspec/specs/`；若需要新契約，先建立或更新 `openspec/changes/<change>/` 工件再實作。
- 純文字修正、小型內部重構或只補 agent 文件時，不必硬開 OpenSpec change，但仍要確認沒有打破現有 spec 描述。
- 修改 Automation Hub、QA AI Helper、Test Run、i18n、DB boundary 等共享行為時，先找既有測試與 spec；不要只靠頁面手測。
- 如果同一規則同時存在於 `docs/`、`manual/`、`openspec/`、`tools/skills/`，修改行為時要同步更新相關文件，不要只更新程式碼。

## 資料庫與資料安全

- 本專案有三組 Alembic migration：
  - main：`alembic.ini` + `alembic/`
  - audit：`alembic_audit.ini` + `alembic_audit/`
  - usm：`alembic_usm.ini` + `alembic_usm/`
- 新增/修改 schema 必須放到正確 migration 目錄，並檢查 `database_init.py`、bootstrap、測試 fixture 與跨引擎相容性。
- Web runtime 優先使用 async session 與 `app/db_access/` boundary；同步 DB engine 只應用於 migration/bootstrap 等明確場景，`ALLOW_SYNC_DB_RUNTIME` 不可當成一般 runtime 解法。
- 不要隨意讀取、改寫或提交本機 `*.db`、`*.sqlite3`、`generated_report/`、`attachments/`、`keys/`、`config.yaml`、`.env*`。需要碰真實或疑似真實資料時，先說明風險與回滾方案。
- `AUTOMATION_PROVIDER_ENCRYPTION_KEY`、Jira/Lark/OpenRouter/GitHub/Jenkins/Allure credentials 都只能走 env/config；不要硬編碼、輸出或寫進測試 snapshot。

## 前端與 i18n

- 新頁面或改版優先沿用 `app/templates/base.html` 的 block、`app/templates/components/` 元件、既有 `btn-*` / table / modal / toolbar 結構。
- HTML 留在 `app/templates/`，JS/CSS 放在 `app/static/js/`、`app/static/css/`；避免新增大型 inline script/style。
- CSS 優先用現有 design token，例如 `var(--tr-*)` 或 `var(--color-*)`；`.stylelintrc.json` 會警告 selector 裡的 raw hex。
- 所有使用者可見新文案同步更新 `app/static/locales/en-US.json`、`zh-CN.json`、`zh-TW.json`。
- 動態 DOM 要使用既有 i18n lifecycle：`data-i18n`、`data-i18n-placeholder`、`data-i18n-title`、`data-i18n-params`，必要時呼叫 `window.i18n.retranslate(...)`，並注意 `i18nReady` / `languageChanged`。

## Automation Hub 特別約束

- Provider credentials 與 environment variables 可能被 AES-256-GCM 加密保存；不要繞過 service 或直接明文落檔。
- script 掃描、`script_format` 推斷、include/exclude glob、`tcrt-automation.yml`、Suite CI job 命名、webhook、Allure/Jenkins/GitHub provider 行為，都要對照 `openspec/specs/automation-hub-*`。
- script 與 manual test case 的關聯以 marker-derived link 為主要真相來源：Python `@pytest.mark.tcrt(...)`，JS/TS `// tcrt:`；`created_by="marker-sync"`、`ai-suggest:<id>`、`PRIMARY` / `COVERS` / `REFERENCES` 行為不可任意改。
- 任何 marker grammar、掃描分類、命名規則或 template set 改動，必須同步更新 `tools/skills/tcrt-automation-pomify/`，尤其 `SKILL.md`、`references/tcrt-format-rules.md`、`references/framework-detection.md` 與相關 templates。

## QA AI Helper 與整合

- QA AI Helper 跨 API、service、planner、prompt、runtime、metrics 與 team analytics；修改前先查 `app/services/qa_ai_helper*`、`app/services/test_case_helper/` 與對應 tests。
- OpenRouter/LLM 設定只能透過現有 config/env 路徑。缺少必要設定時應 fail fast 或回報待設定，不要塞不安全預設值。
- Jira/Lark/MCP 相關改動要檢查權限、audit、team scope 與 token/machine auth 測試。

## 驗證指令

- 後端目標測試優先：`uv run pytest app/testsuite/<target> -q`
- 後端全套：`uv run pytest app/testsuite -q`
- Ruff：`uv run ruff check app scripts database_init.py`
- 前端 lint：`npm run lint`
- i18n coverage：`node scripts/check-i18n-coverage.mjs`
- 修改 JS 時至少跑對應 `node --check app/static/js/<file>.js`
- OpenSpec 變更完成前跑 `openspec validate <change> --strict`
- DB/bootstrap 相關變更需用 disposable DB 或測試 fixture 驗證；不要拿本機真實 DB 當唯一驗證。

## 不要踩的坑

- 不要引入第二套 package manager 或前端 bundler。
- 不要把 Jinja 頁面改成需要 build 才能跑的前端架構。
- 不要直接繞過 `app/db_access/` 在任意服務中新增裸 session/query pattern。
- 不要把 Automation Hub 的人工 link write API 加回來；現況已收斂到 marker-derived 與 AI suggestion acceptance 流程。
- 不要清理 `.opencode/`、`.antigravitycli/`、`.playwright-mcp/`、`.serena/`、`.spectra/`、`.tmp/` 等本機工具狀態，除非任務明確要求。
