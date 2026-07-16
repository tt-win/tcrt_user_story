# SQLite → MySQL 正式 Migration Runbook

本文件是 TCRT 將 `main`、`audit`、`usm` 三套資料庫搬移至既有 MySQL server，並把應用程式切換到 MySQL 的標準操作流程。執行者可以是工程師或 AI Agent；不得省略安全檢查、驗證或 rollback 準備。

本文件**不負責建立或啟動 MySQL server**。開始前，DBA 必須已提供三個空白 database 的位址與具名帳號。

## 0. 不可違反的規則

1. 來源資料庫在整個 migration 期間只讀；搬移腳本不應寫入來源。
2. 正式搬移前先停止所有會寫入來源 DB 的 app、worker、scheduler 或 automation job。
3. 密碼只放在 repo 外或 gitignored 的 env file；不得貼到命令列、log、文件或 commit。
4. 不得使用既有的 `scripts/db_cross_migrate.yaml` 作正式設定；它容易留下明文密碼。統一使用 `--source-env-file` 與 `--target-env-file`。
5. 目標若已有業務資料，沒有操作者對「清空這三個指定 databases」的明確核准，不得使用 `--force-reset-target`。
6. 任一步驟失敗，先停止，不得自行跳過檢查或直接切換 app。

## 1. 完成條件

只有以下條件全部成立才算 migration 完成：

- workflow process exit code 為 `0`，且 `summary.json` 的 `success` 為 `true`。
- `migration.row_counts_match` 為 `true`。
- main、audit、usm 三個 migration jobs 的 `row_counts_match` 都為 `true`。
- 三個 target 的 `current_revision` 都等於 `head_revision`，且 `ready` 為 `true`。
- workflow 啟動的 app 使用目標 MySQL 四組 URL，`GET /health` 回 HTTP `200`。
- 部署環境已換成同一組目標 URL 並重啟，重啟後 health check 仍通過。
- Test Case、Test Run、User Story Map 關鍵頁面已抽樣確認。

## 2. 前置條件

在 repo root 執行：

```bash
uv sync --frozen
```

確認 DBA 已建立並提供：

- main database，例如 `tcrt_main`
- audit database，例如 `tcrt_audit`
- USM database，例如 `tcrt_usm`
- 一個可連線這三個 databases 的 app 帳號

目標帳號必須能在三庫執行 Alembic schema migration 與資料搬移，至少涵蓋 schema 建立/修改、index、foreign key，以及資料的讀寫與清除。帳號不必能存取 MySQL 的 `mysql` 管理 database；目標 databases 必須由 DBA 預先建立。

確認網路與 TLS 規則允許執行 migration 的主機連到 MySQL。不要先修改 app 的正式 DB 設定。

## 3. 停止來源寫入並建立回復點

1. 記錄目前 app 實際使用的四組來源 URL，但不要把密碼寫入 log。
2. 停止 app、worker、scheduler 與所有可能寫入 DB 的 job。
3. 依來源引擎建立一致性備份或 snapshot。
4. 記錄備份位置、建立時間與還原方式。
5. 在 migration 完成或 rollback 結束前，不得重新開啟來源寫入。

若無法證明來源已停止寫入，停止本流程。

## 4. 建立來源 env file

在 repo 外或 `.tmp/` 下建立 `source.env`，並限制檔案權限：

```bash
chmod 600 /secure/path/source.env
```

SQLite 來源範例：

```dotenv
DATABASE_URL=sqlite+aiosqlite:////absolute/path/test_case_repo.db
SYNC_DATABASE_URL=sqlite:////absolute/path/test_case_repo.db
AUDIT_DATABASE_URL=sqlite+aiosqlite:////absolute/path/audit.db
USM_DATABASE_URL=sqlite+aiosqlite:////absolute/path/userstorymap.db
```

注意：絕對路徑在 `sqlite:///` 後需要四個 `/`。三個檔案必須是剛才停止寫入並完成備份的來源，不可指到測試副本或錯誤目錄。

## 5. 建立目標 env file

建立 `target.env` 並設定權限：

```bash
chmod 600 /secure/path/target.env
```

MySQL 範例；將所有 placeholder 換成 DBA 提供的值：

```dotenv
DATABASE_URL=mysql+asyncmy://<user>:<url-encoded-password>@<host>:<port>/<main_database>
SYNC_DATABASE_URL=mysql+pymysql://<user>:<url-encoded-password>@<host>:<port>/<main_database>
AUDIT_DATABASE_URL=mysql+asyncmy://<user>:<url-encoded-password>@<host>:<port>/<audit_database>
USM_DATABASE_URL=mysql+asyncmy://<user>:<url-encoded-password>@<host>:<port>/<usm_database>
```

規則：

- `DATABASE_URL`、`AUDIT_DATABASE_URL`、`USM_DATABASE_URL` 使用 async driver `mysql+asyncmy`。
- `SYNC_DATABASE_URL` 使用 migration driver `mysql+pymysql`。
- 密碼含 `@`、`:`、`/`、`#`、`%` 等字元時，必須先做 URL encoding。
- 四組 URL 必須指向同一個預定 MySQL server 上正確的三個 databases。
- 不要把 env file 加入 Git；以 `git status --short` 確認它沒有被追蹤。

## 6. 執行目標 preflight

只將 `target.env` 匯入目前 shell，執行 preflight 後立即清除：

```bash
set -a
source /secure/path/target.env
set +a
uv run python database_init.py --preflight --json --quiet > /tmp/tcrt-mysql-preflight.json
unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL
sed -n '/^{/,$p' /tmp/tcrt-mysql-preflight.json > /tmp/tcrt-mysql-preflight-clean.json
```

檢查結果：

```bash
jq '[.targets[] | {target, ready, database_state, current_revision, head_revision, driver_statuses}]' /tmp/tcrt-mysql-preflight-clean.json
```

允許的初始狀態：

- 全新空白目標：`ready=true` 且 `database_state=empty`。
- 已由本版 TCRT bootstrap、但沒有業務資料的目標：`ready=true` 且 revision 可驗證。

遇到下列任一情況立即停止：

- 任一 target 的 `ready` 不是 `true`。
- driver 不可用。
- `legacy_unmanaged`。
- database 名稱、host 或 port 與 DBA 提供資料不一致。
- 認證或 TLS 錯誤。

注意：`database_init.py --preflight --json --quiet` 的 stdout 目前含啟動 banner，因此上面的 `sed` 是必要步驟，不得直接對 raw file 執行 `jq`。

## 7. 執行一鍵 migration

確認來源仍維持唯讀後，在 repo root 執行：

```bash
uv run python scripts/run_db_cutover_workflow.py \
  --mode migrate \
  --target mysql \
  --source-env-file /secure/path/source.env \
  --target-env-file /secure/path/target.env \
  --health-timeout 120 \
  > /tmp/tcrt-mysql-migrate-output.json
```

不要加入 `--manage-services`；正式流程使用 `target.env` 指定的既有 DB server。

保存 process exit code：

```bash
MIGRATE_RC=$?
test "$MIGRATE_RC" -eq 0
```

workflow 的固定順序是：

1. DB access guardrails
2. 目標 preflight
3. 目標非空防呆
4. 三庫 Alembic schema bootstrap
5. main → audit → usm 執行 `scripts/db_cross_migrate.py --reset-target`
6. 每張表 source/target row count 覆核
7. `database_init.py --verify-target all`
8. 使用目標 MySQL URL 啟動 app 並檢查 `/health`

任一步驟失敗時 workflow 會短路，不得手動跳到後續步驟。

## 8. 驗證 workflow 證據

取得 run directory：

```bash
RUN_DIR=$(jq -r '.run_dir' /tmp/tcrt-mysql-migrate-output.json)
test -d "$RUN_DIR"
```

檢查總結果：

```bash
jq '{
  success,
  migration_row_counts_match: .migration.row_counts_match,
  jobs: [.migration.jobs[] | {job, row_counts_match}],
  revisions: [.verification.targets[] | {
    target, ready, current_revision, head_revision
  }],
  health: {
    ok: .health_check.ok,
    status_code: .health_check.status_code
  }
}' "$RUN_DIR/summary.json"
```

必須符合「第 1 節：完成條件」。再檢查三個 job log 都存在：

```bash
test -f "$RUN_DIR/logs/migrate-main.log"
test -f "$RUN_DIR/logs/migrate-audit.log"
test -f "$RUN_DIR/logs/migrate-usm.log"
```

若 `success=false`，查看 `summary.md` 與第一個非零 return code 對應的 log。Log 與 summary 不應含明文密碼；若發現密碼，立即限制檔案權限並停止分享。

### 已知資料差異與 warning 判讀

- `test_run_item_result_history` 若含指向不存在 `test_run_items` 的孤立資料，搬移工具會將其列入 `repair_counts.skipped_orphan_item_refs`。驗證使用 `expected_target_rows = source_rows - filtered_rows`；只有這類明確分類的 filtered rows 可視為符合，任何未分類的 row loss 仍會令 `row_counts_match=false`。
- SQLite 來源若仍有 `test_cases.attachment_count`、`test_cases.has_attachments`，summary 會放在 `ignored_source_columns.test_cases`。這兩欄是已知 legacy/computed 欄位，不屬於目前 Alembic target schema；其他未知的 source-only 欄位仍會輸出 warning。
- SQLite 的 expression-based index（例如 `uq_users_username_lower`）不參與 reflection 搬移；正式 target schema 仍以 Alembic migration 為準，搬移工具只精確忽略這一種 SQLAlchemy reflection warning。
- 從最早的 `7a26d2522198` 建立全新 MySQL schema 時，driver 可能在該歷史 revision 暫時輸出 6 筆 duplicate-index warning。不要因此中止後續 revision；head `8f1b2c3d4e5a` 會移除 auto-named duplicates，保留 canonical indexes。若流程未到 head，或 head 完成後同欄位仍有兩個等價 index，視為 migration 失敗。

## 9. 必要 smoke tests

以下 smoke tests 是正式切換前的必要 gate，不可只因 workflow process exit code 為 `0` 就省略。這些檢查只讀取 migration summary、schema metadata 與 Automation pending-run 候選資料，不修改目標資料。

### 9.1 Summary、row count 與 revision

確認所有 job 的逐表覆核、三庫 revision 與 workflow health check 都成功：

```bash
jq -e '
  .success == true and
  .migration.row_counts_match == true and
  ([.migration.jobs[].row_count_verification[] | select(.matches != true)] | length == 0) and
  ([.verification.targets[] |
    select(.ready != true or .current_revision != .head_revision)] | length == 0) and
  .health_check.ok == true and
  .health_check.status_code == 200
' "$RUN_DIR/summary.json" >/dev/null
```

若存在 filtered rows，確認全部可由 allowlisted orphan repair 解釋，且 expected target 計算正確：

```bash
jq -e '
  [.migration.jobs[].row_count_verification[] |
    select(.filtered_rows > 0) |
    select(
      .filtered_rows != (.repair_counts.skipped_orphan_item_refs // 0) or
      .expected_target_rows != (.source_rows - .filtered_rows)
    )
  ] | length == 0
' "$RUN_DIR/summary.json" >/dev/null
```

任一命令非零即停止，不得切換 app。

### 9.2 MySQL schema 與 Automation sync query

載入 target env，以 SQLAlchemy 實際連線確認 canonical indexes、auto-named duplicates，以及 MySQL pending-sync SQL。此 smoke query 只執行候選 run 的 `SELECT`，不呼叫 CI provider、不更新 run：

```bash
set -a
source /secure/path/target.env
set +a
uv run python - <<'PY'
import os

from sqlalchemy import create_engine, inspect, select

from app.models.database_models import AutomationRun
from app.services.automation.run_service import _pending_run_order_clauses

expected_indexes = {
    "active_sessions": {"ix_sessions_expires"},
    "password_reset_tokens": {"ix_reset_tokens_expires"},
    "test_case_sets": {"ix_test_case_sets_team"},
    "user_team_permissions": {
        "ix_user_team_perms_permission",
        "ix_user_team_perms_team",
        "ix_user_team_perms_user",
    },
}
removed_indexes = {
    "ix_active_sessions_expires_at",
    "ix_password_reset_tokens_expires_at",
    "ix_test_case_sets_team_id",
    "ix_user_team_permissions_permission",
    "ix_user_team_permissions_team_id",
    "ix_user_team_permissions_user_id",
}

engine = create_engine(os.environ["SYNC_DATABASE_URL"], future=True)
try:
    inspector = inspect(engine)
    actual_indexes = {
        table: {index["name"] for index in inspector.get_indexes(table)}
        for table in expected_indexes
    }
    for table, expected in expected_indexes.items():
        assert expected <= actual_indexes[table], (table, actual_indexes[table])
    assert not removed_indexes.intersection(
        index_name
        for indexes in actual_indexes.values()
        for index_name in indexes
    )

    statement = select(AutomationRun.id).order_by(
        *_pending_run_order_clauses()
    ).limit(1)
    with engine.connect() as connection:
        connection.execute(statement).all()
        connection.execute(statement).all()
finally:
    engine.dispose()

print("MySQL schema and Automation sync smoke passed")
PY
SMOKE_RC=$?
unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL
test "$SMOKE_RC" -eq 0
```

### 9.3 切換後 app smoke

部署環境切換並重啟後，設定實際 app base URL，確認 health endpoint：

```bash
TCRT_BASE_URL=https://tcrt.example.com
curl --fail --silent --show-error "$TCRT_BASE_URL/health" | jq -e '.status == "healthy"'
```

接著以一般唯讀操作抽樣確認：

- Test Case 列表與一筆明細可開啟。
- Test Run 列表與一筆結果可開啟。
- User Story Map 列表與一張 map 可開啟。
- audit 查詢可讀取切換後新產生的登入或檢視事件。
- Automation background sync 至少跨兩個 tick 沒有 `NULLS FIRST` 或 SQL syntax error。

## 10. 將正式系統切換到 MySQL

只有第 8 節全部通過後才能切換：

1. 保留來源四組 URL 與原部署設定，作為 rollback 設定。
2. 將部署環境的 `DATABASE_URL`、`SYNC_DATABASE_URL`、`AUDIT_DATABASE_URL`、`USM_DATABASE_URL` 更新為 `target.env` 的相同值。
3. 依現行部署方式重啟 app 與 worker；不要同時啟動仍指向來源 DB 的寫入服務。
4. 在新 app instance 檢查 `GET /health` 為 HTTP `200`。
5. 使用 target env 再跑一次只讀驗證：

```bash
set -a
source /secure/path/target.env
set +a
uv run python database_init.py --verify-target all --json --quiet > /tmp/tcrt-mysql-post-cutover.json
VERIFY_RC=$?
unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL
test "$VERIFY_RC" -eq 0
sed -n '/^{/,$p' /tmp/tcrt-mysql-post-cutover.json > /tmp/tcrt-mysql-post-cutover-clean.json
jq '[.targets[] | {target, ready, current_revision, head_revision}]' /tmp/tcrt-mysql-post-cutover-clean.json
```

6. 執行第 9.3 節的切換後 app smoke。

完成後才解除維護狀態。

## 11. 失敗與 rollback

### 尚未切換 app

- 保持 app 停止或仍指向來源。
- 來源未被 migration 工具修改，可直接維持來源為正式 DB。
- 保留 `$RUN_DIR`、備份與兩份 env files 供排查。
- 目標可能已有部分 schema 或資料；修正原因後，重新執行會因非空防呆停止。

若確認目標三庫都是本次失敗產生、可以全部清空，且已取得操作者對這三個明確 database 的破壞性操作核准，才可重跑：

```bash
uv run python scripts/run_db_cutover_workflow.py \
  --mode migrate \
  --target mysql \
  --source-env-file /secure/path/source.env \
  --target-env-file /secure/path/target.env \
  --force-reset-target \
  --health-timeout 120
```

`--force-reset-target` 會清空目標 main、audit、usm 的全部業務資料；不得對仍在使用或不確定歸屬的 DB 執行。

### 已切換 app

1. 立即停止指向 MySQL 目標的 app、worker 與 scheduler，避免 rollback 期間繼續寫入。
2. 將部署環境四組 URL 全部還原為保存的來源設定。
3. 重啟舊設定的 app，確認 `/health` 與來源關鍵頁面。
4. 記錄切換後目標產生的新資料；來源與目標可能已分岔，不得自行雙向合併。
5. 保留目標 DB 原狀供事故分析，除非另有明確刪除核准。

## 12. 本路徑的實跑證據

此流程於 `2026-07-16` 使用隔離的 SQLite 三庫非空來源與 MySQL 8.4 目標實跑：

- main：59 張業務表完成逐表 row count 覆核，sentinel 資料存在。
- audit：1 張業務表完成逐表 row count 覆核，sentinel 資料存在。
- usm：2 張業務表完成逐表 row count 覆核，map 與 node sentinel 資料存在。
- 三庫 `current_revision` 均等於各自 `head_revision`。
- app 使用 MySQL 四組 URL 啟動後，`GET /health` 回 HTTP `200` 與 `{"status":"healthy"}`。
- 目標帳號只有三個目標 databases 的權限，沒有 MySQL `mysql` 管理 database 權限。

同日另以 MySQL 8.0 regression databases 執行完整三庫 `--mode migrate` workflow：含一筆孤立 history 與兩個 legacy attachment 欄位的 SQLite fixture，其 `success=true`、`row_counts_match=true`、app health 通過；main 至 `8f1b2c3d4e5a` 後沒有重複等價 index，Automation pending-sync 查詢也可直接在 MySQL 執行。

實跑 artifacts 位於 `.tmp/db-cutover/`，屬本機驗證輸出，不應提交 Git。正式執行時必須以該次新產生的 `summary.json` 為準，不得引用本節作為正式環境已完成的證據。
