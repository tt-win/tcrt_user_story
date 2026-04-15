## 1. Data Model and Migration / 資料模型與遷移

- [x] 1.1 Add helper stage telemetry schema and ORM model (`ai_tc_helper_stage_metrics`) / 新增 helper 階段 telemetry 資料表與 ORM 模型
- [x] 1.2 Add safe migration/init patch for telemetry table and indexes / 在初始化與補欄流程加入 telemetry table/索引的安全遷移
- [x] 1.3 Add typed model/DTO for stage telemetry record fields / 新增 stage telemetry 的 typed model/DTO 欄位定義

## 2. Helper Telemetry Capture / Helper telemetry 寫入流程

- [x] 2.1 Instrument helper stage lifecycle to capture start/end/duration / 在 helper 各階段生命週期記錄開始、結束與耗時
- [x] 2.2 Persist token usage breakdown (input/output/cache read/cache write) per stage / 在每階段落庫 token 細項統計
- [x] 2.3 Persist output counts for pre-testcase and testcase generation stages / 在 pre-testcase 與 testcase 階段落庫產出數量
- [x] 2.4 Ensure failed stage writes telemetry with failure status / 確保失敗階段仍寫入 telemetry 與失敗狀態
- [x] 2.5 Keep existing helper session API responses backward compatible / 確保既有 helper session API 回應契約不受 telemetry 導入影響

## 3. Analytics Aggregation and API / 統計彙總與 API

- [x] 3.1 Implement helper analytics aggregation service for account-ticket progress / 實作帳號-單號進度彙總服務
- [x] 3.2 Implement stage metrics aggregation (count/avg/p95/max + output totals) / 實作階段耗時與產量彙總（count/avg/p95/max）
- [x] 3.3 Implement fixed Google Vertex pricing calculator with 200K tier threshold for estimated cost / 實作固定 Google Vertex 價格計算器（200K 分段）以估算成本
- [x] 3.4 Implement admin endpoint `/api/admin/team_statistics/helper_ai_analytics` with team/date filters / 新增 helper analytics 管理端點與團隊/日期篩選
- [x] 3.5 Reuse existing admin permission and date-range guard in analytics endpoint / 重用既有 admin 權限檢查與日期區間驗證

## 4. Team Statistics Tab UI / 團隊統計頁籤前端

- [x] 4.1 Add `QA AI Agent - Test Case Helper` tab and pane in `team_statistics.html` / 在 `team_statistics.html` 新增 helper 專屬 tab 與內容區
- [x] 4.2 Add helper analytics loading/rendering pipeline in `team_statistics.js` / 在 `team_statistics.js` 新增 helper 統計載入與渲染流程
- [x] 4.3 Render account-ticket progress table with phase/status indicators / 呈現帳號-單號進度表與 phase/status 指示
- [x] 4.4 Render token usage and estimated cost summary with estimate disclaimer / 呈現 token 與估算費用摘要並標示 estimate
- [x] 4.5 Render stage duration/output metrics table or chart in helper tab / 呈現各階段耗時與產量表格或圖表
- [x] 4.6 Add zh-TW/zh-CN/en-US locale keys for helper analytics tab / 補齊 helper analytics tab 三語系文案

## 5. Tests and Verification / 測試與驗證

- [x] 5.1 Add unit tests for telemetry persistence on success and failure stages / 新增 telemetry 成功/失敗寫入單元測試
- [x] 5.2 Add aggregation tests for progress, stage metrics, and output counts / 新增進度、耗時、產量彙總測試
- [x] 5.3 Add cost estimation tests for tiered pricing calculation / 新增 tiered pricing 成本估算測試
- [x] 5.4 Add API tests for helper analytics endpoint filters and permission guards / 新增 helper analytics API 篩選與權限測試
- [x] 5.5 Add frontend tests for helper tab rendering and empty/error states / 新增 helper tab 渲染與空態/錯誤態前端測試
- [x] 5.6 Run targeted test suite and record verification notes for this change / 執行目標測試並記錄驗證結果
