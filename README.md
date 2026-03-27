# TCRT - Test Case Repository Tool

TCRT 是一套基於 FastAPI 的測試案例管理系統，支援測試案例維護、測試執行追蹤、AI 輔助產生測試案例、Jira/Lark 整合，以及 User Story Map 等功能。

## 目錄

- [快速開始](#快速開始)
- [環境變數參考](#環境變數參考)
- [設定檔 (config.yaml)](#設定檔-configyaml)
- [資料庫架構](#資料庫架構)
- [Docker 部署](#docker-部署)
- [資料庫遷移工具](#資料庫遷移工具)
- [附件路徑正規化工具](#附件路徑正規化工具)
- [專案結構](#專案結構)

---

## 快速開始

### 本地開發（SQLite）

```bash
# 安裝依賴
uv sync

# 複製設定檔
cp config.yaml.example config.yaml

# 初始化資料庫
uv run python database_init.py

# 啟動開發伺服器
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 9999
```

### Docker 部署

```bash
# 複製環境變數範本
cp .env.docker.example .env.docker

# 啟動 PostgreSQL（或 MySQL）
docker compose -f docker-compose.postgres.yml up -d

# 建置並啟動應用
docker compose -f docker-compose.app.yml up -d --build
```

---

## 環境變數參考

以下為 `.env.docker.example` 中所有可用的環境變數。本地開發可使用 `config.yaml` 替代大部分設定。

### 執行環境

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `APP_ENV` | — | 執行環境標識，設為 `docker` 啟用容器模式 |
| `RUNNING_IN_DOCKER` | `0` | 是否在 Docker 容器內執行 |
| `APP_CONFIG_PATH` | — | 指定 `config.yaml` 路徑；未設定時自動偵測 |

### Web 伺服器

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `DEBUG` | `false` | 啟用除錯模式 |
| `HOST` | `0.0.0.0` | 綁定的 IP 位址 |
| `PORT` | `9999` | 綁定的連接埠 |
| `APP_PUBLISHED_PORT` | `9999` | Docker 對外映射的連接埠 |
| `PUBLIC_BASE_URL` | — | 對外可達的完整網址，用於產生連結（如報告下載連結） |
| `APP_BASE_URL` | — | `PUBLIC_BASE_URL` 的舊名別稱（已棄用） |

### 資料庫

系統使用三個獨立資料庫：main（主資料）、audit（稽核紀錄）、usm（User Story Map）。

| 變數 | 說明 |
|------|------|
| `DATABASE_URL` | 主資料庫連線字串（async driver，如 `postgresql+asyncpg://`、`mysql+asyncmy://`、`sqlite+aiosqlite:///`） |
| `SYNC_DATABASE_URL` | 主資料庫同步連線字串（sync driver，如 `postgresql+psycopg://`），供 Alembic migration 與 bootstrap 使用 |
| `AUDIT_DATABASE_URL` | 稽核資料庫連線字串（async driver） |
| `USM_DATABASE_URL` | User Story Map 資料庫連線字串（async driver） |
| `ALLOW_SYNC_DB_RUNTIME` | 是否允許執行期使用同步資料庫引擎（預設關閉），migration 腳本需要時才開啟 |

**支援的資料庫：** SQLite、MySQL 8.x、PostgreSQL 16+

### 容器啟動

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `SKIP_DATABASE_BOOTSTRAP` | `0` | 設為 `1` 跳過啟動時的資料庫初始化（schema migration） |
| `UVICORN_LOG_LEVEL` | `info` | Uvicorn 日誌等級 |
| `UVICORN_PROXY_HEADERS` | `1` | 啟用反向代理 header 信任 |
| `FORWARDED_ALLOW_IPS` | `*` | 允許的轉發來源 IP |
| `WEB_CONCURRENCY` | `1` | Worker 數量，因內建排程器非 multi-worker safe，建議保持 `1` |

### Qdrant 向量資料庫

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `QDRANT_URL` | — | Qdrant 服務位址 |
| `QDRANT_API_KEY` | — | Qdrant API 金鑰 |
| `QDRANT_TIMEOUT` | `30` | 連線逾時（秒） |
| `QDRANT_PREFER_GRPC` | `false` | 是否優先使用 gRPC 連線 |
| `QDRANT_POOL_SIZE` | `32` | 連線池大小 |
| `QDRANT_MAX_CONCURRENT_REQUESTS` | `32` | 最大併發請求數 |
| `QDRANT_MAX_RETRIES` | `3` | 失敗重試次數 |
| `QDRANT_RETRY_BACKOFF_SECONDS` | `0.5` | 重試退避初始間隔（秒） |
| `QDRANT_RETRY_BACKOFF_MAX_SECONDS` | `5.0` | 重試退避最大間隔（秒） |
| `QDRANT_CHECK_COMPATIBILITY` | `true` | 啟動時檢查版本相容性 |
| `QDRANT_COLLECTION_JIRA_REFERENCES` | `jira_references` | Jira 參考資料的 collection 名稱 |
| `QDRANT_COLLECTION_TEST_CASES` | `test_cases` | 測試案例的 collection 名稱 |
| `QDRANT_COLLECTION_USM_NODES` | `usm_nodes` | USM 節點的 collection 名稱 |

### Embedding 服務

| 變數 | 說明 |
|------|------|
| `TEXT_EMBEDDING_URL` | 文字向量化 API 位址（OpenAI 相容格式） |
| `EMBEDDING_API_URL` | `TEXT_EMBEDDING_URL` 的舊名別稱（已棄用） |

### 檔案儲存

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `ATTACHMENTS_ROOT_DIR` | 專案內 `attachments/` | 測試案例附件儲存根目錄 |
| `REPORTS_ROOT_DIR` | 專案內 `generated_report/` | 報告產出儲存根目錄 |

### 認證 (Auth)

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `ENABLE_AUTH` | `true` | 啟用認證機制 |
| `JWT_SECRET_KEY` | — | JWT 簽章密鑰（**必填，務必自行產生**） |
| `JWT_EXPIRE_DAYS` | `7` | JWT Token 有效天數 |
| `PASSWORD_RESET_EXPIRE_HOURS` | `24` | 密碼重設連結有效時數 |
| `SESSION_CLEANUP_DAYS` | `30` | 過期 session 自動清理天數 |

### 稽核 (Audit)

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `ENABLE_AUDIT` | `true` | 啟用稽核紀錄 |
| `AUDIT_BATCH_SIZE` | `100` | 稽核寫入批次大小 |
| `AUDIT_CLEANUP_DAYS` | `365` | 稽核紀錄保留天數 |
| `AUDIT_MAX_DETAIL_SIZE` | `10240` | 單筆稽核明細最大字元數 |
| `AUDIT_DEBUG_SQL` | `false` | 啟用稽核資料庫 SQL 除錯輸出 |

### USM

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `USM_DEBUG_SQL` | `false` | 啟用 USM 資料庫 SQL 除錯輸出 |

### Lark（飛書）整合

| 變數 | 說明 |
|------|------|
| `LARK_APP_ID` | Lark 應用程式 ID |
| `LARK_APP_SECRET` | Lark 應用程式密鑰 |
| `LARK_DRY_RUN` | 設為 `true` 時只模擬同步，不實際寫入 |

### Jira 整合

| 變數 | 說明 |
|------|------|
| `JIRA_SERVER_URL` | Jira Server/DC 網址 |
| `JIRA_USERNAME` | Jira 使用者名稱 |
| `JIRA_API_TOKEN` | Jira API Token |
| `JIRA_CA_CERT_PATH` | 自簽憑證路徑（選填，HTTPS 自簽時需要） |

### LLM / AI

| 變數 | 說明 |
|------|------|
| `OPENROUTER_API_KEY` | OpenRouter API 金鑰，用於 AI 輔助功能 |

> AI 模型選擇、溫度等進階設定位於 `config.yaml` 的 `ai` 區段。

### 初始化管理員帳號

| 變數 | 說明 |
|------|------|
| `BOOTSTRAP_SUPER_ADMIN_USERNAME` | 初始管理員帳號（預設 `admin`） |
| `BOOTSTRAP_SUPER_ADMIN_FULL_NAME` | 初始管理員顯示名稱 |
| `BOOTSTRAP_SUPER_ADMIN_EMAIL` | 初始管理員信箱 |
| `BOOTSTRAP_SUPER_ADMIN_PASSWORD` | 初始管理員密碼 |

> 這些變數由 `database_init.py` 在首次啟動時使用，資料庫中已有 super_admin 時會跳過。

---

## 設定檔 (config.yaml)

除環境變數外，也可透過 `config.yaml` 設定所有參數（本地開發推薦使用）。參考 `config.yaml.example`。

環境變數 **優先於** config.yaml 中的同名設定。

---

## 資料庫架構

系統使用三個獨立資料庫，各自有獨立的 Alembic migration 設定：

| 資料庫 | 用途 | Alembic 設定 | Migration 目錄 |
|--------|------|-------------|---------------|
| main | 測試案例、使用者、團隊、測試執行 | `alembic.ini` | `alembic/` |
| audit | 稽核紀錄 | `alembic_audit.ini` | `alembic_audit/` |
| usm | User Story Map | `alembic_usm.ini` | `alembic_usm/` |

`database_init.py` 會在啟動時自動對三個資料庫執行 Alembic upgrade。

---

## Docker 部署

### 架構

```
docker-compose.app.yml       # 應用程式容器
docker-compose.postgres.yml  # PostgreSQL（三庫共用，透過 init script 建立）
docker-compose.mysql.yml     # MySQL（三庫共用，透過 init script 建立）
```

### 基本流程

```bash
# 1. 啟動資料庫
docker compose -f docker-compose.postgres.yml up -d

# 2. 編輯 .env.docker，設定 DATABASE_URL 等連線資訊
cp .env.docker.example .env.docker

# 3. 啟動應用
docker compose -f docker-compose.app.yml up -d --build
```

容器啟動時會自動執行 `database_init.py` 初始化 schema（可用 `SKIP_DATABASE_BOOTSTRAP=1` 跳過）。

---

## 資料庫遷移工具

### `scripts/db_cross_migrate.py`

跨資料庫資料搬移工具，用於在 SQLite / MySQL / PostgreSQL 之間遷移資料。此腳本**獨立運作**，不依賴 `app/` 模組。

#### 使用情境

- 從 SQLite 開發環境遷移到 MySQL/PostgreSQL 正式環境
- 在不同資料庫引擎之間搬移資料

#### 前置條件

1. **目標資料庫 schema 已存在** — 先透過 `database_init.py` 或 Alembic 初始化目標資料庫
2. 安裝 Python 依賴（`sqlalchemy`、`pyyaml`，以及對應的資料庫驅動）

#### 使用方式

**方式一：YAML 設定檔（推薦）**

```bash
# 複製設定檔範本
cp scripts/db_cross_migrate.yaml.example scripts/db_cross_migrate.yaml

# 先驗證（dry-run）
uv run python scripts/db_cross_migrate.py --config scripts/db_cross_migrate.yaml --dry-run

# 執行搬移
uv run python scripts/db_cross_migrate.py --config scripts/db_cross_migrate.yaml
```

**方式二：命令列參數**

```bash
uv run python scripts/db_cross_migrate.py \
  --source-url "sqlite:///./test_case_repo.db" \
  --target-url "mysql+pymysql://root:password@127.0.0.1:3306/tcrt_main" \
  --reset-target \
  --disable-constraints
```

#### YAML 設定檔格式（`db_cross_migrate.yaml`）

```yaml
defaults:                        # 所有 job 共用的預設值
  chunk_size: 1000               # 每次批量插入的筆數
  reset_target: false            # 是否在搬移前清空目標表
  create_target_schema: false    # 是否從來源自動建立目標缺少的表
  disable_constraints: false     # 搬移時是否暫時停用外鍵約束
  exclude_tables:                # 排除不搬移的表
    - alembic_version
    - migration_history

jobs:                            # 搬移任務列表
  - name: main-sqlite-to-mysql   # 任務名稱（自訂）
    source_url: sqlite:///./test_case_repo.db       # 來源資料庫連線字串
    target_url: mysql+pymysql://root:pw@host/tcrt_main  # 目標資料庫連線字串

  - name: audit-sqlite-to-mysql
    source_url: sqlite:///./audit.db
    target_url: mysql+pymysql://root:pw@host/tcrt_audit

  - name: usm-sqlite-to-mysql
    source_url: sqlite:///./userstorymap.db
    target_url: mysql+pymysql://root:pw@host/tcrt_usm
```

> 三個資料庫（main / audit / usm）需要分別設定 job 進行搬移。

#### 命令列參數

| 參數 | 說明 |
|------|------|
| `--config` | YAML 設定檔路徑 |
| `--job` | 僅執行指定名稱的 job（搭配 `--config` 使用） |
| `--source-url` | 來源資料庫連線字串（單次執行模式） |
| `--target-url` | 目標資料庫連線字串（單次執行模式） |
| `--include-tables` | 僅搬移指定表（逗號分隔）；預設搬移所有表 |
| `--exclude-tables` | 排除指定表（逗號分隔）；預設排除 `alembic_version`, `migration_history` |
| `--chunk-size` | 批次插入筆數（預設 `1000`） |
| `--reset-target` | 搬移前清空目標表資料 |
| `--create-target-schema` | 從來源 metadata 自動建立目標缺少的表 |
| `--disable-constraints` | 搬移時暫時停用外鍵約束（處理循環依賴時需要） |
| `--dry-run` | 僅驗證並顯示計畫，不寫入任何資料 |
| `--json` | 輸出 JSON 格式摘要 |
| `--verbose` | 顯示詳細除錯訊息 |
| `--quiet` | 靜默模式 |

#### 特殊處理

- **MySQL TEXT 自動升級**：若來源資料超過目標 MySQL TEXT 欄位容量，會自動升級為 MEDIUMTEXT / LONGTEXT
- **自參照外鍵排序**：自動處理表內自參照的外鍵順序（如 tree structure）
- **test_cases 修補**：自動修補缺少 `test_case_set_id` 的資料（從 section 或 team default 推導）
- **test_run_item_result_history 過濾**：自動跳過參照不存在 test_run_item 的孤兒紀錄

#### 完整搬移範例（SQLite → MySQL）

```bash
# 1. 啟動 MySQL
docker compose -f docker-compose.mysql.yml up -d

# 2. 初始化目標資料庫 schema（先設好 config.yaml 指向 MySQL）
uv run python database_init.py

# 3. 編輯搬移設定
cp scripts/db_cross_migrate.yaml.example scripts/db_cross_migrate.yaml
# 修改 target_url 中的密碼和主機

# 4. 驗證
uv run python scripts/db_cross_migrate.py --config scripts/db_cross_migrate.yaml --dry-run

# 5. 執行（建議加 --reset-target --disable-constraints）
uv run python scripts/db_cross_migrate.py \
  --config scripts/db_cross_migrate.yaml \
  --reset-target \
  --disable-constraints
```

---

## 附件路徑正規化工具

### `scripts/migrate_attachment_metadata_paths.py`

一次性腳本，將資料庫中的附件 metadata 從絕對路徑格式正規化為相對路徑格式。

#### 使用情境

當專案從絕對路徑儲存附件改為相對路徑模式（`ATTACHMENTS_ROOT_DIR` + 相對路徑），需要執行此腳本將現有資料庫紀錄中的附件路徑正規化。**只需要執行一次。**

#### 影響的資料表欄位

| 表 | 欄位 | 說明 |
|----|------|------|
| `test_cases` | `attachments_json` | 測試案例的附件清單 |
| `test_run_items` | `execution_results_json` | 測試執行結果的附件 |
| `test_run_items` | `upload_history_json` | 測試執行上傳歷史中的附件 |

#### 使用方式

```bash
# 先以 dry-run 模式檢視會影響的筆數
uv run python scripts/migrate_attachment_metadata_paths.py

# 確認無誤後，加上 --write 實際寫入
uv run python scripts/migrate_attachment_metadata_paths.py --write
```

#### 輸出範例

```json
{
  "mode": "dry-run",
  "test_case_rows": 42,
  "test_run_execution_rows": 15,
  "test_run_history_rows": 8
}
```

> 此腳本依賴 `app/` 模組（使用 `get_sync_engine()` 和 `normalize_attachment_metadata()`），需在專案根目錄執行。

---

## 專案結構

```
.
├── app/                         # 主應用程式
│   ├── main.py                  # FastAPI 進入點
│   ├── config.py                # 設定管理
│   ├── database.py              # 資料庫連線引擎
│   ├── api/                     # API 路由
│   ├── auth/                    # 認證授權
│   ├── audit/                   # 稽核系統
│   ├── models/                  # SQLAlchemy 模型 & Pydantic schemas
│   ├── services/                # 業務邏輯
│   └── utils/                   # 工具函式
├── alembic/                     # 主資料庫 migration
├── alembic_audit/               # 稽核資料庫 migration
├── alembic_usm/                 # USM 資料庫 migration
├── scripts/                     # 工具腳本
│   ├── db_cross_migrate.py      # 跨資料庫搬移工具
│   └── migrate_attachment_metadata_paths.py  # 附件路徑正規化
├── docker/                      # Docker 相關檔案
├── config.yaml.example          # 設定檔範本
├── .env.docker.example          # Docker 環境變數範本
├── database_init.py             # 資料庫初始化
├── Dockerfile                   # 容器映像定義
├── docker-compose.app.yml       # 應用容器
├── docker-compose.mysql.yml     # MySQL 容器
└── docker-compose.postgres.yml  # PostgreSQL 容器
```
