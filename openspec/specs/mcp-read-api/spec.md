# mcp-read-api Specification

## Purpose
定義 TCRT 對 MCP consumer 提供的唯讀查詢 API，包括 team、test case 與 test run 的統一讀取模型與過濾規則。

## Requirements
### Requirement: MCP Teams Read Endpoint
系統 SHALL 提供團隊清單讀取端點，回傳經過清理的欄位與總數資訊。

#### Scenario: Team list returns count and sanitized fields
- **WHEN** machine principal 查詢 `/api/mcp/teams`
- **THEN** 回應包含可公開欄位與總筆數，不暴露不必要的內部資訊

### Requirement: MCP Test Case Set and Test Case Query with Filters
系統 SHALL 支援依 team scope、test case set、ticket / tcg、關鍵字與內容展開等條件查詢 test cases。

#### Scenario: Test case filtering works consistently
- **WHEN** 呼叫 team-scoped test case 查詢端點並帶入支援的篩選條件
- **THEN** 回傳結果與 scope / filter 一致，且未授權資料不會被洩漏

### Requirement: MCP Unified Test Run Read Model
系統 SHALL 提供統一的 test run 讀取模型，涵蓋一般 run、adhoc run 與相關類型資料。

#### Scenario: Unified response includes all three run categories
- **WHEN** 呼叫 team-scoped test run 查詢
- **THEN** 回應使用統一格式呈現各類 run

#### Scenario: Run filters apply to all categories
- **WHEN** 帶入 test run 查詢條件
- **THEN** 系統以一致規則套用到各 run 類型

### Requirement: Backward Compatibility for Existing APIs
新增 MCP 讀取能力 SHALL 不改變既有 user JWT API 的行為與契約。

#### Scenario: Existing user JWT APIs remain unchanged
- **WHEN** 既有前端或一般使用者 API 呼叫原本端點
- **THEN** 不需配合 MCP 驗證模式而變更
