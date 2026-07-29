## 1. Super Admin workspace implementation

- [x] 1.1 將 System Overview 改為 compact KPI strip，並將 system main／side columns 改為固定摘要列加可填滿剩餘高度的 detail row。
- [x] 1.2 將 Scheduled Services 改為 canonical compact table、sticky header、跨列對齊欄位與 wrapper 內 responsive scroll。
- [x] 1.3 將 Provider 與 Attention 重組為保留獨立 section state 的 System Health card，並將管理 Quick Actions 改為等寬 icon-only compact rail。

## 2. Localization and verification

- [x] 2.1 補齊 System Health、排程服務欄位與 accessible controls 的 `en-US`、`zh-CN`、`zh-TW` 文案。
- [x] 2.2 新增 Super Admin renderer／CSS／component regression，覆蓋無 nested KPI cards、canonical service table、section isolation、icon-only actions 與 fixed workspace。
- [x] 2.3 執行 Dashboard pytest、component spec、Ruff、frontend lint、i18n、JS syntax、OpenSpec strict validation、Graphify update 與桌面／窄螢幕 browser QA。

## 3. Scheduled service correctness follow-up

- [x] 3.1 修正 Dashboard safe outcome mapping，使 `completed` 顯示成功、`interrupted` 顯示錯誤並納入 Attention。
- [x] 3.2 修正 Scheduled Services naive local timestamp 呈現，並補齊兩項已知服務與 outcome 的三語 allowlisted 文案。
- [x] 3.3 新增 API／frontend regression，執行 Dashboard pytest、Ruff、frontend lint、i18n、JS syntax、OpenSpec strict validation、Graphify update 與 browser QA。
