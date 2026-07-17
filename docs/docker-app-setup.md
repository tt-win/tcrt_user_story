# Docker App Setup

此文件說明如何將 TCRT 的 `app` 以 Docker 容器方式部署。

注意：

- 本文件只容器化 `app`
- `DB` 視為外部服務

## 1. 前置條件

請先準備以下外部服務：

- 主資料庫 (`main`)
- audit 資料庫 (`audit`)
- USM 資料庫 (`usm`)

並確認 app 容器可連到它們。

## 2. 準備環境變數

複製範例檔：

```bash
cp .env.docker.example .env.docker
```

至少要調整：

- `PUBLIC_BASE_URL`
- `DATABASE_URL`
- `SYNC_DATABASE_URL`
- `AUDIT_DATABASE_URL`
- `USM_DATABASE_URL`
- `JWT_SECRET_KEY`

若外部服務目前就跑在你宿主機本機，可直接使用：

- `host.docker.internal`

例如：

- `DATABASE_URL=mysql+asyncmy://user:pass@host.docker.internal:3306/tcrt_main`

如需啟動時略過 bootstrap，可設定：

```bash
SKIP_DATABASE_BOOTSTRAP=1
```

## 3. 啟動 app 容器

```bash
docker compose --env-file .env.docker -f docker-compose.app.yml up -d --build
```

容器啟動時會：

1. 執行 `database_init.py`（失敗時最多重試 `BOOTSTRAP_WAIT_ATTEMPTS` 次、間隔
   `BOOTSTRAP_WAIT_SECONDS` 秒，涵蓋外部 DB 服務啟動當下還沒就緒的競態——這個 compose
   本身不含 DB 服務，見上方「外部依賴」設定）
2. 以前景模式啟動 `uvicorn`

## 4. 健康檢查

```bash
curl http://127.0.0.1:9999/health
```

若你有修改 `APP_PUBLISHED_PORT`，請改用對應 port。

## 5. 停止容器

```bash
docker compose --env-file .env.docker -f docker-compose.app.yml down
```

若同時要清空 app volume：

```bash
docker compose --env-file .env.docker -f docker-compose.app.yml down -v
```

## 6. 部署注意事項

- `WEB_CONCURRENCY`：未設定時依 resolved 主 DB 引擎自動選擇（env `DATABASE_URL` 或 `config.yaml`，經 `scripts/print_inferred_web_concurrency.py`；**SQLite → 1，MySQL/PostgreSQL → 5**）；明確設定時以你的值為準，建議不超過 CPU 核數 × 2。背景服務依 `openspec/specs/background-service-scaling/spec.md` 的 DB advisory-lock leader election 確保跨 worker/副本僅單一執行，`>1` 時 entrypoint 會啟用對應數量的 uvicorn worker；登入 challenge 與權限快取清除也都已改為跨 worker 共用（見 `app/auth/session_service.py`、`app/auth/permission_service.py`），殘留限制包含權限變更跨 worker 最多 30 秒延遲可見，以及認證失敗的 per-IP rate limit 為每個 worker 各自計算，N 個 worker 的有效上限是 N × 30 次/分鐘（見 `openspec/changes/harden-app-token-security/design.md`）。若 `.env.docker` 仍寫死 `WEB_CONCURRENCY=1`，切到 MySQL/PostgreSQL 後請刪除該行或改為 `5`（或你要的值），否則不會套用自動預設。
- 容器內使用 SQLite 時必須設定 `SQLITE_CONTAINER_STORAGE_ACK=1` 才能開機——容器沒有為
  SQLite 檔案掛 volume 時，重建/重新部署會靜默遺失所有資料；正式環境建議改用
  MySQL/PostgreSQL（見 `docs/database-cutover-readiness.md` 的 `--mode migrate`）
- `config.yaml` 預設以唯讀方式從 host 的 `./config.yaml` 掛載進容器（`APP_CONFIG_PATH=/app/config.yaml`）；可用 `APP_CONFIG_FILE` 指定其他 host 路徑。env 變數仍優先於 config.yaml
- 若部署在 reverse proxy 後方，請搭配：
  - `PUBLIC_BASE_URL`
  - `UVICORN_PROXY_HEADERS=1`
  - `FORWARDED_ALLOW_IPS=*`
- 若外部依賴尚未準備好，`database_init.py` 或後續 app startup 可能失敗
- `ATTACHMENTS_ROOT_DIR` 與 `REPORTS_ROOT_DIR` 由 `.env.docker` 指定，`docker-compose.app.yml` 會以「同路徑」bind mount 進 container（不再寫死任何本機路徑）：
  - 例如 `ATTACHMENTS_ROOT_DIR=/srv/tcrt/attachments` 會 mount 成 `/srv/tcrt/attachments:/srv/tcrt/attachments`
  - 這樣可保留既有資料庫中的 `absolute_path` 相容性；若資料庫已存舊路徑，container 內仍能直接讀到檔案
- 若外部 DB 跑在宿主機，容器內不要用 `localhost`，請改用 `host.docker.internal`

### RSA 簽章金鑰持久化（必要）

- 應用程式以 `keys/` 內的 RSA 金鑰對保護登入時傳輸的密碼。金鑰目錄由 `RSA_KEY_DIR` 環境變數決定（預設容器內 `/app/keys`），並由 `docker-compose.app.yml` 的 named volume `tcrt-keys` 持久化。
- **若不持久化此目錄**，每次重建容器都會重生金鑰，導致**先前以舊公鑰加密的 payload 全部無法解密**。請務必保留 `tcrt-keys` volume（`down` 時不要加 `-v`）。
- **既有金鑰遷移**：若你之前已在 host 的 `keys/` 產生過金鑰，且要沿用（避免重生），請在首次啟動「新版」容器前，把現有金鑰連同權限複製進 named volume，例如：

  ```bash
  # 將現有 keys/*.pem 灌入 named volume，保留 0600 並 chown 給容器內非 root 使用者（uid 10001）
  docker run --rm -v tcrt-keys:/keys -v "$(pwd)/keys":/src:ro alpine \
    sh -c "cp /src/private_key.pem /src/public_key.pem /keys/ \
           && chmod 600 /keys/private_key.pem \
           && chown -R 10001:10001 /keys"
  ```

  之後啟動容器時，`PasswordEncryptionService.initialize()` 會走「有檔則載入」分支、不重生。可用私鑰指紋於遷移前後比對確認一致。

### 開機升版備份與回退（建議持久化）

- `database_init.py` 只在偵測到某資料庫有 pending Alembic 升版時才建立升版前備份；已是最新版本則略過，不產生備份檔（詳見 `docs/database-cutover-readiness.md`）。
- 備份與連續失敗 marker 存放於 `BOOTSTRAP_BACKUP_DIR`（預設容器內 `/app/db_backups`），由 `docker-compose.app.yml` 的 named volume `tcrt-db-backups` 持久化。**若不持久化此目錄**：`BOOTSTRAP_ON_FAILURE=rollback` 仍可還原「本次啟動建立的備份」（備份物件留在記憶體內，不依賴此目錄讀取），但連續失敗計數會在每次容器重建後歸零，`BOOTSTRAP_MAX_UPGRADE_ATTEMPTS` 的防迴圈保護將失效。
- `BOOTSTRAP_ON_FAILURE=rollback` 還原 PostgreSQL 需要應用程式的 DB 帳號擁有 `public` schema（可執行 `DROP SCHEMA` / `CREATE SCHEMA`）；還原 MySQL 需要 `DROP TABLE` / `CREATE TABLE` 權限。若帳號權限不足，回退會失敗並以 exit code 9 結束，備份檔仍保留於 volume 供人工還原。
- runtime image 已內建 `mysqldump`/`mysql`（`default-mysql-client`）與 `pg_dump`/`pg_restore`（`postgresql-client`）。若改用自訂 base image，請確保這些工具存在，否則 `BOOTSTRAP_BACKUP_MODE=required`（預設）下備份失敗即中止啟動。

### 非 root 執行與目錄權限

- 映像以固定的非 root 使用者 **uid/gid 10001（`app`）** 執行（multi-stage build，最終映像不含 `build-essential`）。
- **金鑰 named volume（`tcrt-keys`）**：映像已預建 `/app/keys` 並 chown 給 `app`，Docker 初始化 volume 時會沿用此 ownership，故 app 可讀寫（全新部署會自動產生金鑰；遷移既有金鑰見上方 chown 步驟）。
- **備份 named volume（`tcrt-db-backups`）**：映像已預建 `/app/db_backups` 並 chown 給 `app`，同樣沿用此 ownership，無需額外授權。
- **附件 / 報告 bind mount**：host 上的 `ATTACHMENTS_ROOT_DIR` / `REPORTS_ROOT_DIR` 目錄必須對 uid `10001` 可寫，否則上傳會失敗。請於 host 先建立並授權，例如：

  ```bash
  sudo mkdir -p "$ATTACHMENTS_ROOT_DIR" "$REPORTS_ROOT_DIR"
  sudo chown -R 10001:10001 "$ATTACHMENTS_ROOT_DIR" "$REPORTS_ROOT_DIR"
  ```
