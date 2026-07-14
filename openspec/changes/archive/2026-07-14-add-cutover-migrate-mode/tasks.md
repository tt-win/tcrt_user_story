# Tasks — add-cutover-migrate-mode

實作前請先讀 `design.md`（D1–D7）與 `app/db_cutover_workflow.py:298-403`（`run_cutover_workflow`）、`:405-446`（`parse_args`）、`scripts/db_cross_migrate.py:1037-1131`（`run_job`）。

## 1. db_cross_migrate row count 覆核（design D5）

- [x] 1.1 `scripts/db_cross_migrate.py` `run_job()`：資料寫入完成後（`with source_engine.connect() ... target_engine.begin()` 區塊之後、`summary["status"]="completed"` 之前），對 `ordered_tables` 每張表在兩側各執行 `select(func.count()).select_from(table)`，寫入 `summary["row_count_verification"]`（欄位：`table`/`source_rows`/`target_rows`/`matches`）與 `summary["row_counts_match"]`。dry-run 不產生此區段。
- [x] 1.2 `app/testsuite/test_db_cross_migrate_script.py` 擴充：既有 SQLite→SQLite 案例斷言新欄位存在且 `row_counts_match=True`；另加一案例在 copy 後手動刪除 target 一列再呼叫覆核邏輯（或以 monkeypatch 使計數不一致）驗證 `matches=False` 傳播到 `row_counts_match=False` 且 exit code 仍為 0。

## 2. CLI 與連線解析（design D1/D7）

- [x] 2.1 `parse_args()` 新增：`--mode` choices 加入 `migrate`；`--target-env-file`、`--source-env-file`、`--force-reset-target`、`--migrate-disable-constraints` 四參數（help 文字明載 `--force-reset-target` 會清空目標三庫全部業務資料）。
- [x] 2.2 新函式 `parse_env_file(path: Path) -> dict[str, str]`：逐行解析 `KEY=VALUE`（跳過空行/`#` 開頭，值 strip 首尾單雙引號），不引入新相依。
- [x] 2.3 新函式 `resolve_migrate_endpoints(args, target) -> MigrateEndpoints`（dataclass：`source: dict[str,str]`、`target: dict[str,str]`，鍵為四個 URL 環境變數名）：目標依 D1 優先序解析（env-file → manage-services 的 disposable → 錯誤）；來源預設呼叫 `app.db_migrations.resolve_main_database_url/resolve_audit_database_url/resolve_usm_database_url`（SYNC 鍵由 main URL 經 `normalize_sync_database_url` 產生），`--source-env-file` 提供時改用檔內值。缺鍵錯誤訊息需列出缺少的鍵名。
- [x] 2.4 同庫防呆：對 main/audit/usm 逐一以 `make_url()` 比對 source vs target 的 (backend, host, port, database)（SQLite 比對 `Path(database).resolve()`），相同即 raise 明確錯誤。
- [x] 2.5 `--baseline-summary` 與 `--mode migrate` 併用 → 錯誤退出（argparse 檢查或 main() 內檢查皆可，訊息指明僅 rehearsal 適用）。

## 3. migrate 模式編排（design D2/D3/D4/D6）

- [x] 3.1 `run_cutover_workflow()` 增加 `mode == "migrate"` 分支，步驟順序依 design D2；沿用既有 `_run_compose_up`/`_run_guardrails`/`_run_database_init_command`/`_run_health_check`/`_finalize_summary` 慣例，每步失敗短路。
- [x] 3.2 非空目標偵測 `detect_non_empty_targets(endpoints) -> dict[str, list[dict]]`：在 bootstrap 之前執行，依 D3 規則（reflect 排除 `alembic_version`/`migration_history`，任表 COUNT>0 即非空；database 不存在視為空——捕捉連線/不存在例外並視為空）。非空且無 `--force-reset-target` → summary 記錄 `non_empty_tables`（最多 20 筆）後失敗返回。
- [x] 3.3 搬移步驟 `_run_cross_migrate(job_name, source_url, target_url, log_path, disable_constraints) -> CommandResult`：subprocess 執行 `uv run python scripts/db_cross_migrate.py --source-url ... --target-url ... --reset-target --json --quiet`（帶 `--disable-constraints` 若旗標開啟）；URL 先經 `normalize_sync_database_url`；三庫依 main→audit→usm 執行，log 各自落檔 `logs/migrate-{main,audit,usm}.log`；寫入 summary 前以 `redact_url()` 遮蔽 job summary 內的 `source_url`/`target_url`。
- [x] 3.4 覆核判定：任一庫 JSON 的 `row_counts_match` 為 False 或子行程非零 → 該步驟失敗短路。
- [x] 3.5 summary 擴充：`migration` 區段（三庫 job summaries、整體 `row_counts_match`、`duration_seconds`）與 `env_summary` 區段（目標四鍵、`redact_url` 遮蔽）；`render_markdown_summary()` 加 `## Migration`（每庫表數/總列數/覆核結果）與 `## Env Summary` 段落，後者註明明文密碼請取自 target-env-file。
- [x] 3.6 健康檢查沿用 `_run_health_check`，環境為目標 env（`build_runtime_environment` 以 endpoints.target 覆蓋四鍵）。

## 4. 測試

- [x] 4.1 `app/testsuite/test_db_cutover_workflow.py` 新增 migrate 模式端到端（SQLite 來源 → run-dir SQLite 目標）：先以既有 fixture 建立含資料的來源三庫 → 執行 migrate → 斷言 success、目標表列數等於來源、summary 含 `migration.row_counts_match=True` 與 `env_summary` 四鍵、來源檔案 mtime/內容未變。
- [x] 4.2 防呆測試：(a) 目標=來源同庫 → 失敗且訊息明確；(b) 非空目標無 `--force-reset-target` → 在 bootstrap 前中止、summary 含 `non_empty_tables`；(c) 帶 `--force-reset-target` → 成功且目標舊資料被取代；(d) `--baseline-summary` 併用 → 錯誤。
- [x] 4.3 `parse_env_file` 單元測試：註解/空行/引號/缺鍵。

## 5. 文件

- [x] 5.1 `docs/database-cutover-readiness.md` 新增「§ 一鍵搬移（migrate 模式）」：指令範例（真實 server 用 `--target-env-file`、演練用 `--manage-services`）、前提（停止 app 寫入、目標帳號權限：CREATE/ALTER/DROP/REFERENCES）、失敗回復＝目標重跑而來源不動、搬移後續步驟（更新 app env → 重啟 → 抽樣驗證 → Qdrant 重建索引提醒）。
- [x] 5.2 `README.md` 的 `scripts/db_cross_migrate.py` 章節補 migrate 模式入口說明與 `row_count_verification` 欄位。

## 6. 驗證

- [x] 6.1 `uv run pytest app/testsuite/test_db_cutover_workflow.py app/testsuite/test_db_cross_migrate_script.py -q` 全綠。
- [x] 6.2 `uv run ruff check app scripts database_init.py` 通過。
- [x] 6.3 手動煙測：`--mode migrate --target mysql --manage-services`（disposable compose）跑通一次，summary 與 logs 留存於 change 目錄下 `verification.md` 摘錄。
- [x] 6.4 `openspec validate add-cutover-migrate-mode --strict` 通過。
