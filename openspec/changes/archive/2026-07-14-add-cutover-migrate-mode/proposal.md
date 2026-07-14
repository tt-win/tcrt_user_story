# Add Cutover Migrate Mode

## Why

從 SQLite 轉移到 MySQL/PostgreSQL 目前需要操作者手動串五個步驟（起目標 DB → 對目標跑 `database_init.py` 建表 → 逐庫執行 `scripts/db_cross_migrate.py` → `--verify-target all` 驗證 → 改 app 環境變數），步驟間的環境變數切換極易出錯，且既有 cutover workflow runner（`scripts/run_db_cutover_workflow.py`）只驗證環境、不執行資料搬移。要達成「無痛轉移到指定 MySQL server」，需要把整段流程收斂為單一指令並附帶逐表驗證。

## What Changes

- `scripts/run_db_cutover_workflow.py`（實作在 `app/db_cutover_workflow.py`）新增 `--mode migrate`：在既有 preflight / guardrails 之後，依序執行「目標 schema bootstrap → 三庫資料搬移 → 逐表 row count 驗證 → `--verify-target all` → 應用健康檢查」，全部成功才回報 success。
- 目標連線來源二擇一：`--target-env-file <path>`（指向真實 MySQL/PostgreSQL server 的 env 檔）優先；未提供且帶 `--manage-services` 時退回既有 disposable compose 目標（演練用）。
- 來源連線預設沿用目前 app 的 env/config 解析（`resolve_main/audit/usm_database_url`），可用 `--source-env-file` 覆寫；來源一律唯讀，不被修改。
- 安全防線：搬移前偵測目標資料庫是否已含業務資料，非空目標必須帶 `--force-reset-target` 才會清空重灌，否則中止。
- `scripts/db_cross_migrate.py` 增加搬移後逐表 row count 覆核（source vs target），寫入 JSON summary；migrate 模式據此判定成敗。
- summary.json / summary.md 新增 `migration` 區段（每庫每表搬移列數、覆核結果、耗時）與 `env_summary` 區段（搬移完成後 app 應設定的四組 URL，密碼遮蔽），供操作者直接切換。
- `docs/database-cutover-readiness.md` 補「一鍵搬移」runbook 段落，README 的 `db_cross_migrate` 章節補 migrate 模式入口。

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `database-cutover-readiness`: 新增需求——支援的目標資料庫 SHALL 有單一指令的端到端搬移 workflow（schema bootstrap、資料搬移、逐表驗證、健康檢查、環境變數摘要），且對非空目標有明確防呆。

## Impact

- **程式碼**：`app/db_cutover_workflow.py`（新 mode、target/source env 解析、非空目標偵測、migration 步驟編排、summary 擴充）、`scripts/db_cross_migrate.py`（row count 覆核）、`scripts/run_db_cutover_workflow.py`（不變，僅轉呼叫）。
- **相依**：無新套件；資料搬移沿用既有 `db_cross_migrate.py` 的 sync SQLAlchemy 路徑。
- **Migration / rollback / compatibility**：不新增 Alembic revision。搬移對來源唯讀；對目標的破壞性動作（清空重灌）僅在 `--force-reset-target` 明示時發生。中途失敗的回復方式＝目標庫重跑（來源不受影響），寫入 runbook。既有 preflight/smoke/rehearsal 模式行為不變。
- **測試**：`app/testsuite/test_db_cutover_workflow.py` 擴充 migrate 模式（SQLite→SQLite 端到端）；`test_db_cross_migrate_script.py` 擴充 row count 覆核欄位斷言。
