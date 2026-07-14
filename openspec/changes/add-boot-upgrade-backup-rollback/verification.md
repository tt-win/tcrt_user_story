# Verification — add-boot-upgrade-backup-rollback

## 自動化測試

```
uv run pytest app/testsuite/test_bootstrap_pending_detection.py app/testsuite/test_db_backup.py \
  app/testsuite/test_bootstrap_backup_rollback.py app/testsuite/test_database_init.py -q
# 32 passed

uv run pytest app/testsuite -q
# 740 passed, 20 skipped, 6 failed — 6 個失敗全數確認為既有 baseline 問題，與本次變更無關（見下）

uv run ruff check app scripts database_init.py
# 新增/修改的 8 個檔案：All checks passed!（全 repo 既有 473 個錯誤不在本次變更範圍）
```

### 全套測試的 6 個既有失敗（已逐一確認與本次變更無關）

用 `git worktree add` 建立乾淨 checkout（不含本機 gitignored `config.yaml`/`.env`）與 `git stash`
（暫存本次追蹤檔案改動、保留本機 config.yaml）雙重交叉驗證：

| 失敗測試 | 根因 | 確認方式 |
|---|---|---|
| `test_db_access_guardrails_have_no_unexpected_violations` | `app/services/automation/environment_service.py:198` 既有直接 `rollback()` 違規，與本次改動的檔案無關 | 乾淨 worktree 同樣失敗 |
| `test_settings_loader_expands_qa_ai_helper_model_placeholders` | 本機真實 `config.yaml` 的 `ai.qa_ai_helper.models.seed.model` 設定值透過 `Settings.from_env_and_file` 洩漏進本應只讀 tmp_path 設定檔的測試 | `git stash` 暫存本次改動、保留本機 config.yaml 後仍失敗；乾淨 worktree（無 config.yaml）則通過 |
| `test_settings_warns_when_container_runtime_uses_localhost_services` | 同一根因（本機 config.yaml 洩漏），單獨執行時通過，僅在特定測試順序下與其他測試互相干擾而顯現 | 單獨執行於本分支：通過 |
| `test_helper_ai_analytics_returns_gone_for_admin` | 既有 team statistics helper AI 端點行為，與本次改動的檔案無關 | 乾淨 worktree 同樣失敗 |
| `test_helper_ai_analytics_still_requires_admin` | 同上 | 乾淨 worktree 同樣失敗 |
| `test_team_statistics_template_no_longer_exposes_helper_tab_or_sections` | 既有前端模板斷言，與本次改動的檔案無關 | 乾淨 worktree 同樣失敗 |

## 真實 MySQL 8.4 手動煙測（docker-compose.mysql.yml，disposable）

環境：本機新裝 Homebrew `mysql-client`（9.7.1）供 `mysqldump`/`mysql` 使用。

- **Preflight**：`database_init.py --preflight` 對 main/audit/usm 三庫全數通過。
- **Fresh bootstrap（`tcrt` 受限帳號）**：於 `bootstrap_lock()` 進入點失敗——
  `Access denied for user 'tcrt'@'%' to database 'mysql'`。**此為既有問題**（`app/runtime_locks.py`
  的 MySQL advisory lock 連線 maintenance DB 時未指定 database，實務上會嘗試存取 `mysql` 系統庫），
  與本次變更的程式碼無關；已列入 Docker 化風險評估的 P1 項目（`bootstrap_lock` 需要 maintenance DB
  存取權限）。改用 `root` 帳號繞過後续可正常驗證本次變更的實際邏輯。
- **Fresh bootstrap（main，`root` 帳號）**：main 的既有 migration `b9d4e7a3c0f2_split_automation_provider_scope.py`
  對 `automation_runs` 索引使用 `DROP INDEX IF EXISTS <name>`（SQLite/PostgreSQL 語法），MySQL 需要
  `DROP INDEX <name> ON <table>`，導致 `(1064, "You have an error in your SQL syntax...")`。
  **此為既有 migration bug，與本次變更無關**——這代表全新 MySQL 部署目前無法透過 Alembic 走完 head，
  已另行回報給使用者，不在本 change 範圍內修正。
- **audit target（`root` 帳號，繞開 main 的既有 bug，直接呼叫 `bootstrap_target()`）**：
  - Fresh 首次 bootstrap 成功，未產生備份（`is_fresh=True` 正確跳過）。
  - 手動把 `alembic_version` 改回 baseline 製造 pending 後重跑：正確產生 1 份
    `.sql.gz` 備份＋`.meta.json`，真正的 Alembic upgrade 成功跑完到 head。
  - 注入失敗的 upgrader＋`BOOTSTRAP_ON_FAILURE=rollback`：**首次執行發現真實 bug**——
    `_handle_bootstrap_failure` 用 `resolve_database_url()`（回傳 async URL）呼叫
    `restore_backup()`，導致 `greenlet_spawn has not been called` 錯誤、回退失敗（exit 9）。
    已修正為 `normalize_sync_database_url(resolve_database_url(...))`（`database_init.py`）。
    修正後重跑：備份/還原/exit code 8 全數正確，`alembic_version` 與資料表清單精確回到
    升版前狀態（與升版前的表清單逐一比對一致）。

## 真實 PostgreSQL 16 手動煙測（docker-compose.postgres.yml，disposable）

環境：本機新裝 Homebrew `postgresql@16`（16.14，版本對齊 target server；首次誤用最新 `libpq`
18.4 的 `pg_dump`/`pg_restore` 對 PG16 還原時出現 `unrecognized configuration parameter
"transaction_timeout"`——**純屬本機測試工具版本落差，非程式邏輯問題**，換裝版本對齊的 client 後即正常，
已於 `docs/docker-app-setup.md` 註記需對齊 client/server 版本）。

- `test_db_backup_server_engines.py`（MySQL＋PostgreSQL 即時 dump/restore round-trip）：2 passed。
- usm target（`tcrt` 帳號，PG 對此帳號為 superuser，無受限問題）：
  - Fresh 首次 bootstrap 成功，未產生備份。
  - Pending＋修正後的 rollback 邏輯：備份（`.pgdump`）＋`DROP SCHEMA public CASCADE`+`CREATE SCHEMA`+
    `pg_restore --no-owner` 還原，exit code 8，`alembic_version` 與資料表清單精確回到升版前狀態。

## 本次發現並回報（非本 change 範圍，未修正）

1. **`app/runtime_locks.py` 的 MySQL bootstrap advisory lock 對受限帳號會 boot fail**（已知 P1，
   本次真實重現）：`tcrt` 這類只有特定 database GRANT 的帳號連 maintenance 連線會被拒絕。
2. **`alembic/versions/b9d4e7a3c0f2_split_automation_provider_scope.py` 對 MySQL 有語法 bug**：
   `DROP INDEX IF EXISTS <name>` 缺少 MySQL 必要的 `ON <table>` 子句，導致全新 MySQL 部署的
   main 資料庫 bootstrap 會直接失敗。**建議另開獨立修正，優先度高於本次 change 涵蓋範圍**（阻擋
   任何全新 MySQL 部署）。

## OpenSpec

```
openspec validate add-boot-upgrade-backup-rollback --strict
# Change 'add-boot-upgrade-backup-rollback' is valid
```
