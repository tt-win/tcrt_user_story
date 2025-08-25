# UI 元件一致性修正計劃（不涉及 padding）

## 1. 目標與原則
- 目標：在不更動任何 padding 的前提下，統一按鈕、表單、卡片/容器、色彩系統、字體家族、互動狀態、Disabled 與 Badge/狀態標示，移除非標準與 inline style 造成的外觀差異，提高可及性。
- 原則：
  - 禁止修改任何 padding、行高導致的密度。
  - 以 CSS 變數集中管理色彩與效果，不硬編碼色碼。
  - 明確定義 Hover/Focus/Active/Disabled 行為。
  - 避免與框架衝突，盡量以工具類或變體類疊加。

## 2. 修正範圍
- 頁面：base.html、index.html、team_management.html、test_case_management.html、test_run_management.html
- 元件類型：
  - 按鈕：Primary/Secondary/Danger、Icon-only
  - 表單：input/textarea/select 的邊框、focus、驗證語義、placeholder
  - 卡片/容器：外觀（邊框、圓角、陰影）、分隔線
  - 色彩系統：中性色、語義色統一為變數
  - 排版：font-family 與標題字重
  - 互動狀態：Hover/Active/Focus-visible、Transition 時間/緩動
  - Disabled：透明度、游標、移除陰影與互動
  - Badge/狀態：Success/Error/Warning/Info 風格統一
- 明確不動：任何 padding 與由其導致的密度呈現。

## 3. 設計規範（精簡）
- 變數：在 app/static/css/style.css 最前段新增（沿用現有 TestRail 色票並補齊中性色/語義色與效果變數）
  - Brand/Neutral/Semantic：--tr-primary/--tr-primary-dark、--tr-text-*、--tr-border-*、--tr-bg-*、--tr-success/--tr-error/--tr-warning/--tr-info
  - Effects：--radius-sm/md/lg、--tr-shadow-sm/md
  - Motion：--duration-fast/base、--easing-standard
  - Focus：--focus-ring-color
- 全域 Focus：:focus-visible outline 3px、offset 2px，顏色採 --focus-ring-color
- Transition 統一：color/background/border-color/box-shadow/transform，使用 --duration-base 與 --easing-standard
- 按鈕：.btn + .btn-primary/.btn-secondary/.btn-danger；.btn-icon 用於純圖示；字重 600、邊框 1px、圓角 var(--radius-md)
- 表單：邊框 1px var(--tr-border-light)、圓角 var(--radius-md)、placeholder 為 --tr-text-muted；.is-invalid 使用 --tr-danger，.is-valid 使用 --tr-success
- 卡片/容器：.card/.panel/.toolbar：邊框 var(--tr-border-light)、圓角 var(--radius-lg)、陰影 var(--tr-shadow-sm)；分隔線 .divider：1px var(--tr-border-light)
- 排版：body 使用系統字 --font-sans；標題字重 700；文字顏色以 --tr-text-primary/secondary/muted
- Disabled：opacity 0.5、cursor not-allowed、移除陰影與 pointer-events
- Badge：.badge + .badge--success/error/warning/info，邊框 1px，圓角 var(--radius-sm)

## 4. 代碼落地項目
- CSS 新增與調整（style.css）
  - 加入 :root 變數與全域 Focus、Transition、Disabled 樣式（不修改任何 padding）
  - 新增 .btn 變體、表單樣式、.card/.panel/.toolbar、.divider、.badge 變體
- 模板替換（不動 padding）
  - 移除按鈕 inline style → 使用 .btn + 變體
  - 鏈接當按鈕 → 加 .btn-secondary 或 .btn-primary
  - 表單驗證 → 統一 .is-invalid/.is-valid；移除自定紅/綠邊框
  - 可互動卡片/列 → 加 .hoverable 或 .row-clickable
  - 色碼替換 → #999/#666/#ccc/#ddd/#eee 等改用變數
  - 容器外觀 → 加 .card/.panel/.toolbar；保留原 padding 屬性

## 5. 執行步驟與時程
- Phase A（0.5 天）
  - 新增變數與全域基礎規範至 style.css，不修改任何 padding
- Phase B（1-1.5 天）
  - 模板批次替換：按鈕類、表單驗證、容器外觀、可互動列/卡、色碼變數化
- Phase C（0.5 天）
  - 跨瀏覽器檢查 focus-visible、hover/active、禁用狀態；Badge 顯示與 i18n 內容共存檢查
- 非功能性限制：不修改 spacing 與行高；不更動任何 padding

## 6. 驗收標準
- 視覺一致性：
  - 所有按鈕均使用 .btn + 變體類，無 inline style
  - 表單 focus 與驗證邏輯一致，placeholder 顏色統一
  - 容器外觀統一（邊框、圓角、陰影），不影響內距
  - Badge/狀態標示使用統一的 4 種語義變體
- 可及性：
  - 鍵盤巡覽時所有可互動元素具可見 focus 樣式
  - Disabled 元件具備一致視覺與行為
- 代碼規範：
  - 模板無新出現的硬編碼色碼；主要色彩改以 CSS 變數
  - transition 屬性不再使用 all，採統一時間與緩動
- 回歸確認：
  - 批次刪除工具列邏輯不受影響
  - 中英文 i18n 內容替換不受外觀樣式影響

## 7. 風險與回滾
- 風險：第三方元件樣式權重衝突
- 緩解：新增類採低特異性選擇器，必要時以 utility 類局部覆蓋
- 回滾：保留 style.css.backup 與模板備份差異，必要時回退對應片段

## 8. 後續追蹤（非本輪範圍）
- 之後可評估：Spacing scale、表格密度、padding 與 line-height 的一致化
- 規劃將樣式拆分為 tokens.css 與 components.css，並導入 stylelint 以禁止 inline style 與未使用變數的色碼
