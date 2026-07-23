## 1. 後端移除

- [x] 1.1 刪除 `app/api/usm_import.py` 檔案
- [x] 1.2 刪除 `app/services/lark_usm_import_service.py` 檔案
- [x] 1.3 移除 `app/main.py` 中 `usm_import_router` 的 import 與 app.include_router 註冊（約行 133-140）

## 2. 前端 JS 移除

- [x] 2.1 刪除 `app/static/js/usm_import.js` 檔案
- [x] 2.2 移除 `app/static/js/team-management/main.js` 中與 USM 匯入相關的事件監聽器（`importUSMBtn`、`preprocessLarkTableBtn`、`confirmUSMImportBtn` 綁定程式碼，約行 125-128）

## 3. 模板清理

- [x] 3.1 移除 `app/templates/team_management.html` 中的「匯入工具」下拉選單（id=`importMenuGroup`，約行 22-34）
- [x] 3.2 移除 `app/templates/team_management.html` 中的 USM 匯入模態框（id=`usmImportModal`，約行 1036-1135）
- [x] 3.3 移除 `app/templates/team_management.html` 中對 `usm_import.js` 的 script 引用（約行 1137-1138）

## 4. i18n 清理

- [x] 4.1 從 `app/static/locales/en-US.json` 移除 `usm.importModal.*`（約 22 keys）與 `usmImport.*`（約 15 keys）
- [x] 4.2 從 `app/static/locales/zh-TW.json` 移除 `usm.importModal.*` 與 `usmImport.*`
- [x] 4.3 從 `app/static/locales/zh-CN.json` 移除 `usm.importModal.*` 與 `usmImport.*`

## 5. 文件更新

- [x] 5.1 更新 `docs/USM_TEXT_MODE_README.md`，移除 Lark 匯入相關段落
- [x] 5.2 更新 `docs/USM_TEXT_FORMAT_SPEC.md`，移除 Lark 匯入 API 參考
- [x] 5.3 更新 `docs/IMPLEMENTATION_SUMMARY.md`，移除匯入功能說明段落
- [x] 5.4 更新 `JIRA_ANALYSIS_SUMMARY.txt`，移除 USM 匯入功能位置說明（約行 98-114）

## 6. 驗證

- [x] 6.1 執行 `uv run ruff check app scripts database_init.py` 確認無 lint 錯誤
- [x] 6.2 執行 `npm run lint` 確認前端 lint 通過
- [x] 6.3 執行 `node scripts/check-i18n-coverage.mjs` 確認 i18n coverage 正常（不因移除 key 而報錯）
- [x] 6.4 執行 `uv run pytest app/testsuite -q` 確認後端測試全數通過
- [ ] 6.5 手動確認團隊管理頁面不再顯示「匯入工具」下拉選單，功能區塊正常渲染
