# app-chrome-layout Specification Delta

本 delta 建立新能力 `app-chrome-layout`，規範 `base.html` 產生的固定框架（header／footer／main／overlay 層）在所有斷點的可達性、視窗單位與層級契約。

## ADDED Requirements

### Requirement: App chrome controls remain reachable at every viewport width

App chrome（固定 header 與其工具列）所渲染的每一個控制項 SHALL 在任何視窗寬度下保持可達——直接可見，或可透過明確的收合機制（overflow 選單或可水平捲動的工具列）觸及。SHALL 不存在因固定容器裁切而既不可見、也無法捲動抵達的控制項。

#### Scenario: No control is clipped beyond reach

- **WHEN** 在任一支援斷點（含 375px 寬）渲染任一頁面
- **THEN** header 工具列的每個控制項 SHALL 可見，或可經由 overflow 選單／水平捲動抵達
- **AND** SHALL 不存在右緣超出視窗且無捲動路徑的控制項

#### Scenario: Header height stays constant across breakpoints

- **WHEN** 工具列在窄螢幕啟用收合機制
- **THEN** `--header-height` SHALL 維持固定值
- **AND** `.app-main` 的頂部留白 SHALL 不需依斷點另行調整

### Requirement: Sign-out and back navigation have a minimum reachability guarantee

使用者選單（含登出）與返回上一層的入口 SHALL 在所有斷點可見且可操作，SHALL 不被收進 overflow 選單。

#### Scenario: Sign-out reachable on a narrow viewport

- **WHEN** 使用者在 375px 寬的視窗開啟任一頁面
- **THEN** 使用者選單 SHALL 在畫面內
- **AND** 登出動作 SHALL 可直接觸發

#### Scenario: Back entry survives toolbar collapse

- **WHEN** 工具列因寬度不足而收合其他控制項
- **THEN** 返回上一層的入口 SHALL 仍留在工具列上

### Requirement: Viewport-relative heights use dynamic viewport units

需要依視窗高度定尺寸的容器 SHALL 使用動態視窗單位（`dvh`），並 SHALL 提供靜態單位（`vh`）作為不支援瀏覽器的 fallback，以避免行動瀏覽器位址列收合時裁切內容。此需求 SHALL 涵蓋 `height`、`min-height` 與 `max-height`，且 SHALL 涵蓋以 `calc()` 組成的視窗高度運算。

#### Scenario: Dynamic unit overrides static fallback

- **WHEN** 任一規則以視窗高度單位設定 `height`、`min-height` 或 `max-height`（含 `calc()` 形式）
- **THEN** 該規則 SHALL 先宣告 `vh` fallback，再以 `dvh` 覆寫
- **AND** 樣式表 SHALL 不存在僅有 `vh` 而無 `dvh` 覆寫的視窗高度宣告

#### Scenario: Content is not clipped when the mobile address bar collapses

- **WHEN** 行動瀏覽器的位址列在捲動時收合
- **THEN** 固定工作區內的內容 SHALL 不被裁切

### Requirement: Overlay stacking resolves from a single z-index token scale

所有固定與浮動元素（app header／footer、分頁列、語言切換器、dropdown、modal、toast、AI Assistant FAB）的堆疊順序 SHALL 解析自 `:root` 中定義的單一 `--z-*` token scale。`z-index` 宣告 SHALL 不得使用 `!important`，亦 SHALL 不得硬編數值。

#### Scenario: Stacking values come from tokens

- **WHEN** 任一固定或浮動元素需要堆疊順序
- **THEN** 其 `z-index` SHALL 解析自 `--z-*` token
- **AND** SHALL 不出現硬編數值（例如 `9999`、`999999`）

#### Scenario: No importance escalation for stacking

- **WHEN** 樣式表宣告 `z-index`
- **THEN** 該宣告 SHALL 不帶 `!important`

### Requirement: Floating utilities do not obscure interactive controls

畫面上的浮動元素 SHALL 不互相重疊，且 SHALL 不遮蔽任何可互動控制項。浮動元素 MAY 覆蓋靜態內容——`assistant-widget-ui` 已規範 AI Assistant FAB 為全頁右下角懸浮入口，`system-administration-dashboard` 亦明訂該 FAB「仍可 overlay 且不預留空白」，本需求 SHALL 不與之衝突。

視窗級的固定層 SHALL 不依賴 `pointer-events: none` 來避免攔截點擊；需要此類補償即表示該元素不應為視窗級固定層。

#### Scenario: Floating utilities keep clear of each other

- **WHEN** 語言切換器與 AI Assistant 入口同時呈現
- **THEN** 兩者 SHALL 不互相重疊

#### Scenario: Overlay does not cover interactive controls

- **WHEN** 浮動元素覆蓋於頁面內容之上
- **THEN** 該元素 SHALL 不遮蔽按鈕、連結、表單控制或表格列操作等可互動元素
- **AND** MAY 覆蓋靜態文字或圖形內容

#### Scenario: No pointer-events compensation for fixed layers

- **WHEN** 樣式表宣告視窗級固定層
- **THEN** 該層 SHALL 不以 `pointer-events: none` 作為避免攔截點擊的補償

### Requirement: Dead chrome styles are removed rather than carried forward

App chrome 相關樣式若無任何模板或腳本套用，SHALL 移除而非保留或改寫。

#### Scenario: Unused chrome rules are deleted

- **WHEN** 樣式表存在 app chrome 相關的 class 規則
- **THEN** 該 class SHALL 至少有一處模板或腳本套用
- **AND** 無套用者 SHALL 自樣式表移除

### Requirement: Page subtitle degrades gracefully on narrow viewports

Page title 區塊的副標 SHALL 在寬度不足時整體隱藏，SHALL 不被壓縮為逐字換行的直排文字。

#### Scenario: Subtitle hidden rather than squeezed

- **WHEN** 視窗寬度不足以容納標題與工具列
- **THEN** 副標 SHALL 被隱藏
- **AND** 標題 SHALL 保持單行水平呈現
