# assistant-conversations Specification

## Purpose
TBD - created by archiving change add-global-ai-assistant. Update Purpose after archive.
## Requirements
### Requirement: 對話持久化與 per-user 隔離
系統 SHALL 將助手對話與訊息持久化於 main DB（`assistant_conversations`、`assistant_messages`）。每個對話 MUST 有 server-generated 32-hex `conversation_key`（全域唯一、不可變、不可重用）作為刪除後 journal 關聯的權威識別；整數 PK 僅供內部 join。任何對話查詢、續聊、確認操作 MUST 以 `user_id == current_user.id` 過濾；使用者 MUST NOT 能讀取或操作他人的對話。

#### Scenario: 使用者只能列出自己的對話
- **WHEN** 使用者 A 呼叫 `GET /api/assistant/conversations`
- **THEN** 回應僅包含 user_id 為 A 的對話，不包含其他使用者的對話

#### Scenario: 存取他人對話被拒
- **WHEN** 使用者 A 以使用者 B 的 conversation_id 呼叫訊息或確認 API
- **THEN** 系統回傳 404（不洩漏該對話存在與否）

### Requirement: 對話綁定單一團隊
每個對話 SHALL 於建立時設定不可變 `scope_type`（`global` 或 `team`）並綁定至多一個 team_id；`scope_type=team` 時建立當下 team_id MUST 非空，且存不可變 `source_team_id` 供刪除後辨識。mutation 類工具 MUST 僅在 `scope_type=team AND team_id IS NOT NULL` 的對話中可用，其 team_id 由 executor 從對話綁定注入。`scope_type=global` 的對話 SHALL 僅提供 discovery 類工具（列團隊等），MUST NOT 提供任何 mutation。scope/team 綁定於對話存續期間 MUST NOT 可變更（切換團隊即開新對話或切至該團隊既有對話）。已知限制（明文接受）：現行 `check_team_permission` 由全域角色決定、team_id 僅為快取鍵；本綁定縮小預設操作面，不構成 team 粒度授權。

#### Scenario: 全域對話無 mutation 工具
- **WHEN** 使用者在未綁定 team 的對話中要求建立 test case
- **THEN** 目錄中沒有 mutation 工具可用，助手引導使用者選擇團隊後開啟 team 對話

#### Scenario: 團隊被刪除後對話轉唯讀
- **WHEN** 對話綁定的 team 被刪除（team_id 轉為 NULL）
- **THEN** 該對話因 `scope_type=team AND team_id IS NULL` 自動視為唯讀歷史，不得建立新 turn、呼叫 discovery 或 mutation；它不會被誤認為 `scope_type=global`，歷史仍可依 source_team_id 顯示原 scope

#### Scenario: 團隊刪除使既有 pending 失效
- **WHEN** team-bound conversation 已有 pending action，而 team 在 confirm 前被刪除
- **THEN** confirm 的 Tx A 前 scope 驗證將 action 原子標記 expired、清除 payload並寫 synthetic tool result，不發出 loopback；該 conversation 後續只可讀歷史

### Requirement: 使用者可刪除自己的對話
系統 SHALL 提供 `DELETE /api/assistant/conversations/{id}`：刪除對話及其訊息、事件、turns、附檔暫存與 pending actions。若該對話存在進行中 turn 或狀態為 executing 的 pending action，系統 MUST 回 409（需先 stop 並等收尾）。執行日誌（journal）SHALL 保留供稽核，並 MUST 可依不可重用的 `source_conversation_key` 追查——即使 FK 關聯已因刪除而清空。

#### Scenario: 刪除對話
- **WHEN** 使用者刪除自己一則沒有進行中 turn 的對話
- **THEN** 對話、訊息、事件、turns、附檔、pending actions 被移除，執行日誌以 source_conversation_key 保留

#### Scenario: 有進行中 turn 時刪除被拒
- **WHEN** 使用者刪除一則正在串流或有 executing pending action 的對話
- **THEN** 系統回 409，要求先停止該回合

### Requirement: 對話標題自動摘要
系統 SHALL 在對話的第一個 turn（`turn_seq == 0`）進入終態（completed/failed/cancelled，含正常結束、confirm 確認後結束、與 retention job 的 orphan recovery）後，背景嘗試為該對話生成一句簡短標題並寫入 `title` 欄位，供「近期對話」清單顯示；此為盡力而為（best-effort）背景行為，MUST NOT 阻塞 turn 結束、SSE `done` 事件或任何前景回應。標題寫入 MUST 僅在 `title IS NULL` 時發生（以不可重用的 `conversation_key` 做 CAS 條件，MUST NOT 使用可能因刪除重建而被重新分配的整數 PK 做識別），MUST NOT 覆蓋使用者於建立對話時自行指定的 `title`，也 MUST NOT 覆蓋先前已生成的標題。

標題內容 SHALL 優先由 LLM 對「該對話依 turn_seq、message_seq 排序的首則 user 訊息」與「首則純文字 assistant 回覆（`role='assistant' AND tool_calls_json IS NULL`，排除 tool-call 佔位訊息）」做單句摘要；下列情況 MUST fallback 為首則 user 訊息的截斷文字，確保對話一定能取得有意義的標題而非永久留白：LLM 未設定（`assistant.enabled=False` 或無 OpenRouter key）、LLM 呼叫失敗，或該對話首個 turn 終結時尚未產生任何純文字 assistant 回覆（例如第一輪即為 write 工具而先建立確認卡、或該首輪已被拒絕/取消/因 lease 過期被 recovery 標記失敗）。標題生成送往外部 LLM 的內容 MUST 沿用既有訊息持久化前已套用的 credential 遮罩（見 `assistant-data-boundary`），不得繞過遮罩直接送出未遮罩的原始參數。

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

### Requirement: 訊息冪等鍵與並發重送順序
每則使用者訊息 SHALL 攜帶 client 產生的冪等鍵（`client_message_id`）與 server-computed `request_fingerprint`（正規化文字＋依序排列的附件 SHA-256/size），`(conversation_id, client_message_id)` MUST 唯一。處理順序 MUST 明確定義以消除並發競態：(1) 先查既有 turn；ID 與 fingerprint 皆相同則重播/接續其 stream，ID 相同但 fingerprint 不同則回 409 `IDEMPOTENCY_KEY_REUSED`；(2) 否則於單一交易原子保留 user/hour quota＋conversation message_count、取得 lease、配發單調 `turn_seq` 並建立 turn；(3) 若 unique race 導致建立失敗，loser MUST rollback（含 quota）後重新查該 turn，比對 fingerprint 並接續其 stream；(4) 僅**不同** `client_message_id` 因 lease 被佔而無法開新 turn 時才回 429。multipart 重送 MUST NOT 重複保存附檔。

#### Scenario: 相同 ID 並發重送皆接續同一 turn
- **WHEN** 兩個帶相同 client_message_id 的請求並發到達、皆先查不到 turn
- **THEN** 一個建立 turn，另一個因 unique race rollback 後重新查得該 turn 並接續其 stream，皆不回 429

#### Scenario: 斷線重試不重跑工具、不重存附檔
- **WHEN** 前端因 SSE 中斷以相同 client_message_id（含附檔）重送
- **THEN** 系統重播已持久化事件，不重新呼叫 LLM/工具，也不重複保存附檔

#### Scenario: 相同冪等鍵不可代表不同 payload
- **WHEN** client 以既有 client_message_id 重送不同文字或不同附件內容
- **THEN** 系統回 409 IDEMPOTENCY_KEY_REUSED，不重播舊回覆也不覆寫既有 turn

### Requirement: 訊息歷史可完整重建對話畫面
`GET /api/assistant/conversations/{id}/messages` SHALL 回傳 user/assistant/tool 訊息，MUST 先依 conversation 內單調且唯一的 `turn_seq`、再依 per-turn `message_seq` 排序（兩者皆不依賴 created_at 時間戳，也不與 SSE event seq 混用）。回應 SHALL 序列化工具執行（名稱、遮罩後參數摘要、結果狀態）與確認狀態（pending/executing/confirmed/cancelled/expired/**unknown**），使前端能將歷史渲染成與即時串流一致的畫面；未過期的 pending 確認 MUST 以可操作狀態呈現，`unknown` MUST 呈現「結果不明、請查詢核對」。

#### Scenario: 續聊時重現 pending 確認卡
- **WHEN** 使用者關閉面板後重新開啟，該對話存在一筆未過期的 pending action
- **THEN** 歷史回應含該確認的完整資訊與 pending 狀態，前端可直接 confirm/cancel

#### Scenario: 歷史依 turn_seq 再依 message_seq 排序
- **WHEN** 對話有多個 turn、各自 seq 從 0 起
- **THEN** 歷史回應先依 turn_seq、再依 message_seq 排列，跨 turn 的同號 message_seq 不錯置

#### Scenario: write 結果重載後仍可見
- **WHEN** 使用者確認建立 test case set/test run 後重新開啟面板
- **THEN** history 回應對 tool message 提供已投影的結果與 pending outcome，前端可重建與即時 `tool_finished` 一致的成功、失敗或結果不明卡片

### Requirement: 聊天附檔暫存與並發冪等
隨訊息上傳的檔案 SHALL 記錄於 `assistant_uploaded_files`，以單欄 `turn_id` FK 關聯發起訊息的 turn，並保存 attachment_index、SHA-256 與相對 `attachments/assistant_tmp` root 的安全 `relative_path`；實際 stored filename MUST 由 server 隨機生成，不得直接使用原始檔名，且 MUST NOT 持久化機器絕對路徑。`(turn_id, attachment_index)` unique 保證相同 client_message_id 並發重送**不重複保存**（loser 因 unique 失敗、清除自己剛寫的暫存檔）。檔案解析 MUST 重用既有 relative-path containment helper，且檔案僅能被同一對話（經 turn→conversation→user）的工具以 file_ref 引用，並受大小與數量上限限制。retention job MUST 清除逾期 DB rows 對應檔案及沒有 DB row、超過短暫 grace period 的 orphan temp files。

上傳成功後，系統 SHALL 在把該 turn 的對話歷史組成 LLM `messages` 前，將本 turn 已記錄的附件清單（`attachment_index`、原始檔名、content_type）附加於該 turn 的 user 訊息內容，明確告知 LLM 有哪些 `file_ref` 數值可用；此附加內容 MUST NOT 寫回持久化的 `AssistantMessage.content`（避免使用者於前端看到非其輸入的文字），僅在建構 LLM history 時即時附加。`file_ref` MUST 僅在附件上傳當下的同一 turn 內有效——其後續（例如 confirm continuation）或其他 turn 皆不得引用；模型嘗試引用其他 turn 的附件 MUST 被 `file_ref_invalid` 拒絕。

附件實際落地成功後，系統 SHALL 透過既有 turn 事件系統發出 `attachments_saved` 事件（含每個成功保存的 `attachment_index`／原始檔名／content_type／size_bytes），供前端把送出中的附件圖示轉為已確認狀態；此事件沿用既有 SSE 事件序號與重播機制，不需另建協定。`GET .../conversations/{id}/messages` 的歷史回應 SHALL 對每則有附件的 user 訊息項目附上同樣結構的附件清單，供使用者重新取得原始檔案；下載端點 MUST 沿用 `get_turn_owned`／`get_uploaded_file_owned` 既有的多重擁有權比對，不得另開弱化的查詢路徑，且回應 MUST 強制以附件下載呈現（不得 inline），避免使用者上傳內容被同源瀏覽器執行。附件暫存的保存期（`upload_retention_hours`，預設 24 小時）遠短於對話本身的保存期（`retention_days`，預設 90 天）——這是刻意的設計取捨：附件僅供上傳當下該回合使用，一旦逾期，retention job 清除對應 DB row 後，`GET .../messages` 的歷史附件清單與下載端點 SHALL 一併不再顯示/提供該筆附件，不視為資料遺失或需回報的缺陷。

#### Scenario: 附檔供工具引用
- **WHEN** 使用者隨訊息上傳 result.zip，助手隨後呼叫 upload_run_item_results(file_ref)
- **THEN** executor 讀取該暫存檔並上傳至既有端點；跨對話引用他人 file_ref 被拒

#### Scenario: LLM 被告知本回合可用的附件
- **WHEN** 使用者隨訊息上傳一個檔案並詢問助手如何使用它
- **THEN** 送給 LLM 的該則 user 訊息內容附加系統產生的附件清單（含 file_ref 數值與原始檔名），模型得以據此正確填入工具的 `file_ref` 參數；前端歷史畫面顯示的仍是使用者原始輸入文字，不含此附加內容

#### Scenario: file_ref 不可跨 turn 引用
- **WHEN** 附件於某個 turn 上傳後，該 turn 已結束，使用者在後續新 turn 中要求助手使用「剛剛上傳的檔案」
- **THEN** 新 turn 的 LLM history 不會附加舊 turn 的附件清單；若模型仍嘗試以舊 attachment_index 呼叫工具，系統回傳 `file_ref_invalid`，不得誤用他 turn 的暫存檔

#### Scenario: 附件落地成功發出確認事件與歷史欄位
- **WHEN** 使用者上傳的附件全部成功記錄於 `assistant_uploaded_files`
- **THEN** 該 turn 的事件序列含 `attachments_saved`（列出實際保存成功的附件），且之後任何時間點呼叫 `GET .../messages` 的歷史回應對該則 user 訊息附上相同的附件清單

#### Scenario: 附件下載端點的擁有權比對不可弱化
- **WHEN** 前端以 `conversation_id`／`turn_key`／`attachment_index` 呼叫附件下載端點
- **THEN** 端點內部 MUST 依序呼叫既有的 `get_turn_owned`（user_id＋conversation_id＋turn_key 三重比對）與 `get_uploaded_file_owned`（再加 attachment_index），不得只用單一查詢就回傳檔案內容；不屬於該使用者的請求一律 404

#### Scenario: 附件逾期後歷史與下載一併不再提供
- **WHEN** 附件已超過 `upload_retention_hours` 被 retention job 清除
- **THEN** 該筆附件不再出現於歷史回應的附件清單，下載端點回 404；這是刻意的保存期設計，不視為資料遺失

#### Scenario: 並發重送不重複保存附檔
- **WHEN** 相同 client_message_id 帶同一附檔並發重送
- **THEN** `(turn_id, attachment_index)` unique 使第二次保存失敗，loser 清除自己剛寫的暫存檔，最終只保留一份

### Requirement: Retention 清理
系統 SHALL 由排程 job 定期清理超過 `retention_days`（預設 90 天）的對話（連同訊息、pending actions、附檔暫存），並將逾時停留於 executing 的執行紀錄標記為 unknown。

#### Scenario: 過期對話被清除
- **WHEN** 對話的 last_message_at 超過 retention_days 且清理 job 執行
- **THEN** 該對話及其訊息、pending actions、暫存檔被刪除

