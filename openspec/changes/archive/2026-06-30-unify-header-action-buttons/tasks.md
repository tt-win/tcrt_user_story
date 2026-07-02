# Tasks

## 1. 簡單導覽頁（尺寸/標籤/圖示）
- [x] 1.1 `index.html`：Team Settings → `btn-sm`，`me-2`→`me-1`（保留 primary CTA）
- [x] 1.2 `profile.html`：Home 文案 `common.home`→`navigation.backToHome`
- [x] 1.3 `test_case_set_list.html`：Home 文案 `common.home`→`navigation.backToHome`，`fa-home` 補 `me-1`
- [x] 1.4 `qa_ai_helper.html`：Back-to-sets `me-2`→`me-1`；Home `common.home`→`navigation.backToHome`、`me-2`→`me-1`

## 2. 核心管理頁（尺寸 + 語意色）
- [x] 2.1 `test_case_management.html`：全部 `btn-sm`、`me-2`→`me-1`；Bulk Mode `primary`→`info`
- [x] 2.2 `test_run_management.html`：Refresh/Home `btn-sm`、`me-2`→`me-1`；狀態篩選補 `btn-sm`（保留狀態色）
- [x] 2.3 `team_management.html`：全部 `btn-sm`、`me-2`→`me-1`；Import/Data/OrgSync `primary`→`info`（保留 Create Team primary）
- [x] 2.4 `user_story_map.html`：全部 `btn-sm`、`me-2`→`me-1`（MapList=secondary、CalcTickets=info、Save=success、Home=secondary）

## 3. 執行類頁（ms-auto 分區）
- [x] 3.1 `test_run_execution.html`：全部 `btn-sm`、`me-2`→`me-1`；Charts & Reports `primary`→`info`（保留 Start=success/Complete=warning/Restart=info 與 ms-auto 分區）
- [x] 3.2 `adhoc_test_run_execution.html`：全部 `btn-sm`、`me-2`→`me-1`；Charts & Reports `primary`→`info`

## 4. 導覽 outlier 修正
- [x] 4.1 `team_statistics.html`：導覽順序改為 返回上層 → 首頁（交換 Home 與 Back-to-management，調整 `me-2`）
- [x] 4.2 `audit_logs.html`：Back-to-teams `fa-chevron-left`→`fa-arrow-left`、`btn-sm`、`me-2`→`me-1`，後方補 Home
- [x] 4.3 `automation_provider_settings.html`：Back-to-Hub 移入右側群組，橫向 Team Management → Home；順序 Add → Refresh → Back-to-Hub → Home
- [x] 4.4 `automation_webhook_config.html`：同 4.3（Add Webhook → Refresh → Back-to-Hub → Home）

## 5. 驗證
- [x] 5.1 瀏覽器抽查 ≥4 頁（含 test_run_management 篩選、team_statistics、設定頁、執行頁）確認尺寸/顏色/順序
- [x] 5.2 `automation_hub.html` 確認仍為基準（不需改動）
