# Super Admin 系統 Log Viewer 運維說明

最後更新：2026-07-16（openspec change: `add-super-admin-log-viewer`）

`/system-logs` 提供 Super Admin 在瀏覽器即時 tail 應用 log（含 `uvicorn.access` / `uvicorn.error`），
不需 SSH 或 `docker logs`。實作為 in-memory ring buffer 旁路副本：**stdout 輸出完全不變，
`docker logs` 永遠是完整且權威的 log 來源**。

## 環境變數

所有容量均為 **per-worker**；`WEB_CONCURRENCY > 1` 時總記憶體需乘上 worker 數。
範圍外、非正整數或無法解析的值一律**自動回落預設值**（不會啟動失敗），並記一條 warning log。

| 變數 | 預設 | 合法範圍 | 說明 |
|---|---|---|---|
| `LOG_VIEWER_BUFFER_SIZE` | 2000 | 1–20000 | in-memory buffer 保留筆數 |
| `LOG_VIEWER_MAX_STREAMS` | 3 | 1–10 | 同時 SSE 串流連線數（超過回 429） |
| `LOG_VIEWER_MAX_MESSAGE_CHARS` | 4096 | 1–65536 | 單條訊息字元上限（超長截斷並附 `…[truncated]`） |
| `LOG_VIEWER_SUBSCRIBER_QUEUE_SIZE` | 1000 | 1–10000 | 每串流 pending 佇列筆數（滿即淘汰最舊，前端以「遺失 N 筆」呈現） |
| `LOG_VIEWER_KEEPALIVE_SECONDS` | 15 | 5–60 | SSE keep-alive comment 間隔 |
| `LOG_VIEWER_STREAM_MAX_LIFETIME_SECONDS` | 900 | 60–3600 | 串流最大生命週期；屆期送 `end` 關閉，前端自動重連並重新驗證權限 |

### Aggregate budget（記憶體上限）

單欄位各自合法不代表組合安全。除單欄位範圍外另有固定 per-worker 預算（2^25 = 33,554,432 字元）：

- buffer 側：`BUFFER_SIZE × MAX_MESSAGE_CHARS` ≤ 預算
- 訂閱側：`2 × MAX_STREAMS × SUBSCRIBER_QUEUE_SIZE × MAX_MESSAGE_CHARS` ≤ 預算
  （係數 2 計入串流消費過程中 pending 再度填滿的峰值）

任一組合超出預算 → **容量欄位整組回落預設值**並記 warning（時間類欄位不受影響）。

## 已知限制

- **多 worker 視野**：一條串流只呈現處理該連線之 worker 的 log。頁面常駐顯示
  worker PID 與 instance 識別；重連落到另一 worker 時前端會清空畫面並標示「資料來源已切換」。
- **重啟即清空**：buffer 不落地。歷史紀錄請用 `docker logs`。
- **啟動失敗時 viewer 不可用**：app 起不來就沒有頁面。此時用
  `docker logs tcrt-app` —— bootstrap 失敗訊息與 crash loop 每次重試的輸出都完整在 stdout。

## 安全

- API（`GET /api/admin/system-logs`、`GET /api/admin/system-logs/stream`）僅 Super Admin 可用，
  不出現在 OpenAPI schema，回應帶 `Cache-Control: no-store`。
- 輸出前有 redact filter 遮罩疑似 secret（Bearer/JWT/常見秘密欄位賦值），屬縱深防禦；
  不把 secret 寫進 log 仍是第一原則。
- 開啟串流會寫入 audit（`READ` / `system` / `system-logs-stream`，含來源 IP 與 User-Agent）。
- 關鍵字搜尋純在瀏覽器端執行，不會出現在 URL、access log 或 proxy log。
