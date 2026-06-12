## Why

Automation Hub 目前同時提供「手動 UI/API 建立 link」與「marker sync 建立 link」兩條寫入路徑。實務上 marker 已是 single source of truth（程式碼自我宣告 coverage），手動 UI 是重複 surface，且帶來「人類誤連結」「marker 與人工 link 衝突」「link_type 維護成本」等問題；`add-automation-test-markers-and-test-view` 草稿中又設計了「人類手建 link 與 marker sync 衝突解決」邏輯，更凸顯手動路徑已無存在必要。

**取而代之的行為**：test case ↔ automation script 的 link 改由 pytest marker（`@pytest.mark.tcrt(...)` 與 JS/TS 對應註解）在 script 匯入或掃描時自動解析並 upsert 進 `automation_script_case_links`，全程無需使用者手動介入。本變更把寫入路徑收斂為這個 marker 自動同步流程；保留讀取端點供 Test Case 詳情 Automation panel 與 marker sync 顯示使用。

## What Changes

- **BREAKING**：移除 `POST /api/teams/{team_id}/automation-scripts/{script_id}/links` 單筆新增
- **BREAKING**：移除 `POST .../links/batch` 批次新增
- **BREAKING**：移除 `PATCH .../links/{link_id}` 更新
- **BREAKING**：移除 `DELETE .../links/{link_id}` 刪除
- **BREAKING**：移除 Automation Hub Suites tab 的「Manage test case links」按鈕與 modal
- **BREAKING**：移除 Automation Hub Coverage tab 的「Manage links」按鈕
- **BREAKING**：移除 Test Case 詳情 Automation 面板的「+ Link automation script」CTA
- 移除 `app/services/automation/linkage_service.py` 的 `create_link` / `update_link` / `delete_link` 方法，以及 `AutomationLinkAlreadyExistsError` / `PrimaryAutomationLinkConflictError` 例外類型
- 移除 `app/models/automation_link.py` 的 `AutomationScriptLinkCreate` / `AutomationScriptLinkUpdate` / `AutomationScriptLinkBatchCreate` / `AutomationScriptLinkBatchSkip` / `AutomationScriptLinkBatchResponse` Pydantic schema
- 移除 `app/static/js/automation-hub/suites/main.js` 的 manage-links modal 流程（`openLinksModal` / `loadExistingLinks` / `renderExistingLinks` / `searchLinkCases` / `renderLinkResults` / `updateLinksSelectedCount` / `addSelectedLinks` / `updateExistingLinkType` / `deleteExistingLink` / `emitLinksChanged` 與 `data-script-manage-links` 事件委派）
- 移除 `app/static/js/automation-hub/coverage/main.js` 的 `data-coverage-manage-links` 處理
- 移除 `app/static/js/test-case-management/automation-panel.js` 中若仍存在的「+ Link automation script」按鈕處理
- 移除 `app/static/css/automation-hub.css` 內 manage-links modal 相關樣式
- 移除 `app/templates/automation_hub.html` 內 `#scriptLinksModal` 區塊
- 移除 `app/static/locales/{en-US,zh-TW,zh-CN}.json` 的 `automationHub.links.*` i18n key
- 移除寫入端點觸發的 `script.linked` / `script.unlinked` outbound event 呼叫；改由 marker 自動同步流程觸發（event payload 與訂閱契約不變）
- 一次性清理：新增 `scripts/cleanup_manual_automation_links.py`，刪除 `automation_script_case_links` 表中 `created_by` 非 `marker-sync` 開頭、非 `ai-suggest` 開頭的所有列；需手動執行並印出影響列數（不寫進 alembic，屬一次性修補腳本）
- 測試清理：刪除 `app/testsuite/test_automation_links_api.py`（untracked，整檔僅測寫入路徑）；從 `app/testsuite/test_automation_linkage_service.py` 移除 `create_link` / `update_link` / `delete_link` / `primary_conflict` 相關測試案例，僅保留讀取路徑（`list_links_for_script_detailed`、`list_linked_automation`、cascade）
- 跨 change 同步：在本 change 的 `tasks.md` 內新增 task，要求編修 `add-automation-test-markers-and-test-view` 的 `proposal.md` / `design.md` / `tasks.md` / `specs/automation-hub-script-management/spec.md`，移除「人類 vs marker 衝突解決」段落與 `created_by` 優先級邏輯

**保留**（不在本 change 處理）：
- `automation_script_case_links` 資料表（marker 自動同步寫入 + 讀取端點使用）
- `GET /api/teams/{team_id}/automation-scripts/{script_id}/links` 與 `GET .../test-cases/{case_id}/linked-automation` 兩個讀取端點
- `linkage_service.list_links_for_script[_detailed]` 與 `list_linked_automation`
- Test Case 詳情 Automation 面板的「linked scripts 列表」（僅移除 + Link CTA）
- `automation-hub-smart-suite-recommendation` 內 marker 同步的解析實作（屬另一個 active change；本 change 只規範「scan/import 觸發 → link 更新」這個對外契約）

## Capabilities

### New Capabilities
（無）

### Modified Capabilities
- `automation-hub-script-management`：
  - **新增**「scan / import 時自動從 pytest marker 同步 link」requirement（marker 自動同步作為唯一寫入路徑的明確規範）
  - **移除**「手動建立 / 編輯 / 刪除 case link」相關 requirement（POST/PATCH/DELETE/Batch、PRIMARY 唯一性 service 規則、case detail panel 的 + Link CTA、Suites tab 的 Manage links 按鈕）
  - **保留**讀取端點與 `AutomationScriptCaseLink` 表格描述

## Impact

**Code**：
- `app/api/automation_links.py`（移除 4 個寫入端點 handler、移除 `_log_link_action` 的 CREATE 路徑、移除 `dispatch_event_async` 的 `script.linked` / `script.unlinked` 觸發；保留 2 個 GET 與錯誤轉譯工具 `_run_link_write` 收斂為只剩 `_not_found`）
- `app/services/automation/linkage_service.py`（刪 `create_link` / `update_link` / `delete_link` 三個方法、刪 `AutomationLinkAlreadyExistsError` / `PrimaryAutomationLinkConflictError` 兩個例外類型、刪 `_ensure_link_does_not_exist` / `_ensure_primary_available` / `_refresh_script_link_count`；保留 `_get_script` / `_ensure_test_case` / `_get_link` / `_latest_run` 供讀取路徑用，註明 `_refresh_script_link_count` 邏輯改由 `script_service` 在 marker sync 寫入時負責）
- `app/models/automation_link.py`（刪 5 個 Pydantic schema；保留 `AutomationScriptLinkResponse` / `AutomationScriptLinkDetailResponse` / `LinkedAutomationSummary`）
- `app/api/__init__.py`（不變 — `automation_links` router 仍註冊，僅內容縮減）
- `app/api/automation_scripts.py`（`require_team_admin` 在 manage-links 路徑的相依性消失，確認其他路由無用到後保留 import）
- 前端：見 What Changes 清單
- i18n：見 What Changes 清單
- 測試：見 What Changes 清單

**APIs**（破壞性）：
- 5 個寫入端點移除；既有 manage-links modal 使用者會看到 404 / 連線失敗
- `script.linked` / `script.unlinked` outbound webhook event 不再由本模組觸發；訂閱者需重新評估

**Database**：
- `automation_script_case_links` 表**保留**（無 schema 變更）
- 一次性清理腳本（手動執行、非 alembic）：
  - `WHERE created_by NOT LIKE 'marker-sync%' AND created_by NOT LIKE 'ai-suggest%'`
  - 預期影響：清掉本 change 之前所有「人工手建」歷史列
  - 執行前印出「預計刪除 N 列」並要求 `--confirm` 才執行；`--dry-run` 模式預設開
- 無 alembic revision；無 schema migration

**Dependencies / Systems**：
- `MainAccessBoundary`：`run_write` 在本模組僅剩 GET 讀取；寫入路徑全部消失
- audit log：歷史 `AUTOMATION_SCRIPT_LINK` CREATE/UPDATE/DELETE 紀錄**保留**（audit 表不可變更）
- `add-webhook-suite-trigger` change：與本 change 無直接耦合，event 通道未變動

**Risk / Rollback**：
- 主要風險：使用者若尚未採用 marker 將無 UI 路徑建立 link；緩解為 release notes 明確提示，並把 `add-automation-test-markers-and-test-view` 同步推進
- 跨 change 風險：`add-automation-test-markers-and-test-view` 必須同步編修，否則該 change 的 spec 會出現「人類手建 link」死需求；本 change 的 tasks 內會有同步編修 task 並在 PR 描述勾選
- Rollback：從 git history 還原 5 個端點與前端 modal 即可；一次性清理腳本屬不可逆（但只清掉 `created_by` 非 marker 的列，marker-sync 列不受影響）
