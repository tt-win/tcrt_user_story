# ui-design-system Specification

## Purpose
Unify button visual styles across all pages and components to provide consistent user experience with standardized color tokens, states, and interactions.
## Requirements
### Requirement: Global Button Visual System
The system SHALL define a single, shared button visual system that applies to all pages and all button elements, including Bootstrap `.btn` classes and any custom button classes.

#### Scenario: Consistent button base styles
- **WHEN** a button is rendered anywhere in the UI
- **THEN** the button SHALL inherit the shared base styles for typography, spacing, border radius, and elevation

#### Scenario: Consistent button color tokens
- **WHEN** a button uses semantic intent (primary, secondary, success, warning, danger, info)
- **THEN** the button SHALL map to the same color tokens across all pages

### Requirement: Button State Consistency
The system SHALL provide consistent hover, active, disabled, outline, and loading states for all buttons based on the shared button visual system.

#### Scenario: Hover and active states
- **WHEN** a user hovers over or activates a button
- **THEN** the visual feedback SHALL follow the unified hover/active rules

#### Scenario: Disabled state
- **WHEN** a button is disabled
- **THEN** the button SHALL display the unified disabled styling and block interaction cues

#### Scenario: Outline and loading states
- **WHEN** a button uses outline or loading presentation
- **THEN** the button SHALL follow the unified outline and loading rules

### Requirement: Single source-of-truth design tokens

系統 SHALL 在單一位置（`style.css` 的 `:root`）定義全站唯一一層 design token，涵蓋顏色、間距（spacing scale）、圓角（radius）與陰影／層級（elevation）。所有頁面與元件 SHALL 透過 token 取得這些視覺值，而非各自定義或硬編。既有的多前綴 token（`--tr-`／`--btn-`／`--qa-`／`--tc-`／`--ai-`）SHALL 收斂為單一命名規格；遷移期舊前綴 SHALL 以別名（alias）指向 canonical token，以維持非破壞性相容。

#### Scenario: Tokens defined in one place

- **WHEN** 任一頁面或元件需要顏色、間距、圓角或陰影值
- **THEN** 該值 SHALL 解析自 `:root` 中定義的單一 canonical token
- **AND** 不同頁面對同一語意（如主色、標準間距）SHALL 解析到相同的 token 值

#### Scenario: Legacy prefixes resolve to canonical tokens

- **WHEN** 既有樣式仍引用舊前綴 token（例如 `--tr-primary`、`--btn-*`）
- **THEN** 該舊前綴 SHALL 透過 alias 解析到對應的 canonical token
- **AND** 其呈現結果 SHALL 與直接使用 canonical token 一致

#### Scenario: No token-less stylesheet

- **WHEN** 任一 CSS 檔需要視覺值（含先前完全未使用 token 的 `team-statistics.css`、`test-case-reference.css`、`test-case-set-list.css`）
- **THEN** 該檔 SHALL 以 `var(--…)` 引用 canonical token 取得視覺值

### Requirement: Single canonical primary color aligned with framework

系統 SHALL 定義單一 canonical 主色 token（`--color-primary`），且該主色 SHALL 與所採用框架的主色變數（Bootstrap `--bs-primary`）一致。系統 SHALL 不存在多個互相衝突的「主色」來源。

#### Scenario: Primary maps to framework primary

- **WHEN** 任一元件使用主色語意（primary）
- **THEN** 其顏色 SHALL 解析自 `--color-primary`
- **AND** `--color-primary` 的值 SHALL 與 Bootstrap `--bs-primary` 相同

#### Scenario: No competing primary blues

- **WHEN** 渲染任何使用主色的 UI（按鈕、連結、強調元素）
- **THEN** 全站 SHALL 僅呈現單一主色值
- **AND** 先前彼此衝突的主色（`#4a90e2`、`#0d6efd`、`#2463eb`）SHALL 不再以硬編形式出現於 `:root` 以外

### Requirement: Reusable component library for modal, table, and toolbar

系統 SHALL 提供可複用的伺服器端元件（Jinja macro）以呈現 modal、資料表格（data table）與工具列（toolbar），供各頁面共用。各頁面 SHALL 透過這些元件產生對應 UI，而非各自手刻重複的 markup 與樣式。

#### Scenario: Modal rendered via shared component

- **WHEN** 任一頁面需要顯示 modal
- **THEN** 該 modal SHALL 由共用 modal 元件產生
- **AND** 其結構與視覺 SHALL 在所有頁面一致（取代先前 9 個各自獨立的 `.modal` 樣式來源）

#### Scenario: Data table rendered via shared component

- **WHEN** 任一頁面需要呈現資料表格
- **THEN** 該表格 SHALL 由共用 data table 元件產生並套用一致的表格樣式

#### Scenario: Toolbar rendered via shared component

- **WHEN** 任一頁面需要呈現操作工具列
- **THEN** 該工具列 SHALL 由共用 toolbar 元件產生並套用一致的排版

### Requirement: Raw hex and inline styles prohibited and enforced by lint

系統 SHALL 禁止在 `:root` 以外的 CSS 選擇器使用原始 hex 顏色，並 SHALL 禁止在 Jinja 模板中使用 inline `style=` 屬性。此禁止 SHALL 由 lint 工具（stylelint，經由 `npx` 或 pre-commit 執行）強制檢查，且 SHALL 不依賴 Node build pipeline。

#### Scenario: Raw hex outside :root is flagged

- **WHEN** 在 `:root` 以外的選擇器中加入原始 hex 顏色
- **THEN** lint SHALL 回報違規
- **AND** 該違規 SHALL 被阻擋或記入 baseline 待收斂

#### Scenario: Inline style in template is flagged

- **WHEN** 在 Jinja 模板中加入 inline `style=` 屬性
- **THEN** lint SHALL 回報違規

#### Scenario: Lint runs without a build pipeline

- **WHEN** 開發者或 CI 執行樣式護欄檢查
- **THEN** 檢查 SHALL 可透過 `npx`／pre-commit 執行
- **AND** 執行過程 SHALL 不需要建立 Node build pipeline、亦不產出建置產物

### Requirement: CDN dependency pinning and single sourcing

系統 SHALL 將前端 CDN 依賴鎖定於明確版本，並由單一來源提供（統一 origin 或 vendor 至 `static/vendor/`），以消除版本漂移風險。

#### Scenario: Dependencies are version-pinned

- **WHEN** 載入任一前端第三方依賴（如 Bootstrap、Chart.js、Handsontable、Monaco、ReactFlow、marked、highlight.js、DOMPurify）
- **THEN** 其版本 SHALL 為明確鎖定的版本
- **AND** SHALL 不使用會自動跟進更新的浮動版本

#### Scenario: Dependencies share a single source

- **WHEN** 解析多個第三方依賴的載入來源
- **THEN** 這些依賴 SHALL 來自單一來源（同一 CDN origin 或本地 `static/vendor/`）
- **AND** SHALL 不混用多個 CDN origin（jsdelivr／unpkg／cdnjs）

