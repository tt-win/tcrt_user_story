## ADDED Requirements

### Requirement: System Administration Dashboard SHALL be exclusive to Super Admin

System Administration Dashboard MUST 只在 server-authoritative Dashboard dispatch 判定 current user 為 `SUPER_ADMIN` 時存在。它 MUST 是 system-scoped entry，不得載入、查詢或渲染 Personal Dashboard 的 resume、assigned、成果或 preferred Team 資料。`ADMIN` 雖有管理能力，但 MUST 仍取得 Personal Dashboard。

#### Scenario: Admin 不會誤入 Super Admin 首頁

- **WHEN** `ADMIN` 以有效 token 請求 Dashboard
- **THEN** 系統回傳 Personal Dashboard，且 body 不含 system administration summary

#### Scenario: Super Admin 首頁不混入個人工作佇列

- **WHEN** `SUPER_ADMIN` 以有效 token 請求 Dashboard，且其帳號也有 Test Run 指派項目
- **THEN** 系統只回傳 System Administration Dashboard 資料，不查詢或呈現其個人 assigned／resume section

### Requirement: System summary MUST use a fixed safe allowlist and independent section status

System Administration Dashboard SHALL 只提供固定 allowlist 的摘要：安全統計／availability、scheduled service 的 enabled/running/timestamp/outcome code、CI／Result provider configured boolean、注意事件的 count/timestamp，以及 server allowlisted management links。每個資料來源 MUST 獨立回傳 `ready` 或 `unavailable`，失敗不得阻斷其他摘要或使 endpoint 回傳內部 exception。

Dashboard MUST NOT 回傳 credential、token、provider config、connection probe 結果、URL、host、完整 runtime setting、raw system-log message、scheduled-service `last_error`／`last_run_message`、Audit `details`／`action_brief`、IP、User-Agent 或任何原始 exception。Provider 狀態僅能表示 configured／not configured，不得宣稱連線健康。

#### Scenario: 已設定 provider 只顯示設定狀態

- **WHEN** Super Admin 系統中存在 active CI 或 Result provider
- **THEN** Dashboard 最多顯示對應 slot 為 configured，且 response 不含 provider 名稱、endpoint、config 或 credential 資料

#### Scenario: 排程服務錯誤訊息不出現在首頁

- **WHEN** scheduled service 有 `last_error` 或 `last_run_message`
- **THEN** Dashboard 只可顯示 allowlisted status／timestamp／outcome code，response 與畫面都不含原始訊息

#### Scenario: 任一系統來源失敗不外洩也不阻斷首頁

- **WHEN** 其中一個系統摘要來源失敗
- **THEN** 該 section 回傳 `unavailable` 與 generic i18n state，其他安全 section 繼續回傳，且 HTTP body 不含 stack trace 或設定值

### Requirement: System Dashboard navigation and presentation SHALL preserve system scope

System Administration Dashboard MUST 顯示 system scope，而非將 `currentTeam`／偏好 Team 當作頁面篩選器。管理捷徑 MUST 由 server fixed allowlist 產生，且目標既有 route/API 仍 MUST 各自重新執行授權。Dashboard 本身不是管理權限，也不是 system health check。它 MUST 保留既有右下角全域 AI Assistant FAB 的 overlay 行為，不為 FAB 保留空白軌道。

所有使用者可見文案 MUST 提供 `en-US`、`zh-CN`、`zh-TW`；動態統計、code 與 link label MUST 以固定 allowlist／安全文字渲染。

#### Scenario: 快捷入口不繞過既有授權

- **WHEN** Super Admin 從 Dashboard 點選組織設定、系統日誌或稽核日誌入口
- **THEN** 目標 route/API 仍以既有授權流程驗證請求，Dashboard link 不攜帶可繞過授權的 credential 或 scope

#### Scenario: Assistant FAB 可覆蓋系統首頁內容

- **WHEN** Super Admin 開啟 System Administration Dashboard
- **THEN** 全域 AI Assistant 依既有 availability 規則顯示於右下角並可覆蓋內容，Dashboard 不新增 reserved safe area
