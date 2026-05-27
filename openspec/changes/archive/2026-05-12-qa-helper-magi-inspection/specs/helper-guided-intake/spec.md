## MODIFIED Requirements

### Requirement: Guided intake parser MUST prepare downstream structured data
guided intake parser SHALL 在 ticket 載入後準備後續結構化資料。Ticket 確認完成後，系統 SHALL 提供「AI 產生驗證項目」的觸發選項，讓使用者選擇啟動 MAGI inspection 流程或直接手動填寫。

#### Scenario: Parser output is prepared after ticket load
- **WHEN** ticket 成功載入
- **THEN** 系統產出後續規劃與驗證所需的結構化 payload

#### Scenario: AI inspection trigger is offered after ticket confirmation
- **WHEN** 使用者在 TICKET_CONFIRMATION 畫面確認需求內容
- **THEN** 系統提供「AI 產生驗證項目」按鈕，使用者可選擇啟動 MAGI inspection 或跳過直接進入手動 VERIFICATION_PLANNING

#### Scenario: Skipping AI inspection enters empty VERIFICATION_PLANNING
- **WHEN** 使用者選擇跳過 AI inspection
- **THEN** 系統進入 VERIFICATION_PLANNING 畫面，verification items 為空，使用者需手動填寫

## ADDED Requirements

### Requirement: VERIFICATION_PLANNING initialization MUST support AI-populated data import
VERIFICATION_PLANNING 畫面初始化 SHALL 支援從 MAGI inspection 結果匯入 AI 產生的 PlanSection / VerificationItem / CheckCondition 資料。

#### Scenario: AI inspection result populates VERIFICATION_PLANNING on entry
- **WHEN** MAGI inspection 流程成功完成且使用者進入 VERIFICATION_PLANNING
- **THEN** 畫面自動載入 AI 產生的 sections、verification items 與 check conditions

#### Scenario: AI-populated data merges with existing deterministic sections
- **WHEN** 系統同時有 deterministic planner 與 AI inspection 的輸出
- **THEN** AI inspection 結果作為 verification items 的主要來源，deterministic planner 的 section 結構作為骨架，兩者合併呈現
