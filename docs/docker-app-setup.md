# Docker App Setup

此文件說明如何將 TCRT 的 `app` 以 Docker 容器方式部署。

注意：

- 本文件只容器化 `app`
- `DB`、`Qdrant`、`Text Embedding` 都視為外部服務
- 目前內建 scheduler 為 app process 內 thread loop，建議單 worker、單 replica 部署

## 1. 前置條件

請先準備以下外部服務：

- 主資料庫 (`main`)
- audit 資料庫 (`audit`)
- USM 資料庫 (`usm`)
- Qdrant
- Text Embedding service

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
- `QDRANT_URL`
- `TEXT_EMBEDDING_URL`
- `JWT_SECRET_KEY`

若外部服務目前就跑在你宿主機本機，可直接使用：

- `host.docker.internal`

例如：

- `DATABASE_URL=mysql+asyncmy://user:pass@host.docker.internal:3306/tcrt_main`
- `QDRANT_URL=http://host.docker.internal:6333`
- `TEXT_EMBEDDING_URL=http://host.docker.internal:1234/v1/embeddings`

如需啟動時略過 bootstrap，可設定：

```bash
SKIP_DATABASE_BOOTSTRAP=1
```

## 3. 啟動 app 容器

```bash
docker compose --env-file .env.docker -f docker-compose.app.yml up -d --build
```

容器啟動時會：

1. 執行 `database_init.py`
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

- `WEB_CONCURRENCY` 建議保持 `1`
- 若部署在 reverse proxy 後方，請搭配：
  - `PUBLIC_BASE_URL`
  - `UVICORN_PROXY_HEADERS=1`
  - `FORWARDED_ALLOW_IPS=*`
- 若外部依賴尚未準備好，`database_init.py` 或後續 app startup 可能失敗
- `ATTACHMENTS_ROOT_DIR` 與 `REPORTS_ROOT_DIR` 目前直接使用 host 路徑，並以同一路徑 bind mount 進 container：
  - `/Users/hideman/tcrt_files/attachments`
  - `/Users/hideman/tcrt_files/reports`
- 這樣可保留既有資料庫中的 `absolute_path` 相容性；若資料庫已存舊路徑，container 內仍能直接讀到檔案
- 若外部 DB / Qdrant / Embedding 跑在宿主機，容器內不要用 `localhost`，請改用 `host.docker.internal`
