# assistant-tool-execution

## ADDED Requirements

### Requirement: 工具矩陣為契約
助手工具 SHALL 以工具矩陣定案：每個工具的 name、對應 endpoint（method + path template）、參數綁定（path/query/body/multipart）、所需 `PermissionType`、`risk_level`、冪等性、output projection、遮罩規則、錯誤碼映射。registry SHALL 為矩陣的宣告式實作（不含業務邏輯），並 MUST 於載入時驗證：工具名稱唯一、所有 DELETE 端點工具的 risk_level 預設為 irreversible（降級豁免僅限矩陣明文列出且附理由的可完全復原關聯操作，驗證測試比對豁免清單）、每個 path template 可對應用程式實際路由解析。

同一 endpoint 含不同風險 operation/欄位時 MUST 拆成互斥工具 schema：`update_test_case` 不接受 set/section scope 欄位，scope 另走 high-impact `move_test_case_scope`；batch metadata update、batch move、batch delete 分開，delete operation 由 server 固定且為 irreversible；`update_test_run_config` 不接受 scope 欄位，scope 另走 high-impact `update_test_run_scope`。registry contract test MUST 拒絕較低風險工具暴露 higher-risk 欄位或 LLM 覆寫 server-fixed discriminator。

#### Scenario: registry 防 drift
- **WHEN** 內部 router 路徑或 request model 變更導致工具描述與實際端點不符
- **THEN** registry 路由解析驗證或 OpenAPI request contract 測試失敗，變更不得默默上線

#### Scenario: archive 不映射 DELETE
- **WHEN** 使用者要求「歸檔」某 test run 或 run set
- **THEN** 可用工具僅為 status/archive 類端點；DELETE 類為獨立且 irreversible 的工具

#### Scenario: generic update 無法夾帶 scope cleanup
- **WHEN** LLM 對 update_test_case 或 update_test_run_config 傳入 scope 欄位，或嘗試覆寫 batch_delete 的 fixed operation
- **THEN** JSON Schema 拒絕，不得以較低風險確認卡執行資料移動、cleanup 或刪除

### Requirement: path 參數型別必須對應真實端點型別
`AssistantTool.to_llm_schema()` 對 `path_params` 預設宣告為 `"type": "integer"`；若對應真實端點的 path 參數實際型別為字串（例如附件檔名、外部系統 ticket number、enum 值），registry MUST 以顯式 schema（`path_param_schemas`）覆寫，否則 LLM 會被迫捏造不存在的整數值——確認卡仍會建立（risk_level 判斷不受影響），但實際呼叫必然因值不符而失敗（後端回 404，依現有「非 2xx 一律 unknown」設計顯示為結果不明，而非明確失敗或明確成功），使用者體驗上等同該工具完全無法使用。registry contract test MUST 交叉比對每個 loopback 工具宣告的 path 參數型別與真實 FastAPI endpoint 的 Python 參數型別註記（`int`/`str`），不一致即測試失敗，不得默默上線。

對於同時支援本地整數 id 與外部系統別名（例如 Lark record id）的資源識別碼，僅修正 LLM schema 型別不足夠：任何從該識別碼查詢資料庫的程式路徑（team 歸屬驗證、confirmation summary identity 解析、既有值檢查如 credential 覆寫防護等）皆 MUST 採用與該資源真實 API 端點一致的解析順序（本地整數 id 優先，查無才查外部別名），否則即使 schema 型別已修正，仍會在下游驗證環節產生誤判（可能是誤拒真實有效的操作，亦可能是更嚴重的 fail-open——保護邏輯因查無資料列而靜默放行）。已知限制：本次修復涵蓋單一資源 path 參數（`get_test_case`／`update_test_case`／`delete_test_case`／`move_test_case_scope` 的 `record_id`），尚未涵蓋以陣列傳遞多個資源 id 的批次工具（`record_ids`），該類工具目前仍要求全為本地整數 id，對外部別名一律 schema 拒絕（fail-closed，非本次修法引入的新風險），留待後續變更處理。

#### Scenario: 字串識別碼型 path 參數可正確執行
- **WHEN** 某工具的 path 參數在真實端點是字串（如附件檔名、JIRA ticket number、pin entity_type）
- **THEN** registry 以 `path_param_schemas` 宣告該參數為字串型別，LLM 提供真實字串值即可通過 schema 驗證並成功執行，不再被迫提供無意義的整數

#### Scenario: registry drift 測試攔截型別不符
- **WHEN** 新增或修改工具時，某 path 參數的宣告型別與真實端點的 Python 參數型別註記不符
- **THEN** registry 的型別 drift 測試失敗，變更不得默默上線

#### Scenario: 外部別名識別碼的下游解析與真實端點一致
- **WHEN** 資源以外部系統別名（例如 Lark record id）而非本地整數 id 被引用
- **THEN** team 歸屬驗證、confirmation summary identity 解析、既有值保護檢查等下游程式路徑皆能正確解析出該資源，其解析順序與結果與該資源真實 API 端點一致，不因識別碼形式而誤拒或誤判

#### Scenario: 既有值保護檢查不得因識別碼形式被繞過
- **WHEN** 某 write 工具的既有值保護檢查（例如既有 credential test_data 不得被覆寫）需要先查出目標資源目前的值
- **THEN** 該查詢 MUST 支援與其他下游解析一致的識別碼形式；查無資料列 MUST NOT 被當成「無需保護」而靜默放行，避免保護機制對特定識別碼形式的資源 fail-open

### Requirement: executor 為必要權限防線
executor MUST 於每次工具執行前，以 `check_team_permission` 強制驗證使用者具備該工具宣告的 `PermissionType`；驗證失敗即拒絕，不發出 loopback 請求。此檢查為必要防線——部分既有 web 端點（如 test-run-configs、test-run-items、附件端點）本身沒有 in-handler 權限檢查，MUST NOT 假設被呼叫端點會把關。回合開始時的工具目錄預過濾（只把有權限的工具送進 LLM）為引導性質的第一層。

#### Scenario: VIEWER 無法透過無檢查端點寫入
- **WHEN** VIEWER 角色的回合中，LLM 產生 create_test_run_config 工具呼叫（該端點本身無權限檢查）
- **THEN** executor 以宣告的 WRITE 權限檢查拒絕，不發出 loopback 請求

#### Scenario: VIEWER 只看得到唯讀工具
- **WHEN** VIEWER 角色使用者開啟一個回合
- **THEN** LLM 收到的 tools 僅含 read 類工具

### Requirement: in-process loopback 執行與 team_id 注入
工具執行 SHALL 透過 in-process ASGI loopback 呼叫既有 web JWT router，轉發啟動該 turn／confirm 請求的 Bearer JWT；`team_id` MUST 由 executor 從對話綁定注入 path template，MUST NOT 出現在 LLM 可控的參數 schema 中。為支援 subscriber 斷線後 detached runner 繼續，JWT MAY 僅以 ephemeral in-memory runner context 保留至 turn 終態；MUST NOT 寫入 DB、queue payload、event、log、exception 或任何可重播資料，runner 終態／失敗時 MUST 立即釋放引用。loopback 請求 MUST 附 `X-TCRT-Assistant: 1` 與含 conversation key 的 User-Agent。

#### Scenario: LLM 無法指定其他 team
- **WHEN** LLM 產生的工具參數夾帶 team_id 欄位
- **THEN** 參數驗證拒絕未知欄位；實際 team_id 一律取自對話綁定

### Requirement: sub-resource team 歸屬驗證
對 path template 不含 `{team_id}` 或操作可能跨 team 之 sub-resource（set_id/config_id/run_id/section_id/pin entity_id 等）的工具，registry MUST 宣告 `resource_team_check`（由參數解析目標資源實際所屬 team 的 resolver）；executor MUST 於 loopback 之前驗證該 team 等於對話綁定 team，不符即拒絕（不發出請求）。此為結構性保證，MUST NOT 假設被呼叫端點會驗證 team 歸屬。

#### Scenario: 跨 team 的 set_id 被拒
- **WHEN** 對話綁定 team 3，LLM 對 create_test_case_section 傳入屬於 team 5 的 set_id
- **THEN** executor 的 resource_team_check 解析出 team 5 ≠ 3，拒絕執行且不發出 loopback

### Requirement: 執行日誌（journal）與交易邊界
每次工具執行 SHALL 寫入 `assistant_tool_executions` 權威日誌：server-generated `execution_key`（unique）、不可重用的 `source_conversation_key`、不可變 `source_conversation_id`/`source_turn_key`、FK conversation、server-normalized `llm_tool_call_id`、`provider_tool_call_id`（追蹤用）、工具名、遮罩後參數、目標摘要、risk_level、狀態（started/succeeded/failed/unknown）、HTTP 狀態與時間戳。跨 conversation 稽核查詢 MUST 以 `source_conversation_key` 為權威鍵；整數 ID 僅供診斷顯示。非 read 類工具 MUST 於 loopback **之前**的獨立交易寫入 started 紀錄並 commit，寫入失敗即中止執行（fail-closed）；狀態更新（succeeded/failed/unknown）於 loopback **之後**的另一交易 commit。系統 MUST NOT 持有交易跨越 loopback 呼叫。read 類工具日誌為 best-effort。既有 per-endpoint audit 照常由 loopback 觸發，作為輔助歸因。

#### Scenario: journal 起始紀錄於 loopback 前 commit
- **WHEN** 執行一個 mutation 工具
- **THEN** started 日誌在發出 loopback 前已於獨立交易 commit；loopback 完成後另一交易更新最終狀態

#### Scenario: journal 寫入失敗即中止 mutation
- **WHEN** 建立執行日誌起始紀錄時資料庫寫入失敗
- **THEN** 該 mutation 工具不執行，回合以明確錯誤收尾

#### Scenario: 對話刪除後仍可依不可重用 key 追查
- **WHEN** 對話被刪除（FK conversation_id 轉 NULL）後管理者查該對話的助手動作
- **THEN** 執行日誌可依不可變且不可重用的 source_conversation_key 查得全部 attempt、確認與成敗，不會混入後來重用整數 ID 的對話；參數中的機敏值已遮罩

### Requirement: 參數驗證、結果處理與 mutation 不確定性
executor SHALL 於呼叫前以 JSON Schema 驗證工具參數（未知/缺漏參數即拒絕，不發出 HTTP 請求）；工具結果 SHALL 先套用 output projection 與遮罩（見 assistant-data-boundary），再截斷至設定上限（預設 ~8k 字元）後附回 LLM。write 在 pending 前因 schema/team/credential 等驗證被拒時，MUST 先產生 server-normalized ID，並在同一交易持久化遮罩後 assistant tool call＋paired synthetic validation result；原始 credential 值不得進 messages/events/journal。可修正的 schema 錯誤可供 LLM 再規劃，其餘拒絕在 protocol-valid 收尾後終止。read 工具的 HTTP 錯誤 SHALL 映射為明確工具結果（403→權限不足、404→資源不存在、409→衝突、5xx→伺服器錯誤），401 MUST 終止回合並發出 session 過期的 `error` 事件。

mutation 一旦 journal started 已 commit 且準備發出 loopback，任何 timeout、task cancellation、transport exception、無回應或 HTTP 5xx 都 MUST 視為「副作用可能已發生」，將 pending 與 journal 標記 `unknown`、清除 execution payload、終結 continuation turn並釋放 lease，且 MUST NOT 自動重試。只有 executor 在發出 loopback 前拒絕，或工具矩陣明文列為 `definitive_pre_mutation_errors` 且既有 endpoint 契約保證尚未產生任何副作用的 4xx，才可標記 `failed`。mutation 2xx 才可標記 `confirmed`/`succeeded`。工具矩陣與 contract tests MUST 覆蓋每個 mutation 的 definitive failure allowlist；未列錯誤一律保守為 unknown。

#### Scenario: 參數不合 schema
- **WHEN** LLM 產生缺少必填欄位的工具呼叫
- **THEN** executor 不發出請求，以 normalized ID 同交易保存遮罩後 call 與 synthetic validation result，再將錯誤回給 LLM 修正

#### Scenario: credential write 在 pending 前安全拒絕
- **WHEN** write tool call 的參數包含禁止寫入的 credential value
- **THEN** 系統不建立 pending、不發出請求、不持久化原值，只保存遮罩後 call 與 paired synthetic rejection result後終止回合

#### Scenario: 外部 CI 已觸發但本地回寫失敗
- **WHEN** run_automation loopback 已呼叫 CI provider，之後 timeout、5xx 或本地 DB commit 失敗
- **THEN** pending 與 journal 進入 unknown，系統不自動重試並引導查詢 CI／run 狀態

### Requirement: 檔案上傳工具
上傳類工具（test case 附件、run item 結果檔）SHALL 以對話內的 file_ref 引用聊天暫存檔，由 executor 以 multipart loopback 呼叫既有上傳端點；file_ref MUST 驗證屬於本對話且未過期。

#### Scenario: 上傳附件到 test case
- **WHEN** 使用者附上截圖並要求附加到 TC-123
- **THEN** 助手呼叫 upload_test_case_attachment(case_id, file_ref)，executor 讀暫存檔 multipart 上傳，成功後回報附件 id

### Requirement: 複合寫入由 executor 內部編排
`batch_execute_actions` SHALL 是 registry 中的 internal composite tool，不對應公開 router，也不得包含自己或 read 工具。registry contract MUST 驗證其 child tool enum 精確涵蓋全部 loopback write 工具。executor 依使用者確認卡順序逐項呼叫既有 endpoint，整批共用原 pending 的 execution_key、journal 與單一 `tool_timeout_seconds` deadline；multipart 子動作仍以已驗證的對話 file_ref 取檔。每項結果套用原工具 projection／遮罩，aggregate 回報總數、已嘗試數、成功數、剩餘數及逐項 outcome。只有全部明確 2xx 才算 succeeded；任何 ambiguous outcome 立即停止後續、整批 unknown 且不得重試。

#### Scenario: 依確認卡順序執行
- **WHEN** composite 內有更新、歸檔與刪除等多種 action
- **THEN** executor 嚴格依卡片列出的順序執行，不重排、不平行化；後一 action 不得引用前一 response 才產生的值

#### Scenario: 中途結果不明停止批次
- **WHEN** 前兩項明確成功而第三項 transport timeout
- **THEN** 整批標 unknown，回報已知逐項結果與未嘗試數量，不執行第四項，也不重試前三項
