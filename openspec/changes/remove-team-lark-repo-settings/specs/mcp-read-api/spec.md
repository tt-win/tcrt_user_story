## MODIFIED Requirements

### Requirement: MCP Teams Read Endpoint

系統 SHALL 透過 `/api/mcp/teams` 保留 read-only 團隊清單相容端點，並在 `/api/app/teams` 提供正式 app-token 等價 read endpoint。兩者 SHALL 回傳經過清理的欄位與總數資訊；`/api/app/*` SHALL 使用 app-token principal，`/api/mcp/*` SHALL 使用相容 app-token principal。

team read model 中的 `is_lark_configured` 欄位 SHALL 保留於回應（維持既有 response schema 相容性），但 SHALL 一律回傳 `false` 並視為 deprecated：team 層級的 Lark Bitable 設定已由 `remove-team-lark-repo-settings` 移除，系統中不再存在「已設定 Lark」的 team。Client SHALL NOT 依據此欄位提供任何 Lark 相關功能分支。

#### Scenario: Team list returns count and sanitized fields
- **WHEN** machine principal 查詢 `/api/mcp/teams`
- **THEN** 回應包含可公開欄位與總筆數，不暴露不必要的內部資訊

#### Scenario: App namespace returns equivalent team list
- **WHEN** app-token principal 查詢 `/api/app/teams`
- **THEN** 回應 SHALL 與 `/api/mcp/teams` read model 相容

#### Scenario: Deprecated Lark flag is always false
- **WHEN** 任一 principal 查詢 `/api/mcp/teams` 或 `/api/app/teams`
- **THEN** 每一筆 team 的 `is_lark_configured` SHALL 為 `false`，即使該 team 的資料庫列仍保有歷史 Lark token 值
