## Context

MySQL 8.0 cutover 演練顯示 runtime query、ETL verification、metadata reflection 與 index metadata 四個層次的跨引擎落差。最嚴重的是 `AutomationRun.last_synced_at.asc().nullsfirst()` 直接編譯成 MySQL 不支援的 `NULLS FIRST`，讓每次 background tick 都失敗。搬移工具則已明確選擇丟棄無法滿足 target FK 的 orphan history rows，卻沒有把該修補資訊傳給 row-count verification，導致正確執行的清理被誤判為資料遺失。

另外，來源 SQLite 可能帶有不屬於 Alembic head 的 legacy `test_cases` computed columns；SQLite functional index reflection 也會發出 SQLAlchemy warning，但正式 target schema 已由 Alembic 建立。最後，models 中六個欄位同時具有 `index=True` 與 custom single-column indexes，使 initial revision 與目前 head 都包含語意相同的重複 indexes。

## Goals / Non-Goals

**Goals:**

- background sync query 在 SQLite、MySQL 8、PostgreSQL 16 都可執行，且 NULL `last_synced_at` 仍優先。
- row-count gate 只接受由明確、結構化 repair 產生的 filtered rows；未解釋落差仍失敗。
- known source-only computed columns 與 functional-index reflection 不再製造誤導 warning，但保留可稽核 summary。
- Alembic head 與 model metadata 最終只保留每個索引用途的一份 physical index。

**Non-Goals:**

- 不把 orphan history rows 寫入 target，也不自動建立缺失的 parent rows。
- 不搬移 `attachment_count` / `has_attachments`；兩者是由附件關聯計算的 legacy cache 欄位。
- 不修改已發布的 `7a26d2522198` initial migration；fresh bootstrap 套用歷史 revision 時仍可能看到非致命 duplicate-index warning，直到 head migration 清理或未來正式 squash。
- 不改變 username functional unique index 契約；target index 仍由 Alembic 建立。

## Decisions

1. Pending sync 排序使用 `CASE WHEN last_synced_at IS NULL THEN 0 ELSE 1 END, last_synced_at ASC, id ASC`。
   - 理由：三引擎均支援，且完整保留 NULL-first 與 deterministic tie-breaker。
   - 未採用：按 dialect 動態選 `NULLS FIRST`；會增加 runtime 分支且容易再次漂移。
2. `copy_table_data()` 維持回傳 copied row count 的相容介面，但將 repair totals 放入既有 shared context；`run_job()` 把 per-table repair counts 與 filtered rows寫入 summary。
   - `skipped_orphan_item_refs` 是目前唯一可減少 expected target rows 的 repair key。
   - verification 使用 `expected_target_rows = source_rows - filtered_rows`；target 必須精確相等。
   - 任何未知 repair key不得默認為 filtered rows。
3. `validate_target_tables()` 只從 unexpected source-only columns 產生 warning；known legacy 欄位另寫入 `ignored_source_columns` summary。
4. Reflection 只 filter SQLAlchemy 的精確訊息 `Skipped unsupported reflection of expression-based index`；不廣泛關閉 `SAWarning`。
   - 理由：target schema 先由 Alembic 建立，搬移只需 table/column/FK metadata，不靠來源 expression index 建表。
5. 保留 models 中現有命名較明確的 custom indexes，移除相同欄位上的 `index=True`，並新增 head migration drop 六個 auto-named indexes。
   - 理由：不改 published history；head 收斂後減少寫入成本與 schema drift。
   - Downgrade 重新建立 auto-named indexes，不改資料。

## Risks / Trade-offs

- [錯把資料遺失當成 filtered row] → filtered rows 只來自 allowlist repair key，summary 同時保留 source、expected target、actual target 與 repair counts。
- [抑制 reflection warning 隱藏其他 index 問題] → filter 精確比對單一 SQLAlchemy 訊息，並由 Alembic verify 與 index tests驗證 target。
- [drop index 影響 query plan] → 每個被 drop index 都有相同 column sequence 的 custom replacement；migration 前後檢查 index columns。
- [fresh bootstrap 仍顯示 historical warning] → 不篡改已發布 revision；runbook 說明 warning 在新 head 清理後的 final schema 不存在重複 indexes。

## Migration Plan

1. 先部署程式與新 Alembic revision，但保持 app 停止寫入。
2. bootstrap main DB 至新 head；migration 只 drop 六個冗餘 indexes。
3. 驗證每個 canonical custom index 存在、auto-named duplicate 不存在。
4. 重新執行 SQLite → MySQL migrate workflow；確認 orphan repair 以 filtered rows 呈現且整體 row count match。
5. 啟動 app，至少跨兩個 background ticks 確認無 `NULLS FIRST` SQL error。
6. 若 index migration 需回退，執行 downgrade 重建六個 auto-named indexes；若 runtime 回退，資料 schema仍向後相容。

## Open Questions

無。
