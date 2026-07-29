## MODIFIED Requirements

### Requirement: 對話標題自動摘要
系統 SHALL 在對話的第一個 turn（`turn_seq == 0`）進入終態（completed/failed/cancelled，含正常結束、confirm 確認後結束、與 retention job 的 orphan recovery）後，背景嘗試為該對話生成一句簡短標題並寫入 `title` 欄位，供「近期對話」清單顯示；此為盡力而為（best-effort）背景行為，MUST NOT 阻塞 turn 結束、SSE `done` 事件或任何前景回應。標題寫入 MUST 僅在 `title IS NULL` 時發生（以不可重用的 `conversation_key` 做 CAS 條件，MUST NOT 使用可能因刪除重建而被重新分配的整數 PK 做識別），MUST NOT 覆蓋使用者於建立對話時自行指定的 `title`，也 MUST NOT 覆蓋先前已生成的標題。

標題內容 SHALL 優先由 LLM 對「該對話依 turn_seq、message_seq 排序的首則 user 訊息」與「首則純文字 assistant 回覆（`role='assistant' AND tool_calls_json IS NULL`，排除 tool-call 佔位訊息）」做單句摘要；下列情況 MUST fallback 為首則 user 訊息的截斷文字，確保對話一定能取得有意義的標題而非永久留白：LLM 未設定（`assistant.enabled=False` 或無 OpenRouter key）、LLM 呼叫失敗，或該對話首個 turn 終結時尚未產生任何純文字 assistant 回覆（例如第一輪即為 write 工具而先建立確認卡、或該首輪已被拒絕/取消/因 lease 過期被 recovery 標記失敗）。標題生成送往外部 LLM 的內容 MUST 沿用既有訊息持久化前已套用的 credential 遮罩（見 `assistant-data-boundary`），不得繞過遮罩直接送出未遮罩的原始參數。

標題語言 SHALL 跟隨觸發該次生成的回合所帶的介面語系（見 `assistant-agent-loop`「回覆語言跟隨介面語系」），並以 append 方式補在標題 prompt 之後；標題 prompt MUST NOT 寫死單一語系。取不到語系時（未提供、無法映射，或 orphan recovery 等無 request 情境）MUST 退回「與使用者訊息相同的語言」，MUST NOT 因此讓標題永久停留在單一語系或略過生成。

#### Scenario: 首輪一般文字回覆後生成標題
- **WHEN** 使用者的第一則訊息不涉及任何工具呼叫，助手直接以純文字回覆，該 turn 正常結束
- **THEN** 系統背景以「首則 user 訊息＋該則 assistant 回覆」呼叫 LLM 生成一句短標題並寫入 `title`

#### Scenario: 使用者自訂標題不被自動摘要覆蓋
- **WHEN** 使用者建立對話時已指定 `title`
- **THEN** 首輪結束後的自動標題生成偵測到 `title` 非 NULL，略過 LLM 呼叫與寫入，不改動使用者指定的標題

#### Scenario: LLM 未設定或呼叫失敗時 fallback 為截斷原文
- **WHEN** 助手未設定 OpenRouter key，或標題摘要的 LLM 呼叫失敗
- **THEN** 系統以首則 user 訊息截斷後的文字作為 `title` 寫入，不因此讓對話標題永久為 NULL

#### Scenario: write-first 對話仍能取得 fallback 標題
- **WHEN** 使用者的第一則訊息直接觸發 write 工具、該 turn 以建立確認卡（無任何純文字 assistant 回覆）結束
- **THEN** 系統仍在該 turn 結束後背景嘗試生成標題，因查無可用的純文字 assistant 回覆而直接 fallback 為首則 user 訊息截斷,不會等待後續 confirm 才觸發、也不會永久停留在 NULL

#### Scenario: 標題語言跟隨該回合介面語系
- **WHEN** 介面語言為 `en-US` 的使用者送出對話的第一則訊息，該 turn 正常結束
- **THEN** 標題摘要送往 LLM 的 prompt MUST 含要求以英文輸出標題的語言指示
- **WHEN** 該次生成沒有可用語系（例如由 retention job 的 orphan recovery 觸發）
- **THEN** prompt MUST 不附加語言指示，改以「與使用者訊息相同的語言」產生標題
