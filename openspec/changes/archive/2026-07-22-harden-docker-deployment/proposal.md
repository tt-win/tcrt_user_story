## Why

目前 Docker 建置 context 會納入未排除的環境檔、資料庫備份與工具產物，且 PostgreSQL 16 部署搭配 Bookworm 預設的 PostgreSQL 15 client，可能讓敏感資料進入映像並使啟動前備份失敗。Compose 的 port、proxy、host gateway、設定檔與變數插值也有不一致或過度寬鬆的預設，需在映像發布前收斂成可驗證的安全部署契約。

## What Changes

- 收斂 Docker build context，排除所有真實環境檔、設定覆寫、資料庫備份、log 與本機工具產物，並避免 `chown -R` 形成大型重複 layer。
- 讓 runtime image 明確安裝與支援的 PostgreSQL 16 server 相容的 client，並加入版本驗證。
- 讓 Compose 對必要的附件／報告路徑與設定來源 fail fast，統一容器內 port 與 healthcheck，並補齊 Linux host gateway。
- 將 app 與 disposable DB 的 published ports 預設限制在 loopback；proxy headers 僅信任明確設定的來源，不再預設信任所有 client。
- 修正 README、Docker 部署文件與環境範例，使所有指令一致使用 `.env.docker` 做 Compose 插值。
- 新增不需真實 secrets 的 Docker／Compose 靜態驗證，防止上述契約再次漂移。

## Capabilities

### New Capabilities

無。

### Modified Capabilities

- `container-deployment`: 強化建置 context、資料庫工具相容性、Compose fail-fast／port 一致性、host gateway 與網路信任邊界要求。

## Impact

- Docker：`Dockerfile`、`.dockerignore`、三份 Compose、`docker/app-entrypoint.sh`。
- 設定與文件：`.env.docker.example`、`.env.example`、`.gitignore`、`README.md`、`docs/docker-app-setup.md`、資料庫 cutover 文件。
- 驗證：Docker/Compose 靜態檢查與既有 container deployment tests。
- 相容性：既有 `.env.docker` 仍可沿用，但啟動指令必須提供 `--env-file .env.docker`；直接對外發布或位於 reverse proxy 後方的部署需明確設定 host bind 與可信 proxy 範圍。
- 資料／rollback：不修改 schema 或既有 volume 內容；若新映像驗證失敗，可回退舊映像，既有 DB、金鑰與備份 named volumes 不需轉換。
