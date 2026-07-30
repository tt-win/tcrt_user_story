## 1. Token 與視窗單位

- [x] 1.1 在 `app/static/css/style.css` 的 `:root` 新增 `--z-dropdown`／`--z-sticky`／`--z-chrome`／`--z-modal`／`--z-toast`／`--z-assistant` scale。
- [x] 1.2 將所有以視窗高度單位設定 `height`／`min-height`／`max-height` 的規則（含 `calc()` 形式）改為 `vh` fallback + `dvh` 覆寫，涵蓋 `style.css`、`index.css`、`automation-hub.css`、`adhoc-test-run-execution.css`、`system-setup-standalone.css`。
- [x] 1.3 將全站 `z-index` 宣告改為引用 token，移除 `z-index` 上的 `!important`；無法立即收斂者記入 lint baseline 並註明原因。

## 2. Header toolbar 可達性

- [x] 2.1 在 `base.html` 的 `.header-toolbar` 導入 overflow 機制：主要控制項留在列上，其餘收進尾端 overflow 選單，列本身可水平捲動作為 fallback。
- [x] 2.2 將使用者選單（含登出）與返回入口 pin 在列尾右側，確保不進入 overflow、於所有斷點可見。
- [x] 2.3 為 page subtitle 加上窄螢幕隱藏規則，移除直排擠壓。
- [x] 2.4 確認 `--header-height` 在導入 overflow 後維持固定，`.app-main` 的 `padding-top` 不需調整。

## 3. 死碼移除與浮動元素

- [x] 3.1 刪除 `app/static/css/style.css:1193-1216` 的 `.fixed-pagination-bar`／`.pagination`／`.page-link` 死碼（先以 `rg` 複驗 `app/templates`、`app/static/js` 零命中）。
- [x] 3.2 掃描其餘 app chrome 相關 class，移除無任何模板／腳本套用者。
- [x] 3.3 檢查語言切換器與 AI Assistant FAB 的佔位：兩者不得互相重疊，且不得遮蔽按鈕、連結或表格列操作；FAB 覆蓋靜態內容維持現狀。

## 4. 驗證

- [x] 4.1 在 `app/testsuite/test_component_spec.py` 新增 chrome 契約檢查：header toolbar 無不可達控制項、固定層 `z-index` 皆解析自 token、樣式表無缺 `dvh` 覆寫的 `vh` 宣告、app chrome class 皆有套用者。
- [x] 4.2 Browser QA：1440／768／375 三個斷點，逐頁確認 toolbar 全部控制項可達、登出可點、無水平溢出、modal 開啟時堆疊正確。
- [x] 4.3 執行 `uv run pytest app/testsuite -q`、`uv run ruff check .`、`npm run lint`、`node scripts/check-i18n-coverage.mjs`、`openspec validate fix-app-chrome-responsive-reachability --strict`。
