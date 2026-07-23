# Design — optimize-core-hot-paths

本文件定義三項核心契約／規則，以及對既有 API 消費端的向後相容策略：
1. 輕量列表回應契約（list vs detail 欄位界線）。
2. 出站呼叫的事件迴圈安全規則。
3. 聚合下推資料庫的做法。
並補充 USM／稽核變更與 rollback 策略。

## 1. 輕量列表回應契約（list vs detail）

### 動機
`_to_response`（`app/services/test_case_repo_service.py` ~`:65-123`）對每一列都 `json.loads(tcg_json)`／`json.loads(test_data_json)` 並回填 `precondition`／`steps`／`expected_result` 長文字。在 ~150MB 規模、預設 `limit=10000`／`load_all` 的列表請求下，這是最重的單一成本來源，且絕大多數列表場景並不需要這些重欄位。

### 欄位界線

清單回應預設為「輕量投影」，僅含概覽欄位；重欄位移至詳情端點或以 opt-in 取得。

| 欄位 | List（預設輕量） | List（`fields=full` opt-in） | Detail |
| --- | :---: | :---: | :---: |
| `record_id` / `test_case_number` / `title` | ✅ | ✅ | ✅ |
| `priority` / `test_result` | ✅ | ✅ | ✅ |
| `team_id` / `test_case_set_id` / `test_case_section_id` | ✅ | ✅ | ✅ |
| `section_name` / `section_path` / `section_level` | ✅ | ✅ | ✅ |
| `created_at` / `updated_at` / `last_sync_at` | ✅ | ✅ | ✅ |
| `precondition` | ❌ | ✅ | ✅ |
| `steps` | ❌ | ✅ | ✅ |
| `expected_result` | ❌ | ✅ | ✅ |
| `test_data`（`test_data_json`） | ❌ | ✅ | ✅ |
| `tcg`（`tcg_json` 展開） | ❌ | ✅ | ✅ |
| `attachments` | ❌ | ✅ | ✅ |

註：`assignee`／`user_story_map`／`parent_record`／`test_results_files`／`raw_fields` 目前即為空或佔位，輕量投影一律省略，行為不變。

### 實作要點
- 在 service 層新增輕量映射函式（不觸 `json.loads`、不展開長文字），與既有 `_to_response`（完整）並存；`list()` 預設走輕量路徑，opt-in 時走完整路徑。
- 輕量投影建議以 ORM `load_only` / 明確 `select(columns)` 只取所需欄位，避免從 DB 把重欄位（長文字／JSON blob）也讀進來。
- 投影選擇由查詢參數驅動（`fields=full` 或 `include_heavy=true`，擇一命名並於本變更內一致）。

### opt-in 契約（相容性）
- **預設行為改變**：未帶 opt-in 的列表呼叫，回應將**不含**上表的重欄位，且預設 `limit` 由 10000 → 100。
- **既有消費端的遷移路徑**：需要完整列表欄位者，明確加上 `fields=full`（或 `include_heavy=true`）即可取回與舊版相同的形狀；需要逐筆完整資料者改打詳情端點。
- 分頁標頭語意不變：`X-Total-Count`／`X-Has-Next`／`with_meta` 的 `page` 物件維持原意，僅 item 形狀改變。

## 2. 事件迴圈安全規則（出站 IO）

### 規則
任何 `async def` 請求處理路徑上，**不得**直接呼叫阻塞式同步網路／IO（`requests.*`、阻塞式 socket、`time.sleep`）。出站呼叫二擇一：
- **方案 A（最小改動，優先）**：以 `asyncio.to_thread(sync_callable, ...)` 包裹既有同步用戶端呼叫——與 `app/api/jira.py:85` 既有做法一致，改動面最小、風險最低。串流下載可在工作執行緒內以 chunk 迭代並餵給 `StreamingResponse`。
- **方案 B（較大改動）**：改用 `httpx.AsyncClient` 重寫為原生非同步；適用於後續想徹底去除 `requests` 依賴時。本變更預設採方案 A。

重試等待：Lark 重試的 `time.sleep`（`lark_client.py:248,269,282`）若整段呼叫已在 `to_thread` 內執行則可接受（不在迴圈執行緒上）；若改方案 B，須改為 `asyncio.sleep`。

### 適用點
- 附件下載代理 `app/api/attachments.py:download_attachment_proxy`（`:517`、`requests.get` `:666`）。
- 所有 Lark 出站：`lark_client.py` 的 `requests.*`（`:124,169,235,542`）與其在 `attachments.py` 的呼叫點（`:103,364,403,421,461,492`）。

### 驗收
以並發請求觀測：在一個附件傳輸進行中時，其他端點延遲不應被該傳輸時長放大（事件迴圈未被佔住）。

## 3. 聚合下推資料庫

### 狀態計數（取代 7 次 count）
`app/api/test_run_items.py:1227-1238` 改為單一查詢：
```sql
SELECT test_result, COUNT(*) FROM test_run_items
WHERE team_id = :team AND config_id = :config
GROUP BY test_result;
```
於應用層把分組結果攤平為 `total`/`executed`/`passed`/`failed`/`retest`/`na`/`pending`/`not_required`/`skip`，再算各 rate。`executed` = 非 NULL 且非 PENDING（由分組結果加總）。

### Bug ticket 去重（取代撈全量 + Python json.loads）
`:1276-1289` 改用 SQLite JSON 函式於 DB 端展開與去重，例如：
```sql
SELECT COUNT(DISTINCT UPPER(json_extract(t.value, '$.ticket_number')))
FROM test_run_items i, json_each(i.bug_tickets_json) t
WHERE i.team_id = :team AND i.config_id = :config
  AND i.bug_tickets_json IS NOT NULL
  AND json_valid(i.bug_tickets_json)
  AND json_extract(t.value, '$.ticket_number') IS NOT NULL;
```
需處理 `bug_tickets_json` 非合法 JSON 或非陣列的列（以 `json_valid` 過濾，與既有「忽略解析錯誤」語意對齊）。此查詢可與狀態計數合併或並行，但**不得**載入完整結果集到記憶體。

### 附帶清理
移除 `PASS_RATE_*_DEBUG`（`:1241-1270`、含 `:1253-1258` 額外撈 5 筆樣本）——這些是每次請求都會跑的 `logger.warning` 與額外查詢；若仍需診斷，降為 `debug` 級且不撈樣本列。

## 4. N+1、每請求使用者快取、USM、稽核

- **Test Run Set 總覽 N+1**：`app/api/test_run_sets.py:_build_set_detail`（`:318`）逐 set 觸發 `set_db.team.automation_script_groups` lazy load。在總覽查詢（`_query_set_with_members` / `:448-452`）加上 `selectinload(TestRunSetDB.team).selectinload(Team.automation_script_groups)`（其餘 memberships/config 若已預載則沿用）。
- **每請求使用者快取**：`app/auth/dependencies.py:get_current_user`（`:49`）每請求查 user 表。比照 `app/auth/permission_service.py:33` 的 `PermissionCache`（5 分鐘 TTL、in-process）建立 user 快取；以 `user_id` 為鍵快取使用者物件。**失效**：使用者停用、角色變更、登出等寫入點需呼叫對應 `clear`，避免停權延遲過長。TTL 取捨：太長 → 停權延遲；建議與 permission 一致（≤5 分鐘）並在敏感寫入點主動失效。
- **USM 邊建構 O(n²)**：`app/api/user_story_maps.py:705-725` 每節點巢狀掃 `related_ids`。改為先建 `id→node` 索引與 `seen_edges` set，一次遍歷節點即可產生 parent／related 邊，整體 O(n + E)。
- **稽核移出請求路徑**：`app/middlewares/audit_middleware.py:50` 目前在回應前 `await log_action`。改為以背景任務排程（如 `asyncio.create_task` 或 FastAPI `BackgroundTasks`），請求回應不等待。同時在 `app/audit/audit_service.py` 移除「`severity == CRITICAL` 強制 flush」（`:86`）這條，讓 DELETE 也走一般批次門檻（`batch_size`／30s，`:84-87`），避免請求路徑上、`_batch_lock`（`:35`）內的同步 flush。批次與重試機制本身保留（`_flush_batch` `:514`、失敗回填 `:565`）。

### 稽核最終一致性保證
移出請求路徑後，需明確：
- 應用關機時呼叫 `force_flush`（`:483`）確保緩衝清空。
- 背景寫入失敗時沿用既有回填重試（`:565`），不靜默丟棄。
- 取捨：DELETE 等高風險事件的稽核改為「近即時」而非「請求內同步落地」；以批次門檻（≤30s 或達 `batch_size`）+ 關機 flush 作為遺失邊界，於本變更接受此語意（仍不遺失，只是不再阻塞請求）。

## 5. 向後相容與 rollback

- **對外契約改變僅限測試案例列表**（item 形狀 + 預設 `limit`）。提供 `fields=full` opt-in 與詳情端點作為完整資料來源；可保留舊預設值的旗標／參數作為短期回退。
- **其餘變更對外契約不變**（事件迴圈安全、聚合下推、N+1、使用者快取、USM、稽核背景化），回應欄位與數值維持一致；rollback 僅需還原對應 handler，**不涉及資料模型或 migration**。
- 不新增索引、不改 schema、不引入新快取基礎設施（僅沿用既有 in-process TTL 模式）。
