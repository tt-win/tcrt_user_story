## ADDED Requirements

### Requirement: Bulk Create Mode 支援 Test Data 欄位
Test Case Management 的 Bulk Create Mode（文字模式）SHALL 在說明文字、placeholder 與 sample 中描述可選的 test_data 欄位（CSV 第 8 欄 JSON 陣列）。使用者依格式貼上後，系統 SHALL 能解析並在預覽中顯示 Test Data 摘要，確認後送出 bulk create 請求。

#### Scenario: 使用者以文字模式帶入 Test Data
- **WHEN** 使用者在 Bulk Create Mode 貼上含第 8 欄合法 test_data JSON 的列並通過驗證
- **THEN** 預覽顯示該列的 Test Data 摘要，且確認後建立的案例含對應 Test Data

#### Scenario: 舊格式貼上仍可用
- **WHEN** 使用者僅貼上不含第 8 欄的既有 7 欄（或更少）格式
- **THEN** UI 不得強制要求 Test Data；流程與加入該欄位前相同

### Requirement: Bulk Create 說明標示 Export 不可整列貼回
Bulk Create 說明文案 SHALL 讓使用者理解：Test Case Set CSV Export 的整列格式與 Bulk Create 欄序不同，不可直接整列貼上；僅 test_data 儲存格的 JSON 形狀可對應第 8 欄。文案亦 SHALL 警告 test_data 可能含敏感 credential。

#### Scenario: 說明含格式與敏感資料提示
- **WHEN** 使用者開啟 Bulk Create Mode 對話框
- **THEN** 可見 test_data 欄位格式說明，以及敏感資料／不可整列 round-trip 的提示（透過 help 文案或同等 UI 提示）
