## ADDED Requirements

### Requirement: 以字元 working budget 服務長 context 模型
系統 SHALL 繼續以 **serialized character budget**（非跨模型 token 精確值）限制送往 LLM 的歷史與單次工具結果。預設 working budget MUST 高於 v1 的 48k／8k，且 MUST NOT 預設等於任何模型的標稱最大 context（含 DeepSeek V4 Flash 的 1M tokens）。文件與 config 註解 MUST 記載：DeepSeek V4 Flash／Pro 官方 context 為 **1,000,000 tokens**；TCRT 預設採用更低的 character working budget（預設 history 480000 chars、tool_result 64000 chars）。

#### Scenario: 預設 history 與 tool-result 高於 v1
- **WHEN** 使用未覆寫 env 的 AssistantConfig 預設值
- **THEN** `history_max_chars` 預設為 480000，`tool_result_max_chars` 預設為 64000

#### Scenario: env clamp 防止無界
- **WHEN** 設定 `TCRT_ASSISTANT_HISTORY_MAX_CHARS` 或 `TCRT_ASSISTANT_TOOL_RESULT_MAX_CHARS` 超過實作 clamp 上界
- **THEN** 系統夾制到上界（history ≤ 1200000、tool_result ≤ 200000）且服務可啟動

### Requirement: List 工具結果採 soft truncation
當工具結果在 projection 與 credential redaction 之後為 **物件陣列** 或含 **`items` 物件陣列的 envelope**，且序列化長度超過 `tool_result_max_chars` 時，系統 MUST：

1. 將結果正規化為 envelope（若原為裸陣列，MUST 包成含 `items` 的物件；不得只回裸陣列而無 meta）。
2. 從陣列前端保留盡量多的**完整元素**（元素不可半截 JSON）。
3. 寫入中繼資料：`truncated`（bool）、`returned_count`、`source_count`、`next_skip`、固定英文 `hint`。
4. `next_skip` MUST 等於 `(request_skip 或 0) + returned_count`；executor MUST 把該次工具呼叫的 `skip` 參數傳入 truncation（無則 0）。
5. MUST NOT 將整個 list 結果替換成僅含 `preview` 字串的毀滅式截斷。

若連 **0 個完整元素**都無法放入 budget（單列已超過 max_chars），MUST 回 envelope：`items=[]`、`truncated=true`、`returned_count=0`、`source_count`、`hint` 提示改用 refs／更窄 filter／更小 limit；MUST NOT 對未 redact 內容做 hard preview。

#### Scenario: 大型 item list 保留完整前列
- **WHEN** `list_test_run_items`（或 refs 變體）回傳投影後 100 筆且超出 tool_result budget
- **THEN** 送往 LLM 的結果為含 `items` 的 envelope、若干完整物件、`truncated=true`、`returned_count` 等於保留筆數、`source_count=100`，且每筆保留元素含 id（或約定的 ref 主鍵）

#### Scenario: 單列過大無法放入
- **WHEN** 投影後單一 list 元素序列化已超過 tool_result budget
- **THEN** 結果為 `items=[]`、`truncated=true`、`returned_count=0`，且不含 credential 明文

#### Scenario: 非 list 過大仍 hard truncate
- **WHEN** 單一 detail 物件（非 list／非 items envelope）序列化後仍超過 tool_result budget
- **THEN** 結果可為 `{truncated: true, preview: ...}` 形式，且 preview 不得含未遮罩 credential 值

### Requirement: 截斷不得作為資料保護手段
長度截斷（soft 或 hard）MUST 發生在 allowlist projection 與 credential redaction **之後**。截斷 MUST NOT 取代 projection 或 redaction。Soft truncation 產生的 meta 欄位 MUST 僅存在於送往 LLM／持久化 tool message 的結果視圖，MUST NOT 寫入業務資料表或當成 mutation 請求 body。

#### Scenario: 先投影再 soft truncate
- **WHEN** list 元素含 projection 未允許欄位與 credential test_data
- **THEN** 送往 LLM 的保留元素不含未允許欄位，credential value 為 `[REDACTED]`，之後才套用字元 budget

### Requirement: 對話訊息上限可支撐較長任務
`max_messages_per_conversation` 預設 MUST 不低於 500（可由 env 調整並 clamp）。超限行為維持既有明確錯誤，不得靜默丟棄訊息。

#### Scenario: 預設訊息上限
- **WHEN** 使用未覆寫 env 的預設設定
- **THEN** 單一對話允許至少 500 則訊息後才因上限拒絕新 turn
