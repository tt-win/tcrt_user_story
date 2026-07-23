## 1. Bootstrap 修正

- [x] 1.1 新增已存在目標 database 使用受限帳號時不連管理 database 的 regression test
- [x] 1.2 修改 database existence / auto-create 流程，僅在明確 missing-database error 時 fallback
- [x] 1.3 驗證既有自動建庫及一般連線錯誤行為未回歸
- [x] 1.4 遮蔽 cutover command、stdout/stderr、log 與跨庫 JSON summary 中的 DB 密碼

## 2. 端到端 MySQL 搬移驗證

- [x] 2.1 建立隔離 SQLite 三庫來源與非空 sentinel 資料
- [x] 2.2 使用 source / target env files 執行 SQLite → MySQL migrate workflow
- [x] 2.3 獨立覆核三庫 row counts、Alembic revisions、sentinel 資料與 app health

## 3. 文件與驗證

- [x] 3.1 撰寫不含 Docker 建置步驟的正式 MySQL migration / cutover runbook
- [x] 3.2 執行 targeted tests、Ruff、OpenSpec strict validation 與 graphify incremental update
- [x] 3.3 自我檢查 diff 並記錄 Obsidian worklog
