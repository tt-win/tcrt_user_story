# Proposal: add-super-admin-log-viewer

## Why

目前應用程式 log 只輸出到 stdout（`logging.basicConfig` + StreamHandler），要看即時 log 必須 SSH 進主機或執行 `docker logs` attach container。Super Admin 在排查線上問題（整合失敗、排程異常、使用者回報錯誤）時沒有任何網頁內的觀察手段，形成對主機存取權限的不必要依賴。

## What Changes

- 新增 in-memory ring buffer log handler：以額外 handler 形式掛載到 root logger 與 `uvicorn.access` / `uvicorn.error`，將 log record 複製一份到有上限的記憶體 buffer；**stdout 輸出行為完全不變**，`docker logs` 仍是完整且權威的 log 來源。
- 新增 Super Admin 專用 API：log 快照查詢 `GET /api/admin/system-logs` 與 SSE 即時串流 `GET /api/admin/system-logs/stream`（admin router prefix `/admin` 經 `api_router` 掛載於 `/api` 下），`require_super_admin()` 保護、`include_in_schema=False`、回應標示不可快取（`no-store`）。快照參數僅 level / logger / limit；**keyword 篩選完全在前端進行**，避免敏感搜尋字串進入 access log。
- 新增 `/system-logs` 網頁：即時 tail、暫停/續播、level 與 logger 篩選、前端 keyword 篩選與 highlight（安全 DOM 渲染，log 視為未受信任輸入）、下載目前畫面內容、顯示 worker instance/PID、斷線自動重連（401/403 即停止）；導覽入口僅 Super Admin 可見。
- log viewer 串流開啟寫入 audit（`ActionType.READ` / `ResourceType.SYSTEM`，best-effort、與既有 audit service 行為一致）；串流有最大生命週期，屆期重連並重新驗證權限，涵蓋 token 到期／降權情境。
- buffer 內容經 redact filter 遮罩疑似 secret/token 片段後才對瀏覽器輸出（縱深防禦）。
- 三語系 i18n（en-US / zh-CN / zh-TW）同步新增文案。

### 非目標（Non-goals）

- 不做 log 檔案落地、不新增 volume——維持 docker stdout 慣例（使用者明確要求）。
- 不做歷史查詢：重啟後 buffer 清空；啟動失敗（app 起不來）時以 `docker logs` 為 fallback。
- 不做跨 worker 聚合：`WEB_CONCURRENCY > 1` 時單一連線僅見處理該請求的 worker，UI 以 PID 標示透明化此限制（預設單 worker，現況無感）。
- 不引入外部 log 基礎設施（ELK、Loki 等）。

## Capabilities

### New Capabilities

- `system-log-viewer`: Super Admin 專用的即時系統 log 檢視能力——in-memory 捕捉、權限控管、SSE 串流、前端 tail UI、敏感資訊遮罩與存取稽核。

### Modified Capabilities

（無——不變更任何既有 spec 的需求；stdout logging、audit 模組、admin 權限模型皆沿用現有行為。）

## Impact

- **後端**：新模組（handler + redact filter，含明確的跨 thread 並行模型與 idempotent 掛載）；`app/main.py` 掛載 handler；`app/api/admin.py` 新增兩個端點（實際路徑 `/api/admin/system-logs*`）；audit 寫入沿用既有 `app/audit/audit_service.py`。
- **前端**：`app/main.py` 新增 `/system-logs` 頁面 route；`app/templates/system_logs.html`；`app/static/js/system-logs.js`（fetch + ReadableStream 串流，因 Bearer auth 無法用 EventSource）；`app/static/css/system-logs.css`；`app/static/locales/*.json` 三語系；`team_management.html`「數據與記錄」下拉新增入口。
- **設定**：新增 `LogViewerConfig` 整合進 `app/config.py` 的 `Settings`（全部參數有預設值與硬上限）；無 DB schema 變更、無 migration、無排程/MCP/AI helper 影響。
- **文件**：新增運維說明（env 一覽、多 worker 視野限制、重啟清空、啟動失敗以 `docker logs` fallback）。
- **風險**：log 內容暴露面擴大（Super Admin only + redact + audit + `no-store` 緩解）；log 為未受信任輸入的 XSS 面（安全 DOM 渲染契約）；記憶體佔用（deque maxlen + 訊息截長 + 佇列有界）；SSE 長連線（async generator、連線數上限、最大生命週期）。
