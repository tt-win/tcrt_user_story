## 1. P0: Portable enum value storage（主庫 + audit）

- [ ] 1.1 盤點主庫 `app/models/database_models.py` 15 個裸 `Enum(PyEnum)` 欄位與 `app/audit/database.py` 3 個 `SQLEnum` 欄位，逐一記錄目前的儲存表示法（成員名稱）與對應的 `.value`，確認是否存在 name 與 value 不一致的 enum。
- [ ] 1.2 將上述 enum 欄位改為可攜寫法（停用原生具名型別、改以 enum 值字串儲存），對齊 automation enum 既有的 `values_callable` 模式；保持 Python 屬性型別仍為 PyEnum。
- [ ] 1.3 撰寫主庫資料遷移 revision：將既有列以「名稱」儲存的 enum 值就地轉為「值」表示法；對 name 與 value 相同者為 no-op，對不同者建立明確的逐值映射。
- [ ] 1.4 撰寫 audit DB 對應的資料遷移 revision，套用相同的名稱→值轉換。
- [ ] 1.5 為兩支資料遷移 revision 補上可逆的 `downgrade`（值→名稱）。
- [ ] 1.6 在 SQLite 上產生／套用 migration，確認 model 與 migration 同步、drift 檢查通過。
- [ ] 1.7 在 MySQL 8 與 PostgreSQL 16 上套用同一 head，確認不再要求原生 `ENUM` / named type，且資料值轉換正確。

## 2. P0: Symmetric large-text type & retire MySQL-only widen path

- [ ] 2.1 確認三套 model（`database_models.py`、`audit/database.py`、`user_story_map_db.py`）的大型文字欄位皆以「一次宣告、依方言變體」的型別來源（SQLite/PG 為 `TEXT`、MySQL 為 `MEDIUMTEXT`）提供，無遺漏欄位。
- [ ] 2.2 將既有以 `dialect.name == 'mysql'` 設限的 text 加寬 migration 標記為 legacy-only，並改寫為由 model 型別來源統一決定（不再於各引擎留下不對稱的物理欄位歷史）。
- [ ] 2.3 退役 `database_init.py` 的 MySQL-only 開機自檢 gate（`verify_mysql_mediumtext_defaults`），改以引擎對稱的 drift 驗證涵蓋 large-text 一致性。
- [ ] 2.4 移除／調整僅針對該 gate 的測試，補上引擎對稱的 large-text 驗證測試。

## 3. P1: Enforce logically-required constraints in schema

- [ ] 3.1 撰寫回填 + NOT NULL 強制 migration：在三引擎上把 `test_cases.test_case_set_id` 的 NULL 依既有派生規則（由 section 反推 set；無 section 則用 team 預設 set）回填，並確保欄位為 NOT NULL；對已滿足者為 no-op。
- [ ] 3.2 將 `scripts/db_cross_migrate.py` 中 `test_case_set_id` 的臨時修補（`_repair_test_cases_payload`）改為僅在 schema 已保證時跳過，或移除其作為唯一保證的角色。
- [ ] 3.3 以 schema 層一致定義 username 的大小寫不敏感唯一性，使 SQLite 與 MySQL/PG 行為一致。
- [ ] 3.4 移除 `scripts/db_cross_migrate.py` 中因大小寫差異而存在的 username 去重（`_dedup_users_payload_case_insensitive`）與其連帶的孤兒過濾（`_filter_orphan_user_refs`）對「正確性」的依賴。
- [ ] 3.5 為兩支 schema 強制變更補上可逆 `downgrade`（NOT NULL 降回 nullable、唯一性定義還原）。

## 4. P1: PostgreSQL sequence integrity in cross-migrate

- [ ] 4.1 在 `scripts/db_cross_migrate.py` 以顯式 PK 載入完成後，針對 PostgreSQL 目標逐表將 identity / serial sequence 重置為 `max(pk) + 1`（或等效）。
- [ ] 4.2 僅對 PostgreSQL 目標執行 sequence 重置；SQLite / MySQL 目標不受影響。
- [ ] 4.3 新增測試：PG 搬遷後對受影響表插入新列不會與既有 PK 撞鍵。

## 5. P2: De-duplicate copied infrastructure

- [ ] 5.1 將 4 份 SQLite PRAGMA listener（`app/database.py` 兩處、`app/models/user_story_map_db.py`、`app/audit/database.py`）抽為單一共用 helper 並改為呼叫之。
- [ ] 5.2 將 3 份近乎相同的 Alembic `env.py`（`alembic/`、`alembic_audit/`、`alembic_usm/`）的共用邏輯抽為共用模組，各 `env.py` 僅保留目標差異設定。
- [ ] 5.3 確認去重後三套 migration 與 PRAGMA 行為與去重前一致（無回歸）。

## 6. Cross-engine verification

- [ ] 6.1 建立／更新跨引擎 schema 比對：對 SQLite / MySQL 8 / PostgreSQL 16 套用同一 head 後，比對邏輯 schema（表、欄位、型別語意、約束、唯一性）一致。
- [ ] 6.2 執行跨引擎搬遷 rehearsal（SQLite → MySQL、SQLite → PostgreSQL），確認不再依賴腳本端臨時修補即達成一致；輸出一致性摘要。
- [ ] 6.3 執行 `pytest app/testsuite -q` 相關測試全部通過。
- [ ] 6.4 確認 enum 新增值的流程：在三引擎上新增一個 enum 值不再需要 `ALTER TYPE` / `MODIFY COLUMN` 即可讀寫（可攜表示法驗證）。
