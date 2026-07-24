## Why

目前系統以多種形式使用知識圖譜 / RAG（AI 助手的 `search_knowledge`、`analyze_knowledge_impact` 工具；admin 的 `/api/knowledge/search`、`/api/knowledge/impact`；未來改版的 QA AI Helper grounding），但**沒有任何地方留下這些查詢的過程與結果**。當檢索退化（斷路器跳脫、併發滿載、graph 逾時）或回傳品質異常時，維運者無從事後回溯「查了什麼、命中什麼、為何降級」。本變更提供一個 Super Admin 可檢視的知識圖譜查詢記錄，作為 RAG 的可觀測性基礎。

## What Changes

- 於 audit DB 新增專用表 `knowledge_query_logs`，持久化每一次知識圖譜查詢的**中繼資料＋過程診斷＋精簡結果摘要**（不含結果全文，避免敏感測試資料落地）。
- 在三個公開查詢入口埋點，涵蓋「任何形式」的知識圖譜使用：
  - 業務層 `KnowledgeRetrievalService.search_knowledge()` / `.analyze_impact()`（AI 助手與未來 QA AI Helper 皆經此）——**in-method** 記錄，掌握 dual-route、斷路器、逾時、degraded 等過程。
  - admin `/api/knowledge/search`、`/api/knowledge/impact`（直呼 `HybridSearchService`，不經業務層）——**端點各自**記錄，**不改道、不變更其 request/response 契約**。
- 新增 fail-safe、批次緩衝的寫入服務：查詢路徑只做 O(1) append，永不因記錄失敗而阻斷或降級查詢；含跨引擎可攜的保留期清理與關機 flush。
- 新增唯讀 API `GET /api/admin/knowledge-query-logs`（＋單筆詳情），`require_super_admin` 保護，支援分頁與篩選。
- `/system-logs` 頁面新增一個**獨立分頁**「知識圖譜查詢記錄」，供 Super Admin 分頁/篩選檢視；三語系文案。
- **未來 QA AI Helper** 接上 RAG 時 MUST 走 `build_rag_context_for_qa_helper`（會被記錄），MUST NOT 直呼 `HybridSearchService.context_for_qa_helper()`（否則繞過記錄）。

非目標（Out of scope）：
- 不改變任何既有知識圖譜查詢的行為、參數或回傳契約（純觀測性疊加）。
- 不記錄結果全文 snippet；不涵蓋 `/api/knowledge/health`、backfill/寫入路徑（非查詢）。
- 不修補 `system-log-viewer` spec 既有的分頁清單缺漏（該 spec 未列出先前已上線的 Knowledge Graph health 分頁，屬 `add-knowledge-graph-integration` 遺留、既有債，不在本變更範圍）。

## Capabilities

### New Capabilities
- `knowledge-query-log`: 知識圖譜/RAG 查詢的觀測性記錄能力——涵蓋範圍與埋點契約、`knowledge_query_logs` 儲存模型與資料安全、fail-safe 寫入與保留清理、Super Admin 唯讀查詢 API，以及 `/system-logs` 下的查詢記錄分頁 UI。

### Modified Capabilities
（無。本變更為觀測性疊加，不改變既有 capability 的既定行為或契約；`system-log-viewer` 的頁面 shell 與授權模型維持不變，新分頁沿用其既有 shell 與 `require_super_admin` 資料保護模式。）

## Impact

- **資料庫（audit DB）**：新增表 `knowledge_query_logs` 與一支 `alembic_audit/` migration（`down_revision` 必須接當前單一 head `77b4f439d2f6`，否則雙 head 會使 bootstrap 與測試套件的 `upgrade head` 失敗）。新表加入 `database_init.py` 的 `TARGET_REQUIRED_TABLES["audit"]`；是否加入 `TARGET_CRITICAL_TABLES` 視部署是否「先遷移再驗證」而定。JSON 欄採 `MediumText`＋`json.dumps`，enum 採 `native_enum=False`，跨 SQLite/MySQL 8/PostgreSQL 16 可攜。
- **服務層**：`app/services/knowledge/retrieval_service.py`（in-method 埋點）、新 `app/services/knowledge/query_log_service.py`（寫入器）、`app/services/knowledge/__init__.py`（singleton accessor）。`retrieval_service.py` 目前為未追蹤檔且同時是 `integrate-knowledge-rag-engine` 與 `cross-team-rag` 的產出，需與提交該檔者協調，作為單一 owning 後續 commit，避免三方衝突。
- **API**：`app/api/admin.py` 新增唯讀端點；讀取經 `app/db_access/audit.py` boundary 自寫分頁查詢（不重用 `audit_service.query_logs`／`_build_conditions`，兩者綁死 `audit_logs`）。
- **排程/生命週期**：`app/main.py` shutdown 於 audit engine dispose 前呼叫寫入器 `force_flush()`；保留清理併入 flush 交易、週期性執行。新增 config `knowledge_query_log_retention_days` 與 flag `KNOWLEDGE_QUERY_LOG_ENABLED`。
- **前端 / i18n**：`app/templates/system_logs.html`、`app/static/js/system-logs.js`、三語系 locale 檔（含 param key 與 `datetime-formatter.js`）。
- **相依（散文宣告，OpenSpec 無結構化 depends_on）**：本變更排序於 `integrate-knowledge-rag-engine`、`cross-team-rag` 之後（前者建立 retrieval service、後者引入被記錄的 cross-team 欄位）。
- **資料安全**：query_text/結果 title/error 落地前套 `redact_sensitive` 值級遮蔽＋size cap；跨團隊結果僅存於 Super-Admin-only 表，與既有 audit 記錄跨使用者/跨團隊動作的治理姿態一致（`cross-team-rag` spec 對持久化保持沉默、無衝突）。
- **驗證**：`uv run pytest app/testsuite/<target> -q`、`uv run ruff check`、`node --check app/static/js/system-logs.js`、`node scripts/check-i18n-coverage.mjs`、`npm run lint`、`openspec validate log-knowledge-graph-queries --strict`；migration 以 disposable DB 實跑。既有 `test_tools_knowledge.py` 三處 `assert_called_once_with` 需隨新增可選 `context=` 參數更新。
