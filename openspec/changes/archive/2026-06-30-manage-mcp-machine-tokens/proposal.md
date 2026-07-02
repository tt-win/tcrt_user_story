## Why

MCP machine token 目前**只有建立這一條路**：[`POST /api/organization/mcp/machine-tokens`](app/api/organization_sync.py:104) 會回傳一次性 raw token，之後 token 以 SHA256 hash 存於 `mcp_machine_credentials`（[`app/models/database_models.py:1694`](app/models/database_models.py:1694)）。沒有任何列出與撤銷端點——全 repo 中 `MCPMachineCredential` 只在 create 端點與驗證 lookup（[`app/auth/mcp_dependencies.py:183`](app/auth/mcp_dependencies.py:183)）被引用。

實務影響：Super Admin 一旦關掉「僅顯示一次」的建立結果，就**完全看不到自己核發過哪些 token**、各自的 scope／到期／最後使用時間，也**無法撤銷**疑似外洩或不再使用的 token——只能直接改資料庫。這是治理與安全缺口：token 是對外唯讀資料的鑰匙，卻無法盤點與回收。

值得注意的是 auth 端**已經**會擋下非 ACTIVE 的 credential（[`app/auth/mcp_dependencies.py:212`](app/auth/mcp_dependencies.py:212) 檢查 `status == ACTIVE`，否則回 401 `MACHINE_TOKEN_REVOKED`）。也就是說「撤銷」的執行面早已具備，缺的是**讓人能撤銷的管理面**，以及讓 `mcp-machine-auth` spec 把這個既有行為寫明。

## What Changes

- 新增唯讀列表端點 `GET /api/organization/mcp/machine-tokens`（Super Admin only，沿用 `require_super_admin()`）：
  - 回傳所有 machine credential 的 **metadata**，依 `created_at` 由新到舊排序。
  - 每筆含 `credential_id / name / description / permission / status / allow_all_teams / team_scope_ids / expires_at / last_used_at / created_at / updated_at`。
  - **SHALL NOT** 回傳 `token_hash`，更不可能回傳 raw token（明文未留存）。
  - 回應沿用 sibling create 端點的 `{ "success": true, "data": { ... } }` 包裝。
- 新增撤銷端點 `DELETE /api/organization/mcp/machine-tokens/{credential_id}`（Super Admin only）：
  - **軟刪**：將 `status` 由 `ACTIVE` 改為 `REVOKED`，不刪除資料列（保留稽核軌跡與 `last_used_at`）。
  - 寫入 audit log（`ActionType.UPDATE` / `ResourceType.SYSTEM` / `resource_id = mcp_machine_credential:{id}`），與 create 的稽核格式對齊。
  - 找不到 id → 404；對已是 `REVOKED` 的 token 再撤銷 → **idempotent 回 200**（no-op，不重複寫稽核）。
- 前端在 [`team_management.html`](app/templates/team_management.html:443) 的 MCP Token 分頁**改以「已核發 Token」列表為主畫面**：顯示名稱、狀態（active／revoked／expired）、scope、到期、最後使用時間，每筆 active token 提供「撤銷」按鈕（confirm 後呼叫 DELETE 並重載）。原本的建立表單**移入疊加的「核發 Token」modal**（`#mcpTokenCreateModal`，由列表卡 header 的按鈕開啟），一次性 raw token 結果顯示於 modal 內。
- [`team-management/main.js`](app/static/js/team-management/main.js:132) 新增 `loadMcpTokens()` / render / `revokeMcpToken()`，並在建立成功後自動重載列表。
- 三語系檔（[`zh-TW`](app/static/locales/zh-TW.json)／`zh-CN`／`en-US`）新增列表與撤銷相關 i18n key。

## 非目標 (Non-goals)

- **不**重現 raw token。token 以 hash 存放、明文僅建立時顯示一次，這是刻意的安全設計（同 GitHub PAT）；列表只回 metadata。
- **不**提供編輯既有 token 的 scope／到期／描述。本次只加「列出」與「撤銷」，要改設定請撤銷後重建。
- **不**做硬刪除（`DELETE` row）。撤銷一律軟刪，保留稽核與最後使用紀錄。
- **不**改動 create 端點與 token 驗證流程；auth 端對 REVOKED 的拒絕行為早已存在，本 change 只補 spec 文字。
- **不**新增分頁參數。machine token 數量級小，列表一次回全部即可（如未來成長再加 `skip`/`limit`）。

## Capabilities

### New Capabilities
- `mcp-machine-token-management`：Super Admin 對 MCP machine credential 的**管理生命週期之列出與撤銷**——以 metadata-only（永不重現 secret）列出既有 credential，並以軟刪（status → REVOKED）＋稽核方式撤銷。

### Modified Capabilities
- `mcp-machine-auth`：補一條既有但未寫明的需求——已撤銷（`REVOKED`）的 machine credential 在 MCP 驗證時 SHALL 被拒（程式已於 [`mcp_dependencies.py:212`](app/auth/mcp_dependencies.py:212) 實作），使「撤銷」能端到端被驗收。

## Impact

### Code
- [app/api/organization_sync.py](app/api/organization_sync.py)：新增 `list_mcp_machine_tokens`（GET）與 `revoke_mcp_machine_token`（DELETE）兩個 route handler，沿用既有 `MainAccessBoundary`、`require_super_admin()`、`audit_service` 模式。
- [app/templates/team_management.html](app/templates/team_management.html:443)：MCP Token 分頁新增列表卡與表格容器。
- [app/static/js/team-management/main.js](app/static/js/team-management/main.js:132)：新增列表載入／渲染／撤銷邏輯，串接分頁顯示時機。
- [app/static/locales/zh-TW.json](app/static/locales/zh-TW.json) / `zh-CN.json` / `en-US.json`：新增 `mcpToken.*` 列表與撤銷 key。

### Tests
- [app/testsuite/test_organization_mcp_machine_token_api.py](app/testsuite/test_organization_mcp_machine_token_api.py)：沿用既有 `organization_token_test_env` fixture，新增列表（含「不外洩 token_hash／raw_token」斷言）、撤銷（DB status 變 REVOKED、row 仍在）、權限（admin 403）、404、idempotent 重複撤銷等測試。
- 既有 mcp auth 測試補一條：REVOKED token 打 MCP 讀取端點被拒（驗證 `mcp-machine-auth` 新 scenario，行為已存在）。

### Migration / 相容性
- **無 DB migration**：重用既有 `mcp_machine_credentials` 表與 `MCPMachineCredentialStatus.REVOKED`（[`app/models/database_models.py:59`](app/models/database_models.py:59)）。
- 純新增端點 + UI；舊 consumer 與既有 create 流程行為不變。
- 撤銷為非破壞性軟刪，可藉直接改 DB status 還原（雖非本次 UI 範圍）。
