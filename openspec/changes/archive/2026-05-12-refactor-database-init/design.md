## Context

在目前的系統架構中，資料庫的初始化與版本遷移（Migration）由 `database_init.py` 負責。這個腳本當初是為了快速雛型開發而建立的，使用了許多直接對 SQLite 操作的語法（如使用 PRAGMA 判斷外鍵、手刻暫存表搬移資料來模擬 `ALTER TABLE`）。
隨著我們先前完成了基礎操作（CRUD、查詢）的抽象化，目前的瓶頸轉移到了啟動與建表階段。如果我們要讓應用程式能順利啟動並在 MySQL/PostgreSQL 建立正確的資料表與測試資料，我們必須廢棄這些針對 SQLite 限制的 Workaround，並導入業界標準的 SQLAlchemy 遷移工具 —— **Alembic**。

## Goals / Non-Goals

**Goals:**
- 引入 Alembic 並設定正確的目錄結構 (`alembic/`, `alembic.ini`)。
- 產生第一個基於當前 Model 的 Initial Migration Script，作為跨資料庫的基礎結構 (Baseline)。
- 大幅精簡 `database_init.py`，移除所有跟 Table 重建、資料搬移有關的手寫 SQL。
- `database_init.py` 將轉型為負責觸發 Alembic 升級 (Upgrade) 以及寫入必要種子資料 (如 admin 帳號、預設團隊) 的啟動腳本。
- 更新 `start.sh`，確保每次服務啟動前都會自動執行資料庫遷移。

**Non-Goals:**
- 不負責處理將現有 SQLite `.db` 檔案中的生產資料**遷移到另一個 MySQL 資料庫**的 ETL 工作。本次只確保「系統可以使用任一資料庫啟動並建立正確的 Schema」。

## Decisions

1. **引入 Alembic 的配置方式**
   *   **決定：** 使用 `alembic init -t async alembic` 初始化，因為專案的資料庫引擎已升級為 `aiosqlite`（異步模式）。
   *   **Rationale：** 因為 SQLAlchemy 的 engine 使用了 `async_engine`，Alembic 的 env.py 必須使用異步的方式載入連接並執行遷移，否則會發生事件迴圈的衝突或錯誤。

2. **`database_init.py` 的重構職責**
   *   **決定：** `database_init.py` 不再呼叫 `Base.metadata.create_all`，而是透過 Python API 呼叫 `alembic.command.upgrade(alembic_cfg, "head")`。完成 Schema 建立後，再執行原有的 Seed Data (如 admin 使用者建立) 邏輯。
   *   **Rationale：** 這樣可以保證無論是全新部署還是舊有部署，啟動流程都是統一的（Upgrade 到最新版本 -> 檢查必備資料）。避免 `create_all` 與 Alembic revision 產生衝突。

3. **支援不同的環境變數載入**
   *   **決定：** 在 `alembic/env.py` 中匯入我們現有的 `app.config`，使得 Alembic 的 `sqlalchemy.url` 可以直接吃到環境變數中的 `DATABASE_URL`，而不依賴寫死在 `alembic.ini` 的字串。
   *   **Rationale：** 這是 12-Factor App 的最佳實踐，確保 CI/CD 或 Docker 容器可以動態切換資料庫配置。

## Risks / Trade-offs

- **[Risk] 現有測試環境的干擾** → 許多現有的 Pytest 測試可能依賴 `Base.metadata.create_all` 來建立記憶體或暫存檔案資料庫。若強行改為 Alembic 升級，測試啟動可能會變慢。
  - **Mitigation：** 對於測試環境 (如 `conftest.py` 中)，可以保留使用 `create_all` 來加速建表，因為測試環境通常不需要關心歷史 Migration 紀錄；但生產/正式啟動流程必須嚴格走 Alembic。

- **[Risk] SQLite 欄位變更的限制** → 雖然 Alembic 支援了大部分操作，但 SQLite 依舊不支援某些 `ALTER TABLE`。
  - **Mitigation：** 在 `alembic/env.py` 中設定 `render_as_batch=True`。這是 Alembic 官方提供用來解決 SQLite `ALTER` 限制的機制，它會在底層自動幫我們做「建新表、搬資料」的動作，我們就不需要自己手寫 Workaround。

## Migration Plan

1. 安裝 `alembic` 套件。
2. 執行 `alembic init -t async alembic`。
3. 調整 `alembic/env.py` 讀取 `app.config.DATABASE_URL`。
4. 設定 `render_as_batch=True` 支援 SQLite。
5. 執行 `alembic revision --autogenerate -m "initial_schema"` 建立 baseline。
6. 修改 `database_init.py` 與 `start.sh`。