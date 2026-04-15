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
