## MODIFIED Requirements

### Requirement: 系統啟動與資料庫初始化
系統啟動時 (`start.sh` 或手動執行) SHALL 負責確保資料庫結構處於最新狀態，並寫入基礎的 Seed Data (例如系統管理員帳號與預設選項)。

#### Scenario: 啟動全新系統
- **WHEN** 在一個空的資料庫上執行啟動流程 (如 `sh start.sh`)
- **THEN** 腳本會先觸發 `alembic upgrade head` 建立所有的資料表結構，接著呼叫更新後的 `database_init.py` 來寫入預設的 Admin 帳號，最終順利啟動 Web 服務。

#### Scenario: 啟動已存在的系統
- **WHEN** 在已有資料的資料庫上執行啟動流程
- **THEN** 腳本會觸發 `alembic upgrade head` 將資料庫更新到程式碼定義的最新狀態，若無變更則跳過，隨後檢查 Seed Data (例如 Admin) 是否已存在，然後啟動 Web 服務，過程中不發生錯誤且保留原有資料。
