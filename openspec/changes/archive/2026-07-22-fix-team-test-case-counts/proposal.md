## Why

teams 清單與詳情回應中的 `test_case_count` 來自 `Team.test_case_count` 資料庫欄位，但全
codebase（含 scripts 與 bootstrap）沒有任何程式碼寫入該欄位——它永遠是預設值 0。
`GET /api/mcp/teams`、`GET /api/app/teams` 與 JWT `GET /api/teams` 因此一律回報 0，
外部 AI agent 會誤判 team 沒有任何測試案例，浪費額外查詢與 token。set 與 section 層級
的計數已在 `fix-app-test-case-set-counts` 修正為即時計算，team 層級是同類殘留問題。

## What Changes

- `GET /api/mcp/teams`、`GET /api/app/teams` 與 JWT `GET /api/teams` 的 `test_case_count`
  改為即時計算（`COUNT(test_case_local.id) GROUP BY team_id`），與 set / section 計數相同
  pattern；清單一次 grouped query，單一 team 端點用單筆 COUNT。
- JWT team 詳情與更新回應同步使用即時計數；建立回應固定為 0（新 team 必無案例）。
- 廢棄依賴 `Team.test_case_count` 欄位讀值（欄位保留不動，無 migration）。
- 補 regression tests 斷言三個介面的 team 計數為實際案例數。

## Capabilities

### Modified Capabilities

- `mcp-read-api`: Teams 讀取端點的 `test_case_count` 必須反映該 team 實際的 test case 數量，
  適用 `/api/mcp/teams` 與 canonical `/api/app/teams`。

## Impact

- Backend：`app/api/mcp.py`（新增 `_get_team_case_counts` helper + list_teams 使用）、
  `app/api/app_read.py`（list_app_teams 使用同 helper）、`app/api/teams.py`（list / detail /
  update 回應改即時計數）。
- Tests：`app/testsuite/test_mcp_api.py`、`app/testsuite/test_app_token_read_api.py` 增加
  team 計數斷言。
- 無 schema 變更、無 migration；`Team.test_case_count` 欄位保留（僅不再作為回應來源）。
- Rollback：還原三個端點的計數來源為欄位值即可，單純程式邏輯回退。
