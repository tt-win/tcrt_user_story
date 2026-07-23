# Design: 統一 UI design token 與元件庫

本文件說明本變更的設計決策，重點在於：在**不導入 Node build pipeline、不做視覺改版、不導入 SPA 框架**的前提下，如何把分裂的 token／元件／依賴收斂為單一來源，並以可漸進、非破壞性的方式落地。

## 約束與前提

- 技術棧固定：server-rendered Jinja2 + vanilla CSS/JS + Bootstrap 5（CDN）。
- 不得新增建置流程（webpack／vite／PostCSS／Sass 編譯等）。CSS 必須維持瀏覽器可直接載入的原生 CSS。
- 不得改變既有外觀（保留 TestRail／TCRT look），本變更是「收斂／一致性」而非「重設計」。
- 必須可漸進落地：22 個 CSS 檔（約 10,350 行）、88 個 JS 檔、254 個 inline style 無法一次重寫，需新舊並存的過渡策略。

## 1. Token 命名空間遷移（5 前綴 → 1）

### 現況

跨 6 個檔案有 115 個 token 定義、5 種競爭前綴：`--btn-`（60）、`--tr-`（36）、`--qa-`（7）、`--tc-`（4）、`--ai-`（1）。三個 CSS 檔完全不用 token。

### 目標命名規格

於 `style.css` `:root` 收斂為單一語意化命名，分四類：

- 顏色：`--color-{primary|secondary|success|warning|danger|info|…}`，必要時加狀態尾綴（如 `--color-primary-hover`）。
- 間距：`--space-{1..n}`（單一 scale）。
- 圓角：`--radius-{sm|md|lg}`（單一集合）。
- 陰影／層級：`--elevation-{0..n}`（單一集合）。

### 遷移策略：alias 過渡，非一次替換

canonical token 為唯一真實值；舊前綴 token **不刪除**，改寫為指向 canonical 的 alias：

```css
:root {
  /* canonical（唯一真實來源） */
  --color-primary: #0d6efd;       /* 對齊 Bootstrap --bs-primary */
  --space-2: 0.5rem;
  --radius-md: 0.375rem;

  /* legacy alias（過渡相容，逐步移除） */
  --tr-primary: var(--color-primary);
  --btn-bg-primary: var(--color-primary);
}
```

如此既有引用舊 token 的 CSS 不需同步改動即可立即對齊新值，達成非破壞性。alias 在後續清理任務中逐步移除。

## 2. Bootstrap 對齊策略

主色衝突來源：design token `--tr-primary=#4a90e2`、Bootstrap `#0d6efd`（22 處）、JS `#2463eb`（10 處）。

決策：**以 Bootstrap `--bs-primary` 為錨點**，`--color-primary` 取同值，並覆寫 Bootstrap 變數使兩者恆等：

```css
:root {
  --color-primary: #0d6efd;
  --bs-primary: var(--color-primary);
  --bs-primary-rgb: 13, 110, 253;
}
```

理由：Bootstrap 由 CDN 載入且 `.btn-primary`、連結、focus ring 等大量元件預設吃 `--bs-*`；以其為錨點可讓「不改 markup 的既有 Bootstrap 元件」自動對齊，遷移面最小。`#4a90e2`／`#2463eb` 透過 alias 與 JS `ui/` utils 收斂（見 §5），不再硬編。

`style.css` 目前對 `.btn-primary` 的透明／漸層覆寫會被 per-page CSS 繞過，造成不一致；本變更移除該覆寫，讓按鈕色單一來自 canonical 主色，與既有 `ui-design-system`「Global Button Visual System」需求一致。

## 3. Macro 元件 API 介面

於 `app/templates/components/` 新增四個 macro，沿用既有 `components/status_badge.html` 的 Jinja macro 慣例。API 以「行為與輸出契約」描述，實作可調整參數細節：

- `button(intent='primary', size='md', label='', icon=none, type='button', attrs={})`
  輸出單一按鈕結構，class 對齊 canonical 按鈕樣式；`intent` 對映語意色 token。取代散落 46 處的 `.btn` 變體。

- `modal(id, title, body, footer=none, size='md')`
  輸出單一 modal 結構（header／body／footer）與一致樣式，取代 9 個各自手刻的 `.modal` 樣式來源。`body`／`footer` 以 caller block 注入。

- `data_table(columns, rows=none, options={})`
  輸出一致的表格容器與 class；`columns` 定義表頭，`rows` 可選（資料由 JS 動態填入時可只取容器）。

- `toolbar(items=[])`
  輸出頁面操作列的一致排版容器；`items` 為按鈕／控制項集合。

使用方式（示意）：

```jinja
{% from 'components/modal.html' import modal %}
{% call modal(id='edit-tc', title='Edit Test Case') %}
  {# body content #}
{% endcall %}
```

## 4. stylelint 護欄整合（無 Node build）

定位：stylelint 僅為**檢查工具**，不產出任何建置產物、不參與資產 pipeline。

- 依賴：`package.json` 僅含 devDependencies（stylelint + 必要 plugin）；無 build script。
- 執行：`npx stylelint "app/static/css/**/*.css"`，並掛 pre-commit hook；CI 增加單一 lint 步驟。
- 規則一：`:root` 以外禁止原始 hex（以 `color-no-hex` 搭配對 `:root` 的例外，或等效設定），強制改用 token。
- 規則二：禁止模板 inline `style=`。stylelint 原生不掃 HTML，故以 stylelint 的 HTML/Jinja plugin 或一支輕量輔助 lint script 涵蓋 `app/templates/**`，納入同一 lint 步驟。
- 既有違規導入策略：採 baseline（記錄現有違規清單）或分批收斂，新增違規一律阻擋，但不因存量違規阻斷既有開發。

## 5. JS 顏色去硬編與模組化（P2）

JS 內 193 個硬編 hex 是顏色第三來源。設計：新增 `app/static/js/ui/` 共用 utils 模組，提供由 CSS 變數讀色的 helper（`getComputedStyle(document.documentElement).getPropertyValue('--color-primary')`），讓 JS 取色單一來自 token。

模組化採資料夾為單位漸進改 ES modules，先以一個功能確立模式（`<script type="module">` 載入，無打包）。此為 P2，與 P0／P1 解耦，可獨立推進。

## 6. 非破壞性漸進落地

- **新舊並存**：舊前綴 token 以 alias 保留、舊 CSS 類別不立即刪除；遷移期任一頁面可在尚未改寫前維持原樣。
- **視覺無感**：主色錨定既有 Bootstrap 值、其餘 token 取既有實際值；CDN 改為鎖版只固定現用版本，不升級。
- **可分批**：P0（token + 護欄）先止血並防回退；P1（元件 + 最髒頁面）逐頁收斂；P2（CDN + JS 模組）獨立推進。各階段皆可獨立驗證、獨立合併。
- **可回退**：每階段為加法或等值替換；alias 與 baseline 機制確保任一步驟可中止而不破壞既有頁面。

## 風險與緩解

- **inline style 掃除遺漏視覺差異**：以逐頁人工抽查（驗證 6.4）搭配遷移前後對照，確保外觀一致。
- **stylelint HTML 覆蓋度**：若 plugin 對 Jinja 語法支援不足，退而以輔助 grep-based script 檢查 inline `style=`，仍納入同一 lint gate。
- **Bootstrap 變數覆寫副作用**：覆寫 `--bs-primary` 可能牽動 focus ring／連結等；以抽查頁面確認無非預期變化。
