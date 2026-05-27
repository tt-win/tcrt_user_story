## Context

Automation Hub 已有完整 webhook 基礎設施（`app/services/automation/webhook_service.py`、`app/api/automation_webhooks_public.py`）：
- INBOUND webhook 作為「結果接收端」：CI 完成後 POST `/run-status`、`/allure-results` 回流。
- OUTBOUND webhook 作為「事件推送端」：TCRT 把 `run.tracked` / `run.completed` 推給外部。

Suite（script group）執行已由 `AutomationScriptGroupService.trigger_group_run`（`script_group_service.py:319`）實作，會 self-heal CI job、呼叫 provider `trigger_run`、建立 `AutomationRun`（目前固定 `triggered_by=USER`）。`AutomationRunTrigger.WEBHOOK` enum 已存在但尚未被用於觸發。

缺口：沒有「外部一條 URL 即可觸發某 suite」的入口。本變更新增一種 inbound trigger webhook。

## Goals / Non-Goals

**Goals:**
- 讓 INBOUND webhook 可固定綁定一個 script group，外部 POST `/trigger` 即觸發該 suite 在 CI 執行。
- 觸發後立即（非同步）回傳 run handle，沿用既有 HMAC 簽章與 rate limit。
- 最大化複用既有 `trigger_group_run`，僅讓 `triggered_by` / `triggered_by_webhook_id` 可由呼叫端注入。

**Non-Goals:**
- 不阻塞等待 suite 跑完（不做 long-poll）；最終結果仍走既有 `/run-status` callback。
- 不支援單一 script（非 group）觸發；本變更只針對 suite。
- 不改動既有 INBOUND（run-status / allure-results）與 OUTBOUND 行為。
- 不在本變更引入 idempotency token de-dupe（trigger 每次都建立新 run，符合「重跑」語意）。

## Decisions

**D1：以 `script_group_id` 欄位綁定，而非 payload 指定。**
在 `AutomationWebhook` 加 nullable FK `script_group_id`。URL（token）即代表目標 suite，呼叫端不需也不能改觸發對象 → 一個 token 的爆破半徑限縮在一個 suite。替代方案（payload 指定 group_id）讓單一 token 可觸發 team 內任意 suite，安全邊界較鬆，否決。

**D2：trigger 流程複用 `trigger_group_run`，擴充其 `triggered_by` / `triggered_by_user_id` / `triggered_by_webhook_id` 參數。**
`trigger_group_run` 目前硬寫 `triggered_by=AutomationRunTrigger.USER`。改為接受可選參數，預設仍為 USER（既有 caller 不受影響），webhook 路徑傳入 `WEBHOOK` + `triggered_by_webhook_id`。避免複製整段 CI self-heal / trigger 邏輯。

**D3：在 webhook_service 新增 `trigger_suite_run`，由 public API `/trigger` 端點呼叫。**
流程：`load_inbound_webhook(token)` → `verify_signature` → 檢查 `webhook.script_group_id` 非空 → 呼叫 `AutomationScriptGroupService(session).trigger_group_run(...)` → 更新 `webhook.last_triggered_at` / `last_status` → 回傳 run handle。與既有 `/run-status` 同樣走 `MainAccessBoundary.run_write`。

**D4：簽章驗證與 rate limit 一致。**
`/trigger` 沿用 `_consume_rate_limit(token)` 與 `verify_signature`（body 為觸發參數 JSON，可為 `{}`）。若 webhook 設了 secret 則要求 `X-TCRT-Signature`，與既有 INBOUND 一致。

**D5：CRUD 對 `script_group_id` 的約束。**
建立 / 更新時，`script_group_id` 僅 INBOUND 可帶；OUTBOUND 帶入回 400。綁定的 group 必須屬於同一 team，否則回 400/404。GET 列表回傳 `script_group_id`（metadata，不涉密）。

**D6：回應形狀。**
`POST /trigger` 回 `{run_id, tcrt_correlation_id, external_run_id, external_run_url, status}`，status 為 `QUEUED`。與既有 `WebhookRunStatusResponse` 風格一致，方便呼叫端後續以 `tcrt_correlation_id` 對應 `/run-status` 回流。

## Risks / Trade-offs

- **未綁定 suite 的 INBOUND webhook 被 POST `/trigger`** → 回 409/400 明確錯誤碼（`WEBHOOK_NO_SUITE_BOUND`），不觸發任何 CI。
- **CI provider / job 不可用導致 `trigger_group_run` 拋錯** → 對應 `trigger_group_run` 既有例外（CI job missing、CI API error）映射成 502/409，不留下半截 run（沿用其 flush 行為）。
- **綁定的 group 被刪除**（FK `ondelete` 行為）→ `script_group_id` 設計為 nullable + `SET NULL`（與 `AutomationRun.script_group_id` 一致）；觸發時若 group 已不存在，回 404 `SUITE_NOT_FOUND`。
- **重複觸發造成多個 run** → 這是預期語意（trigger = 重跑）；rate limit 仍保護爆量。
- **既有 `trigger_group_run` 簽名變動** → 新增參數皆有預設值，既有 USER 路徑（API / UI）行為不變，測試需覆蓋兩條路徑。

## Migration Plan

1. DB：`automation_webhooks` 新增 `script_group_id INTEGER NULL`（FK → `automation_script_groups.id`, `ON DELETE SET NULL`）。更新 `database_init.py` bootstrap；既有列為 NULL，非破壞性。
2. 部署順序：先上 DB schema + 後端，再上前端 UI 欄位。舊前端不送 `script_group_id` 不影響後端（欄位可選）。
3. Rollback：移除端點與欄位即可；NULL 欄位不影響既有 INBOUND/OUTBOUND 資料。

## Open Questions

- 暫無；採用 D1–D6 預設決策推進。
