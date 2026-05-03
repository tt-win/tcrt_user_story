# mcp-read-api Specification

## Purpose
定義 TCRT 對 MCP consumer 提供的唯讀查詢 API，包括 team、test case 與 test run 的統一讀取模型與過濾規則。本次 change 擴充 test_data 欄位的暴露行為。

## ADDED Requirements

### Requirement: MCP Test Case Detail SHALL Expose test_data
單筆 test case detail 端點 (`GET /api/mcp/teams/{team_id}/test-cases/{test_case_id}`) SHALL 在回應中包含 `test_data` 陣列；陣列中的每一項 SHALL 完整保留 `id` / `name` / `category` / `value` 四個欄位，不在 server 端做任何 redaction。當 test case 沒有 test_data 時，SHALL 回傳 `[]` 而非 `null`。

#### Scenario: Detail 端點回傳 test_data 陣列
- **WHEN** machine principal 呼叫 `GET /api/mcp/teams/{team_id}/test-cases/{test_case_id}`，且該 test case 已有兩筆 test_data（分別為 `category="text"` 與 `category="credential"`）
- **THEN** 回應 `test_case.test_data` 為長度 2 的陣列，每筆物件包含 `id`、`name`、`category`、`value` 四欄位且 value 未被截斷或遮罩

#### Scenario: 沒有 test_data 的 test case
- **WHEN** machine principal 對一個未設定任何 test_data 的 test case 呼叫 detail 端點
- **THEN** 回應 `test_case.test_data` 為空陣列 `[]`

#### Scenario: 異常 test_data_json 不應導致 500
- **WHEN** DB 中的 `test_data_json` 欄位包含無法解析的 JSON 字串（資料毀損）
- **THEN** 端點 SHALL 回傳 `test_data: []` 而非 500 錯誤

### Requirement: MCP List/Lookup SHALL Support include_test_data Query Parameter
`GET /api/mcp/teams/{team_id}/test-cases` 與 `GET /api/mcp/test-cases/lookup` 端點 SHALL 接受 `include_test_data: bool = false` query param。當為 `true` 時，回應中每筆 test_case payload SHALL 包含 `test_data` 陣列；當為 `false`（預設）或未提供時，回應 SHALL 不包含 `test_data` 欄位以維持向後相容。回應的 `filters` 物件 SHALL 回 echo `include_test_data` 的實際值。

#### Scenario: include_test_data=true 帶出 test_data
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-cases?include_test_data=true`
- **THEN** 回應的每筆 `test_cases[i]` 包含 `test_data` 陣列，且 `filters.include_test_data == true`

#### Scenario: 預設不帶 test_data（向後相容）
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-cases` 且未提供 `include_test_data`
- **THEN** 回應的 `test_cases[i]` 不包含 `test_data` 鍵，且 `filters.include_test_data == false`

#### Scenario: lookup 端點支援同樣語意
- **WHEN** 呼叫 `GET /api/mcp/test-cases/lookup?test_case_number=TC-A-001&include_test_data=true`
- **THEN** 回應的 `items[i].test_case` 包含 `test_data` 陣列

#### Scenario: include_test_data 與 include_content 解耦
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-cases?include_content=true&include_test_data=false`
- **THEN** 回應的 `test_cases[i]` 包含 `precondition` / `steps` / `expected_result` 但不包含 `test_data`

### Requirement: MCP test_data Payload SHALL Preserve Category Without Server-Side Redaction
所有 MCP 端點回傳的 `test_data[i]` 物件 SHALL 完整保留 `category` 欄位（值為 `text|number|credential|email|url|identifier|date|json|other` 之一）。對於 `category="credential"` 等敏感分類，server SHALL NOT 在回應中對 `value` 進行截斷、遮罩或雜湊化；redaction 屬下游消費端職責（例如 audit log 寫入時）。

#### Scenario: credential 類別 value 完整回傳
- **WHEN** test case 含一筆 `category="credential", name="admin_password", value="P@ssw0rd!"` 的 test_data，machine principal 呼叫 detail 端點
- **THEN** 回應 `test_case.test_data[0].value == "P@ssw0rd!"` 且 `category == "credential"`

#### Scenario: 未知 category 字串回傳原值
- **WHEN** DB 中存有 `category="legacy_secret"`（不在 enum 列表中）的 test_data 項
- **THEN** 端點回傳該項時 `category` 為原字串（由 `TestDataItem` 的 `field_validator` 在寫入路徑早已 fallback 至 `text`，但讀取路徑 SHALL 不再做二次 normalization）

## MODIFIED Requirements

### Requirement: MCP Test Case Set and Test Case Query with Filters
系統 SHALL 支援依 team scope、test case set、ticket / tcg、關鍵字、內容展開與 test_data 展開等條件查詢 test cases。新增 `include_test_data` query param 不影響既有的 `set_id` / `search` / `priority` / `test_result` / `assignee` / `tcg` / `ticket` / `include_content` / `strict_set` / `skip` / `limit` 行為。

#### Scenario: Test case filtering works consistently
- **WHEN** 呼叫 team-scoped test case 查詢端點並帶入支援的篩選條件
- **THEN** 回傳結果與 scope / filter 一致，且未授權資料不會被洩漏

#### Scenario: include_test_data 與既有 filter 同時使用
- **WHEN** 呼叫 `GET /api/mcp/teams/{team_id}/test-cases?priority=High&include_test_data=true&limit=50`
- **THEN** 回應同時套用 priority 過濾與 test_data 帶出，`page.limit == 50` 且 `filters.priority == "High"`、`filters.include_test_data == true`
