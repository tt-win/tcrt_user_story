## Why

TCRT 的 audit 與 system log 語意混用同一套「WARNING / severity」詞彙：audit 無法有效搜尋操作摘要，severity 無法區分「動作敏感度」與「成敗」；system log 則把可預期的 soft-fail（例如 load test-run result / Result provider / Allure proxy 降級路徑）標成 WARNING，造成運維噪音。需要一套嚴格、可遵循、可擴充的事件 envelope 與分級軸，並讓 audit 真正可搜。

## What Changes

MVP 範圍（刻意收斂，不做觀測平台大重寫）：

- **引入事件 envelope v1**：以 `event_code`、`schema_version`、`impact`、`outcome`、`brief`、可驗證的 `details` 作為 audit 與重要 ops log 的共同語意骨架（transport 仍分離：audit DB vs Python logging / ring buffer）。
- **分軸取代混用 severity**：
  - **impact**（動作本質敏感度）：`routine | notable | sensitive | privileged`
  - **outcome**（本次結果）：`success | denied | failure | partial`
  - **ops level**（system log）：stdlib `DEBUG|INFO|WARNING|ERROR|CRITICAL`，僅依「是否需運維介入」選用
- **Event catalog（登錄表）**：新寫入路徑必須使用已登錄的 `event_code`；impact / 預設 ops level / 是否寫 audit 由 catalog 決定，禁止 caller 隨手塞 free-form severity。
- **Audit 可搜尋（Phase A）**：
  - API/UI 補齊 `action_type`、`impact`、`outcome`、`resource_id` 篩選
  - 新增 `q` 搜尋 `action_brief` + `event_code` + `resource_id` + `username`（**不搜 details**）
  - 搜尋以 `POST /audit/logs/search` 為主，避免 `q` 進入 URL query（見 design）
- **Audit schema 擴充**（audit DB migration）：新增 `event_code`、`outcome`、`impact`；保留既有 `severity` 作 legacy 相容讀取，新寫入同時填新舊欄位映射。
- **校正高噪 ops 路徑 level**：至少涵蓋 Automation Hub `run_service` / `allure_proxy` 的 result load、CI artifact、Allure proxy 降級路徑——可預期 fallback 不得再標 WARNING。
- **UI**：audit 頁顯示 impact + outcome；system-logs 若 record 含 event_code 可顯示（不改「禁止 server keyword」契約）。
- **Emit 模型**：核心 `emit_event` 嚴格驗證；業務路徑 `safe_emit_event` 維持 audit best-effort（失敗不 500）。
- **同交付**：所有顯式 `AuditSeverity.WARNING` 站點改正確 `outcome`（deny→denied），避免 adapter 預設 success 污染。

**非 BREAKING（對外 API 契約）**：
- 既有 `GET /audit/logs` 篩選參數保留；新增參數為 opt-in；**新增** `POST /audit/logs/search`。
- 既有 `severity` 回應欄位保留（新寫入會依映射填入）。
- system-logs 仍禁止 server-side keyword；ring buffer **不**改變 handler 拓樸。
- **有意行為變更**：鎖定 ops 路徑的 log **level 與 message 正文**會變（功能目標，非 buffer 副作用）。

## Non-Goals

- 不合併 audit 與 system log 為單一倉庫或單一搜尋框。
- 不做跨引擎全文檢索（FTS5 / FULLTEXT / tsvector）——列為 follow-up。
- 不把所有既有 `logger.warning` call site 一次改完；本 change 只強制 catalog 路徑 + 鎖定的高噪 automation result 路徑 + 顯式 WARNING audit 站點。
- 不改變 system-log-viewer 的 in-memory / SSE / Super Admin 權限模型，**不**新增 server keyword。
- 不引入 ELK/OpenTelemetry 後端或第三方 log 船運。
- 不擴大 middleware 自動 audit READ 的覆蓋（避免噪音）。
- 不保證反向代理或未來 body logger 永不記錄 POST body。


## Capabilities

### New Capabilities

- `audit-event-envelope`：audit 事件 envelope、catalog、impact/outcome、可搜尋查詢 API/UI、audit DB 欄位與 legacy severity 映射。
- `ops-structured-logging`：ops 事件 logging 規則、level 選用準則、structured message 格式、automation result 路徑 level 校正。

### Modified Capabilities

- `system-log-viewer`：buffer/API 記錄 MAY 攜帶可選 structured 欄位（`event_code`、`outcome`）；snapshot 與 SSE 同 schema；UI MAY 顯示 event_code；**維持**禁止 server keyword 與 ring-buffer handler 拓樸不變（ops 路徑的 level／message 內容為有意變更）。

## Impact

- **Audit DB**：`alembic_audit` 新 migration（可空 team 既有契約不變）；`AuditLogTable` / models / service / query。
- **API**：`app/api/audit.py` 查詢與 export；audit 寫入 helper（新 emit API）。
- **UI/i18n**：`audit_logs.html` / `audit_logs.js`；`en-US` / `zh-CN` / `zh-TW`。
- **Ops logging**：`app/utils/` 或 `app/observability/` 新增 catalog + emit helper；`run_service.py`、`allure_proxy.py` 等。
- **System log viewer**：`system_log_buffer.py` 可選欄位；前端顯示（非必要大改）。
- **Tests**：audit query/search、catalog validation、severity 映射、automation result log level、既有 system-log 契約回歸。
- **Rollback**：程式回滾 + audit migration downgrade（新欄位 nullable 或有 default，舊讀取路徑保留 `severity`）。
