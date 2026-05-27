# helper-guided-intake Specification

## Purpose
定義 QA AI Agent 前兩個畫面的 guided intake：ticket 載入、session 建立、重新開始與只讀 ticket 檢視。

## Requirements
### Requirement: Ticket input screen MUST remain sessionless until submission
screen 1 SHALL 在送出 ticket 前保持 sessionless。

#### Scenario: Entry button opens screen 1 without a session
- **WHEN** 使用者打開 QA AI Agent
- **THEN** 進入 screen 1 時尚未建立 session

### Requirement: Ticket submission MUST create a new helper session
送出 ticket 後 SHALL 建立新的 helper session。

#### Scenario: Submitting a ticket creates a session
- **WHEN** 使用者在 screen 1 送出 ticket
- **THEN** 系統建立新 session 並進入下一畫面

### Requirement: Restart MUST clear the current in-progress session before the next submission
重新開始 SHALL 清除尚未完成的 in-progress session。

#### Scenario: Restart clears the unfinished session and returns to screen 1
- **WHEN** 使用者在流程中選擇 restart
- **THEN** 系統清除當前未完成 session 並回到 screen 1

#### Scenario: Completed session is not destructively restarted from screen 7
- **WHEN** 使用者已到完成畫面
- **THEN** 系統不以 destructive 方式重啟已完成 session

### Requirement: Screen 2 MUST render read-only ticket markdown
screen 2 SHALL 預設以唯讀方式呈現 ticket markdown，但使用者可切換至編輯模式修改內容。唯讀預覽仍為預設檢視模式。

#### Scenario: Jira content is shown in read-only preview by default
- **WHEN** 使用者在 screen 2 檢視 ticket
- **THEN** 內容預設以 rendered Markdown 預覽呈現，不可直接 inline 編輯

#### Scenario: User can switch to edit mode
- **WHEN** 使用者點擊「編輯」按鈕
- **THEN** 預覽區域切換為 textarea 編輯模式，使用者可修改 raw markdown 內容

### Requirement: Guided intake parser MUST prepare downstream structured data
guided intake parser SHALL 在 ticket 載入後準備後續結構化資料。

#### Scenario: Parser output is prepared after ticket load
- **WHEN** ticket 成功載入
- **THEN** 系統產出後續規劃與驗證所需的結構化 payload

### Requirement: VERIFICATION_PLANNING initialization MUST support AI-populated data import
VERIFICATION_PLANNING 畫面初始化 SHALL 支援從 MAGI inspection 結果匯入 AI 產生的 PlanSection / VerificationItem / CheckCondition 資料。

#### Scenario: AI inspection result populates VERIFICATION_PLANNING on entry
- **WHEN** MAGI inspection 流程成功完成且使用者進入 VERIFICATION_PLANNING
- **THEN** 畫面自動載入 AI 產生的 sections、verification items 與 check conditions

#### Scenario: AI-populated data merges with existing deterministic sections
- **WHEN** 系統同時有 deterministic planner 與 AI inspection 的輸出
- **THEN** AI inspection 結果作為 verification items 的主要來源，deterministic planner 的 section 結構作為骨架，兩者合併呈現


### Requirement: Ticket fetch MUST support optional comment inclusion
**Reason**: The revised screen-1 flow only asks for `Ticket Number`; comment-fetch toggles are no longer part of the primary journey.
**Migration**: If comment support is needed later, it should be added as a separate optional extension without changing the session-creation rule.

### Requirement: Guided intake MUST support multilingual raw source resolution
**Reason**: The new intake flow focuses on a single read-only ticket confirmation step and does not ask the user to resolve multilingual source blocks before planning.
**Migration**: Keep parser normalization compatible with current ticket formats, but do not surface a multilingual source-resolution workflow in the new helper.

