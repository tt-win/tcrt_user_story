## Context

目前主庫已經透過 Alembic 與顯式 `validate/adopt/upgrade` 流程納入版本管理，但 `audit` 與 `USM` 仍在應用啟動時直接做 schema mutation。`audit` 透過 `create_all + ALTER TABLE` 補欄；`USM` 透過 `create_all + PRAGMA/rename/copy` 修表。這代表啟動程序同時兼任 schema migration executor，且兩套 auxiliary DB 沒有自己的 revision chain、沒有 legacy 驗證、也沒有 fail-fast 保護。

## Goals / Non-Goals

**Goals:**
- 讓 `audit` 與 `USM` 都和主庫一樣，以 Alembic 作為唯一正式 schema 管理方式。
- 對 `audit` 與 `USM` 提供顯式 `validate-legacy-*` 與 `adopt-legacy-*` 指令。
- 啟動流程在遇到未納管 auxiliary legacy DB 時直接拒絕啟動，而不是隱式修補。
- 抽出可重用的 migration target helper，避免三套 DB 各自複製一份邏輯。

**Non-Goals:**
- 不處理跨資料庫 ETL/資料搬遷。
- 不把三套資料庫合併成單一 schema 或單一 revision chain。
- 不改動 audit/usm 的業務模型與查詢語意。

## Decisions

1. **每套 DB 使用獨立 Alembic 環境**
   - 決定：保留現有主庫 `alembic/`，另外新增 `alembic_audit/` 與 `alembic_usm/`，各自搭配獨立 ini 檔與 versions 目錄。
   - Rationale：三套 DB 本來就是不同實體資料庫，各自獨立 revision chain 最清楚，也避免多 metadata / multi-base 的 Alembic 複雜度。
   - Alternative considered：單一 Alembic 環境管理三套 DB。放棄原因是 env.py、target_metadata、revision lineage 會更複雜，回滾與 adoption 也較難界定。

2. **將 migration helper 抽象成 target-based API**
   - 決定：在 `app/db_migrations.py` 引入可描述 `main/audit/usm` 的 target 定義，統一處理 URL 解析、baseline 查找、schema diff、adoption 與 upgrade。
   - Rationale：主庫目前已經有完整嚴格流程，直接抽象化可避免邏輯分叉。

3. **runtime initializer 不再負責 schema repair**
   - 決定：`init_audit_database()` 與 `init_usm_db()` 只保留 engine/session 初始化，不再執行 `create_all` 或手刻 `ALTER/PRAGMA` 修補。
   - Rationale：schema mutation 必須集中到 migration layer，否則會繞過嚴格版控。

4. **bootstrap 以 fail-fast 為原則**
   - 決定：`database_init.py` 依序處理 `main -> audit -> usm`。任何一套 DB 若是 unmanaged legacy，直接失敗並提示對應 adoption 指令。
   - Rationale：這與主庫現在的治理方式一致，避免啟動時默默改 schema。

## Risks / Trade-offs

- **[Risk] 舊有 audit/usm 資料庫可能與 model baseline 不完全一致** → Mitigation：先用 `compare_metadata` 列出差異，只有完全一致才允許 adoption。
- **[Risk] USM 先前靠 runtime repair 修表，移除後可能暴露歷史 drift** → Mitigation：以 baseline migration 明確定義現行 schema，並用 adoption validation 擋下不一致資料庫。
- **[Risk] 多一套 migration 環境增加維護成本** → Mitigation：將 helper 共用化，並在文件中固定新增 revision 的操作方式。

## Migration Plan

1. 新增 `alembic_audit/`、`alembic_usm/` 與對應 ini 檔。
2. 以現有 `AuditBase.metadata` 與 `USM Base.metadata` 建立 baseline revisions。
3. 重構 `app/db_migrations.py`，支援三套 target 的 validate/adopt/upgrade。
4. 更新 `database_init.py` CLI 與 `start.sh` bootstrap 順序。
5. 移除 audit/usm runtime schema mutation。
6. 驗證 fresh install、legacy adoption 與全量 pytest。

## Open Questions

- 無。這次延用主庫的嚴格治理原則，套用到另外兩套 DB。
