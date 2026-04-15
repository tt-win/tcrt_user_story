## Purpose

目前專案主要使用 SQLAlchemy 作為資料庫存取層，但有許多地方繞過了 ORM 直接寫原生 SQLite 語法 (如 `json_each`、`INSERT OR REPLACE`、`PRAGMA`) 或手刻 Migration 腳本。這破壞了資料庫的抽象化，導致未來若要切換到 MySQL 等其他資料庫將變得非常困難。本次重構的目的是將這些底層依賴消除，全面回歸 SQLAlchemy 的標準操作與通用的架構設計。

## Requirements

### 功能性需求
- 系統 SHALL 將 `app/database.py` 與其他資料庫連線初始化中的 SQLite `PRAGMA` 參數移除或抽象化，使其不會在非 SQLite 資料庫上拋出錯誤。
- 系統 SHALL 替換所有寫死 SQLite 語法的 SQL 查詢（例如 `test_case_repo_service.py` 中的 `json_each`），改用 SQLAlchemy 的標準函式或依資料庫動態產生的語法。
- 系統 SHALL 重構 `tcg_converter.py` 中的 `INSERT OR REPLACE` 語法，改用更通用的 Upsert 邏輯（如先 `SELECT` 後 `INSERT` 或 `UPDATE`，或是 SQLAlchemy 提供的標準 `dialects` 方法）。
- 系統 SHALL 移除模型定義中專屬於 SQLite 的參數（如 `sqlite_autoincrement=True`）。
- 系統 SHALL 具備兼容原本 SQLite 開發與測試環境的能力。

#### Scenario: 抽象化的資料庫連線
```gherkin
Given 系統設定連接至 MySQL 資料庫
When 系統啟動並建立資料庫連線池
Then 系統不會執行任何針對 SQLite 的 `PRAGMA` 指令
And 系統成功建立與 MySQL 的連線
```

#### Scenario: 抽象化的 JSON 陣列查詢
```gherkin
Given 系統需要查詢 JSON 欄位中的陣列內容
When 執行對應的 Repository 方法時
Then 系統會透過 ORM 或相容於當前資料庫方言的查詢語法來取得資料
And 系統不會出現 `json_each` 這類 SQLite 專屬的語法錯誤
```

## Non-Functional Requirements
- 所有的修改 MUST 保持原有邏輯的功能完整性，所有的 Unit Tests 與 Integration Tests 都必須通過。
- 資料庫連線配置必須支援同時透過環境變數設定不同的資料庫類型。

## What Changes

- 修改 `app/database.py`、`app/audit/database.py` 及 `app/models/user_story_map_db.py` 中初始化連線的事件監聽器。
- 修改 `app/services/test_case_repo_service.py` 中的 JSON 查詢邏輯。
- 修改 `app/services/tcg_converter.py` 的 Upsert 邏輯。
- 修改 `app/models/database_models.py` 的 Model 定義。
- 建立或更新通用抽象化的工具函式或資料庫支援。

## Capabilities

### Modified Capabilities
- `database-operations`: 將所有綁定 SQLite 的實作重構為跨資料庫的 SQLAlchemy 抽象化實作。

## Impact

- `app/database.py`
- `app/audit/database.py`
- `app/models/user_story_map_db.py`
- `app/services/test_case_repo_service.py`
- `app/services/tcg_converter.py`
- `app/models/database_models.py`
- 既有的測試案例 (Test Cases) 可能需要因應查詢方式的改變進行微調或驗證。
