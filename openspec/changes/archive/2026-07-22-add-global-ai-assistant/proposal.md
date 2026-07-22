# Proposal: add-global-ai-assistant

## Why

TCRT 的完整 test case / test run 操作面目前只有兩種入口：網頁 UI 的逐頁操作，以及對外的 `tools/skills/tcrt-app` skill（App Token API，供外部 AI agent 使用）。站內使用者沒有任何對話式操作入口——想「建一個 run、把失敗的 case 加進去、回報結果」必須跨多個頁面手動完成。本變更在 TCRT 站內建置全域 AI 助手：每頁右下角懸浮圖標開啟聊天面板，以自然語言查詢與操作 test case / test run，能力對齊 tcrt-app skill 的完整操作面，且一切動作以登入使用者本人的權限執行、嚴格限制於 TCRT 功能範圍。

## What Changes

- 新增全域助手後端：LLM tool-calling agent loop（OpenRouter，重用 `settings.openrouter`），以 SSE 串流回應；宣告式工具目錄（實作前先以工具矩陣定案）透過 in-process ASGI loopback 呼叫既有 web JWT router，權限由 executor 於呼叫前強制檢查（多數既有端點無 in-handler 檢查，故為必要防線）。
- 新增送往外部 LLM 前的資料邊界：每個工具定義 output projection 與遮罩規則，系統讀出的既有 credential 經遮罩後不外送；provider 設定與附件內容不進入 prompt、訊息紀錄與 SSE。誠實界定：使用者輸入本身會送往外部 LLM，widget scope note 警告勿貼入密碼等機密；助手不接受把 credential 值寫入 test case。
- 新增 `/api/assistant/*` API：availability gating、對話 CRUD（含刪除）、訊息（multipart，支援附檔、client 冪等鍵）、write 操作 confirm/cancel。
- **所有 write 操作伺服器端強制確認**（防 prompt injection 觸發未經使用者意圖的寫入）：只有 read 免確認，mutation 分兩級確認卡（idempotent/reversible 輕量卡、high_impact/irreversible 警告卡）；確認執行具 at-most-once 保證（DB CAS 狀態機 + 執行日誌 + server-generated execution_key）；archive 意圖結構上只映射到 status/archive 端點，絕不走 DELETE。
- 新增 assistant execution journal（main DB）：每次工具執行的 attempt/confirmation/成敗/目標都有權威紀錄（參數遮罩後保存、含不可重用 source_conversation_key 供對話刪除後追查），mutation 的 journal started 紀錄於 loopback 前獨立交易 commit、失敗即中止執行（fail-closed）；timeout/transport/5xx 等無法證明未執行的 mutation 結果一律標 unknown、不自動重試；既有 per-endpoint audit 為輔助歸因。
- 對話持久化：main DB 新增九張表（conversations、turns、events、messages、pending_actions、tool_executions、uploaded_files、rate_limit_buckets、runtime_counters；turn/event 分表且 child 以單欄 turn_id FK 關聯支撐 SSE 可靠重播與跨 conversation 完整性，pending action 雙欄分離原始/遮罩參數並以 server-generated execution_key 保證 at-most-once），pending action 狀態機含具獨立 execution deadline 與 recovery fencing 的 unknown 終態，附 retention 清理排程與使用者刪除對話能力（進行中 turn 回 409）。SSE runner 與 subscriber 生命週期分離，所有 subscriber 由 DB event tail 跨 worker 接續；lease 具 owner fencing，runtime counters 提供跨 worker in-flight admission。
- 對話強制綁定團隊脈絡：mutation 工具僅在 team-bound 對話可用，executor 注入 team_id（不由 LLM 提供）；全域（無 team）對話僅提供 discovery 類工具。
- 新增全頁前端懸浮 widget（FAB + 聊天面板），純 JS 注入、以 design token 實作、三語系 i18n、streamed markdown（marked + 新增 DOMPurify CDN）；「停止中」與「已取消」為明確不同狀態。
- 嚴格 guardrails：TCRT-only 系統 prompt 與拒絕指示、工具目錄按使用者權限預過濾、每使用者限流以 DB quota bucket 跨 conversation／worker 原子保留、無任何通用（非 TCRT）工具。
- 功能預設關閉（opt-in）：必須明確設定 `TCRT_ASSISTANT_ENABLED=true` 才啟用；LLM 未設定（無 OpenRouter key）或停用時 widget 不顯示、chat API 回 503，不提供 fallback。

## Capabilities

### New Capabilities
- `assistant-conversations`: 助手對話與訊息的持久化、per-user 隔離、團隊綁定、查詢/建立/刪除/續聊、retention 清理與聊天附檔暫存。
- `assistant-agent-loop`: LLM tool-calling 迴圈行為——turn 生命週期與跨 worker lease、SSE 事件協定與續傳、取消語意、迭代/逾時/character 上限、opt-in 啟用、限流與 in-flight admission。
- `assistant-tool-execution`: 宣告式工具目錄（工具矩陣）與 in-process loopback 執行——參數綁定、權限預過濾與縱深防禦、team_id 注入、執行日誌、結果投影、錯誤映射、防 drift 測試。
- `assistant-action-confirmation`: 所有 write 操作的伺服器端確認狀態機（pending/executing/confirmed/cancelled/expired/failed/unknown）、兩級確認卡、TTL、CAS 原子認領與 at-most-once 執行、結果不明時的 reconciliation。
- `assistant-data-boundary`: 送往外部 LLM 的資料範圍——credential test data 與機敏設定的遮罩、附件內容隔離、對話紀錄保存期限、洩漏防護測試。
- `assistant-widget-ui`: 全頁懸浮 widget 的可見性 gating、聊天互動、確認卡、停止/取消狀態、i18n 與無障礙行為、SSE parser 自動化測試。
- `assistant-prompt-skills-admin`: Super Admin 可 CRUD 的 DB 版 system prompt 與 skill recipes（Docker 安全、factory seed、restore、agent catalog 注入）。

### Modified Capabilities

（無——既有 capability 的需求不變；助手透過既有 API 操作，不改變其契約。）

## Impact

- **程式碼**：新增 `app/services/assistant/`（registry、executor、LLM、agent loop、conversation service、journal）、`app/api/assistant.py`、`app/models/assistant.py`、`prompts/assistant/system.md`、`app/static/js|css/assistant-widget.*`；修改 `app/config.py`、`app/models/database_models.py`、`app/api/__init__.py`、`app/services/scheduler.py`、`app/templates/base.html`、三個 locale 檔。
- **資料庫/migration**：main alembic tree 新增一支 migration（九張表，`native_enum=False`，SQLite/MySQL/PostgreSQL 相容）；非破壞性、可 downgrade；audit/usm tree 不動。
- **排程**：scheduler 新增 retention/recovery job（過期對話、聊天暫存檔、逾時 pending actions、execution deadline＋lease 雙過期的 executing action 以 recovery owner-CAS 標 unknown、runtime admission counter reconciliation）。
- **相依**：後端零新增（httpx 已存在）；前端新增 DOMPurify pinned CDN（lazy-load）；前端測試使用 Node 內建 `node:test`（零新依賴）。
- **安全/權限**：不新增權限模型；動作沿用使用者 JWT 與既有 router 的 `check_team_permission`。已知限制（明文接受）：現行權限由全域角色決定、`check_team_permission` 的 team_id 僅為快取鍵，助手不改變此行為，僅以對話綁定 team 縮小預設操作面。
- **資料外送**：工具結果經 projection/遮罩後才進入 LLM context；送往 OpenRouter 的資料範圍與保存期限在 `assistant-data-boundary` spec 明定。
- **風險與相容性**：JWT 過期中斷長對話（confirm 以新 JWT 執行緩解）；loopback 與內部 router 形狀耦合（以 registry 對 `app.routes` 解析＋OpenAPI request contract 測試防 drift）；prompt injection 以權限過濾＋所有 write 確認＋TCRT-only 工具＋資料邊界封頂。Rollback：預設即關閉，取消 `TCRT_ASSISTANT_ENABLED` 即完全停用；migration 提供 downgrade。
