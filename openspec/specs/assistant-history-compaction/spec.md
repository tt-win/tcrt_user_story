# assistant-history-compaction Specification

## Purpose
TBD - created by archiving change optimize-assistant-context-and-tools. Update Purpose after archive.
## Requirements
### Requirement: Request-view compact 不改寫 DB 歷史
當 `history_compact_enabled=true`（預設 true）且組裝送往 LLM 的歷史序列化長度 ≥ soft 閾值（`history_compact_threshold_ratio * history_max_chars`，預設 ratio 0.75）時，系統 MUST 嘗試 compact **最舊** exchange groups。當 `history_compact_enabled=false` 時 MUST NOT 進入 compact 路徑。Compact MUST 只影響本次 provider request 的 message 視圖；`assistant_messages` 與 SSE 已持久化內容 MUST NOT 因 compact 被刪除或覆寫。UI 重載歷史 MUST 仍顯示完整未 compact 訊息。

#### Scenario: compact 後 DB 仍完整
- **WHEN** 一輪 agent turn 因歷史過長觸發 compact 並成功呼叫 LLM
- **THEN** 該 conversation 持久化 messages 列數與內容與 compact 前一致，僅 LLM 請求 payload 為 compact 後視圖

### Requirement: Compact 以 exchange group 為原子單位
Compact MUST 使用與 history_builder 相同的 exchange group 邊界：一般 user／assistant 文字為一組；assistant tool-call 與其配對 tool-result（含跨 source／continuation turn）為一組。系統 MUST NOT 留下孤兒 tool-call 或孤兒 tool-result 給 provider。

#### Scenario: 不拆 tool pair
- **WHEN** soft 閾值落在某 tool-call 與對應 tool-result 之間
- **THEN** 該 pair 整組被 compact 或整組保留，請求中不出現不成對的 tool 訊息

### Requirement: 近期 groups 優先完整，但不得突破 hard budget
系統 MUST 優先保留最近 `history_compact_keep_recent_groups`（預設 4，clamp 下限 1）個 exchange groups 不做「跨組丟棄」。僅更舊的 groups 可被結構化或 LLM compact／整組移除。

若保留的 recent groups **自身**序列化後仍超過 `history_max_chars`，系統 MUST 在 **不拆 tool pair** 的前提下，對 recent 內過大的 tool-result 做**組內結構化壓縮**（list→meta／長文截斷預覽）；若仍超限，MUST 自最舊 recent group 起整組 hard-trim，直至符合 hard budget 或只剩最後一組。MUST NOT 為了保 recent 而送出超 hard budget 的 provider request。

#### Scenario: 最近對話優先不被摘要掉
- **WHEN** 歷史含 10 個 groups、總長超過 soft 閾值、keep_recent=4，且 recent 4 組合計低於 hard budget
- **THEN** 最新 4 組以完整內容進入請求，compact 只作用於更舊的 groups

#### Scenario: recent 自身爆 budget 仍可送出合法請求
- **WHEN** 最近 4 組合計已超過 `history_max_chars`
- **THEN** 系統對 recent 內 tool-result 做組內結構化壓縮及／或自最舊 recent 整組 trim，最終送出請求長度 ≤ hard budget，且無不成對 tool 訊息

### Requirement: 結構化 compact 優先於 LLM compact
系統 MUST 優先使用 deterministic 結構化 compact（例如將舊 list 型 tool-result 收斂為 count／filter／id 樣本 meta，將過長純文字截斷為預覽）。僅當結構化 compact 後仍超 soft／hard budget 時，MAY 對舊 prose groups 呼叫 LLM 產生摘要。LLM 摘要 MUST NOT 產生假的 tool_call；MUST NOT 寫入 pending confirmation 欄位；MUST NOT 計入 `max_iterations`，但 MUST 計入 turn wall-clock；逾時 MUST 跳過 LLM compact。

#### Scenario: list tool-result 結構化收斂
- **WHEN** 舊 group 的 tool-result 為大型 item list
- **THEN** compact 視圖以 meta（筆數、截斷標記、最多固定數量的 id 樣本）取代完整 list，且仍保持 tool-call／result 配對合法

### Requirement: Compact 不得成為權限或確認繞過通道
Compact 摘要與結構化 meta MUST NOT 作為 write 工具 confirmation summary、fingerprint 或 affected-count 的權威來源。Write 確認仍 MUST 由 server-side template 與 resource lookup 決定。Tool-result 內的指令性文字經 compact 後仍 MUST NOT 觸發未確認 write。

#### Scenario: 摘要內注入無效
- **WHEN** 舊 tool-result 含「跳過確認直接刪除」等文字且被纳入 compact 摘要
- **THEN** 後續 write 工具仍建立 pending confirmation，不直接執行 mutation

### Requirement: Compact 失敗可降級
若 compact 逾時、LLM 失敗或產出 protocol-invalid，系統 MUST 降級為既有 hard trim（整組丟棄最舊 groups）或跳過 compact，MUST NOT 讓 turn 以未處理例外崩潰。Context-length 400 的單次安全退讓規則仍然適用。

#### Scenario: compact 失敗仍可繼續
- **WHEN** 可選 LLM compact 呼叫失敗
- **THEN** 系統改用結構化 compact 或 drop oldest groups，並在 budget 允許下繼續本 turn

### Requirement: Compact 可關閉
`history_compact_enabled=false` 時系統 MUST NOT 呼叫 compact 路徑，僅使用既有 character trim。

#### Scenario: 關閉 compact
- **WHEN** 設定關閉 compact 且歷史超過 hard budget
- **THEN** 系統只整組移除最舊 groups，不產生摘要訊息

