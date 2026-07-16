## 1. Automation sync portability

- [x] 1.1 新增 MySQL compile 與 NULL-first ordering regression tests
- [x] 1.2 將 pending run 排序改成跨引擎 CASE clauses

## 2. Migration verification and warning classification

- [x] 2.1 新增 orphan filtered-row 可通過與未知 row loss 仍失敗的 tests
- [x] 2.2 將 repair totals 傳入 row-count verification 並輸出 expected target / filtered rows
- [x] 2.3 將 legacy attachment 欄位改為 structured ignored source columns，未知欄位仍 warning
- [x] 2.4 精確抑制 SQLite expression-index reflection warning 並保留其他 SAWarnings

## 3. Duplicate index convergence

- [x] 3.1 新增 migration / metadata tests 覆蓋六組 duplicate indexes
- [x] 3.2 從 models 移除冗餘 index=True 並新增可逆 head migration
- [x] 3.3 在 disposable MySQL 驗證 upgrade 後 canonical indexes 存在且 duplicates 不存在

## 4. End-to-end verification and documentation

- [x] 4.1 以含 orphan history 與 legacy attachment 欄位的 SQLite fixture 跑完整 MySQL migrate workflow
- [x] 4.2 驗證 app health 與 automation sync query 在 MySQL 連續執行不含 NULLS FIRST error
- [x] 4.3 更新 MySQL migration runbook、執行 relevant gates 與 OpenSpec strict validation
- [x] 4.4 自審 diff、更新 Graphify 與 Obsidian worklog
