# Design — remove-manual-automation-link-ui-and-write-api

## 1. 設計目標

把 `automation_script_case_links` 的寫入路徑收斂為 **pytest marker 自動同步** 單一來源；UI 與 API 不再提供手動建立 / 編輯 / 刪除 link 的入口。

**取代行為**：script ↔ test case 的 link 改由 script 內 pytest marker（`@pytest.mark.tcrt(...)`、JS/TS 對應註解）在 scan / import 流程觸發時自動解析並 upsert，全程無需使用者介入；具體 marker 文法於 `add-automation-test-markers-and-test-view` 規範，本 change 只負責規範「觸發點 + 對 link 表的寫入契約 + audit / webhook 整合」。

讀取端點與表結構保留給 marker sync 顯示、Test Case 詳情 Automation panel 與 coverage 統計使用。

## 2. 精準刪除清單

### 2.1 後端 — `app/services/automation/linkage_service.py`

**刪除**：
- 公開方法 `create_link(...)`
- 公開方法 `update_link(...)`
- 公開方法 `delete_link(...)`
- 公開方法 `list_links_for_script(...)`（內部被 `list_links_for_script_detailed` 取代；如無其他呼叫端則一起刪，否則保留）
- 例外類型 `AutomationLinkAlreadyExistsError`
- 例外類型 `PrimaryAutomationLinkConflictError`
- 私有方法 `_ensure_link_does_not_exist`
- 私有方法 `_ensure_primary_available`
- 私有方法 `_refresh_script_link_count`（註記：linked_test_case_count 改由 `app/services/automation/script_service.py` 的 marker sync 寫入路徑負責維護，於 `add-automation-test-markers-and-test-view` 內補實作）

**保留**：
- 例外類型 `AutomationLinkNotFoundError`（讀取路徑仍用得到）
- 例外類型 `AutomationLinkageServiceError`（基底）
- 公開方法 `list_links_for_script_detailed(...)`
- 公開方法 `list_linked_automation(...)`
- 私有方法 `_get_script` / `_ensure_test_case` / `_get_link` / `_latest_run`
- 工具函式 `link_to_dict(...)` / `_utcnow()`

### 2.1.1 新增 marker 自動同步寫入錨點（介面契約）

`linkage_service` 對外暴露的「marker 自動同步寫入」介面，**實作於 `add-automation-test-markers-and-test-view`**；本 change 在介面層做以下規範（用於對齊 service 與 script_service 呼叫端的契約）：

- `linkage_service.upsert_marker_link(team_id, script_id, test_case_id, link_type, marker_meta) -> AutomationScriptCaseLink`
  - 寫入 `created_by="marker-sync"`、`note` 內含 `marker_meta` 摘要
  - 若已存在 `created_by="marker-sync"` 既有 link 則更新 link_type 與 note
  - 若 link 不存在則 insert
  - 回傳寫入後的 ORM 物件供 audit / event 觸發使用
- `linkage_service.delete_marker_link(team_id, script_id, test_case_id) -> bool`
  - 僅刪除 `created_by="marker-sync"` 的 link；對其他來源 link 不動作
  - 回傳 `True` 表示實際刪了一列、`False` 表示無對應 marker-sync link
- `linkage_service.refresh_script_link_count(script_id) -> int`
  - 重算 `automation_scripts.linked_test_case_count` 並 flush
  - 由 `AutomationScriptService.sync()` 在 marker 解析後呼叫

> 上述三個方法**介面宣告**放本 change（讓讀取端點 / audit / event 觸發的契約清楚），**實作**於 `add-automation-test-markers-and-test-view` 落地。

### 2.2 後端 — `app/api/automation_links.py`

**刪除 endpoint 與 handler**：
- `POST /api/teams/{team_id}/automation-scripts/{script_id}/links`（`create_automation_script_link`）
- `PATCH /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`（`update_automation_script_link`）
- `DELETE /api/teams/{team_id}/automation-scripts/{script_id}/links/{link_id}`（`delete_automation_script_link`）
- `POST /api/teams/{team_id}/automation-scripts/{script_id}/links/batch`（`batch_create_automation_script_links`）

**刪除輔助**：
- `_run_link_write`（已無 write 操作需要它；改為最簡化或移除）
- `_log_link_action` 中 `ActionType.CREATE` / `UPDATE` 路徑（讀取端點不寫 audit；DELETE 隨 endpoint 一起刪）
- `dispatch_event_async` 的 `script.linked` / `script.unlinked` 觸發
- import：`AutomationScriptLinkCreate` / `AutomationScriptLinkUpdate` / `AutomationScriptLinkBatchCreate` / `AutomationScriptLinkBatchSkip` / `AutomationScriptLinkBatchResponse` / `AutomationLinkAlreadyExistsError` / `PrimaryAutomationLinkConflictError` / `MainAccessBoundary.run_write` 若無寫入用途則一併移除

**保留**：
- `GET /api/teams/{team_id}/automation-scripts/{script_id}/links`（`list_automation_script_links`）
- `GET /api/teams/{team_id}/test-cases/{case_identifier}/linked-automation`（`list_linked_automation_for_test_case`）
- `_case_label` / `_resolve_case_id`（讀取路徑仍要解析 `lark_record_id`）
- `_not_found` 工具

### 2.3 後端 — `app/models/automation_link.py`

**刪除 Pydantic schema**：
- `AutomationScriptLinkCreate`
- `AutomationScriptLinkUpdate`
- `AutomationScriptLinkBatchCreate`
- `AutomationScriptLinkBatchSkip`
- `AutomationScriptLinkBatchResponse`（含 `model_rebuild()` 呼叫）
- import：`Field`（若無其他用途）

**保留**：
- `AutomationScriptLinkResponse`
- `AutomationScriptLinkDetailResponse`
- `LinkedAutomationSummary`

### 2.4 前端 — `app/static/js/automation-hub/suites/main.js`

**刪除**：
- 函式：`openLinksModal` / `loadExistingLinks` / `renderExistingLinks` / `searchLinkCases` / `renderLinkResults` / `updateLinksSelectedCount` / `addSelectedLinks` / `updateExistingLinkType` / `deleteExistingLink` / `emitLinksChanged`
- 事件委派分支：`data-script-manage-links` click handler
- state 欄位：`state.linksScriptId` / `state.linksSelected` / `state.linksResults` / `state.linksExisting` / `state.linksModal`（若僅 manage-links 用則刪，否則留空）
- 按鈕元素：script row 內的 `<button data-script-manage-links="...">`（`suites/main.js:885` 附近）

**保留**：
- `linkSource()` 函式（marker sync 與 ai-suggest 顯示仍要用）
- 既有 marker badge 渲染、Test view 切換（屬另一個 active change）

### 2.5 前端 — `app/static/js/automation-hub/coverage/main.js`

**刪除**：
- `data-coverage-manage-links` click handler（`coverage/main.js:39` 附近）
- 按鈕元素：`<button data-coverage-manage-links="${script.id}">`（`coverage/main.js:122` 附近）
- 對應 i18n key 參照

### 2.6 前端 — `app/static/js/test-case-management/automation-panel.js`

**刪除**：
- 「+ Link automation script」按鈕的 click handler 與對應渲染（若有，於本 change 內以 rg 確認後刪除；無則不動）

### 2.7 前端 — `app/templates/automation_hub.html`

**刪除**：
- `#scriptLinksModal` 整段 modal markup（含 search / existing / batch 區塊）

### 2.8 前端 — `app/static/css/automation-hub.css`

**刪除**：
- `.automation-links-*` 類別（`automation-links-type` / `automation-links-result` 等）
- `#scriptLinksModal` 相關樣式（如有）

### 2.9 i18n — `app/static/locales/{en-US,zh-TW,zh-CN}.json`

**刪除**：
- `automationHub.links.manage`
- `automationHub.links.added`
- `automationHub.links.skipped`
- `automationHub.links.addFailed`
- `automationHub.links.updated`
- `automationHub.links.updateFailed`
- `automationHub.links.deleteConfirm`
- `automationHub.links.deleted`
- `automationHub.links.deleteFailed`
- `automationHub.links.loadFailed`
- `automationHub.links.searchFailed`
- `automationHub.links.noResults`
- `automationHub.links.sourceAi`
- `automationHub.links.sourceHuman`
- `automationHub.links.markerHint`
- `automationHub.coverage.manageUnavailable`（若已存在於 locales）

**保留**：
- `automationHub.links.sourceHuman` / `sourceAi` 若 marker sync 顯示 badge 仍要用，則保留；如僅 manage-links modal 用則刪

### 2.10 測試

**刪除**：
- `app/testsuite/test_automation_links_api.py`（untracked，整檔測 POST batch / GET enriched；GET 部分理論上仍存在，但目前檔案內容僅測寫入路徑）

**編修**：
- `app/testsuite/test_automation_linkage_service.py`：
  - 保留 `test_list_links_for_script_detailed_includes_case_number_and_title`
  - 保留 `test_create_link_and_list_linked_automation` 的「list_linked_automation」部分，移除 create_link 區段
  - 移除 `test_primary_link_is_unique_per_test_case`
  - 移除 `test_update_link_to_primary_checks_existing_primary`
  - 移除 `test_delete_link_refreshes_script_link_count`
  - 保留 `test_delete_script_cache_cascades_links`（cascade 行為不變）
  - fixture `automation_linkage_db` 仍需要（提供 read 測試的基本資料）

## 3. 一次性資料清理腳本

### 3.1 規格 — `scripts/cleanup_manual_automation_links.py`

- **用途**：刪除 `automation_script_case_links` 中 `created_by` 非 marker / ai-suggest 的歷史人工列
- **刪除條件**：
  ```sql
  DELETE FROM automation_script_case_links
  WHERE created_by IS NOT NULL
    AND created_by NOT LIKE 'marker-sync%'
    AND created_by NOT LIKE 'ai-suggest%'
  ```
- **NULL created_by 處理**：保留（屬 legacy 列，無明確來源標記；保守起見不動，留待人工檢視）
- **介面**：
  - 預設 `--dry-run`，只印出預計影響列數與前 10 筆範例
  - 加 `--confirm` 才真正執行 DELETE
  - 加 `--team-id <id>` 過濾單一 team（建議預設開）；不加則處理全部 team
- **執行環境**：同步 SQL（`sqlite3` 直接連線，避免 async session 開銷）
- **執行時機**：實作完成、PR merge 後由 ops 手動執行；不寫進 alembic

### 3.2 回滾

腳本無 transaction log，若誤刪需從 DB 備份還原。建議執行前先 `cp test_case_repo.db test_case_repo.db.bak.$(date +%s)`。

## 4. 跨 change 影響 — `add-automation-test-markers-and-test-view`

### 4.1 必刪內容（marker change 內）

- `proposal.md`：
  - 「Derived link sync」段落中「人類手建 link 優先級高於 marker」與「衝突時保留人類版本」相關描述
  - 「修改 Capabilities」中提到「人類手建 link 優先」的 requirement
- `design.md`：
  - 「Marker 與人類手建 link 衝突的 UX」段落
  - 「Unknown TC number 的處理」內若有人類 link fallback 設計
- `tasks.md`：
  - 任何與「人類手建 link 衝突解決」相關的 task
- `specs/automation-hub-script-management/spec.md` delta：
  - 移除「人類手建 link 優先」requirement 或改寫為「marker-sync 為唯一寫入來源」

### 4.2 不變內容

- marker 文法（`@pytest.mark.tcrt` / `// tcrt: TC-`）設計
- smart-scan response `marker_links` / `warnings` 擴充
- AI 建議式連結（`ai-link-suggestions` endpoint）— 屬輔助 surface，不算「人工手建 link」，保留
- Suites tab Script ↔ Test view 切換
- skill 同步義務

### 4.3 同步編修執行者

由本 change 的實作 PR 內含 marker change 的同步 PR（或同一 PR 多 commit），由 code review 確認 marker change 的 spec 不再含死需求後，本 change 才可 archive。

## 5. 測試計畫

### 5.1 保留 / 補強既有測試

- `test_automation_linkage_service.py` 留下的 read 測試仍跑：detailed list、list linked automation、cascade
- 不再測 create_link / update_link / delete_link / primary conflict

### 5.2 需新增測試

- `test_automation_links_api.py`：本 change 內**不重建**（untracked 檔案整個移除），因 read endpoints 行為未變、既有 service 測試已涵蓋
- `test_automation_linkage_service.py` 補一條：marker sync 寫入後 `list_linked_automation` 仍能讀到（屬 marker change 範圍，本 change 不補）

### 5.3 前端測試

本專案目前無 JS unit test，僅以手動驗證：

1. Suites tab：script row 沒有「Manage links」按鈕
2. Coverage tab：script row 沒有「Manage links」按鈕
3. Test Case 詳情 Automation 面板：沒有「+ Link automation script」CTA，但 linked scripts 列表仍顯示
4. 任何 4 個被移除 API 路徑直接打都回 404 / 405

## 6. 部署與發布

- 變更為「行為移除」型 PR，release notes 須明確標示 BREAKING
- 文件 `docs/` 內若提到 manage-links 流程需一併修（`fd docs/`、`rg "Manage test case links" docs/` 確認）
- README 的 Automation Hub 區段同步刪除手動連結示意
