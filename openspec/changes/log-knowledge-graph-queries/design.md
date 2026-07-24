## Context

知識圖譜 / RAG 查詢目前匯流於三層：`KnowledgeRetrievalService`（業務層，掌握 team 授權、dual-route、斷路器、逾時、degraded 語意）、`HybridSearchService.hybrid_search`／`impact_analysis`（真正的查詢引擎，Qdrant 向量＋Neo4j Cypher）、以及 `Neo4jClient.execute_read`／`QdrantKnowledgeClient.search`（底層 client）。AI 助手工具經業務層；admin `/api/knowledge/search`、`/api/knowledge/impact` 則**直呼** `HybridSearchService`；未來 QA AI Helper 預期經 `build_rag_context_for_qa_helper`（內部呼叫 `search_knowledge`）。

audit DB 為多 DB 拓撲之一，預設 SQLite（NullPool、WAL、`busy_timeout=30s`），另支援 MySQL 8 / PostgreSQL 16。既有 `AuditLogTable` 以 `MediumText`＋`json.dumps` 存 JSON、以 `native_enum=False` 存列舉字串，並有 client-side `default=func.now()` 時間戳；alembic 環境開啟 `compare_type`／`compare_server_default`。audit DB 由 migration 建置（測試 fixture 亦跑 migration，非 `create_all`），當前單一 head 為 `77b4f439d2f6`。

本設計已歷三輪紅隊對抗定案；下列決策多為紅隊揪出的錯誤做法之修正。

## Goals / Non-Goals

**Goals:**
- 涵蓋「任何形式」的知識圖譜查詢，一次查詢恰一筆記錄，含降級路徑。
- 記錄查詢過程與結果摘要，供 Super Admin 事後回溯。
- 純觀測性疊加：零查詢行為/契約變更、零熱路徑阻斷風險。
- 跨三種 DB 引擎可攜；有界成長。

**Non-Goals:**
- 不改道 admin 端點、不改任何查詢的參數/結果/錯誤行為。
- 不記錄結果全文；不涵蓋 health/backfill/寫入路徑。
- 不修補 `system-log-viewer` spec 既有分頁清單缺漏（既有債）。

## Decisions

### D1. 埋點：業務層 in-method + admin 端點各自記錄（不改道、不單點）
兩方法（`search_knowledge`、`analyze_impact`）採 in-method 記錄，因為只有此處能取得結構化的降級原因（回傳 dict 僅有自由文字 message，無機器可讀判別碼，caller-side 無法還原斷路器/併發滿載/空團隊等分支）。admin 端點直呼引擎、**不經**業務層，故於端點各自記錄其 raw 路徑。
- 否決「只在 `hybrid_search` 單點埋」：dual-route 會使一次查詢產生兩筆，且該層無 team 授權/降級語意。
- 否決「把 admin `/search` 改道走 `search_knowledge`」：會破壞契約（top_k 100→20、注入 0.55 threshold、結果形狀截斷改寫、team filter 語意變、吞錯）。

### D2. 全路徑單次記錄：外層 `try/finally`
`search_knowledge` 有 8 個回傳出口（5 個前置檢查早退＋成功/逾時/例外），`analyze_impact` 有 3 個。以**單一外層 `try/finally`** 包住整個 method body，各 `return X` 改為 `result = X; return result`，於 `finally` 依 `result` 記錄一次並全吞例外。
- 保證恰一筆、涵蓋降級早退路徑。
- `finally` 在 `async with _RAG_SEMAPHORE` 退出**之後**執行 → 記錄不佔併發格。
- 記錄在斷路器 `except` **之外** → 記錄拋錯永遠不會觸發 `_record_failure()`（否決「在每個 return 前就地 emit」，那會被斷路器 except 捕捉、誤把成功翻成 degraded、甚至雙記）。

### D3. 寫入器：緩衝＋批次 flush 的 fail-safe 服務（非 create_task）
新 `app/services/knowledge/query_log_service.py`，比照 `AuditService` 批次模型：查詢路徑 `await` 一個 O(1) 緩衝 append，實際 DB 寫入由背景週期性 flush 承擔；整體以廣義 try/except 吞例外。經 `get_query_log_service()` singleton 取用（比照 `get_retrieval_service`）。
- 否決「`asyncio.create_task` fire-and-forget 於每次 `record()`」：weakref 導致「task destroyed while pending」與請求結束被取消的掉資料風險；採「單一 background periodic flush task」由 `main.py` startup/shutdown 對稱 `start()`/`stop()` 控制。
- 觸發策略：每 5 秒（`_FLUSH_INTERVAL_SECONDS`）檢查一次 buffer，**只要 buffer 非空就 flush**（不再以 `batch_size=50` 為「是否觸發 flush」的門檻，否則使用者只查 1 筆永遠看不到記錄；`batch_size` 仍為單次 transaction 上限，但不作為觸發條件）。
- background task 在 **每個 worker process** 各自啟動（與 `_start_knowledge_graph_sync_workers` 同層級，不走 leader election），因為 `record()` 寫入的 buffer 為 process-local；non-leader worker 的查詢也要在該 process 內被 flush。
- shutdown：於 `app/main.py` 之 `cleanup_audit_database()`（會 dispose engine）**之前**、以**獨立** try/except 呼叫本器 `stop()`（內含取消 background task + 收尾 `force_flush`），避免與 `audit_service.force_flush()` 共用 try 時前者拋錯連帶跳過本器 flush。

### D4. 儲存：audit DB 專用表，逐字沿用 `AuditLogTable` 慣例
`knowledge_query_logs` model subclass `AuditBase` 並於 `app/audit/database.py` import（使其註冊進 `AuditBase.metadata`，供 `_load_audit_metadata` 與 drift 比對）。JSON 欄用 `MediumText`＋`json.dumps`（避免純 `sa.Text` 在 MySQL 的 64KB 截斷）；`source`/`operation`/`status` 用 `SQLEnum(..., native_enum=False, values_callable=...)`（新增列舉值免 migration）；`timestamp` 用 client-side `default=func.now()` 且 migration **不**寫 `server_default`（否則 `compare_server_default` 判 drift）；索引採 composite `(source,ts)`／`(status,ts)`／`(primary_team_id,ts)`／`(user_id,ts)`。
- 否決「塞進 `audit_logs` as event」：`log_action` 有 10KB detail 上限會**整包丟棄**結果摘要（本功能核心），且 365 天保留與高頻遙測錯配、污染安全稽核。專用表避開全部。

### D5. 遷移：接單一 head、測試靠 migration
migration `down_revision='77b4f439d2f6'`（當前唯一 head）。因測試 fixture 以 `upgrade head` 建 audit DB，migration 正確性是 gate；以 disposable DB 實跑驗證。新表加入 `TARGET_REQUIRED_TABLES["audit"]`；`TARGET_CRITICAL_TABLES` 只在確認 bootstrap「先遷移再驗證」時才加，否則既有 DB 會在遷移前驗證階段硬失敗。

### D6. 保留清理：可攜時間戳刪除、週期性、併入 flush 交易
僅以「刪除早於保留天數」的時間戳條件 DELETE（比照 `cleanup_old_records`），**放棄列數上限**（`DELETE...LIMIT` 僅 MySQL、`NOT IN (SELECT 目標表)` 觸 MySQL 1093，皆不可攜）。清理週期性執行（每 N 次 flush／時間窗）並**併入同一筆 insert flush 交易**，避免在共享 audit SQLite 上多開一次檔案級寫鎖交易。config `knowledge_query_log_retention_days`、flag `KNOWLEDGE_QUERY_LOG_ENABLED`。

### D7. 讀取 API：自寫分頁查詢，不重用 audit 查詢器
`GET /api/admin/knowledge-query-logs`(+`/{id}`) 置於 `app/api/admin.py`，`require_super_admin()`（比照既有 `/api/admin/system-logs*`；**注意**：`/api/knowledge/health` 只是 `require_admin`，不可當範本）。讀取經 `app/db_access/audit.py` session provider 自寫分頁查詢與條件 builder。
- 否決重用 `audit_service.query_logs`／`_build_conditions`：兩者死綁 `AuditLogTable`，且 `_build_conditions` 注入 `knowledge_query_logs` 不存在的 `role` 欄。

### D8. UI：獨立第 4 分頁，重用元件 + textContent
於 `#systemLogsTabs` 新增獨立 tab（**不**塞進 KG health pane，否則兩者共用 `shown.bs.tab` 會 double eager-load 且擠壓版面）；靜態骨架重用 `data_table.html`／`toolbar.html` macro，tbody 以 `createElement`/`textContent` 建（不可照抄用 `innerHTML` 的 `audit_logs.js`）；三語系 i18n，筆數用 param key、時間戳用 `datetime-formatter.js`。

### D9. 未來 QA AI Helper 涵蓋
QA 接 RAG 時走 `build_rag_context_for_qa_helper`（內呼 `search_knowledge`，並傳 `context={source:qa_helper}` 使來源標籤正確）；spec 明訂 MUST NOT 直呼 `HybridSearchService.context_for_qa_helper()`（該法存在且同名，是現成繞過點）。

## Risks / Trade-offs

- 埋點須改動 `retrieval_service.py`（目前為未追蹤檔，且同時是 `integrate-knowledge-rag-engine`／`cross-team-rag` 的產出）→ 與提交該檔者協調，作為單一 owning 後續 commit；避免同時去動雙重爭用的 `tool_executor.py`。
- 新增可選 `context=` 參數 → 破壞 `test_tools_knowledge.py` 三處 `assert_called_once_with`；參數須有預設，並同步更新該三處測試。
- 共享 audit SQLite 檔案級寫鎖 → 高負載下記錄 insert/清理與 `audit_logs` 寫入序列化，可能出現延遲尖峰而非錯誤；以批次 flush＋週期清理＋併入交易緩解。
- admin `/search` 實際是 `get_current_user`（任何登入者可達）→ 記錄會含一般使用者的查詢；與既有 audit 記錄跨使用者動作的治理姿態一致，僅 Super Admin 可讀。
- 跨團隊結果落地於 Super-Admin-only 表；`cross-team-rag` spec 對持久化沉默（非禁止），proposal 已註記。
- repo 無自動 single-head/drift 測試 → 以 bootstrap `upgrade head`＋disposable DB 實跑為實質 gate。

## Migration Plan

1. 新增 model＋`alembic_audit` migration（`down_revision=77b4f439d2f6`），disposable DB 跑 `upgrade head`／`downgrade` 驗證，並確認 bootstrap `TARGET_REQUIRED_TABLES` 通過。
2. 加寫入器＋singleton＋shutdown flush；加 config／flag。
3. 業務層外層 `try/finally` 埋點＋admin 端點記錄＋`build_rag_context_for_qa_helper` 傳 context；更新受影響單元測試。
4. 讀取 API＋UI 分頁＋i18n。
5. 全鏈驗證（pytest 目標＋全套、ruff、node --check、i18n coverage、npm lint、openspec validate --strict）。

Rollback：功能受 `KNOWLEDGE_QUERY_LOG_ENABLED` 旗標保護，停用即不寫入不影響查詢；migration 提供 downgrade 移除新表（非破壞既有表）。

## Open Questions

- `TARGET_CRITICAL_TABLES["audit"]` 是否加入新表，取決於實際部署是否保證「先遷移再驗證」——實作時確認 bootstrap 順序後定案。
- 保留天數與 flush 批次大小/週期的預設值，於實作時依實際查詢頻率調校（起始建議保留 30 天）。
