## Why

現行 Super Admin Dashboard 的 App Token 快捷入口會先要求選擇一個 Team，之後只載入該 Team 的 token。這把系統層管理工作限制成逐 Team 操作，也讓 Super Admin 無法在單一畫面盤點所有團隊的憑證狀態。

## What Changes

- Super Admin 從 System Administration Dashboard 開啟 App Token modal 時，立即載入所有團隊的 token metadata，不再要求先選擇 Team 或改變 `currentTeam`。
- 全域列表顯示 owner team，並保留既有 metadata-only 邊界；raw token 與 token hash 永遠不進列表。
- Super Admin 可在同一畫面對任何列表項目執行 global 撤銷與輪替操作；建立 token 時在建立表單中明確選擇 owner team，不透過切換工作區來隱含決定 owner。
- Global create/rotate route 均由 `require_super_admin()` 保護，rotate 由 server 依 token id 解析 owner team；Team Management 的 team-bound modal、Admin 個人 Dashboard 的 preferred-Team 流程維持不變。
- 同步三語系文案、OpenSpec scenarios、前端 contract tests 與跨團隊 API regression coverage。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `app-token-management-ui`: Super Admin organization context 改為全團隊 metadata list 與 row-level management；create 仍要求明確 owner Team。
- `system-administration-dashboard`: App Token quick action 開啟 global management mode，不先進入單一 Team picker。

## Impact

- 前端：擴充共用 `app-tokens.js` controller 與 modal，Team Management 的 team-bound 行為不變。
- API：保留既有 Super Admin `GET /api/app-tokens`、`DELETE /api/app-tokens/{token_id}`，新增同樣由 Super Admin 守門的 `POST /api/app-tokens` 與 `POST /api/app-tokens/{token_id}/rotate`；create body 明確攜帶 owner team。無 schema 或 migration。
- 安全：global mode 僅是 UI 選項；所有 global read/create/rotate/revoke 由後端 Super Admin guard 與 token owner lookup 授權，team-scoped endpoint 另外驗證 explicit `UserTeamPermission`，並以 modal pending-mutation guard 避免一次性 raw response 因 context 切換遺失。既有 team-scoped audit 與 owner predicate 保持有效。
- 測試：新增跨團隊列表/row action routing、global-mode/no-preselection、global endpoint guard、owner lookup、secret redaction 與 audit-scope assertions，並保留既有 Team Admin/Admin/非授權角色回歸測試。
- 回復：移除 global mode、owner-team 欄位/文案與新增 global routes 即可回到既有 Team picker；不影響既有 token 資料。
