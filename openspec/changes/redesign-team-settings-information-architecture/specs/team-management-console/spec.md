## ADDED Requirements

### Requirement: Team management page scope is limited to per-team data

`/team-management` 頁面 SHALL 僅包含以下功能：team 清單、新增/編輯/刪除 team（含 Lark Bitable `wiki_token` 與 `test_case_table_id` 連結欄位、Lark 連線驗證）、team 卡片操作選單（進入團隊各功能頁、App Token 入口）。頁面 SHALL NOT 包含人員管理、組織同步、Service 管理、MCP Token 簽發、組織自動化基礎設施等 org-wide 功能（相關契約見 `organization-management-console`）。

#### Scenario: Team CRUD remains available
- **WHEN** 具備權限的使用者在 `/team-management` 建立、編輯或刪除一個 team
- **THEN** 行為與既有 `app/api/teams.py` contract 一致，不受本次頁面重組影響

#### Scenario: Organization-wide tabs are no longer present on this page
- **WHEN** 任何角色的使用者開啟 `/team-management`
- **THEN** 頁面 DOM SHALL NOT 包含 `#tab-pane-personnel`、`#tab-pane-org`、`#tab-pane-service-management`、`#tab-pane-mcp-token`、`#tab-pane-org-automation-infra` 或其容器 modal（原「組織與系統設定」modal）

### Requirement: Per-team App token issuance remains on the team management page

App Token（per-team API token）的簽發、列表、撤銷 UI SHALL 維持掛載於 `/team-management` 頁面的 team 卡片操作選單（`#appTokenModal`），不隨組織層分頁一併搬遷至 `/organization-management`。

#### Scenario: App token management stays reachable from team card menu
- **WHEN** 使用者從 team 卡片選單開啟「App Tokens」
- **THEN** 系統 SHALL 顯示該 team 的 App Token 管理 modal，行為與既有 `app/api/app_tokens.py` contract 一致
