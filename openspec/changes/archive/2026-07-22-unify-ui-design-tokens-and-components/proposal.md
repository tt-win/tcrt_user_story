## Why

全站 UI 風格已嚴重發散，維護成本與視覺不一致持續惡化：

- **顏色失控**：CSS 內約 220 個相異 hex、JS 內約 193 個硬編 hex；光是「主色藍」就有 ≥10 種同時在用且彼此衝突——design token `--tr-primary=#4a90e2`、Bootstrap `#0d6efd`（22 處）、JS `#2463eb`（10 處）三者各說各話。
- **token 分裂**：跨 6 個檔案共 115 個 token 定義，存在 5 種彼此競爭的前綴（`--tr-` 36、`--btn-` 60、`--qa-`、`--tc-`、`--ai-`）。另有 3 個 CSS 檔完全不使用任何 token（`team-statistics.css`、`test-case-reference.css`、`test-case-set-list.css`），直接寫死色碼。
- **元件零複用**：全站僅 1 個 Jinja macro（`components/status_badge.html`）與 1 個 include（`_partials/user_menu.html`）。`.modal` 被 9 個 CSS 檔各自獨立樣式化；`.btn` 選擇器散落在 46 處；`style.css` 把 `.btn-primary` 覆寫成透明／漸層樣式，per-page CSS 又各自繞過它。
- **inline style 蔓延**：模板中有 254 個 inline `style=""`（`test_case_management.html` 84、`test_run_execution.html` 57、`user_story_map.html` 31），讓 token 與樣式收斂無從談起。
- **CSS 量體龐大且各自為政**：22 個 CSS 檔（約 10,350 行）。`style.css`（1,545 行）經由 `base.html` 載入為事實上的基底，其餘 21 個則由各頁 `{% block head %}` 各自載入，形成 per-page silo。
- **CDN 來源混雜**：Bootstrap 5.3.0、Handsontable、Monaco、ReactFlow+React+dagre、Chart.js、marked、highlight.js、DOMPurify 等分別來自 jsdelivr／unpkg／cdnjs，版本漂移風險高。88 個 JS 檔，0 個使用 ES modules。

既有主規格 `ui-design-system` 目前僅涵蓋「按鈕視覺統一」。本變更在不做視覺改版、不導入 SPA 框架的前提下，把 token、元件、護欄一次收斂，並提供可漸進落地、非破壞性的路徑，止住風格回退。

## What Changes

本變更分三個優先序推進（P0 止血並建立護欄，P1 收斂元件與最髒的頁面，P2 處理依賴與 JS 模組化）。

**P0｜單一 token 層 + 護欄（止住回退）**

- 在 `style.css` 的 `:root` 收斂為**唯一一層 design token**：單一 `--color-primary`（對齊 Bootstrap `--bs-primary`）、單一 spacing scale、單一 radius／elevation 集合；把 5 種前綴（`--tr-`／`--btn-`／`--qa-`／`--tc-`／`--ai-`）收斂為一套命名規格。
- 既有前綴 token 改為**對映別名（alias）指向新 canonical token**，舊類別樣式不立即移除，確保非破壞性。
- 導入 **stylelint** 護欄（以 `npx` 或 pre-commit 執行，**不建立 Node build pipeline**）：禁止在 `:root` 之外出現原始 hex、禁止模板 inline `style=`，以阻止樣式回退。

**P1｜Jinja macro 元件庫 + 收斂最髒頁面**

- 在 `app/templates/components/` 建立可複用 Jinja macro 元件庫：`modal()`、`button()`、`data_table()`、`toolbar()`。
- 以 `modal()` 取代 9 個手刻 modal 樣式與複製貼上的 markup；以 `button()` 收斂散落的 `.btn` 變體。
- 將 3 個無 token 的 CSS 檔（`team-statistics.css`、`test-case-reference.css`、`test-case-set-list.css`）遷移為使用 canonical token。
- 將 inline-style 最嚴重的模板（`test_case_management.html`、`test_run_execution.html`、`user_story_map.html`）的 inline `style=` 掃到 utility class。

**P2｜CDN 單一來源 + JS 模組化**

- 將 CDN 依賴**鎖定版本並單一來源**（統一 origin 或 vendor 到 `static/vendor/`），消除版本漂移。
- 以資料夾為單位將 JS 功能漸進改為 ES modules，抽出共用 `ui/` utils 模組，由 CSS 變數讀取顏色（不再硬編 hex）。

非目標（Non-Goals）：

- **不**為 app shell 導入 SPA 框架（React／Vue）；維持 server-rendered Jinja2 + vanilla CSS/JS + Bootstrap 5 CDN。
- **不**做視覺改版；本變更為一致性／收斂，保留既有 TestRail／TCRT 外觀。
- **不**建立 Node build pipeline（webpack／vite／PostCSS 等）；stylelint 僅作為檢查護欄，不產出建置產物。
- **不**一次性重寫全部 22 個 CSS 檔或 88 個 JS 檔；採漸進式遷移，舊樣式以 alias 維持相容。

## Capabilities

### New Capabilities
<!-- 無新增 capability；本變更擴充既有 ui-design-system。 -->

### Modified Capabilities
- `ui-design-system`: 在既有「按鈕視覺統一」之上，新增（1）單一真實來源 design token 層、(2) 對齊框架的單一 canonical 主色、(3) modal／table／toolbar 可複用元件庫、(4) 以 lint 強制禁止原始 hex 與 inline style、(5) CDN 依賴版本鎖定與單一來源等需求。

## Impact

- **前端**：
  - `app/static/css/style.css`：`:root` 收斂為單一 canonical token 層；舊前綴 token 改為 alias。
  - `app/static/css/{team-statistics,test-case-reference,test-case-set-list}.css`：遷移為使用 canonical token。
  - `app/static/css/test-case-management.css`、`test-run-execution.css`、`user-story-map.css`：承接由模板 inline style 搬出的 utility class。
  - `app/templates/components/`：新增 `modal.html`、`button.html`、`data_table.html`、`toolbar.html` macro。
  - `app/templates/{test_case_management,test_run_execution,user_story_map}.html` 等：改用元件 macro 與 utility class，移除 inline `style=`。
  - `app/templates/base.html`：集中載入 CDN 依賴（單一來源、鎖定版本）並提供 `static/vendor/` 路徑。
  - `app/static/js/`：以資料夾為單位漸進改 ES modules，新增共用 `ui/` utils 模組（由 CSS 變數讀色）。
- **建置/工具** stylelint：新增 `.stylelintrc`（或等效設定）與 `package.json`／pre-commit 設定，以 `npx stylelint` 執行；規則含「`:root` 外禁止原始 hex」「模板禁止 inline `style=`」。**不**新增 Node build pipeline，CI 僅多一個 lint 步驟。
- **相容性**：採非破壞性漸進落地——舊前綴 token 以 alias 保留、舊 CSS 類別不立即刪除，遷移期新舊樣式可並存；視覺不改版，使用者外觀無感；CDN 改為鎖版只固定既有版本，不升級行為。lint 規則對既有違規可先以 baseline／逐步收斂方式導入，不阻斷既有開發。
