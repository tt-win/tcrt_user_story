## Context

TCRT 的 app compose 將資料庫視為外部服務，並以 `.env.docker` 同時提供容器環境與 Compose 插值。現況的 build context 邊界過寬、Bookworm 預設 PostgreSQL client 版本落後於支援的 PostgreSQL 16、short bind mount 會在來源不存在時建立目錄，且 published ports 與 proxy trust 預設過度寬鬆。變更需保留三資料庫 bootstrap、升版前備份、RSA key 與 backup named volume 的既有契約。

## Goals / Non-Goals

**Goals:**

- 讓映像建置不會取得或封裝真實設定、備份、log 與本機工具產物。
- 讓 PostgreSQL backup/restore client major 與專案支援的 PostgreSQL 16 相容。
- 讓 Compose 缺少必要 interpolation 值時立即失敗，且 container port、published port 與 healthcheck 不漂移。
- 預設只在 host loopback 發布 app 與 disposable DB ports，並要求明確設定可信 proxy。
- 保留「未提供 config.yaml 仍可用內建預設啟動」的既有行為。

**Non-Goals:**

- 不把 MySQL/PostgreSQL smoke compose 改成 production database deployment。
- 不修改 schema、DB credential service 或現有 named volume 內容。
- 不導入 Kubernetes、Docker secrets 或外部 KMS。
- 不刪除目前本機映像、container、volume 或疑似含敏感資料的檔案。

## Decisions

### 1. 防護 build context，並在 COPY 時直接指定 ownership

`.dockerignore` 明確排除 `.env*`、實際 root config variants、`db_backups/`、`graphify-out/`、logs、憑證／private key 與其他 runtime data。Dockerfile 保留目前可相容 runtime 資產的 `COPY . .`，但改成 `COPY --chown=app:app`，避免 `chown -R /app` 另外複製大型 layer。

替代方案是立即改成 source allowlist；目前 app 仍會從 repo root 讀取 `prompts/`、`manual/`、`config/` 等資產，未先建立完整 runtime manifest 就改 allowlist 容易漏檔，因此本次先以 denylist + automated contract test 收斂風險。

### 2. 透過 PostgreSQL 官方 PGDG APT repository 安裝 client 16

Bookworm distribution 的 `postgresql-client` meta package 是 15，不能 dump PostgreSQL 16。Runtime stage 依 PostgreSQL 官方 signed repository 作法加入 PGDG source，明確安裝 `postgresql-client-16`，並在 build 階段執行 `pg_dump --version` major 檢查。

替代方案是改用 `postgres:16` 作 runtime base；該映像會帶入 server 相關內容且偏離目前 Python/uv base，攻擊面與變更幅度較大，故不採用。

### 3. Docker 內部 port 固定 9999，只讓 published host port 可設定

Compose 明確覆寫容器 `PORT=9999`，port mapping 與兩層 healthcheck 皆維持 9999；`APP_PUBLISHED_PORT` 只控制 host 端。這避免 `.env.docker` 修改 `PORT` 後產生 healthcheck 與 mapping 漂移。本機非 Docker 的 `start.sh` 仍可使用自訂 `PORT`。

### 4. config.yaml 改為可選 Compose override

Base app compose 不掛載 `config.yaml`，因此全新 clone 或只使用 env 的部署可直接套用內建預設。新增 config override compose，僅在使用者明確提供 `APP_CONFIG_FILE` 時以 long bind syntax 掛載，並設定 `create_host_path: false` 與固定 container target `/app/config.yaml`。

這比把缺少的 host file 自動建立成目錄安全，也比把 example config 當 runtime default 更符合既有 fallback 契約。

### 5. 網路與 proxy trust 採安全預設、允許明確覆寫

新增 `APP_PUBLISHED_HOST`，app、MySQL 與 PostgreSQL published ports 預設綁定 `127.0.0.1`。容器預設停用 proxy headers，`FORWARDED_ALLOW_IPS` 預設只信任 loopback；位於 reverse proxy 後方的部署必須明確開啟並指定 proxy IP/CIDR。App compose 加入 `host.docker.internal:host-gateway`，讓 Linux Docker Engine 與 Docker Desktop 使用同一 hostname。

### 6. 驗證不讀真實 secrets

Compose validation 使用 `.env.docker.example` 搭配 `--no-env-resolution`，避免解析真實 `.env.docker`。靜態測試檢查 ignore contract、port/proxy default、config override 與 PostgreSQL client major；完整 image build 才驗證套件安裝與 final image metadata。

## Risks / Trade-offs

- [PGDG repository 暫時不可用會讓 build 失敗] → 明確 fail build，保留既有已驗證映像作 rollback；不悄悄回退 PG15。
- [Loopback 預設可能改變既有從其他主機直接連線的部署] → 文件列出 `APP_PUBLISHED_HOST=0.0.0.0` 的明確 opt-in，並要求同步設定 firewall/TLS/proxy trust。
- [既有腳本省略 `--env-file`] → README 與 runbook 全面同步；Compose 對必要路徑使用 `:?`，讓錯誤在 config 階段發生。
- [`COPY . .` 仍依賴 denylist 完整性] → 測試鎖定高風險模式，後續可在獨立 change 建立完整 runtime allowlist。

## Migration Plan

1. 修正 ignore、Dockerfile、Compose、環境範例與文件，並先跑不讀真實 secrets 的靜態驗證。
2. 以乾淨 build context 建置新映像，確認 `pg_dump` major 16、非 root user、healthcheck 與映像內容排除契約。
3. 用 disposable PostgreSQL 16 執行 backup/restore smoke，再部署新 app image。
4. 若新映像啟動失敗，停止新 container 並切回舊映像；保留 `tcrt-keys`、`tcrt-db-backups` 與外部 DB，不執行 volume rollback。
5. 對修正前已建置的映像先停止發布；是否刪除本機或 registry artifact 另行取得明確核准。

## Open Questions

無；production 是否公開到非 loopback、proxy CIDR 與外部 DB 位址均由部署者依環境明確設定。
