## 1. Setup Alembic (環境建置)

- [x] 1.1 新增 `alembic` 到 `requirements.txt`。(Add `alembic` to `requirements.txt`)
- [x] 1.2 執行 `alembic init -t async alembic` 產生初始目錄與配置檔。(Run `alembic init -t async alembic` to generate initial folder and config)
- [x] 1.3 修改 `alembic/env.py`，匯入專案的 `app.config.DATABASE_URL` 作為目標連線，並設定 `render_as_batch=True` 以支援 SQLite 批次遷移。(Modify `alembic/env.py` to use `app.config.DATABASE_URL` and enable `render_as_batch=True`)
- [x] 1.4 修改 `alembic/env.py` 匯入 `Base.metadata`，讓 Alembic 能夠偵測到現有的資料表結構。(Import `Base.metadata` in `alembic/env.py` for auto-generation)

## 2. Generate Baseline Migration (建立基準遷移腳本)

- [x] 2.1 確認目前開發環境的 SQLite `test_case_repo.db` 為乾淨或移除狀態，確保不會干擾。(Ensure local SQLite DB is clean before generating baseline)
- [x] 2.2 執行 `alembic revision --autogenerate -m "initial_schema"`，產生第一版的 Schema 建立腳本。(Run `alembic revision --autogenerate -m "initial_schema"` to create the baseline script)
- [x] 2.3 檢查產生的 migration script (`alembic/versions/xxx_initial_schema.py`)，確保沒有遺漏任何 Table 且語法正確無誤。(Review the generated migration script for accuracy)

## 3. Refactor `database_init.py` (重構初始化腳本)

- [x] 3.1 移除 `database_init.py` 中所有的 `CREATE TABLE` 或手動處理 `ALTER TABLE` 搬移資料的邏輯（如 `_migrate_users_email_to_nullable` 等）。(Remove all manual schema creation and migration logic from `database_init.py`)
- [x] 3.2 在 `database_init.py` 中引入 `alembic.command.upgrade`，將建表的責任交給 Alembic。如果無法透過 API 呼叫，則保留在 `start.sh` 呼叫指令。(Introduce `alembic upgrade head` API call in `database_init.py` to handle schema setup)
- [x] 3.3 保留並整理 `database_init.py` 中負責建立基礎資料（Seed Data，例如 Admin 帳號、預設 USM 等）的邏輯。(Preserve and cleanup the seed data creation logic for Admin user, etc.)

## 4. Update System Bootstrap (更新啟動腳本)

- [x] 4.1 更新 `start.sh`，在啟動 `uvicorn` 前，若有需要，加入 `alembic upgrade head` 指令（作為備援或主要遷移入口）。(Update `start.sh` to ensure `alembic upgrade head` runs before application starts)
- [x] 4.2 檢查 `database_sync_backup.py` 等其他可能會呼叫到資料庫建立的腳本，確保不再依賴 `Base.metadata.create_all` (測試環境除外)。(Update other scripts to stop relying on `create_all` for production flows)

## 5. Testing and Validation (測試與驗證)

- [x] 5.1 刪除本機的 `.db` 檔案，執行 `start.sh` 測試全新安裝，驗證資料表與 Admin 帳號皆正確產生。(Test fresh install by removing local `.db` and running `start.sh`)
- [x] 5.2 執行全專案的 Pytest 測試，確保測試環境 (conftest.py) 在建表行為的變更後仍能順利執行。(Run all Pytest test cases to ensure testing flow is not broken)
