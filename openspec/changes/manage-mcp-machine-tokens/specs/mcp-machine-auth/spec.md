# mcp-machine-auth Specification

## MODIFIED Requirements

### Requirement: Machine Principal Authentication for MCP
系統 SHALL 透過 machine credential 驗證 MCP 請求，並拒絕無效、已過期、**已撤銷**或不存在的 token。已撤銷（`status` 非 `ACTIVE`，即 `REVOKED`）的 credential SHALL 與無效 token 同樣被拒，回傳 401 並寫入 denied audit 記錄。

#### Scenario: Valid machine credential can access MCP APIs
- **WHEN** 請求攜帶有效（`status` 為 `ACTIVE` 且未過期）的 machine token
- **THEN** 系統將其解析為 machine principal 並允許進入後續授權流程

#### Scenario: Invalid or expired machine credential is rejected
- **WHEN** token 無效、已過期或不存在
- **THEN** 系統回傳拒絕結果且不提供 MCP 資料

#### Scenario: Revoked machine credential is rejected
- **WHEN** 某 credential 已被撤銷（`status = REVOKED`），其 token 仍被用於呼叫 MCP 讀取端點
- **THEN** 系統 SHALL 回 `401`（code `MACHINE_TOKEN_REVOKED`）且不提供 MCP 資料，並寫入一筆 denied（reason `machine_token_revoked`）的 audit 記錄
