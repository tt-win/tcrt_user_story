# Add Boot Upgrade Backup & Rollback

## Why

容器化部署後，每次開機都由 entrypoint 執行 `database_init.py` 對三套資料庫做 Alembic 升版，但目前的保護只有半套：升版前備份僅支援 SQLite（檔案複製，且寫入容器內 ephemeral 的 CWD）、MySQL/PostgreSQL 完全沒有備份，且升版失敗只會讓容器 abort、沒有回退機制。MySQL 的 DDL 非交易性——migration 中途失敗會留下半套 schema，重啟後重跑 upgrade 可能直接撞牆，唯一可靠的復原是還原備份。要把 MySQL/PostgreSQL 當成正式部署目標，「有 pending 升版才備份、失敗可回退、回退後舊版 image 能立即開機」必須成為 bootstrap 的內建行為。

## What Changes

- `database_init.py` bootstrap 在升版前對每個 target（main/audit/usm）比對 Alembic current revision 與 head：**無 pending revision 時跳過備份**，只做既有驗證；有 pending 時才觸發備份與升版。（現況為 SQLite 每次開機都備份，屬行為變更。）
- 依引擎提供升版前備份，統一寫入 `BOOTSTRAP_BACKUP_DIR`（預設 `<專案根>/db_backups/`，容器部署應掛 volume）：
  - SQLite：沿用檔案複製，但目的地由 CWD 改為 `BOOTSTRAP_BACKUP_DIR`。（**BREAKING**：`backup_*.db` 不再寫入專案根/CWD。）
  - MySQL：`mysqldump --single-transaction`（需要容器 image 內含 client；缺 client 時依備份政策決定 fail fast 或降級警告）。
  - PostgreSQL：`pg_dump -Fc`（同上）。
- 備份保留策略：每個 target 保留最近 N 份（`BOOTSTRAP_BACKUP_RETENTION`，預設 5），超出自動清除。
- 備份政策 `BOOTSTRAP_BACKUP_MODE=required|best-effort|off`（預設 `required`）：`required` 時備份失敗（含缺 dump client）即中止升版；`best-effort` 記錄警告後繼續；`off` 等同現有 `--no-backup`。
- 失敗回退政策 `BOOTSTRAP_ON_FAILURE=abort|rollback`（預設 `abort`＝現況行為）：`rollback` 模式下，升版或升版後驗證失敗時自動還原該次備份（SQLite 還原檔案、MySQL/PostgreSQL 還原 dump），還原完成後仍以非零狀態退出——語意是「資料庫已回到升版前狀態，換回舊版 image 可立即正常開機」。
- 連續失敗防護：升版失敗時在 `BOOTSTRAP_BACKUP_DIR` 寫入 failure marker（含 target、revision 區間、時間、錯誤摘要）；同一 head revision 連續失敗達上限（`BOOTSTRAP_MAX_UPGRADE_ATTEMPTS`，預設 3）後拒絕再嘗試升版並以明確錯誤退出，要求人工介入，避免 container restart policy 造成無限「升版失敗→回退」循環。升版成功時清除 marker。
- 全部流程維持在既有 `bootstrap_lock()` 之內，多 worker / 多副本併發啟動下仍只有單一行程執行備份與升版。
- 容器與文件配套：runtime image 安裝 `default-mysql-client` 與 `postgresql-client`；`docker-compose.app.yml` 增加 backup volume 掛載示例；`.env.docker.example`、`README.md`、`docs/database-cutover-readiness.md`、`docs/docker-app-setup.md` 同步新環境變數與回退語意。

## Capabilities

### New Capabilities

- `boot-upgrade-safety`: 定義開機自動升版的安全要求——pending 偵測決定是否備份、跨引擎升版前備份與保留策略、備份政策分級、失敗回退語意（回退後舊版可立即開機）、連續失敗防護，以及與 bootstrap 併發鎖的關係。

### Modified Capabilities

- `system-bootstrap`: 「啟動已存在的系統」的行為由「必要驗證與非破壞性修補」擴充為「有 pending schema 升版時，先依政策完成備份再升版；無 pending 時不產生備份副作用」。

## Impact

- **程式碼**：`database_init.py`（bootstrap 流程、備份/回退/marker 邏輯）、`app/db_migrations.py`（pending revision 偵測 helper 重用/擴充）、新增 `app/db_backup.py`（或等效模組，引擎分派的 dump/restore）。
- **容器**：`Dockerfile`（runtime stage 安裝 mysql/postgres client）、`docker-compose.app.yml`（backup volume 範例）、`docker/app-entrypoint.sh`（不變或僅註解更新）。
- **設定**：新增 `BOOTSTRAP_BACKUP_DIR`、`BOOTSTRAP_BACKUP_MODE`、`BOOTSTRAP_BACKUP_RETENTION`、`BOOTSTRAP_ON_FAILURE`、`BOOTSTRAP_MAX_UPGRADE_ATTEMPTS`；`--no-backup` CLI 旗標語意映射到 `BOOTSTRAP_BACKUP_MODE=off`。
- **Migration / rollback / compatibility**：不新增任何 Alembic revision、不改 schema。行為變更點：(1) SQLite 無 pending 時不再每次備份；(2) 備份檔位置改變；(3) `rollback` 模式會對資料庫執行還原（破壞性動作，僅在該次 bootstrap 自己建立的備份存在且升版失敗時發生，且預設不啟用）。dump/restore 涉及 DB credentials 傳遞（`MYSQL_PWD`/`PGPASSWORD` 環境變數方式），不得寫入 log。
- **測試**：`app/testsuite` 新增 pending 偵測、備份政策、retention、marker 防迴圈的單元/整合測試；MySQL/PG dump-restore 以 disposable DB 驗證（沿用既有 mysql/postgres smoke 基礎）。
