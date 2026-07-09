# mcp-read-api Specification

## MODIFIED Requirements

### Requirement: MCP Teams Read Endpoint
系統 SHALL 透過 `/api/mcp/teams` 保留 read-only 團隊清單相容端點，並在 `/api/app/teams` 提供正式 app-token 等價 read endpoint。兩者 SHALL 回傳經過清理的欄位與總數資訊；`/api/app/*` SHALL 使用 app-token principal，`/api/mcp/*` SHALL 使用相容 app-token principal。

#### Scenario: Team list returns count and sanitized fields
- **WHEN** machine principal 查詢 `/api/mcp/teams`
- **THEN** 回應包含可公開欄位與總筆數，不暴露不必要的內部資訊

#### Scenario: App namespace returns equivalent team list
- **WHEN** app-token principal 查詢 `/api/app/teams`
- **THEN** 回應 SHALL 與 `/api/mcp/teams` read model 相容

### Requirement: MCP Test Case Set and Test Case Query with Filters
系統 SHALL 支援依 team scope、test case set、ticket / tcg、關鍵字與內容展開等條件查詢 test cases。`/api/mcp/*` SHALL 保留 read-only 相容；`/api/app/*` SHALL 成為正式 app-token read/write namespace，其中 read payload SHALL 與 MCP read model 相容。

#### Scenario: Test case filtering works consistently
- **WHEN** 呼叫 team-scoped test case 查詢端點並帶入支援的篩選條件
- **THEN** 回傳結果與 scope / filter 一致，且未授權資料不會被洩漏

#### Scenario: App namespace supports the same read filters
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/test-cases` 並帶入 MCP read filters
- **THEN** response SHALL 使用相同 filter 語意與 pagination model

### Requirement: MCP Unified Test Run Read Model
系統 SHALL 提供統一的 test run 讀取模型，涵蓋一般 run、adhoc run 與相關類型資料。`/api/app/*` SHALL 提供正式等價 read endpoint，並另外提供受 app-token scope 控制的 mutation endpoints。

#### Scenario: Unified response includes all three run categories
- **WHEN** 呼叫 team-scoped test run 查詢
- **THEN** 回應使用統一格式呈現各類 run

#### Scenario: Run filters apply to all categories
- **WHEN** 帶入 test run 查詢條件
- **THEN** 系統以一致規則套用到各 run 類型

#### Scenario: App namespace provides equivalent test run read model
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/test-runs`
- **THEN** response SHALL 與 `/api/mcp/teams/{team_id}/test-runs` read model 相容

### Requirement: Backward Compatibility for Existing APIs
新增 app-token API 與 MCP 相容讀取能力 SHALL 不改變既有 user JWT API 的行為與契約。既有 `/api/mcp/*` read endpoints SHALL 在相容期內保持可用，但正式外部 API 文件 SHALL 以 `/api/app/*` 為 canonical namespace。

#### Scenario: Existing user JWT APIs remain unchanged
- **WHEN** 既有前端或一般使用者 API 呼叫原本端點
- **THEN** 不需配合 MCP 驗證模式而變更

#### Scenario: Existing MCP read clients remain functional
- **WHEN** 既有 `tcrt_mcp` client 在相容期內呼叫 `/api/mcp/*`
- **THEN** read-only request SHALL 繼續回應

#### Scenario: Mutation requires app namespace
- **WHEN** client 對 `/api/mcp/*` 發送 mutation
- **THEN** request SHALL 被拒絕
- **AND** response SHALL 指向 `/api/app/*` mutation API

### Requirement: MCP SHALL Provide Read-Only Test Case Sections Endpoint
系統 SHALL 提供 `GET /api/mcp/teams/{team_id}/test-case-sections` 相容端點，回傳指定 team 範圍內的 test case sections。端點 SHALL 維持唯讀；不接受 POST / PUT / PATCH / DELETE。正式 app-token namespace SHALL 另提供 `/api/app/teams/{team_id}/test-case-sections` 等價 read endpoint，並可在 `/api/app/*` 下提供受 scope 控制的 section mutation endpoints。

#### Scenario: 預設查詢回傳 team 全部 sections
- **WHEN** machine principal 對某 team 呼叫 `GET /api/mcp/teams/{team_id}/test-case-sections` 而不帶任何 query 參數
- **THEN** 回應的 `sections` 包含該 team 所有 set 下的所有 sections，`filters` echo 為 `{set_id: null, set_not_found: false, parent_section_id: null, roots_only: false, include_empty: true}`，`total` 等於 `sections` 長度

#### Scenario: 端點僅支援 GET
- **WHEN** 對 `/api/mcp/teams/{team_id}/test-case-sections` 發出 POST / PUT / DELETE 請求
- **THEN** API 回應 `405 Method Not Allowed` 或 `404`（依 FastAPI router 配置），不執行任何寫入

#### Scenario: 不存在的 team 回 404
- **WHEN** machine principal 對不存在的 `team_id` 呼叫 sections 端點
- **THEN** API 回應 `404` 並指明 `找不到團隊 ID {team_id}`

#### Scenario: 超出 team scope 的請求被拒
- **WHEN** 一個 `team_scope_ids` 不含目標 team 的 machine principal 呼叫該 team 的 sections 端點
- **THEN** API 回應 `403` 並 audit log 記錄 `TEAM_SCOPE_DENIED`

#### Scenario: App namespace section read is equivalent
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/test-case-sections`
- **THEN** response SHALL 與 MCP section read model 相容
