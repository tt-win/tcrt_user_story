## Why

使用者在不同 TCRT 頁面間切換時，必須手動回到首頁或記住各頁 URL，缺乏在同一 team 內快速跨頁導覽的機制。現有 header 中已有 team badge 顯示當前 team，將其升級為可互動的導覽入口點可以顯著改善工作流程，且無需改動整體版面配置。

## What Changes

- Header 的 `team-name-badge` 從純展示的 `<span>` 改為可點擊的 Bootstrap dropdown trigger
- 新增 `team-nav-config.js`，以 data-driven 方式定義所有 team-scoped 頁面清單（single source of truth）
- 新增 `team-nav.js`，根據 config 動態產生 dropdown 選單，並標示當前頁面為 active
- User Story Map 路徑含 `{team_id}`，由 `AppUtils.getCurrentTeam().id` 動態填入
- Automation Hub 入口遵守現有 org-level 開關（`getAutomationHubEntryEnabled()`）
- 所有選單文字接入現有 i18n 系統

## Capabilities

### New Capabilities

- `team-badge-nav-dropdown`: Header team badge 升級為下拉導覽選單，顯示當前 team 所有主要頁面，支援 active 標示與條件顯示

### Modified Capabilities

- `ui-design-system`: Header 區域新增互動式 dropdown 元件，遵循現有 Bootstrap 5 design token 與 i18n 規範

## Impact

- `app/templates/base.html`：team badge span 改為 dropdown button wrapper
- `app/static/js/team-nav-config.js`：新增 config 檔（守門點）
- `app/static/js/team-nav.js`：新增 dropdown 初始化與渲染邏輯
- `app/static/locales/en-US.json`、`zh-CN.json`、`zh-TW.json`：新增導覽選單的 i18n key
- 無 API 變更、無資料庫異動、無 migration
