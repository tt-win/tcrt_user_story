## Context

QA AI Helper 的 screen 2（需求單內容確認）目前以唯讀方式呈現 JIRA ticket 的 Markdown 內容。使用者只能觀看並決定是否繼續至下一步。若需求單內容有誤或不完整，使用者必須回到 JIRA 修改後重新載入，打斷了產生 Test Case 的連續流程。

現有架構中：
- `renderTicketConfirmation()` 將 `raw_ticket_markdown` 渲染為 HTML 後直接顯示於 `#qaHelperTicketMarkdown`
- 後端已有 `POST /sessions/{session_id}/ticket`（`fetch_ticket`）支援在既有 session 上重新從 JIRA 抓取內容
- `validation_summary.is_valid` 控制是否允許進入下一步（`proceedBtn.disabled`）
- 下游已有 canonical revision 的編輯概念，但 screen 2 的 raw markdown 層目前無編輯入口

## Goals / Non-Goals

**Goals:**
- 讓使用者在 screen 2 可直接編輯需求 Markdown 原文
- 編輯後可觸發重新解析（reparse），直接更新既有 ticket_snapshot 的 structured_requirement 與 validation_summary
- 提供從 JIRA 重新載入（reload）功能，覆蓋目前內容
- 透過 dirty state 管理防止使用者意外覆蓋已編輯的內容

**Non-Goals:**
- 不改變 screen 2 的整體版面結構（仍維持左 8 右 4 的 layout）
- 不提供結構化欄位逐一編輯的 UI（例如分別編輯 User Story、Criteria）；使用者直接編修完整 Markdown
- 不影響 screen 3 以後的流程（downstream 的 canonical revision、plan 等維持不變）
- 不新增資料庫欄位；reparse 直接更新既有的 ticket_snapshot 記錄
- 不在此變更中處理多人同時編輯或衝突合併

## Decisions

### 1. 使用 CodeMirror 或 Textarea 作為編輯元件

**選擇：Textarea（附 monospace 字型 + 自動高度調整）**

理由：
- 專案前端目前無 build 流程、無 Node 依賴，引入 CodeMirror 需額外 CDN 載入與初始化邏輯
- 編輯場景為中短篇幅的 Markdown，不需要語法高亮或自動補全
- Textarea 更輕量，與既有 TCRT 風格一致
- 替代方案：CodeMirror via CDN — 提供更好的編輯體驗，但增加前端複雜度且對此場景過度設計

### 2. 編輯模式的啟動方式

**選擇：預設以 rendered Markdown 預覽呈現，提供「編輯」按鈕切換至 textarea 編輯模式**

理由：
- 保留現有唯讀預覽體驗作為預設，減少使用者認知負擔
- 多數情況使用者不需編輯，僅需確認即可
- 明確的模式切換避免使用者誤觸改動
- 替代方案：預設即為 split-pane 編輯+預覽 — 佔用過多版面且對不需編輯的使用者是多餘的

### 3. 重新解析（Reparse）的觸發機制

**選擇：使用者手動點擊「重新解析」按鈕觸發**

理由：
- 解析需呼叫後端 API，每次輸入即觸發會產生大量無謂請求
- 手動觸發讓使用者確認編輯完成後再執行解析，降低後端負載
- 後端 reparse API 接收完整 markdown，重新執行 deterministic parser 與 validation，直接更新既有 ticket_snapshot
- 替代方案：Auto-save + debounce — 體驗略佳但需處理中間狀態與 inflight cancel 邏輯

### 4. 重新載入（Reload from JIRA）與 dirty state 防護

**選擇：重新載入前若有未解析的手動編輯，先顯示確認 dialog**

理由：
- 避免使用者辛苦編輯的內容被意外覆蓋
- 確認 dialog 使用 Browser confirm()，保持簡單
- Dirty state 在前端以 JavaScript 變數追蹤（類似既有 `planDirty` 模式）

### 5. 後端 Reparse 端點設計

**選擇：新增 `POST /sessions/{session_id}/ticket/reparse` 端點**

理由：
- 與既有 `POST /sessions/{session_id}/ticket`（reload from JIRA）語意分離
- Reparse 接收使用者編修的 markdown，後端重新執行 deterministic parser + validation
- 直接更新既有 ticket_snapshot 的 `raw_ticket_markdown`、`structured_requirement`、`validation_summary`，不新增任何欄位
- 回傳更新後的 workspace

## Risks / Trade-offs

- **[Risk] 使用者編輯後的 Markdown 可能不符合 deterministic parser 預期格式** → Mitigation: Reparse 後的 validation_summary 會明確顯示錯誤，使用者可繼續修正或 reload 原始內容
- **[Risk] 前端 textarea 在長文件時可能效能不佳** → Mitigation: JIRA ticket description 通常在中等篇幅（< 500 行），textarea 可勝任
- **[Trade-off] 與 canonical revision 的編輯概念部分重疊** → 兩者作用於不同層級：screen 2 editing 操作 raw ticket markdown（JIRA 原始需求），canonical revision 操作下游的結構化正規版本。保持分離以維持清晰的資料流邊界
