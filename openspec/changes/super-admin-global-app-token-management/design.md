## Context

App Token lifecycle UI 已抽成 Team Management 與 Dashboard 共用的 Jinja modal/controller。既有後端已提供 team-scoped lifecycle endpoint（由 `_require_team_admin` 驗證 explicit `UserTeamPermission`）與 Super Admin `GET /api/app-tokens`、`DELETE /api/app-tokens/{token_id}`。本 change 會補上受 `require_super_admin()` 保護的 global create/rotate endpoint，沿用同一 token lifecycle core。問題在於 shared controller 將 `state.teamId` 視為所有操作的前置條件，因此 Super Admin system dashboard 只能先選一個 Team。

## Goals / Non-Goals

**Goals:**

- 在 system-administration Dashboard 的 global mode 立即讀取 `/api/app-tokens`，一次呈現所有 token metadata。
- 在列表中呈現 owner team，讓 Super Admin 能辨識每一筆 token 的團隊歸屬。
- 讓 create、rotate、revoke 都能從同一 modal 發起，且不透過 `currentTeam` 或 modal team context 轉換來授權。
- 讓 Team Management 與 Personal Admin Dashboard 保持原本 team-bound lifecycle。
- 以測試鎖定 API path、角色隔離、無 raw secret 與 global mode 的 no-preselection 行為。

**Non-Goals:**

- 不新增 Super Admin 專用 token scope、資料表或 migration；global create/rotate route 只提供明確的 Super Admin management boundary，並重用既有 lifecycle semantics。
- 不改變 app token principal 的 team scope 或 raw token one-time response；global management audit 需額外標示 global scope。
- 不讓一般 Admin/User/Viewer 取得 global list/create/rotate/revoke capability。
- 不把 Super Admin 的 global modal 綁定到或寫入 `currentTeam`。

## Decisions

1. **Server-selected global mode.** `index.js` 只在 server-projected `system_administration` Dashboard 將 `allowAllTeams: true` 傳給 controller。這個旗標只改變呈現與 endpoint 選擇，不能取代 API authorization。
2. **Separate global list path.** Global mode 直接呼叫 `GET /api/app-tokens`，不先呼叫任何 `/api/teams/{team_id}/app-tokens`。Global response additive 地帶回 owner team name；若 owner team name 缺少，仍顯示 stable team id，不丟失可追蹤性。Team-bound mode 繼續使用原 path。
3. **Explicit owner on create.** Global mode 的 create form 顯示 owner-team select，且只有有效、active 的 selected team id 才能送出 `POST /api/app-tokens`。該 endpoint body 明確包含 `owner_team_id` 並由 `require_super_admin()` 守門；建立後重新載入 global list，不把該 team 寫入 `state.teamId`。
4. **Global row mutations without context switch.** Global revoke 使用 Super Admin 專用 `DELETE /api/app-tokens/{token_id}`；global rotate 使用 `POST /api/app-tokens/{token_id}/rotate`，server 由 token id 自行解析 owner team，不接受 client team id。UI 不改變目前 modal/global context；失敗時保留列表並顯示 API error。
5. **Stable metadata-only rendering.** 列表只使用 response 的 name、owner team id/name、prefix、status、scopes、expiry、last-used 與 action；`raw_token`、`token_hash` 不渲染。一次性 raw token 僅存在 create/rotate 成功後的 warning panel，關閉 modal 或重設 scope 時清除。
6. **Explicit state invalidation and audit.** 每次 open、reset、load 與 mutation 都以 request version/owner id 驗證結果仍屬目前 modal session；pending mutation 期間阻止 modal 關閉或切換 context，直到一次性 raw response 已被安全處理；global list reload 不得被舊 team-bound request 覆蓋。Global create/rotate/revoke 的 audit details 必須標示 global management scope。

## Risks / Trade-offs

- **[Risk] Client forged `allowAllTeams` exposes data.** → Global list/create/rotate/revoke routes all require `require_super_admin()`; team-bound endpoints remain independently authorized. Add non-Super Admin denial tests and never rely on the flag for permission.
- **[Risk] Wrong owner team on create.** → Require an explicit select populated from authorized active teams; global POST validates the team server-side and creates only for that owner.
- **[Risk] Row action targets another token/team.** → Global rotate resolves owner from token id and global revoke resolves token id server-side; team-scoped endpoints retain owner predicates. Add wrong-team IDOR and global routing assertions.
- **[Risk] Team list and token list race or inactive team.** → Global metadata carries owner team name from the token query with stable ID fallback; create options only use the current authorized active-team response. Inactive-team tokens remain visible for audit/revocation.
- **[Risk] Secret leakage or one-time response loss during global rendering.** → Keep response models metadata-only; clear raw-token display on close/reset, pin the modal context while a mutation is pending, and assert frontend source never maps `raw_token`/`token_hash` into rows.
- **[Risk] Global actions are not attributable.** → Add a `management_scope=global` audit detail for global routes while preserving owner team id and existing event codes.
- **[Risk] Shared modal regressions.** → Keep team-bound branch explicit and extend existing frontend contract tests for both modes, locales, and no-preselection behavior.

## Migration Plan

No database or data migration. Deploy the additive Super Admin global create/rotate routes, owner-team metadata projection, controller/template/locale/test changes, and the explicit team-membership guard for team-scoped token APIs. Roll back by disabling `allowAllTeams` and removing the global routes/owner-team form/table additions; token records remain unchanged and team-scoped authorization remains enforced.

## Open Questions

None.
