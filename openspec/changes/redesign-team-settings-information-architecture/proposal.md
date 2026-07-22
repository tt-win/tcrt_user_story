## Why

`/team-management` 頁面（`app/templates/team_management.html`，1034 行）目前同時承載 7 種不同層級的關注點：team 資料 CRUD（含 Lark Bitable 連結）、跨團隊人員管理、組織同步、排程服務管理、MCP Machine Token 簽發、組織層自動化基礎設施（CI/Result provider + Automation Hub 入口開關）、以及 per-team App Token 簽發。其中 5 項是透過單一「組織與系統設定」modal 的 5 個分頁塞入，導致「team 自己的資料/設定」與「org-wide、通常僅 Super Admin 可管理的系統設定」在同一個頁面、同一個入口下混雜，使用者難以判斷某個功能屬於哪個層級，維護者也難以判斷新功能該加在哪裡。

後端權限系統其實已經用不同的 `feature` 名稱區分這些關注點（`team_management` / `user_management` / `organization_management`，見 `config/permissions/ui_capabilities.yaml`），且 `page=organization` 這個 permission page key 早已存在（`pages.organization.components` 已定義 `tab-personnel-li`、`tab-org`、`tab-service-management`、`tab-mcp-token` 等元件），只是前端從未把它渲染成獨立頁面，全部借用 team_management 的 DOM 掛載。`app/api/organization_sync.py` 一個檔案同時背負組織同步、排程服務、MCP Token 三個不相關 API，是後端層也有相同混雜問題的證據。repo 內已有可依循的前例：`system_logs.html`、`assistant_admin.html` 都是從 `team_management.html` 拆出去的獨立頁面（只留連結按鈕），`automation_provider_settings.html` 則是 per-team 的 Git 來源設定頁（從 Automation Hub 情境進入，不掛在 team management）。本變更要把剩餘幾個仍塞在 modal 分頁裡的組織層功能，套用同一套已驗證的拆分模式，並讓前端頁面結構與既有 permission page key 對齊。

## What Changes

- 新增獨立的「組織與系統設定」頁面與導覽 shell（路由/權限技術對應沿用既有但從未真正落地的 `organization` permission page key；**頁面顯示文字沿用使用者已熟悉的既有字樣「組織與系統設定」，不採用「組織管理」——紅隊審查發現「組織管理」會與既有「組織同步」功能混淆，詳見 design.md D1**），收納目前擠在 team_management「組織與系統設定」modal 內、屬於 org-wide／通常 Super Admin 專用的 5 個分頁：人員管理、組織同步、Service 管理（排程服務）、MCP Token 簽發、組織自動化基礎設施（含 Automation Hub 入口開關）。
- `/team-management` 頁面範圍縮小為純粹的 team 資料 CRUD：team 清單、新增/編輯/刪除 team、Lark Bitable 連結欄位、team 卡片操作選單（進入團隊各功能頁 + App Token 入口）；移除「組織與系統設定」modal 整體，改為一顆導向新「組織與系統設定」頁面的連結（僅具備 `organization_management` 權限者可見，沿用既有 feature gating，不新增權限模型）。
- **BREAKING（僅內部 UI 路由，非 API contract）**：原本掛在 `/team-management` 頁面 DOM 上的分頁錨點（`#tab-pane-personnel`、`#tab-pane-org`、`#tab-pane-service-management`、`#tab-pane-mcp-token`、`#tab-pane-org-automation-infra`）與對應 JS 掛載點全數失效，任何書籤／文件中引用這些錨點的地方需要更新為新頁面路徑。後端 API 路徑與 contract 不變（僅新增/搬移前端呼叫來源，不改 request/response 格式）。
- 修改 `automation-hub-provider-framework` 規格：「Org-level provider UI MUST live in team management's org-sync modal」改為指向新的「組織與系統設定」頁面（tab id／錨點依 design.md 決議）。
- 修改 `scheduled-service-management` 規格：Purpose 與「Super Admin can manage scheduled services in organization modal」改為指向「組織與系統設定」頁面，不再描述「team 管理 modal」。
- App Token（per-team API token 簽發）暫定維持在 `/team-management`（隨 team CRUD 一起，因其本質是 per-team 憑證）；是否應改放「組織與系統設定」頁或 Automation Hub 情境內，列為 design.md 待決策項，不在本 proposal 中先行拍板。
- 本 change 的產出範圍是**資訊架構規劃與對應 spec 契約**（proposal + design + delta specs + 任務分解），不含一次性完成全部 7 個功能區塊搬遷的實作；design.md 需明確標出本 change 直接落地的部分，以及需要拆成後續 change 執行的部分。

## Capabilities

### New Capabilities
- `organization-management-console`: 新的獨立「組織與系統設定」頁面與導覽 shell，統整人員管理、組織同步、Service 管理、MCP Token 簽發、組織自動化基礎設施五個分頁的容器、URL/錨點規則、與存取層級（Admin+ / Super Admin），對應既有 `organization` permission page key。
- `team-management-console`: 縮小後的 `/team-management` 頁面正式契約——僅保留 team 資料 CRUD（含 Lark Bitable 連結）、per-team App Token 入口、導向「組織與系統設定」頁面的連結；正式排除人員管理/組織同步/Service 管理/MCP Token/組織自動化基礎設施等 org-wide 內容。

### Modified Capabilities
- `automation-hub-provider-framework`: 「Org-level provider UI MUST live in team management's org-sync modal」requirement 改為指向新「組織與系統設定」頁面內的對應區塊；Storage provider 引導文案（指向 `/automation-provider-settings`）與 audit log scope 行為不變。
- `scheduled-service-management`: Purpose 敘述與「Super Admin can manage scheduled services in organization modal」requirement 改為描述「組織與系統設定」頁面而非 team management modal；後端 registry／權限行為不變。

## Impact

- **前端 template**：`app/templates/team_management.html`（大幅縮減）；新增「組織與系統設定」頁面 template（名稱待 design.md 決議，例如 `organization_management.html`）。
- **前端 JS**：`app/static/js/team-management/main.js` 拆分（目前身兼 team CRUD + 組織同步 + 排程服務 + MCP Token 四種職責）；`personnel_management.js`、`org-automation-infra.js` 改掛到新頁面；`app-tokens.js` 視 App Token 決策留在原處或搬移。
- **i18n**：`app/static/locales/{en-US,zh-CN,zh-TW}.json` 新增「組織與系統設定」頁面相關 key，既有 `orgSync.*`、`personnel.*`、`scheduledServices.*`、`mcpToken.*`、`orgAutomationInfra.*` key 視情況搬移／新增頁面層級 key（不刪除既有語意）。
- **權限設定**：`config/permissions/ui_capabilities.yaml` 沿用既有 `pages.organization` 區塊（補上目前只靠 JS role fallback、未落在 yaml 的 `tab-org-automation-infra`），`pages.team_management` 移除已不再存在的 org-wide 元件 key；沿用既有 `organization_management` / `user_management` feature，不新增權限模型；清理與本次無關的既存 drift（如孤兒的 `home.org-entry`、`organization.tab-test-cases`）留待 design.md 判斷是否一併處理或另開 change。
- **後端路由**：`app/main.py` 新增「組織與系統設定」頁面的 `GET` route；`app/api/permissions.py` 的 `page` 參數沿用既有 `organization` 合法值（無需新增）。API 業務邏輯（`app/api/organization_sync.py`、`system_automation_providers.py`、`system_automation_hub.py`、`users.py` 等）不變，僅前端呼叫來源改變。
- **資料庫**：無 schema 變更、無 migration。
- **既有 spec 文件**：`openspec/specs/automation-hub-provider-framework/spec.md`、`openspec/specs/scheduled-service-management/spec.md`。
- **對外文件**：若 `docs/`、`manual/` 有引用 team_management 分頁位置的截圖或路徑說明，需同步更新（於 design.md 盤點）。
