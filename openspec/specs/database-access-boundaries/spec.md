# database-access-boundaries Specification

## Purpose
定義 runtime、背景任務與離線工具應如何透過顯式資料存取邊界存取主庫、audit 與 USM 資料。

## Requirements
### Requirement: Runtime data access SHALL 經過顯式資料存取邊界
系統 SHALL 要求 runtime 資料存取經由 `app/db_access/` 等顯式邊界模組。

#### Scenario: API handler 讀取主庫資料
- **WHEN** API handler 需要讀寫主庫
- **THEN** 應透過受管 boundary 取得資料

#### Scenario: 背景任務寫入 audit 資料
- **WHEN** 背景任務需要寫入 audit DB
- **THEN** 應使用對應受管 boundary

### Requirement: Session lifecycle 與 transaction ownership SHALL 被集中治理
系統 SHALL 集中管理 session lifecycle 與 transaction ownership。

#### Scenario: Runtime 寫入流程成功完成
- **WHEN** 寫入流程成功
- **THEN** transaction 由受管邊界一致提交

#### Scenario: Runtime 寫入流程發生錯誤
- **WHEN** 寫入流程失敗
- **THEN** 由受管邊界負責 rollback 與清理

### Requirement: Multi-database coordination SHALL 經由顯式協調層
跨主庫 / audit / USM 的流程 SHALL 透過明確協調層處理。

#### Scenario: 同一流程需要更新主庫與 USM
- **WHEN** 同一工作流程跨兩個以上資料庫
- **THEN** 協調層負責排序、錯誤處理與一致性策略

### Requirement: Offline tools SHALL 重用受管資料存取邊界
離線工具與 migration / ETL 腳本 SHOULD 儘可能重用既有資料存取邊界，而非複製 runtime 存取邏輯。

#### Scenario: 執行離線 ETL 工具
- **WHEN** 離線工具需要讀取主庫或 USM
- **THEN** 重用既有邊界或相容抽象
