# Database Access Inventory

本文件是 `complete-db-access-abstraction` change 的基線盤點，目的是把 direct DB access 的歸屬、允許例外與第一波熱區固定下來，避免後續重構仍靠臨時搜尋。

## Ownership Baseline

- `main`: 由 `app/database.py` 提供 async engine、`SessionLocal`、`get_async_session`、`get_db`、`run_sync`
- `audit`: 由 `app/audit/database.py` 提供 `audit_db_manager` 與 `get_audit_session`
- `usm`: 由 `app/models/user_story_map_db.py` 提供 `usm_engine`、`USMAsyncSessionLocal`、`get_usm_db`

新的受管 boundary 入口定義於 `app/db_access/`。

## Allowed Exceptions

以下路徑目前被視為允許直接碰資料庫的基礎設施或支援層：

- `app/database.py`
- `app/audit/database.py`
- `app/models/user_story_map_db.py`
- `app/db_access/`
- `app/db_migrations.py`
- `database_init.py`
- `app/testsuite/`

對應的機械化 allowlist 在 `config/db_access_policy.yaml`。

## First-Wave Hotspots

### Main DB

- `app/api/test_cases.py`: route 內的 `run_sync(..._create/_update/_delete)` 與 `sync_db.commit()` 仍直接持有 mutation ownership
- `app/api/test_run_items.py`: route 內多段 sync closure 直接提交
- `app/api/test_run_sets.py`: route 在 `run_sync` 內提交，再於 handler 做額外狀態 recalculation/commit
- `app/api/test_run_configs.py`: route 內同時出現 commit、rollback 與 set status 協調
- `app/api/adhoc.py`: main DB mutation 與 raw SQL / transaction 細節仍在 handler
- `app/services/jira_testcase_helper_service.py`: 大量 sync write path 與 helper table raw SQL
- `app/services/test_case_set_service.py`: service 直接擁有 commit
- `app/services/user_service.py`: service 自行開 session 並提交

### Audit DB

- `app/api/team_statistics.py`: reporting query 同時碰 `main` 與 `audit`，且自行 `SessionLocal()`
- `app/api/admin.py`: dialect-sensitive 診斷邏輯與 direct session factory
- `app/auth/session_service.py`: service 直接持有 session lifecycle 與 commit

### USM / Cross-DB

- `app/api/user_story_maps.py`: handler 內直接管理 `usm_db`，並混入 `main_db` 協調
- `app/api/user_story_maps.py`: around line `2200` 仍有 `run_sync(main_db, _load_nodes)` 讀 `UserStoryMapNodeDB` 的跨庫邊界疑點

### Tooling

- `scripts/etl_to_qdrant.py`
- `ai/etl_all_teams.py`
- `ai/etl_retry_teams.py`
- `ai/test_llm_context.py`

以上工具仍直接使用 `SessionLocal()`，尚未切到 target-aware boundary。

## Refactor Rule Of Thumb

```text
Allowed:
  infra/provider -> boundary -> orchestrator -> route/service

Not allowed:
  route/service -> SessionLocal()
  route/service -> commit()/rollback()
  route/service -> execute(text(...)) for shared runtime path
  handler mixing main + audit/usm sessions directly
```

後續 `ast-grep` 守門與 migration/smoke 驗證都以這份盤點為基線。
