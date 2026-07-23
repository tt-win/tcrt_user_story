# assistant-efficient-tools Specification

## Purpose
TBD - created by archiving change optimize-assistant-context-and-tools. Update Purpose after archive.
## Requirements
### Requirement: 操作族與工具選擇優先序
助手工具與 skills MUST 支援下列操作族，並在 system prompt／skills 中規定優先序：**Discover（stats／count）→ Select-refs（slim id 列表）→ Mutate-by-id 或 Mutate-by-filter**；MUST NOT 將「無 filter 的 full projection 全量 list」作為批次指派或改結果的預設路徑。

#### Scenario: skill 指引批次指派
- **WHEN** 使用者透過 skill 或系統提示處理「把未指派 item 指給某人」
- **THEN** 指引路徑使用 statistics 或 refs／filter batch，而非先拉取完整 ITEM（含 title/comment）全列表

### Requirement: Test run item ref 列表工具
系統 SHALL 提供 read 工具（例如 `list_test_run_item_refs`）回傳精簡欄位集合，至少含：`id`、`test_case_number`、`test_result`、`assignee_name`。MUST NOT 在預設 projection 中包含 `title`、`comment`、attachments 或 execution result 明細。MUST 支援與 item list 同等的 filter 與 skip／limit。分頁列表 MUST 使用穩定排序（至少以 `id` 升序作為 tie-break），使 `skip`／`next_skip` 可重現。Assistant 省略 `limit` 時預設 MUST 為 100；不論模型是否傳入 `limit`，executor MUST 將 `limit` **clamp 到 ≤ 500**。

#### Scenario: 只取 id 以供指派
- **WHEN** 助手呼叫 item refs 工具並帶 `test_result` 或未指派類 filter
- **THEN** 回傳列僅含 ref projection 欄位，可供後續 batch_update 使用，且回應受 soft truncation 規則約束

#### Scenario: 模型傳入過大 limit 被 clamp
- **WHEN** 助手對 item refs 傳入 `limit=10000`
- **THEN** 實際請求 limit ≤ 500

### Requirement: Test case ref 列表工具
系統 SHALL 提供 read 工具（例如 `list_test_case_refs`）回傳精簡案例參考欄位（至少 `record_id`／等價主鍵與 `test_case_number`；不得預設包含 steps／precondition／expected_result／test_data 全文）。Assistant 省略 limit 時 MUST 注入預設 limit（≤ 50）；不論是否傳入，executor MUST 將 limit **clamp 到 ≤ 200**。

#### Scenario: 案例 ref 不含步驟全文
- **WHEN** 助手列出某 set 下案例 refs
- **THEN** 結果不含 steps／expected_result 全文

### Requirement: Full list 工具注入預設並 clamp 上限
對既有 full projection 的 `list_test_run_items` 與 `list_test_cases`：

1. 模型省略 `limit` 時，executor MUST 注入 assistant 預設 limit（各 ≤ 50）。
2. 模型傳入的 `limit` MUST 被 clamp：full items ≤ **100**、full cases ≤ **100**（assistant loopback 專用上限，低於後端 UI 允許上限）。
3. 此注入與 clamp MUST 僅影響助手 loopback，不得改變瀏覽器直接呼叫同一 API 時的預設或上限行為。

對其他可能回傳大型陣列的 read 工具（例如 `list_test_runs`、`list_test_run_sets`），若無既有分頁參數，仍 MUST 受 soft truncation 約束；tool description MUST 提示結果可能被截斷。

#### Scenario: 省略 limit 不拉 10000 筆 cases
- **WHEN** 助手呼叫 `list_test_cases` 且未傳 limit
- **THEN** 實際 loopback 請求帶 assistant 預設 limit（≤ 50），而非 API 的 10000 預設

#### Scenario: 模型指定超大 limit 被 clamp
- **WHEN** 助手呼叫 `list_test_cases` 且 `limit=50000`
- **THEN** 實際 loopback limit ≤ 100

### Requirement: 依 filter 批次更新 test run items
系統 SHALL 提供 high_impact write 能力，依對話 team 下之 `config_id` + **封閉 filter schema** 解析匹配 items，並批次套用封閉 patch（`assignee_name` 和／或 `test_result`；不得接受任意 SQL 或未宣告欄位）。

**Filter 語意（封閉）：**

- `test_result`：可選；枚舉含明確的未執行語意（例如 `null`／`pending` 以 schema 單值表示，不得語意模糊）。
- `assignee_unassigned`（bool）或等價封閉欄位：為 true 時僅匹配 assignee 為空／null；MUST NOT 與「字串相等空字串」 silently 混用未定義行為。
- `assignee_name`：可選精確匹配現有指派名。
- `search`：可選，行為對齊既有 item list search（標題／編號），長度與危險字元依既有 API 限制；查詢 MUST 走既有參數化／ORM 路徑，不得拼接 raw SQL。
- 互斥：`assignee_unassigned=true` 與非空 `assignee_name` 同時出現 MUST schema／驗證拒絕（fixable）。

**匹配與上限：**

- 匹配 MUST 在 server 端於 prepare pending 時解析；單次 matched **硬上限 500**；超過 MUST 422／fail-closed 且不建立可執行 pending。
- matched **0** 筆 MUST 拒絕建立 pending（明確錯誤），不得建立 count=0 的可確認 action。
- Confirmation summary MUST 含 server `matched_count`、filter 摘要、最多 10 個 sample ids（排序後取樣）。
- **stable membership digest**：fingerprint MUST 包含排序後完整 matched id 列表（或等價不可碰撞 digest）＋ filter 正規化＋ patch；confirm 時 MUST 重新 resolve；集合或 count 變更 MUST `CONFIRMATION_STALE`，不執行。
- MUST NOT 採信模型自報 count 或 id 列表作為執行集合（執行集合以 server resolve 為準；pending payload 存 server 解析結果）。
- 權限、team 歸屬、journal、mutation unknown 規則 MUST 與既有 `batch_update_results` 同等嚴格。

#### Scenario: filter 批次指派需確認且顯示 server count
- **WHEN** 助手請求將某 config 下未指派 items 指派給「Alice」且 server 匹配 37 筆
- **THEN** 系統建立 pending confirmation，摘要含 matched count=37 與 sample ids，使用者確認後才執行更新

#### Scenario: 超過 matched 上限被拒
- **WHEN** filter 匹配超過 500 筆
- **THEN** 不建立可執行 pending，並提示收窄 filter

#### Scenario: 匹配 0 筆被拒
- **WHEN** filter 匹配 0 筆
- **THEN** 不建立 pending，回可修正或明確錯誤

#### Scenario: confirm 前集合變更則 stale
- **WHEN** pending 建立後、confirm 前有 item 被改指派導致 matched 集合變化
- **THEN** confirm 回 CONFIRMATION_STALE（或等價），不執行 mutation

### Requirement: 每 turn 步驟上限提高且 continuation 重置
`max_iterations` 預設 MUST 為 24，env clamp 上界 MUST 至少 64。Confirm 成功後的 continuation turn MUST **重新從 0 計算** iteration，不得沿用 source turn 已消耗步數導致無法收尾。達上限時 MUST 以系統固定文案終止，不得讓模型無限循環。

#### Scenario: 預設 24 步
- **WHEN** 使用未覆寫 env 的預設設定
- **THEN** 單一 agent turn 最多 24 次 LLM 迭代後系統終止並提示達上限

#### Scenario: confirm 後可再規劃
- **WHEN** source turn 已用掉接近上限的 iterations 後建立 pending，使用者 confirm 成功
- **THEN** continuation turn 可再次執行最多 max_iterations 次迭代以產生後續讀取或最終回覆

### Requirement: Turn timeout 與較多步驟相容
`turn_timeout_seconds` 預設 MUST 不低於 300。Timeout 與 lease 續租行為 MUST 保持 fail-closed（逾時不留下可重放的半套 mutation 狀態，規則同既有 agent-loop）。

#### Scenario: 預設 turn timeout
- **WHEN** 使用未覆寫 env 的預設設定
- **THEN** turn 牆鐘逾時下限為 300 秒

### Requirement: 新工具納入 registry 封閉契約
所有新增 loopback 工具 MUST 登錄 tool registry：唯一名稱、method/path 可解析、permission、risk_level、projection allowlist、team resolver、confirmation metadata（write）、sensitive 欄位宣告、以及 list 類工具的 `default_limit`／`max_limit`（若適用）。載入測試 MUST 失敗於缺漏項。

#### Scenario: registry 驗證新工具
- **WHEN** 應用載入 tool registry
- **THEN** refs 與 filter-batch 工具通過與既有工具相同的契約測試，且 list 工具宣告 max_limit

