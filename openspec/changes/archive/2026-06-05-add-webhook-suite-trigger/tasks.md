## 1. 資料模型與 migration

- [x] 1.1 `AutomationWebhook` 新增 `script_group_id`（nullable FK → `automation_script_groups.id`, `ON DELETE SET NULL`）與對應 relationship
- [x] 1.2 更新 `database_init.py` bootstrap：新欄位建立 / 既有 DB 非破壞性補欄位
- [x] 1.3 確認 migration 對既有 webhook 列維持 `script_group_id=NULL`，不影響既有 inbound/outbound

## 2. Service 層

- [x] 2.1 `trigger_group_run` 擴充可選參數 `triggered_by` / `triggered_by_user_id` / `triggered_by_webhook_id`，預設維持 `triggered_by=USER`
- [x] 2.2 `AutomationWebhookService` 新增 `trigger_suite_run`：載入 inbound webhook、檢查 `script_group_id`、呼叫 `trigger_group_run(triggered_by=WEBHOOK, triggered_by_webhook_id=...)`、更新 `last_triggered_at` / `last_status`，回傳 run handle
- [x] 2.3 定義 / 映射 service 例外：未綁定 suite、suite 不存在、CI 失敗

## 3. 公開 trigger 端點

- [x] 3.1 `automation_webhooks_public.py` 新增 `POST /v1/webhooks/ci/{token}/trigger`：rate limit → load inbound → verify_signature → trigger_suite_run
- [x] 3.2 回應 model `WebhookTriggerResponse`：`run_id, tcrt_correlation_id, external_run_id, external_run_url, status`
- [x] 3.3 錯誤碼映射：401/403/404（token）、401（簽章）、409 `WEBHOOK_NO_SUITE_BOUND`、404 `SUITE_NOT_FOUND`、409/502（CI）、429（rate limit）

## 4. Webhook CRUD 與 schema

- [x] 4.1 `app/models/automation_webhook.py`：`AutomationWebhookCreate` / `Update` / `Response` 增 `script_group_id`
- [x] 4.2 CRUD service / API：建立與更新時驗證「僅 INBOUND 可帶 `script_group_id`」「綁定 group 屬同 team」，違反回 400/404
- [x] 4.3 `webhook_to_dict` 與列表回傳含 `script_group_id`

## 5. 前端 UI

- [x] 5.1 webhook 設定頁：INBOUND 表單增「綁定 test suite」下拉（載入該 team 的 script group）
- [x] 5.2 綁定後顯示 `/trigger` URL 範例；列表顯示綁定的 suite 名稱
- [x] 5.3 i18n：en-US / zh-CN / zh-TW 新增字串

## 6. 測試與驗證

- [x] 6.1 webhook_service 單元測試：trigger_suite_run 成功 / 未綁定 / suite 不存在 / 簽章失敗
- [x] 6.2 `trigger_group_run` 既有 USER 路徑回歸 + 新 WEBHOOK 路徑測試
- [x] 6.3 public `/trigger` 端點測試：rate limit、簽章、回應形狀
- [x] 6.4 CRUD `script_group_id` 驗證測試（INBOUND only、跨 team 拒絕）
- [x] 6.5 執行 `pytest app/testsuite -q` 確認無回歸
