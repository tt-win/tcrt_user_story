## ADDED Requirements

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
