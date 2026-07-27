## 1. `app/api/test_runs.py`：只留報告端點

- [x] 1.1 移除 8 支 Lark record 端點：`GET /{config_id}/records`、`GET /{config_id}/records/count`、`GET /{config_id}/records/{record_id}`、`POST /{config_id}/records`、`PUT /{config_id}/records/{record_id}`、`DELETE /{config_id}/records/{record_id}`、`GET /{config_id}/statistics`、`POST /{config_id}/batch-update-results`
- [x] 1.2 移除只被上述路由使用的 helper：`get_lark_client_for_test_run()`、`filter_test_runs()`、`sort_test_runs()`、`log_test_run_action()`（已確認 repo 中無其他呼叫者）
- [x] 1.3 清理隨之未使用的 import：`LarkClient`、`settings`、`asyncio`、`app.models.test_run` 全部、audit 相關、`PermissionType`、`Query` 等（以 ruff 為準，逐一確認保留下來的兩支端點是否仍需要）
- [x] 1.4 改寫檔案 docstring：目前寫「直接操作 Lark 多維表格」，改為描述「test run HTML 報告端點」
- [x] 1.5 確認 `POST /{config_id}/generate-html` 與 `GET /{config_id}/report` 完整保留、prefix 不變（前端 `test-run-execution/reports.js:53` 依賴此 URL）

## 2. `app/api/attachments.py`：移除 Lark 寫入路由

- [x] 2.1 移除 6 支端點：`POST /teams/{team_id}/testcases/{record_id}/upload`、`POST /teams/{team_id}/test-runs/{config_id}/records/{record_id}/upload`、`POST .../upload-screenshot`、`POST /teams/{team_id}/upload-file-token`、`POST /teams/{team_id}/testcases/{record_id}/attach-token`、`DELETE /teams/{team_id}/testcases/{record_id}/attachments/{file_token}`
- [x] 2.2 **保留** `GET /teams/{team_id}/attachments/download` 與 `get_lark_client_for_team()`（下載代理的 Lark 回退仍在用，且有 spec 與測試鎖定）
- [x] 2.3 清理隨之未使用的 import（`UploadFile`／`File`／`Form` 等），以 ruff 為準

## 3. 刪除死模組

- [x] 3.1 刪除 `app/models/test_run.py`（唯一 importer 是 1.1 移除的路由；已確認 `TestRunFieldMapping`／`TestRunFilter` 無其他使用者）
- [x] 3.2 刪除 `app/services/test_result_file_service.py`（全 repo 零 importer）
- [x] 3.3 移除 `app/api/test_run_items.py` 的 `_get_lark_client_for_team()`（死 helper）與隨之未使用的 `LarkClient` import

## 4. 驗證

- [x] 4.1 `python -c "import app.main"` 等效檢查：app 可正常 import、router 掛載無殘留 import 錯誤。**結果**：`app.main` 成功載入，router 掛載無誤
- [x] 4.2 檢查 route table：`generate-html` 與 `report` 仍在；`/records`、`upload-file-token`、`attach-token` 已不存在。**結果**：`/test-runs/` 下只剩 `generate-html`、`report`；`/api/attachments/` 下只剩 `attachments/download`
- [x] 4.3 `uv run pytest app/testsuite/test_attachment_proxy_contract.py -q` 通過（保留下來的下載代理未被誤傷）。**結果**：6 passed
- [x] 4.4 抽樣跑 test run 相關既有測試（逐檔）：`test_test_run_set_api.py`、`test_test_run_multi_set_api.py`、`test_app_token_test_run_api.py`、`test_test_run_item_update_without_snapshot.py`。**結果**：5 + 4 + 30 + 1 = 40 passed
- [x] 4.5 `uv run ruff check app scripts database_init.py` 無新增錯誤（與 HEAD 比對）。**結果**：360 errors，與 HEAD 逐字相同（既有債務）；本次觸碰的檔案逐檔 All checks passed
- [x] 4.6 `openspec validate purge-dead-lark-runtime-code --strict`

## 5. 收尾

- [x] 5.1 確認 `rg -n "lark" app/api app/services --glob '!*lark*'` 的殘留結果全部可解釋（下載代理回退、cleanup service legacy 分支、組織層 Lark 服務）。**結果**：僅三處——`attachments.py` 下載代理回退、`test_result_cleanup_service` legacy 分支（兩者皆有空 token guard）、`lark_users.py` 組織層查詢（只用全域 app_id/secret）
