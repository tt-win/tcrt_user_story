## MODIFIED Requirements

### Requirement: Team management page scope is limited to per-team data

`/team-management` 頁面 SHALL 僅包含以下功能：team 清單、新增/編輯/刪除 team（欄位限於 team 名稱、描述、JIRA 設定與預設優先級）、team 卡片操作選單（進入團隊各功能頁、App Token 入口）。頁面 SHALL NOT 包含 Lark Bitable 連結欄位（`wiki_token`、`test_case_table_id`）或 Lark 連線驗證入口，亦 SHALL NOT 包含人員管理、組織同步、Service 管理、MCP Token 簽發、組織自動化基礎設施等 org-wide 功能（相關契約見 `organization-management-console`）。

#### Scenario: Team CRUD remains available
- **WHEN** 具備權限的使用者在 `/team-management` 建立、編輯或刪除一個 team
- **THEN** 行為與既有 `app/api/teams.py` contract 一致，除 Lark 欄位已移除外不受其他頁面重組影響

#### Scenario: Organization-wide tabs are no longer present on this page
- **WHEN** 任何角色的使用者開啟 `/team-management`
- **THEN** 頁面 DOM SHALL NOT 包含 `#tab-pane-personnel`、`#tab-pane-org`、`#tab-pane-service-management`、`#tab-pane-mcp-token`、`#tab-pane-org-automation-infra` 或其容器 modal（原「組織與系統設定」modal）

#### Scenario: Lark Bitable fields are absent from the team form
- **WHEN** 使用者開啟新增或編輯 team 的表單
- **THEN** 表單 SHALL NOT 包含 Wiki Token 欄位、Test Case Table ID 欄位或「驗證 Lark 連線」按鈕
- **AND** 送出時 SHALL NOT 於 request body 帶入 `lark_config`

#### Scenario: Creating a team requires no Lark configuration
- **WHEN** 具備 ADMIN 以上權限的使用者僅提供 team 名稱（可選描述、JIRA 設定、預設優先級）呼叫 `POST /api/teams`
- **THEN** 系統 SHALL 成功建立 team（201）
- **AND** 回應 SHALL NOT 包含 `lark_config` 欄位

#### Scenario: Existing Lark values are preserved and never surfaced
- **WHEN** 系統中存在 change 落地前建立、`teams.wiki_token` 與 `teams.test_case_table_id` 帶有歷史值的 team
- **THEN** `GET /api/teams` SHALL 正常列出該 team 且不回傳其 `wiki_token` 或 `test_case_table_id`
- **AND** 對該 team 執行 `PUT /api/teams/{id}` 更新其他欄位時，資料庫中既有的 Lark 欄位值 SHALL 保持不變

#### Scenario: Lark validation endpoints are removed
- **WHEN** 任何 client 呼叫 `POST /api/teams/validate` 或 `POST /api/teams/validate-table`
- **THEN** 系統 SHALL NOT 提供該端點，並以 4xx 客戶端錯誤回應（實際為 405 Method Not Allowed：該路徑被同層的 `/{team_id}` 路由涵蓋，而該路徑不接受 POST）
