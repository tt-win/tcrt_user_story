## 1. Bounded list + lightweight projection（P0）

- [ ] 1.1 在 `app/api/test_cases.py` 將列表預設 `limit` 由 `10000` 降為 `100`（保留 `le` 上限與 `ge=1`），並收斂 `load_all`（預設關閉；若保留則需明確上限或受權限/旗標保護）
- [ ] 1.2 定義輕量列表回應形狀（list projection），**排除** `precondition`／`steps`／`expected_result`／`test_data`(`test_data_json`)／`tcg`(`tcg_json` 展開) 等重欄位，僅保留概覽欄位（如 `test_case_number`／`title`／`priority`／`test_result`／`section_*`／`team_id`／時間戳）
- [ ] 1.3 在 `app/services/test_case_repo_service.py` 新增輕量映射路徑（不對重欄位做 `json.loads`／不展開長文字），與既有 `_to_response`（完整）並存；`list()` 預設走輕量路徑
- [ ] 1.4 新增重欄位 opt-in（如 `fields=full` 或 `include_heavy=true`）使既有消費端可取回完整列表欄位；詳情端點維持回傳完整欄位
- [ ] 1.5 移除或合併重複的前置 `count()`（`test_cases.py:393` 與 `:409` 兩遍 WHERE）：以單一視窗查詢（或 `func.count()` over window／一次查詢加總筆數）同時取得分頁資料與 `X-Total-Count`／`X-Has-Next`，維持既有標頭語意

## 2. Event-loop unblocking（P0）

- [ ] 2.1 將 `app/api/attachments.py:download_attachment_proxy`（`:517`）的 `requests.get(stream=True)`（`:666`）改為事件迴圈安全：以 `asyncio.to_thread` 包裹或改用 `httpx.AsyncClient`（串流回應同樣不得在迴圈上阻塞）
- [ ] 2.2 將 `app/services/lark_client.py` 的同步 `requests.*`（`:124,169,235,542`）包成事件迴圈安全呼叫；對應 `app/api/attachments.py` 內的 Lark 呼叫點（`:103,364,403,421,461,492`）改為 `await`
- [ ] 2.3 Lark 重試等待（`lark_client.py:248,269,282` 的 `time.sleep`）改為不阻塞事件迴圈（於 to_thread 內執行，或改 `asyncio.sleep`），確保重試期間迴圈仍可服務其他請求
- [ ] 2.4 比照 `app/api/jira.py`（`:85` 等）的 `asyncio.to_thread` 既有做法，確保風格一致

## 3. DB-side aggregation（P1）

- [ ] 3.1 在 `app/api/test_run_items.py` 將 7 次 `.count()`（`:1227-1238`）改為單一 `GROUP BY test_result` 查詢，於記憶體中組裝各狀態計數與 `total`/`executed`/各 rate
- [ ] 3.2 將 bug ticket 去重計數（`:1276-1289` 撈全量後 `json.loads`）改為 DB 端 JSON 函式（如 SQLite `json_each`）做去重計數，避免載入完整結果集
- [ ] 3.3 移除 `:1241-1270` 與 `:1253-1258` 的 `PASS_RATE_*_DEBUG` 樣本撈取與逐列 `logger.warning`（避免每次請求的額外查詢與日誌成本；如需診斷改為 debug 級且不撈樣本列）

## 4. N+1 & per-request user cache（P1）

- [ ] 4.1 在 `app/api/test_run_sets.py` 的總覽查詢（`_query_set_with_members` / `:448-452`）以 `selectinload(TestRunSetDB.team).selectinload(Team.automation_script_groups)` 預載，消除 `_build_set_detail`（`:318`）逐 set 觸發的 lazy load N+1
- [ ] 4.2 在 `app/auth/dependencies.py:get_current_user`（`:49`）為使用者讀取加入短 TTL 的 in-process 快取（比照 `app/auth/permission_service.py:33` 的 5 分鐘 TTL 模式），並在使用者停用／角色變更等寫入點提供失效（clear）機制
- [ ] 4.3 確認快取不破壞 `is_active`／角色即時性需求（停用後在可接受時窗內生效；失效路徑覆蓋停用與角色變更）

## 5. USM & audit（P2）

- [ ] 5.1 在 `app/api/user_story_maps.py` 將動態建邊（`:705-725`）改為單次掃描預先建立鄰接關係（以 id→node 索引與 set 去重），消除每節點掃 `related_ids` 的 O(n²)
- [ ] 5.2 在 `app/middlewares/audit_middleware.py`（`:50`）將 `log_action` 移出請求路徑（背景任務／不阻塞回應），請求回應不再等待稽核寫入
- [ ] 5.3 在 `app/audit/audit_service.py` 調整 DELETE 不再強制同步 flush（`:86` 的 `severity == CRITICAL` 觸發）；改由既有批次門檻（`batch_size`／30s）落地，並提供關機／顯式 `force_flush`（`:483`）保證不遺失
- [ ] 5.4 確認全域 `asyncio.Lock`（`:35`）不再位於請求回應路徑的關鍵段上（背景化後鎖競爭不影響使用者延遲）

## 6. Verification（驗證 + 量測）

- [ ] 6.1 測試案例列表：預設請求回傳列數 ≤ 預設 `limit`（100），且回應**不含**重欄位；帶 opt-in（`fields=full`）時回傳完整欄位；`X-Total-Count`／`X-Has-Next` 語意正確
- [ ] 6.2 事件迴圈安全：以並發請求驗證附件下載／Lark 傳輸期間其他請求不被阻塞（無同步 `requests`/`time.sleep` 殘留於 `async def` 路徑）
- [ ] 6.3 聚合下推：測試執行統計只發出單一聚合查詢（+JSON 去重查詢），回應數值與舊實作一致（以既有資料對拍）
- [ ] 6.4 N+1：Test Run Set 總覽查詢次數不隨 set 數量線性成長（以查詢計數驗證）
- [ ] 6.5 使用者快取：連續多個已驗證請求僅在 TTL 內查 user 表一次；停用使用者於失效後被拒
- [ ] 6.6 稽核：DELETE 請求回應不再等待 flush；批次仍於門檻內落地、關機前 `force_flush` 不遺失
- [ ] 6.7 量測（perf）：建立可重現的前後對照基準（list payload 大小／回傳列數、統計端點查詢次數、總覽查詢次數、熱端點 p95 延遲），記錄改善幅度作為驗收
- [ ] 6.8 執行 `pytest app/testsuite -q` 相關測試通過，確認回應契約與行為無回歸
