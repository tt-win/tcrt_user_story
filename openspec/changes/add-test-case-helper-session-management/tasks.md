## 1. Backend API and Contract / 後端 API 與契約

- [x] 1.1 Add session list endpoint and response models (`GET /teams/{team_id}/test-case-helper/sessions`) / 新增 session 清單端點與回應模型
- [x] 1.2 Add single delete endpoint for helper session (`DELETE /sessions/{session_id}`) / 新增單筆刪除 session 端點
- [x] 1.3 Add bulk delete and clear-all endpoints (`POST /sessions/bulk-delete`, `POST /sessions/clear`) / 新增批次刪除與一鍵清理端點
- [x] 1.4 Extend helper session response with timestamp-based display label field / 擴充 session 回應加入 timestamp 命名顯示欄位

## 2. Service Layer and Data Handling / 服務層與資料處理

- [x] 2.1 Implement list query with team scope, ordering, and limit/pagination guard / 實作團隊範圍查詢、排序與數量限制
- [x] 2.2 Implement deletion service methods for single, batch, and clear-all operations / 實作單筆、批次與清空刪除服務方法
- [x] 2.3 Ensure deleted sessions are no longer retrievable by get-session flow / 確保刪除後無法透過既有 get-session 流程回復
- [x] 2.4 Add audit log entries for batch delete and clear-all actions / 補齊批次刪除與一鍵清理審計紀錄

## 3. Helper Session Manager UI / 前端 Session 管理介面

- [x] 3.1 Add Session Manager entry button to helper modal footer (right of Start Over) / 在 helper footer 新增 Session 管理入口按鈕
- [x] 3.2 Build Session Manager modal partial with left-right split layout and ticket-aware list / 建立左右欄 session 管理 modal 與 ticket 清單
- [x] 3.3 Implement modal switching orchestration between helper modal and session manager modal / 實作 helper 與 session manager modal 切換狀態機
- [x] 3.4 Implement resume flow to reopen helper modal with selected session progress / 實作指定 session 回復並切回 helper modal
- [x] 3.5 Implement multi-select, batch delete, and one-click cleanup interactions with confirmations / 實作多選刪除與一鍵清理互動及確認流程

## 4. i18n and UX Consistency / 多語系與體驗一致性

- [x] 4.1 Add new locale keys for session manager actions and empty/error states (`zh-TW`, `zh-CN`, `en-US`) / 新增 session 管理相關三語系文案
- [x] 4.2 Align session manager visual tokens and spacing with helper style system / 對齊 helper 既有視覺 token 與間距規範
- [x] 4.3 Update session badge/text rendering to use timestamp naming instead of serial naming / 將 session 顯示名稱由流水號改為 timestamp

## 5. Tests and Verification / 測試與驗證

- [x] 5.1 Add API tests for list, resume-target retrieval, single delete, batch delete, and clear-all / 新增 API 測試覆蓋查詢與刪除流程
- [x] 5.2 Add frontend tests for modal switching, session resume, and manager-close restore behavior / 新增前端測試覆蓋 modal 切換與回復
- [x] 5.3 Add regression tests for timestamp label rendering and ticket key visibility in list / 新增 timestamp 命名與 ticket 顯示回歸測試
- [x] 5.4 Run targeted test suite and record verification notes in change context / 執行目標測試並記錄驗證結果

## Verification Notes / 驗證紀錄

- 2026-02-26: `PYTHONPATH=. pytest app/testsuite/test_jira_testcase_helper_frontend.py -q` -> `7 passed`
- 2026-02-26: `PYTHONPATH=. pytest app/testsuite/test_jira_testcase_helper_api.py app/testsuite/test_jira_testcase_helper_frontend.py -q` -> `11 passed`
