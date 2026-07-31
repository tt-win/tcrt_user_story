---
alwaysApply: true
---

# TCRT 專案補充指引

最後整理：2026-07-30

本檔只記錄 `tcrt_user_story` 這個 repo 特有的約束，通則見全域 agent 指引。衝突時以資料安全、秘密保護、破壞性動作核准與使用者最新指示優先。

**單一來源**：本檔是唯一正本。`AGENTS.md`、`.codex/AGENTS.md`、`.opencode/AGENTS.md`、`.antigravitycli/AGENTS.md`、`.qwen/QWEN.md`、`.gemini/GEMINI.md`、`.github/copilot-instructions.md`、`.cursor/rules/tcrt-project.mdc` 全部是指向本檔的 symlink——只改這裡，不要建立副本。

## 技術邊界

- 套件管理只有 `uv` + `uv.lock`。前端是 Jinja2 + Bootstrap 5 CDN + 原生 JS/CSS，`package.json` 只做 stylelint 與 inline-style guard，**不是** build pipeline。不要引入第二套 package manager 或前端 bundler，也不要把 Jinja 頁面改成需要 build 才能跑。
- DB 同時支援 SQLite / MySQL 8 / PostgreSQL 16。SQL 要跨引擎可攜，除非該路徑明確限定引擎且有測試覆蓋。
- **三組獨立 Alembic migration**，新 schema 必須放對目錄：main（`alembic.ini` + `alembic/`）、audit（`alembic_audit.ini` + `alembic_audit/`）、usm（`alembic_usm.ini` + `alembic_usm/`）。同時檢查 `database_init.py`、bootstrap 與測試 fixture。
- Runtime DB 一律走 async session + `app/db_access/` boundary，不要在 service 裡新增裸 session/query；`ALLOW_SYNC_DB_RUNTIME` 只給 migration/bootstrap，不是 runtime 解法。
- Automation Hub 的 script ↔ test case 關聯只有兩條路：marker-derived（Python `@pytest.mark.tcrt(...)`、JS/TS `// tcrt:`）與 AI suggestion acceptance。不要把人工 link write API 加回來。

## 變更流程

- 行為、API contract、schema、權限、安全、跨模組流程、使用者可見 UX 的變更，先讀 `openspec/project.md` 與相關 `openspec/specs/`，需要新契約就先建 `openspec/changes/<change>/` 工件再實作，完成前跑 `openspec validate <change> --strict`。純文字修正與小型內部重構不必開 change。
- 改 marker grammar、掃描分類、命名規則或 template set，必須同步 `tools/skills/tcrt-automation-pomify/`（`SKILL.md`、`references/tcrt-format-rules.md`、`references/framework-detection.md`、templates）。
- 同一規則若同時出現在 `docs/`、`manual/`、`openspec/`、`tools/skills/`，改行為時要一起更新。

## 秘密與本機資料

- `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 與 Jira / Lark / OpenRouter / Qdrant / GitHub / Jenkins / Allure credentials 只能走 env/config，不得硬編碼、輸出或寫進測試 snapshot。缺設定要 fail fast，不要塞不安全預設值。
- **需要本機測試帳號時，先查 repo 根目錄的 `credentials.md`**（gitignored，含 Super Admin / Admin / Viewer 三組本機帳號），不要另外向使用者索取或自行建立帳號。該檔內容只能用於操作本機執行中的 TCRT，不得輸出到回覆、log、截圖、測試 fixture 或 commit；若檔案不存在就直接說明，不要猜測。
- 不要讀取、改寫或提交 `*.db`、`config.yaml`、`.env*`、`keys/`、`credentials.md`、`generated_report/`、`attachments/`。需要碰真實或疑似真實資料前，先說明風險與回滾方案。
- 不要清理 `.opencode/`、`.antigravitycli/`、`.playwright-mcp/`、`.serena/`、`.spectra/`、`.tmp/` 等本機工具狀態。

## 前端與 i18n

- 沿用 `app/templates/base.html` 的 block 與 `app/templates/components/` 元件；HTML 留在 `app/templates/`，JS/CSS 放 `app/static/js|css/`，避免新增大型 inline script/style。
- 顏色優先用既有 design token（`var(--color-*)` 為 canonical，`var(--tr-*)` 為 alias）；`.stylelintrc.json` 會警告 selector 裡的 raw hex。
- 使用者可見文案必須同時更新 `app/static/locales/` 的 `en-US.json`、`zh-CN.json`、`zh-TW.json`——缺一個語系就是未完成。
- 動態 DOM 要走既有 i18n lifecycle：`data-i18n`、`data-i18n-placeholder`、`data-i18n-title`、`data-i18n-params`，必要時呼叫 `window.i18n.retranslate(...)`，並注意 `i18nReady` / `languageChanged`。

## 驗證（本 repo 沒有 CI，這些就是 gate）

```bash
uv run pytest app/testsuite/<target> -q     # 目標測試優先，全套為 app/testsuite
uv run ruff check .                         # 必須零診斷
npm run lint                                # stylelint + inline-style guard
node scripts/check-i18n-coverage.mjs
node --check app/static/js/<file>.js        # 改 JS 時
```

Ruff 不得用新的 `# noqa`、per-file ignore 或關閉規則掩蓋問題。DB / bootstrap 變更要用 disposable DB 或測試 fixture 驗證，不要拿本機真實 DB 當唯一驗證。
