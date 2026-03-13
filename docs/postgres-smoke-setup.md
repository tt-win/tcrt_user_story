# PostgreSQL Smoke Setup

此文件提供本專案在本機對 PostgreSQL 執行三套資料庫 `main`、`audit`、`usm` 的 smoke / rehearsal 標準流程。

## 1. 啟動 PostgreSQL

```bash
docker compose -f docker-compose.postgres.yml up -d
```

初始化後會建立：

- `tcrt_main`
- `tcrt_audit`
- `tcrt_usm`

帳號：

- user: `tcrt`
- password: `tcrt`

對外埠號：

- `5433`

## 2. 安裝必要 driver

```bash
pip install asyncpg "psycopg[binary]"
```

## 3. 設定三套資料庫 URL

```bash
export DATABASE_URL='postgresql+asyncpg://tcrt:tcrt@127.0.0.1:5433/tcrt_main'
export SYNC_DATABASE_URL='postgresql+psycopg://tcrt:tcrt@127.0.0.1:5433/tcrt_main'
export AUDIT_DATABASE_URL='postgresql+asyncpg://tcrt:tcrt@127.0.0.1:5433/tcrt_audit'
export USM_DATABASE_URL='postgresql+asyncpg://tcrt:tcrt@127.0.0.1:5433/tcrt_usm'
```

## 4. 執行 preflight

```bash
python3 database_init.py --preflight
```

預期結果：

- 三個 targets 都為 `ready: yes`
- `driver_statuses` 顯示 `asyncpg`、`psycopg` 皆為 `OK`
- `head_revision` 可正確讀取

## 5. 執行 bootstrap 與驗證摘要

```bash
python3 database_init.py
python3 database_init.py --verify-target all
```

預期結果：

- 三套資料庫的 `current_revision` 與 `head_revision` 一致
- `required_tables` 全部為 `OK`

## 6. 啟動應用程式並檢查健康狀態

```bash
HOST=127.0.0.1 PORT=19998 SERVER_PID_FILE=/tmp/tcrt-postgres-smoke.pid UVICORN_RELOAD=0 ./start.sh
curl http://127.0.0.1:19998/health
kill "$(cat /tmp/tcrt-postgres-smoke.pid)"
rm -f /tmp/tcrt-postgres-smoke.pid
```

## 7. 清理環境

```bash
docker compose -f docker-compose.postgres.yml down -v
unset DATABASE_URL SYNC_DATABASE_URL AUDIT_DATABASE_URL USM_DATABASE_URL
```

## 8. Rollback / Re-Verification

若 smoke 或 rehearsal 過程失敗，請依 [database-cutover-readiness.md](database-cutover-readiness.md) 先回退環境與重新驗證，不要直接切換生產流量。
