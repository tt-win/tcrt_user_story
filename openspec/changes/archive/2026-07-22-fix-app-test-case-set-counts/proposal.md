## Why

`/api/app/teams/{team_id}/test-cases` 宣告與 MCP read model 相容，但回應中的
`sets[].test_case_count` 一律落入 schema 預設值 `0`；外部 skill 因而將有案例的
Test Case Set 誤報為空集合。需讓 canonical App Token API 回傳與 MCP 相同的實際計數。

## What Changes

- App Token test case read endpoint 會為 team 內每個 Test Case Set 回傳實際的
  `test_case_count`，以該 set 直接擁有的 test cases 計算。
- 加入 regression test，確認未過濾與帶 `set_id` 的 App Token response 都保有正確的
  set-level count 與 pagination total。
- 補充 `tcrt-app` skill/API 文件，明確說明 team total、set total 與 `set_id` filter 的
  讀取方式。

## Capabilities

### New Capabilities

<!-- None. -->

### Modified Capabilities

- `mcp-read-api`: App Token 的 canonical test case read response 必須與 MCP read model
  一致地回傳每個 Test Case Set 的實際案例數。

## Impact

- 影響 `GET /api/app/teams/{team_id}/test-cases` 的 response payload；欄位既有且型別不變，
  因此不是 breaking change。
- 修改 async read query、App Token read API tests，以及 `tools/skills/tcrt-app` 的使用文件。
- 不改 schema、資料或權限；無 migration。若需要回滾，只需還原 endpoint 計數組裝邏輯，
  不影響既有資料或 MCP compatibility endpoint。
