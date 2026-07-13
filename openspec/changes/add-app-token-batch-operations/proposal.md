## Why

app-token surface 目前只有「批次建立」（test cases `/batch`、run items batch create），
沒有批次更新／刪除。外部 AI agent 要改 N 筆案例屬性或回報 N 筆執行結果，只能打 N 次
單筆 API——直接放大 token 與呼叫成本。JWT/web 已有 `POST .../testcases/batch`（delete /
update_priority / update_tcg / update_section / update_test_set）、`POST .../items/
batch-update-results` 與 `POST .../testcases/bulk_clone`，app-token 缺對應能力。

## What Changes

- 將三個 JWT 批次實作的核心邏輯抽成可共用的 sync 函式（單一真相，避免兩條 auth 路徑漂移）：
  - `run_test_case_batch_operation_sync`（test_cases.py 內，actor 參數化）
  - `run_bulk_clone_sync`（test_cases.py 內）
  - `apply_batch_item_update_sync`（test_run_items.py 內，逐項結果更新）
- 新增 app-token 端點（皆逐項回報 per-item error，不整批失敗）：
  - `POST /api/app/teams/{team_id}/test-cases/batch-operations`：
    `delete` 需 `test_case:admin`；`update_priority` / `update_tcg` / `update_section` /
    `update_test_set` 需 `test_case:write`。`update_test_set` 沿用既有 Test Run scope cleanup。
  - `POST /api/app/teams/{team_id}/test-cases/bulk-clone`：`test_case:write`，
    語意同 JWT `/bulk_clone`（複製內容欄位、不複製 TCG/附件/結果，重複編號整批拒絕）。
  - `POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items/batch-update-results`：
    `test_run:execute`，欄位同 JWT（`test_result` / `assignee_name` / `executed_at` /
    `comment`），寫入相同 result history。
- JWT 端點行為不變（僅改為呼叫共用函式）。
- 不新增 `bulk_create` 對應端點：app-token 已有 `/test-cases/batch` 批次建立，語意重複。
- 更新 `tools/skills/tcrt-app` 文件（本機）：三個新端點、scope、body 形狀與批次工作流範例。

## Capabilities

### Modified Capabilities

- `app-token-test-case-api`: 新增批次操作（delete/update_*）與 bulk clone 端點需求。
- `app-token-test-run-api`: 新增批次結果更新端點需求。

## Impact

- Backend：`app/api/test_cases.py`（抽取兩個共用函式）、`app/api/test_run_items.py`（抽取
  逐項更新 helper）、`app/api/app_test_cases.py`、`app/api/app_test_runs.py`（新端點）。
- Tests：`test_app_token_test_case_api.py`、`test_app_token_test_run_api.py` 新增批次案例；
  跑 JWT 既有 batch 回歸確保抽取無行為變更。
- Scope 常數不變；無 schema 變更、無 migration。
- Rollback：移除三個新端點、將共用函式內聯回 JWT route 即可；無資料影響。
