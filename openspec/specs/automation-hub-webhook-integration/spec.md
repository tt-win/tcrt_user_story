# automation-hub-webhook-integration Specification

## Purpose
TBD - created by archiving change add-automation-hub. Update Purpose after archive.
## Requirements
### Requirement: System MUST provide inbound webhook for CI run-status updates
端點 `POST /api/v1/webhooks/ci/{token}/run-status` SHALL 接收 CI 完成事件，token 對應 `automation_webhooks` 中 `direction=INBOUND, is_active=true` 的紀錄。

Payload schema：

```json
{
  "tcrt_correlation_id": "uuid-string",
  "external_run_id": "ci-run-123",
  "external_run_url": "https://github.com/.../actions/runs/123",
  "status": "SUCCEEDED",
  "started_at": "2026-05-11T10:00:00Z",
  "finished_at": "2026-05-11T10:12:34Z",
  "duration_ms": 754000,
  "report_url": "https://allure.../runs/123",
  "error_summary": null
}
```

成功 SHALL 更新對應 `automation_runs` 紀錄（依 `tcrt_correlation_id` 配對；若無則依 `external_run_id` + `team_id`），回 200 `{"updated": true, "run_id": 33}`。

#### Scenario: Successful update
- **WHEN** CI 帶有效 token + 簽章 + 已知的 `tcrt_correlation_id`
- **THEN** TCRT SHALL 更新 status / finished_at / report_url 等欄位，並觸發 outbound `run.completed` 事件

#### Scenario: Token not found
- **WHEN** token 不存在或 is_active=false
- **THEN** API SHALL 回 401（不洩漏存在性），寫 audit `WEBHOOK_AUTH_FAIL`

#### Scenario: Correlation id not found
- **WHEN** payload 的 `tcrt_correlation_id` 在 TCRT DB 中不存在
- **THEN** API SHALL 回 404 `{"error": "Run not found"}`，寫 audit 並提示 CI 端可能 race condition

### Requirement: Inbound webhook MUST verify HMAC-SHA256 signature
若 webhook 紀錄有 `secret`，請求 SHALL 攜帶 `X-TCRT-Signature: sha256=<hex>`，後端以 webhook secret 計算 raw body 的 HMAC-SHA256，與 header 比對；不符 SHALL 回 401。

亦 SHALL 驗證 `X-TCRT-Delivery: <uuid>`（idempotency）；同 delivery_id 在 24 小時內第二次呼叫 SHALL 回 200 with `{"duplicate": true}`，不重複更新。

#### Scenario: Signature mismatch
- **WHEN** 請求帶錯誤 signature
- **THEN** TCRT SHALL 回 401，寫 audit `WEBHOOK_AUTH_FAIL`

#### Scenario: Idempotent delivery
- **WHEN** 同 `X-TCRT-Delivery` 在 1 小時內第二次到達
- **THEN** TCRT SHALL 回 200 `{"duplicate": true}`，不重複處理

### Requirement: Inbound webhook MUST enforce per-token rate limit
TCRT SHALL 對每個 token 套用 120 req/min 的 in-memory token bucket。超過 SHALL 回 429 並帶 `Retry-After` header。

#### Scenario: Burst protection
- **WHEN** 同一 token 1 分鐘內第 121 次請求
- **THEN** TCRT SHALL 回 429

### Requirement: Inbound webhook MAY bind a test suite and trigger its run
INBOUND webhook 紀錄 SHALL 支援可選的 `script_group_id`，綁定該 team 內的一個 automation script group（test suite）。當 webhook 綁定了 suite 時，端點 `POST /api/v1/webhooks/ci/{token}/trigger` SHALL 觸發該 suite 在 CI 執行。

- token SHALL 對應 `automation_webhooks` 中 `direction=INBOUND, is_active=true` 的紀錄；不符 SHALL 回 401/403/404，與既有 inbound 一致（不洩漏存在性）。
- 若 webhook 紀錄有 `secret`，請求 SHALL 攜帶 `X-TCRT-Signature: sha256=<hex>`，後端以 webhook secret 計算 raw body 的 HMAC-SHA256 比對；不符 SHALL 回 401。請求 body 為觸發參數 JSON（可為 `{}`，亦可含 `branch` / `runner_label` / `inputs`）。
- 觸發 SHALL 複用既有 suite 執行流程（self-heal CI job → provider trigger → 建立 `automation_runs`），並以 `triggered_by=WEBHOOK`、`triggered_by_webhook_id=<webhook.id>` 記錄該 run。
- 端點 SHALL **立即**（非同步）回 200 `{run_id, tcrt_correlation_id, external_run_id, external_run_url, status}`，status 為 `QUEUED`；suite 最終結果仍透過既有 `POST /api/v1/webhooks/ci/{token}/run-status` callback 回流。
- 端點 SHALL 套用既有 per-token rate limit（120 req/min），超過回 429 帶 `Retry-After`。
- 成功觸發 SHALL 更新該 webhook 的 `last_triggered_at` 與 `last_status`。

#### Scenario: Trigger bound suite
- **WHEN** 外部系統對綁定 suite 的 inbound webhook POST `/trigger`，token 與簽章皆有效
- **THEN** TCRT SHALL 觸發該 suite 在 CI 執行，建立 `triggered_by=WEBHOOK` 的 run，並立即回 200 含 `run_id` 與 `tcrt_correlation_id`、`status=QUEUED`

#### Scenario: Webhook not bound to a suite
- **WHEN** 對一個未綁定 `script_group_id` 的 inbound webhook POST `/trigger`
- **THEN** TCRT SHALL 回 409 `{"code": "WEBHOOK_NO_SUITE_BOUND"}`，不觸發任何 CI run

#### Scenario: Bound suite no longer exists
- **WHEN** webhook 綁定的 script group 已被刪除（`script_group_id` 為 NULL 或查無）
- **THEN** TCRT SHALL 回 404 `{"code": "SUITE_NOT_FOUND"}`，不觸發任何 CI run

#### Scenario: Signature mismatch on trigger
- **WHEN** webhook 設有 secret 但 `/trigger` 請求簽章不符
- **THEN** TCRT SHALL 回 401，不觸發任何 CI run

#### Scenario: CI trigger fails
- **WHEN** 觸發時 CI job 不存在無法自癒，或 CI provider API 失敗
- **THEN** TCRT SHALL 回 409/502 並帶對應錯誤碼，不留下半截成功的 run handle

### Requirement: System MUST emit outbound events for hub lifecycle
TCRT SHALL 對 `automation_webhooks` 中 `direction=OUTBOUND, is_active=true` 且符合事件訂閱的紀錄發送 POST。事件類型 SHALL 包含：

- `script.discovered`：新 script 經 auto-discovery 發現並加入 hub
- `script.linked`：script 連結到 test case
- `script.unlinked`：script 解除連結
- `script.synced`：script cached_content 重新 fetch 完成（etag 變更或手動觸發）
- `run.triggered`：TCRT 觸發 run
- `run.tracked`：run 配對到 external_run_id
- `run.completed`：run 進入終態（含 SUCCEEDED / FAILED / CANCELLED）

Payload envelope：

```json
{
  "event": "run.completed",
  "delivery_id": "uuid",
  "occurred_at": "2026-05-11T10:00:00Z",
  "team_id": 1,
  "data": {
    "run_id": 33,
    "script_id": 5,
    "script_name": "Login Flow E2E",
    "status": "FAILED",
    "external_run_url": "...",
    "report_url": "..."
  }
}
```

Headers：`X-TCRT-Signature: sha256=<hex>`（HMAC over raw body）、`X-TCRT-Event`、`X-TCRT-Delivery`、`Content-Type: application/json`。

#### Scenario: Slack receives run.completed
- **WHEN** 一個 outbound webhook 訂閱 `run.completed`，run 進入 FAILED 狀態
- **THEN** TCRT SHALL POST 到 target_url 帶 HMAC 簽章，Slack incoming webhook 可解析並轉成訊息

### Requirement: Outbound dispatch MUST be fire-and-forget in v1
v1 outbound SHALL **不** 引入 retry queue：

- 發送 timeout 10 秒
- 失敗（非 2xx 或 timeout）SHALL 寫一筆 audit `WEBHOOK_DELIVERY_FAILED`（含 status code、回應截斷 1KB、duration_ms）
- UI SHALL 顯示「最近 50 次投遞」（含失敗），但 **不** 自動重試
- 每次投遞無論成敗 SHALL 更新 `automation_webhooks.last_triggered_at` 與 `last_status`

#### Scenario: Outbound failure not retried in v1
- **WHEN** outbound POST 收 503
- **THEN** TCRT SHALL 寫 audit 標 FAILED，**不** 重試；UI 列入失敗清單

#### Scenario: User-driven manual replay
- **WHEN** admin 在 UI 點「重發此事件」
- **THEN** TCRT SHALL 重新發送該 delivery（含新 delivery_id），結果再次寫 audit

### Requirement: System MUST provide webhook CRUD with one-time secret disclosure
API SHALL 提供下列端點，所有端點 SHALL 要求 team admin 權限：

- `POST /api/teams/{team_id}/automation-webhooks`：建立；payload 含 `direction`, `name`, `target_url`（outbound 必填）, `events`（list, outbound 必填）, `script_group_id`（可選，**僅 INBOUND** 可帶；OUTBOUND 帶入 SHALL 回 400）; response SHALL 一次性回 `token + secret`
- `GET /api/teams/{team_id}/automation-webhooks`：列表，SHALL 只回 metadata + fingerprint（含 `script_group_id`），不回 token / secret
- `PATCH /api/teams/{team_id}/automation-webhooks/{id}`：更新 name / target_url / events / is_active / `script_group_id`；SHALL 不允許改 direction；對 OUTBOUND webhook 設定 `script_group_id` SHALL 回 400
- `POST /api/teams/{team_id}/automation-webhooks/{id}/rotate-secret`：重新產生 secret，SHALL 一次性回應
- `DELETE /api/teams/{team_id}/automation-webhooks/{id}`：刪除
- `POST /api/teams/{team_id}/automation-webhooks/{id}/test`：發送 test ping（outbound only）；inbound webhook SHALL 無此端點

建立或更新時，`script_group_id` 所指 script group SHALL 屬於同一 `team_id`，否則 SHALL 回 400/404。

#### Scenario: One-time secret display
- **WHEN** 建立新 webhook
- **THEN** API response SHALL 包含 token + secret；後續 GET SHALL 只回 fingerprint

#### Scenario: Bind suite to inbound webhook
- **WHEN** admin 建立或更新 INBOUND webhook 並帶同 team 的 `script_group_id`
- **THEN** API SHALL 儲存綁定並在 GET 回傳該 `script_group_id`

#### Scenario: Reject suite binding on outbound webhook
- **WHEN** admin 對 OUTBOUND webhook 設定 `script_group_id`
- **THEN** API SHALL 回 400，不儲存綁定

### Requirement: UI MUST provide webhook config page with examples
`automation_webhook_config.html` SHALL 提供：

- 建立 inbound webhook：表單 `name`、可選「綁定 test suite」下拉（列出該 team 的 script group）；回應顯示 token + secret 一次（提供「複製 curl 範例」按鈕，內含完整 HMAC 計算示意）；綁定 suite 時 SHALL 顯示 `/trigger` URL 範例
- 建立 outbound webhook：表單 `name`, `target_url`, events 多選 checkbox, secret（auto-generated）；「發送測試 ping」按鈕
- 列表現有 webhook：fingerprint、綁定的 suite 名稱（若有）、last_triggered_at、last_status、is_active 切換
- 最近 50 次投遞紀錄（從 audit 過濾）
- 失敗投遞「重發」按鈕

#### Scenario: Test ping
- **WHEN** admin 點「發送測試 ping」
- **THEN** TCRT SHALL POST 假事件 `{"event":"test","data":{...}}` 到 target_url，UI 即時顯示 response status

#### Scenario: Bind suite in UI
- **WHEN** admin 為 inbound webhook 於下拉選擇一個 test suite 並儲存
- **THEN** UI SHALL 顯示該 webhook 的 `/trigger` URL 範例，列表顯示綁定的 suite 名稱

### Requirement: Documentation MUST include payload schema and CI workflow template
`docs/automation-webhook.md` SHALL 包含：

- Inbound payload schema 與必要 / 選用欄位
- HMAC-SHA256 簽章計算範例（Python / Node / shell）
- Outbound 各事件 payload schema
- v1 不重試的行為說明
- Rate limit 說明
- 安全建議（secret 保管、IP 白名單）

`docs/automation-workflow-templates/github-actions-playwright.yml` SHALL 提供完整可用的 GH Actions workflow 範例，包含：
- 讀取 `inputs.tcrt_run_id`
- 完成後 curl POST 到 TCRT inbound webhook 帶 HMAC 簽章
- 用 secrets.TCRT_WEBHOOK_TOKEN + TCRT_WEBHOOK_SECRET

#### Scenario: Copy-paste workflow works
- **WHEN** 使用者複製 docs 中的 GH Actions workflow，替換 owner / repo / secrets
- **THEN** workflow SHALL 能正確觸發 → 執行 Playwright → 回報結果到 TCRT，無需修改其他細節
