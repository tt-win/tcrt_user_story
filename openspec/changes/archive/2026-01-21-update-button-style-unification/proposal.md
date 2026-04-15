# Change: Unify Button Styles Across UI

## Why
目前各頁面按鈕樣式與配色分散在多個 CSS 檔案，導致外觀不一致且維護成本高。

## What Changes
- 定義全站一致的按鈕配色邏輯與狀態樣式（hover/active/disabled/outline/loading）。
- 規範所有按鈕元件（含 Bootstrap `.btn` 與自訂按鈕）需遵循同一套視覺規格。

## Impact
- Affected specs: ui-design-system (new)
- Affected code: `app/static/css/style.css`, page-specific CSS (`app/static/css/*.css`), all templates with buttons (`app/templates/**/*.html`)
