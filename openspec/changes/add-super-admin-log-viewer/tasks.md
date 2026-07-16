# Tasks: add-super-admin-log-viewer

## 1. 設定與 Log 捕捉層

- [x] 1.1 在 `app/config.py` 新增 `LogViewerConfig`（比照既有 `XxxConfig.from_env()` 模式）並掛進 `Settings`：buffer_size / max_streams / max_message_chars / subscriber_queue_size / keepalive_seconds（合法 5–60）/ stream_max_lifetime_seconds（合法 60–3600），每項定義合法範圍（含下限），範圍外或非法值 fallback 預設；另實作 per-worker aggregate budget（buffer `buffer_size × max_message_chars` 與訂閱端 `2 × max_streams × subscriber_queue_size × max_message_chars`——係數 2 計 local batch 峰值——各 ≤ 2^25 字元，超出整組回落預設並記 warning）；同步更新 `.env.example`
- [x] 1.2 新增 `RingBufferLogHandler`：deque maxlen、結構化 record（seq/timestamp/level/logger/message/pid）、`handler.format()` 保留 exc_info traceback 與多行、截斷附標記、`emit()` 永不拋出且不遞迴記錄、`worker_instance_id`（pid + 啟動識別）
- [x] 1.3 實作並行模型（**有界 handoff + 合併喚醒 + 單一緩衝，不得每筆 log 排程一個 callback**）：單一 `threading.Lock` 保護 buffer/seq 配號/訂閱者 registry；每訂閱者一個 lock 保護的有界 pending deque（唯一共享緩衝，滿即淘汰最舊）＋ `wakeup_scheduled` flag ＋ `wake_event`，僅 `False → True` 時排程一次 `call_soon_threadsafe(wake_event.set)`（callback 不搬資料）；**generator 於 `await wake_event.wait()` 後在 lock 內自取 batch、清空 pending、清 event 與 flag（同一 critical section），lock 外逐筆消費**；排程失敗或 loop 關閉靜默移除訂閱者，任何例外不得進 event loop exception handler；訂閱建立於同一 critical section 內完成「註冊 pending + 複製 replay snapshot + 記 `replay_latest_seq`」，lock 外先回放 `seq <= replay_latest_seq` 再消費 `seq > replay_latest_seq`；snapshot 於 lock 內複製
- [x] 1.4 新增 redact filter（大小寫不敏感：Bearer token、類 JWT、`password`/`secret`/`api_key`/`access_token`/`refresh_token`/`client_secret`/`token`/`authorization` 於 key=value、URL query、JSON `"k": "..."`、Python dict repr `'k': '...'` 格式），僅在 API 輸出路徑套用
- [x] 1.5 在 `app/main.py` logging 初始化處掛載 handler 到 root logger 與 `uvicorn.access` / `uvicorn.error`（處理 propagate=False），掛載 idempotent，stdout handler 不動
- [x] 1.6 撰寫捕捉層測試：容量淘汰、截長標記、emit 例外吞掉、跨 thread emit、併發 snapshot/append、pending 滿即淘汰最舊且 **event loop exception handler 不得收到例外**、**大量 emit 且 event loop 暫不 yield 時每訂閱者至多一個 outstanding wakeup（不隨 log 筆數成長）**、**wakeup callback 已執行但 generator 尚未取 batch 期間持續 emit 的交錯測試（callback 數與 pending 均有界、generator 最終取得資料）**、**訂閱建立瞬間持續寫入 log 的交錯測試（無遺失、無重複）**、redact 各格式與大小寫變體、idempotent 掛載、root 與兩個 uvicorn logger 各恰好捕捉一次且 stdout 格式數量不變、config 極端值/低於下限 fallback 與**單欄位合法但組合超預算的 aggregate budget 測試** → `uv run pytest app/testsuite/<new> -q`

## 2. Super Admin API

- [x] 2.1 在 `app/api/admin.py` 新增 `GET /api/admin/system-logs` 快照端點：僅 level（最低門檻）/ logger（前綴）/ limit（預設 500、上限 2000 clamp、**tail 語意：篩選後取最新 N 筆再依 seq 遞增回傳**）參數、**無 keyword 參數**、回傳含 worker_instance_id/pid/oldest_seq/latest_seq、`Cache-Control: no-store` + `Pragma: no-cache`、`require_super_admin()` + `include_in_schema=False`
- [x] 2.2 新增 `GET /api/admin/system-logs/stream` SSE 端點：`meta`/`log`/`gap`/`end` event 契約、`id:` 帶 seq、精確續傳語意（instance 不符或缺 instance_id 全量回放；`since_seq < oldest_seq - 1` 才送 gap 且 `lost_count = oldest_seq - since_seq - 1`；`since_seq = oldest_seq - 1` 完整回放不送 gap；`since_seq > latest_seq` 或非法視為 reset 全量回放；空 buffer 時 oldest/latest 為 null、直接進即時推送）、**`since_seq` 以 raw string（`str | None`）宣告並於 handler 內解析（非整數不得被 FastAPI 提前 422）**、keep-alive comment、`no-store`/`Pragma`/`X-Accel-Buffering: no`、連線數上限回 429、最大生命週期屆期送 `end` 關閉
- [x] 2.3 以 try/finally 保證 disconnect / cancel / 例外 / 屆期任一路徑解除訂閱並釋放 stream slot
- [x] 2.4 串流成功建立（取得 slot、首個 event 前）呼叫 `audit_service.log_action`：`ActionType.READ`、`ResourceType.SYSTEM`、`resource_id="system-logs-stream"`、details 含 instance_id 與 since_seq、帶 ip_address/user_agent；audit 停用或失敗不阻斷串流
- [x] 2.5 撰寫 API 測試（鎖定完整 URL `/api/admin/system-logs*`）：非 Super Admin 401/403、快照 200 與 level/logger 語意、limit clamp 與 **tail 取最新 N 筆**、SSE meta/存量回放/instance 不符全量回放、**since_seq 邊界全覆蓋**（`oldest_seq - 1` 不送 gap、`< oldest_seq - 1` 送 gap 且 lost_count 正確、`> latest_seq` reset、缺 instance_id 全量、空 buffer null 邊界、**`since_seq=abc` 與 `since_seq=-1` 均回 200 SSE 全量回放而非 422**）、429、生命週期屆期 end、disconnect cleanup（slot 釋放後可再連）、redact 生效、audit 寫入與 audit 失敗不阻斷、**`/openapi.json` 不含兩個 system-log 端點**、**兩端點的 `Cache-Control`/`Pragma`（串流另含 `X-Accel-Buffering`）headers 斷言** → `uv run pytest app/testsuite/<new> -q`

## 3. 前端頁面

- [x] 3.1 在 `app/main.py` 新增 `/system-logs` 頁面 route 與 `app/templates/system_logs.html`（繼承 `base.html`、沿用既有 components 與 design token）、`app/static/css/system-logs.css`
- [x] 3.2 實作 `app/static/js/system-logs.js` 串流核心：fetch + ReadableStream、SSE parser 與 highlight segmenter 抽成 **DOM-free 純函式**（Node 無 `document` 可測，不引入 jsdom）、處理 meta/log/gap/end、斷線與屆期自動以 since_seq + instance_id 重連並以 **exponential backoff + jitter 退避**（429 遵循 `Retry-After`、收到 meta 後重置）、401/403 停止重連並顯示未授權狀態、**meta instance 與現有資料不同時清空資料模型/DOM/cursor 並插入「資料來源已切換」標示（不得混用不同 instance 的 seq）**
- [x] 3.3 實作安全渲染兩層：**DOM-free 純函式 highlight segmenter**（輸入文字與 keyword、輸出片段結構，keyword regex 特殊字元 escape）＋ **thin DOM assembler**（以 textContent / createTextNode 建立 text node 與 `<mark>` 元素落地片段，禁止 innerHTML 插入未 escape 內容）；Node 測試測 segmenter，assembler 由瀏覽器煙霧測試驗證（task 4.3）
- [x] 3.4 實作 UI 功能：即時 tail 與自動捲動（上捲暫停、回底恢復）、暫停/續播（**暫停 = 停止 DOM 更新與捲動，串流與資料模型持續接收；續播重繪**）、level/logger 篩選（一鍵隱藏 `uvicorn.access`）、**前端** keyword 篩選與 highlight（不送伺服器）、seq 缺口與 gap event 顯示「遺失 N 筆」、清空畫面、下載 .txt、常駐顯示 instance/PID、前端上限 5000 筆（**DOM 與底層 record 陣列同步環形淘汰**，不得只清 DOM）
- [x] 3.5 在 `team_management.html`「數據與記錄」下拉選單新增入口，僅 super_admin 顯示（實作採該頁既有 ui-config 權限機制：`ui_capabilities.yaml` 新增 `systemLogsLink: organization_management:manage`；原規劃的 `window.currentUser` 判斷在該頁有載入時序 race，見 design D5）
- [x] 3.6 三語系文案：`app/static/locales/en-US.json`、`zh-CN.json`、`zh-TW.json` 同步新增，動態 DOM 使用 `data-i18n` lifecycle
- [x] 3.7 撰寫 Node 測試（`app/testsuite/js/system-logs.test.mjs`，以 `node --test` 執行、helper 均 DOM-free）：highlight segmenter（惡意 HTML `<img onerror=…>`、`<script>`、引號、換行、regex 特殊字元）、**SSE parser**（事件跨任意 chunk boundary、同 chunk 多事件、UTF-8 多位元組字元拆段、keep-alive comment、結尾不完整 frame）、**backoff 計算（含 429 `Retry-After` 與 meta 重置）、401/403 停止重連判斷、5000 筆環形淘汰、instance 切換 reset**；另加頁面 route/靜態資產存在的 pytest 煙霧測試
- [x] 3.8 前端驗證：`node --check app/static/js/system-logs.js`、**`node --test app/testsuite/js/system-logs.test.mjs`**、`node scripts/check-i18n-coverage.mjs`、`npm run lint`

## 4. 文件與收尾

- [x] 4.1 撰寫運維說明文件：env 參數一覽與預設/上限、aggregate budget 規則、**所有容量均為 per-worker（總量乘 `WEB_CONCURRENCY`）**、多 worker 視野限制、重啟即清空、啟動失敗以 `docker logs` fallback
- [x] 4.2 本次新增／修改 Python 檔 targeted Ruff 通過；全 repo `uv run ruff check app scripts database_init.py` 仍有 218 個既有 testsuite lint errors，未擴張本 change scope 清理
- [x] 4.3 瀏覽器實測：Super Admin 開頁即時 tail、篩選/highlight、暫停、gap 標示、下載；非 Super Admin 看不到入口且 API 被拒；含惡意字串 log 以純文字呈現
- [x] 4.4 跑受影響範圍測試（`uv run pytest app/testsuite -q` 或依風險縮小），確認無回歸——已跑：新增兩測試檔 59 passed、`test_permission_ui_config.py` 2 passed、`test_reporting_statistics_api.py` 3 passed（db_test_helpers 修復驗證）、`test_app_token_test_case_api.py` 30 passed；2026-07-16 複查全套執行至 92 passed / 約 8% 後再次停滯於本機資料庫相依，停滯前無 failure；全套回歸另由使用者手動驗證
- [x] 4.5 `openspec validate add-super-admin-log-viewer --strict` 通過

## 5. 實作複查修正

- [x] 5.1 修正 redaction：一般三段式 JWT-like token、含空白的 JSON / Python repr quoted secret、Authorization scheme credential 均完整遮罩，補 regression tests
- [x] 5.2 修正 stream slot ownership：audit await 期間取消及 subscribe 失敗均釋放 slot，generator cleanup 採 idempotent release，補 cancellation / exception tests
- [x] 5.3 修正前端 paused notice 與環形淘汰：暫停期間 notice 進有界 queue、續播後落地；model 回傳淘汰 seq 供 DOM 精確同步移除；system-log CSS 全面使用既有 `--tr-*` tokens
- [x] 5.4 複查 gates：system-log Python 65 passed、受影響既有測試 35 passed、Node 17 passed、targeted Ruff / JS syntax / i18n / npm lint / OpenSpec strict validation / diff check 通過
