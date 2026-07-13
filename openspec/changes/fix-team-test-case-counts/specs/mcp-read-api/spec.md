# mcp-read-api Specification

## MODIFIED Requirements

### Requirement: MCP Teams Read Endpoint
系統 SHALL 提供團隊清單讀取端點，回傳經過清理的欄位與總數資訊。回應中每個 team 的 `test_case_count` SHALL 反映該 team 實際擁有的 test case 數量（即時計算，不得依賴未維護的快照欄位），`/api/mcp/teams` 與 canonical `/api/app/teams` 皆適用。

#### Scenario: Team list returns count and sanitized fields
- **WHEN** machine principal 查詢 `/api/mcp/teams`
- **THEN** 回應包含可公開欄位與總筆數，不暴露不必要的內部資訊

#### Scenario: Team 的 test_case_count 為實際案例數
- **WHEN** 某 team 擁有 N 筆 test cases，principal 查詢 `/api/mcp/teams` 或 `/api/app/teams`
- **THEN** 該 team 項目的 `test_case_count` SHALL 等於 N
- **AND** 沒有任何 test case 的 team SHALL 回傳 0
