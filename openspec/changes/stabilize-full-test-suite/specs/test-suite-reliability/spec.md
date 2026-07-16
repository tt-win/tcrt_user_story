## ADDED Requirements

### Requirement: Regression tests MUST isolate ambient configuration
回歸測試 MUST 明確設定或清除其判斷所涉及的環境變數與 process-global 設定，不得因開發機、CI runner 或前一個測試已存在的合法設定而改變結果。

#### Scenario: QA model placeholder test runs with deployment overrides present
- **WHEN** process environment 原先含有 QA AI Helper stage model override
- **THEN** placeholder 測試先隔離該 override，再只驗證本案例建立的 YAML placeholder 與環境值
- **AND** 測試結束後原始 process environment 由 fixture 還原

#### Scenario: Container warning test follows another settings test
- **WHEN** container warning 測試在其他會改動設定或 logger state 的測試之後執行
- **THEN** 它仍捕捉到由本案例輸入觸發的完整警告

### Requirement: Cross-process lock tests MUST use an isolated lock namespace
跨行程 lock 測試 MUST 讓本案例啟動的所有子行程共用唯一測試 lock namespace，並與開發機或 CI 上不屬於本案例的 TCRT runtime lock 隔離；隔離不得改變 production 預設 lock identity。

#### Scenario: Developer server already holds the production leader lock
- **WHEN** 執行測試時另有 TCRT server 持有 production leader lock
- **THEN** 測試 holder 仍能取得本案例專屬 lock
- **AND** 測試不得停止、重啟或接管該既有 server

#### Scenario: Two test subprocesses compete in the same namespace
- **WHEN** holder 已取得本案例 lock，另一個測試子行程嘗試取得同一 namespace
- **THEN** 第二個子行程無法取得 leadership
- **AND** holder 結束後新子行程可取得 leadership

### Requirement: Shared application state MUST be restored after each test
使用 module-level FastAPI app、dependency override、singleton scheduler、permission cache 或 logging state 的測試 MUST 在案例結束時還原其修改，且案例結果不得依賴測試順序。

#### Scenario: State-sensitive test runs alone and in the full suite
- **WHEN** 同一個 state-sensitive test 分別單獨執行與在全套測試中執行
- **THEN** 兩種執行方式產生相同結果

### Requirement: Registry tests MUST assert capability instead of fixed cardinality
針對可擴充 registry 的測試 MUST 驗證必要項目、欄位與 registry/API 一致性，不得在產品契約未限制數量時寫死總筆數。

#### Scenario: A new scheduled service is registered
- **WHEN** scheduler registry 在既有 `lark_org_sync` 之外增加合法服務
- **THEN** scheduled-service list 測試仍驗證 `lark_org_sync` 存在且回應符合 registry
- **AND** 測試不因總數大於一而失敗

### Requirement: Full-suite stabilization MUST preserve failure detection
測試穩定化 MUST 修正根因或隔離前提，不得以 skip、xfail、刪除負向斷言、吞掉例外或終止外部程序來取得綠色結果。

#### Scenario: Stabilized baseline is verified
- **WHEN** 目標測試全部通過後執行 `uv run pytest app/testsuite -q`
- **THEN** 全套測試通過且沒有為本 change 新增 skip 或 xfail
- **AND** leader 互斥、權限拒絕、placeholder fail-fast 與 DB guardrail 的負向案例仍被驗證
