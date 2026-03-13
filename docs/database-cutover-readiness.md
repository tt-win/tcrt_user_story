# Database Cutover Readiness

此文件定義從 SQLite 切換到 MySQL / PostgreSQL 前的 rehearsal、rollback 與 re-verification 基準流程。

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

## 3. 驗證輸出最低要求

rehearsal 完成後，至少應保留：

- `--preflight` 輸出
- `--verify-target all` 輸出
- `/health` 驗證結果
- 若有資料搬遷，重要表的 row count 比對結果

建議至少比對：

- `main`: `users`、`teams`、`test_cases`
- `audit`: `audit_logs`
- `usm`: `user_story_maps`、`user_story_map_nodes`

## 4. Rollback 前提

若 rehearsal 或切換驗證失敗，rollback 前請先保留：

- 來源資料庫備份或快照
- 失敗當下的目標資料庫 preflight / verification 輸出
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

只有在上述流程恢復正常後，才應重新安排下一次 rehearsal 或正式 cutover。
