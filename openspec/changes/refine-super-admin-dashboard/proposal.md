## Why

Super Admin 首頁雖已與一般使用者分流，但仍保留大型 metric cards、分散的 provider／attention cards 與帶文字的大型快捷入口，資訊密度和固定工作區行為沒有跟上 Personal Dashboard 的後續收斂。系統管理者需要在不增加資料面或監控契約的前提下，更快掃描系統狀態與進入管理功能。

## What Changes

- 保留 Super Admin 專用、system-scoped 與 server-authoritative 的首頁，不加入個人 Resume、Assigned、Outcomes 或 Preferred Team。
- 將 System Overview 改為緊湊、同列且跨欄對齊的 KPI strip，減少巢狀 card 與垂直留白。
- 將 Scheduled Services 改為 canonical compact table，固定欄位呈現服務、最近執行、啟用／執行狀態與安全 outcome；表頭固定，超量內容只在 card body 內捲動。
- 修正 Scheduled Services 的既有資料語意：將 scheduler 的 `completed`／`interrupted` 狀態正規化為安全 outcome、維持排程管理頁的本機 wall-clock 時間語意，並以三語友善名稱呈現已知服務。
- 將 Provider configured 狀態與 Needs Attention 摘要整合為單一 System Health panel，但維持兩個來源各自的 ready／unavailable 降級與既有安全 allowlist。
- 將管理 Quick Actions 改為與 Personal Dashboard 一致的 icon-only、等寬填滿 rail，保留三語 accessible name 與 tooltip。
- 沿用固定 hero、固定 viewport workspace、section 內捲動與 responsive 密度；窄螢幕只在 dashboard region／table wrapper 內捲動，AI Assistant FAB 維持 overlay。
- 不擴張 Dashboard API 的敏感資料面、權限或 provider health 語意，也不改變資料庫 schema 或 migration；不新增 Jira。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `system-administration-dashboard`: 收斂 Super Admin 首頁的資訊密度、排程服務表格、系統狀態整合、icon-only 管理入口與響應式固定工作區契約。

## Impact

- 前端：`app/static/js/index.js`、`app/static/css/index.css`、三語 locale。
- 後端：`app/services/dashboard_service.py` 的既有 safe outcome projection。
- 測試：Dashboard frontend/component regression 與 responsive browser QA。
- 後端與資料：沿用既有 `GET /api/dashboard` safe projection，無 API、schema、migration 或外部依賴變更。
