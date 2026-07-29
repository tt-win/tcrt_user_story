## ADDED Requirements

### Requirement: System Administration Dashboard SHALL use a high-density fixed workspace

System Administration Dashboard MUST 在既有固定 hero 下使用受控高度的 system workspace。桌面版 MUST 將 System Overview 顯示為單層、同列且等寬的 KPI strip，不得為每個 KPI 建立 nested card；Scheduled Services MUST 取得主要剩餘高度並以 canonical compact table 顯示服務、最近執行、啟用／執行狀態與安全 outcome。card header MUST 保持可見，超量資料只能在 card body 或 table wrapper 內捲動，不能撐高 document。

System Quick Actions MUST 使用 icon-only、等寬填滿的 compact action rail；每個 action MUST 保留 localized `aria-label`、tooltip 與 keyboard focus，不得因移除可見文字而失去可存取名稱。窄螢幕 MUST 只讓 hero 下方 dashboard region 與必要的 table wrapper 捲動，AI Assistant FAB 仍可 overlay 且不預留空白。

#### Scenario: 桌面摘要使用單列 KPI strip

- **WHEN** Super Admin 以桌面寬度開啟 System Administration Dashboard
- **THEN** active Teams、active Users、active Test Runs 在同一個 Overview card 內以三個等寬 metric cell 顯示，且沒有三張 nested metric cards

#### Scenario: 排程服務欄位跨列對齊

- **WHEN** Scheduled Services section 回傳多筆資料
- **THEN** 畫面以欄位標頭只出現一次的 compact table 顯示服務、最近執行、狀態與結果，每筆服務只佔一列，超量資料只在該 card 內捲動

#### Scenario: 管理入口以可存取的 icon rail 呈現

- **WHEN** server 回傳多個 allowlisted management shortcuts
- **THEN** Quick Actions 以等寬 icon-only 按鈕填滿 rail，每個按鈕都有目前語系的 accessible name 與 tooltip，且不設定 Team context

#### Scenario: 長內容不造成 document scroll

- **WHEN** 排程服務達到 server-defined 上限且 viewport 高度有限
- **THEN** hero 與 card header 維持可見，服務只在 section 內捲動，Dashboard 內容不造成 browser document 垂直捲軸

### Requirement: System health presentation MUST preserve independent safe section states

System Administration Dashboard SHALL 將 Attention count／latest timestamp、CI Provider configured 與 Result Provider configured 整合於單一 System Health presentation card，但 MUST 保留 `attention` 與 `providers` 兩個 response section 的獨立 `ready`／`unavailable` 處理。任一來源失敗 MUST 只顯示該 group 的 generic localized state，另一 group 仍須顯示；configured 只能表示已設定，不得被描述為連線健康。System Health MUST NOT 顯示 provider 名稱、URL、credential、raw error 或 scheduled-service message。

#### Scenario: Provider unavailable 不遮蔽 Attention

- **WHEN** providers section 為 `unavailable` 且 attention section 為 `ready`
- **THEN** System Health 在 Provider group 顯示 generic unavailable state，並繼續顯示安全的 Attention count 與 latest timestamp

#### Scenario: Attention unavailable 不遮蔽 Provider

- **WHEN** attention section 為 `unavailable` 且 providers section 為 `ready`
- **THEN** System Health 在 Attention group 顯示 generic unavailable state，並繼續顯示 CI／Result configured badges

#### Scenario: 整合狀態卡不擴張資料面

- **WHEN** Super Admin 檢視 System Health
- **THEN** 畫面只使用既有 allowlisted count、timestamp 與 configured boolean，不顯示任何 provider detail、connection probe 或原始錯誤

### Requirement: Scheduled service summary MUST preserve scheduler semantics

System Administration Dashboard MUST 將 scheduler persistence status 正規化為安全 outcome：`completed` MUST 呈現為成功，`interrupted` MUST 呈現為錯誤並納入 Attention，且未知值 MUST 降級為 generic unknown。Scheduled Services 的 naive timestamp MUST 沿用排程管理頁的 local wall-clock 語意，不得因假設為 UTC 而產生額外時區位移。已知服務 MUST 以三語 allowlisted 友善名稱呈現；未知服務 MAY fallback 至安全 `service_key`，但 MUST NOT 暴露資料庫 `display_name`、message 或 raw error。

#### Scenario: 成功排程顯示成功結果

- **WHEN** scheduler 紀錄的 `last_run_status` 為 `completed`
- **THEN** Dashboard API 回傳安全 outcome `success`，畫面以目前語系的成功 badge 呈現而不是 `unknown`

#### Scenario: 中斷排程列入需要注意

- **WHEN** scheduler 紀錄的 `last_run_status` 為 `interrupted`
- **THEN** Dashboard API 回傳安全 outcome `error`，且 Attention count 與 latest timestamp 包含該服務

#### Scenario: 本機排程時間不產生額外位移

- **WHEN** Scheduled Services 收到沒有 timezone offset 的 scheduler local timestamp
- **THEN** Dashboard 使用與排程管理頁一致的 local wall-clock parse path 呈現，不得將該值先視為 UTC 再轉換

#### Scenario: 已知服務顯示本地化名稱

- **WHEN** `service_key` 為 `lark_org_sync` 或 `audit_cleanup`
- **THEN** Dashboard 顯示目前語系的 allowlisted 友善名稱，並保留原始 key 作為非主要識別資訊且不讀取資料庫 `display_name`
