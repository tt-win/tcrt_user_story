## MODIFIED Requirements

### Requirement: Runtime data access SHALL 經過顯式資料存取邊界
系統 SHALL 要求 runtime 資料存取與 transaction recovery 經由 `app/db_access/` 等顯式邊界模組；受管 boundary 之外的 runtime service SHALL NOT 直接 `commit()` 或 `rollback()`。

#### Scenario: API handler 讀取主庫資料
- **WHEN** API handler 需要讀寫主庫
- **THEN** 應透過受管 boundary 取得資料

#### Scenario: 背景任務寫入 audit 資料
- **WHEN** 背景任務需要寫入 audit DB
- **THEN** 應使用對應受管 boundary

#### Scenario: Runtime service handles an integrity conflict
- **WHEN** runtime service 的 flush 因唯一性衝突失敗
- **THEN** transaction recovery 由擁有 transaction 的受管 boundary 執行
- **AND** service 將衝突轉換成既有 domain/API error 而不直接 rollback session

#### Scenario: Runtime guardrail scan runs
- **WHEN** DB access guardrail 掃描 runtime 路徑
- **THEN** 掃描結果不含未核准的直接 session、commit、rollback 或 raw SQL 違規

### Requirement: Offline tools SHALL 重用受管資料存取邊界
離線工具與 migration／ETL 腳本 SHALL 優先重用既有邊界或 migration transaction；若工具因一次性維護、引擎限定或獨立 CLI transaction ownership 無法合理重用 boundary，則 MUST 在 DB access policy 以最小檔案範圍記錄為已核准例外，並由工具本身明確管理 commit／rollback 與失敗退出。

#### Scenario: 執行可重用 boundary 的離線 ETL 工具
- **WHEN** 離線工具需要讀取或修改主庫、audit 或 USM 資料且既有 boundary 可承載該流程
- **THEN** 工具重用受管邊界或相容抽象

#### Scenario: Engine-specific maintenance CLI owns its transaction
- **WHEN** 一次性 maintenance CLI 直接使用 SQLite connection 或獨立 SQLAlchemy session 且不在 web runtime 執行
- **THEN** policy 以精確檔案路徑記錄該例外及分類
- **AND** guardrail 不把未列入 policy 的新工具自動放行

#### Scenario: Approved offline tool fails during write
- **WHEN** 已核准的離線工具在寫入期間失敗
- **THEN** 工具 rollback 或由 transaction context 自動回復
- **AND** 以非零狀態退出且不宣告成功
