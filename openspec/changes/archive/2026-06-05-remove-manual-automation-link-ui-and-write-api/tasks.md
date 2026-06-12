# Tasks — remove-manual-automation-link-ui-and-write-api

> 順序由上往下；每個 task 完成後 commit 一次以利 review 與回滾。

## 1. 後端 service 與 schema 收斂

- [x] 1.1 從 `app/services/automation/linkage_service.py` 刪除 `create_link` / `update_link` / `delete_link` 公開方法
- [x] 1.2 刪除 `AutomationLinkAlreadyExistsError` / `PrimaryAutomationLinkConflictError` 例外類型
- [x] 1.3 刪除私有方法 `_ensure_link_does_not_exist` / `_ensure_primary_available` / `_refresh_script_link_count`
- [x] 1.4 確認並刪除 `list_links_for_script`（若無外部呼叫端）
- [x] 1.5 在 `linkage_service.py` 註解中標註：「`linked_test_case_count` 之後由 marker 自動同步寫入路徑維護」
- [x] 1.6 從 `app/models/automation_link.py` 刪除 5 個 Pydantic schema（Create / Update / BatchCreate / BatchSkip / BatchResponse）與對應 import
- [ ] 1.7 在 `linkage_service.py` 介面區塊宣告三個 marker 自動同步錨點（**介面**放本 change，**實作**由 `add-automation-test-markers-and-test-view` 落地）：
  - `upsert_marker_link(team_id, script_id, test_case_id, link_type, marker_meta) -> AutomationScriptCaseLink`
  - `delete_marker_link(team_id, script_id, test_case_id) -> bool`
  - `refresh_script_link_count(script_id) -> int`
- [ ] 1.8 為 marker 自動同步補上 audit 與 outbound event 觸發輔助（介面契約）：
  - `_log_link_action(..., source="marker-sync", reason=...)` 寫 `AUTOMATION_SCRIPT_LINK` audit
  - `dispatch_event_async(..., "script.linked" | "script.unlinked", {actor_user_id: "system:marker-sync", ...})` 觸發 webhook

## 2. 後端 API endpoint 移除

- [x] 2.1 從 `app/api/automation_links.py` 刪除 `create_automation_script_link` / `update_automation_script_link` / `delete_automation_script_link` / `batch_create_automation_script_links` 四個 handler
- [x] 2.2 刪除 `_run_link_write` 輔助函式（無寫入端點後無用途）
- [x] 2.3 從 `_log_link_action` 移除人工 CREATE / UPDATE / DELETE 呼叫路徑（保留 marker-sync 呼叫點）
- [x] 2.4 移除人工 `dispatch_event_async` 的 `script.linked` / `script.unlinked` 觸發（保留 marker-sync 觸發點）
- [x] 2.5 清理 `app/api/automation_links.py` 已無用的 import
- [x] 2.6 確認 `app/api/__init__.py` 的 `api_router.include_router(automation_links_router)` 仍可運作

## 3. 前端 modal 與按鈕移除

- [x] 3.1 從 `app/static/js/automation-hub/suites/main.js` 刪除 manage-links modal 10 個函式
- [x] 3.2 刪除 `data-script-manage-links` click handler 委派
- [x] 3.3 刪除 `state.linksScriptId` / `state.linksSelected` / `state.linksResults` / `state.linksExisting` / `state.linksModal` 欄位
- [x] 3.4 從 `suites/main.js` script row 模板刪除 `<button data-script-manage-links="...">` 元素
- [x] 3.5 從 `app/static/js/automation-hub/coverage/main.js` 刪除 `data-coverage-manage-links` click handler
- [x] 3.6 從 `coverage/main.js` 刪除 `<button data-coverage-manage-links="...">` 元素
- [x] 3.7 從 `app/static/js/test-case-management/automation-panel.js` 刪除「+ Link automation script」按鈕（若有）
- [x] 3.8 從 `app/templates/automation_hub.html` 刪除 `#scriptLinksModal` 整段 modal markup
- [x] 3.9 從 `app/static/css/automation-hub.css` 刪除 `.automation-links-*` 與 `#scriptLinksModal` 相關樣式

## 4. i18n 清理

- [x] 4.1 從 `app/static/locales/en-US.json` 刪除 `automationHub.links.*` 全系列 key
- [x] 4.2 同步刪除 `zh-TW.json` / `zh-CN.json` 對應 key
- [x] 4.3 從三語言檔刪除 `automationHub.coverage.manageUnavailable`（若仍存在）

## 5. 測試清理

- [x] 5.1 刪除 `app/testsuite/test_automation_links_api.py`（untracked 整檔）
- [x] 5.2 從 `app/testsuite/test_automation_linkage_service.py` 移除 `test_primary_link_is_unique_per_test_case`
- [x] 5.3 移除 `test_update_link_to_primary_checks_existing_primary`
- [x] 5.4 移除 `test_delete_link_refreshes_script_link_count`
- [x] 5.5 編修 `test_create_link_and_list_linked_automation`：只保留 list 驗證段
- [x] 5.6 確認 `test_list_links_for_script_detailed_includes_case_number_and_title` 與 `test_delete_script_cache_cascades_links` 仍能跑
- [x] 5.7 跑 `pytest app/testsuite/test_automation_linkage_service.py -q` 確認綠

## 6. Marker 自動同步整合驗證（介面已宣告於本 change，實作由 marker change 落地）

> 本 change **不**實作 marker 解析邏輯；只負責介面契約與整合點規範。實作由 `add-automation-test-markers-and-test-view` 完成。

- [ ] 6.0.1 確認 `AutomationScriptService.sync()` 會依序呼叫 `linkage_service.upsert_marker_link` / `delete_marker_link` / `refresh_script_link_count`（於 marker change 內實作）
- [ ] 6.0.2 確認 `sync()` 觸發路徑涵蓋：手動 `POST .../automation-scripts/sync`、背景排程每小時 sync、首次從 StorageProvider import
- [ ] 6.0.3 確認 marker 變更會同步觸發 `script.linked` / `script.unlinked` outbound event（`actor_user_id: "system:marker-sync"`）
- [ ] 6.0.4 確認 audit log 每筆 marker-sync 變更都有 `AUTOMATION_SCRIPT_LINK` + `details.source = "marker-sync"` 紀錄
- [ ] 6.0.5 確認 `unknown_tc` 警告路徑（marker 寫了但 case 不存在）→ 不建 link、記入 scan response `warnings[]`
- [ ] 6.0.6 確認 marker 解析失敗採 fail-open（不阻擋 sync，於 `warnings[]` 紀錄）

## 7. 一次性清理腳本

- [x] 7.1 新增 `scripts/cleanup_manual_automation_links.py`：
  - argparse 接受 `--dry-run`（預設）/ `--confirm` / `--team-id <id>`（選填）
  - 直接用 `sqlite3` 連 `test_case_repo.db`
  - `--dry-run` 印出「預計刪除 N 列」與前 10 筆範例
  - `--confirm` 模式：要求使用者輸入「YES」字串確認；執行單一 DELETE 語句並印出實際影響列數
- [x] 7.2 在腳本頂部加 usage 註解，明確標示「執行前請先 `cp test_case_repo.db test_case_repo.db.bak.<ts>`」
- [x] 7.3 註明：「`NULL created_by` 列保留（屬 legacy、無明確來源標記）；僅清 `created_by` 非 marker-sync / ai-suggest 前綴的歷史人工列」

## 8. 跨 change 同步編修（**本 change archive 前必做**）

- [ ] 8.1 編修 `openspec/changes/add-automation-test-markers-and-test-view/proposal.md`：刪除「人類手建 link 優先級高於 marker」「衝突時保留人類版本」相關段落
- [ ] 8.2 編修 `add-automation-test-markers-and-test-view/design.md`：刪除「Marker 與人類手建 link 衝突的 UX」段落
- [ ] 8.3 編修 `add-automation-test-markers-and-test-view/tasks.md`：移除「人類手建 link 衝突解決」相關 task
- [ ] 8.4 編修 `add-automation-test-markers-and-test-view/specs/automation-hub-script-management/spec.md`：把「人類手建 link 優先」改寫為「marker-sync 為唯一寫入來源」
- [ ] 8.5 確認 `add-automation-test-markers-and-test-view` 的 `sync()` 流程符合本 change task 6 規定的整合點
- [ ] 8.6 PR 描述勾選「marker change 同步編修完成」

## 9. 驗證

- [x] 9.1 `openspec validate remove-manual-automation-link-ui-and-write-api --strict` 通過
- [ ] 9.2 `pytest app/testsuite -q` 全綠
- [x] 9.3 `rg "data-script-manage-links|data-coverage-manage-links" app/` 確認前端無殘留
- [x] 9.4 `rg "create_link|update_link|delete_link" app/services/automation/linkage_service.py` 確認 service 無殘留
- [x] 9.5 `rg "AutomationLinkAlreadyExistsError|PrimaryAutomationLinkConflictError" app/` 確認例外類型已清
- [ ] 9.6 啟動服務（`./start.sh`）手動驗證：
  - Suites tab script row 無「Manage links」按鈕
  - Coverage tab script row 無「Manage links」按鈕
  - Test Case 詳情 Automation 面板無「+ Link automation script」CTA，但 linked scripts 列表仍顯示
  - 對 4 個被移除的 API 路徑直接打，回 404 / 405

> 2026-06-05 smoke note: `GET /health` = healthy；`POST /api/teams/1/automation-scripts/1/links` 回 405，`POST /api/teams/1/automation-scripts/1/links/batch` 回 404，`PATCH /api/teams/1/automation-scripts/1/links/1` 回 404，`DELETE /api/teams/1/automation-scripts/1/links/1` 回 404。UI 驗證因本機需要登入且目前無可安全使用的既有帳密，待人工登入後補完。

## 10. 文件

- [x] 10.1 `rg "Manage test case links" docs/` 確認無殘留
- [x] 10.2 README 的 Automation Hub 區段同步刪除手動連結示意（若有）
- [x] 10.3 補一段「Links come from pytest markers」的 release notes 段落，明確說明新行為
