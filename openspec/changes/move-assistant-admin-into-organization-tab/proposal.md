## Why

「AI 助手設定」目前是 `/organization-management` 頁面工具列上的一顆獨立連結按鈕，點擊後跳到完全獨立的 `/assistant-admin` 頁面。使用者要求它應該跟人員管理、組織同步、Service 管理、MCP Token、組織自動化基礎設施一樣，成為同一層級的分頁（tab），而不是另外開一個頁面。同時，`assistantAdmin.*` 的三語系文案大量沿用小寫技術欄位名稱（如「skill_id」「name」「enabled」「builtin」「新增 skill」「重設 factory」），與其餘頁面一貫使用的正式中文/正確大小寫英文用語不一致，需一併修正。

## What Changes

- 將「AI 助手設定」從 `/organization-management` 的獨立連結按鈕，改為與其餘 5 個分頁同層級的第 6 個分頁（`tab-assistant-admin` / `tab-pane-assistant-admin`），內容（System Prompt／Skills 子分頁）與行為完全承接自原 `/assistant-admin` 頁面，不改變任何 `/api/admin/assistant/*` API contract。
- 移除獨立路由 `/assistant-admin`、`app/templates/assistant_admin.html`；JS 由 `app/static/js/assistant-admin.js` 搬到 `app/static/js/organization-management/assistant-admin.js`（比照人員管理／組織自動化基礎設施等既有分頁的檔案位置慣例）。
- `config/permissions/ui_capabilities.yaml`：`assistantAdminLink` 元件鍵改為 `tab-assistant-admin`，沿用原本的 `organization_management:manage`（僅 Super Admin），不新增權限模型。
- 修正 `app/static/locales/{en-US,zh-CN,zh-TW}.json` 內 `assistantAdmin.*` 區塊的大小寫：技術欄位名稱（skill_id、name、enabled、builtin 等）與動詞片語（新增 skill、重設 factory 等）改為正式中文用語或正確英文大小寫（Title Case），不影響任何 i18n key 名稱，只改顯示文字。
- 修正 `openspec/specs/assistant-prompt-skills-admin/spec.md`「Super Admin UI」requirement 的既有落差：目前文字仍描述「入口置於團隊管理 Super Admin 選單」，實際上該入口已在前一個 change（`redesign-team-settings-information-architecture`）搬到 `/organization-management` 頁面的獨立連結；本次一併更新為「組織與系統設定頁面的分頁」，避免 spec 持續落後於實作。

## Capabilities

### Modified Capabilities
- `assistant-prompt-skills-admin`: 「Super Admin UI」requirement 改為描述分頁而非獨立頁面／獨立連結；入口位置改為 `/organization-management` 頁面的第 6 個分頁。
- `organization-management-console`: 新增第 6 個分頁 `tab-assistant-admin`（AI 助手設定），存取層級與既有 `assistantAdminLink`（現更名 `tab-assistant-admin`）一致（`organization_management:manage`，僅 Super Admin）。

## Impact

- **前端 template**：`app/templates/organization_management.html` 新增第 6 個分頁；刪除 `app/templates/assistant_admin.html`。
- **前端 JS**：新增 `app/static/js/organization-management/assistant-admin.js`（搬移自 `app/static/js/assistant-admin.js`，內容不變，僅檔案位置）；刪除原檔案。
- **i18n**：三語系 `assistantAdmin.*` 文案大小寫修正，不新增/刪除 key。
- **權限設定**：`config/permissions/ui_capabilities.yaml` 的 `assistantAdminLink` 鍵更名為 `tab-assistant-admin`。
- **後端路由**：`app/main.py` 移除 `GET /assistant-admin` route；`/api/admin/assistant/*` API 完全不變。
- **資料庫**：無 schema 變更、無 migration。
- **既有 spec 文件**：`openspec/specs/assistant-prompt-skills-admin/spec.md`、`openspec/specs/organization-management-console/spec.md`。
