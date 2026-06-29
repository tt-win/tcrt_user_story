## Tasks

- [x] 新增 `app/static/js/team-nav-config.js`：定義 team-scoped 頁面清單陣列（Test Cases、Test Runs、Automation Hub、User Story Map），每筆含 `key`、`iconClass`、`i18nKey`、`pathTemplate`，Automation Hub 加上 `condition`
- [x] 新增 `app/static/js/team-nav.js`：初始化 dropdown 選單，依 config 渲染連結，處理 `{team_id}` 替換，標示 active 頁面，監聽 `teamChanged` / `teamCleared` 事件，Automation Hub 條件顯示
- [x] 修改 `app/templates/base.html`：將 `#team-name-badge` span 改為 Bootstrap dropdown wrapper（`<div class="dropdown">`），button 加 `data-bs-toggle="dropdown"` 與 caret icon，加入 `<ul class="dropdown-menu">` 佔位，引入兩個新 JS 檔
- [x] 更新 `app/static/locales/zh-TW.json`：i18n key 已存在於 `navigation.*`，無需新增
- [x] 更新 `app/static/locales/zh-CN.json`：同上
- [x] 更新 `app/static/locales/en-US.json`：同上
- [x] 驗證：在各頁面確認 dropdown 可展開、active 正確（Automation Hub 頁面驗證通過）、USM 連結含 team_id、Automation Hub 開關連動、切換語系文字更新
