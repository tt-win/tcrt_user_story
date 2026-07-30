## 1. 共用元件

- [x] 1.1 新增 `app/templates/components/skeleton.html`，提供表格列與卡片列表兩種骨架，列數固定為視窗可見範圍。
- [x] 1.2 新增 `app/templates/components/empty_state.html`，結構對齊 `/organization-management` 使用者詳情區（圖示 + 標題 + 說明 + 可選動作入口）。
- [x] 1.3 在 `app/static/css/style.css` 新增 skeleton 與 empty state 的共用樣式，僅使用既有 design token。

## 2. 修復實測缺陷

- [x] 2.1 修正 `test-case-set-list/main.js:191-195` 的靜默提前返回：`currentTeamId` 缺失時 SHALL 呈現說明前置條件的狀態，不得只寫 `console.warn`。
- [x] 2.2 為 `#emptyState` 建立實際的顯示路徑（目前全檔只有 3 處引用、無任何 `remove('d-none')`，屬死碼），並確保 error 分支存在。
- [x] 2.3 修正 `/organization-management` 的 `#pm-delete`、`#pm-reset`，在未選取使用者時為 disabled，消除目前「可點但靜默 no-op」的行為（`personnel_management.js:524` 已有內部 guard，本項只補呈現層）。
- [x] 2.4 掃描其他選取相依動作（批次修改／批次複製／批次刪除等），套用相同啟用規則。

## 3. 非阻塞式確認與通知（105 處 / 15 檔）

- [x] 3.1 在 `app/static/js/app.js` 新增回傳 Promise 的 `AppUtils.confirm()` 與 `AppUtils.notify()`，使用系統內既有的 modal 與 toast 元件。
- [x] 3.2 高風險優先：改寫破壞性操作前作為唯一確認關卡的呼叫點（`organization-management/personnel_management.js:525` 刪除使用者、`test-case-cross-set-ops.js:325` 跨 set 搬移），每處補 regression 驗證確認關卡未被繞過。
- [x] 3.3 改寫 `adhoc_test_run.js`（21 處）、`test-case-section-list.js`（16 處）、`test-case-cross-set-ops.js`（14 處）。
- [x] 3.4 改寫 `adhoc_run_manager.js`（8）、`team-management/app-tokens.js`（7）、`user_story_map.js`（6）、`base-auth.js`（4）。
- [x] 3.5 改寫 `usm-text-editor.js`（3）、`test-case-section-integration.js`（3）、`personnel_management.js`（3）、`audit_logs.js`（3）、`test-run-execution/reports.js`（2）、`test-case-set-list/main.js`（2）、`test-case-management/utils.js`（2）、`test-run-management/validation.js`（1）。
- [x] 3.6 確認改寫後 `rg --pcre2 '(?<![\w.$])(alert|confirm)\s*\(' app/static/js` 零命中。

## 4. 逐頁補齊各狀態

- [x] 4.1 盤點所有呈現伺服器資料的視圖，記錄目前缺少的狀態。
- [x] 4.2 依盤點結果逐頁補齊 loading（形狀已知者用 skeleton）／empty／error 三態，content 維持現狀。
- [x] 4.3 錯誤狀態一律提供行內訊息與重試入口，不得只寫 console。

## 5. 在地化與驗證

- [x] 5.1 新增空狀態與錯誤狀態文案，同步 `en-US.json`、`zh-CN.json`、`zh-TW.json`。
- [x] 5.2 在 `app/testsuite/test_component_spec.py` 新增狀態契約檢查：資料區段具備各狀態容器、每個狀態容器都有對應的顯示路徑（防止 `#emptyState` 式死碼）、選取相依動作預設 disabled、模板與 JS 無原生 `alert`／`confirm`。
- [x] 5.3 Browser QA：逐頁確認無資料、載入中、載入失敗三種情況皆有可讀回饋且無空白區域。
- [x] 5.4 執行 `uv run pytest app/testsuite -q`、`uv run ruff check .`、`npm run lint`、`node scripts/check-i18n-coverage.mjs`、對應 `node --check`、`openspec validate establish-data-view-state-contract --strict`。
