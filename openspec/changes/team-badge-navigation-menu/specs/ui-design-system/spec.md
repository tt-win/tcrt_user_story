## ADDED Requirements

### Requirement: Team Badge as Interactive Dropdown

Header 中的 team badge SHALL 作為可互動的 dropdown trigger，遵循現有 Bootstrap 5 dropdown 視覺規範與互動模式。

#### Scenario: Badge 外觀保持一致

WHEN team badge 升級為 dropdown trigger
THEN badge 外觀 SHALL 維持原有 `badge bg-primary` 樣式，不應有明顯視覺突變

#### Scenario: 有 dropdown caret 指示可互動

WHEN team badge 可互動時
THEN badge SHALL 顯示一個細微的 caret/chevron 圖示，提示使用者此元素可點擊展開

#### Scenario: Dropdown 選單視覺符合現有 Bootstrap dropdown

WHEN 下拉選單展開
THEN 選單 SHALL 使用 Bootstrap 5 `.dropdown-menu` 樣式，與頁面其他 dropdown（如語言切換器）視覺一致
