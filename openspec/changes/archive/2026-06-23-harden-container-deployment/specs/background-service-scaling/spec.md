## ADDED Requirements

### Requirement: Exactly one leader runs scheduled and automation jobs
系統 SHALL 確保跨多個 worker／副本時，排程器（scheduled service）與 automation 背景工作（run sync、script discovery）由**恰好一個** leader 行程執行；非 leader 的行程 SHALL NOT 啟動這些背景迴圈。leadership SHALL 以資料庫 advisory lock 取得（或由專責 worker 行程承載）。

#### Scenario: Only the leader starts background loops
- **WHEN** 多個應用程式行程同時啟動
- **THEN** 僅取得 leadership 的行程啟動排程器執行緒與 automation ticker
- **AND** 其餘行程不啟動排程輪詢，也不建立 automation 背景 task

#### Scenario: Scheduled jobs fire once across replicas
- **WHEN** 在 N 個副本下，一個排程服務（例如 Lark 組織同步）到達其執行時間
- **THEN** 該工作僅被執行一次（由 leader），而非每個副本各執行一次

#### Scenario: Automation run-sync fans out once
- **WHEN** automation run-sync ticker 到期
- **THEN** 僅 leader 行程執行同步與 webhook 扇出，避免重複扇出與互相覆蓋的寫入

### Requirement: Leadership recovers after the leader fails
系統 SHALL 在現任 leader 失效（行程結束或資料庫連線中斷）時釋放其 leadership，使另一個存活行程能取得 leadership 並接管排程／automation 背景工作，避免背景工作永久停擺。

#### Scenario: New leader takes over after crash
- **WHEN** 現任 leader 行程結束或失去資料庫連線，advisory lock 因而釋放
- **THEN** 另一個存活行程取得 leadership
- **AND** 排程與 automation 背景工作於新 leader 上恢復執行

#### Scenario: No double execution during handover
- **WHEN** leadership 由舊行程移轉至新行程
- **THEN** 任一時刻僅一個行程持有 leadership 並執行背景工作（不會同時兩個 leader）

### Requirement: Web tier scales without duplicate background execution
系統 SHALL 允許 web 服務層以多 worker／多副本部署而不重複執行背景工作；`WEB_CONCURRENCY=1` 的硬性限制 SHALL 被移除，因為背景執行的單例性已改由 leader election 保證，而非由限制 worker 數達成。

#### Scenario: Multiple web workers serve requests safely
- **WHEN** 部署將 `WEB_CONCURRENCY` 設為大於 1（或啟動多個副本）
- **THEN** 所有 worker 皆可服務 HTTP 請求
- **AND** 背景排程／automation 工作仍只在單一 leader 上執行，不隨 worker 數倍增

#### Scenario: Scaling does not duplicate webhook delivery
- **WHEN** web 層擴充為多副本且 automation 事件發生
- **THEN** 對外 webhook 僅扇出一次（來自 leader），不因副本數而重複送出
