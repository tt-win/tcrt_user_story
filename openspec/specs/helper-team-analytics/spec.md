# helper-team-analytics Specification

## Purpose
定義團隊統計頁中的 QA AI Helper analytics 能力，讓管理者可查詢 helper 使用、token、成本與階段輸出等指標。

## Requirements
### Requirement: Team statistics page SHALL provide QA Helper analytics tab
系統 SHALL 在團隊統計頁提供 QA Helper analytics 分頁。

#### Scenario: Open helper analytics tab in team statistics
- **WHEN** 使用者開啟團隊統計頁的 helper analytics 分頁
- **THEN** 系統載入對應的 QA Helper 統計內容

### Requirement: System SHALL show account-ticket progress for helper sessions
系統 SHALL 顯示帳號與 ticket 維度的 helper session 進度資訊。

#### Scenario: Render account-ticket progress list
- **WHEN** 使用者查詢 helper analytics
- **THEN** 頁面顯示 account-ticket 進度列表與對應狀態

### Requirement: System SHALL provide token usage and estimated cost summary
系統 SHALL 依既定費率顯示 token 使用量與估算成本摘要。

#### Scenario: Calculate estimated cost from token usage
- **WHEN** helper telemetry 含有 token 使用資料
- **THEN** 系統計算並顯示估算成本

#### Scenario: Display estimate disclaimer
- **WHEN** 頁面呈現成本資訊
- **THEN** 需清楚標示為 estimate

### Requirement: System SHALL provide stage duration and output metrics
系統 SHALL 提供各 helper stage 的耗時與輸出量指標。

#### Scenario: Show stage metrics for analysis and generation outcomes
- **WHEN** stage telemetry 可用
- **THEN** 頁面顯示階段耗時、輸出數量與相關彙整

### Requirement: System SHALL expose helper analytics through admin statistics API
系統 SHALL 透過 admin / statistics API 提供 helper analytics 查詢。

#### Scenario: Query helper analytics API with range filters
- **WHEN** 後端收到帶有時間區間等條件的查詢
- **THEN** 回應對應的 helper 統計資料集
