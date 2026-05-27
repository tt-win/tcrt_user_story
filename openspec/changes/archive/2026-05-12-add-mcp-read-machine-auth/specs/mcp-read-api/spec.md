## ADDED Requirements

### Requirement: MCP Teams Read Endpoint
The system SHALL provide an MCP teams endpoint that returns team count and team list in a safe read model (without secrets such as wiki token).  
系統必須提供 MCP 團隊讀取端點，回傳團隊總數與清單，且不得包含機密欄位。

#### Scenario: Team list returns count and sanitized fields
- **WHEN** client calls MCP teams endpoint with valid `mcp_read`
- **THEN** response SHALL include `total` and `items`, and SHALL NOT include `wiki_token` or equivalent secret fields

### Requirement: MCP Test Case Set and Test Case Query with Filters
The system SHALL provide MCP read endpoints to retrieve team-level test case sets and test cases with filter support.  
系統必須支援團隊層級的 test case set / test case 查詢與過濾參數。

#### Scenario: Test case filtering works consistently
- **GIVEN** team has multiple test cases across different sets and priorities
- **WHEN** client queries with filters (`set_id`, `search`, `priority`, `test_result`, `assignee`)
- **THEN** the system SHALL return only matched items and include deterministic pagination metadata

### Requirement: MCP Unified Test Run Read Model
The system SHALL provide MCP test run read response covering:
1) test run sets, 2) unassigned test runs, 3) ad-hoc test runs, with explicit status fields.  
系統必須提供統一的 Test Run 讀取模型，涵蓋三種來源與狀態資訊。

#### Scenario: Unified response includes all three run categories
- **GIVEN** a team contains set members, unassigned configs, and ad-hoc runs
- **WHEN** client calls MCP test-runs endpoint
- **THEN** response SHALL include `sets`, `unassigned`, `adhoc`, and status for each returned run object

#### Scenario: Run filters apply to all categories
- **WHEN** client queries test-runs endpoint with filters (`status`, `run_type`, `include_archived`)
- **THEN** the system SHALL apply filters consistently and return category-specific matched results

### Requirement: Backward Compatibility for Existing APIs
The system SHALL NOT break existing non-MCP endpoints and authentication flows while adding MCP endpoints.  
新增 MCP 端點時不得破壞既有 API 與使用者登入流程。

#### Scenario: Existing user JWT APIs remain unchanged
- **WHEN** existing frontend/API clients call current endpoints
- **THEN** behavior and response contracts SHALL remain backward compatible
