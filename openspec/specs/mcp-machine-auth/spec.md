# mcp-machine-auth Specification

## Purpose
定義 MCP 讀取 API 的 machine principal 驗證、`mcp_read` 權限與 team scope 授權行為，確保對外讀取能力可被控管與稽核。
## Requirements
### Requirement: Machine Principal Authentication for MCP
系統 SHALL 透過 app-token principal 驗證 MCP 相容請求，並拒絕無效、過期、已撤銷或不存在的 token。既有 machine credential SHALL 視為 legacy app-token credential，映射為 principal 時 SHALL 原樣保留 `allow_all_teams` 與多 team scope；相容期內仍可呼叫 `/api/mcp/*` read endpoints，但新 token 與新管理介面 SHALL 使用 app token 命名。

#### Scenario: Valid machine credential can access MCP APIs
- **WHEN** 請求攜帶有效 legacy `mcp_read` token 或具備對應 read scope 的 app token
- **THEN** 系統將其解析為 app-token principal 並允許進入後續授權流程

#### Scenario: Invalid or expired machine credential is rejected
- **WHEN** token 無效、已過期、已撤銷或不存在
- **THEN** 系統回傳拒絕結果且不提供 MCP 資料

#### Scenario: New app token can read MCP compatibility endpoints
- **WHEN** app token 具備對應 read scope（`test_case:read` 或 `test_run:read`）
- **THEN** token SHALL 可在相容期內呼叫 `/api/mcp/*` 對應 read endpoints，無需額外 per-token 旗標

### Requirement: `mcp_read` Authorization with Team Scope
系統 SHALL 將既有 `mcp_read` 授權語意映射為 app-token read scope，並持續限制可讀取的 team scope。相容 `/api/mcp/*` endpoint SHALL 永遠只接受 read 操作；write scopes SHALL 只對 `/api/app/*` mutation endpoints 生效。

#### Scenario: Access denied without `mcp_read`
- **WHEN** legacy machine principal 不具備 `mcp_read` 且 app-token principal 不具備等價 read scope
- **THEN** 系統拒絕讀取 MCP API

#### Scenario: Access denied outside allowed team scope
- **WHEN** principal 嘗試讀取未授權的 team 資料
- **THEN** 系統拒絕該請求

#### Scenario: MCP namespace remains read-only
- **WHEN** principal 具備 app-token write scope 但對 `/api/mcp/*` 發送 mutation
- **THEN** 系統 SHALL 拒絕 mutation，並引導 client 使用 `/api/app/*`

### Requirement: Machine Credential Auditability
系統 SHALL 對允許與拒絕的 MCP 相容請求保留 audit 記錄。Audit actor SHALL 使用 app-token principal；legacy machine token SHALL 以相容欄位標示，不得偽裝成人類 user。

#### Scenario: Audit log is written for allowed request
- **WHEN** machine principal 或 app-token principal 成功存取 MCP API
- **THEN** 系統寫入對應 audit 記錄
- **AND** details SHALL 包含 credential id/name 與 compatibility mode

#### Scenario: Audit log is written for denied request
- **WHEN** principal 因權限、scope 或 namespace 問題被拒絕
- **THEN** 系統仍寫入可追蹤的 audit 記錄

