## Context

app token 與 legacy MCP credential 共用 `app/auth/app_token_dependencies.py` 的 resolver：先查 `team_app_tokens`，未命中再 fallback 查 `mcp_machine_credentials`，並把 legacy `mcp_read` 映射成 `[test_case:read, test_run:read]` read principal。安全審查（2026-07-15）在此表面上發現一個路徑遍歷寫檔漏洞、若干授權完整性缺口與缺乏防濫用機制。本 change 針對性收斂，不重寫認證架構。

現況重點：
- attachment 上傳以 `test_case_number` 直接組路徑；`_ensure_within_root` 的容器檢查在寫檔之後才執行。
- app token update 直接採用 body 的 set/section id，未驗證歸屬。
- `/api/app/*`、`/api/mcp/*` 認證無 rate limit；每個 401 都寫審計。
- `audit_service.cleanup_old_records()` 無呼叫者；scheduler `service_registry` 目前只註冊 `lark_org_sync`。
- webhook 端已有可重用的 in-process token-bucket（`automation_webhooks_public.py:_consume_rate_limit`）。

## Goals / Non-Goals

**Goals:**
- 消除認證後任意寫檔（路徑遍歷）與跨 team 授權完整性缺口。
- 加入認證失敗的 per-IP rate limit，避免未認證審計灌爆與 DB 負載放大。
- 讓審計保留機制真正生效，並為失敗重排緩衝設上限。
- 將 legacy MCP credential 的可及面收斂回 `/api/mcp/*`。
- 為上述行為補齊回歸測試。

**Non-Goals:**
- 不改 token 產生 / hash 儲存 / 一次性顯示流程（審查確認安全）。
- 不在 app 層加 HTTPS/HSTS/TrustedHost（部署層負責）。
- 不處理全域 ADMIN 可管理任意 team token 的 RBAC 取捨（另案）。
- 不做 `/docs`、`/openapi.json` gating。

## Decisions

**D1 — `test_case_number` 路徑安全在 model 層驗證。**
於 `TestCaseCreate` / `TestCaseUpdate`（及 batch 使用的 model）的 `test_case_number` field validator 拒絕含 `/`、`\`、`..` 或 NUL 的值，回 422。選 model 層而非 route 層，因 create / batch / update / bulk-clone 多路徑共用同一 model，單點驗證涵蓋所有入口。顯示用的基底 `TestCase.test_case_number`（允許空值）不加此限制，避免影響既有 Lark 匯入顯示資料。

**D2 — 附件寫檔前先做容器檢查（defense in depth）。**
在 `open(stored_path, "wb")` 之前呼叫 `_ensure_within_root(stored_path, root_dir)`（或等效檢查），確保即使未來出現新的路徑注入點，也不會在容器檢查前落檔。與 D1 為雙層防護：D1 擋來源、D2 擋落地。

**D3 — app token update 驗證 set/section 歸屬。**
`PUT /api/app/teams/{team_id}/test-cases/{case_id}` 在寫入 `test_case_set_id` / `test_case_section_id` 前，比照 create 路徑（app_test_cases.py:144-167）與 JWT update（test_cases.py:1025-1105）驗證目標 set 屬於 `team_id`、section 屬於該 set，不符回 400。共用既有驗證 helper，不新增邏輯分支。

**D4 — 認證失敗 rate limit 以 client IP 為 key，重用 token-bucket 模式。**
在 `app/auth/app_token_dependencies.py` 對「無效 / 缺失 token」的路徑加入 per-IP token bucket（沿用 `automation_webhooks_public.py` 的實作形狀），超限回 429 + `Retry-After`，且**在寫審計之前**短路，避免放大。成功認證不受限（正常流量不觸發）。key 用 `request.client.host`；bucket 容量與 refill 走 `app/config.py` 新設定，預設保守（例如 30/min/IP）。限流狀態為 in-process（與現有 webhook 一致），多 worker 下為 per-worker，足以擋單源灌爆；分散式限流列為 future work。

**D5 — legacy principal 在 `/api/app/*` 一律拒絕。**
最小侵入作法：在 `/api/app/*` 的 principal 取得層（app token read/mutation 依賴）檢查 `principal.is_legacy`，為真則回 401（`APP_TOKEN_INVALID`，對外不區分原因）並寫 deny 審計。`/api/mcp/*` 不受影響，legacy token 維持原始 read-only 面。新 team app token 的 `is_legacy=False` 不受影響。此法優於在 resolver 直接拒絕（resolver 為 mcp/app 共用），確保 `/api/mcp/*` 行為不變。

**D6 — 審計保留掛上 scheduler，重排緩衝設上限。**
於 scheduler `service_registry` 新增一個 audit cleanup service definition（runner 呼叫 `audit_service.cleanup_old_records(AUDIT_CLEANUP_DAYS)`），採 daily schedule。另為 audit 寫入失敗時的 in-memory 重排 buffer 設定最大長度，超限丟棄最舊並記一筆 warning（避免 OOM）。

**D7 — `expires_in_days` 邊界驗證。**
在 `AppTokenCreateRequest.expires_in_days` 加 `ge=0` 與合理上限（例如 `le=3650`，10 年），超界回 422，避免負值（即建即過期）與極大值造成的 `timedelta` OverflowError → 500。

**D8 — attachment 刪除改回 404 且以 team 過濾。**
`_delete_attachment_common` 在 app-token 路徑以 `id + team_id` 過濾查詢，找不到即回 404，消除目前 409 訊息洩漏所屬 team 的存在性 oracle。需確認 JWT 路徑行為不受影響（若共用，於 app-token 呼叫端傳入 team 過濾參數）。

**D9 — 讀取回應遮蔽 credential 類 test_data。**
在 `/api/app/*` 與 `/api/mcp/*` 的 test case 詳情 payload 組裝處，對 `category=="credential"` 的 test_data value 做遮蔽（比照審計層 `_redact_details` 的語意），確保讀 principal 無法取得明文憑證測資。

## Risks / Trade-offs

- **D1 可能拒絕既有含特殊字元的編號**：現實中 test_case_number 形如 `TCG-93178.010.010`，不含路徑字元，風險低；仍需跑既有測試確認無回歸。
- **D5 對已改用 `/api/app/*` 的 legacy client 為 BREAKING**：這些 client 應改用正式 team app token。屬刻意收斂，需在 tasks 的相容性說明中標註並通知既有 legacy token 使用者。
- **D4 per-worker 限流在多 worker 部署下每 IP 實際額度為 N 倍**：可接受（目的是擋單源洪泛，非精準配額）；分散式限流另案。
- **D6 cleanup 首次執行可能刪除大量歷史審計**：`AUDIT_CLEANUP_DAYS` 預設 365，首次執行前應確認保留天數符合稽核政策；cleanup 走既有 batch 刪除，非破壞性 schema 變更。
- **無 schema 變更、無 migration**：全部為程式與設定調整，rollback 為還原程式碼即可。
