## ADDED Requirements

### Requirement: Machine Principal Authentication for MCP
The system SHALL provide a machine-to-machine authentication mechanism for MCP integration, allowing MCP servers to obtain an authenticated machine principal without interactive UI login.  
系統必須提供 MCP 專用的機器對機器認證，讓 MCP Server 在無互動登入流程下取得可驗證身分。

#### Scenario: Valid machine credential can access MCP APIs
- **GIVEN** MCP server has an active machine credential
- **WHEN** it calls an MCP endpoint with that credential
- **THEN** the system SHALL authenticate the request as a machine principal and attach principal context to request state

#### Scenario: Invalid or expired machine credential is rejected
- **WHEN** MCP endpoint receives an invalid, revoked, or expired machine credential
- **THEN** the system SHALL return authentication failure and SHALL NOT expose protected data

### Requirement: `mcp_read` Authorization with Team Scope
The system SHALL enforce a dedicated `mcp_read` permission and optional team scope for machine principals.  
系統必須強制檢查 `mcp_read` 權限，並支援 team scope 限制機器身分可讀取的團隊範圍。

#### Scenario: Access denied without `mcp_read`
- **WHEN** authenticated principal does not have `mcp_read`
- **THEN** the system SHALL deny access to MCP read endpoints

#### Scenario: Access denied outside allowed team scope
- **GIVEN** principal is bound to team scope [1, 3]
- **WHEN** it requests team 2 data
- **THEN** the system SHALL deny access and return authorization failure

### Requirement: Machine Credential Auditability
The system SHALL emit audit logs for machine-authenticated MCP API access, including principal identity, endpoint, team scope decision, and result.  
系統必須為機器身分的 MCP 存取寫入稽核軌跡。

#### Scenario: Audit log is written for allowed request
- **WHEN** machine principal successfully reads MCP endpoint data
- **THEN** an audit entry SHALL be recorded with principal id, target endpoint, team id, and success status

#### Scenario: Audit log is written for denied request
- **WHEN** machine principal is denied by scope or permission checks
- **THEN** an audit entry SHALL be recorded with denial reason and target metadata
