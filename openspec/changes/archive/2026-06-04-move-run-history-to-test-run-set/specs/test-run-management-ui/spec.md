# Delta Spec — test-run-management-ui

> 對 `openspec/specs/test-run-management-ui/spec.md` 的 delta，記錄「Test Run Set 詳情頁新增 Automation Runs section」對既有 requirement 的影響。

## ADDED Requirements

### Requirement: Test Run Set detail MUST list automation runs triggered by this set

Test Run Set 詳情 modal SHALL 新增 `Automation Runs` section，列出所有 `test_run_set_id == current_set.id` 的 `automation_runs` row，欄位：run id、suite (script_group_id)、branch、status badge、triggered_by、started_at + duration、操作（取消、對齊、開報表）。

#### Scenario: 點開 Test Run Set 詳情載入 runs
- **WHEN** user 開啟 Test Run Set 詳情 modal
- **THEN** 系統 SHALL 立即對 `GET /api/teams/{team_id}/test-run-sets/{set_id}/runs` 取資料
- **AND** section 頂部 SHALL 顯示總筆數 badge
- **AND** 表格 SHALL 顯示 run id（monospace）、branch、status badge、triggered_by、started_at、duration
- **AND** 表格每行 SHALL 附「Open in CI」「Open report」「Cancel」「Reconcile」按鈕

#### Scenario: 空 set 顯示提示
- **WHEN** 此 set 尚未觸發任何 run
- **THEN** section SHALL 顯示「No runs yet. Click "Run as Automation" to trigger one.」提示

#### Scenario: 報表嵌入
- **WHEN** user 點某 run 的「Open report」按鈕
- **THEN** 系統 SHALL 開啟 `reportEmbedModal` 並把 `report_url` 設進 iframe
- **AND** 同一 modal 提供「Open in CI」按鈕連到 `external_run_url`（iframe 被 X-Frame-Options 阻擋時的 fallback）

#### Scenario: 取消 / 對齊 set-scope run
- **WHEN** user 點某 run 的「Cancel」（terminal 狀態不顯示）或「Reconcile」（已有 external_run_id 不顯示）
- **THEN** 系統 SHALL 對 `POST /api/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}/{cancel,reconcile}` 送 request
- **AND** 成功後 SHALL 重新載入 list

#### Scenario: Modal 關閉時清空
- **WHEN** user 關閉 Test Run Set 詳情 modal
- **THEN** 系統 SHALL 清空 runs 列表（避免下次開啟不同 set 看到舊資料）
