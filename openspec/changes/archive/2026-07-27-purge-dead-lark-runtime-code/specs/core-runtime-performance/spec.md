## MODIFIED Requirements

### Requirement: 請求處理不得在事件迴圈上執行阻塞式網路或 IO

系統 SHALL 確保任何 `async` 請求處理路徑上的出站網路呼叫與檔案串流不阻塞事件迴圈。對既有同步用戶端（組織層 Lark 出站呼叫，如人員／部門同步、群組通知、使用者查詢）SHALL 以背景執行緒（`asyncio.to_thread`）或非同步用戶端（`httpx.AsyncClient`）執行；重試等待 SHALL 不在事件迴圈上同步休眠。附件下載代理已無外部代理路徑（僅本機檔案串流），其不阻塞要求由檔案串流部分涵蓋。

#### Scenario: 附件傳輸期間不阻塞其他請求
- **WHEN** 一個附件下載請求正在從本機串流資料
- **THEN** 其他並發請求仍可被事件迴圈服務，不被該傳輸阻塞

#### Scenario: 出站 Lark 呼叫不阻塞事件迴圈
- **WHEN** 請求處理過程中發出組織層 Lark 出站呼叫
- **THEN** 該呼叫不在事件迴圈執行緒上同步阻塞
- **AND** Lark 重試等待期間事件迴圈仍可服務其他請求

#### Scenario: async 路徑無同步網路殘留
- **WHEN** 檢視 `async` 請求處理路徑
- **THEN** SHALL NOT 存在未經離載的同步出站網路呼叫
