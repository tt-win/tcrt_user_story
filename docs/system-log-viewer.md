# Super Admin 系統 Log Viewer 運維說明

最後更新：2026-07-17（openspec changes: `add-super-admin-log-viewer`、`add-system-runtime-settings-viewer`）

`/system-logs` 提供 Super Admin 在瀏覽器即時 tail 應用 log（含 `uvicorn.access` / `uvicorn.error`），
不需 SSH 或 `docker logs`。實作為 in-memory ring buffer 旁路副本：**stdout 輸出完全不變，
`docker logs` 永遠是完整且權威的 log 來源**。

頁面以分頁組織：**Logs**（即時 log）與 **Runtime Settings**（唯讀 runtime 設定快照，見下節）。

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

## Runtime Settings 分頁

`/system-logs` 的 **Runtime Settings** 分頁透過
`GET /api/admin/system-runtime-settings`（僅 Super Admin、不進 OpenAPI、`no-store`）
唯讀顯示**處理該請求之 worker process** 的設定快照。首次切入分頁 lazy fetch 一次，
之後以「重新整理」按鈕再取。

### 快照契約摘要（固定 allowlist）

根物件恰好含 `generated_at`（UTC 秒精度 + `Z`）、`pid`、`worker_instance_id`（log handler
未安裝時為 null）、`process`、`database`、`app`、`log_viewer`，不多不少。**不回傳**任何 DB URL
字串、query、userinfo、secret、`config.yaml` 內容或檔案系統完整路徑（SQLite 僅 basename）。

### WEB_CONCURRENCY 三態

`process.web_concurrency_source` 對齊部署腳本 shell `-z` 語意（不先 strip）：

| env `WEB_CONCURRENCY` | source | 語意 |
|---|---|---|
| 未設或精確 `""` | `inferred_default` | 啟動腳本會用 main 引擎推導預設（sqlite→1、mysql/postgresql→5） |
| 合法正整數 | `configured` | 明確設定 |
| 純空白、`0`、負數、非整數 | `invalid_configured` | 設定異常；腳本**不會** fallback 到推導預設 |

`worker_count_note_code` 恒為 `not_actual_worker_count`：以上皆非實際 worker 進程數
（app 無法自知 worker 總數；reload 模式強制單 worker）。

### 結構化 DB 摘要

`database.main/audit/usm` 各為 `engine`（`sqlite`/`mysql`/`postgresql`/`other`；
`postgres://` 別名正規化為 `postgresql`）、`driver`、`host`、`port`、`database` 五欄，
無 URL、無密碼、無 query。URL 無法解析時 engine 為 `other`、其餘欄位 null，API 仍回 200。

### Worker mismatch 判定

Logs 與 Settings 可能由**不同 worker** 服務。僅當兩分頁的 `worker_instance_id`
皆為非空字串且不同時，UI 才顯示 mismatch 提示；任一方缺失時顯示「無法確認」，
**不以 PID 判定**（容器內常為 PID 1）。

### 稽核

每次快照 API 成功讀取寫一筆 best-effort audit（`READ` / `system` /
`system-runtime-settings`），來源 IP 與 User-Agent 在一級欄位，`details` 僅含
`pid` 與 `worker_instance_id`，不含快照本體；audit 失敗不影響回應。
