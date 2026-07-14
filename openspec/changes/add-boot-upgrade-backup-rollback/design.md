# Design — add-boot-upgrade-backup-rollback

## Context

容器 entrypoint（`docker/app-entrypoint.sh`）每次開機執行 `uv run python database_init.py`，對 `MIGRATION_ORDER = ("main", "audit", "usm")` 三個 target 依序 `bootstrap_target()`（`database_init.py:469`）：`create_database_if_missing` → `backup_sqlite_if_needed`（僅 SQLite，寫到 CWD）→ Alembic `upgrade head` → `verify_required_tables` → MySQL MEDIUMTEXT 檢查 → （main）automation key 檢查。全程包在 `bootstrap_lock()`（`app/runtime_locks.py`）內。

現況缺口：

1. MySQL/PostgreSQL 沒有升版前備份；MySQL DDL 非交易性，revision 中途失敗會留下半套 schema，重跑 `upgrade head` 可能因物件已存在而永久卡死。
2. SQLite 每次開機都備份（即使無 pending migration），且備份寫到 CWD（容器內 ephemeral、занимает雙倍磁碟）。
3. 升版失敗 → exit 1 → 容器 abort；沒有回退，配 `restart: unless-stopped` 會無限重試。

既有可重用元件：`app/db_migrations.py` 的 `_get_current_revision(database_url)`（讀 DB `alembic_version`，DB 不存在/無表回 `None`）與 `_get_head_revision(cfg)`（讀 script directory head）、`build_alembic_config()`、`get_migration_target()`。

## Goals / Non-Goals

**Goals:**

- 有 pending revision 才備份；無 pending 零副作用。
- SQLite / MySQL / PostgreSQL 三引擎升版前備份，統一目錄、統一保留策略。
- 失敗回退（opt-in）：還原到升版前狀態，讓「換回舊版 image」能立即開機。
- 連續失敗防護，避免 restart-loop 反覆升版-回退。
- 全程維持在既有 `bootstrap_lock()` 內，不新增併發面。

**Non-Goals:**

- 不做排程型定期備份（只做「升版前」時點備份）。
- 不做 point-in-time recovery、不管 binlog/WAL 歸檔。
- 不改 Alembic revision 內容、不動 schema。
- 不處理 Qdrant / 附件 / 報告目錄的備份。
- 不提供自動 `alembic downgrade`（理由見 Decisions D6）。

## Decisions

### D1. Pending 偵測：`alembic_version` current vs script head

- 新 helper `get_pending_status(target_name) -> PendingStatus`，放在 `app/db_migrations.py`（緊鄰 `_get_current_revision`）。
- `PendingStatus` dataclass：`{target: str, current: str | None, head: str, is_pending: bool, is_fresh: bool}`。
  - `current`：`_get_current_revision()` 結果。
  - `head`：`_get_head_revision(build_alembic_config(target))`。
  - `is_pending = current != head`。
  - `is_fresh = current is None AND 該 DB 無任何業務表`（用既有 inspector 檢查 `TARGET_REQUIRED_TABLES` 任一表是否存在；`create_database_if_missing` 剛建立者必為 fresh）。legacy 未 stamp 的 DB（有表無 `alembic_version`）→ `is_fresh=False`、`is_pending=True`。
- 決策：**`is_fresh=True` 時跳過備份**（沒有可保護的資料），失敗也不回退（無備份可還原，行為同 abort）。
- 替代方案：用 `alembic check`（需要 metadata diff，過重且與 drift 驗證混淆）— 否決。

### D2. 備份模組：新檔 `app/db_backup.py`（bootstrap 專用，允許 sync）

單一模組收攏引擎分派，公開介面：

```python
@dataclass
class BackupResult:
    target: str            # main | audit | usm
    engine: str            # sqlite | mysql | postgresql
    path: Path             # 備份檔絕對路徑
    from_revision: str | None
    to_revision: str       # head

def create_backup(target_name: str, pending: PendingStatus, backup_dir: Path) -> BackupResult
def restore_backup(result: BackupResult) -> None
def apply_retention(backup_dir: Path, target_name: str, keep: int) -> list[Path]  # 回傳刪除清單
```

- 這是 migration/bootstrap 場景，依專案慣例允許 sync engine 與 subprocess；**不得**被 web runtime import 使用（測試中加 guard 不必要，靠 code review 與 `check_db_access_guardrails.py` 現況即可，該腳本不掃 bootstrap 模組）。
- 備份檔命名（固定格式，restore/retention/測試都依賴它）：
  `<BOOTSTRAP_BACKUP_DIR>/<target>/<UTC 時戳 YYYYmmddTHHMMSSZ>__<from_rev|none>__<to_rev>.<ext>`
  ext：SQLite=`.sqlite3`、MySQL=`.sql.gz`、PostgreSQL=`.pgdump`。
- 每個 `BackupResult` 旁寫同名 `.meta.json`：`{target, engine, database, from_revision, to_revision, created_at, tool_version}`，restore 與人工檢視使用。

### D3. 引擎別備份程序

| 引擎 | 工具 | 命令要點 |
|---|---|---|
| SQLite | Python `sqlite3.Connection.backup()` API | 對來源 DB 開唯讀連線後 `.backup()` 到目標檔。**不用 `shutil.copy2`**：backup API 對 WAL 模式安全、不需另外處理 `-wal`/`-shm`。 |
| MySQL | `mysqldump` | `mysqldump --single-transaction --no-tablespaces --add-drop-table --routines --host <h> --port <p> --user <u> <database>`，stdout 直接 gzip 進目標檔。密碼經 `MYSQL_PWD` 環境變數傳遞，**不進 argv、不進 log**。 |
| PostgreSQL | `pg_dump` | `pg_dump --format=custom --file <path> --host <h> --port <p> --username <u> <database>`。密碼經 `PGPASSWORD`。 |

- 連線參數一律從 `resolve_database_url(target)` 的 SQLAlchemy URL 解析（`make_url`），與 runtime 同源。
- client 缺失偵測：`shutil.which("mysqldump")` / `which("pg_dump")`；缺失時依 `BOOTSTRAP_BACKUP_MODE`（見 D5）決定 fail / warn。
- Dockerfile runtime stage 追加 `default-mysql-client postgresql-client`（bookworm 套件），與 `curl` 同一層安裝。

### D4. 引擎別還原程序（restore_backup）

前提：只在「本次 bootstrap 自己建立的備份」上執行；還原前先 `engine.dispose()` 關閉本行程所有連線。

| 引擎 | 程序 |
|---|---|
| SQLite | 以 `sqlite3.Connection.backup()` 反向複製（備份檔 → 原路徑）；完成後刪除原 DB 的 `-wal`/`-shm` 殘檔。 |
| MySQL | (1) 連線後 `SET FOREIGN_KEY_CHECKS=0`，枚舉 `information_schema.tables` 中該 database 全部 base table 並逐一 `DROP TABLE`（清掉失敗 migration 產生的新表）；(2) 以 `mysql` client 重放 gunzip 後的 dump（dump 內含 `--add-drop-table`，重放具冪等性）。 |
| PostgreSQL | (1) `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`（用應用連線帳號執行；帳號需為 schema owner——部署文件明載此前提）；(2) `pg_restore --no-owner --host ... --dbname <db> <path>`。 |

- 選 drop-then-replay 而非只靠 dump 的 DROP 語句：dump 只會 DROP 它自己包含的表，失敗 migration 新建的表會殘留 → 下次 upgrade 再撞。此程序保證還原後狀態 == 備份時點。
- 替代方案（MySQL `DROP DATABASE` + `CREATE DATABASE`）：需要 database 層權限且會掉 charset/collation 設定 — 否決。

### D5. 政策與環境變數（一律 `os.getenv`，不進 config.yaml）

| 變數 | 值域 | 預設 | 語意 |
|---|---|---|---|
| `BOOTSTRAP_BACKUP_DIR` | path | `<PROJECT_ROOT>/db_backups` | 備份根目錄；容器部署掛 volume。目錄不存在則 `mkdir -p`。 |
| `BOOTSTRAP_BACKUP_MODE` | `required` / `best-effort` / `off` | `required` | `required`：備份失敗（含缺 client）→ 該次 bootstrap 以 exit 8 中止、不執行 upgrade。`best-effort`：記 warning 繼續 upgrade（此時 `rollback` 失敗行為退化為 abort）。`off`：不備份（等同既有 `--no-backup`）。 |
| `BOOTSTRAP_BACKUP_RETENTION` | int ≥ 1 | `5` | 每 target 保留最近 N 份（含本次），依檔名時戳排序刪舊。 |
| `BOOTSTRAP_ON_FAILURE` | `abort` / `rollback` | `abort` | upgrade 或升版後驗證失敗時：`abort`=現況（exit 1）；`rollback`=還原本次所有已升版 target 後 exit 9。 |
| `BOOTSTRAP_MAX_UPGRADE_ATTEMPTS` | int ≥ 1 | `3` | 同一 (target, head) 連續失敗次數達上限後，開機直接 exit 10 拒絕再升版。 |

- CLI 對映：既有 `--no-backup` ⇒ 強制 `BOOTSTRAP_BACKUP_MODE=off`（CLI 優先）。新增 `--clear-failure-markers`：刪除全部 failure marker 後 exit 0（人工介入後解鎖用）。
- `.env.docker.example` 補上五個變數與註解；`docker-compose.app.yml` 加 `tcrt-db-backups` named volume 掛到 `/app/db_backups` 的示例。

### D6. 回退語意：restore-from-backup，不用 `alembic downgrade`

- 理由：MySQL DDL 非交易性，失敗當下 DB 已處於「兩個 revision 之間」的未定義狀態，downgrade 腳本假設起點是完整 revision，不可靠；restore 則無條件回到已知良好時點。
- **多 target 一致性**：`MIGRATION_ORDER` 依序處理時記錄 `upgraded: list[BackupResult]`；任一 target 失敗（upgrade 例外、或該 target 升版後驗證失敗），`rollback` 模式須**反序還原 `upgraded` 內全部 target ＋ 當前失敗 target**。理由：只還原失敗者會留下「main=新 / audit=舊」混合狀態，舊版 image 的 alembic 看到未知 revision 會直接啟動失敗。
- 還原成功 → exit 8（含明確訊息「DB 已回到升版前，請改用舊版 image 或修復後重試」）；還原過程再失敗 → exit 9（訊息指向備份檔路徑與 `.meta.json`，要求人工還原）。兩者都非零：**容器仍不啟動**，這是刻意的——回退的目的不是讓新 image 帶舊 schema 起服務（新 code 對舊 schema 未必相容），而是保住資料並讓舊 image 可用。
- fresh DB（D1 `is_fresh`）失敗：無備份，直接 abort（exit 1），訊息註明 fresh bootstrap 失敗無需回退。

### D7. 連續失敗防護（failure marker）

- 檔案：`<BOOTSTRAP_BACKUP_DIR>/<target>/upgrade-failure.json`，內容：
  `{"target": ..., "head": ..., "from_revision": ..., "attempts": int, "last_error": str(截斷 2000 字), "last_attempt_at": ISO8601, "rolled_back": bool}`。
- 流程：bootstrap 進入該 target 前讀 marker——若存在且 `marker.head == 目前 head` 且 `attempts >= BOOTSTRAP_MAX_UPGRADE_ATTEMPTS` → 整個 bootstrap exit 10（不動任何 DB）。若 `marker.head != 目前 head`（image 已換版）→ 視為新一輪，attempts 重計。
- 失敗時寫/累加 marker（在 restore 之後寫，`rolled_back` 記錄還原結果）；該 target 升版成功時刪除 marker。
- marker 放 backup dir（volume）而非 DB：DB 可能正處於不可寫/不一致狀態。

### D8. 主流程整合點（`database_init.py`）

`bootstrap_target()` 拆分改造（維持函式對外簽名相容不是目標，`main()` 是唯一 caller）：

```text
main() 內（bootstrap_lock() 之下）：
  policies = read_bootstrap_policies()            # D5 env 解析，集中一處
  for target in MIGRATION_ORDER:
      check_failure_marker(target, policies)      # D7，超限 → exit 10
  upgraded: list[BackupResult] = []
  for target in MIGRATION_ORDER:
      pending = get_pending_status(target)        # D1
      create_database_if_missing(...)             # 既有
      if not pending.is_pending:
          verify-only 路徑（既有 verify_required_tables 等），continue
      backup = maybe_create_backup(target, pending, policies)   # D2/D3/D5
      try:
          upgrade + 既有驗證鏈（required tables / MEDIUMTEXT / automation key）
      except Exception:
          handle_upgrade_failure(target, upgraded + [backup], policies)  # D6/D7 → exit 8/9/1
      clear_failure_marker(target)
      apply_retention(...)
      upgraded.append(backup)
  ensure_super_admin_seed(...)                    # 既有，不變
```

- `backup_sqlite_if_needed()` 退役：邏輯併入 `app/db_backup.py`；`adopt_legacy_target` / `upgrade_legacy_target` 兩個 CLI 路徑改呼叫新模組（行為：一律備份、無 pending 判斷——legacy 納管本身就是 schema 變更）。
- `--skip-migrations` 路徑不變（無 upgrade 即無備份/回退）。
- seed（`ensure_super_admin_seed`）失敗不觸發 DB 回退（非 schema 變更，重跑冪等）。

### D9. Exit code 配置（既有：0 成功、1 一般錯誤、2 檢查未過、3/4 legacy、5 preflight、6 verify、7 legacy 升級缺表）

- `8`：備份失敗（required 模式）或「升版失敗且已成功回退」。
- `9`：升版失敗且回退失敗（需人工介入）。
- `10`：連續失敗達上限，拒絕嘗試。
- entrypoint 不需改（`set -eu` 對任何非零一視同仁）；exit code 供 orchestrator / 人工診斷區分。

## Risks / Trade-offs

- [大庫 dump 拉長開機時間] → 只在有 pending 時備份；文件註明大庫可改 `BOOTSTRAP_BACKUP_MODE=off` ＋ 外部快照策略；mysqldump `--single-transaction` 不鎖表。
- [備份期間其他副本等待] → 都在 `bootstrap_lock` 內，等待者只是 block（MySQL `GET_LOCK` timeout 120s，`_BOOTSTRAP_LOCK_TIMEOUT_SECONDS`），大庫 dump 可能超過 → 文件明載：多副本滾動部署時建議 `SKIP_DATABASE_BOOTSTRAP=1` 於非首個副本，或接受等待逾時重啟。
- [PG `DROP SCHEMA public CASCADE` 權限不足] → restore 失敗走 exit 9 人工路徑；部署文件把「應用帳號須為 schema owner」列為 rollback 模式前提。
- [dump/restore 期間 credentials 洩漏] → 僅經 `MYSQL_PWD`/`PGPASSWORD` env 傳遞；log 一律以 `redact_url`（複用 `app/db_cutover_workflow.py:137` 的遮蔽邏輯或等效實作）輸出 URL。
- [`best-effort` + `rollback` 組合下無備份可還原] → 明確定義：退化為 abort（exit 1）並在 log 說明原因，不算矛盾設定。
- [marker 所在 volume 未掛載] → marker 寫在 ephemeral 目錄時防迴圈失效（每次重啟 attempts 歸零）→ 文件明載 backup volume 是 rollback/marker 兩機制的共同前提；`BOOTSTRAP_BACKUP_MODE=required` 且目錄不可寫 → exit 8。

## Migration Plan

1. 純程式碼變更，無 Alembic revision。
2. 預設值（`required`/`abort`）下與現況的差異只有：(a) SQLite 無 pending 不再備份、(b) 備份位置改 `db_backups/`。既有部署若依賴 CWD 的 `backup_*.db` 需改讀新位置（README 註明）。
3. Rollback（本 change 自身）：revert commits 即回到現行為，無資料層殘留（`db_backups/` 目錄可留可刪）。

## Open Questions

（無——以下決策已定案：不用 alembic downgrade（D6）、多 target 全體還原（D6）、marker 放 volume（D7）、exit code 避開既有 5/6/7（D9）。）
