## Context
目前按鈕樣式分散於全站 CSS 與各頁面 CSS，且仍依賴多種 Bootstrap 類別與自訂類別，導致視覺與狀態規格不一致。

## Goals / Non-Goals
- Goals:
  - 統一全站按鈕色彩邏輯與互動狀態（hover/active/disabled/outline/loading）。
  - 保持既有主題色系與使用語意（primary/secondary/success/warning/danger/info）。
- Non-Goals:
  - 不更動按鈕的功能行為或新增元件框架。
  - 不引入新的 UI 套件或大幅改版佈局。

## Decisions
- Decision: 以既有主題色定義按鈕 token，集中在全域樣式檔進行覆寫，並要求所有自訂按鈕類別對齊 token。
- Alternatives considered:
  - 分散在各頁面調整：成本高、難以維護。
  - 導入新 UI 套件：超出範圍，且與既有 Bootstrap 5 佈局衝突。

## Risks / Trade-offs
- 既有頁面依賴的局部樣式可能與新規範衝突，需要逐頁調整。

## Migration Plan
1. 盤點現有按鈕樣式來源與例外。
2. 建立全域按鈕 token 與基底樣式。
3. 逐頁套用與修正。
4. 驗證主要頁面一致性。

## Open Questions
- 是否需要對特定功能性按鈕（例如 icon-only 或 tag button）保留例外規格？
