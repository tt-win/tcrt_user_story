## Context

`/organization-management`（由 `redesign-team-settings-information-architecture` change 建立）目前有 5 個分頁：人員管理、組織、Service 管理、MCP Token、組織自動化基礎設施。「AI 助手設定」（`/assistant-admin`，由已封存的 `add-global-ai-assistant` change 建立）目前是該頁工具列上的一顆獨立連結按鈕，指向完全獨立的頁面。使用者要求它應與其餘 5 個分頁同層級。

`/assistant-admin` 頁面本身結構簡單：一個 `#aaMain` 容器，內含自己的 nested tab bar（System Prompt｜Skills 兩個子分頁），JS（`assistant-admin.js`，IIFE、無跨檔案全域依賴）僅以 DOM id 操作，不依賴頁面層級結構。

## Goals / Non-Goals

**Goals：**
- 把「AI 助手設定」的內容（含其內部 System Prompt／Skills 子分頁）搬進 `/organization-management` 成為第 6 個頂層分頁。
- 修正 `assistantAdmin.*` 三語系文案的大小寫不一致。
- 同步更新 `assistant-prompt-skills-admin` 主 spec 內已經落後於實作的「入口位置」描述。

**Non-Goals：**
- 不改變 `/api/admin/assistant/*` 任何 API contract、資料模型或業務邏輯。
- 不改變 System Prompt／Skills 內部的子分頁式互動設計（保留 nested tab bar，不整併成單一畫面）。
- 不新增權限模型；沿用既有 `organization_management:manage`（Super Admin only）。

## Decisions

### D1. 巢狀 tab bar 而非攤平

`tab-assistant-admin` 分頁內容維持原本的 `aaTabPrompt`／`aaTabSkills` 兩個子分頁（Bootstrap tab 巢狀使用），不攤平成單一長頁面或拆成兩個頂層分頁。理由：這兩個子分頁本來就是同一功能（助手設定）下的兩個檢視角度，攤平成頂層分頁會讓組織管理頁面從 5 個分頁暴增到 7 個、稀釋既有分頁的視覺權重；Bootstrap 巢狀 tab 是標準支援的模式，只要子分頁 id（`aaTabPrompt`/`aaTabSkills`/`aaPanePrompt`/`aaPaneSkills`）與頂層分頁 id 不衝突即可，兩者本來就無命名衝突。

### D2. JS 檔案搬到 `organization-management/` 目錄，不與其他分頁共用邏輯

`assistant-admin.js` 是完全自包含的 IIFE（不依賴 `teams` 等既有全域變數，也不被其他檔案引用），搬移風險等同於先前搬移 `org-automation-infra.js`（低風險、可整段搬移）。搬移後仍獨立以 `DOMContentLoaded` 初始化，與 `organization-management/main.js` 的分頁可視性邏輯各自獨立運作，不整併成單一模組。

### D3. 移除 `/assistant-admin` 獨立路由，不保留相容重導向

`/assistant-admin` 頁面上線時間短（隨已封存的 `add-global-ai-assistant` change 新增），且只有一個內部入口（先前那個連結按鈕）會失效，不像 `redesign-team-settings-information-architecture` 那樣需要顧慮大量外部書籤／文件連結。直接移除路由與 template，不做相容重導向或舊錨點提示。

### D4. 大小寫修正範圍：僅改 `assistantAdmin.*` 的顯示文字，不改 key 名稱

只修正 value（顯示文字），不重新命名任何 i18n key，避免影響 JS 內 `t(key, fallback)` 呼叫或觸發不必要的 diff。中文字串改用正式中文用語（如「新增 Skill」「重設為原廠設定」「Skill ID」），英文技術詞彙（System Prompt、Skill、Factory、Token 等）維持 Title Case。

## Risks / Trade-offs

- **[Risk] 巢狀 tab 的 Bootstrap 事件命名空間**——確認 `aaTab*` 系列 id 與組織頁既有 `tab-*` 系列 id 無命名衝突（已核對，無重複）。
- **[Trade-off] 移除 `/assistant-admin` 路由是不可逆的小型 breaking change**——僅影響先前那顆連結按鈕與可能存在的內部書籤；`/api/admin/assistant/*` API 本身不受影響，任何直接呼叫 API 的整合不受影響。

## Migration Plan

單次直接完成（無需分階段）：
1. 將 `assistant_admin.html` 的 `#aaUnauthorized`／`#aaWarning`／`#aaMain` 內容搬進 `organization_management.html` 新的 `#tab-pane-assistant-admin`。
2. 新增分頁按鈕 `tab-assistant-admin`（Super Admin only，`ui_capabilities.yaml` 新鍵 `tab-org-automation-infra` 相同 action pattern，但沿用既有 `organization_management:manage`）。
3. 移動 JS 檔案、更新 `<script src>`。
4. 移除 `/assistant-admin` 路由與舊 template。
5. 修正三語系文案大小寫。
6. 更新 `assistant-prompt-skills-admin`、`organization-management-console` 兩份主 spec。

**Rollback**：無資料層變更；回退整批 commit 即可恢復獨立頁面與連結。
