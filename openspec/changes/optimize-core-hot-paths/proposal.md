## Why

核心 DB 已逼近 SQLite 的舒適區（`test_case_repo.db` ~150MB、`audit.db` ~92MB），而最熱、最重的請求路徑上累積了數個會隨資料量線性（甚至平方）放大的成本，並非缺索引的問題（複合索引已覆蓋熱門過濾／排序欄位），而是「一次抓太多、在 Python 端反覆解析、在事件迴圈上做阻塞 IO、在記憶體裡做聚合」這類**契約層級**的低效：

- **測試案例列表（最熱端點）**：`app/api/test_cases.py:366` 預設 `limit=10000`、`load_all=true`（`:403-405`）會回傳整表；`app/services/test_case_repo_service` 的 `_to_response`（~`:65-123`）對**每一列**都 `json.loads` `tcg_json`／`test_data_json` 並展開 `precondition`／`steps`／`expected_result`，即使呼叫端只需要列表概覽；同一個 WHERE 還先 `service.count()`（`:393`）再 `service.list()`（`:409`）跑兩遍。
- **事件迴圈被同步 IO 阻塞**：附件下載代理 `app/api/attachments.py:666` 在 `async def download_attachment_proxy`（`:517`）裡用 `requests.get(..., stream=True)`，傳輸期間阻塞**整個事件迴圈**、影響所有使用者；所有 Lark 呼叫（`attachments.py:103,364,403,421,461,492` → `lark_client.py` 的 `requests.*` `:124,169,235,542`）與 Lark 重試 `time.sleep`（`lark_client.py:248,269,282`）同樣阻塞。JIRA 端已正確（`app/api/jira.py:85` 用 `asyncio.to_thread`），應比照。
- **統計在 Python 端聚合**：`app/api/test_run_items.py:1227-1238` 連發 7 次 `.count()`；`:1276` 撈出所有符合的列再逐列 `json.loads(bug_tickets_json)`（`:1278-1287`）做去重計數。
- **Test Run Set 總覽 N+1**：`app/api/test_run_sets.py:452` 撈出所有 set 後逐一 `_build_set_detail`（`:305`），`:318` 觸發 `set_db.team.automation_script_groups` 逐 set lazy load。
- **每請求使用者查詢無快取**：`app/auth/dependencies.py:49` 每個已驗證請求都打一次 user 表（權限檢查在 `permission_service.py:33` 已有 5 分鐘 TTL 快取，可比照）。
- **USM 樹邊建構 O(n²)**：`app/api/user_story_maps.py:705-725` 以每節點巢狀迴圈掃 `related_ids`。
- **稽核在請求路徑上**：`app/middlewares/audit_middleware.py:50` 在回應前 `await log_action`；`audit_service.py:35` 的全域 `asyncio.Lock` 串行化寫入；`:86` 對 `CRITICAL` 強制 flush，而每個 DELETE 都被標為 CRITICAL（`audit_middleware.py:98`），等於在請求路徑上、鎖內做同步 flush（批次機制本身設計良好，問題在觸發時機與位置）。

本變更針對上述熱路徑，做契約層級的效率優化，使行為**可觀測、可量測**，且不改資料模型、不新增索引、不引入新的快取基礎設施。

## What Changes

- **綁定列表回傳量並提供輕量投影（P0）**：降低測試案例列表預設 `limit`（例如 100）、收斂 `load_all` 行為；新增**輕量列表投影**，預設**不含** `steps`／`expected_result`／`test_data_json`／`precondition` 等重欄位，僅在詳情端點載入重欄位；移除或合併重複的前置 `count()`，以單一帶視窗（windowed）查詢取得分頁中繼資料。
- **解除事件迴圈阻塞（P0）**：附件下載代理與所有 Lark 出站呼叫改為事件迴圈安全（以 `asyncio.to_thread` 包裹既有同步呼叫，或改用 `httpx.AsyncClient`），比照 JIRA 既有做法；Lark 重試等待不得在事件迴圈上同步 `sleep`。
- **聚合下推資料庫（P1）**：以單一 `GROUP BY` 取代 7 次 `count()`；bug ticket 去重計數改用 DB 端 JSON 函式，避免撈全量再於 Python 解析。
- **修正 N+1 與每請求開銷（P1）**：Test Run Set 總覽以 `selectinload` 預載 `team.automation_script_groups`；為 `get_current_user` 的使用者讀取加入短 TTL 的處理快取（比照 permission 快取）。
- **USM 與稽核（P2）**：USM 邊建構改為單次掃描預先建立鄰接關係，消除 O(n²)；稽核改為移出請求路徑（背景任務），且不再對每個 DELETE 強制同步 flush。
- **量測（驗證）**：為受影響端點建立可重現的前後量測（回傳列數、回傳 payload 是否含重欄位、聚合查詢次數、是否阻塞事件迴圈），作為驗收依據。

非目標（Non-Goals）：

- 不新增索引（既有複合索引已覆蓋熱門過濾／排序欄位）。
- 不變更資料模型／schema、不做資料遷移。
- 不引入新的快取基礎設施（僅沿用既有的單機 in-process TTL 模式）。
- 不改 Qdrant／LLM 路徑（已正確非同步且不在熱路徑）。
- 不改 config 載入方式（啟動時載入一次，現狀正確）。

## Capabilities

### New Capabilities
- `core-runtime-performance`: 定義核心熱路徑的執行期效能**契約**——列表端點的回傳量與輕量投影預設、出站 IO 的事件迴圈安全規則、聚合統計於資料庫端計算、以及已驗證請求的固定（bounded）額外開銷。需求皆綁定可觀測行為與可量測門檻。

### Modified Capabilities
<!-- 無既有 capability 的需求被變更；本變更僅新增執行期效能契約需求。 -->

## Impact

- **API 相容性**：測試案例列表端點的**回應形狀改變**——預設回傳輕量投影，`steps`／`expected_result`／`test_data_json`／`precondition` 等重欄位**預設不再出現於列表**；預設 `limit` 由 10000 降為 100，`load_all` 行為收斂。為向後相容，提供明確的 opt-in（例如 `fields=full` 或 `include_heavy=true` 查詢參數）讓既有消費端可取回完整欄位；詳情端點維持完整欄位不變。`X-Total-Count`／`X-Has-Next` 等既有分頁標頭語意保持不變。Test Run Set 總覽與測試執行統計的**回應欄位不變**（僅內部查詢方式改變）。
- **後端**：`app/api/test_cases.py`／`app/services/test_case_repo_service.py`（輕量投影、單一視窗查詢）；`app/api/attachments.py`、`app/services/lark_client.py`（事件迴圈安全出站 IO）；`app/api/test_run_items.py`（GROUP BY + DB JSON 聚合）；`app/api/test_run_sets.py`（`selectinload`）；`app/auth/dependencies.py`（短 TTL 使用者快取）；`app/api/user_story_maps.py`（單次掃描建邊）；`app/middlewares/audit_middleware.py`／`app/audit/audit_service.py`（移出請求路徑、停止對 DELETE 強制同步 flush）。不新增資料表、不新增 migration。
- **相容性／rollback**：行為改變集中於列表回應形狀與預設量；可逐項以 feature flag／參數開關回退（如保留舊預設 `limit` 與完整欄位的 opt-in 路徑）。其餘變更（事件迴圈安全、聚合下推、N+1、快取、稽核改背景）為內部實作優化，對外契約不變，rollback 僅需還原對應 handler。稽核改為背景任務後，DELETE 等高風險事件的最終一致性保證需在設計中明確（見 `design.md`）。
