## Why

TCRT 同時要能跑在 SQLite（開發／既有部署）、MySQL 8 與 PostgreSQL 16（目標 server DB）。但目前同一個 Alembic head 在不同引擎上會產生**邏輯不一致的 schema**，使跨引擎搬遷（cross-engine migration）必須靠 `scripts/db_cross_migrate.py` 在搬資料當下臨時修補，而不是由 schema 本身保證一致。

兩個根因：

1. **Enum 以「名稱」儲存且產生原生具名型別**：多數 enum 欄位使用裸 `Enum(PyEnum)`，沒有 `values_callable`。這會在 MySQL 產生原生 `ENUM(...)`、在 PostgreSQL 產生 named type，並持久化 enum 的「成員名稱」。於是新增／改名一個 enum 值在 PostgreSQL 需要 `ALTER TYPE`、在 MySQL 需要 `MODIFY COLUMN`，但在 SQLite 卻是 no-op，造成保證會發生的跨引擎 drift。專案內 automation 相關 enum 已示範可攜寫法（`values_callable` 回傳 `.value`），應作為統一目標。

2. **大型文字型別與其驗證在引擎間不對稱**：model 端雖已用跨引擎的 large-text 型別（SQLite/PG 走一般 `TEXT`、MySQL 走 `MEDIUMTEXT`），但「把既有 legacy 欄位升級為 `MEDIUMTEXT`」的 migration 以 `dialect.name == 'mysql'` 設限、且開機自檢只在 MySQL 上驗證。結果是同一個 head 在不同引擎留下不一致的物理欄位歷史，且 drift 驗證只能片面地保證 MySQL。

此外，幾個「邏輯上必要」的限制並未由 schema 統一強制，而是被搬遷工具偽裝成功：必填 FK 在 legacy 資料中可能為 NULL、username 在 SQLite 大小寫敏感而在 MySQL/PG 唯一索引大小寫不敏感、孤兒列需於搬遷時過濾；以及搬遷工具在「以顯式 PK 載入」後**未重置 PostgreSQL sequence**，導致切換後第一筆 insert 可能撞鍵。

本變更的目的：讓 TCRT 的資料庫 schema 在 SQLite / MySQL 8 / PostgreSQL 16 三個引擎上產生**相同的邏輯 schema**，把目前散落在搬遷腳本與 MySQL-only 自檢中的隱性約束，收斂回 schema 與 migration 本身，使跨引擎搬遷可預測、可重複、且 drift 驗證能對稱地保持綠燈。

## What Changes

- 將主庫 model 中 15 個裸 `Enum(PyEnum)` 欄位改為**可攜的值儲存**（停用原生具名型別、改以儲存 enum 的字串值），對齊 automation enum 既有的可攜寫法；audit DB 的 3 個 enum 欄位同樣改為可攜寫法。轉換以**值穩定**為前提（持久化的字面值不改變語意）。
- 提供既有資料的相容遷移：把以「enum 名稱」儲存的舊值，轉為與新可攜定義一致的「enum 值」，三引擎皆能套用。
- 把 large-text 型別在三引擎間的對稱性補齊：保留 model 端「一次宣告、依方言變體」的型別來源，**退役 MySQL-only 的加寬 migration 與 MySQL-only 的開機自檢 gate**，改以引擎對稱的 drift 驗證確保一致。
- 將搬遷工具目前偽裝的邏輯約束改由 schema／migration 統一強制：
  - 必填 FK `test_cases.test_case_set_id` 以**回填 migration** 在三引擎上確保無 NULL，並使搬遷工具不再需要臨時修補。
  - **大小寫不敏感的 username 唯一性**由 schema 層一致定義，使 SQLite 與 MySQL/PG 行為一致，搬遷工具不再需要去重。
- 修正 `scripts/db_cross_migrate.py`：在以顯式 PK 載入資料後，**重置 PostgreSQL 各表 sequence** 至正確下一值，避免切換後首筆 insert 撞鍵。
- 收斂重複設定（降低後續 drift 風險）：將 4 份幾乎相同的 SQLite PRAGMA listener 與 3 份幾乎相同的 Alembic `env.py` 去重為共用來源。

非目標（Non-Goals）：

- 不把三套資料庫（主庫／audit／USM）合併為單一資料庫。
- 不更換搬遷機制；Alembic 仍是唯一的 schema 變更工具。
- 不調整任何 enum 的業務語意、不新增或移除 enum 成員；本變更只改變其**儲存表示法**。
- 不變更應用層讀寫 enum 的 Python API（model 屬性型別維持 PyEnum）。

## Capabilities

### New Capabilities

- `schema-engine-portability`: 定義 TCRT 資料庫 schema 在 SQLite / MySQL 8 / PostgreSQL 16 三引擎上必須產生相同邏輯 schema 的可觀察要求，涵蓋 enum 的可攜值儲存、large-text 型別的引擎對稱、邏輯必填約束的統一強制，以及跨引擎資料搬遷（含 PostgreSQL sequence 完整性）的正確性。

### Modified Capabilities

<!-- 不變更 database-migration / database-cutover-readiness 既有需求；本變更新增獨立的 portability capability，與其互補。 -->

## Impact

- **資料庫**：
  - 主庫 15 個 enum 欄位、audit 3 個 enum 欄位的儲存表示法改變（名稱 → 值）；需資料遷移把既有列的舊表示法就地轉換。MySQL/PG 上原生具名型別將不再被新 schema 要求。
  - 新增 `test_cases.test_case_set_id` 的回填 + NOT NULL 強制 migration。
  - username 唯一性改為大小寫不敏感的一致定義。
  - 退役 MySQL-only 的 text 加寬 migration 與開機自檢 gate（large-text 型別仍由 model 端依方言變體提供）。
- **後端**：
  - `app/models/database_models.py` 與 `app/audit/database.py` 的 enum 欄位宣告改為可攜寫法（不改 Python 層 enum 型別）。
  - `scripts/db_cross_migrate.py` 移除已不再需要的臨時修補（必填 FK 回填、username 去重、對應的孤兒過濾），並新增 PostgreSQL sequence 重置步驟。
  - 去重 SQLite PRAGMA listener 與 Alembic `env.py` 為共用來源。
  - 開機自檢／drift 驗證改為引擎對稱。
- **相容性**（migration / rollback / compatibility — 必填）：
  - **Migration**：所有變更以 Alembic revision 套用，可在 SQLite / MySQL 8 / PostgreSQL 16 上執行；enum 值轉換為冪等的資料更新，回填 migration 對已滿足約束的資料為 no-op。
  - **Rollback**：每支新 revision 提供對應 `downgrade`（enum 值轉換可反向、回填約束可降回 nullable、型別變更可還原）；資料層的值轉換以可逆映射定義，避免單向毀損。退役 MySQL-only 自檢屬行為移除，rollback 僅需恢復該 gate 呼叫。
  - **Compatibility**：Python 應用層讀寫 enum 的介面不變（屬性仍為 PyEnum）；既有 SQLite 部署升級後行為不退化；跨引擎搬遷在本變更後不再依賴腳本端臨時修補即可達成一致邏輯 schema。
