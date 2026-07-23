# core-runtime-performance Specification

## Purpose
TBD - created by archiving change optimize-core-hot-paths. Update Purpose after archive.
## Requirements
### Requirement: 列表端點預設綁定回傳量

系統 SHALL 對清單型端點施加預設回傳量上限，避免單一請求載入整表。測試案例列表端點的預設每頁筆數 SHALL 為一個有界的小值（預設 100），且「忽略分頁、一次載入全部」的行為 SHALL 預設關閉；若提供該行為，SHALL 受明確上限或權限／旗標保護。系統 SHALL 維持既有分頁中繼資料語意（`X-Total-Count`／`X-Has-Next`，或 `with_meta` 的 `page` 物件）。

#### Scenario: 預設請求回傳量受限
- **WHEN** 呼叫測試案例列表端點且未指定 `limit`
- **THEN** 回傳列數不超過預設上限（100）
- **AND** 回應標頭 `X-Total-Count` 反映符合條件的總筆數
- **AND** `X-Has-Next` 正確指示是否尚有下一頁

#### Scenario: 全量載入預設關閉
- **WHEN** 呼叫端未明確要求全量載入
- **THEN** 系統不會忽略分頁回傳整表
- **AND** 回傳列數仍受預設上限約束

### Requirement: 列表預設回傳輕量投影且重欄位可選擇性載入

系統 SHALL 在清單回應中預設只回傳概覽（輕量）投影，**排除** `precondition`、`steps`、`expected_result`、`test_data`（`test_data_json`）與展開後的 `tcg`（`tcg_json`）等重欄位；產生輕量投影時 SHALL 不對這些重欄位做 JSON 解析或長文字展開。系統 SHALL 提供明確的 opt-in（例如 `fields=full` 或 `include_heavy=true`）讓既有消費端取回完整欄位。重欄位的完整內容 SHALL 仍可由單筆詳情端點取得。

#### Scenario: 預設列表不含重欄位
- **WHEN** 呼叫測試案例列表端點且未要求完整欄位
- **THEN** 回應項目包含概覽欄位（如 `test_case_number`、`title`、`priority`、`test_result`、區段資訊、時間戳）
- **AND** 回應項目不包含 `steps`、`expected_result`、`precondition`、`test_data` 等重欄位
- **AND** 系統未對重欄位執行逐列 JSON 解析

#### Scenario: 以 opt-in 取回完整欄位
- **WHEN** 呼叫端在列表請求帶入完整欄位旗標（如 `fields=full`）
- **THEN** 回應項目包含完整欄位（含重欄位），與既有行為相容

#### Scenario: 詳情端點仍回傳完整欄位
- **WHEN** 呼叫單筆測試案例詳情端點
- **THEN** 回應包含完整欄位（含 `steps`、`expected_result`、`precondition`、`test_data`）

### Requirement: 分頁中繼資料以單次查詢取得

系統 SHALL 以單次查詢同時取得分頁資料與總筆數／是否有下一頁，不得對同一組過濾條件先後執行獨立的計數查詢與資料查詢兩遍。

#### Scenario: 不重複掃描相同條件
- **WHEN** 列表端點需同時回傳資料列與總筆數中繼資料
- **THEN** 系統不會對相同 WHERE 條件先執行一次計數查詢、再執行一次資料查詢
- **AND** `X-Total-Count`／`X-Has-Next` 仍正確反映總量與分頁狀態

### Requirement: 請求處理不得在事件迴圈上執行阻塞式網路或 IO

系統 SHALL 確保任何 `async` 請求處理路徑上的出站網路呼叫與檔案串流不阻塞事件迴圈。對既有同步用戶端（Lark 附件下載代理與所有 Lark 出站呼叫）SHALL 以背景執行緒（`asyncio.to_thread`）或非同步用戶端（`httpx.AsyncClient`）執行；重試等待 SHALL 不在事件迴圈上同步休眠。

#### Scenario: 附件傳輸期間不阻塞其他請求
- **WHEN** 一個附件下載代理請求正在傳輸資料
- **THEN** 其他並發請求仍可被事件迴圈服務，不被該傳輸阻塞

#### Scenario: 出站 Lark 呼叫不阻塞事件迴圈
- **WHEN** 請求處理過程中發出 Lark 出站呼叫
- **THEN** 該呼叫不在事件迴圈執行緒上同步阻塞
- **AND** Lark 重試等待期間事件迴圈仍可服務其他請求

#### Scenario: async 路徑無同步網路殘留
- **WHEN** 檢視 `async` 請求處理路徑
- **THEN** 不存在於事件迴圈上直接執行的同步 `requests.*` 或 `time.sleep` 出站呼叫

### Requirement: 聚合統計於資料庫端計算

系統 SHALL 於資料庫端計算聚合統計，不得為取得分組計數而執行多次獨立的計數往返，亦不得為計算聚合而載入完整結果集再於應用層解析。測試執行統計的各狀態計數 SHALL 由單一分組查詢取得；bug ticket 去重計數 SHALL 以資料庫端 JSON 函式計算。

#### Scenario: 狀態計數以單一分組查詢取得
- **WHEN** 計算某 config 的測試執行統計（各狀態計數與比率）
- **THEN** 各狀態計數由單一 `GROUP BY` 查詢取得
- **AND** 不再對每個狀態分別發出獨立計數查詢

#### Scenario: Bug ticket 去重不載入全量
- **WHEN** 計算 bug ticket 去重數量
- **THEN** 去重計數由資料庫端 JSON 函式計算
- **AND** 系統不會為此載入所有符合的列再於應用層逐列解析 JSON

#### Scenario: 聚合結果與既有實作一致
- **WHEN** 以相同資料計算統計
- **THEN** 回應數值（total／executed／各狀態計數／各 rate／bug 計數）與舊實作一致

### Requirement: 已驗證請求的額外開銷有界

系統 SHALL 使每個已驗證請求的固定額外開銷有界，不得隨資料量或關聯數量無界扇出（fan-out）。每請求的使用者讀取 SHALL 由短 TTL 的處理快取覆蓋（比照既有 permission 快取模式），並於使用者停用／角色變更時失效。集合總覽類端點 SHALL 預載必要關聯，使查詢次數不隨集合數量線性成長（消除 N+1）。

#### Scenario: 使用者讀取由短 TTL 快取覆蓋
- **WHEN** 同一使用者在 TTL 時窗內連續發出多個已驗證請求
- **THEN** 系統在該時窗內僅查詢使用者表一次
- **AND** 使用者停用或角色變更後，於快取失效後立即生效

#### Scenario: 集合總覽無 N+1
- **WHEN** 取得 Test Run Set 總覽且存在多個 set
- **THEN** 查詢次數不隨 set 數量線性成長（關聯以單次預載取得）

#### Scenario: 圖譜邊建構不隨節點數平方成長
- **WHEN** 由節點動態建構 User Story Map 的邊
- **THEN** 系統以單次掃描建立鄰接關係
- **AND** 計算成本不呈節點數的平方成長

### Requirement: 稽核寫入不在請求回應路徑上

系統 SHALL 將稽核寫入移出請求回應路徑，請求回應 SHALL 不等待稽核落地；高風險動作（如 DELETE）SHALL 不再於請求路徑上強制同步 flush。系統 SHALL 仍保證稽核最終落地（既有批次門檻 + 關機／顯式 `force_flush`），不遺失事件。

#### Scenario: DELETE 回應不等待稽核 flush
- **WHEN** 使用者發出會被稽核的 DELETE 請求
- **THEN** 回應不等待稽核寫入或同步 flush 完成

#### Scenario: 稽核最終落地不遺失
- **WHEN** 稽核事件以背景批次處理
- **THEN** 事件於既有批次門檻內落地
- **AND** 關機前或顯式 `force_flush` 時緩衝中的事件全部寫入，不遺失

