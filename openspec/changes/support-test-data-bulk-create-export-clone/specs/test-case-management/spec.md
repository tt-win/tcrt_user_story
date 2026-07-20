## ADDED Requirements

### Requirement: 本地批次建立可攜帶 Test Data
系統透過本地 bulk create API 建立測試案例時，SHALL 允許每個 item 可選攜帶 Test Data，並持久化至該案例的本地 `test_data_json`。Test Data 的驗證與正規化 SHALL 與單筆建立路徑一致。此能力不依賴外部資料源同步。

#### Scenario: 批次建立寫入本地 Test Data
- **WHEN** 具備權限的使用者以 bulk create 建立含 Test Data 的測試案例
- **THEN** 資料僅寫入本地資料庫，且後續以本地讀取 API 可取得相同 Test Data 內容

### Requirement: 本地批次複製保留 Test Data
系統透過本地 bulk clone 複製測試案例時，SHALL 將來源案例的 Test Data 一併複製到新案例，使批次複製後的內容完整度與單筆詳情中的 Test Data 一致（在 clone 既有不複製附件/執行結果等邊界之外，Test Data 視為案例內容的一部分而必須複製）。

#### Scenario: 批次複製後新案例仍有 Test Data
- **WHEN** 使用者 bulk clone 一筆已含 Test Data 的本地測試案例
- **THEN** 新案例在本地可讀出與來源等價的 Test Data，且無需再從外部系統同步

### Requirement: Test Case Set CSV 匯出包含 Test Data
系統匯出某 Test Case Set 的 CSV 時，SHALL 包含 Test Data 欄位，使本地備份或搬移作業不遺失 Test Data。匯出為唯讀快照，不觸發外部同步。

#### Scenario: 匯出 Set 可取得 Test Data
- **WHEN** 使用者匯出含 Test Data 案例的 Test Case Set CSV
- **THEN** 下載的 CSV 中對應列包含可解析的 Test Data 內容
