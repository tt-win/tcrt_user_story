## ADDED Requirements

### Requirement: Screen 2 MUST provide an edit mode toggle for ticket markdown
系統 SHALL 在 screen 2 提供「編輯」按鈕，讓使用者切換至 textarea 編輯模式。

#### Scenario: User enters edit mode from read-only preview
- **WHEN** 使用者在 screen 2 點擊「編輯」按鈕
- **THEN** Markdown 預覽區域切換為可編輯的 textarea，顯示 raw markdown 原文

#### Scenario: User exits edit mode without reparse
- **WHEN** 使用者在編輯模式中點擊「取消編輯」按鈕
- **THEN** textarea 內容被捨棄，回到原本的 Markdown 預覽顯示

### Requirement: Screen 2 MUST allow user to reparse edited markdown
系統 SHALL 在編輯模式中提供「重新解析」按鈕，將使用者修改後的 markdown 送交後端重新執行 deterministic parser 與格式驗證，直接更新既有的 ticket_snapshot。

#### Scenario: User triggers reparse after editing
- **WHEN** 使用者在編輯模式中修改 markdown 後點擊「重新解析」
- **THEN** 系統將修改後的 markdown 送至後端 reparse 端點，直接更新既有 ticket_snapshot 的 `raw_ticket_markdown`、`structured_requirement` 與 `validation_summary`，並重新渲染 screen 2 確認畫面

#### Scenario: Reparse result updates validation summary
- **WHEN** 後端 reparse 完成
- **THEN** screen 2 右側的格式檢查結果即時更新，反映新的 errors、warnings 與 stats

#### Scenario: Reparse with invalid markdown shows validation errors
- **WHEN** 使用者編修的 markdown 不符合 parser 預期格式
- **THEN** validation_summary 顯示對應的錯誤，「需求驗證項目分類與填充」按鈕保持 disabled

### Requirement: Screen 2 MUST provide reload-from-JIRA functionality
系統 SHALL 在 screen 2 提供「重新載入需求單」按鈕，從 JIRA 重新抓取最新的 ticket 內容。

#### Scenario: User reloads ticket from JIRA
- **WHEN** 使用者點擊「重新載入需求單」按鈕
- **THEN** 系統從 JIRA 重新抓取 ticket 內容，覆蓋目前的 raw_ticket_markdown，重新解析並更新 validation_summary

#### Scenario: Reload overwrites manual edits
- **WHEN** 使用者已手動編修 markdown 後點擊「重新載入需求單」
- **THEN** JIRA 最新內容覆蓋手動編修的內容，structured_requirement 與 validation_summary 以 JIRA 原始內容重新計算

### Requirement: System MUST warn before reload when unsaved edits exist
系統 SHALL 在偵測到使用者有未重新解析的手動編修時，於重新載入前顯示確認提示。

#### Scenario: Dirty state triggers confirmation before reload
- **WHEN** 使用者修改了 markdown 但尚未重新解析，且點擊「重新載入需求單」
- **THEN** 系統顯示確認 dialog 警告即將覆蓋手動編修的內容
- **AND** 使用者確認後才執行重新載入；取消則保留目前內容

#### Scenario: No warning when no edits were made
- **WHEN** 使用者未修改 markdown 即點擊「重新載入需求單」
- **THEN** 系統直接執行重新載入，不顯示確認 dialog

### Requirement: Backend MUST provide reparse endpoint
系統 SHALL 提供 `POST /sessions/{session_id}/ticket/reparse` API 端點，接收使用者編修後的 markdown，直接更新既有 ticket_snapshot 記錄。

#### Scenario: Reparse endpoint processes user-edited markdown
- **WHEN** 前端發送 reparse 請求，payload 包含 `raw_ticket_markdown` 字串
- **THEN** 後端以該 markdown 重新執行 deterministic parser 與 `validate_preclean_output`
- **AND** 直接更新既有 ticket_snapshot 的 `raw_ticket_markdown`、`structured_requirement`、`validation_summary`
- **AND** 回傳更新後的 workspace
