# MySQL Smoke Setup

此文件提供本專案在本機對 MySQL 執行三套資料庫 `main`、`audit`、`usm` 的 smoke / rehearsal 標準流程。

若你要部署正式的 app Docker 容器，請改看 `docs/docker-app-setup.md`；本文件只處理 MySQL smoke / rehearsal。

## 1. 一鍵 smoke workflow

```bash
python3 scripts/run_db_cutover_workflow.py --target mysql --mode smoke --manage-services
```

此流程會自動：

- 啟動 `docker-compose.mysql.yml`
- 執行 guardrails
- 執行 preflight / bootstrap / verify
- 啟動應用程式並檢查 `GET /health`
- 將輸出寫到 `.tmp/db-cutover/<timestamp>-mysql-smoke/`
- 預設在結束時關閉 MySQL 容器

若要保留容器環境供後續手動檢查，可加入 `--keep-services`。

## 2. 啟動 MySQL（手動模式）

```bash
docker compose -f docker-compose.mysql.yml up -d
```

初始化腳本會建立：

- `tcrt_main`
- `tcrt_audit`
- `tcrt_usm`

帳號：

- user: `tcrt`
- password: `tcrt`

## 3. 安裝必要 driver

```bash
pip install asyncmy PyMySQL
```

## 4. 設定三套資料庫 URL

```bash
export DATABASE_URL='mysql+asyncmy://tcrt:tcrt@127.0.0.1:33060/tcrt_main'
export SYNC_DATABASE_URL='mysql+pymysql://tcrt:tcrt@127.0.0.1:33060/tcrt_main'
export AUDIT_DATABASE_URL='mysql+asyncmy://tcrt:tcrt@127.0.0.1:33060/tcrt_audit'
export USM_DATABASE_URL='mysql+asyncmy://tcrt:tcrt@127.0.0.1:33060/tcrt_usm'
```

## 5. 執行 preflight

```bash
python3 database_init.py --preflight
```

預期結果：

- 三個 targets 都顯示 `ready: yes`
- `driver_statuses` 全部為 `OK`
- 不出現 `legacy_unmanaged`

若任何 target 顯示 `legacy_unmanaged`，請依輸出指示先執行對應的：

- `--validate-legacy-<target>-db`
- `--adopt-legacy-<target>-db`

## 6. 執行 bootstrap 與驗證摘要

```bash
python3 database_init.py
python3 database_init.py --verify-target all
```

預期結果：

- 三套資料庫都印出 `Verification`
- `head_revision` 與 `current_revision` 一致
- `required_tables` 全部為 `OK`

## 7. 啟動應用程式並檢查健康狀態

```bash
HOST=127.0.0.1 PORT=19999 SERVER_PID_FILE=/tmp/tcrt-mysql-smoke.pid UVICORN_RELOAD=0 ./start.sh
curl http://127.0.0.1:19999/health
kill "$(cat /tmp/tcrt-mysql-smoke.pid)"
rm -f /tmp/tcrt-mysql-smoke.pid
```

## 8. 執行 rehearsal 並比對 SQLite baseline

先跑一次 SQLite baseline：

```bash
python3 scripts/run_db_cutover_workflow.py --target sqlite --mode rehearsal
```

再將最新的 SQLite `summary.json` 帶進 MySQL rehearsal：

```bash
python3 scripts/run_db_cutover_workflow.py \
  --target mysql \
  --mode rehearsal \
  --manage-services \
  --baseline-summary .tmp/db-cutover/<sqlite-run>/summary.json
```

Rehearsal 會在 `summary.json` 與 `summary.md` 中輸出 row count / revision comparison。

## 9. 清理環境

```bash
docker compose -f docker-compose.mysql.yml down -v
unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL
```

## 10. Rollback / Re-Verification

若 rehearsal 或 smoke 失敗，請依 [database-cutover-readiness.md](database-cutover-readiness.md) 的 rollback 與 re-verification 流程處理，不要直接覆寫來源資料庫。
