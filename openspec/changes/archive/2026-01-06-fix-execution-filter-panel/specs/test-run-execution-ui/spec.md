## ADDED Requirements
### Requirement: Execution Filter Panel Toggle
系統 SHALL 在使用者啟用 executionFilterToggle 時顯示 Test Run Execution 的 filter panel，並提供狀態、案例編號、標題、優先級與執行者的篩選輸入。

#### Scenario: Toggle filter panel via click or keyboard
- **WHEN** 使用者點擊 executionFilterToggle 或按下 Enter/Space
- **THEN** filter panel 會顯示並可被操作

#### Scenario: Close filter panel
- **WHEN** 使用者點擊關閉按鈕、按下 Escape，或點擊 panel 外部
- **THEN** filter panel 會關閉且 toggle 狀態回到收合
