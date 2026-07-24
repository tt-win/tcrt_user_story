## 1. Schema 與遷移（audit DB）

- [x] 1.1 於 `app/audit/database.py` 新增 `KnowledgeQueryLogTable(AuditBase)`：欄位含 timestamp、query_id、source/operation/status（`native_enum=False` 列舉）、user_id/username、conversation_id/turn_key/llm_tool_call_id（可空）、query_text、primary_team_id、allowed_team_ids、top_k、score_threshold、fallback_recommended、degrade_reason、duration_ms、result_count、process、results_summary、error、schema_version；JSON 欄用 `MediumText`＋`json.dumps`；`timestamp=Column(DateTime, default=func.now(), index=True)` 且不設 server_default
- [x] 1.2 加 composite 索引 `(source,timestamp)`、`(status,timestamp)`、`(primary_team_id,timestamp)`、`(user_id,timestamp)`，並確認 model 被 import 進 `AuditBase.metadata`
- [x] 1.3 建立 `alembic_audit/versions/` migration：`down_revision='77b4f439d2f6'`，create_table 欄位/nullable/預設與 model 逐字一致（避免 `compare_type`/`compare_server_default` drift），大型文字欄位（`query_text`/`allowed_team_ids`/`process`/`results_summary`/`error`）採 `sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")` 對齊 `MediumText` 別名（MySQL 直接建出 MEDIUMTEXT、其他方言維持 TEXT）；提供 downgrade 移除該表
- [x] 1.6 新增 sibling catch-up migration（`down_revision='20260724_knowledge_query_logs'`，head=`b1c2d3e4f506`）：照 `a371471a3008` 模式硬編 5 個知識查詢欄位清單，MySQL-only `alter_column` 升級為 MEDIUMTEXT；其他方言 no-op。修補 1.3 上一版以 `sa.Text()` 建立造成的 bootstrap gate 違規（`verify_large_text_columns` 在 MySQL 上擋下 `TEXT`）
- [x] 1.4 於 `database_init.py` 將 `knowledge_query_logs` 加入 `TARGET_REQUIRED_TABLES["audit"]`（確認 bootstrap 先遷移再驗證後，再決定是否加入 `TARGET_CRITICAL_TABLES`）
- [x] 1.5 → verify：disposable audit DB 跑 `upgrade head` 與 `downgrade`，確認單一 head 未分叉；`uv run pytest app/testsuite/test_auxiliary_db_migrations.py -q`

## 2. 設定與旗標

- [x] 2.1 於 `app/config.py` 新增 `knowledge_query_log_retention_days`（預設 30）與 `KNOWLEDGE_QUERY_LOG_ENABLED`（預設隨知識圖譜啟用）設定路徑
- [x] 2.2 → verify：設定載入單元測試（存在/預設值/停用旗標）

## 3. 寫入服務（fail-safe、批次、可攜清理）

- [x] 3.1 新增 `app/services/knowledge/query_log_service.py`：in-memory 緩衝＋批次 flush＋廣義 try/except 吞例外；查詢路徑僅 O(1) `await` append，不同步等待 DB I/O
- [x] 3.2 落地前套 `redact_sensitive`（來自 `app/utils/system_log_buffer.py`）於 query_text/結果 title/error，並套用 size cap（超限安全截斷）；`results_summary` 精簡（type/id/截斷 title/score/source/team_id，無全文）
- [x] 3.3 清理：以時間戳條件 DELETE（跨引擎可攜、比照 `cleanup_old_records`），週期性且併入 flush 同交易；不使用列數上限刪除
- [x] 3.4 於 `app/services/knowledge/__init__.py` 加 `get_query_log_service()` singleton（比照 `get_retrieval_service`）
- [x] 3.5 於 `app/main.py` shutdown、`cleanup_audit_database()` 之前、以獨立 try/except 呼叫寫入器 `stop()`（取消 background task + 收尾 force_flush）
- [x] 3.7 於 `app/main.py` startup（與 `_start_knowledge_graph_sync_workers` 同層級、不走 leader election）呼叫寫入器 `start()` 啟動 background periodic flush task（每 5s 檢查一次；buffer 非空就 flush）。若漏接 background lifecycle，使用者查詢只會卡在 in-memory 永遠不寫入（已在 2026-07-24 上線後第一次查詢驗證發現並修補）
- [x] 3.6 → verify：`uv run pytest app/testsuite/test_knowledge_query_log_service.py -q`（寫入映射、記錄失敗不拋、停用不寫、size cap 截斷、時間戳清理可攜 SQL、background flush 寫入、start 冪等、stop 收尾）

## 4. 業務層埋點（in-method，全路徑單次）

- [x] 4.1 為 `KnowledgeRetrievalService.search_knowledge` / `analyze_impact` 加可選 `context` 參數（source＋user_id/team_id＋可選 llm_tool_call_id；預設 None，向後相容）
- [x] 4.2 以單一外層 `try/finally` 包住兩方法 body，各 `return X` 改 `result = X; return result`，於 `finally` 依 result＋收集的 diagnostics（dual_route、per-collection 計數、graph 展開/逾時、斷路器狀態、degrade_reason）guarded 記錄一次；確認記錄在 semaphore 釋放後、斷路器 except 之外
- [x] 4.3 `build_rag_context_for_qa_helper` 呼叫 `search_knowledge` 時帶 `context={source: qa_helper}`
- [x] 4.4 → verify：`uv run pytest app/testsuite/test_knowledge_retrieval_service.py -q`（8 條 search 出口＋3 條 impact 出口各恰一筆；記錄拋錯不觸發 `_record_failure`；dual-route 不雙記）

## 5. AI 助手與 admin 端點涵蓋

- [x] 5.1 於 `tool_executor.py` 的 `run_read_tool`→`_run_local_read_tool` 轉遞 `llm_tool_call_id`（widen 簽章＋dispatch），使助手記錄可交叉索引既有 `AssistantToolExecution` journal；新參數須有預設
- [x] 5.2 於 `app/api/knowledge.py` 的 `/search`、`/impact` 端點，在既有直呼之後 guarded 記錄一筆（`source=api`、user_id），不更動端點回傳契約
- [x] 5.3 更新 `app/testsuite/test_tools_knowledge.py` 三處 `assert_called_once_with` 以容納新增 `context=` 參數
- [x] 5.4 → verify：`uv run pytest app/testsuite/test_tools_knowledge.py app/testsuite/test_knowledge_hybrid_search.py -q`

## 6. 唯讀查詢 API

- [x] 6.1 於 `app/api/admin.py` 新增 `GET /api/admin/knowledge-query-logs`(+`/{id}`)，`require_super_admin()`，`Cache-Control: no-store`；經 `app/db_access/audit.py` boundary 自寫分頁查詢與條件 builder（不重用 `audit_service.query_logs`/`_build_conditions`）
- [x] 6.2 篩選：source/status/team_id/時間區間/查詢文字；回應含分頁結果與總數
- [x] 6.3 → verify：`uv run pytest app/testsuite/test_knowledge_query_log_api.py -q`（分頁、篩選、非 Super Admin 403）

## 7. 前端分頁與 i18n

- [x] 7.1 於 `app/templates/system_logs.html` 的 `#systemLogsTabs` 新增獨立 tab 按鈕與 pane（重用 `data_table.html`/`toolbar.html` macro 作靜態骨架）
- [x] 7.2 於 `app/static/js/system-logs.js` 新增 panel class（比照 `RuntimeSettingsPanel`/`KnowledgeGraphPanel` 的 `shown.bs.tab` 延遲載入）；tbody 以 `createElement`/`textContent` 建；筆數用 param key、時間戳用 `datetime-formatter.js`；於 `SystemLogsPage.init()` 實例化
- [x] 7.3 於 `app/static/locales/{en-US,zh-CN,zh-TW}.json` 新增分頁與表格文案鍵（含 `systemLogs.tabs.*` 與查詢記錄區塊）
- [x] 7.4 → verify：`node --check app/static/js/system-logs.js`、`node scripts/check-i18n-coverage.mjs`、`npm run lint`

## 8. 全鏈驗證與工件

- [ ] 8.1 `uv run pytest app/testsuite -q` 全套通過
- [ ] 8.2 `uv run ruff check app scripts database_init.py` 通過
- [ ] 8.3 `openspec validate log-knowledge-graph-queries --strict` 通過
- [ ] 8.4 自我審查 diff：每行皆可追溯需求、無殘留 debug/stub/孤兒 import；確認未動雙重爭用的無關檔
