# ui-design-system Specification Delta

本 delta 修改既有 `ui-design-system` 的 design token 需求。原條款以「陰影／層級（elevation）」帶過堆疊順序，語意含糊，實際上全站沒有任何 z-index token，層級改由硬編數值與 `!important` 競賽決定（實測出現 `999999`、`999998`、`9999` 等值）。本 delta 以明確的 z-index scale 取代該表述。

## MODIFIED Requirements

### Requirement: Single source-of-truth design tokens

系統 SHALL 在單一位置（`style.css` 的 `:root`）定義全站唯一一層 design token，涵蓋顏色、間距（spacing scale）、圓角（radius）、陰影（shadow）與堆疊層級（z-index scale）。所有頁面與元件 SHALL 透過 token 取得這些視覺值，而非各自定義或硬編。既有的多前綴 token（`--tr-`／`--btn-`／`--qa-`／`--tc-`／`--ai-`）SHALL 收斂為單一命名規格；遷移期舊前綴 SHALL 以別名（alias）指向 canonical token，以維持非破壞性相容。

#### Scenario: Tokens defined in one place

- **WHEN** 任一頁面或元件需要顏色、間距、圓角、陰影或堆疊層級值
- **THEN** 該值 SHALL 解析自 `:root` 中定義的單一 canonical token
- **AND** 不同頁面對同一語意（如主色、標準間距、固定框架層級）SHALL 解析到相同的 token 值

#### Scenario: Legacy prefixes resolve to canonical tokens

- **WHEN** 既有樣式仍引用舊前綴 token（例如 `--tr-primary`、`--btn-*`）
- **THEN** 該舊前綴 SHALL 透過 alias 解析到對應的 canonical token
- **AND** 其呈現結果 SHALL 與直接使用 canonical token 一致

#### Scenario: No token-less stylesheet

- **WHEN** 任一 CSS 檔需要視覺值（含先前完全未使用 token 的 `team-statistics.css`、`test-case-reference.css`、`test-case-set-list.css`）
- **THEN** 該檔 SHALL 以 `var(--…)` 引用 canonical token 取得視覺值

#### Scenario: Stacking order is tokenized

- **WHEN** 任一元件需要 `z-index`
- **THEN** 該值 SHALL 解析自 `:root` 的 `--z-*` scale
- **AND** SHALL 不出現硬編堆疊數值，亦 SHALL 不以 `!important` 宣告 `z-index`
