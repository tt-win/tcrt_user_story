# helper-session-management Specification

## Purpose
定義 QA Helper 的 session manager 介面與生命週期控制，支援恢復、刪除與清理既有 helper sessions。

## Requirements
### Requirement: Session Manager Entry in Helper Modal
系統 SHALL 在 helper modal 提供 session manager 入口。

#### Scenario: User opens session manager from helper modal
- **WHEN** 使用者在 helper modal 操作 session 管理入口
- **THEN** 系統開啟 session manager 檢視

### Requirement: Session Manager Split Layout with Ticket-Aware List
session manager SHALL 提供左右分割版面與帶 ticket / 時間資訊的 session 清單。

#### Scenario: Session list renders ticket and timestamp label
- **WHEN** session manager 載入 session 清單
- **THEN** 每筆 session 顯示 ticket 與時間標記

### Requirement: Resume Any Selected Session
系統 SHALL 允許使用者恢復任一選取的 session。

#### Scenario: Resume selected session and continue progress
- **WHEN** 使用者選擇某個 session 並執行 resume
- **THEN** helper 回到該 session 的目前進度

### Requirement: Batch Session Deletion
系統 SHALL 支援批次刪除多個 helper sessions。

#### Scenario: Delete selected sessions
- **WHEN** 使用者選取多筆 session 後執行刪除
- **THEN** 系統刪除所選 sessions 並更新清單

### Requirement: One-Click Session Cleanup
系統 SHALL 支援一鍵清除 helper sessions。

#### Scenario: Clear all sessions
- **WHEN** 使用者執行 clear all
- **THEN** 系統移除目前可清除的 sessions

### Requirement: Session Manager Close Restores Helper Modal
關閉 session manager SHALL 回到 helper 主要 modal，而非中斷整個 helper 體驗。

#### Scenario: Close manager and return to helper modal
- **WHEN** 使用者關閉 session manager
- **THEN** 系統回到 helper modal 主視圖
