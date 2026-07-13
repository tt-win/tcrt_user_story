## Why

`add-team-app-token-apis` 的 app-token Test Run 建立端點可設定 `related_tp_tickets`，但更新端點
（`PUT /api/app/teams/{team_id}/test-run-configs/{config_id}`）只套用
name/description/version/environment/build/status/scope，會靜默丟棄請求中的
`related_tp_tickets`。既有 JWT web API 的更新可修改該欄位，Test Run Set 的 app-token 更新也支援
`related_tp_tickets`。此落差使 app-token 使用者（含 `tcrt-app` skill）無法在建立後調整 Test Run 的
TP 票號關聯，也讓 skill 無法完整修改 Test Run 的可變屬性。

## What Changes

- `PUT /api/app/teams/{team_id}/test-run-configs/{config_id}` 在請求提供 `related_tp_tickets`
  時，SHALL 以既有 `TP-\d+` 格式驗證後更新該欄位；未提供時維持原值。
- app-token Test Run Config 的建立與更新 response SHALL 回傳 `related_tp_tickets`，使呼叫端可讀回
  目前值。
- 不變更通知設定與 `start_date` / `end_date` 的既有行為（維持建立時設定或由狀態轉換管理）。
- 更新 `tcrt-app` skill 文件，將 `related_tp_tickets` 列入 Test Run 更新可改欄位並修正限制註記。

## Capabilities

### Modified Capabilities

- `app-token-test-run-api`: 明確要求 Test Run Config 更新可修改 `related_tp_tickets`，且 mutation
  response 包含該欄位。

## Impact

- Backend：`app/api/app_test_runs.py` 的 `update_app_test_run_config` 新增 `related_tp_tickets`
  處理（寫入 `related_tp_tickets_json`），並在 `_serialize_config` 回傳 `related_tp_tickets`。
- Tests：擴充 `app/testsuite/test_app_token_test_run_api.py`，涵蓋更新設定與省略時保留的行為。
- Docs：`tools/skills/tcrt-app/references/api-reference.md`（更新可改欄位與限制註記）。此 skill 為本機 gitignored 目錄，非版控。
- 不變更 schema、scope、通知或日期行為。回滾僅需移除該欄位處理與序列化，屬單一檔案邏輯回退。
