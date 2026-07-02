## 1. 後端 — 列表端點

- [x] 1.1 在 [`app/api/organization_sync.py`](app/api/organization_sync.py) 新增 `_serialize_machine_credential(credential)` helper，回傳白名單 metadata dict：`credential_id`、`name`、`description`、`permission`、`status`（取 `.value`）、`allow_all_teams`、`team_scope_ids`（由 `team_scope_json` 解析，沿用 `json.loads` + `_normalize_team_scope_ids` 模式；`allow_all_teams` 時回 `[]`）、`expires_at` / `last_used_at` / `created_at` / `updated_at`（ISO 字串或 `None`）。**禁止**輸出 `token_hash`。
- [x] 1.2 新增 `@router.get("/mcp/machine-tokens")` handler `list_mcp_machine_tokens`，依賴 `require_super_admin()` 與 `get_main_access_boundary`；以 `main_boundary.run_read` 執行 `select(MCPMachineCredential).order_by(MCPMachineCredential.created_at.desc(), MCPMachineCredential.id.desc())`，逐筆過 `_serialize_machine_credential`。
- [x] 1.3 回應包裝為 `{ "success": True, "data": { "items": [...], "total": len(items) } }`。

## 2. 後端 — 撤銷端點

- [x] 2.1 新增 `@router.delete("/mcp/machine-tokens/{credential_id}")` handler `revoke_mcp_machine_token(credential_id: int, request: Request, ...)`，依賴 `require_super_admin()`。
- [x] 2.2 於 `main_boundary.run_write` 內：以 id 載入 credential；`None` → 回 dict 標記 `not_found`；若 `status == REVOKED` → 標記 `already_revoked`（不改動）；否則設 `status = MCPMachineCredentialStatus.REVOKED`、`flush`，回 `changed=True` 與 `name`。
- [x] 2.3 handler 依結果分支：`not_found` → `HTTPException(404, code="MCP_MACHINE_TOKEN_NOT_FOUND")`；`already_revoked` → 回 200（no-op，不寫稽核）；`changed` → 寫一筆 `audit_service.log_action(action_type=ActionType.UPDATE, resource_type=ResourceType.SYSTEM, resource_id=f"mcp_machine_credential:{credential_id}", action_brief=f"撤銷 MCP machine token: {name}", ...)`（稽核失敗只 log warning，不影響回應，比照 create）。
- [x] 2.4 成功回應：`{ "success": True, "data": { "credential_id": id, "status": "revoked" } }`。

## 3. 前端 — HTML

- [x] 3.1 在 [`team_management.html`](app/templates/team_management.html:443) `#tab-pane-mcp-token` 以「已核發 Token」列表卡為**主畫面**：card-header 含標題（`mcpToken.title`）、「核發 Token」鈕 `#mcpTokenOpenCreateBtn`（`data-bs-toggle="modal"` → `#mcpTokenCreateModal`）與 Refresh 鈕 `#mcpTokenRefreshBtn`；card-body 含 loading `#mcpTokenListLoading`、空狀態 `#mcpTokenListEmpty`、`<table>` 含 `<tbody id="mcpTokenTableBody">`（表頭：名稱／狀態／scope／到期／最後使用／建立／操作，皆掛 `data-i18n`）。
- [x] 3.2 將原建立表單移入頂層 modal `#mcpTokenCreateModal`（form id 與所有欄位 id 原封保留，reset/generate 移至 modal-footer），置於與其他 admin modal 同層。

## 4. 前端 — JS

- [x] 4.1 在 [`initMcpTokenTab()`](app/static/js/team-management/main.js:132) 綁定：`#mcpTokenRefreshBtn` click → `loadMcpTokens()`；`#tab-mcp-token` 的 `shown.bs.tab` → 首次顯示 lazy load；`#mcpTokenCreateModal` 的 `show.bs.modal` → `refreshMcpTokenTeamScopeOptions()` + `resetMcpTokenForm()`（每次開啟重整團隊、清空殘留結果）。
- [x] 4.2 實作 `loadMcpTokens()`：`AuthClient.fetch('/api/organization/mcp/machine-tokens')`，控制 loading／empty／table 三態；失敗以 `AppUtils.showError(getI18n('mcpToken.listLoadFailed', ...))`。
- [x] 4.3 實作 render：每筆組 row，狀態徽章由前端衍生（`revoked` 優先 → 否則 `expires_at` 已過為 `expired` → 否則 `active`）；scope 顯示「所有團隊」或 `#id` 清單；`expires_at`/`last_used_at`/`created_at` 過 `formatIsoDatetime`（未使用顯示 `getI18n('mcpToken.neverUsed', '從未')`、不過期顯示 `mcpToken.neverExpires`）；所有文字過 `escapeHtml`。
- [x] 4.4 實作 `revokeMcpToken(credentialId, name)`：`confirm` 顯示 token 名稱 → `AuthClient.fetch(DELETE)` → 成功 `AppUtils.showSuccess` + `loadMcpTokens()`；失敗 `AppUtils.showError`。僅對非 `revoked` 列渲染撤銷鈕。
- [x] 4.5 在 [`createMcpMachineToken`](app/static/js/team-management/main.js:260) 成功分支末尾呼叫 `loadMcpTokens()`，使新 token 立即出現於列表。

## 5. 前端 — i18n

- [x] 5.1 在 [`zh-TW.json`](app/static/locales/zh-TW.json) 新增 `mcpToken.*` key：`listTitle`、`colName`、`colStatus`、`colScope`、`colExpires`、`colLastUsed`、`colCreated`、`colActions`、`statusActive`、`statusRevoked`、`statusExpired`、`scopeAllTeams`、`neverUsed`、`revokeButton`、`revokeConfirm`、`revokeSuccess`、`revokeFailedPrefix`、`listLoadFailed`、`listEmpty`、`listLoading`（另含 `listSubtitle`、`openCreateButton`、`createModalTitle`）。
- [x] 5.2 在 [`zh-CN.json`](app/static/locales/zh-CN.json) 補上相同 key（簡中翻譯）。
- [x] 5.3 在 [`en-US.json`](app/static/locales/en-US.json) 補上相同 key（英文翻譯）。

## 6. 測試

- [x] 6.1 在 [`test_organization_mcp_machine_token_api.py`](app/testsuite/test_organization_mcp_machine_token_api.py) 沿用 `organization_token_test_env`，新增 `test_super_admin_can_list_mcp_machine_tokens`：先建兩個 token，GET 列表，斷言 `data.total==2`、依 `created_at` 由新到舊、含預期 metadata 欄位。
- [x] 6.2 新增 `test_list_excludes_token_secret`：斷言每筆 item 不含 `token_hash`、`raw_token` key。
- [x] 6.3 新增 `test_admin_cannot_list_mcp_machine_tokens`：切換成 admin → GET 回 403。
- [x] 6.4 新增 `test_super_admin_can_revoke_mcp_machine_token`：建 token → DELETE → 回 200；查 DB 該列仍在且 `status == REVOKED`。
- [x] 6.5 新增 `test_revoke_nonexistent_token_returns_404`：DELETE 不存在 id → 404、code `MCP_MACHINE_TOKEN_NOT_FOUND`。
- [x] 6.6 新增 `test_revoke_is_idempotent`：對已撤銷者再 DELETE → 200，DB 仍 `REVOKED`。
- [x] 6.7 新增 `test_admin_cannot_revoke_mcp_machine_token`：切換成 admin → DELETE 回 403、狀態不變。
- [x] 6.8 在 MCP auth 測試（[`test_mcp_api.py`](app/testsuite/test_mcp_api.py)）`_seed_mcp_data` 新增 `revoked-reader`（`status=REVOKED`），於 `test_mcp_auth_requires_valid_machine_token` 斷言該 token 打 `/api/mcp/teams` → 401、code `MACHINE_TOKEN_REVOKED`（驗證 `mcp-machine-auth` 新 scenario）。

## 7. 驗收

- [x] 7.1 `pytest app/testsuite/test_organization_mcp_machine_token_api.py app/testsuite/test_mcp_api.py -q` 全綠（37 passed）。
- [x] 7.2 `openspec validate manage-mcp-machine-tokens --strict` 通過。
- [ ] 7.3 手動驗證：UI 建立 token → 列表立即出現 → 撤銷 → 列表狀態變 revoked → 用該 token 打 MCP 端點得 401。PR description 附 `curl` 範例（list 與 revoke 各一）。
