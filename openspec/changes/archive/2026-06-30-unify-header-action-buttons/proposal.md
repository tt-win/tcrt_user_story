## Why

各頁面 header 的操作按鈕在尺寸（btn-sm vs 全尺寸）、顏色語意、排列順序與導覽按鈕（Back/Home）的圖示與 i18n key 上各自為政，造成視覺不一致與認知負擔。需要一套明確、可被守門的規範，讓既有頁面收斂、未來新頁面遵循。

## What Changes

- 統一所有 header 操作按鈕為 `btn-sm`，圖示與文字間距統一為 `me-1`
- 套用語意化顏色調色盤：`primary`=主要建立/CTA、`success`=提交（儲存/開始/轉換）、`warning`=停止/終結、`info`=次要功能啟動（AI Helper、圖表報表、計算票證、重新執行、匯入工具、數據選單、組織設定）、`secondary`=工具與導覽（重新整理、跳至、返回上層、首頁、橫向設定連結）
- **篩選與分段切換控制項**（狀態篩選、日期區間、團隊篩選）為例外：維持狀態/選取的顏色編碼與 active 狀態，僅套用尺寸規則
- 統一排列：頁面動作（依重要性）→ 工具（Refresh）→ Jump-to →【導覽群組：返回上層（`fa-arrow-left`）→ 首頁（`fa-home`）】固定靠右、置於 user menu 之前
- 統一導覽按鈕：返回上層用 `fa-arrow-left`（取代 audit_logs 的 chevron）；首頁一律 `fa-home` + `navigation.backToHome` + `href="/"`（停用 header 內的 `common.home`）
- 修正 outlier：`team_statistics` 導覽順序（首頁/返回顛倒）、`automation_provider_settings` 與 `automation_webhook_config` 的返回鍵置左＋橫向「Team Management」連結、`team_management` 與部分頁的 `primary` 濫用

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `ui-design-system`: 新增「Header Action Button Layout and Color Logic」需求，明文規範 header 操作按鈕的尺寸、語意化顏色、排列順序、導覽按鈕慣例與篩選控制項例外，並要求新頁面遵循（守門）

## Impact

- 受影響 templates（header `page_specific_actions` 區塊）：`index`、`test_case_set_list`、`test_case_management`、`test_run_management`、`test_run_execution`、`adhoc_test_run_execution`、`user_story_map`、`team_management`、`team_statistics`、`audit_logs`、`qa_ai_helper`、`profile`、`automation_provider_settings`、`automation_webhook_config`（`automation_hub` 已符合，作為基準）
- i18n：header 內 `common.home` → `navigation.backToHome`（兩者值相同，無文案變動）；新增 audit_logs / 設定頁的首頁鍵沿用既有 key
- 無 API、資料庫、排程、MCP 影響；純前端模板與樣式 class 調整
