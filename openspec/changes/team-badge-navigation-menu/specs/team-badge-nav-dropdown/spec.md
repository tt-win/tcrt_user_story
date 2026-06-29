## ADDED Requirements

### Requirement: Config-Driven Page Registry

系統 SHALL 提供 `team-nav-config.js`，以陣列形式定義所有 team-scoped 頁面的導覽清單。每筆記錄 SHALL 包含以下欄位：
- `key`（string）：唯一識別符
- `iconClass`（string）：Font Awesome icon class
- `i18nKey`（string）：i18n 翻譯 key
- `pathTemplate`（string）：路徑樣板，可含 `{team_id}` 佔位符
- `condition`（async function | undefined）：可選的顯示條件，回傳 boolean

此 config 檔 SHALL 為 team 頁面導覽的 single source of truth；新增 team-scoped 頁面時 MUST 在此檔案新增對應記錄。

#### Scenario: 查看初始頁面清單

WHEN 開啟 `team-nav-config.js`
THEN 清單 SHALL 包含以下頁面（按順序）：Test Cases、Test Runs、Automation Hub、User Story Map

#### Scenario: User Story Map 含 team_id 佔位符

WHEN `pathTemplate` 包含 `{team_id}`
THEN 系統 SHALL 在渲染時以當前 team 的 id 替換佔位符

### Requirement: Team Badge Dropdown Trigger

Header 中的 team badge SHALL 升級為可點擊的 Bootstrap 5 dropdown trigger。點擊後 SHALL 展開導覽選單。

#### Scenario: 點擊 badge 展開選單

WHEN 使用者點擊 team badge
THEN SHALL 顯示包含所有 team-scoped 頁面連結的下拉選單

#### Scenario: 無 team 時 badge 不可點擊

WHEN `AppUtils.getCurrentTeam()` 回傳 null
THEN badge SHALL 維持隱藏（`d-none`），不顯示 dropdown

### Requirement: Active Page Indication

下拉選單 SHALL 標示當前所在頁面為 active 狀態。

#### Scenario: 當前頁面標示 active

WHEN 下拉選單展開
THEN 對應當前 `window.location.pathname` 的選單項目 SHALL 以視覺方式標示為 active（例如 Bootstrap `.active` class）

#### Scenario: 非 team-scoped 頁面無 active 標示

WHEN 當前路徑不符合任何 config 中的 pathTemplate
THEN 所有選單項目均 SHALL NOT 顯示 active 狀態

### Requirement: Automation Hub Entry Condition

Automation Hub 頁面連結 SHALL 遵守現有 org-level 入口開關。

#### Scenario: 入口開關關閉時隱藏 Automation Hub

WHEN `AppUtils.getAutomationHubEntryEnabled()` 回傳 false
THEN Automation Hub 選單項目 SHALL 不顯示

#### Scenario: 入口開關開啟時顯示 Automation Hub

WHEN `AppUtils.getAutomationHubEntryEnabled()` 回傳 true（或 API 尚未回應）
THEN Automation Hub 選單項目 SHALL 顯示（預設顯示，fallback true）

### Requirement: Team Change Event Reactivity

Team badge dropdown SHALL 在 team 變更或清除時更新。

#### Scenario: team 變更後選單內容更新

WHEN `teamChanged` 事件觸發
THEN badge 文字與選單連結（含 team_id 相關 URL）SHALL 重新計算並更新

#### Scenario: team 清除後 badge 隱藏

WHEN `teamCleared` 事件觸發
THEN badge SHALL 隱藏（`d-none`），dropdown SHALL 無法展開

### Requirement: i18n Support

所有選單項目文字 SHALL 透過 i18n 系統翻譯，支援 zh-TW、zh-CN、en-US 三語系。

#### Scenario: 切換語系時選單文字更新

WHEN 使用者切換語言
THEN 下拉選單中的頁面名稱 SHALL 顯示對應語系的翻譯文字
