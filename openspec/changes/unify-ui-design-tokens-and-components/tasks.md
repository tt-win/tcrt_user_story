## 1. 設計 token 收斂（單一真實來源）

- [x] 1.1 盤點 5 種前綴 token 與使用點，對映策略見 design.md §1（canonical 命名 + alias 過渡）
- [x] 1.2 在 `style.css` `:root` 定義 canonical `--color-*`（primary/secondary/success/warning/danger/info，取現有值）
- [x] 1.3 主色錨點採**現有品牌藍 `#4a90e2`**（使用者決策，視覺變動最小）；覆寫 `--bs-primary`/`--bs-link-color` 為品牌主色，消除與 Bootstrap 預設 `#0d6efd` 的雙主色衝突
- [x] 1.4 將 `--tr-*` 色彩 token alias 至 canonical（`--tr-primary: var(--color-primary)` 等，值不變）。`--btn-*`/`--qa-*`/`--tc-*`/`--ai-*` 之 alias 留待後續（與 1.5 同批）
- [ ] 1.5 移除 `.btn-primary` 透明/漸層覆寫（**延後**：屬按鈕視覺重塑，需逐頁瀏覽器驗證；本次以「主色錨點 #4a90e2、按鈕樣式不變」維持最小視覺變動）

## 2. stylelint 護欄（防回退，無 Node build）

- [x] 2.1 新增 `package.json`（僅 devDependencies：stylelint）與 `.stylelintrc.json`，定位為檢查工具、不產出建置產物
- [x] 2.2 設定規則：禁止在 `:root` 以外使用原始 hex（`color-no-hex`；token 定義區塊以 `stylelint-disable color-no-hex` 例外）。目前以 severity `warning` 建立 baseline（596 處），待 group 4 收斂後可升為 error
- [x] 2.3 禁止 Jinja 模板新增 inline `style=` — 以 `scripts/check-inline-styles.mjs` 計數回歸守門（baseline 254，超過即 fail）
- [x] 2.4 提供執行入口（`npm run lint` / `lint:css` / `lint:templates` / `baseline`）；既有違規以 baseline 機制導入不阻斷開發（`scripts/frontend-lint-baseline.json`）。pre-commit hook 由團隊接入（README 已說明 `npm run lint`）
- [ ] 2.5 在 CI 新增一個 lint 步驟執行護欄（僅檢查，不建置）— 待接 Jenkins pipeline（`npm ci && npm run lint`）

## 3. Jinja macro 元件庫

- [x] 3.1 新增 `components/button.html`（`button(intent,size,label,label_i18n,icon,type,outline,extra_classes,attrs)`，對齊 Bootstrap 語意色，無 inline style）
- [x] 3.2 新增 `components/modal.html`（`modal(id,title,title_i18n,size,footer,scrollable)`，body 以 `{% call %}` 注入，取代手刻 `.modal`）
- [x] 3.3 新增 `components/data_table.html`（`data_table(columns,id,extra_classes,striped)`，一致表格容器，資料列可由 JS 填入）
- [x] 3.4 新增 `components/toolbar.html`（`toolbar(title,title_i18n,subtitle)`，操作鈕以 `{% call %}` 注入）
- [x] 3.5 撰寫 `components/README.md` 說明 5 個 macro 的 API 與輸出契約；4 個 macro 皆通過 Jinja2 render 驗證且不輸出 inline style

## 4. 遷移 silo CSS 與 inline styles

- [ ] 4.1 將 `app/static/css/team-statistics.css` 內硬編 hex 替換為 canonical token（達成 0 raw hex）
- [ ] 4.2 將 `app/static/css/test-case-reference.css` 內硬編 hex 替換為 canonical token
- [ ] 4.3 將 `app/static/css/test-case-set-list.css` 內硬編 hex 替換為 canonical token
- [ ] 4.4 將 9 個手刻 modal 的模板改用 `modal()` macro，移除各 CSS 檔重複的 `.modal` 樣式
- [ ] 4.5 將 `app/templates/test_case_management.html`（84 處 inline style）的 inline `style=` 搬至 utility class
- [ ] 4.6 將 `app/templates/test_run_execution.html`（57 處）的 inline `style=` 搬至 utility class
- [ ] 4.7 將 `app/templates/user_story_map.html`（31 處）的 inline `style=` 搬至 utility class

## 5. CDN 依賴與 JS 模組化

- [ ] 5.1 盤點現有 CDN 依賴與來源（Bootstrap 5.3.0、Handsontable、Monaco、ReactFlow+React+dagre、Chart.js、marked、highlight.js、DOMPurify）與各自版本
- [ ] 5.2 統一為單一 origin 並鎖定版本，或 vendor 到 `app/static/vendor/`；在 `base.html` 集中載入，消除版本漂移
- [ ] 5.3 抽出共用 `app/static/js/ui/` utils 模組，提供由 CSS 變數讀取顏色的 helper（取代 JS 內 193 個硬編 hex 的來源）
- [ ] 5.4 以資料夾為單位，將至少一個 JS 功能改寫為 ES modules 作為示範與模式確立

## 6. 驗證

- [ ] 6.1 執行 `npx stylelint` 確認 `:root` 外無原始 hex、模板無 inline `style=`（或對應 baseline 已收斂）
- [ ] 6.2 grep 驗證 3 個原無 token 的 CSS 檔已改用 `var(--`，且不再含硬編 hex
- [ ] 6.3 grep 驗證主色衝突已消除（`#4a90e2`／`#0d6efd`／`#2463eb` 不再散見於非 `:root` 處）
- [ ] 6.4 瀏覽器手動驗證：抽查首頁、test case 管理、test run 執行、user story map、team statistics 等頁，按鈕／modal／表格／工具列視覺一致且與遷移前外觀無感差異
- [ ] 6.5 確認 CDN 依賴載入正常、版本鎖定生效，無 console 載入錯誤
