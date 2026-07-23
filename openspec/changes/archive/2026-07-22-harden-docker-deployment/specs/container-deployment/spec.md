## ADDED Requirements

### Requirement: Compose fails fast on incomplete deployment inputs
系統的 app Compose 設定 SHALL 在 attachments 與 reports host path 等必要 interpolation 值缺漏時於 config 階段失敗，且 SHALL 使用同一份明確指定的 Docker environment file 進行 Compose interpolation 與容器環境載入。

#### Scenario: Missing storage path is rejected before container creation
- **WHEN** 部署未提供 `ATTACHMENTS_ROOT_DIR` 或 `REPORTS_ROOT_DIR`
- **THEN** `docker compose config` 以非零狀態結束並指出缺少的變數
- **AND** 不產生空白或相對的 volume target

#### Scenario: Documented command resolves the example environment
- **WHEN** 使用文件記載的 `--env-file .env.docker` 指令與完整環境檔執行 Compose
- **THEN** app environment 與所有 Compose interpolation 均解析為同一份部署設定

### Requirement: Container port and healthcheck remain coherent
系統 SHALL 將 app container 內部監聽 port 固定為 `9999`，並使 Dockerfile healthcheck、Compose healthcheck 與 port target 使用同一 port；可設定的 published port SHALL 僅改變 host 端 port。

#### Scenario: Custom published port keeps container healthcheck valid
- **WHEN** 部署設定不同的 `APP_PUBLISHED_PORT`
- **THEN** host 端使用該 port 對應 container port `9999`
- **AND** container 仍於 `9999` 監聽且兩層 healthcheck 均檢查 `9999`

### Requirement: Container network defaults enforce explicit trust
系統的 app 與 disposable database Compose 設定 SHALL 預設只將 published ports 綁定 host loopback；app SHALL NOT 預設信任所有來源的 forwarded headers，部署者可用明確環境設定覆寫 published host 與可信 proxy IP/CIDR。

#### Scenario: Default ports are host-local
- **WHEN** 使用範例預設值解析 app、MySQL 與 PostgreSQL Compose
- **THEN** published ports 綁定 `127.0.0.1`
- **AND** 區網介面不因 Compose 預設而直接暴露服務

#### Scenario: Direct client cannot spoof proxy headers by default
- **WHEN** app 使用 Docker 範例預設啟動且未設定可信 reverse proxy
- **THEN** proxy header handling 預設停用或僅信任 loopback
- **AND** 不使用 `FORWARDED_ALLOW_IPS=*` 信任任意 client

### Requirement: Host service access is portable across Docker platforms
系統的 app Compose 設定 SHALL 提供 `host.docker.internal` 到 host gateway 的明確 mapping，使 Docker Engine on Linux 與 Docker Desktop 可使用一致的 host service hostname。

#### Scenario: Linux container resolves host service alias
- **WHEN** app 在 Linux Docker Engine 上以 Compose 啟動
- **THEN** `host.docker.internal` 經 `host-gateway` mapping 解析到 host bridge gateway

## MODIFIED Requirements

### Requirement: Configuration reaches the container
系統 SHALL 提供標準化且可選的 Compose override 機制，讓部署者以 `APP_CONFIG_FILE` 將既有 `config.yaml` 唯讀掛載到固定 container path，並以 `APP_CONFIG_PATH` 讀取；未使用 override 時系統 SHALL 回退既有內建預設且不中斷啟動。若明確要求掛載但來源檔不存在，Compose SHALL fail fast 而不得建立同名目錄。

#### Scenario: Mounted config takes effect
- **WHEN** 部署以 config override 與有效 `APP_CONFIG_FILE` 啟動容器
- **THEN** 該檔唯讀掛載到固定 container config path
- **AND** 系統套用該檔內的設定（例如 AI helper 調校），而非僅跑預設值

#### Scenario: Missing optional config falls back to defaults
- **WHEN** 容器未套用 config override
- **THEN** 系統以內建預設值啟動且不失敗
- **AND** Compose 不在 host 自動建立 `config.yaml` 目錄

#### Scenario: Requested config source is missing
- **WHEN** 部署套用 config override，但 `APP_CONFIG_FILE` 未設定或指向不存在的檔案
- **THEN** Compose 在 config 或 container creation 前失敗並回報來源問題
- **AND** 不建立同名 host 目錄

### Requirement: Hardened runtime image
系統的容器映像 SHALL 以非 root 使用者執行、於映像層級內建 `HEALTHCHECK`，且最終 runtime 映像 SHALL NOT 包含僅供建置使用的工具鏈。Docker build context 與 final image SHALL 排除真實環境檔、secret-bearing config variants、資料庫備份、logs、private keys 與本機工具產物；runtime 內的 database backup clients SHALL 與專案支援的 MySQL 8.4 與 PostgreSQL 16 server 相容。

#### Scenario: Container runs as non-root
- **WHEN** 以該映像啟動容器
- **THEN** 應用程式行程以非 root 使用者執行
- **AND** 金鑰與狀態目錄對該使用者可寫

#### Scenario: Image carries its own healthcheck
- **WHEN** 容器啟動並通過啟動期
- **THEN** 映像內建的 `HEALTHCHECK` 對 `/health` 回報健康狀態，無需依賴外部 compose 設定

#### Scenario: Build-only and local data stay outside the image
- **WHEN** 從包含 `.env.docker`、`db_backups/`、logs 與工具輸出的工作目錄建置映像
- **THEN** 這些檔案不進入 build context 或 final image
- **AND** 最終映像不含 `build-essential` 等僅建置期需要的套件

#### Scenario: PostgreSQL backup client matches supported server major
- **WHEN** 建置支援 PostgreSQL 16 的 runtime image
- **THEN** `pg_dump --version` 與 `pg_restore --version` 回報 major 16
- **AND** client 可對 PostgreSQL 16 執行升版前備份與還原
