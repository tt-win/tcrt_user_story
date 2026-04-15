## MODIFIED Requirements

### Requirement: Screen 2 MUST render read-only ticket markdown
screen 2 SHALL 預設以唯讀方式呈現 ticket markdown，但使用者可切換至編輯模式修改內容。唯讀預覽仍為預設檢視模式。

#### Scenario: Jira content is shown in read-only preview by default
- **WHEN** 使用者在 screen 2 檢視 ticket
- **THEN** 內容預設以 rendered Markdown 預覽呈現，不可直接 inline 編輯

#### Scenario: User can switch to edit mode
- **WHEN** 使用者點擊「編輯」按鈕
- **THEN** 預覽區域切換為 textarea 編輯模式，使用者可修改 raw markdown 內容
