## 1. 權限設定

- [x] 1.1 `config/permissions/ui_capabilities.yaml`：將 `pages.organization.components.assistantAdminLink` 更名為 `tab-assistant-admin`（feature/action 不變：`organization_management:manage`）

## 2. 頁面搬遷

- [x] 2.1 在 `app/templates/organization_management.html` 新增第 6 個分頁按鈕 `tab-assistant-admin` 與分頁內容 `tab-pane-assistant-admin`（含原 `assistant_admin.html` 的 `#aaUnauthorized`／`#aaWarning`／`#aaMain`，含其內部 System Prompt／Skills 巢狀子分頁），並移除原本的獨立連結按鈕
- [x] 2.2 新增 `app/static/js/organization-management/assistant-admin.js`（搬移自 `app/static/js/assistant-admin.js`，內容不變）；`organization_management.html` 新增對應 `<script src>`
- [x] 2.3 `organization-management/main.js` 的 `applyOrganizationUiVisibility`／`applyOrganizationUiVisibilityByRoleFallback` 新增 `tab-assistant-admin` 的可視性切換（比照 `tab-org`/`tab-service-management`/`tab-mcp-token` 的 fail-closed 模式，直接沿用 `toggleSyncTabVisibility`，移除原本專為連結按鈕寫的 `toggleAssistantAdminLinkVisibility`）
- [x] 2.4 移除 `app/main.py` 的 `GET /assistant-admin` route、`app/templates/assistant_admin.html`、`app/static/js/assistant-admin.js`

## 3. 文案大小寫修正

- [x] 3.1 修正 `app/static/locales/{en-US,zh-CN,zh-TW}.json` 內 `assistantAdmin.*` 的顯示文字大小寫：`newSkill`、`seedMissing`、`editSkill`、`resetFactory`、`restoreBuiltins`、`col.skillId`／`col.name`／`col.enabled`／`col.builtin`、`triggersLabel`、`bodyLabel`、`promptLabel`、`pageSubtitle`、`warning`、`confirmOverwrite`。**補充**：`menuEntry` key 因原本的連結按鈕已隨任務 2.1 移除而變成孤兒 key，改為新增 `tabTitle`（比照其餘 5 個分頁皆有 `tabTitle` 慣例）取代，三語系皆同步處理（非單純大小寫修正，是本次搬遷必然產生的 key 異動）

## 4. Spec 同步

- [x] 4.1 同步 `openspec/specs/organization-management-console/spec.md` 的 delta（五分頁 → 六分頁），並更新 Purpose 段落
- [x] 4.2 同步 `openspec/specs/assistant-prompt-skills-admin/spec.md` 的 delta（Super Admin UI requirement 改為描述分頁而非獨立頁面）

## 5. 驗證

- [x] 5.1 `node --check` 驗證新增/搬移的 JS 檔案語法（`organization-management/assistant-admin.js`、`organization-management/main.js`）
- [x] 5.2 `node scripts/check-i18n-coverage.mjs` 通過
- [x] 5.3 `npm run lint` 通過（新增一個 `style="display: none;"` inline style，比照 `tab-org-automation-infra` 既有的 fail-closed 隱藏模式，已用 `npm run baseline` 將 baseline 從 258 更新為 259，非未審查的回退）
- [x] 5.4 一次性 SQLite 環境即時驗證：`/organization-management` 含新分頁（`tab-assistant-admin`／`tab-pane-assistant-admin`／`aaSkillsBody` 各恰好 1 個）、`/assistant-admin` 舊路由已移除（404）、舊 JS 路徑 404、新 JS 路徑 200；super_admin 角色 ui-config 回傳 `tab-assistant-admin: true`，admin 角色回傳 `false`；admin 直接呼叫 `/api/admin/assistant/system-prompt` 仍 403（後端授權不受影響），super_admin 呼叫成功回傳真實內容
- [x] 5.5 `openspec validate move-assistant-admin-into-organization-tab --strict` 通過（連同 `organization-management-console`、`assistant-prompt-skills-admin` 兩份主 spec 一併驗證）
- [x] 5.6 `app/testsuite/test_permission_ui_config.py` 新增 `tab-assistant-admin` 案例（比照 `tab-org-automation-infra`），4 個測試全數通過；另跑 `test_assistant_content_store_admin.py`／`test_assistant_skills.py`（20 個測試）確認後端 API 完全不受頁面搬遷影響
