## Why

app-token 的 Test Run 執行面還缺兩塊,使 skill 使用者無法完整驅動 Test Run 生命週期:

1. **狀態階段轉換**：一般 `PUT .../test-run-configs/{config_id}` 只把 `status` 硬設進 DB,
   沒有狀態機驗證、沒有 `start_date`/`end_date` 連動、也不重算所屬 set 狀態。既有 JWT
   `PUT .../{config_id}/status` 才有完整生命週期語意。app-token 因此無法「正確地」推進
   draft → active → completed → archived。
2. **執行結果檔上傳**：JWT 有 `POST .../items/{item_id}/upload-results`（multipart）記錄
   截圖/log 等執行證明,app-token 沒有對應端點。且可攜式 `tcrt_api.sh` 只支援 JSON body,
   無 multipart,連現有 test-case 附件上傳都送不出去。

## What Changes

- 新增 `PUT /api/app/teams/{team_id}/test-run-configs/{config_id}/status`（`test_run:write`）：
  受控狀態機 + `start_date`/`end_date` 副作用 + 所屬 set 狀態重算。轉換規則抽成單一共用
  helper,JWT 與 app-token 兩個 `/status` 端點共用,避免狀態機在兩條 auth 路徑漂移。
- 一般 `PUT .../test-run-configs/{config_id}` 的直接 `status` 設定行為**維持不變**（依決策保留）。
- 新增 `POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/upload-results`
  （`test_run:execute`）：multipart 上傳,存至 attachments 根目錄下
  `test-runs/{team_id}/{config_id}/{item_id}/`,並更新 item 的 `execution_results_json`、
  `result_files_*`、`upload_history_json`,schema 與 JWT 版本一致。
- 可攜式 client（`tcrt_api.sh` + `tcrt_api.py`）新增 multipart `--file field=@path`（可重複）模式,
  含檔名/路徑安全處理;此 skill 為本機 gitignored,client 變更不進版控。
- 更新 skill 文件（本機）暴露兩個新端點與上傳用法。

## Capabilities

### Modified Capabilities

- `app-token-test-run-api`: 新增 Test Run Config 狀態轉換端點與 Test Run Item 結果檔上傳端點兩條
  requirement。

## Impact

- Backend：
  - `app/services/test_run_set_status.py` 新增 `apply_config_status_transition_sync`（狀態機 + 日期副作用）。
  - `app/api/test_run_configs.py` 的 JWT `/status` 改用該 helper（行為不變,消除重複）。
  - `app/api/app_test_runs.py` 新增 `/status` 與 `/items/{item_id}/upload-results` 兩個端點。
- Local（gitignored,不進版控）：`tools/skills/tcrt-app` 的 client 與文件。
- Tests：`app/testsuite/test_app_token_test_run_api.py` 覆蓋狀態轉換（合法/非法/日期/set 重算）與上傳
  （成功/scope/404）;並跑 JWT `/status` 回歸確保 helper 抽取無行為變更。
- Scopes 不變（`test_run:write` / `test_run:execute`）;無 schema 變更。
- Rollback：移除兩個新端點與 helper、將 JWT `/status` 還原為 inline 邏輯即可,無資料遷移。
