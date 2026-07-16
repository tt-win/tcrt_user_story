## ADDED Requirements

### Requirement: V3 helper analytics dashboard SHALL remain available after legacy retirement
系統 SHALL 保留現行 V3 QA AI Helper dashboard 與 `/qa-ai-helper/*` 資料 API，同時 SHALL NOT 暴露 legacy `helper-ai-*` DOM marker、舊 `helper_ai_analytics` 載入管線或舊 tab translation key。

#### Scenario: Administrator opens team statistics after legacy retirement
- **WHEN** 具權限管理員開啟團隊統計頁
- **THEN** 頁面仍提供 `qa-ai-helper-tab` 與 `qa-ai-helper-pane` 的 V3 dashboard
- **AND** template 與 JavaScript 不含 legacy `helper-ai-*` sections 或 `helper_ai_analytics` pipeline

#### Scenario: V3 helper tab label is translated
- **WHEN** 使用者以任一受支援語系開啟團隊統計頁
- **THEN** V3 tab 使用非 legacy 的專用 i18n key
- **AND** 三個 locale 都提供該 key

### Requirement: Legacy helper analytics endpoint SHALL expose an authenticated retirement response
系統 SHALL 保留 legacy helper analytics endpoint 的最小相容 tombstone：先執行既有管理員權限檢查，再對授權管理員回傳可辨識的 `410 Gone`，且 SHALL NOT 查詢或重建已退役的 analytics 資料管線。

#### Scenario: Authorized administrator calls retired endpoint
- **WHEN** 具管理員權限的使用者查詢 legacy helper analytics endpoint
- **THEN** 系統回傳 HTTP `410 Gone`
- **AND** response detail 含穩定的 `legacy_helper_statistics_retired` error code 與遷移說明

#### Scenario: Unauthorized user calls retired endpoint
- **WHEN** 不具所需管理員權限的使用者查詢 legacy helper analytics endpoint
- **THEN** 系統回傳 HTTP `403 Forbidden`
- **AND** 不洩漏退役端點的內部資料或歷史統計

## REMOVED Requirements

### Requirement: Team statistics page SHALL provide QA Helper analytics tab
**Reason**: Legacy Helper analytics UI 已由 V3 rollout 退役，保留入口會呈現無法維護或不再代表現況的統計。

**Migration**: 由既有 V3 `qa-ai-helper-tab`／`qa-ai-helper-pane` 接替；移除或更名 legacy marker、舊載入流程與舊 tab translation key，不刪除 V3 dashboard。

### Requirement: System SHALL show account-ticket progress for helper sessions
**Reason**: 此畫面依賴已退役的 legacy analytics pipeline。

**Migration**: 不再於團隊統計頁顯示 account-ticket helper progress；既有資料不刪除，無 schema migration。

### Requirement: System SHALL provide token usage and estimated cost summary
**Reason**: Legacy token/cost 彙整不再是受支援的團隊統計能力。

**Migration**: 移除前端摘要與 estimate disclaimer；既有 telemetry 資料不搬移。

### Requirement: System SHALL provide stage duration and output metrics
**Reason**: Legacy stage metrics UI 與資料載入流程一併退役。

**Migration**: 移除對應 DOM 與 JavaScript renderer，不建立替代 endpoint。

### Requirement: System SHALL expose helper analytics through admin statistics API
**Reason**: Analytics payload API 已退役，不能以一般 `404` 讓舊 client 無法區分路徑錯誤與功能下線。

**Migration**: 以本 delta 新增的 authenticated `410 Gone` tombstone 取代資料 payload；client 應停止呼叫此 endpoint。
