## Why

目前 Automation Hub 的 inbound webhook 只是「結果接收端」：CI 跑完後把 run-status / allure-results 回拋進 TCRT。要從外部系統（排程器、其他 CI、ChatOps）主動「啟動」一個 test suite，必須走 team admin 的 UI / 認證 API，無法用一條穩定的 webhook URL 觸發。本變更新增一種綁定特定 test suite（script group）的 inbound trigger webhook：外部 POST 該 URL 即觸發整個 suite 在 CI 上執行，並立即回傳 run handle。

## What Changes

- `AutomationWebhook` 新增 `script_group_id`（nullable FK → `automation_script_groups`），代表此 inbound webhook 綁定的 test suite。一個 trigger webhook 對應一個 suite。
- 新增公開端點 `POST /api/v1/webhooks/ci/{token}/trigger`：驗證 token（INBOUND + active）與 HMAC 簽章後，呼叫既有 `AutomationScriptGroupService.trigger_group_run`，以 `triggered_by=WEBHOOK`、`triggered_by_webhook_id=<webhook.id>` 建立 run，**立即**回傳 `{run_id, tcrt_correlation_id, external_run_id, external_run_url, status: QUEUED}`（非同步：最終結果仍透過既有 `/run-status` callback 回流）。
- 沿用既有 inbound 的 per-token rate limit（120 req/min）與 HMAC 簽章驗證機制。
- Webhook CRUD（建立 / 更新）新增可選 `script_group_id`：僅 INBOUND 可帶；OUTBOUND 帶入 SHALL 拒絕。綁定的 suite 必須屬於同一 team。
- Webhook 設定 UI 對 INBOUND webhook 提供「綁定 test suite」下拉選擇，並顯示 trigger URL 範例。

## Capabilities

### New Capabilities
（無）

### Modified Capabilities
- `automation-hub-webhook-integration`: 新增「inbound trigger webhook 綁定 suite 並觸發 run」的需求；擴充 webhook CRUD 需求以支援 `script_group_id`。

## Impact

- **資料庫**：`automation_webhooks` 新增 `script_group_id` 欄位（nullable，非破壞性）。需更新 `database_init.py` bootstrap 與 migration；既有 webhook 列 `script_group_id=NULL` 不受影響。
- **API**：新增 `app/api/automation_webhooks_public.py` 的 `/trigger` 端點；`app/api/automation_webhooks.py` CRUD 與 `app/models/automation_webhook.py` pydantic schema 增 `script_group_id`。
- **Service**：`app/services/automation/webhook_service.py` 增 trigger 流程（複用 `trigger_group_run`、`triggered_by=WEBHOOK`）。
- **前端**：`automation_webhook_config` 相關模板 / JS 增 suite 綁定欄位與 i18n。
- **相容性**：純新增能力，既有 inbound（run-status / allure-results）與 outbound 行為不變；無 rollback 資料風險。
