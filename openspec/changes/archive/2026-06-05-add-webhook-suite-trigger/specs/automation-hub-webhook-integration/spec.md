## ADDED Requirements

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

## MODIFIED Requirements

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
