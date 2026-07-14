# Database Cutover Readiness

此文件定義從 SQLite 切換到 MySQL / PostgreSQL 前的 rehearsal、rollback 與 re-verification 基準流程。

## 0. 標準 workflow 入口

專案現在提供統一 runner：

```bash
python3 scripts/run_db_cutover_workflow.py --target sqlite --mode smoke
python3 scripts/run_db_cutover_workflow.py --target mysql --mode smoke --manage-services
python3 scripts/run_db_cutover_workflow.py --target postgres --mode smoke --manage-services
```

每次 run 都會在 `.tmp/db-cutover/<timestamp>-<target>-<mode>/` 留下：

- `summary.json`
- `summary.md`
- `logs/preflight.log`
- `logs/bootstrap.log`
- `logs/verify.log`
- `logs/start.log`
- 若使用 `--manage-services`，另有 `logs/compose-up.log` 與 `logs/compose-down.log`

## 1. Cutover 前提

在任何 rehearsal 或正式切換前，必須先滿足：

- 三套資料庫 `main`、`audit`、`usm` 都已設定明確 URL
- `python3 database_init.py --preflight` 全部通過
- 來源資料庫已有可回復的備份或快照
- 目標資料庫已有獨立 rehearsal 環境，不與 production 共用

## 2. 標準 rehearsal 流程

1. 啟動目標資料庫服務與初始化 database。
2. 設定 `DATABASE_URL`、`SYNC_DATABASE_URL`、`AUDIT_DATABASE_URL`、`USM_DATABASE_URL`。
3. 執行 `python3 database_init.py --preflight`。
4. 如為既有未納管資料庫，先執行對應的 `--validate-legacy-*-db` 與 `--adopt-legacy-*-db`。
5. 執行 `python3 database_init.py`。
6. 執行 `python3 database_init.py --verify-target all`。
7. 啟動應用並確認 `/health` 可回應。

建議直接使用統一 runner：

```bash
python3 scripts/run_db_cutover_workflow.py --target sqlite --mode rehearsal
python3 scripts/run_db_cutover_workflow.py \
  --target mysql \
  --mode rehearsal \
  --manage-services \
  --baseline-summary .tmp/db-cutover/<sqlite-run>/summary.json
python3 scripts/run_db_cutover_workflow.py \
  --target postgres \
  --mode rehearsal \
  --manage-services \
  --baseline-summary .tmp/db-cutover/<sqlite-run>/summary.json
```

## 3. 驗證輸出最低要求

rehearsal 完成後，至少應保留：

- `summary.json`
- `summary.md`
- `--preflight` 或 `logs/preflight.log`
- `--verify-target all` 或 `logs/verify.log`
- `/health` 驗證結果與 `logs/start.log`
- 若有資料搬遷，重要表的 row count 比對結果

建議至少比對：

- `main`: `users`、`teams`、`test_cases`
- `audit`: `audit_logs`
- `usm`: `user_story_maps`、`user_story_map_nodes`

若使用統一 runner，row count comparison 會寫在 `summary.json` 的 `comparison` 欄位與 `summary.md` 的 `Comparison` 段落。

## 4. Rollback 前提

若 rehearsal 或切換驗證失敗，rollback 前請先保留：

- 來源資料庫備份或快照
- 失敗當下的目標資料庫 preflight / verification 輸出
- `.tmp/db-cutover/<failed-run>/summary.json`
- 失敗時間點使用的環境變數與 compose/連線設定

## 5. Rollback 步驟

1. 停止目前指向目標資料庫的應用服務。
2. 清除或回退 `DATABASE_URL`、`SYNC_DATABASE_URL`、`AUDIT_DATABASE_URL`、`USM_DATABASE_URL` 到原來源資料庫設定。
3. 若已對目標資料庫寫入測試資料，保留該環境供後續分析，不要直接覆蓋來源資料庫。
4. 若來源資料庫在 rehearsal 過程被替換，先從切換前備份或快照回復。
5. 重新啟動應用前，先在來源資料庫環境執行驗證。

## 6. Re-Verification Flow

rollback 後至少重新執行：

```bash
python3 database_init.py --preflight
python3 database_init.py --verify-target all
HOST=127.0.0.1 PORT=19997 SERVER_PID_FILE=/tmp/tcrt-reverify.pid UVICORN_RELOAD=0 ./start.sh
curl http://127.0.0.1:19997/health
kill "$(cat /tmp/tcrt-reverify.pid)"
rm -f /tmp/tcrt-reverify.pid
```

或直接重新跑：

```bash
python3 scripts/run_db_cutover_workflow.py --target sqlite --mode smoke
```

只有在上述流程恢復正常後，才應重新安排下一次 rehearsal 或正式 cutover。

## 7. 開機自動升版：備份、失敗回退與連續失敗防護

此節說明**每次容器/服務啟動**（非僅 cutover 當下）`database_init.py` 的升版前備份與失敗處理機制。

### 7.1 何時備份

啟動時針對 main / audit / usm 三套資料庫，逐一比對目前 Alembic revision 與 migration head：

- **無 pending 升版**（已是 head）：不建立任何備份，只執行既有驗證。
- **有 pending 升版**：依 `BOOTSTRAP_BACKUP_MODE` 政策決定是否先備份再升版。
- **全新資料庫**（尚無任何業務表）：視為無可保護資料，一律跳過備份直接升版。

### 7.2 備份政策與工具

| 引擎 | 備份工具 | 還原方式 |
|------|----------|----------|
| SQLite | `sqlite3` backup API | 反向 backup 複製回原檔（WAL 安全），並清除 `-wal`/`-shm` 殘檔 |
| MySQL / MariaDB | `mysqldump --single-transaction` | 先 `DROP TABLE` 清空全部既有表，再以 `mysql` client 重放 dump |
| PostgreSQL | `pg_dump --format=custom` | 先 `DROP SCHEMA public CASCADE` + `CREATE SCHEMA public`，再 `pg_restore` |

備份檔與 metadata（`.meta.json`）存放於 `BOOTSTRAP_BACKUP_DIR`（預設 `<專案根>/db_backups`，容器內建議掛 volume），依 target 分子目錄，檔名含時戳與 from/to revision。`BOOTSTRAP_BACKUP_RETENTION`（預設 5）控制每個 target 保留的最近備份數量。

`BOOTSTRAP_BACKUP_MODE`：

- `required`（預設）：備份失敗（含缺少 `mysqldump`/`pg_dump`）即中止該次 bootstrap，不執行升版。
- `best-effort`：備份失敗僅記警告，繼續升版（此時該 target 若升版失敗，回退能力會因無備份而退化為 abort）。
- `off`：不備份，等同 CLI `--no-backup`。

### 7.3 失敗回退（BOOTSTRAP_ON_FAILURE）

- `abort`（預設）：沿用既有行為，升版或升版後驗證失敗即中止、以非零狀態退出。
- `rollback`：任一 target 失敗時，將**本次已成功升版的 target**與**失敗 target 自身（若有備份）**依相反順序全部還原至升版前狀態，讓三套資料庫維持一致、可換回舊版 image 立即開機。若失敗 target 本身是全新資料庫或因 `best-effort` 未能備份，該 target 不會被還原（無備份可還原），但其餘已成功 target 仍會還原。

**Exit code 對照（開機升版流程新增）：**

| Exit code | 意義 |
|-----------|------|
| `8` | 備份失敗（`required` 模式）或「升版失敗且已成功回退」 |
| `9` | 升版失敗、回退還原本身也失敗，需人工介入（訊息含備份檔位置） |
| `10` | 同一 head 連續失敗達 `BOOTSTRAP_MAX_UPGRADE_ATTEMPTS`，拒絕再次嘗試升版 |

### 7.4 連續失敗防護（failure marker）

每次升版失敗會在 `BOOTSTRAP_BACKUP_DIR/<target>/upgrade-failure.json` 記錄或累加嘗試次數（同一 head 才累加，head 改變視為新一輪）。達 `BOOTSTRAP_MAX_UPGRADE_ATTEMPTS`（預設 3）後，開機直接拒絕嘗試（exit 10），避免 container restart policy 造成無限「升版失敗→回退」循環。升版成功會清除該 target 的 marker。

人工排除問題後，解鎖重試：

```bash
python3 database_init.py --clear-failure-markers
```

### 7.5 容器部署前提

- `BOOTSTRAP_BACKUP_DIR` 必須是持久化 volume（見 `docker-compose.app.yml` 的 `tcrt-db-backups`），否則 failure marker 每次重啟歸零、防迴圈失效。
- `BOOTSTRAP_ON_FAILURE=rollback` 還原 PostgreSQL 需要應用程式 DB 帳號可 `DROP/CREATE SCHEMA`；還原 MySQL 需要 `DROP/CREATE TABLE` 權限。
- runtime image 需含 `mysqldump`/`mysql`、`pg_dump`/`pg_restore`（官方 Dockerfile 已內建）。
- **`pg_dump`/`pg_restore` 版本須與目標 PostgreSQL server 對齊或相近**：明顯更新的 client（例如 PG18 client 對 PG16 server）產生的 dump 可能含目標 server 不認得的 session 設定（例如 `transaction_timeout`），導致 `pg_restore` 失敗。官方 Dockerfile 透過 Debian 套件庫安裝，版本已與 target PostgreSQL 16 對齊；若自訂 base image 或在本機手動測試，請確認版本一致。
- 多副本同時開機時，備份/升版/回退全程在既有 `bootstrap_lock()` 序列化鎖之內執行，不會重複。

## 8. 一鍵搬移（migrate 模式）

此節說明將現有資料（通常是 SQLite 開發/既有部署）一次性搬移到指定 MySQL/PostgreSQL server 的單一指令流程，
與上方 §0-§6 的 rehearsal/smoke（驗證環境是否可升版）不同——migrate 模式**會實際搬移資料**。

### 8.1 指令

對已存在的正式 server（真實密碼放在 env 檔，不進 log／summary）：

```bash
python3 scripts/run_db_cutover_workflow.py \
  --mode migrate \
  --target mysql \
  --target-env-file /path/to/target.env
```

`target.env` 需含 `DATABASE_URL`、`SYNC_DATABASE_URL`、`AUDIT_DATABASE_URL`、`USM_DATABASE_URL` 四鍵（格式同
`.env.docker.example`）。來源預設為目前 app 環境實際解析到的三庫（即執行當下的 `DATABASE_URL` 等環境變數/
config.yaml 設定）；如來源不同，另加 `--source-env-file /path/to/source.env`。

對 disposable compose 目標演練（不需另外準備 env 檔）：

```bash
python3 scripts/run_db_cutover_workflow.py --mode migrate --target mysql --manage-services
```

### 8.2 流程

Guardrails → preflight → **非空目標偵測**（見 8.4）→ 目標 schema bootstrap（Alembic，全新/已清空目標）→
main→audit→usm 依序資料搬移（`scripts/db_cross_migrate.py`，一律 `--reset-target`）→ 逐表 row count 覆核 →
`--verify-target all` → 應用健康檢查。任一步驟失敗即中止，`run_dir` 下保留完整 `logs/`（含
`logs/migrate-main.log`/`logs/migrate-audit.log`/`logs/migrate-usm.log`）與 `summary.json`/`summary.md`。

### 8.3 前提

- **正式搬移前務必停止對來源資料庫的寫入**（停止 app 容器或切維護模式）；工具本身不鎖定來源，搬移期間仍被寫入會導致資料不一致。
- 目標資料庫帳號需要建表與寫入權限：`CREATE`、`ALTER`、`DROP`、`REFERENCES`（Alembic 建 schema）+ `INSERT`/`DELETE`（資料搬移與 reset-target）。
- 來源資料庫僅需讀取權限；migrate 模式全程不寫入來源。

### 8.4 非空目標防呆

搬移前會偵測目標三庫是否已有業務資料（排除 `alembic_version`/`migration_history`）。**非空且未帶
`--force-reset-target`** 會在任何寫入發生前中止，summary 的 `non_empty_tables` 列出偵測到的表與列數（最多
20 筆）。確認可以覆蓋後，加上 `--force-reset-target` 重新執行——**此為破壞性操作，會清空目標 main/audit/usm
三庫全部既有業務資料**，執行前請自行確認目標不是仍在使用中的環境。

若來源存在循環外鍵導致搬移排序失敗，加上 `--migrate-disable-constraints`（透傳
`db_cross_migrate.py --disable-constraints`）。

### 8.5 失敗回復

失敗時**目標資料庫可能處於部分搬移狀態，來源資料庫不受影響**（全程唯讀）。回復方式：直接重新執行同一指令
（目標會被視為「非空」而要求 `--force-reset-target`，或先手動清空目標後不帶該旗標重跑），不需要對來源做任何操作。

### 8.6 搬移完成後

1. summary 的 `env_summary` 區段列出四組已遮蔽密碼的目標連線設定；依此更新 app 實際使用的環境變數（`.env.docker` 或部署環境變數）。
2. 重新部署/重啟 app，指向新的資料庫。
3. 抽樣核對關鍵頁面（Test Case、Test Run、User Story Map）資料是否正確顯示。
