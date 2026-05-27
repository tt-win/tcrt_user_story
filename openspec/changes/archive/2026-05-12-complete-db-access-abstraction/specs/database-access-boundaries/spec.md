# database-access-boundaries Specification

## Purpose
定義 `main`、`audit`、`usm` 三套資料庫在 runtime、background tasks 與 offline tools 中的顯式存取邊界、session ownership 與跨資料庫協調規範，避免未來切換資料庫時再次逐檔追查散落的 ORM 與 SQL 存取。

## Requirements
### Requirement: Runtime data access SHALL 經過顯式資料存取邊界
系統 SHALL 為 `main`、`audit`、`usm` 三套資料庫提供顯式的資料存取邊界，並要求 API handler、application/domain service 與 background task 透過該邊界執行讀寫。 Runtime caller MUST NOT 直接持有 `AsyncSession`、ORM query 或 `commit` / `rollback` 細節。

#### Scenario: API handler 讀取主庫資料
- **WHEN** 任一 API handler 需要查詢或更新主庫資料
- **THEN** handler 透過受管的 `main` access boundary 取得結果，而不是直接建立 session 或組裝 ORM query

#### Scenario: 背景任務寫入 audit 資料
- **WHEN** 背景任務需要寫入 audit database
- **THEN** 任務透過受管的 `audit` access boundary 執行寫入，而不是在任務本體內直接 `add` / `commit`

### Requirement: Session lifecycle 與 transaction ownership SHALL 被集中治理
系統 SHALL 將 session 的建立、關閉、commit、rollback 與 sync fallback 集中治理於 boundary/provider/unit-of-work 層。 Runtime code outside the managed boundary MUST NOT 直接呼叫 `SessionLocal()`、`get_async_session()`、`commit()` 或 `rollback()`。

#### Scenario: Runtime 寫入流程成功完成
- **WHEN** 受管 boundary 完成一個需要寫入資料的 runtime 流程
- **THEN** transaction 由 boundary/provider 負責提交，且 caller 不需要自行處理 session close 或 commit

#### Scenario: Runtime 寫入流程發生錯誤
- **WHEN** 受管 boundary 內的資料寫入失敗
- **THEN** rollback 由同一個受管 transaction owner 負責執行，且錯誤不需要 caller 透過直接 session 操作補救

### Requirement: Multi-database coordination SHALL 經由顯式協調層
系統 SHALL 將同時觸及 `main`、`audit`、`usm` 的流程收斂到顯式的 orchestration/coordinator 層。 Handler 或單一 boundary MUST NOT 直接混用多套資料庫 session；每一個 boundary 只負責自己的資料庫。

#### Scenario: 同一流程需要更新主庫與 USM
- **WHEN** 某個業務流程同時需要更新 `main` 與 `usm`
- **THEN** 該流程由顯式協調層編排兩個 boundary 的呼叫順序與失敗處理，而不是在單一 handler 內直接混用兩個 session

#### Scenario: 跨庫流程失敗
- **WHEN** 跨資料庫流程在部分步驟完成後失敗
- **THEN** 系統透過協調層定義的補償或 rollback 指引處理，而不是依賴隱式共享 transaction

### Requirement: Offline tools SHALL 重用受管資料存取邊界
系統 SHALL 讓 `scripts/`、`ai/` 與維運工具透過 target-aware 的設定與受管 access boundary 存取資料庫，而不是直接綁定 SQLite 檔案路徑、隱式 session factory 或各工具自行推導 driver/dialect。

#### Scenario: 執行離線 ETL 工具
- **WHEN** 離線 ETL 或資料修補工具需要讀寫主庫資料
- **THEN** 工具透過受管的 target-aware boundary 存取資料庫，且可在 SQLite、MySQL 或 PostgreSQL 設定下重複執行

#### Scenario: 執行 AI 工具讀取多資料庫
- **WHEN** `ai/` 內的工具需要讀取 `main` 或 `usm`
- **THEN** 該工具使用與 runtime 一致的設定解析與資料存取契約，而不是直接假設本機 `.db` 檔案存在
