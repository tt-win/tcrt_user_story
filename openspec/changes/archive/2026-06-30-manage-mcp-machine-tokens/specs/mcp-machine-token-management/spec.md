# mcp-machine-token-management Specification

## ADDED Requirements

### Requirement: Super Admin can list MCP machine credentials (metadata only)
端點 `GET /api/organization/mcp/machine-tokens` SHALL 回傳所有 MCP machine credential 的 **metadata**，供 Super Admin 盤點已核發的 token。授權 SHALL 沿用 `require_super_admin()`；非 Super Admin SHALL 被拒（403）。

回應 SHALL 採 `{ "success": true, "data": { "items": [...], "total": <int> } }` 包裝（與 sibling create 端點一致），`items` 依 `created_at` 由新到舊排序。每筆 `items[i]` SHALL 含：

- `credential_id`, `name`, `description`
- `permission`, `status`（`active` / `revoked`）
- `allow_all_teams`, `team_scope_ids`（由 `team_scope_json` 解析；`allow_all_teams=true` 時為空陣列）
- `expires_at`, `last_used_at`, `created_at`, `updated_at`

回應 SHALL NOT 包含 `token_hash`，且因明文未留存而**不可能**包含 raw token。列表 SHALL 同時包含 `active` 與 `revoked` 狀態的 credential（不過濾），讓撤銷後仍可追蹤。

#### Scenario: Super Admin 列出已核發 token
- **WHEN** Super Admin 呼叫 `GET /api/organization/mcp/machine-tokens`
- **THEN** SHALL 回 `200`，`data.items` 含所有 credential 的 metadata，依 `created_at` 由新到舊排序，`data.total` 等於 items 數

#### Scenario: 列表不外洩任何 secret
- **WHEN** 取得列表回應
- **THEN** 每筆 item SHALL NOT 含 `token_hash` 或任何 raw token 欄位，僅含上述 metadata 欄位

#### Scenario: 已撤銷的 token 仍列出且標示狀態
- **WHEN** 某 credential 的 `status` 為 `revoked`
- **THEN** 該筆 SHALL 仍出現於列表，且 `status` 欄位為 `revoked`

#### Scenario: 非 Super Admin 不可列出
- **WHEN** 一般 Admin 或更低權限者呼叫該端點
- **THEN** SHALL 回 `403`，不回傳任何 credential 資料

### Requirement: Super Admin can revoke a machine credential (soft, audited)
端點 `DELETE /api/organization/mcp/machine-tokens/{credential_id}` SHALL 將指定 credential 的 `status` 由 `ACTIVE` 改為 `REVOKED`（**軟刪**，不刪除資料列，保留 `last_used_at` 與稽核軌跡）。授權 SHALL 沿用 `require_super_admin()`；非 Super Admin SHALL 被拒（403）。

撤銷成功 SHALL 寫入一筆 audit 記錄（`ActionType.UPDATE`、`ResourceType.SYSTEM`、`resource_id = "mcp_machine_credential:{id}"`），格式與 create 稽核對齊。撤銷後該 credential 於下一次 MCP 驗證即被拒（見 `mcp-machine-auth`）。

#### Scenario: 撤銷有效 token
- **WHEN** Super Admin 對一個 `status=active` 的 credential 呼叫 DELETE
- **THEN** SHALL 回 `200`，該 credential 於 DB 的 `status` 變為 `REVOKED` 且資料列仍存在，並寫入一筆 `ActionType.UPDATE` 的 audit 記錄

#### Scenario: 撤銷不存在的 token 回 404
- **WHEN** 呼叫 DELETE 的 `credential_id` 不存在
- **THEN** SHALL 回 `404`，不寫入撤銷稽核

#### Scenario: 重複撤銷為 idempotent
- **WHEN** 對一個已是 `status=revoked` 的 credential 再次呼叫 DELETE
- **THEN** SHALL 回 `200`（no-op），DB 狀態維持 `REVOKED`，且 SHALL NOT 重複寫入撤銷稽核

#### Scenario: 非 Super Admin 不可撤銷
- **WHEN** 一般 Admin 或更低權限者呼叫該端點
- **THEN** SHALL 回 `403`，credential 狀態不變
