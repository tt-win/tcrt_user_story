## Why

App Token API 可以更新已知 Test Run Item，但沒有列出指定 Test Config items 的端點。
外部 skill 因而無法取得 item IDs、保存原結果或安全地執行逐筆 result 更新。

## What Changes

- 新增受 team scope 與 `test_run:read` 保護的 App Token Test Run Item list endpoint。
- 回傳安全的 item execution metadata 與 pagination，讓 client 可建立更新前快照並以
  `test_run:execute` 的既有單筆 endpoint 更新結果。
- 更新 tcrt-app API 文件與回歸測試，說明安全的「列出 → 備份 → 逐筆更新 → 驗證」流程。

## Capabilities

### New Capabilities

- `app-token-test-run-item-read`: 讓 App Token 在單一 team 與 Test Config 範圍內，讀取
  paginated Test Run Items 與 execution metadata。

### Modified Capabilities

<!-- None. -->

## Impact

- 新增 `GET /api/app/teams/{team_id}/test-run-configs/{config_id}/items`，不改既有 endpoint
  或 schema，也不需要 migration。
- 影響 `app/api/app_test_runs.py`、App Token test-run tests，以及本機 tcrt-app skill 文件。
- response 不回傳 test case content、附件、credential-category test data 或完整 assignee
  資訊；僅提供執行與回復所需欄位。若需回滾，停用 router 即可，無資料回復作業。
