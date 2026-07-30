## 1. 字型鏈修復

- [x] 1.1 修正 `base.html` 的 Google Fonts family 名稱（`Noto Sans CJK TC` → `Noto Sans TC`），並確認回應實際包含 CJK family。
- [x] 1.2 先將 `style.css:12-15` 的 `[class*="case-number"]`／`[class*="test-number"]` 萬用選擇器收斂為具名 class 清單（至少涵蓋 `.test-case-number`、`.test-case-number-open`、`.test-case-number-value`、`.case-number`），確認命中範圍不含中文說明文字。
- [x] 1.3 移除無效的 `Noto Sans Condensed`，將編號類欄位改綁等寬字型，更新 `--font-*` token 命名與語意，並同步 `index.css:558` 的引用。
- [x] 1.4 合併 `app/static/css/style.css` 中兩條互相衝突的 `body { font-family }` 宣告（`:7-9` 與 `:193-201`），移除為勝出而加的 `!important`。

## 2. 第三方資產自託管

- [x] 2.1 建立 `app/static/vendor/`，納入 Bootstrap 5.3.0 CSS/JS、Font Awesome 6.4.0、pako 2.1.0 與字型 woff2，並附記錄來源與版本的 manifest。
- [x] 2.2 將 `base.html` 的所有外部 `<link>`／`<script>` 改指向 vendor 路徑，移除 jsdelivr／cdnjs／Google Fonts 的執行期依賴。
- [x] 2.3 為主要字重加 `<link rel="preload">`，字型宣告使用 `font-display: swap`。
- [x] 2.4 確認容器映像與 `asset_url()` 版本化機制正確涵蓋 vendor 資產。

## 3. 頭像代理

- [x] 3.1 新增已驗證使用者才可存取的頭像代理端點，向上游取得後以短期快取回應。
- [x] 3.2 上游不可用時回傳本地產生的字母縮寫佔位圖，不得破圖、不得回退為直連外部網域。
- [x] 3.3 將前端所有頭像來源改為代理端點，移除模板與 JS 中對 `feishucdn.com`、`gravatar.com` 的直接引用。

## 4. i18n 按需載入

- [x] 4.1 修改 `app/static/js/i18n.js`，初始只載入當前語系；`switchLanguage()` 時才載入目標語系。
- [x] 4.2 語系載入失敗時維持原語系並回報，不得留下半套翻譯或使頁面因 `i18n-loading` 永久隱藏。

## 5. 驗證

- [x] 5.1 在 `app/testsuite/test_component_spec.py` 新增檢查：渲染後的頁面不含指向外部 origin 的 `<link>`／`<script>`／`<img>`（`<iframe>` 與 `<a>` 明確排除，屬功能性外部內容）；每個 `--font-*` token 都有對應的自託管字型檔。
- [ ] 5.2 Browser QA：三語系逐頁確認 CJK 字型實際生效（DevTools 確認載入的 woff2 含 CJK）、頭像正常、離線／封鎖外部網域時頁面完整可用；同時確認 Allure 報表 iframe 未被誤擋。
- [x] 5.3 於瀏覽器量測 `Noto Sans TC` 四字重全部 `unicode-range` 分片的合計體積，據以決定是否需要靜態子集。
- [x] 5.4 執行 `uv run pytest app/testsuite -q`、`uv run ruff check .`、`npm run lint`、`node scripts/check-i18n-coverage.mjs`、`node --check app/static/js/i18n.js`、`openspec validate fix-frontend-asset-and-font-integrity --strict`。

### 5.3 量測結果（2026-07-30）

自託管 woff2（Google Fonts CSS API → fonts.gstatic.com 分片）合計 **4.72 MiB**：
- Noto Sans TC（400/500/600/700，105 個 unicode-range 檔）：**4.00 MiB**
- Noto Sans + Noto Sans Mono：其餘

結論：體積可接受，**暫不做靜態子集**；若日後映像體積壓力上升再評估預先產生的子集產物入 repo。

### 5.2 阻塞

本機 `:9999` 進程仍在 listen，但 `/health` 逾時無回應，無法完成 Browser QA。需重啟應用後再驗 CJK woff2 載入、頭像代理與離線可用性。
