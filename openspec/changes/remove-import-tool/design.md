## Context

`team_management.html` 頁面工具列中有一個「匯入工具」下拉選單，內含「匯入 USM」按鈕，點擊後開啟模態框，讓使用者輸入 Lark 多維表格 URL 並將資料匯入為 USM（User Story Map）。這個功能的前端由 `usm_import.js` 處理，後端由 `app/api/usm_import.py`（Lark 匯入 API router）與 `app/services/lark_usm_import_service.py`（Lark API 呼叫與資料轉換）組成。

由於團隊已不再使用 Lark 管理 USM，該功能無實際價值，僅增加維護負擔。

## Goals / Non-Goals

**Goals:**
- 從團隊管理頁面完全移除「匯入工具」UI（下拉選單、模態框）
- 刪除 Lark 匯入 API 端點與後端服務
- 刪除前端 `usm_import.js`
- 清理對應的 i18n key
- 清理 `main.py` 中的 router 註冊

**Non-Goals:**
- 不移除文字模式（`user_story_map.html` 中的 text pane、`usm-text-editor.js`、`usm_text_parser.py`、`POST /api/user-story-maps/{id}/import-text`）— 這是獨立的 USM 文字編輯功能，不屬於「匯入工具」
- 不變更任何資料庫 schema
- 不變更 `app/services/qa_ai_helper_planner.py` 中對「匯入」intent 的分類（保留 `import_export` category，避免不必要改動）

## Decisions

1. **完全刪除而非註解** — 檔案層級刪除（`usm_import.py`, `lark_usm_import_service.py`, `usm_import.js`），UI 與 i18n 區塊也完全移除，不留 dead code。理由：功能無復用可能，保留只增加混淆。

2. **i18n key 直接刪除** — `usm.importModal.*`（約 22 keys）與 `usmImport.*`（約 15 keys）在三語系檔案中一次移除。不保留 deprecation 過渡期，因為沒有使用者依賴此功能。

3. **保留文字模式相關檔案不變** — `usm_text_parser.py`、`usm-text-editor.js`、`user_story_map.html` 文字 pane 不碰。這是獨立功能，不是匯入工具的一部分。

4. **文件更新策略** — `docs/USM_TEXT_MODE_README.md`、`docs/USM_TEXT_FORMAT_SPEC.md`、`docs/IMPLEMENTATION_SUMMARY.md` 僅移除 Lark 匯入相關段落，不大量重寫。`JIRA_ANALYSIS_SUMMARY.txt` 中相關段落也一併移除。

## Risks / Trade-offs

- **[Risk] 外部服務可能仍呼叫已移除的 API** → Mitigation：Lark 匯入 API 無已知外部呼叫者，移除前確認 API 無 recent 呼叫紀錄；若有需求仍可從 git history 恢復
- **[Risk] i18n key 移除後，其他 JS 可能動態引用這些 key** → Mitigation：`usm.importModal.*` 與 `usmImport.*` 只在 `usm_import.js` 中被引用，移除該檔案後無其他參照點
