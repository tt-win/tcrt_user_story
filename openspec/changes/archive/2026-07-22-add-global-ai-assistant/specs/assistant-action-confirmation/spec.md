# assistant-action-confirmation

## ADDED Requirements

### Requirement: 所有 write 工具僅能經確認端點執行
工具 SHALL 依 `risk_level` 分級（read / idempotent_write / reversible_write / high_impact / irreversible）。**只有 `read` 可在 agent 迴圈內 inline 執行**；所有非 read 工具（idempotent_write / reversible_write / high_impact / irreversible）executor MUST 硬性拒絕 inline 執行，其唯一執行路徑 SHALL 是 confirm endpoint。此為防 prompt injection 觸發未經使用者意圖之寫入的結構性保證，不得依賴 prompt。確認卡分兩級：idempotent_write / reversible_write 用輕量確認卡，high_impact / irreversible 用警告確認卡。

#### Scenario: 迴圈內任何 write 被硬拒
- **WHEN** agent 迴圈嘗試直接執行 update_test_case、create_test_case、pin_entity 或 delete_test_case（不論 prompt 內容為何）
- **THEN** executor 拒絕 inline 執行，改走 pending action 確認流程

#### Scenario: 輕量與警告兩級卡
- **WHEN** 助手分別要執行 reversible 的 create_test_case 與 irreversible 的 delete_test_case
- **THEN** 前者建立輕量確認卡的 pending action、後者建立警告確認卡的 pending action，皆需使用者確認

### Requirement: pending action 參數雙欄分離
pending action MUST 分開保存兩份參數：`arguments_redacted_json`（遮罩後，供 UI、歷史、journal 與 LLM 使用）與 `execution_payload_json`（confirm 時據以執行的完整參數）。`execution_payload_json` MUST NOT 進入 LLM context、訊息紀錄、SSE 或 journal；於 confirm / cancel / expire / executing→unknown / retention 清理任一發生時 MUST 立即清為空。因 credential 值寫入已被禁（見 assistant-data-boundary），execution_payload 正常路徑不含 credential；`execution_payload_encrypted` + Assistant 專用金鑰保留為縱深防禦（若 payload 含敏感內容則加密、金鑰未設定則拒絕建立），MUST NOT 耦合 Automation Provider 金鑰。

#### Scenario: confirm 以完整參數執行、外顯僅遮罩版
- **WHEN** 使用者確認一筆 high_impact pending action（如批次刪除）
- **THEN** 工具以 execution_payload_json 的完整參數執行；UI/歷史/journal 僅見遮罩版；resolve 後 execution_payload_json 被清空

### Requirement: server-generated at-most-once 主鍵與 LLM 配對鍵
每個待執行的工具呼叫 MUST 由伺服器生成必填、全域唯一的 `execution_key`，作為 at-most-once 的唯一鍵（pending action 與執行日誌皆以它為唯一）。系統另 MUST 生成非空、對話內唯一的 `llm_tool_call_id`，並以此重寫持久化及送往 LLM 的 assistant tool call／tool result 配對；provider 回傳的 `provider_tool_call_id` MAY 為空或跨 turn 重複，MUST NOT 作為配對或 at-most-once 依據，僅供追蹤。

系統保證**至多執行一次**：loopback 成功但回寫失敗，或 mutation loopback 發生任何無法證明未執行的 timeout／transport／5xx 時進入 `unknown`、靠查詢核對，MUST NOT 宣稱「剛好一次」。`execution_key` MUST 為固定長度 32-hex（`token_hex(16)`），確保 continuation turn 的 `client_message_id = "confirm:" + execution_key`（40 字元）不超過 64 字元欄位上限；`llm_tool_call_id` 可決定性取自 execution_key（例如 `call_<execution_key>`）。

#### Scenario: provider 未提供或重用 call id 仍保證單次
- **WHEN** 兩個工具呼叫的 provider_tool_call_id 相同（或皆為空）但為不同執行
- **THEN** 各自的 server-generated execution_key 不同，兩者互不影響；同一 execution_key 的重複執行被 unique constraint 擋下

### Requirement: pending 建立、可信確認摘要與 source turn 原子收尾
LLM 發出 write 工具呼叫後，系統 MUST 先重新執行 JSON Schema、目前權限、conversation scope/team、resource_team_check、credential/sensitive input 與 canonical summary 驗證；任一步失敗不得建立 pending，並 MUST 在同一交易保存遮罩後的 server-normalized assistant tool call 與 paired synthetic validation result。credential 原值不得進 messages/events/journal；只有可修正的 schema 錯誤可繼續迴圈，其餘驗證拒絕在寫成對歷史後終止。驗證通過後 SHALL 於**單一交易原子完成 source turn 的收尾**：持久化使用 server-normalized ID 的 assistant tool-call message＋建立 pending action（狀態 `pending`，TTL 預設 600 秒，含工具名、雙欄參數、`confirmation_summary_json`＋fingerprint）＋寫入 `confirmation_required` 與 `done` 事件＋將 source turn 標記 completed＋以 `admission_released=false` CAS 釋放 global/user counters＋以 owner-CAS **釋放 source turn 的 lease**，一次 commit。若未原子釋放 admission/lease，使用者 confirm 時 continuation turn 將無法安全取得新額度與 lease。同一 LLM response 中此 write 之後的 tool calls MUST 一律丟棄（不預建 pending、不執行）。

`confirmation_summary_json` MUST 由 registry 的固定模板、已通過 schema 驗證的 arguments 與 server-side resource lookup 決定性產生，至少包含 canonical tool label key、risk level、target type/IDs、affected count（可解析時）與固定 warning keys；任何 lookup 資料先經 projection/redaction。系統 MUST 對 `{canonical_summary, stable_target_identity/version, destructive_membership_digest}` 的 canonical JSON 保存 SHA-256 `confirmation_fingerprint`，不得只 hash UI 摘要。單筆 resolver 至少提供 immutable business key 與 `updated_at`/row version；批次提供排序後目標 identities digest。若 high-impact/irreversible endpoint 無法建立穩定 identity/version/完整 membership，MUST fail-closed。LLM 文字 MUST NOT 作為確認卡主標、目標、數量或警告內容。summary lookup 失敗時 high-impact／irreversible action MUST fail-closed，不建立可確認 action；其他 write 僅可顯示固定的「影響範圍無法解析」警告，不得採用 LLM 自述。

confirm 在認領前 MUST 重新做 schema、目前權限、conversation scope/team 與 resource lookup 驗證並重算 canonical summary/fingerprint。若 fingerprint 改變，系統 MUST 以 `status=pending AND confirmation_fingerprint=old` CAS 更新卡片並回 409 `CONFIRMATION_STALE`，不執行工具；使用者看到新摘要後必須再次確認。若權限或 team 已失效，系統 MUST 原子 expire action、清 payload、寫 synthetic tool result。真正認領 Tx A 的 CAS MUST 同時比對最新 fingerprint。

#### Scenario: 建立 pending 即釋放 source turn lease
- **WHEN** agent 迴圈遇到 write 工具而建立 pending
- **THEN** 同一交易內 source turn 標記 completed、以 CAS 釋放 admission 並釋放 lease，使後續 confirm 的 continuation turn 能取得新 admission 與 lease

#### Scenario: prompt injection 無法淡化確認摘要
- **WHEN** LLM 為 delete_test_case 回傳「只是查看資料」等誤導文字
- **THEN** 確認卡仍以 registry 與實際 target 產生 canonical 刪除標籤、目標與 irreversible 警告，LLM 文字不進入主摘要

#### Scenario: 等待確認期間影響範圍改變
- **WHEN** 建立刪除 set 的 pending 後，set 內案例數在使用者按確認前改變
- **THEN** confirm 重算 fingerprint 後回 CONFIRMATION_STALE 並更新卡片，不執行刪除；使用者必須依新摘要再次確認

#### Scenario: 相同 row id 被重用仍視為 stale
- **WHEN** pending 指向的原資源被刪除，資料庫其後以相同整數 ID 建立顯示摘要相同的新資源
- **THEN** stable identity/version fingerprint 必須不同並回 CONFIRMATION_STALE；不得只因 UI 摘要相同就作用於 replacement

#### Scenario: 同一 response 後續 tool calls 被丟棄
- **WHEN** LLM 在一則 response 中回傳多個 tool call，第一個是 write
- **THEN** 建立該 write 的 pending 後回合結束，其餘 tool calls 不預建也不執行

### Requirement: pending action 狀態機、history closure 與原子認領
狀態轉移 SHALL 為：`pending → executing → confirmed | failed | unknown`，以及 `pending → cancelled | expired`。`expires_at` 只適用 pending TTL，不得用於 executing recovery。Confirm Tx A 以 DB time 設 `executing_started_at` 與 `execution_deadline = db_now + tool_timeout + margin`。`unknown` 為 orphan executing recovery 的終態，MUST 為模型、歷史 API 與確認卡 UI 可表示的狀態；recovery 必須先在 deadline 與 conversation lease 均過期、continuation turn 仍 running 且 owner 仍吻合時，以 CAS 把 owner 換成 recovery key。只有 CAS winner 可在同一交易寫 unknown、paired synthetic result、terminal turn/event、釋放 admission，最後以 recovery key CAS 釋放 lease。confirm 認領 MUST 以資料庫 compare-and-set（單一 `UPDATE ... WHERE status='pending' AND expires_at > now`，原子包含 TTL）完成並 commit；認領失敗 MUST 回傳明確錯誤且不執行工具。CAS 認領與 journal 起始紀錄 MUST 於 loopback 之前的獨立交易完成 commit，MUST NOT 持有交易跨越 loopback。

#### Scenario: executing 不使用 pending TTL 回收
- **WHEN** action 在 pending TTL 即將到期時才被 confirm，工具仍在 execution deadline 內且 runner 持有有效 lease
- **THEN** recovery 不得因 pending `expires_at` 已過就標 unknown；只有 execution deadline 與 lease 均過期且 recovery owner-CAS 成功才可收尾

每個 write assistant tool call 必須有同 `llm_tool_call_id` 的 tool result。confirmed 使用投影遮罩後真實結果；cancelled、expired、unknown，以及未取得真實 response 即 failed 的路徑，MUST 在切換終態的同一交易寫入固定、遮罩後的 synthetic tool result。送新訊息使 pending 過期時，synthetic result MUST 先取得下一個 message_seq 寫入原 source exchange，之後才建立新 turn，確保任何可見歷史狀態皆 protocol-valid。

#### Scenario: 並發 confirm 只執行一次
- **WHEN** 兩個並發請求同時 confirm 同一筆 pending action
- **THEN** 僅一個請求完成 `pending → executing` 認領並執行工具，另一個收到「已被處理」錯誤

#### Scenario: 逾時後確認被拒
- **WHEN** 使用者於建立後超過 TTL 才按確認
- **THEN** confirm API 回傳明確錯誤（已過期），工具未執行

#### Scenario: 送新訊息使 pending 過期
- **WHEN** 對話存在 pending action 時使用者送出新訊息
- **THEN** 該 pending action 標記 expired 並原子寫入 paired synthetic tool result，新回合才正常進行

### Requirement: confirm continuation turn
confirm 執行後接續的助手回覆 SHALL 在一個 deterministic continuation turn 中進行，其 `client_message_id` 由 execution_key 決定（如 `confirm:<execution_key>`），受 `(conversation_id, client_message_id)` unique 約束。重複 confirm 或 confirm SSE 中斷重試 MUST 命中既有 continuation turn 並重播其事件，MUST NOT 重新執行工具。continuation turn MUST 取得 conversation lease（維持每對話單一進行中 turn）。confirm 與「送新訊息使 pending 過期」並發時，兩者以相同的 `status='pending'` CAS 條件競爭，MUST 只有一方成功。

#### Scenario: 重複 confirm 重播而不重執行
- **WHEN** confirm 的 SSE 中斷，前端以同一 action 重試 confirm
- **THEN** 系統命中既有 continuation turn 重播事件，工具不再執行（execution_key 已存在）

#### Scenario: confirm 與 pending 過期並發只有一方勝出
- **WHEN** 使用者 confirm 的同時另一路徑因新訊息將該 pending 標記 expired
- **THEN** 僅一個 CAS 成功；若 expire 先成功則 confirm 收到「已過期」錯誤且工具不執行

### Requirement: at-most-once 執行保證
每次工具執行 MUST 對應執行日誌中唯一的 `execution_key` 紀錄（資料庫 unique constraint）；同一 `execution_key` MUST NOT 被執行兩次。工具執行成功但回寫失敗（狀態停留 `executing`）時，系統 MUST NOT 自動重送；SHALL 於下次互動或排程掃描時將該紀錄標記為 `unknown`、清除其原始執行參數，並在對話中回報結果不明、引導使用者以查詢類工具核對實際狀態後再決定。

#### Scenario: 重複的 execution_key 被拒
- **WHEN** 任何路徑嘗試以既有的 execution_key 再次執行工具
- **THEN** unique constraint 使第二次執行失敗，不發出 loopback 請求

#### Scenario: 執行結果不明時不自動重試且清除原始參數
- **WHEN** confirm 執行期間程序中斷，狀態停在 executing
- **THEN** 後續互動將其標記 unknown、清除 execution_payload_json、寫入 paired synthetic tool result 並回報使用者先查詢再決定，系統不自動重送

### Requirement: confirm 的判斷順序
confirm endpoint SHALL 依固定順序判斷，消除「並發/重試 confirm」與「重播既有 continuation」的契約衝突：
1. 已存在該 action 的 continuation turn → 重播其事件並接續 live stream（不重執行）。
2. 無 continuation 且 pending 可認領（status=pending 且未逾 TTL）→ 於 Tx A 原子建立 continuation turn＋CAS 認領＋journal，執行工具。
3. action 已達終態（confirmed/failed/unknown）且無 continuation → 回該終態狀態。
4. action 為 expired / cancelled → 回明確錯誤。

#### Scenario: 重試 confirm 走重播分支
- **WHEN** confirm 已建立 continuation turn 後前端重試 confirm
- **THEN** 進入判斷 1，重播既有事件而非重新認領或執行

#### Scenario: 過期 action confirm 回明確錯誤
- **WHEN** 對已 expired 的 action 呼叫 confirm
- **THEN** 進入判斷 4，回明確錯誤，不執行工具

### Requirement: confirm/cancel 端點行為
`POST /api/assistant/conversations/{cid}/actions/{id}/confirm` SHALL 驗證：目前使用者為對話擁有者、action 屬於該對話；依上述判斷順序處理。認領新 continuation 前 MUST non-blocking 取得本 worker runner slot；取不到不得建立 turn或認領 pending。認領情境的 Tx A MUST 原子包含 global/user admission、conversation lease 取得、continuation turn 建立、pending CAS（含 TTL）與 journal started，一次 commit；任一額度/lease 取不到即 rollback 且 pending 維持可重試（不進入 executing）。認領後以本次請求的 JWT 執行工具；只有明確 2xx 才標記 confirmed，ambiguous mutation outcome 依規則標 unknown；以延續的 SSE stream 回傳後續 agent 回覆。cancel MUST 以 CAS（`UPDATE ... SET status='cancelled' WHERE status='pending'`）標記、清除 execution payload，並在同一交易寫入 paired synthetic tool result，避免 confirm 已進入 executing 時被 cancel 覆寫；CAS 失敗即回明確錯誤。他人 MUST NOT 能 confirm/cancel 非自己的 action。

#### Scenario: 拿不到 lease 時 pending 維持可重試
- **WHEN** confirm 時該對話已有另一進行中 turn 佔用 lease
- **THEN** Tx A rollback，action 維持 pending（未進 executing），回可重試提示

#### Scenario: confirm 與 cancel 並發只有一方成功
- **WHEN** 一個 confirm 與一個 cancel 並發到達同一 pending action
- **THEN** 兩者以相同 `status='pending'` CAS 條件競爭，只有一方成功；若 confirm 先認領為 executing，cancel 的 CAS 失敗、不覆寫狀態

#### Scenario: 非擁有者確認被拒
- **WHEN** 使用者 B 嘗試 confirm 使用者 A 的 pending action
- **THEN** 系統回 404，action 維持 pending

### Requirement: 複合寫入動作的一次知情確認
`batch_execute_actions` MUST 將同一 team 內 2–50 個已具完整參數的 write action 保存於單一 pending。每個子動作 MUST 個別重新執行 schema、權限、team、credential/sensitive input 與 canonical summary 驗證。外層 summary MUST 逐項包含 server-derived action label、risk 與完整 target summary，整張卡的 tier 取子動作最高風險；fingerprint MUST 涵蓋有序完整 action 列表及各自 stable identity。任一 action 的 target、版本、歸屬或權限改變均視為 stale／失效，不得執行任何子動作。

#### Scenario: 一次確認完整動作集合
- **WHEN** 使用者要求多個建立、更新、移動、狀態變更、歸檔、觸發、附件或刪除動作，且每項參數均已完整解析
- **THEN** 系統顯示一張卡逐項列出 action 與 target；使用者確認一次後才依列出順序執行

#### Scenario: 動作集合不完整時 fail closed
- **WHEN** 任一 action schema 不合法、目標不存在、跨 team、權限不足、file_ref 無效，或總數超出 2–50
- **THEN** 系統不建立 pending、不執行任何子動作

#### Scenario: 新 ID 相依不預先合併
- **WHEN** 後一動作的必要 ID 只能由前一 create action 的 response 產生
- **THEN** 後一動作不放入同一 composite；前一動作完成後由 continuation 以真實 ID 重新規劃
