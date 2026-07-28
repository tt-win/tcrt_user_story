# ui-design-system Specification Delta

本 delta 擴充既有 `ui-design-system`，新增「頁面層級元件規格強制」相關需求。既有需求（按鈕視覺系統、token 單一來源、macro 元件庫、hex／inline style 護欄、CDN 鎖定）不改動，本 delta 補上讓這些規範在 18 個頁面上**機械可驗證**且**全站一致**的需求。

## ADDED Requirements

### Requirement: Component specification enforcement across all pages

系統 SHALL 以自動化測試（`app/testsuite/test_component_spec.py`）對全部頁面路由的 rendered HTML 進行機械檢查，使 SPEC-BTN-001／SPEC-BDG-001／SPEC-TBL-001／SPEC-MDL-001／SPEC-CRD-001／SPEC-TLB-001／SPEC-TAB-001／SPEC-DRP-001／SPEC-HOM-001／SPEC-NAV-001 從文件規範變成會 fail 的測試。無法以路由渲染驗證的頁面 SHALL 以模板原始碼掃描作為 fallback 並在測試中標註原因。

#### Scenario: Forbidden button classes are detected
- **WHEN** 任一頁面渲染出含 `btn-xs`、`btn-view`、`btn-edit` 或 `test-run-kebab-btn` 類別的按鈕
- **THEN** `test_component_spec.py` SHALL fail 並指出違規頁面與元素

#### Scenario: Forbidden badge patterns are detected
- **WHEN** 任一頁面渲染出 `text-bg-*` 類別、無 `bg-*` 的裸 `badge`、`badge-role`、或 `bg-*-subtle text-*-emphasis` 多類別組合
- **THEN** 測試 SHALL fail

#### Scenario: Tables conform to canonical class set
- **WHEN** 任一頁面渲染出 `<table class="table">`
- **THEN** 該 table SHALL 同時含 `table-sm`、`table-hover`、`align-middle`
- **AND** 其 `<thead>` SHALL 不含 `table-light`

#### Scenario: Modals conform to structural rules
- **WHEN** 任一頁面渲染出 `.modal-dialog`
- **THEN** 該 dialog SHALL 不含 inline `style=` 屬性
- **AND** `.modal-header` SHALL 不含 `bg-light` 或 `bg-danger`
- **AND** modal-header 內 SHALL 僅有 `<h5 class="modal-title">` 與 `<button class="btn-close">`

#### Scenario: Tabs conform to nav-tabs with icons
- **WHEN** 任一頁面渲染出 tab 導覽
- **THEN** 該導覽 SHALL 使用 `nav nav-tabs`（非 `nav-pills`）+ `mb-3`
- **AND** 每個 `nav-link` 按鈕 SHALL 含 `<i>` 圖示

#### Scenario: Home button is uniform across all pages
- **WHEN** 任一頁面渲染出指向 `/` 的 home 按鈕
- **THEN** 該按鈕的文案 SHALL 為 `回到首頁`
- **AND** 其 class 順序 SHALL 為 `btn btn-secondary btn-sm`
- **AND** 圖示 `<i class="fas fa-home me-1"></i>` 與文案 SHALL 在同一行

### Requirement: Button class ordering and semantic mapping

所有頁面的按鈕 SHALL 遵循 `btn btn-{variant} btn-sm` 類別順序（variant 在 size 之前），並依語意對應 variant（`btn-primary`=建立/儲存、`btn-secondary`=取消/返回、`btn-success`=確認/套用、`btn-danger`=刪除、`btn-info`=僅輔助/資訊、`btn-warning`=警示動作）。dropdown 觸發按鈕 SHALL 一律使用 `btn-secondary`。

#### Scenario: Variant precedes size
- **WHEN** 任一按鈕同時含 variant 與 size 類別
- **THEN** `btn-{variant}` SHALL 出現在 `btn-sm` 之前

#### Scenario: Dropdown triggers use secondary
- **WHEN** 工具列渲染 dropdown 觸發按鈕
- **THEN** 該按鈕 SHALL 使用 `btn btn-secondary btn-sm dropdown-toggle`
- **AND** SHALL 不使用 `btn-info`

### Requirement: Inline styles prohibited in templates and modals

Jinja 模板 SHALL 不含任何 inline `style=` 屬性，此禁止 SHALL 由 `scripts/check-inline-styles.mjs` 護欄強制檢查。modal 尺寸 SHALL 透過具名 CSS class（如 `modal-tc-editor`、`modal-xl`、`modal-dialog-scrollable`）表達，而非 inline `style=`。

#### Scenario: Template inline style is blocked
- **WHEN** 開發者在 Jinja 模板加入 inline `style=` 屬性
- **THEN** `npm run lint:templates` SHALL 報告違規

#### Scenario: Modal size expressed via class
- **WHEN** modal 需要非預設尺寸
- **THEN** 該尺寸 SHALL 由具名 CSS class 表達
- **AND** `.modal-dialog` SHALL 不含 inline `style=`

### Requirement: Card header canonical classes

所有 `.card-header` SHALL 含完整 canonical 類別集合：`bg-light d-flex align-items-center justify-content-between flex-wrap gap-2`。card-header 標題 SHALL 使用 `<h6 class="mb-0">`（不外加 `fw-bold`）。card-body padding 預設為 `0.75rem`；唯有 card 包含需貼邊的 table/chart 時得以 `p-0` 覆寫，並 SHALL 旁附註釋說明原因。

#### Scenario: Card header has full canonical set
- **WHEN** 任一頁面渲染 `.card-header`
- **THEN** 其 class SHALL 同時含 `bg-light`、`d-flex`、`align-items-center`、`justify-content-between`

### Requirement: Navigation consolidation via header Admin dropdown

系統 SHALL 在 `base.html` header 提供單一「管理」dropdown，整合組織（團隊管理、組織設定）與系統（稽核日誌、系統日誌、統計分析）入口，其可見性 SHALL 由既有 Casbin RBAC 的 Jinja 條件控制。`team_management.html` SHALL 不再含獨立的 `btn-info` data menu dropdown。automation 子頁面 SHALL 以 breadcrumb 取代「Back to Hub」按鈕。

#### Scenario: Admin dropdown present in base layout
- **WHEN** 已認證使用者檢視任一頁面
- **THEN** header SHALL 渲染「管理」dropdown（受 RBAC 控制可見性）

#### Scenario: Team management has no data menu
- **WHEN** 渲染 `team_management.html`
- **THEN** 該頁 SHALL 不含 `btn-info.dropdown-toggle` data menu

### Requirement: AI surface visual consistency

QA AI Helper、inline AI Assist modal 與 global assistant widget SHALL 共用同一組 AI 表面 CSS 類別（如 `.ai-bubble-user`、`.ai-bubble-assistant`、`.ai-tool-activity`、`.ai-confirm-card`），以呈現一致的氣泡、工具活動、確認卡與 composer 樣式。

#### Scenario: Shared AI bubble classes across surfaces
- **WHEN** 任一 AI 表面（QA AI Helper、inline AI Assist、global assistant）渲染使用者或助理訊息
- **THEN** 該訊息 SHALL 使用共用 `.ai-bubble-user` 或 `.ai-bubble-assistant` 類別

### Requirement: Internationalization keys live only in locale JSON

使用者可見字串 SHALL 只定義於 `app/static/locales/{en-US,zh-CN,zh-TW}.json`。系統 SHALL 不在 DOM 中以 `d-none` div 隱藏 i18n 字串。JS 取用字串 SHALL 透過既有 i18n lifecycle（`data-i18n`／`data-i18n-placeholder`／`data-i18n-title`／`data-i18n-params`／`window.i18n.t()`／`window.i18n.retranslate(...)`）。任一 locale 新增使用者可見文案時，三個語系檔 SHALL 同步更新。

#### Scenario: No hidden i18n divs
- **WHEN** 渲染任一頁面
- **THEN** DOM 中 SHALL 不存在含 `data-i18n` 屬性的 `d-none` 元素

#### Scenario: Three locales kept in sync
- **WHEN** 任一語系檔新增 key
- **THEN** 另兩個語系檔 SHALL 含相同 key
- **AND** `node scripts/check-i18n-coverage.mjs` SHALL 通過
