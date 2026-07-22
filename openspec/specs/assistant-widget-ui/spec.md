# assistant-widget-ui Specification

## Purpose
TBD - created by archiving change add-global-ai-assistant. Update Purpose after archive.
## Requirements
### Requirement: 全頁懸浮入口與可見性 gating
系統 SHALL 在所有已登入頁面右下角提供懸浮圖標（FAB），點擊開關聊天面板。widget SHALL 由前端 JS 注入，並以 `GET /api/assistant/availability` 判斷是否顯示（合併「功能已設定啟用」與「使用者可用」）；判斷 MUST fail-closed（API 錯誤即不顯示），未登入頁面 MUST NOT 顯示，登出事件 SHALL 即時移除 widget。

#### Scenario: 停用時完全不顯示
- **WHEN** assistant 未設定或 availability API 失敗
- **THEN** 頁面不注入任何 widget DOM

### Requirement: 新對話的資料範圍提示
系統 SHALL 在一則對話尚無任何訊息時（新建立、或尚未輸入過的既有對話），於訊息串列頂端顯示一則一次性提示，說明「僅協助 TCRT test case/test run 操作」且「對話內容會送往外部 LLM」；該提示 MUST NOT 以面板固定橫幅呈現，而是作為訊息串列中的一個項目，因此會隨後續訊息把它推出可視範圍，並 SHALL 在顯示固定秒數後自動淡出移除，不需使用者手動關閉。一旦該對話已有任何訊息，MUST NOT 再顯示此提示。

#### Scenario: 新對話顯示一次性資料外送提示
- **WHEN** 使用者開啟一則尚無訊息的對話（新建或既有空對話）
- **THEN** 訊息串列頂端出現提示，明確告知對話內容會送往外部 LLM 服務

#### Scenario: 提示會自動淡出
- **WHEN** 提示顯示超過設定的時間、使用者未與其互動
- **THEN** 提示淡出並從 DOM 移除，不阻塞或遮蔽後續訊息

#### Scenario: 提示會被對話捲動帶走
- **WHEN** 提示仍顯示，使用者送出訊息或收到回覆使串列成長
- **THEN** 訊息串列自動捲到底部，提示隨捲動移出可視範圍，不需等待淡出

#### Scenario: 已有訊息的對話不再顯示提示
- **WHEN** 使用者重新開啟一則已有至少一則訊息的既有對話
- **THEN** 訊息串列不顯示此提示

### Requirement: 對話介面與串流渲染
面板 SHALL 呈現訊息列表（使用者/助手氣泡）、工具執行進度（可摺疊步驟列，含執行中/成功/失敗狀態）與輸入區。助手回覆 SHALL 以 SSE 串流漸進渲染 markdown，且 MUST 經 sanitize 後才插入 DOM；sanitize 程式庫載入失敗時 MUST fallback 為純文字轉義渲染，絕不直接插入未淨化的 LLM 輸出。串流中 SHALL 提供停止按鈕。

#### Scenario: 串流中顯示工具進度
- **WHEN** 助手執行工具
- **THEN** 面板顯示該步驟的進行中指示，完成後轉為成功/失敗圖示與摘要

### Requirement: 附件上傳狀態與可下載連結
使用者隨訊息送出附件時，該則使用者泡泡 SHALL 顯示每個附件的圖示與檔名，並呈現三種狀態之一：上傳中、已上傳、上傳失敗，狀態圖示 MUST 具 `role=status` 與依狀態產生的 aria-label／title（比照既有 write 結果狀態圖示的無障礙慣例）。送出當下 MUST 立即以「上傳中」狀態顯示附件（不得像送出前的暫存區一樣在送出瞬間清空、讓使用者看不到任何附件蹤跡）；伺服器確認實際落地成功後（`attachments_saved` SSE 事件），狀態 MUST 轉為「已上傳」並成為可點擊連結，開啟後下載/預覽該附件原始內容；若整個請求失敗，或個別附件因並發重送競態未被保存，對應圖示 MUST 轉為「上傳失敗」且不可點擊。歷史重載時，已確認的附件 SHALL 直接以「已上傳」狀態呈現可點擊連結，不需要重新等待任何事件。附件下載端點的擁有權檢查 MUST 沿用既有的四重比對（user_id／conversation_id／turn_id／attachment_index），不得另開弱化的查詢路徑；下載一律以強制附件下載（非 inline）呈現，防止使用者上傳的 HTML/SVG 內容被同源瀏覽器 inline 執行。

#### Scenario: 送出附件立即顯示上傳中狀態
- **WHEN** 使用者隨訊息選擇一個檔案並送出
- **THEN** 使用者泡泡立即顯示該附件的圖示、檔名與「上傳中」狀態，不會在送出瞬間變得看不到附件蹤跡

#### Scenario: 上傳成功後轉為可點擊連結
- **WHEN** 伺服器確認附件已成功落地並發出 `attachments_saved` 事件
- **THEN** 對應附件圖示轉為「已上傳」狀態，使用者可點擊開啟/下載該附件原始內容

#### Scenario: 上傳失敗時明確呈現
- **WHEN** 附件請求整體失敗，或個別附件因並發重送競態未被保存
- **THEN** 對應附件圖示轉為「上傳失敗」狀態且不可點擊，不會讓使用者誤以為已成功

#### Scenario: 歷史重載直接呈現已確認附件
- **WHEN** 使用者重新開啟一則已有附件的歷史對話
- **THEN** 該則使用者訊息的附件圖示直接以「已上傳」狀態呈現可點擊連結，無需等待任何即時事件

### Requirement: write 結果不依賴 LLM 回覆
confirm continuation 的 `tool_finished` SHALL 是使用者可見結果的權威來源。前端 MUST 只顯示緊湊的狀態圖示：執行中、succeeded、failed、unknown；不得展開已投影 payload、ID、名稱、計數、錯誤 detail 或「動作已完成」等可見文字。狀態圖示 MUST 具 `role=status`、依 outcome 產生的 aria-label 與 title，不能只靠顏色辨識。工具活動與確認摘要 MUST 在同一個動作容器，確認摘要不另開對話氣泡；狀態圖示 MUST 放在該容器標題列右側，不得在容器下方另行呈現。完整 projection/redaction/truncation 後 payload仍保留於 tool history／SSE protocol 供 LLM、稽核與重載判定使用，但不得渲染成結果明細。圖示 MUST 在後續 LLM 回覆為空、失敗、或繼續規劃下一個 write 時仍保持可見，且重載歷史後呈現一致。

#### Scenario: 建立類操作只顯示成功圖示
- **WHEN** create_test_case_set、create_test_run_config 或 create_test_run_set 回傳 2xx，但後續 LLM 回覆為空或錯誤
- **THEN** 面板仍立即顯示成功圖示，但不顯示 projection 內的 id/name 或其他結果明細

#### Scenario: 狀態圖示具無障礙名稱
- **WHEN** 工具進入執行中、成功、失敗或結果不明狀態
- **THEN** 畫面只顯示對應圖示，但輔助科技可由 aria-label 辨識完整狀態，滑鼠停留可由 title 得知狀態

#### Scenario: 動作與確認摘要不拆成多個氣泡
- **WHEN** 工具活動後產生單筆或複合 write 確認摘要，並由 confirm continuation 回傳執行狀態
- **THEN** 「執行動作」標題、確認摘要與狀態圖示共用一個容器，圖示在標題列右側，不另外建立結果氣泡

#### Scenario: 確認 API 失敗不得假顯示成功
- **WHEN** confirm API 回傳 CONFIRMATION_STALE、權限失效、admission denied 或連線錯誤
- **THEN** 確認卡在 request 期間只顯示「確認中」且停用按鈕；失敗後必須從 history 重載權威狀態，不得留在 confirmed 假成功狀態

### Requirement: 兩級確認卡
所有 write 操作皆會產生 `confirmation_required` 事件。面板 SHALL 依 risk_level 渲染兩級確認卡：idempotent_write / reversible_write 用**輕量卡**（精簡、一鍵確認、低打擾），high_impact / irreversible 用**警告卡**（警示樣式 + 影響摘要清單）。卡片的 action label、target、affected count 與 warning MUST 僅由 server-derived `confirmation_summary_json` 搭配 i18n key 渲染，不得採用 LLM 自述文字；resource lookup 回傳的 target label 仍屬不可信資料，MUST 以 `textContent`／等價 escaping 渲染，不得當 HTML 或 i18n key 解譯。缺少必要 canonical 欄位時前端 MUST fail-closed，不顯示可按的確認按鈕。兩者皆含確認/取消按鈕，並鎖定輸入區直到使用者決定；決定後卡片 MUST 轉為不可再操作的狀態（已確認/已取消/已過期/結果不明 unknown）。續聊載入歷史時，未過期的 pending 卡 MUST 重現為可操作狀態，已 unknown 者 MUST 呈現「結果不明、請查詢核對」提示。

#### Scenario: 輕量與警告兩級呈現
- **WHEN** 助手分別要求 reversible 的建立 case 與 irreversible 的刪除 run
- **THEN** 前者呈現輕量確認卡、後者呈現含影響摘要的警告確認卡

#### Scenario: 確認前無法繼續輸入
- **WHEN** 確認卡呈現且尚未決定
- **THEN** 輸入框與送出按鈕停用並顯示提示文字

#### Scenario: unknown 結果呈現
- **WHEN** 一筆確認的執行結果不明（orphan recovery 標記 unknown）
- **THEN** 確認卡呈現不可操作的「結果不明」狀態並引導使用者查詢核對

### Requirement: 停止與取消狀態區分
widget 的停止按鈕 SHALL 呼叫顯式 stop API（非僅中斷 fetch），並依序呈現兩種明確狀態：「停止中」（等待當前工具收尾，輸入仍鎖定）與「已取消」（回合結束，輸入解鎖）。SSE subscriber 斷線只停止畫面接收，不取消 server-side runner；前端 SHALL 以 `(turn_key, after_seq)` 重連任一 worker，從 DB-backed event stream 恢復顯示，不得讓使用者誤判操作已取消。

#### Scenario: 停止按鈕顯示兩段狀態
- **WHEN** 使用者於工具執行中按下停止
- **THEN** 介面先顯示「停止中」，收到取消結束事件後轉為「已取消」並解鎖輸入

### Requirement: 對話生命週期與團隊切換
widget SHALL 記憶面板開關狀態與各團隊最近對話（localStorage），跨頁面導航後可續聊（以事件序號續傳）；切換團隊時 SHALL 對進行中的回合呼叫 stop API 並切換至該團隊的對話脈絡（團隊綁定不可變，故為切換對話而非改綁）；面板關閉期間收到回覆完成時 SHALL 於 FAB 顯示未讀標記。

#### Scenario: 切換團隊停止回合
- **WHEN** 串流進行中使用者切換目前團隊
- **THEN** 進行中回合被停止並提示已切換團隊，新輸入作用於新團隊的對話

### Requirement: 近期對話清單顯示標題
「近期對話」清單 SHALL 優先顯示每筆對話的 `title`（後端自動生成或使用者自訂，見 `assistant-conversations` 對話標題自動摘要）；`title` 為 NULL 時（例如首輪尚未終結、或標題生成正在背景進行中）MUST fallback 顯示 `conversation_key` 前 8 碼，確保清單始終有可辨識的項目。`title` 為使用者可見的動態文字內容，MUST 以 `textContent`／等價 escaping 渲染，不得當 HTML 解譯。

#### Scenario: 已生成標題時顯示標題
- **WHEN** 對話的首輪已結束、`title` 已由背景生成或使用者自訂
- **THEN** 近期對話清單該筆項目顯示 `title`，不顯示 conversation_key 片段

#### Scenario: 標題尚未生成時 fallback 顯示
- **WHEN** 對話剛建立、首輪尚未終結或標題背景生成尚未完成，`title` 為 NULL
- **THEN** 該筆項目 fallback 顯示 `conversation_key` 前 8 碼

### Requirement: 前端核心邏輯自動化測試
SSE 事件解析、確認卡狀態機與取消流程 SHALL 實作為可獨立測試的純函式模組，並以 Node 內建 `node:test` 撰寫自動化測試（不引入新測試框架依賴）；僅視覺與整頁互動以手動驗證補充。

#### Scenario: SSE parser 有自動化測試
- **WHEN** 執行前端測試指令
- **THEN** SSE 分塊解析（跨 chunk 邊界、多事件、殘缺行）與確認卡狀態轉移案例通過

### Requirement: i18n 與無障礙
widget 所有使用者可見文案 SHALL 提供 en-US、zh-CN、zh-TW 三語系並遵循既有 i18n lifecycle（`data-i18n` 屬性與動態 retranslate）。每個 registry 工具（read/write/composite）的步驟名稱 MUST 具 `assistant.action.<tool_name>` 三語翻譯，畫面不得直接顯示 `list_test_case_sets` 等 method identifier；未知或漏翻譯工具 MUST 使用翻譯過的泛用動作名稱。鍵盤行為 SHALL 支援：Enter 送出、Shift+Enter 換行（含 IME composing 防護）、Esc 關閉面板；訊息區 SHALL 標記 `aria-live="polite"`，FAB 與控制項 SHALL 有 aria-label。

#### Scenario: 語言切換即時生效
- **WHEN** 使用者切換介面語言
- **THEN** widget 靜態文案隨既有 i18n 機制更新，無需重新整理

#### Scenario: 工具步驟不顯示 method identifier
- **WHEN** 助手執行 `list_test_case_sets` 或 registry 中任一 read/write/composite 工具
- **THEN** 步驟顯示目前語系的明確動作名稱（如「列出 test case set」），且語言切換後即時重譯；不得顯示原始 tool name

#### Scenario: 複合動作列出全部 action 與目標
- **WHEN** `confirmation_summary.target_type` 為 `batch_actions`
- **THEN** 卡片以 textContent／等價 escaping 逐項呈現伺服器提供的 action label 與 target summary；缺少 actions、target 或數量不一致時 fail-closed，不顯示確認按鈕

### Requirement: 背景版本偵測不得中斷未保存操作
全域版本檢查器偵測到較新 server version 時 MUST 僅顯示可由使用者主動點擊的更新提示，不得自動重新載入頁面。此規則保護助手輸入草稿、表單與其他未保存操作；只有使用者明確點擊更新按鈕才可清快取並 reload。

#### Scenario: 助手輸入中偵測到新版本
- **WHEN** 使用者正在助手輸入框編輯文字，背景 response header 或版本輪詢回報較新版本
- **THEN** 頁面不 reload、輸入內容保留，僅出現「有新版本」按鈕

