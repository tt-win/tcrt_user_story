# Design: make-schema-engine-portable

本變更跨 SQLite / MySQL 8 / PostgreSQL 16 三引擎，且涉及既有資料的就地轉換，故需要明確的相容性與回滾設計。本文聚焦四件事：enum 與 large-text 的遷移相容性、既有「enum 名稱」資料的轉換、rollback 策略，以及 drift 驗證如何持續保持綠燈。

## 現況基準（已驗證）

- **Enum**：主庫 `app/models/database_models.py` 有 15 個裸 `Enum(PyEnum)` 欄位（無 `values_callable`），`app/audit/database.py` 有 3 個 `SQLEnum` 欄位。這些會在 MySQL 產生原生 `ENUM(...)`、在 PostgreSQL 產生 named type，並持久化 enum 的**成員名稱**。專案內 automation 相關 enum 已採可攜寫法（`values_callable=lambda values: [item.value for item in values]`），作為統一目標。
- **Large-text（重要前提）**：三套 model 其實**已**透過 `from ..db_types import MediumText as Text` 將 `Text` 別名為依方言變體的型別（SQLite/PG → `TEXT`、MySQL → `MEDIUMTEXT`）。因此「型別宣告」面向已大致到位；真正的不對稱在於：把 legacy 欄位升級到 `MEDIUMTEXT` 的 migration 以 `dialect.name == 'mysql'` 設限，且開機自檢 `verify_mysql_mediumtext_defaults`（`database_init.py:214`）只在 MySQL 上跑。本變更不重複宣告型別，而是**消除驗證與 legacy 加寬路徑的引擎不對稱**。
- **被搬遷工具偽裝的約束**：`scripts/db_cross_migrate.py` 內 `_repair_test_cases_payload`（必填 FK 回填）、`_dedup_users_payload_case_insensitive`（username 大小寫去重）、`_filter_orphan_user_refs`／`_filter_test_run_item_result_history_payload`（孤兒過濾），以及**缺少 PostgreSQL sequence 重置**（全檔 `setval` 出現次數為 0）。

## Enum 遷移相容性

設計關鍵在於把「儲存表示法從名稱換成值」與「Python 介面不變」兩件事解耦。

- **宣告層**：欄位改為可攜寫法（停用原生具名型別／改以 `values_callable` 儲存 `.value`）。Python 屬性型別仍為對應的 PyEnum，應用層讀寫不變。
- **儲存層**：MySQL 不再要求原生 `ENUM`，PostgreSQL 不再要求 named type，欄位以一般字串值持久化。這正是「新增 enum 值不需要 `ALTER TYPE` / `MODIFY COLUMN`」得以成立的原因。
- **name vs value 對映**：任務 1.1 要先逐 enum 確認 name 與 value 是否一致。
  - 若某 enum 所有成員的 `name == value`（常見於以字串值定義的 enum），資料轉換為 no-op，僅 DDL 從具名型別轉為字串欄位。
  - 若 name 與 value 不同，需建立**逐值對照表**，於資料遷移中將舊的名稱字面值更新為新的值字面值。
- **DDL 變更的引擎差異**：在 MySQL/PG 上，從原生具名型別轉為字串欄位是型別變更；SQLite 透過 Alembic batch 模式處理（既有 spec 已要求 `render_as_batch=True`）。三引擎以同一 revision 表達，差異交由 Alembic dialect 處理。

## Large-text 遷移相容性

- 不更動既有的 model 型別來源（`MediumText` 變體）。
- 將 MySQL-only 的加寬 migration 標記為 legacy-only：其存在只是為了把「在型別別名落地之前就建立」的舊 MySQL 欄位補成 `MEDIUMTEXT`；新建資料庫由型別來源直接決定，不需該步驟。
- 退役 `verify_mysql_mediumtext_defaults` 這個 MySQL-only gate，改由引擎對稱的 drift 驗證涵蓋 large-text 一致性（見下節）。此為行為移除，對資料無破壞性。

## 既有 enum-name 資料的資料遷移

- 主庫與 audit DB 各一支**資料遷移 revision**，與宣告層變更同批或緊接其後。
- 遷移內容為**冪等的逐值 UPDATE**：對每個受影響欄位，將舊表示法（名稱）映射為新表示法（值）。對 name==value 的欄位為 no-op。
- 遷移以資料庫無關的方式表達（透過 Alembic 操作或參數化 SQL），確保三引擎皆可套用。
- 順序：先確保資料值符合新可攜定義，再讓欄位型別不依賴原生具名型別，避免「值已存在但型別仍受限」的中間態造成寫入失敗。

## Rollback 策略

每支新 revision 都提供可逆 `downgrade`，且資料轉換採**可逆映射**以避免單向毀損：

- **Enum 值轉換**：`downgrade` 以反向對照表把值轉回名稱；name==value 者為 no-op。宣告層可還原為原生具名型別。
- **Large-text**：退役 gate 的 rollback 僅需恢復 `verify_mysql_mediumtext_defaults` 的呼叫；legacy 加寬 migration 的標記可還原。型別來源未變，故無資料風險。
- **必填 FK**：回填 migration 的 `downgrade` 將欄位降回 nullable；已回填的值不刪除（回填值是合法資料，刪除反而有害），符合「向後相容、不破壞資料」原則。
- **username 唯一性**：`downgrade` 還原唯一性定義。注意：若在大小寫不敏感唯一性生效後產生過資料，downgrade 不會也不應重新引入大小寫重複；rollback 著重於約束定義還原而非資料回灌。
- **搬遷腳本變更**：`scripts/db_cross_migrate.py` 的修補移除與 sequence 重置屬程式行為，不是 schema 版本，rollback 透過版本控制還原檔案即可。

## Drift 驗證如何持續綠燈

drift 驗證是本變更「一致性」承諾的守門員，設計上要避免它在轉換過程中誤報或片面通過：

- **同步性**：宣告層改寫後，需在 SQLite 上重新產生／對齊 migration，使 model 與 migration 一致（任務 1.6）；這是既有開機 drift 檢查的前提。
- **引擎對稱**：把 large-text 與 enum 的一致性檢查改為對三引擎對稱適用，取代 MySQL-only gate。驗證比對的是**邏輯 schema**（型別語意、可空性、唯一性、外鍵），允許 `MEDIUMTEXT` vs `TEXT` 這類已知物理變體，不將其判為 drift。
- **跨引擎比對**：任務 6.1 對三引擎套用同一 head 後比對邏輯 schema；任務 6.4 驗證「新增 enum 值不需 DDL」這個可攜性的可觀察結果。
- **搬遷 rehearsal**：任務 6.2 以 SQLite → MySQL、SQLite → PostgreSQL 的 rehearsal 確認在 schema 已一致後，不再依賴腳本端臨時修補即可完成，並輸出與既有 `database-migration` / `database-cutover-readiness` 一致的一致性摘要，避免與這兩個既有 capability 的要求衝突。

## 與既有 capability 的關係

- 不變更 `database-migration`（Alembic 為唯一工具、batch 模式、preflight、一致性摘要）與 `database-cutover-readiness`（smoke / rehearsal / rollback 準備）的既有需求；本變更新增的 `schema-engine-portability` 與其互補：前者管「遷移如何被執行與驗證」，本變更管「schema 本身在三引擎是否邏輯一致」。
- 因此本變更輸出的跨引擎比對與 rehearsal 摘要，刻意對齊上述既有流程的「一致性摘要」概念，便於併入既有 cutover 判斷。
