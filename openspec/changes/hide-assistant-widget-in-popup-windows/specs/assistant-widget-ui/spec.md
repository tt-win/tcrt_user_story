## MODIFIED Requirements

### Requirement: 全頁懸浮入口與可見性 gating
系統 SHALL 在所有已登入頁面右下角提供懸浮圖標（FAB），點擊開關聊天面板。widget SHALL 由前端 JS 注入，並以 `GET /api/assistant/availability` 判斷是否顯示（合併「功能已設定啟用」與「使用者可用」）；判斷 MUST fail-closed（API 錯誤即不顯示），未登入頁面 MUST NOT 顯示，登出事件 SHALL 即時移除 widget。以 `window.open` 開啟、只服務單一任務的彈出視窗（參考測試案例視窗、minimal/editor 模式的 Test Case 編輯器視窗）MUST NOT 注入 widget；該判斷 SHALL 早於 availability 查詢，命中時不注入任何 widget DOM，也不發出 availability 請求。彈窗判斷的權威來源 SHALL 是伺服器渲染於 `<body>` 的旗標，前端 MAY 另以 `minimal` / `editor` query 容錯，主視窗頁面 MUST 不受影響。

#### Scenario: 停用時完全不顯示
- **WHEN** assistant 未設定或 availability API 失敗
- **THEN** 頁面不注入任何 widget DOM

#### Scenario: 單一任務彈出視窗不出現助手入口
- **WHEN** 使用者由主視窗開啟參考測試案例彈窗或 minimal/editor 模式的 Test Case 編輯器彈窗
- **THEN** 該彈窗不注入 FAB 與面板 DOM、不呼叫 availability API，主視窗的 widget 與其進行中的對話不受影響
