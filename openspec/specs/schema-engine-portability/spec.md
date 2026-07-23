# schema-engine-portability Specification

## Purpose
TBD - created by archiving change make-schema-engine-portable. Update Purpose after archive.
## Requirements
### Requirement: Identical logical schema across supported engines

系統 SHALL 確保同一個 Alembic head 在 SQLite、MySQL 8 與 PostgreSQL 16 上產生**相同的邏輯 schema**：相同的表與欄位集合、相同的欄位型別語意、相同的可空性與唯一性約束、相同的外鍵關係。物理層面允許各引擎的原生差異（如 MySQL 的 `MEDIUMTEXT`），但其邏輯意義 SHALL 一致。

#### Scenario: 三引擎套用同一 head 後邏輯 schema 一致

- **WHEN** 在 SQLite、MySQL 8、PostgreSQL 16 上分別套用同一個 Alembic head
- **THEN** 三者的邏輯 schema（表、欄位、型別語意、可空性、唯一性、外鍵）相同
- **AND** 任何引擎間的差異僅限於原生物理表示，不影響邏輯一致性

#### Scenario: 同一 head 不再產生引擎相依的邏輯差異

- **WHEN** 比對工具檢查三引擎在同一 head 下的邏輯 schema
- **THEN** 不存在「某欄位在某引擎為某邏輯型別、在另一引擎為不同邏輯型別」的差異
- **AND** 不存在「某約束只在部分引擎成立」的情形

### Requirement: Portable enum value storage

系統 SHALL 以**可攜的值表示法**持久化 enum 欄位（儲存 enum 的字串值，而非成員名稱），且 SHALL NOT 依賴引擎原生具名 enum 型別（MySQL `ENUM`、PostgreSQL named type）。新增或調整 enum 成員集合 SHALL NOT 需要在任一引擎執行 `ALTER TYPE` 或 `MODIFY COLUMN` 才能讀寫資料。應用層讀寫 enum 的 Python 介面 SHALL 維持不變。

#### Scenario: enum 以可攜值儲存且不使用原生具名型別

- **WHEN** 在 MySQL 8 或 PostgreSQL 16 上檢視 enum 欄位的型別
- **THEN** 該欄位不是引擎原生具名 enum 型別
- **AND** 欄位持久化的是 enum 的字串值

#### Scenario: 既有名稱表示法的資料被正確轉換

- **WHEN** 在含有以 enum 名稱儲存之舊資料的資料庫上套用本變更的資料遷移
- **THEN** 既有列被就地轉為與新定義一致的 enum 值表示法
- **AND** 名稱與值相同的 enum 其轉換為 no-op，名稱與值不同者依明確映射轉換
- **AND** 該遷移可反向 `downgrade` 回名稱表示法

#### Scenario: 新增 enum 值不需 DDL 變更

- **WHEN** 在三引擎中任一引擎新增一個 enum 值並寫入該值
- **THEN** 寫入與讀回成功，且不需事先執行 `ALTER TYPE` / `MODIFY COLUMN`

### Requirement: Uniform large-text type across engines

系統 SHALL 以單一型別來源宣告大型文字欄位，並依方言提供變體（SQLite 與 PostgreSQL 為一般 `TEXT`、MySQL 為 `MEDIUMTEXT`）。large-text 一致性的驗證 SHALL 對所有支援引擎對稱適用，SHALL NOT 僅在 MySQL 上驗證；亦 SHALL NOT 依賴 MySQL-only 的加寬步驟作為達成一致的唯一手段。

#### Scenario: large-text 型別由單一來源依方言決定

- **WHEN** 在三引擎上建立含大型文字欄位的表
- **THEN** 每個引擎得到其方言對應的文字型別（MySQL 為 `MEDIUMTEXT`，其餘為 `TEXT`）
- **AND** 該決策來自單一型別來源，無散落於各引擎的特例分支

#### Scenario: drift 驗證對所有引擎對稱

- **WHEN** 執行 large-text 一致性驗證
- **THEN** 驗證對 SQLite、MySQL 8、PostgreSQL 16 對稱適用
- **AND** 不存在僅針對 MySQL 的單邊 gate 才能通過的情形

### Requirement: Logically-required constraints enforced in schema

系統 SHALL 由 schema 與 migration 統一強制邏輯上必要的約束，而非由資料搬遷工具於搬遷當下臨時偽裝。必填外鍵 `test_cases.test_case_set_id` SHALL 在所有引擎上為 NOT NULL，並由回填 migration 處理既有 NULL 值。username 的唯一性 SHALL 在所有引擎上以**大小寫不敏感**方式一致成立。

#### Scenario: 必填 FK 在三引擎皆為 NOT NULL 且 NULL 被回填

- **WHEN** 在含有 `test_cases.test_case_set_id` 為 NULL 之既有資料的資料庫上套用回填 migration
- **THEN** 既有 NULL 依派生規則被回填為有效的 set
- **AND** 該欄位在三引擎上皆成為 NOT NULL
- **AND** 對已無 NULL 的資料，回填為 no-op

#### Scenario: username 大小寫不敏感唯一性跨引擎一致

- **WHEN** 嘗試建立僅大小寫不同的兩個 username（例如 `nikki` 與 `Nikki`）
- **THEN** 系統在 SQLite、MySQL 8、PostgreSQL 16 上一致地視為衝突
- **AND** 跨引擎搬遷不需在搬遷當下另行去重即可滿足唯一性

### Requirement: Cross-engine data migration correctness

系統 SHALL 確保跨引擎資料搬遷在邏輯 schema 一致的前提下完成，且不依賴搬遷腳本端臨時修補來達成正確性。當目標為 PostgreSQL 且以顯式主鍵載入資料後，系統 SHALL 將相關表的 identity / serial sequence 重置至正確的下一值，以保證後續插入不與既有主鍵衝突。

#### Scenario: PostgreSQL sequence 於顯式 PK 載入後被重置

- **WHEN** 以 `scripts/db_cross_migrate.py` 將資料以顯式主鍵載入 PostgreSQL 目標後
- **THEN** 受影響表的 sequence 被重置為大於現有最大主鍵的值
- **AND** 搬遷後對這些表插入新列不會與既有主鍵撞鍵

#### Scenario: 搬遷正確性不再依賴腳本端臨時修補

- **WHEN** 在邏輯 schema 已一致的資料庫間執行跨引擎搬遷
- **THEN** 必填 FK 回填、username 大小寫去重等正確性由 schema／migration 保證
- **AND** 搬遷流程於該等面向不需臨時修補即可完成並輸出一致性摘要

#### Scenario: sequence 重置僅作用於 PostgreSQL 目標

- **WHEN** 搬遷目標為 SQLite 或 MySQL
- **THEN** 系統不執行 PostgreSQL sequence 重置步驟
- **AND** 該等目標的搬遷行為不受影響

### Requirement: Alembic head SHALL avoid redundant equivalent indexes

main DB 的 Alembic head 與 SQLAlchemy model metadata SHALL NOT 對同一 table 的相同 column sequence 保留多個非必要 indexes。Published migration history SHALL 維持不可變；修正 SHALL 透過新的 forward migration 移除冗餘 indexes，並提供可逆 downgrade。

#### Scenario: 升級含重複單欄 indexes 的既有 main DB
- **WHEN** main DB 從舊 head 升級至本變更 head
- **THEN** 六個已知 auto-named duplicate indexes 被移除且 canonical custom indexes 保留
- **AND** table data、constraints 與 query-visible columns 不變

#### Scenario: Downgrade index cleanup migration
- **WHEN** 操作者 downgrade 本變更 revision
- **THEN** 六個 auto-named indexes 被重建，schema 回到升級前 index 集合

### Requirement: Cross-engine reflection SHALL distinguish known source-only metadata

跨引擎搬移 SHALL 將已知 legacy source-only computed columns 與未知 schema drift 分開處理。`test_cases.attachment_count` 與 `test_cases.has_attachments` SHALL 不搬移、但 SHALL 在 summary 中列為 ignored source columns；其他未知 source-only columns SHALL 繼續產生 warning。SQLite functional-index reflection 的已知 SQLAlchemy warning MAY 被精確抑制，target indexes SHALL 仍由 Alembic head 管理。

#### Scenario: SQLite source 含 legacy attachment computed columns
- **WHEN** source `test_cases` 比 target 多出 `attachment_count` 與 `has_attachments`
- **THEN** 搬移 summary 列出兩欄為 known ignored source columns
- **AND** 不將兩欄視為未知 schema drift，也不嘗試寫入 target

#### Scenario: Source 含未知額外欄位
- **WHEN** 任一 source table 含不在 allowlist 且 target 不存在的欄位
- **THEN** 搬移工具繼續輸出明確 warning，指出該欄位未搬移

#### Scenario: SQLite functional index reflection
- **WHEN** source schema 含 `lower(username)` expression-based index 且 target schema 已由 Alembic 建立
- **THEN** 搬移資料不依賴該 source index reflection
- **AND** 只抑制 SQLAlchemy 對 unsupported expression-index reflection 的特定 warning，其他 reflection warnings 保留

