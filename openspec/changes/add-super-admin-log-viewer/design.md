# Design: add-super-admin-log-viewer

## Context

- 應用 log 現況：`app/main.py:51` 的 `logging.basicConfig(level=logging.INFO)` 與 `app/utils/logging.py` 的 `setup_app_logging()` 都只掛 StreamHandler，log 僅存在於容器 stdout，唯一檢視手段是 `docker logs` 或 SSH。
- 部署現況：`docker/app-entrypoint.sh` 以 uvicorn 啟動，`WEB_CONCURRENCY` 預設 1、可 >1；`restart: unless-stopped`。
- 權限現況：`app/auth/dependencies.py` 已有 `require_super_admin()`；`app/api/admin.py` 的 admin router（prefix `/admin`）經 `api_router` 掛載於 `/api` 之下（`app/main.py:138`），故 admin 端點實際路徑為 `/api/admin/...`。
- 認證是 Bearer token（HTTPBearer）：瀏覽器 `EventSource` 無法帶 Authorization header，但 repo 已有 fetch + `StreamingResponse` SSE 前例（QA AI Helper MAGI inspection，`app/api/qa_ai_helper.py`）。
- Audit 現況：`app/audit/audit_service.py` 提供 `log_action(...)`（含 `ActionType.READ`、`ResourceType.SYSTEM`、ip/user_agent 欄位）；audit 停用時直接略過、寫入失敗會吞錯記 log——audit 是 best-effort，設計須與此一致。
- 設定現況：`app/config.py:519` 的 `Settings` 以子設定物件組合（各 `XxxConfig.from_env()`），新設定應整合於此，不散落讀 env。
- 導覽現況：`/audit-logs` 入口位於 `app/templates/team_management.html` 的「數據與記錄」下拉選單；前端以 `base-auth.js` 的 role 判斷控制顯示。

## Goals / Non-Goals

**Goals:**

- Super Admin 登入 TCRT 後，不需主機權限即可即時 tail 應用 log（含 uvicorn access/error log）。
- stdout 輸出行為零改動：`docker logs` 永遠是完整、權威的 log 來源；本功能是唯讀的旁路副本。
- log 暴露面受控：Super Admin only、輸出前 redact、串流開啟寫 audit、回應不可快取、前端安全渲染（log 視為未受信任輸入）。
- 記憶體、連線數、串流生命週期均有硬上限；功能任何元件故障不得影響主服務。

**Non-Goals:**

- 不落地 log 檔案、不新增 volume、不改 entrypoint。
- 不做歷史查詢（重啟即清空）；app 起不來時的 fallback 是 `docker logs`。
- 不做跨 worker log 聚合（v1 以 instance 識別讓限制透明並保證續傳正確性）。
- 不引入外部 log stack（ELK / Loki / promtail 等）。

## Decisions

### D1. 捕捉方式：額外掛載 in-memory ring buffer handler（明確定義並行模型）

在 root logger 另掛自訂 `RingBufferLogHandler`（`collections.deque(maxlen=N)`），並對 `uvicorn.access` / `uvicorn.error` 個別附加（兩者可能 `propagate=False`）。

**Record 結構**：`{seq, timestamp, level, logger_name, message, pid}`。

- `seq`：單調遞增序號（於 buffer lock 內配號）。
- `timestamp`：ISO 8601 UTC 含毫秒。
- `message`：以 `handler.format(record)` 產生的完整格式化結果——**包含 `exc_info` traceback 與 stack info**，多行內容保留原樣；超過單條長度上限（`max_message_chars`）時截斷並附上 `…[truncated]` 標記。

**並行模型（logging 來自任意 thread，SSE 消費在 event loop）**：

- buffer、seq 配號、訂閱者 registry 由同一把 `threading.Lock` 保護；`emit()` 在 lock 內完成「配號 + append + 投遞到各訂閱者的 pending 結構」。
- **跨 thread 投遞採「有界 handoff + 合併喚醒」，不得每筆 log 排程一個 event-loop callback**。理由：即使 `asyncio.Queue` 有界並捕捉 `QueueFull`，`loop.call_soon_threadsafe(...)` 每筆一次仍會在 event loop ready queue 無界累積尚未執行的 callback（各自持有 record）——producer 快於 event loop 時，有界 queue 只約束 callback 執行後的狀態，約束不了 callback backlog。設計如下：
  - 每個訂閱者持有一個受同一把 lock 保護的**有界 pending deque**（`maxlen = subscriber_queue_size`）；`emit()` 直接 append，滿時由 deque 淘汰最舊未投遞筆（掉的訊息由 seq 缺口呈現，見 D2）。
  - 每個訂閱者維護 `wakeup_scheduled` flag（lock 內讀寫）：僅在 `False → True` 轉換時排程**一次**喚醒 callback；callback 只負責 `wake_event.set()`（`asyncio.Event`），**不搬移任何資料**；loop 已關閉或排程失敗時靜默移除該訂閱者。
  - **取資料由 generator 自己完成**（單一緩衝模型，pending deque 是唯一共享緩衝）：

    ```text
    emit（任意 thread）:
      lock 內 append pending；wakeup_scheduled False→True 時
      call_soon_threadsafe(wake_event.set)

    generator（event loop）:
      await wake_event.wait()
      lock 內：batch = pending 全部；pending.clear()；
               wake_event.clear()；wakeup_scheduled = False
      lock 外逐筆消費 batch（redact、送 SSE frame）
    ```

  - race-safety：flag / event / pending 的狀態轉換都在同一 critical section 完成；flag 清除後才發生的新 emit 會觸發下一次喚醒，不漏訊息。generator 取走的 local batch 是消費中的瞬時資料（單一 batch ≤ pending 上限），不構成第二個共享緩衝；但 generator 持有 batch 期間 pending 可再度填滿，**每訂閱者暫存峰值為 pending 上限的 2 倍**，aggregate budget（D7）依此計算。
  - 效果：無論 log 產生多快，每個訂閱者同時至多一個 outstanding wakeup callback，backlog 不隨 log 筆數成長；event loop 不會收到任何例外；log 寫入路徑永不阻塞。
- **訂閱建立必須原子化**：在同一個 critical section（同一把 lock）內完成「註冊 pending deque + 複製 replay snapshot + 記下 `replay_latest_seq`」；lock 釋放後先回放 `seq <= replay_latest_seq` 的存量，再消費 pending 中 `seq > replay_latest_seq` 的事件。此順序保證訂閱瞬間產生的 log 既不遺失（先 snapshot 後註冊的 lost-update）也不重複（先註冊後 snapshot 的雙路徑送達）。
- snapshot 讀取同樣在 lock 內複製後回傳，避免與 append 併發迭代。
- **掛載 idempotent**：以 handler 單例 + 掛載前檢查（同型 handler 已存在即跳過），避免 reload / 測試重複掛載造成重複捕捉。
- `emit()` 全程 try/except 包覆、永不拋出；handler 內部不呼叫 logging（防遞迴）。

**instance 識別**：handler 初始化時產生 `worker_instance_id = "<pid>-<啟動亂數>"`，用於跨重啟/跨 worker 的續傳正確性（見 D2、D6）。

- 為什麼不改寫/轉向現有 handler：stdout 是 docker 慣例與使用者明確要求，旁路複製風險最小。
- 為什麼不用檔案（曾評估 named volume boot log）：使用者決策——容器內不落檔，維持 stdout 單一事實來源。

### D2. 傳輸：SSE（`StreamingResponse` + async generator），契約明確化

沿用 QA AI Helper 的既有模式，不引入 WebSocket。

**SSE frame 契約**：

- `id:` 帶該筆 record 的 `seq`；`data:` 為 record 的 JSON。
- `event: meta`——連線建立後的第一個 event，內容含 `{worker_instance_id, pid, oldest_seq, latest_seq, buffer_size, stream_max_lifetime_seconds}`。
- `event: log`——一般 log record。
- `event: gap`——伺服器無法從 `since_seq` 完整回放（已被淘汰）時送出，內容含估計遺失筆數。
- `event: end`——串流達最大生命週期由伺服器主動收尾時送出。
- keep-alive：每 `keepalive_seconds` 送一行 SSE comment（`: keep-alive`）。

**續傳語意（精確定義，令 buffer 目前範圍為 `[oldest_seq, latest_seq]`）**：

- client 帶 `since_seq` 與 `instance_id`。instance 不符（worker 不同或已重啟）、只帶 `since_seq` 未帶 `instance_id`、或 `since_seq` 非法（非整數、負數）→ 一律忽略 cursor，送 `meta` 後全量回放 buffer。
- **`since_seq` 以 raw string 參數宣告（`str | None`）、handler 內自行解析**——若宣告為 `int` 型別，FastAPI 會在進入 handler 前對非整數回 422，違反「非法視為 reset、以 200 建立串流」的契約。
- instance 相符時：
  - `oldest_seq - 1 <= since_seq <= latest_seq` → 完整回放 `seq > since_seq`，**不送 gap**（`since_seq = oldest_seq - 1` 恰可完整涵蓋，非遺失）。
  - `since_seq < oldest_seq - 1` → 確有遺失：先送 `gap`，`lost_count = oldest_seq - since_seq - 1`，再從 `oldest_seq` 回放。
  - `since_seq > latest_seq` → cursor 不可信（超前於伺服器），視同 reset：忽略 cursor、全量回放。
- 空 buffer 時 `oldest_seq` / `latest_seq` 為 `null`：無存量可回放、不送 gap，直接進入即時推送。

**背壓**：訂閱者 pending deque 滿即淘汰最舊未投遞筆（D1）；client 由 `id` 序號缺口與 `gap` event 察覺（前端行為見 D5）。

**回應 headers（快照與串流皆同）**：`Cache-Control: no-store`、`Pragma: no-cache`；串流另加 `X-Accel-Buffering: no`。

### D3. API：掛在既有 admin router，實際路徑為 `/api/admin/...`

admin router prefix 是 `/admin`，再經 `api_router` 掛上 `/api`（`app/main.py:138`），完整路徑：

- `GET /api/admin/system-logs`——快照查詢。參數僅 `level`、`logger`、`limit`；**不提供 keyword 參數**（理由見 D4）。
  - `level`：最低門檻語意（如 `WARNING` 回傳 WARNING 含以上）。
  - `logger`：logger 名稱前綴比對。
  - `limit`：預設 500，伺服器上限 2000（超過即 clamp）。**語意為 tail**：先套 level/logger 篩選、取「最新 N 筆」，再依 `seq` 遞增排序回傳（不得升冪後取前 N 筆而拿到最舊資料）。
  - 回傳依 `seq` 遞增排序，並附 `worker_instance_id`、`pid`、`oldest_seq`、`latest_seq`。
- `GET /api/admin/system-logs/stream`——SSE 串流（契約見 D2），支援 `since_seq` + `instance_id`；同時連線達 `max_streams` 回 429。

兩者 `Depends(require_super_admin())` + `include_in_schema=False`。API 測試直接鎖定完整 URL（`/api/admin/system-logs*`）。

**串流授權生命週期**：`Depends` 只在建立連線時驗證，token 到期或降權後既有連線不會自動失效。因此：

- 串流有最大生命週期 `stream_max_lifetime_seconds`（預設 900 秒），屆時送 `event: end` 並關閉；前端重連時整條 auth 鏈重新驗證，權限已失效者收到 401/403。
- 前端收到 401/403 即停止重連並呈現未授權狀態（見 D5）。
- 權限失效的最大暴露窗即一個 lifetime 週期，spec 明文記載此界限。

**Audit 契約**：串流「成功建立」（通過權限檢查且取得 stream slot、送出首個 event 之前）時呼叫 `audit_service.log_action`：`ActionType.READ`、`ResourceType.SYSTEM`、固定 `resource_id="system-logs-stream"`、`details` 含 `worker_instance_id` 與 `since_seq`，並帶 `ip_address` / `user_agent`。與既有 service 行為一致採 **best-effort**：audit 停用或寫入失敗不阻斷串流（錯誤由 service 記 log）。快照查詢不逐筆記 audit（避免噪音）。

**連線清理**：SSE generator 以 try/finally 保證 client disconnect、cancel、例外任一路徑都解除訂閱並釋放 stream slot；配套測試涵蓋 disconnect cleanup。

### D4. Keyword 完全在前端處理；redact 於輸出前套用

**keyword 不進 API**：GET query 會被 uvicorn access log 記錄完整 request line——使用者若貼 token 或敏感字串搜尋，會回寫進本功能自己的 buffer、瀏覽器歷史與 proxy log。故快照 API 僅 `level`/`logger`/`limit`，keyword 篩選與 highlight 完全在前端對已取得的資料進行（資料量受 buffer 與前端行數上限約束，前端篩選成本可接受）。

- 已評估替代方案「POST search endpoint」：可避免 URL 洩漏，但增加端點面積且前端已握有全量資料，無必要。

**redact filter**：buffer 存原始訊息、API 輸出前才遮罩。理由：redact 規則可演進而不影響已捕捉資料；log 熱路徑不付 regex 成本。pattern 覆蓋（大小寫不敏感）：

- `Bearer <token>` 與獨立的類 JWT 字串（`xxx.yyy.zzz` base64url 形態）。
- 常見秘密欄位名的賦值形態，欄位名至少含 `password`、`secret`、`api_key`、`access_token`、`refresh_token`、`client_secret`、`token`、`authorization`，格式涵蓋：
  - `key=value`（env / query 形態，含 URL query string 中的 `?token=...&`）。
  - JSON：`"access_token": "..."`。
  - Python dict repr：`'api_key': '...'`。

### D5. 前端頁面：獨立 `/system-logs`，log 視為未受信任輸入

- `app/main.py` 加 route → `app/templates/system_logs.html`（繼承 `base.html`）；邏輯在 `app/static/js/system-logs.js`，樣式在 `app/static/css/system-logs.css`（用既有 design token）。
- 串流用 fetch + `ReadableStream` 解析 SSE（帶 Bearer header）；斷線與 `event: end` 後自動以 `since_seq` + `instance_id` 重連；收到 401/403 停止重連、顯示未授權狀態並提示重新登入。
- **重連退避**：exponential backoff + jitter（如 1s 起、上限 30s）；429 回應遵循 `Retry-After`；成功收到 `meta` 後重置 backoff。避免 server 停機或持續 429/500 時形成緊密重連迴圈。
- **SSE parser 抽成可獨立測試的純函式**（餵 chunk、吐 event），測試涵蓋：事件跨任意 chunk boundary、同一 chunk 多事件、UTF-8 多位元組字元被拆段、keep-alive comment 行、結尾不完整 frame 的暫存。

**XSS 契約（log message 與 keyword 都是未受信任輸入）**：

- log 內容一律以 `textContent` / `document.createTextNode` 寫入 DOM；keyword highlight 以「切分文字片段 + 建立 `<mark>` 元素」實作，**禁止**將未 escape 的 log 或 keyword 組字串塞進 `innerHTML`。
- keyword 用於比對前先 escape regex 特殊字元。
- render/highlight helper 抽成可獨立測試的純函式，測試涵蓋惡意 HTML（`<img onerror=…>`）、引號、換行、regex 特殊字元。

**功能**：即時 tail + 自動捲動（手動上捲暫停跟隨、回底部恢復）、暫停/續播、level 與 logger 篩選（一鍵隱藏 `uvicorn.access`）、keyword 前端篩選與 highlight、清空畫面、下載目前畫面內容為 .txt（前端組檔）、常駐顯示 `worker_instance_id` / PID。

**暫停語意**：「暫停」= 停止 DOM 更新與自動捲動，但串流連線與資料模型持續接收（仍受環形上限約束）；「續播」時以資料模型重繪。這使暫停期間不失去即時資料，同時記憶體有界。

**丟訊息的 UI 行為**：偵測到 seq 缺口或收到 `gap` event 時，於 log 流中插入「遺失 N 筆」標記；重連時由 buffer 回放自然回補仍在 buffer 內的部分。

**前端行數上限**：`FRONTEND_MAX_LINES`（5000，JS 常數）同時約束 **DOM 與底層 record 陣列**——JS 為了重新篩選而保留的資料模型與畫面同步環形淘汰最舊筆，兩者都有界；不得只移除 DOM row 而讓 record 陣列無界成長。

**worker instance 切換的前端處理**：頁面資料只來自 SSE 的 `meta` + replay（不另行無條件合併快照 API 的資料）。重連收到的 `meta.worker_instance_id` 與目前資料模型的 instance 不同時，**清空既有 record 陣列、DOM 與 cursor**，插入「資料來源已切換」標示後接受新 worker 的全量回放——不得將新舊 instance 的 seq 混在同一序列（會造成錯誤的 gap 判斷與排序）。

**測試性**：渲染/highlight helper 與 SSE parser 均設計為 DOM-free 純函式（highlight 回傳片段結構、由薄薄一層 DOM 組裝器落地），Node 環境無 `document` 也可直接以 `node --test` 驗證；不為此引入 jsdom 等新依賴。

**導覽入口**：加在 `team_management.html`「數據與記錄」下拉選單（與 `/audit-logs` 同處），項目預設 `d-none`，由該頁既有的 `/api/permissions/ui-config` 機制決定顯示——`config/permissions/ui_capabilities.yaml` 新增元件 `systemLogsLink: { feature: organization_management, action: manage }`（Casbin 中僅 super_admin 對該 feature 有 `.*`，admin 只有 view）。實作時原規劃的 `window.currentUser.role` 判斷在該頁不可靠（載入時序 race），故改用與同頁其他元件一致的權限驅動機制；前端 gating 是 UX，後端 `require_super_admin()` 是真正防線。i18n 用 `data-i18n` lifecycle，三語系同步。

### D6. 多 worker 行為：明示而非解決，續傳以 instance 識別保證正確性

SSE 連線由單一 worker 處理，只見該 worker 的 buffer。單靠 `since_seq` 不足：重連落到另一 worker 時序號會碰撞或長期無資料。故 `meta` event 與快照回應皆帶 `worker_instance_id`，client 發現 instance 改變即拋棄舊 cursor、接受全量回放（見 D2）。UI 常駐顯示 instance/PID。預設 `WEB_CONCURRENCY=1`，現況無感；未來若需聚合再開新 change。

### D7. 設定：集中於 `app/config.py`，全部有預設值與硬上限

新增 `LogViewerConfig`（比照既有 `XxxConfig.from_env()` 模式）加入 `Settings`（`app/config.py:519`），不散落讀 env：

| 設定 | env | 預設 | 硬上限 |
|---|---|---|---|
| buffer 筆數 | `LOG_VIEWER_BUFFER_SIZE` | 2000 | 20000 |
| 同時串流數 | `LOG_VIEWER_MAX_STREAMS` | 3 | 10 |
| 單條訊息字元數 | `LOG_VIEWER_MAX_MESSAGE_CHARS` | 4096 | 65536 |
| 訂閱 pending deque 深度 | `LOG_VIEWER_SUBSCRIBER_QUEUE_SIZE` | 1000 | 10000 |
| keep-alive 間隔（秒） | `LOG_VIEWER_KEEPALIVE_SECONDS` | 15 | 合法範圍 5–60 |
| 串流最大生命週期（秒） | `LOG_VIEWER_STREAM_MAX_LIFETIME_SECONDS` | 900 | 合法範圍 60–3600 |

非法值一律 fallback 到預設值，不失敗、不放行極端值。「非法」定義為：非正整數、超過上限，**或低於表列合法範圍的下限**（如 keepalive 1–4 秒、lifetime 低於 60 秒——過短的 lifetime 會造成持續重連與 audit 噪音）。純容量欄位下限為 1。`FRONTEND_MAX_LINES=5000` 為 JS 常數（純前端顯示界限，不需後端 env）。

**跨欄位 aggregate budget**：單欄位上限各自安全不代表組合安全（`20000 × 65536` 字元相乘已達 GiB 級）。故加一條固定預算（程式常數，非 env）：

- `buffer_size × max_message_chars <= 33,554,432`（2^25 字元；以 Python 最寬 4 bytes/char 估計，worst case 約 128 MiB/worker）。
- 訂閱端：`2 × max_streams × subscriber_queue_size × max_message_chars` 也須不超過同一預算（係數 2 計入 generator 持有 local batch 期間 pending 再度填滿的峰值，見 D1）。
- 任一組合超出預算 → **整組相關欄位回落預設值**（規則單一、可預期，不做部分 clamp 的複雜協商），並記一條 warning log。
- 所有容量皆為 **per-worker**；總記憶體還需乘上 `WEB_CONCURRENCY`，運維文件明載。
- config 測試涵蓋「單欄位皆合法但組合超預算」的極端組合。

## Risks / Trade-offs

- [log 含敏感資料被瀏覽器端看到] → Super Admin only + 輸出前 redact + audit 存取紀錄 + `Cache-Control: no-store`；不記 secret 仍是第一原則。
- [log 內容注入 XSS] → textContent/`<mark>` 片段渲染契約 + helper 純函式測試（D5）。
- [keyword 洩漏至 access log / proxy / buffer] → keyword 不離開前端（D4）。
- [權限失效後串流殘留] → 串流最大生命週期 + 重連重新驗證 + 401/403 停止重連；暴露窗上限為一個 lifetime 週期（D3）。
- [跨 thread 投遞與並發迭代 race / callback backlog 無界] → 單一 lock 保護 buffer/seq/registry、有界 pending deque + 合併喚醒（每訂閱者至多一個 outstanding callback）、訂閱註冊與 replay snapshot 原子化、snapshot 複製後回傳、掛載 idempotent（D1）。
- [buffer / 訂閱 pending 佔用記憶體] → 所有容量參數有預設與硬上限、跨欄位 aggregate budget 防組合爆量（D7）、單條截長、pending 滿即淘汰最舊、連線數上限。
- [handler 故障影響主服務] → `emit()` 永不拋出、不遞迴記錄；viewer 元件故障只導致 viewer 不可用。
- [SSE 經 proxy 被緩衝] → `X-Accel-Buffering: no` + keep-alive comment。
- [啟動失敗時 viewer 無法使用] → 接受的取捨（Non-goal）；stdout 未動，`docker logs` 完整可用。
- [多 worker 視野不全 / 續傳錯亂] → `worker_instance_id` 識別 + instance 變更即全量回放 + UI 常駐顯示（D6）。
- [audit best-effort 與稽核期望落差] → spec 明文採「嘗試寫入、失敗不阻斷」，與既有 audit service 行為一致，不另造絕對保證。

## Migration Plan

無 DB schema 變更、無 migration。部署即生效；rollback 即還原程式碼（無持久化狀態需清理）。新 env 均有安全預設值，未設定不影響啟動。運維文件（env 一覽、多 worker 限制、重啟清空、`docker logs` fallback）隨 change 一併交付。

## Open Questions

（無——範圍已與使用者於 2026-07-16 收斂：即時 tail only、含 access log、不落檔；review 回饋已於同日全數納入本版。）
