## Why

目前 QA AI Agent - Test Case Helper 缺少跨帳號、跨 Ticket、跨階段的可視化統計，管理者無法即時掌握開發進度、token 消耗與估計成本，也難以定位流程瓶頸。需要在 Team 統計頁新增專屬分析視圖，讓營運與研發可以用同一套口徑追蹤效率與花費。

## Purpose

建立 Team-level 的 QA Helper analytics，提供 account/ticket/progress、token/cost、stage duration/output 三類核心指標，支援日常管理、成本預估與流程優化。

## What Changes

- 在團隊數據統計頁新增獨立 Tab：`QA AI Agent - Test Case Helper`。
- 新增帳號與 Ticket 維度統計：每位使用者正在處理/已完成哪些 JIRA 單號與當前階段進度。
- 新增 token 與 estimated cost 統計：整體與分帳號彙總，採用需求指定的 Google Vertex pricing table（含 200K tiered pricing）。
- 新增階段耗時與產出統計：分析、pre-testcase、testcase、commit 的耗時，與 pre-testcase/testcase 產出數量。
- 新增後端統計 API 與必要 telemetry 欄位，對齊既有 helper session lifecycle。

## Capabilities

### New Capabilities
- `helper-team-analytics`: Team 統計頁中的 QA Helper 專屬 tab、統計查詢 API、篩選與彙總指標呈現。

### Modified Capabilities
- `jira-ticket-to-test-case-poc`: 擴充 helper session/stage telemetry 與 token usage metadata，支援後續統計與成本估算。

## Requirements

### Requirement: Team analytics tab for QA Helper
- **GIVEN** 使用者具備團隊統計檢視權限
- **WHEN** 使用者開啟團隊數據統計並切換到 QA Helper tab
- **THEN** 系統顯示帳號-單號進度、token/cost、階段耗時與產出統計

### Requirement: Cost estimation with pricing tiers
- **GIVEN** helper 執行紀錄含 token usage
- **WHEN** 系統計算 estimated cost
- **THEN** 系統依模型對應的 tiered pricing 規則估算成本（如 input/output/cache read/write）
- **AND** 明確標示為 estimate（非實際扣費）

## Non-Functional Requirements

- 統計查詢在一般團隊資料量下應維持互動體驗（P95 < 2s）。
- 統計計算需 deterministic、可重現，且同一查詢條件下結果一致。
- 成本估算規則需可配置與可擴充，避免硬編碼特定模型價格。
- 新 UI 需遵循現有 TCRT style system 與 i18n 規範（zh-TW/zh-CN/en-US）。

## Impact

- Backend: helper session/stage telemetry aggregation service、team analytics API。
- Frontend: 團隊數據統計頁新增 QA Helper tab、圖表/表格與篩選互動。
- Data: helper 相關 usage/duration/output 指標欄位或衍生計算邏輯。
- Tests: API aggregation tests、cost estimation tests、frontend tab/render/filters tests。
