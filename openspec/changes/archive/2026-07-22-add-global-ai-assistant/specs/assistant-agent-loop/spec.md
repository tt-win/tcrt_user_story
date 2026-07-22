# assistant-agent-loop

## ADDED Requirements

### Requirement: LLM tool-calling 迴圈
系統 SHALL 以 OpenRouter chat completions（`tools=`、`tool_choice="auto"`）執行 agent 迴圈：載入 character-budgeted 對話歷史與系統 prompt → 呼叫 LLM → 執行回傳的工具呼叫並將（投影遮罩後的）結果附回 → 迭代直到 LLM 回傳純文字回覆。**只有 read 工具可在迴圈內連鎖執行**；一旦 LLM 產生 write 工具呼叫，迴圈 MUST 停在該 write：建立 pending action、發 `confirmation_required` 並結束回合，同一 response 中此 write 之後的 tool calls 一律丟棄。使用者確認後由 continuation turn 重新規劃下一步（此時狀態已變，不預先假設後續操作）。迴圈 MUST 受上限保護：最大迭代數（預設 8）、單次 LLM 呼叫逾時（60s）、單一工具逾時（30s）、單回合 wall clock（180s）。

#### Scenario: read 連鎖、遇 write 即停下確認
- **WHEN** 使用者要求「查失敗的 case 再建 run 加進去」
- **THEN** 迴圈連鎖執行查詢類工具，遇到第一個 write（建 run）即建立 pending、發確認卡並結束回合，不預先執行後續 write

#### Scenario: 多步驟寫入逐步確認
- **WHEN** 完成「建 run」確認後，continuation 重新規劃並提出「加 case」
- **THEN** 「加 case」再建立各自的 pending 確認卡，逐步確認而非一次連鎖完成

#### Scenario: 同一要求中的多個完整動作只確認一次
- **WHEN** 使用者在同一要求指定兩個以上已具備完整參數、無新 ID 相依的寫入動作
- **THEN** LLM 以一個 `batch_execute_actions` tool call 依序提交全部動作，系統只建立一個 pending；需要前一步結果才能組參數的後續動作仍由 continuation 重新規劃

#### Scenario: confirm 完成後過濾過時準備文字，但允許路徑總結
- **WHEN** confirmed write 已由 `tool_finished` 回報成功，continuation 最後只回傳「已準備好／請確認」等時序倒置空話（或空字串）
- **THEN** 系統不持久化、不送出該 terminal text，只以權威狀態圖示收尾
- **WHEN** continuation 最後回傳有實質內容的完成路徑總結（列出已執行步驟與關鍵 ID／結果）且無新 tool call
- **THEN** 系統 MUST 持久化該文字並以 `text_delta` 送前端，作為使用者可見的完成總結
- **AND** 若 continuation 實際提出新的 write tool call，仍正常建立下一張確認卡（伴隨的「準備」散文不作為 terminal text 送出）
- **AND** write 已終態化為 succeeded 後，後續 LLM 規劃異常不得再送出暗示 mutation 失敗的 error 或文字

### Requirement: LLM history 正規化與原子裁切
LLM 請求 MUST 帶 `parallel_tool_calls=false`（讓模型一次只回一個 tool call）；系統仍 MUST 防禦性處理 provider 回傳多個 tool call 的情況——遇第一個 write 即停下、丟棄其餘。持久化的 assistant message `tool_calls_json` MUST 只包含實際處理的 tool call。每個送往 LLM 的 assistant tool call MUST 使用伺服器正規化、非空且在對話內唯一的 `llm_tool_call_id`，其對應 tool result MUST 使用同一 ID；provider ID 僅另存供追蹤，不得直接作為配對鍵。

`history_max_chars` MUST 以序列化後字元數裁切（不得宣稱為跨模型 token 精確值），並先把歷史組成不可分割的 exchange group：一般 user/assistant 對話為一組；assistant tool call 與其 tool result（含跨 source turn／confirm continuation turn 的 write 流程）為一組。系統僅可整組保留或整組移除，MUST NOT 留下孤兒 assistant tool call 或孤兒 tool result。cancelled、expired、unknown，及任何「未取得真實工具結果即終止」的路徑 MUST 先寫入遮罩後的 synthetic tool result，再供歷史重建。

#### Scenario: 被丟棄的 tool call 不留孤兒
- **WHEN** provider 於一則 response 回傳 3 個 tool call，系統只處理第一個
- **THEN** 持久化的 assistant message 只含該處理的 tool call，重建 history 時無缺對應 result 的孤兒 call

#### Scenario: budget 裁切不拆散工具交換
- **WHEN** 歷史超過 character budget，最舊邊界落在 assistant tool call 與其 tool result 之間
- **THEN** 系統整組移除或整組保留該 exchange，不產生孤兒訊息

#### Scenario: provider context 過長只安全退讓一次
- **WHEN** 尚未執行 mutation 的完整 provider request 因 context length 回 400
- **THEN** 系統再整組移除最舊 exchange 並安全重試一次；第二次仍失敗即終止，不拆 tool pair、不循環重試

#### Scenario: provider call id 缺失仍可配對
- **WHEN** provider 未回傳 call id 或重用了先前 ID
- **THEN** 系統以 server-normalized `llm_tool_call_id` 重寫送回 LLM 的 assistant/tool 訊息，兩者可唯一配對

#### Scenario: read 工具訊息原子成對持久化
- **WHEN** read loopback 完成並準備將結果附回 LLM
- **THEN** assistant tool-call message 與 projected/redacted tool-result message 在同一 Tx B 依序寫入；若 Tx B rollback，兩者皆不可出現在歷史

#### Scenario: 迭代達上限
- **WHEN** LLM 連續發出超過 max_iterations 的（read）工具呼叫
- **THEN** 迴圈終止並回覆說明已達操作上限的訊息，不再執行工具

### Requirement: turn 與 event 持久化模型
系統 SHALL 以獨立資料表持久化回合與 SSE 事件：turn 表保存 `turn_key`、`client_message_id`、終態（running/completed/cancelled/failed）、取消旗標、per-turn 事件序號游標與 started/completed 時間戳；event 表以單欄 `turn_id` FK 關聯 turn，保存每個 SSE 事件的 `seq`、`event_type`（message_start/text_delta/tool_started/tool_finished/confirmation_required/error/done/cancelled）與 payload。event 表 MUST 對 `(turn_id, seq)` 唯一。child 表（events/messages/pending）MUST 以單欄 `turn_id` FK 關聯，conversation 由 turn 推導。模型 MUST 足以區分各事件型別並可靠重播任一 turn。LLM 語意歷史 SHALL 與 SSE 事件分開保存。

跨 conversation 隔離採兩層：(1) DB 層 FK 拒絕指向**不存在** turn 的 child；(2) 因 child 不保存自身 conversation_id，「有效但屬他對話的 turn」由**應用層**保證——所有 turn/child 查詢 MUST 經 `turn → conversation → user_id == current_user.id` 過濾，使用者 MUST NOT 能存取他人 turn。

#### Scenario: 各事件型別可區分並重播
- **WHEN** 某 turn 曾產生 text_delta、confirmation_required 與 error 事件後被載入
- **THEN** 系統依 seq 順序重播且每個事件的型別與 payload 均可還原

#### Scenario: DB 拒絕不存在的 turn
- **WHEN** 嘗試寫入 turn_id 指向不存在 turn 的 event/message/pending
- **THEN** 資料庫 FK 約束拒絕（各支援引擎皆 enforce）

#### Scenario: 應用層拒絕存取他人 turn
- **WHEN** 使用者 A 以屬於使用者 B 對話的 turn_id 查詢事件或續傳
- **THEN** 服務層經 turn→conversation→user_id 過濾回 404，不洩漏該 turn

### Requirement: turn 併發控制（跨 worker、具 fencing）
同一對話同時至多一個進行中 turn，MUST 以資料庫 lease（`active_turn_key` owner + 過期時間）強制，跨多個 worker/process 有效，MUST NOT 依賴行程記憶體。取得、續租與釋放 MUST 以 owner key 做 compare-and-set；續租／釋放的 `UPDATE` MUST 含 `active_turn_key = current_turn_key`，stale owner 不得清除新 owner 的 lease。runner MUST 在每次 LLM 呼叫、工具呼叫及事件／訊息寫入前驗證並續租；驗證與該次 DB 寫入 SHALL 位於同一交易。外部呼叫前的續租期限 MUST 大於該呼叫 timeout 加安全裕度。失去 lease 的 runner MUST 停止後續副作用，且不得覆寫新 turn 的事件或終態。lease 過期的孤兒 turn SHALL 依 unknown／failed 收尾規則恢復（mutation executing → unknown；未開始 mutation 的 turn → failed），MUST NOT 自動重跑。

executing mutation recovery MUST 使用獨立 `execution_deadline`，不得以 pending `expires_at` 判斷。Confirm Tx A 以 DB time 設 `executing_started_at` 與 `execution_deadline = db_now + tool_timeout + margin`。recovery 僅能在 deadline 與 conversation lease 皆過期、continuation turn 仍 running且 owner 仍為 continuation turn 時，先 CAS 將 owner 換為 recovery key；CAS 成功者才可同交易寫 unknown、paired synthetic result、terminal event/turn並釋放 admission，最後以 recovery key CAS 釋放 lease。

#### Scenario: 多 worker 下第二條 turn 被拒
- **WHEN** 兩個 worker 同時收到同一對話的訊息請求
- **THEN** 僅一個取得 lease 執行，另一個回 429 與明確錯誤碼

#### Scenario: stale runner 不得越過新 owner
- **WHEN** worker A 的 lease 過期、worker B 取得新 lease，而 A 隨後恢復
- **THEN** A 的 owner-CAS 續租／寫入失敗並停止，且不得執行下一個 LLM／工具呼叫或清除 B 的 lease

#### Scenario: renew 與 orphan recovery 競爭
- **WHEN** 原 runner 續租與 recovery 同時處理已達 execution deadline 的 executing action
- **THEN** 只有 owner-CAS 勝方可繼續；recovery 若搶得 recovery key，原 runner 的後續寫入全部失敗，且 action 只收尾一次

### Requirement: SSE 事件協定、detached runner 與跨 worker 續傳
訊息端點 SHALL 以 `text/event-stream` 回應，事件型別為：`message_start`、`text_delta`、`tool_started`、`tool_finished`、`confirmation_required`、`error`、`done`、`cancelled`；每個事件 MUST 帶 per-turn 單調遞增 `seq` 並持久化於 event 表。`done`/`cancelled` MUST 為對應 turn 的終結事件；不可恢復錯誤 MUST 以 `error` 事件收尾。agent runner MUST 由應用程式生命週期管理的 supervisor 啟動並持有，不得由單一 `StreamingResponse` generator 擁有或在 generator `finally` 取消；browser disconnect 只結束該 subscriber。

因 seq 為 per-turn，續傳 cursor MUST 帶 turn identity——`(turn_key, after_seq)` 或 `Last-Event-ID: <turn_key>:<seq>`，MUST NOT 只依 after_seq。每個 subscriber（含原請求）MUST 以 DB 為唯一事件來源，反覆查詢並依序送出 `seq > cursor` 的持久化事件，直到讀到 terminal event；不得依賴 process-local queue 接 live。此 DB tail 演算法使重連落到任一 worker 時皆能 gap-free 地完成「回放後接續 live」，且 MUST NOT 重新執行工具或 LLM 呼叫。History API 回傳訊息/事件 MUST 先依 turn_seq、再依 seq 排序。

#### Scenario: 斷線續傳不重跑
- **WHEN** 前端於某 turn 的 seq=7 斷線後帶 `(turn_key, after_seq=7)` 重連
- **THEN** 系統回放該 turn seq>7 的既有事件並接續即時事件，工具不重複執行

#### Scenario: 瀏覽器斷線不取消 runner
- **WHEN** StreamingResponse subscriber 在 agent runner 執行中斷線
- **THEN** subscriber 結束但 supervisor 中的 runner 繼續，後續事件仍持久化且可由任一 worker 重連讀取

#### Scenario: 跨 turn 的 after_seq 不混淆
- **WHEN** 對話有多個 turn、各自 seq 從 0 起
- **THEN** 續傳以 (turn_key, after_seq) 唯一定位事件，不會取到他 turn 的同號事件

#### Scenario: 工具執行進度可見
- **WHEN** 迴圈執行某工具
- **THEN** 前端先收到 `tool_started`（含工具名與參數摘要），完成後收到 `tool_finished`（含成功與否、結果摘要）

#### Scenario: confirm continuation 也有完整工具事件
- **WHEN** 使用者確認一筆 write action，continuation turn 執行 loopback
- **THEN** continuation 在 loopback 前先寫入 `tool_started`，終態時寫入含投影後結果的 `tool_finished`，且以 `done` 或 `cancelled` 結束

#### Scenario: orphan recovery 可終止 SSE
- **WHEN** 排程將 lease 過期的一般 turn 收旂為 failed，或將 executing mutation 收旂為 unknown
- **THEN** 同一交易寫入可重播的終態事件；mutation recovery 亦寫入 `tool_finished(outcome=unknown)`，讓 DB-tail subscriber 結束並顯示核對指引

### Requirement: 取消語意
系統 SHALL 提供顯式 stop API 設定 turn 取消旗標；agent 迴圈 MUST 在每個工具邊界與每次 LLM 呼叫前檢查旗標——已開始的單一工具不中斷不回滾，但取消後 MUST NOT 啟動下一個工具或 LLM 呼叫。瀏覽器中斷連線（abort fetch）MUST NOT 視為取消。取消完成後 SHALL 發出明確的取消結束事件。

#### Scenario: 停止時不啟動下一工具
- **WHEN** 使用者於工具 A 執行中按下停止
- **THEN** 工具 A 執行完成（結果照常記錄），迴圈不啟動工具 B，回合以取消狀態收尾

### Requirement: opt-in 啟用與未設定即停用
助手功能 SHALL 預設關閉；MUST 明確設定 `TCRT_ASSISTANT_ENABLED=true` 才啟用。當 OpenRouter API key 缺失或功能停用時，availability API SHALL 回報 disabled，chat/confirm API SHALL 回傳 503 `ASSISTANT_NOT_CONFIGURED`；系統 MUST NOT 提供退化（fallback）回覆。

#### Scenario: 既有部署升版後不被動開啟
- **WHEN** 已設定 OPENROUTER_API_KEY（供 QA AI Helper 使用）的部署升版且未設定 TCRT_ASSISTANT_ENABLED
- **THEN** 助手維持停用，widget 不顯示

### Requirement: 使用者限流與 in-flight admission 採跨 worker 原子保留
系統 SHALL 對每位使用者強制：每小時訊息數上限（預設 60）、單一對話訊息數上限（預設 200）、單則訊息長度上限（預設 4000 字元）；超限 MUST 回傳明確錯誤碼。`bucket_started_at` 固定為 UTC 整點。新 turn 的 TurnStart 交易 MUST 以 `(user_id, bucket_started_at)` 唯一的 rate-limit bucket 執行條件式原子遞增（`used_count < limit`）；bucket 不存在時以 savepoint 嘗試 insert，unique race loser rollback savepoint 後改走條件式 update，不得讓整個 TurnStart 處於 aborted transaction。系統並以 conversation row 的 `message_count < limit` 條件式遞增對話計數；quota reservation、conversation lease、turn 與 user message 建立必須同一交易 commit。相同 client_message_id 的既有 turn 直接重播、不重複扣 quota；unique race loser rollback 後亦不得耗用 quota。

同一 TurnStart 交易還 MUST 固定依 `global` → `user:<id>` 順序，對 `assistant_runtime_counters.active_count < limit` 做條件式遞增（預設 global 32、per-user 3）；migration 預建 `global=0`。`user:<id>` 不存在時以 savepoint 嘗試 insert `active_count=1`，unique race loser rollback savepoint 後改走條件式 update，任一超限使整個 TurnStart rollback。每個 turn 以 `admission_released=false` CAS 在 terminal/recovery 交易中各 decrement 一次。reconciliation 的權威集合是所有 `admission_released=false` turns；lease 暫時過期本身不得直接扣 counter，必須先由 recovery fencing 將 turn terminalize並釋放，或依 unreleased turns 重建 global/user 計數。每 process 另以 non-blocking semaphore（預設 8）限制 runner；本機 slot 不足時不得建立 turn或無界排隊。此機制 MUST 在 SQLite/MySQL/PostgreSQL 與多 worker 下成立，不可使用 process-local counter 或先 count 再 insert。

#### Scenario: 超過訊息頻率上限
- **WHEN** 使用者一小時內送出第 61 則訊息
- **THEN** 系統回傳 429 與明確錯誤碼

#### Scenario: 跨 conversation 並發只保留一份剩餘額度
- **WHEN** 同一使用者在兩個 conversation 並發送訊息且該小時只剩一份 quota
- **THEN** 僅一個 TurnStart 的條件式遞增成功，另一個回 429，總用量不超限

#### Scenario: 多對話不能繞過 active-turn 上限
- **WHEN** 同一使用者跨多個 conversation 並發建立超過 per-user active-turn limit 的回合
- **THEN** 只有額度內的 TurnStart commit，其餘回 429，且 terminal/recovery 各只釋放一次 counter

#### Scenario: 首次使用者 counter 並發建立
- **WHEN** fresh DB 上同一新使用者由兩個 worker 同時建立第一個 turn
- **THEN** 一方在 savepoint insert `user:<id>`，unique loser回到條件式 update；交易保持可用且 active_count 精確等於成功建立的 turns

### Requirement: 常用多步驟路徑以 skill recipe 提供
系統 SHALL 將常用多步驟操作路徑維護為 skill recipes。Runtime 真相為 main DB（見 capability `assistant-prompt-skills-admin`）；`prompts/assistant/skills/*.md` 僅 factory seed。每次 turn 開始組裝 system prompt 時，MUST 自 DB 讀取 system 模板並以 **enabled** skills 注入 compact catalog（替換 `{{SKILL_CATALOG}}`）。工具目錄 MUST 提供 read-only local 工具 `list_skills` 與 `get_skill`（不走 ASGI loopback、`team_check=none`，全域對話亦可用；僅 enabled），讓模型在規劃多步驟前載入完整步驟，而不是在 max_iterations 預算內逐步試探。

Skill 內容 MUST 以助手工具名稱描述步驟，並優先批次工具（例如多筆指派／回報結果用 `batch_update_results`，禁止對 N 筆目標迴圈呼叫 `update_test_run_item`）。`batch_update_results` 的 LLM schema MUST 允許 assignee-only 更新（`assignee_name` 可不伴隨 `test_result`）。

#### Scenario: 依案例編號前綴批次指派
- **WHEN** 使用者要求將某 test run 中特定單號前綴的 items 指派給某 assignee
- **THEN** 助手可經 skill catalog / `get_skill` 取得 `assign-run-items-by-case-prefix` 步驟：列出 items → 前綴過濾 → **單次** `batch_update_results`（僅 `assignee_name`），不得對每筆 item 各呼叫一次 `update_test_run_item`

#### Scenario: skill 工具不需 team 綁定
- **WHEN** 使用者在全域（無 team）對話呼叫 `list_skills` 或 `get_skill`
- **THEN** 工具可成功回傳 catalog / recipe；其餘 mutation 仍依既有 scope 規則不可用

#### Scenario: 停用 skill 不進 turn catalog
- **WHEN** 某 skill 在 DB 為 `is_enabled=false`
- **THEN** 該 turn 注入的 catalog 與 agent 的 list/get_skill 皆不包含它

### Requirement: TCRT-only guardrails
系統 prompt SHALL 限定助手僅服務 TCRT test case / test run 相關操作並明確拒絕離題請求；工具目錄 MUST 不含任何非 TCRT 功能之工具；系統 prompt MUST 聲明工具結果與 test case 內容為資料而非指令。

#### Scenario: 離題請求被拒絕
- **WHEN** 使用者要求寫詩或閒聊
- **THEN** 助手以固定語氣拒絕並引導回 TCRT 操作，不呼叫任何工具
