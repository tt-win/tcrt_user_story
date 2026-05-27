## 1. Data Model & Migration（資料模型與遷移）

- [x] 1.1 Add machine credential schema and ORM model（新增機器憑證 schema 與 ORM 模型）
- [x] 1.2 Add DB initialization/migration compatibility for machine credential tables and indexes（補齊 machine credential 資料表與索引的初始化/遷移相容）

## 2. Auth & Permission Guard（認證與授權守門）

- [x] 2.1 Implement machine token verification dependency for MCP routes（實作 MCP 路由專用 machine token 驗證依賴）
- [x] 2.2 Enforce `mcp_read` permission and team scope checks with deny-by-default（實作 `mcp_read` 與 team scope 驗證，預設拒絕）
- [x] 2.3 Add audit logging for allow/deny machine MCP access（補上 machine MCP allow/deny 稽核記錄）

## 3. MCP Read APIs（MCP 唯讀端點）

- [x] 3.1 Add `/api/mcp/teams` with sanitized response and total count（新增 `/api/mcp/teams`，回傳去敏感欄位與總數）
- [x] 3.2 Add `/api/mcp/teams/{team_id}/test-cases` with filters and pagination metadata（新增 team test-cases 查詢與 filter/分頁資訊）
- [x] 3.3 Add `/api/mcp/teams/{team_id}/test-runs` unified response for set/unassigned/adhoc with status filters（新增統一 test-runs 回傳，涵蓋 set/unassigned/adhoc 與狀態過濾）

## 4. Validation & Documentation（驗證與文件）

- [x] 4.1 Add tests for machine auth, permission scope, and MCP API contracts（新增 machine auth、scope 與 MCP API 契約測試）
- [x] 4.2 Add docs/config examples for MCP machine credential usage（補齊 MCP 機器憑證使用文件與設定範例）
