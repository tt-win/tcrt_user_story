# mcp-machine-auth Specification

## Purpose
定義 MCP 讀取 API 的 machine principal 驗證、`mcp_read` 權限與 team scope 授權行為，確保對外讀取能力可被控管與稽核。

## Requirements
### Requirement: Machine Principal Authentication for MCP
系統 SHALL 透過 machine credential 驗證 MCP 請求，並拒絕無效、過期或不存在的 token。

#### Scenario: Valid machine credential can access MCP APIs
- **WHEN** 請求攜帶有效的 machine token
- **THEN** 系統將其解析為 machine principal 並允許進入後續授權流程

#### Scenario: Invalid or expired machine credential is rejected
- **WHEN** token 無效、已過期或不存在
- **THEN** 系統回傳拒絕結果且不提供 MCP 資料

### Requirement: `mcp_read` Authorization with Team Scope
系統 SHALL 驗證 machine credential 是否具有 `mcp_read` 權限，並限制其可讀取的 team scope。

#### Scenario: Access denied without `mcp_read`
- **WHEN** machine principal 不具備 `mcp_read`
- **THEN** 系統拒絕讀取 MCP API

#### Scenario: Access denied outside allowed team scope
- **WHEN** principal 嘗試讀取未授權的 team 資料
- **THEN** 系統拒絕該請求

### Requirement: Machine Credential Auditability
系統 SHALL 對允許與拒絕的 MCP machine 請求保留 audit 記錄。

#### Scenario: Audit log is written for allowed request
- **WHEN** machine principal 成功存取 MCP API
- **THEN** 系統寫入對應 audit 記錄

#### Scenario: Audit log is written for denied request
- **WHEN** machine principal 因權限或 scope 問題被拒絕
- **THEN** 系統仍寫入可追蹤的 audit 記錄
