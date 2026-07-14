# Tasks — add-boot-upgrade-backup-rollback

實作前請先讀 `design.md`（決策 D1–D9 為本清單的規格依據）與 `database_init.py:469-525`（`bootstrap_target`）、`database_init.py:824-857`（main 迴圈）、`app/db_migrations.py:368-421`（revision helpers）、`app/runtime_locks.py:79-125`（bootstrap_lock）。

## 1. Pending 偵測（design D1）

- [x] 1.1 在 `app/db_migrations.py` 新增 `PendingStatus` dataclass（欄位：`target: str`、`current: str | None`、`head: str`、`is_pending: bool`、`is_fresh: bool`）與 `get_pending_status(target_name: str) -> PendingStatus`：`current` 用既有 `_get_current_revision(resolve_database_url(target_name))`、`head` 用 `_get_head_revision(build_alembic_config(target_name))`；`is_fresh` 定義為 `current is None` 且該 DB 中 `TARGET_REQUIRED_TABLES[target_name]`（自 `database_init.py` 傳入或搬到共用處）沒有任何一張表存在（用 `sqlalchemy.inspect(engine).get_table_names()`）。
- [x] 1.2 單元測試 `app/testsuite/test_bootstrap_pending_detection.py`：(a) 空白 SQLite → `is_fresh=True, is_pending=True`；(b) upgrade head 後 → `is_pending=False`；(c) 手動把 `alembic_version` 改為舊 revision → `is_pending=True, is_fresh=False`；(d) 有業務表但無 `alembic_version` 表（legacy）→ `is_fresh=False, is_pending=True`。

## 2. 備份模組 `app/db_backup.py`（design D2/D3）

- [x] 2.1 建立 `app/db_backup.py`：`BackupResult` dataclass、`create_backup(target_name, pending, backup_dir) -> BackupResult`、`restore_backup(result) -> None`、`apply_retention(backup_dir, target_name, keep) -> list[Path]`。引擎判別用 `make_url(url).get_backend_name()`（對齊 `app/runtime_locks.py:51` 的寫法）。檔名格式與 sidecar `.meta.json` 內容依 design D2 逐字實作。
- [x] 2.2 SQLite 備份：`sqlite3.connect(src)` 後 `src_conn.backup(dst_conn)`；還原為反向 backup ＋ 刪除目標旁 `-wal` / `-shm` 檔。
- [x] 2.3 MySQL 備份：`shutil.which("mysqldump")` 檢查 → 組 argv（`--single-transaction --no-tablespaces --add-drop-table --routines --host --port --user <database>`，密碼放 `env={"MYSQL_PWD": ...}`）→ stdout 經 `gzip.open` 寫入目標檔；`subprocess.run(..., check=True)` 失敗時拋 `BackupError`（新增之例外類別）。
- [x] 2.4 MySQL 還原：以 SQLAlchemy 連線 `SET FOREIGN_KEY_CHECKS=0` 後枚舉 `information_schema.tables WHERE table_schema=<db> AND table_type='BASE TABLE'` 逐一 `DROP TABLE`；再 `shutil.which("mysql")` 檢查後以 `mysql` client 重放 gunzip 內容（stdin pipe，密碼同樣走 `MYSQL_PWD`）。
- [x] 2.5 PostgreSQL 備份：`pg_dump --format=custom --file <path> --host --port --username <database>`，密碼走 `PGPASSWORD`。
- [x] 2.6 PostgreSQL 還原：以應用連線執行 `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` 後 `pg_restore --no-owner --host ... --dbname <db> <path>`。
- [x] 2.7 `apply_retention`：列出 `<backup_dir>/<target>/` 下符合命名格式的備份，依檔名時戳降序保留前 N，刪除其餘（含 sidecar），回傳刪除清單。
- [x] 2.8 單元測試 `app/testsuite/test_db_backup.py`：SQLite create/restore 往返（含 WAL 模式資料庫）、retention 邊界（N=1、恰好 N、超過 N）、檔名/sidecar 格式、缺 client 時拋 `BackupError`（用 monkeypatch 讓 `shutil.which` 回 None）。MySQL/PG 的 dump-restore 整合測試放 `app/testsuite/test_db_backup_server_engines.py`，比照既有 mysql/postgres smoke 測試的 skip 條件（無對應 env/service 時 skip）。

## 3. 政策解析與 failure marker（design D5/D7）

- [x] 3.1 在 `database_init.py` 新增 `read_bootstrap_policies() -> BootstrapPolicies`（dataclass）：解析 `BOOTSTRAP_BACKUP_DIR`（預設 `PROJECT_ROOT / "db_backups"`；`PROJECT_ROOT` 取 `Path(__file__).resolve().parent`）、`BOOTSTRAP_BACKUP_MODE`（非法值 → 明確錯誤 exit 2）、`BOOTSTRAP_BACKUP_RETENTION`（int ≥1）、`BOOTSTRAP_ON_FAILURE`、`BOOTSTRAP_MAX_UPGRADE_ATTEMPTS`；CLI `--no-backup` 覆寫 mode 為 `off`。
- [x] 3.2 marker 讀寫函式（可放 `app/db_backup.py`）：`read_failure_marker(backup_dir, target)`、`record_upgrade_failure(backup_dir, target, head, from_rev, error, rolled_back)`（存在且同 head 則 attempts+1，否則重建 attempts=1）、`clear_failure_marker(backup_dir, target)`。檔案路徑與 JSON 欄位依 design D7。
- [x] 3.3 CLI 旗標 `--clear-failure-markers`：刪除三個 target 的 marker 後 return 0（加進 `database_init.py` 的 argparse 與 main() 分支，放在 bootstrap_lock 之外即可）。
- [x] 3.4 單元測試（併入 `test_db_backup.py` 或獨立檔）：attempts 累加、head 改變重計、清除、達上限判定。

## 4. 主流程整合（design D6/D8/D9）

- [x] 4.1 重構 `database_init.py` main() 的 bootstrap 分支（`:824-857`）為 design D8 的流程：先全 target 檢查 marker（達上限 → exit 10）；逐 target `get_pending_status` → 無 pending 走 verify-only（沿用 `--skip-migrations` 分支既有的驗證鏈：`verify_required_tables` + `verify_mysql_mediumtext_defaults` + main 的 automation key 檢查）→ 有 pending 依政策備份 → upgrade + 驗證鏈 → 成功即 `clear_failure_marker` + `apply_retention` → 記入 `upgraded` 清單。
- [x] 4.2 失敗處理 `handle_upgrade_failure(...)`：`abort` → 寫 marker（rolled_back=False）後 exit 1；`rollback` → 反序 `restore_backup` 本次 `upgraded` 全部 ＋ 失敗 target（若有備份），全部成功 → 寫 marker（rolled_back=True）→ exit 8；任一還原失敗 → 印出備份路徑與 sidecar 後 exit 9；fresh target 失敗（無備份）→ 同 abort，訊息註明 fresh bootstrap。
- [x] 4.3 備份失敗處理：`required` → exit 8（不執行 upgrade）；`best-effort` → warning 後繼續且該 target 的 rollback 能力退化為 abort。
- [x] 4.4 退役 `backup_sqlite_if_needed()`（`database_init.py:176-197`）：`bootstrap_target` 內呼叫點移除；`adopt_legacy_target`（`:410`）與 `upgrade_legacy_target`（`:432`）改呼叫 `app/db_backup.create_backup`（一律備份、不看 pending）。移除後全 repo `rg backup_sqlite_if_needed` 應無殘留引用。
- [x] 4.5 確認 `ensure_super_admin_seed` 仍在所有 target 完成後執行、失敗不觸發回退（seed 冪等）。
- [x] 4.6 整合測試 `app/testsuite/test_bootstrap_backup_rollback.py`（SQLite 為主）：(a) 無 pending 開機兩次 → 0 備份檔；(b) 有 pending → 產生 1 份備份且升版成功、marker 不存在；(c) 注入失敗的 fake migration（monkeypatch `TARGET_UPGRADERS`）＋ `BOOTSTRAP_ON_FAILURE=rollback` → DB 檔內容回到升版前（比對升版前 snapshot 的 `alembic_version` 與表清單）、exit 8、marker attempts=1 rolled_back=True；(d) 連續失敗 3 次後第 4 次 exit 10；(e) `--clear-failure-markers` 後恢復；(f) 多 target 情境：main 成功 audit 失敗 → main 也被還原。

## 5. 容器與文件配套

- [x] 5.1 `Dockerfile` runtime stage：`apt-get install` 清單加 `default-mysql-client postgresql-client`（與 curl 同一 RUN 層）。
- [x] 5.2 `docker-compose.app.yml`：新增 named volume `tcrt-db-backups` 掛載至 `/app/db_backups`，environment 補 `BOOTSTRAP_BACKUP_DIR: ${BOOTSTRAP_BACKUP_DIR:-/app/db_backups}`。
- [x] 5.3 `.env.docker.example`：新增 D5 五個變數與逐一註解（含「backup volume 是 rollback 與 failure-marker 兩機制的共同前提」、「PG rollback 模式要求應用帳號為 schema owner」、「多副本滾動部署建議非首副本 `SKIP_DATABASE_BOOTSTRAP=1`」）。
- [x] 5.4 `README.md`：環境變數表補五個新變數；「備份檔位置由 CWD 改為 `db_backups/`」列入行為變更說明。
- [x] 5.5 `docs/database-cutover-readiness.md` 與 `docs/docker-app-setup.md`：補開機升版備份/回退段落與 exit code 對照（8/9/10）。
- [x] 5.6 `.gitignore` 加 `db_backups/`。

## 6. 驗證

- [x] 6.1 `uv run pytest app/testsuite/test_bootstrap_pending_detection.py app/testsuite/test_db_backup.py app/testsuite/test_bootstrap_backup_rollback.py -q` 全綠。
- [x] 6.2 `uv run pytest app/testsuite -q` 全綠（確認 bootstrap 重構未破壞既有 `test_db_cross_migrate_script.py`、`test_db_cutover_workflow.py` 等）。
- [x] 6.3 `uv run ruff check app scripts database_init.py` 通過。
- [x] 6.4 手動煙測（disposable MySQL，用 `docker-compose.mysql.yml`）：正常升版路徑 ＋ 人為注入失敗 migration 的 rollback 路徑各跑一次，記錄輸出到 change 目錄下 `verification.md`。
- [x] 6.5 `openspec validate add-boot-upgrade-backup-rollback --strict` 通過。
