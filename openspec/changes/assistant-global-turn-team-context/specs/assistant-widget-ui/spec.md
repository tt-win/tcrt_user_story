## ADDED Requirements

### Requirement: Widget active conversation 不按 workspace team 分流

Assistant widget SHALL 使用單一 global localStorage key 記住 active conversation。建立、載入、近期對話與重新開啟流程 MUST NOT 以目前 workspace team id 選擇不同 conversation。

#### Scenario: 跨 team 導覽後重新開啟 widget

- **WHEN** 使用者在 ART 開啟 conversation，切到 CID 頁面、關閉再開啟 widget
- **THEN** widget 載入同一 global conversation

### Requirement: Send payload 不攜帶 workspace team

Widget 送出 global message MUST NOT 呼叫 workspace team helper來建立 routing 欄位，也 MUST NOT 附加 `context_team_id`。Team selection SHALL 完全由對話內 tool selector protocol處理。

#### Scenario: 任意頁面的 send payload 相同

- **WHEN** 相同使用者訊息分別從 global dashboard、ART 頁面與 CID 頁面送出
- **THEN** Assistant routing payload 不因頁面 team 不同而改變
