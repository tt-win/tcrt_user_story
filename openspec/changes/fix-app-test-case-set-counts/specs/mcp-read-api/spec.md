## MODIFIED Requirements

### Requirement: MCP Test Case Set and Test Case Query with Filters
系統 SHALL 支援依 team scope、test case set、ticket / tcg、關鍵字與內容展開等條件查詢 test cases。
`/api/mcp/*` SHALL 保留 read-only 相容；`/api/app/*` SHALL 成為正式 app-token read/write
namespace，且兩個 test case read response SHALL 使用相同的 filter、pagination 與
Test Case Set summary 語意。每個 response 的 `sets[]` item SHALL 包含該 team 中對應
Test Case Set 的實際 `test_case_count`；此 count SHALL 計算直接屬於該 set 的全部
test cases，且不得因目前 case-list query 的 `set_id`、search、priority 或 test result
filter 改變。`page.total` SHALL 繼續表示目前 filters 後的 case-list 總數。

#### Scenario: Test case filtering works consistently
- **WHEN** 呼叫 team-scoped test case 查詢端點並帶入支援的篩選條件
- **THEN** 回傳結果與 scope / filter 一致，且未授權資料不會被洩漏

#### Scenario: App namespace returns actual counts for all sets
- **WHEN** app token 呼叫 `GET /api/app/teams/{team_id}/test-cases`，team 內的 set A 有 2
  個 cases、set B 沒有 cases
- **THEN** response 的 `sets[]` 包含 set A 的 `test_case_count: 2` 與 set B 的
  `test_case_count: 0`，且 `page.total` 等於 team 的全部 case 數

#### Scenario: Set summary count is independent of the case-list filter
- **WHEN** app token 呼叫 `GET /api/app/teams/{team_id}/test-cases?set_id={set_a_id}`
- **THEN** `page.total` 僅計算 set A 的 cases，而 `sets[]` 仍回傳 team 內每個 set 的
  team-wide `test_case_count`
