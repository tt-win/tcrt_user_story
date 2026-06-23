## 1. P0 地雷 — 金鑰持久化、密鑰快速失敗、可攜路徑

- [x] 1.1 將 `PasswordEncryptionService.KEY_DIR`（[`app/auth/password_encryption.py:20`](app/auth/password_encryption.py:20)）改為可由環境變數（例如 `RSA_KEY_DIR`）覆寫，缺省回退現行 repo 相對 `keys/`，確保未設定時行為不變
- [x] 1.2 在 `docker-compose.app.yml` 為金鑰目錄掛上 named volume，並以環境變數指向容器內路徑，使金鑰於容器重建後存活 — 新增 named volume `tcrt-keys`，掛載於 `${RSA_KEY_DIR:-/app/keys}`
- [x] 1.3 當 `enable_auth` 為真且 `JWT_SECRET_KEY` 缺漏時，於啟動以明確錯誤中止 — 實作為 `startup_event` 開頭（try 區塊之外，故 raise 能真正中止啟動）的快速失敗檢查（[`app/main.py:331`](app/main.py:331)）。**未**改動 `AuthConfig.from_env`：因 `config.py` 於 import 期即載入 settings（`config.py:739`），於 from_env raise 會使所有測試/腳本 import 即崩潰；改於啟動點把關可達成相同「不以空密鑰簽章」意圖且不破壞 import
- [x] 1.4 當系統內已存在 automation provider 資料卻缺 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 時啟動快速失敗 — **已由現有 bootstrap 覆蓋**：`database_init.py` 的 [`verify_automation_provider_encryption_key`](database_init.py:244)（呼叫於 :488/:792）會在 provider 有資料但缺/壞金鑰時 raise，且 entrypoint 於 uvicorn 前先跑 bootstrap，故預設啟動路徑已快速失敗；未另加重複檢查（caveat：`SKIP_DATABASE_BOOTSTRAP=1` 時略過，屬明確 opt-out）
- [x] 1.5 以 `${ATTACHMENTS_ROOT_DIR}` / `${REPORTS_ROOT_DIR}` 取代 `docker-compose.app.yml:15-16` 寫死的 `/Users/hideman/...` 路徑，並提供 `.env` 範例 — compose 改 env 驅動，`.env.docker.example` 補 `RSA_KEY_DIR`
- [x] 1.6 撰寫既有金鑰遷移說明：把現存 `keys/*.pem` 搬入持久化目錄、掛 volume 後沿用，不重生 — 見 [`docs/docker-app-setup.md`](docs/docker-app-setup.md) §6「RSA 簽章金鑰持久化」

## 2. 映像硬化（Dockerfile）

- [x] 2.1 將 `Dockerfile` 改為 multi-stage build：build stage 安裝 `build-essential` 並 `uv sync`，runtime stage 僅複製 venv 與應用程式，最終映像不含 `build-essential` — 另於 `.dockerignore` 新增排除 `keys/`（避免把 host RSA 金鑰烤進映像）
- [x] 2.2 在 runtime stage 建立非 root 使用者並以 `USER` 切換執行；確保金鑰目錄、reports/attachments 目錄對該使用者可寫 — 固定 uid/gid `10001`（`app`）、`chown -R app:app /app`（named volume `tcrt-keys` 掛 `/app/keys` 時沿用 ownership）；bind-mount 之 attachments/reports 目錄權限已於 docs §6 說明需 chown 給 10001
- [x] 2.3 在 `Dockerfile` 加入 `HEALTHCHECK`（打 `/health`），使映像層級即具健康檢查（不僅依賴 compose）
- [x] 2.4 驗證映像可建置且容器以非 root 啟動、`/health` 通過 — build OK；runtime user `uid=10001(app)`；最終映像無 gcc（`NO_GCC`）；`/health` 回 `{"status":"healthy"}`。另精簡 `.dockerignore`（排除 allure-projects/openspec/.codex/.serena/.opencode 等非執行期目錄），映像 **2.22GB→900MB**，且確認 `prompts/` 等執行期目錄仍在

## 3. 設定可達容器 + bootstrap 併發安全

- [x] 3.1 標準化 `APP_CONFIG_PATH`：讓應用程式讀取此環境變數指定的 `config.yaml`，未設定時回退既有預設值 — `app/config.py` 模組層級 `settings` 載入改讀 `APP_CONFIG_PATH`（與 `app/db_migrations.py:66` 一致）
- [x] 3.2 在 `docker-compose.app.yml` 以掛載方式提供 `config.yaml` — 新增唯讀掛載 `${APP_CONFIG_FILE:-./config.yaml}:/app/config.yaml:ro` + `APP_CONFIG_PATH=/app/config.yaml`；`.dockerignore` 維持排除 config.yaml（不烤進映像）
- [x] 3.3 以 DB advisory lock 包住 `database_init.py` 的 schema 變更，序列化平行啟動下的 Alembic upgrade — `database_init.py` 的 bootstrap 區段以 `app/runtime_locks.bootstrap_lock()` 包住（PG/MySQL advisory lock、SQLite 檔案鎖）。PG/MySQL 鎖連 maintenance DB（保留原帳密，`render_as_string(hide_password=False)`）以支援 target DB 尚未建立時上鎖；已於真實 PostgreSQL 驗證 `bootstrap_lock` 取得/釋放成功
- [x] 3.4 調整 `docker/app-entrypoint.sh`：bootstrap 走加鎖版本，並保留 `SKIP_DATABASE_BOOTSTRAP` 既有開關語意 — entrypoint 仍呼叫 `database_init.py`（鎖已內建於其中），`SKIP_DATABASE_BOOTSTRAP` 語意不變
- [x] 3.5 將 `@app.on_event("startup"/"shutdown")` 遷移為 FastAPI `lifespan`，背景服務啟停收斂於此 — 改為 `lifespan` async context manager（`_run_startup` / `_run_shutdown`），移除 deprecated `on_event`

## 4. 背景服務單一 leader（解開水平擴充）

- [x] 4.1 設計並實作 DB advisory-lock leader election：跨副本恰好一個 leader — `app/runtime_locks.BackgroundLeaderLock`（PG `pg_try_advisory_lock` / MySQL `GET_LOCK(…,0)` / SQLite portalocker 非阻塞檔案鎖）
- [x] 4.2 排程器改為僅 leader 行程 `start()`；非 leader 不啟動 thread/輪詢 — `app/main.py` `_try_become_leader_and_start_background` → `_start_background_services`
- [x] 4.3 automation ticker 改為僅 leader 行程啟動；非 leader 不建立 asyncio task — 同上，automation_background_manager 僅 leader 啟動
- [x] 4.4 處理 leader 失效接手：lock 釋放後另一副本可取得 leadership 並接管 — 非 leader 跑 `_leader_retry_loop`（每 30s try-acquire）；leader 鎖綁定連線/檔案 handle，行程結束自動釋放，scheduler `initialize(recover_running=True)` 回收殘留狀態
- [x] 4.5 移除 `WEB_CONCURRENCY=1` 的硬性限制與 entrypoint 警告，更新 README — entrypoint 移除警告並於 `WEB_CONCURRENCY>1` 時加 `--workers`；README env 表與 docs §6 同步更新

## 5. 測試與驗證

- [x] 5.1 測試：缺 `JWT_SECRET_KEY`（`enable_auth=true`）時啟動快速失敗；有設定時正常啟動 — [`app/testsuite/test_container_deployment_p0.py`](app/testsuite/test_container_deployment_p0.py)
- [x] 5.2 測試：有 provider 資料但缺 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 時啟動快速失敗 — [`test_container_deployment_p1.py`](app/testsuite/test_container_deployment_p1.py)`::test_provider_encryption_key_required_when_providers_exist`
- [x] 5.3 測試／驗證：容器重建後金鑰持久化（私鑰指紋不變），舊公鑰加密的 payload 仍可解密 — [`test_container_deployment_p0.py`](app/testsuite/test_container_deployment_p0.py) 驗證 `RSA_KEY_DIR` 覆寫後重新載入公鑰指紋不變（同一 keypair 即保證舊 payload 可解密）
- [x] 5.4 測試：leader election 下多行程僅一個取得 leadership；leader 失效後另一行程接手 — [`test_container_deployment_p1.py`](app/testsuite/test_container_deployment_p1.py)`::test_leader_lock_is_exclusive_across_processes`（跨子行程互斥 + 釋放後可接手）。另實環境驗證：真實 PostgreSQL `pg_try_advisory_lock` 互斥（A=True / B=False / 釋放後可再取得）；真實 **2-worker 容器**（`WEB_CONCURRENCY=2`）log 顯示 leader=1 / non-leader=1，且僅 leader 啟動排程器
- [x] 5.5 測試：bootstrap advisory lock 下平行啟動不會雙重 migration — [`test_container_deployment_p1.py`](app/testsuite/test_container_deployment_p1.py)`::test_bootstrap_lock_serializes_across_processes`（兩子行程 critical section 不交錯）
- [x] 5.6 驗證：`docker-compose.app.yml` 不含任何寫死本機路徑、且 `config.yaml` 經掛載提供時可正常起服務並套用設定 — Docker 實測：`rg /Users docker-compose.app.yml` 無結果；以 `-v config.yaml:/app/config.yaml:ro -e APP_CONFIG_PATH=/app/config.yaml` 啟動容器，`/health` 通過且容器內 `get_settings().auth.jwt_expire_days == 13`（確認讀到掛載設定）
- [x] 5.7 執行 `pytest app/testsuite -q` 相關測試通過 — 全套 **539 passed / 6 failed / 18 skipped**；6 個 failed 已以 `git stash` 對照 baseline 確認**全為既有失敗**（與本 change 無關：guardrails 為 `scripts/*` 既有 commit/rollback 違規、qa-ai-helper 設定與 helper-AI analytics/template 屬其他變更範圍、qdrant 設定為既有 test-ordering flakiness），本 change 未新增任何失敗或 guardrail 違規（`app/runtime_locks.py` 未被 guardrail 標記）
