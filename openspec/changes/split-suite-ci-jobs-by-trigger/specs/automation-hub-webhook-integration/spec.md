## MODIFIED Requirements

### Requirement: Inbound webhook MAY bind a test suite and trigger its run
INBOUND webhook 紀錄 SHALL 支援可選的 `script_group_id`，綁定該 team 內的一個 automation script group（test suite）。當 webhook 綁定了 suite 時，端點 `POST /api/v1/webhooks/ci/{token}/trigger` SHALL 觸發該 suite 在 CI 執行。

- token SHALL 對應 `automation_webhooks` 中 `direction=INBOUND, is_active=true` 的紀錄；不符 SHALL 回 401/403/404，與既有 inbound 一致（不洩漏存在性）。
- 若 webhook 紀錄有 `secret`，請求 SHALL 攜帶 `X-TCRT-Signature: sha256=<hex>`，後端以 webhook secret 計算 raw body 的 HMAC-SHA256 比對；不符 SHALL 回 401。請求 body 為觸發參數 JSON（可為 `{}`，亦可含 `branch` / `runner_label` / `inputs`）。
- 觸發 SHALL 走該 suite 的**專屬 webhook job**（`ci_job_name_webhook`，job 名 `tcrt_{team}_{suite}_hook`），與 Test Run Set 觸發的主 job 物理隔離；webhook job **lazy 建立**（首次觸發時 self-heal → provider trigger → 建立 `automation_runs`），並以 `triggered_by=WEBHOOK`、`triggered_by_webhook_id=<webhook.id>` 記錄該 run。詳見 run-orchestration spec。
- 端點 SHALL **立即**（非同步）回 200 `{run_id, tcrt_correlation_id, external_run_id, external_run_url, status}`，status 為 `QUEUED`；suite 最終結果仍透過既有 `POST /api/v1/webhooks/ci/{token}/run-status` callback 回流。
- 端點 SHALL 套用既有 per-token rate limit（120 req/min），超過回 429 帶 `Retry-After`。
- 成功觸發 SHALL 更新該 webhook 的 `last_triggered_at` 與 `last_status`。

#### Scenario: Trigger bound suite
- **WHEN** 外部系統對綁定 suite 的 inbound webhook POST `/trigger`，token 與簽章皆有效
- **THEN** TCRT SHALL 觸發該 suite 的 webhook job 在 CI 執行，建立 `triggered_by=WEBHOOK` 的 run，並立即回 200 含 `run_id` 與 `tcrt_correlation_id`、`status=QUEUED`

#### Scenario: First webhook trigger provisions the webhook job
- **WHEN** 綁定的 suite 尚無 webhook job（`ci_job_name_webhook` 為 NULL）被首次 `/trigger`
- **THEN** TCRT SHALL lazy 建立該 suite 的 webhook job、回填 `ci_job_name_webhook`，run 在該 webhook job 執行

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
