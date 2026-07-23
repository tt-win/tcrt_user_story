## Why

USM 匯入工具（從 Lark 多維表格匯入 User Story Map）已不再使用 — 團隊不再透過 Lark 維度表格管理 USM 結構，該功能已無實際使用場景。保留此功能徒增維護成本（i18n key、API endpoint、前後端程式碼）並在團隊管理頁面佔據不必要的 UI 空間。

## What Changes

- 移除團隊管理頁面中的「匯入工具」下拉選單與 USM 匯入模態框
- 移除 `POST /api/usm-import/import-from-lark` 與 `GET /api/usm-import/lark-preview` API 端點（**BREAKING**）
- 移除 `app/api/usm_import.py`（Lark 匯入 API router）
- 移除 `app/services/lark_usm_import_service.py`（Lark 匯入服務層）
- 移除 `app/static/js/usm_import.js`（前端匯入邏輯）
- 移除 `main.py` 中對 `usm_import_router` 的註冊
- 移除 `team-management/main.js` 中對應的事件監聽器
- 移除 `usm.importModal.*` 與 `usmImport.*` i18n keys（三語系）
- 清理相關文件中的過時參考

## Capabilities

### New Capabilities

無。本變更為純移除，不引入新功能。

### Modified Capabilities

無。現有 spec 中沒有針對 USM 匯入的行為描述，因此不需 delta spec。

## Impact

- **API**: `POST /api/usm-import/import-from-lark` 與 `GET /api/usm-import/lark-preview` 移除（BREAKING），無其他 API 受影響
- **UI**: `team_management.html` 中匯入工具下拉選單與模態框移除
- **前端 JS**: `usm_import.js` 檔案刪除；`team-management/main.js` 移除關聯事件綁定
- **後端**: `usm_import.py` router 與 `lark_usm_import_service.py` 服務刪除；`main.py` 取消 router 註冊
- **i18n**: 三語系檔案中 `usm.importModal.*`（~22 keys）與 `usmImport.*`（~15 keys）移除
- **文件**: `docs/USM_TEXT_MODE_README.md`、`docs/USM_TEXT_FORMAT_SPEC.md`、`docs/IMPLEMENTATION_SUMMARY.md` 中過時參考需更新或標註
- **測試**: 無現有測試被影響
- **資料庫**: 無 schema 變更，不需 migration
- **非目標**: 文字模式（`user_story_map.html` 中的 text pane 與 `usm-text-editor.js`）保留不變，因為它是 USM 的文字編輯功能而非「匯入工具」
