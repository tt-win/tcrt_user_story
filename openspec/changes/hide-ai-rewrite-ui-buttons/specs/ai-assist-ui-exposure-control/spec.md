# ai-assist-ui-exposure-control Specification

## Purpose
定義 AI assist 的 UI 可見性治理規則，讓產品可在「能力保留」與「入口關閉」之間安全切換。Define governance for AI assist UI exposure while preserving service capability.

## ADDED Requirements

### Requirement: Default hidden AI rewrite entry
The system SHALL keep AI rewrite entry controls hidden by default in end-user test case editing UI.

#### Scenario: Default page render hides entry controls
- **WHEN** 使用者首次載入 Test Case 編輯頁 / user loads test case editor page
- **THEN** 不顯示 AI rewrite 入口按鈕或等效可見 action

### Requirement: Capability retention under hidden mode
When UI exposure is hidden, the system SHALL keep AI assist backend endpoint and core prompt processing logic available.

#### Scenario: Hidden mode does not delete backend flow
- **WHEN** 系統以 hidden mode 運作 / system runs in hidden mode
- **THEN** 後端 AI assist route 與處理邏輯仍存在且可被內部驗證流程使用

### Requirement: Frontend-only re-enable path
The system SHALL support re-enabling AI rewrite visibility through frontend assets without requiring database migrations.

#### Scenario: Re-enable planning confirms no schema change
- **WHEN** 團隊規劃重新開放 UI 入口 / team plans re-enable
- **THEN** 方案僅需前端模板與腳本調整，且不涉及 DB schema migration
