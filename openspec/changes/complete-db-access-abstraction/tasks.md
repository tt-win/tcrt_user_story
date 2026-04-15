## 1. Baseline And Boundary Setup

- [x] 1.1 盤點 `app/api/`、`app/services/`、`app/auth/`、`scripts/`、`ai/` 的 direct DB access，建立 `main` / `audit` / `usm` 歸屬與允許例外清單 (Inventory direct DB access across runtime/tooling paths and classify ownership plus explicit exceptions for `main` / `audit` / `usm`)
- [x] 1.2 建立 `main`、`audit`、`usm` 的受管 access boundary 骨架，明確定義 session provider、transaction owner 與 caller contract (Create managed access-boundary skeletons for `main`, `audit`, and `usm` with explicit session-provider, transaction-owner, and caller contracts)
- [x] 1.3 建立跨資料庫 orchestration 介面與依賴注入入口，禁止 handler 直接混用多套資料庫 session (Create cross-database orchestration entry points and dependency injection paths so handlers no longer mix multiple database sessions directly)

## 2. Main Database Runtime Refactor

- [x] 2.1 將 `app/api/test_cases.py`、`app/api/test_run_items.py`、`app/api/test_run_sets.py`、`app/api/test_run_configs.py` 的 direct session / commit 流程搬入受管 `main` boundary (Move direct session and commit flows from the main test APIs into the managed `main` boundary)
- [x] 2.2 重構 `app/services/test_case_set_service.py`、`app/services/jira_testcase_helper_service.py` 與相關主庫 service，改走 boundary contract 而非直接 ORM 存取 (Refactor main-database services to consume the boundary contract instead of direct ORM access)
- [x] 2.3 清理 `app/api/adhoc.py` 與其他主庫熱區中的 raw SQL、transaction 與 session ownership，統一到受管 boundary/adapter (Consolidate raw SQL, transaction handling, and session ownership from main-database hotspots into managed boundaries/adapters)

## 3. Auxiliary Databases And Cross-Database Flows

- [x] 3.1 為 `audit` 與 `usm` 建立 target-aware boundary/provider，移除 runtime caller 自行建立 session 的做法 (Create target-aware boundary/providers for `audit` and `usm` and remove ad-hoc session creation from runtime callers)
- [x] 3.2 重構 `app/api/user_story_maps.py` 的 `main` / `usm` 混合流程，將跨庫協調提升到顯式 orchestration layer (Lift mixed `main` / `usm` flows out of `app/api/user_story_maps.py` into an explicit orchestration layer)
- [x] 3.3 重構 `app/auth/session_service.py`、`app/api/users.py`、audit 相關流程，讓 auth/audit 路徑改走受管 boundary 與 transaction 規則 (Refactor auth, user, and audit-related flows to use managed boundaries and centralized transaction rules)

## 4. Reporting, Admin, And Offline Tooling Cleanup

- [x] 4.1 清理 `app/api/team_statistics.py`、`app/api/admin.py` 與其他 reporting/admin 熱區中的 dialect-specific SQL 與診斷邏輯 (Clean up dialect-specific SQL and diagnostics in reporting/admin hotspots such as `team_statistics.py` and `admin.py`)
- [x] 4.2 重構 `app/services/user_service.py`、`app/services/lark_notify_service.py`、`app/services/lark_org_sync_service.py` 等自行開 session 的 service (Refactor services that currently open sessions directly so they use the managed boundary model)
- [x] 4.3 將 `scripts/`、`ai/` 與資料維運工具改為重用 target-aware config 與受管 boundary，而不是依賴 SQLite 檔案路徑或隱式 session factory (Migrate scripts, AI tools, and maintenance utilities to the target-aware managed boundary instead of SQLite file paths or implicit session factories)

## 5. Guardrails And Regression Coverage

- [x] 5.1 建立 `ast-grep` 或等效靜態守門規則，阻擋非受管模組中的 `SessionLocal()`、直接 `commit()`、直接 `execute(text(...))` 與多 DB 混用模式 (Add `ast-grep` or equivalent guardrails to block forbidden direct session, commit, raw SQL, and multi-database patterns outside managed modules)
- [x] 5.2 調整 integration/API 測試 fixture，使 `main`、`audit`、`usm` 的驗證對齊受管 migration 與 target-aware schema setup (Update integration and API test fixtures so `main`, `audit`, and `usm` validation uses managed migration and target-aware schema setup)
- [x] 5.3 補上 boundary、cross-database orchestration、dialect-aware raw SQL 與 session ownership 的回歸測試 (Add regression tests for managed boundaries, cross-database orchestration, dialect-aware raw SQL, and centralized session ownership)

## 6. Cutover Readiness Verification

- [x] 6.1 建立 SQLite / MySQL / PostgreSQL 的 preflight 與 smoke workflow，涵蓋 `main`、`audit`、`usm` 三套資料庫 (Create SQLite, MySQL, and PostgreSQL preflight/smoke workflows covering all three managed databases)
- [x] 6.2 補齊 cutover rehearsal 的一致性摘要輸出、rollback 前提與重新驗證文件/工具 (Add cutover rehearsal summaries, rollback prerequisites, and re-verification guidance in documentation or tooling)
- [x] 6.3 執行 SQLite 回歸、MySQL smoke/rehearsal 與 PostgreSQL smoke/rehearsal，確認新 boundary 與守門規則可支撐無痛切換目標 (Run SQLite regression plus MySQL/PostgreSQL smoke rehearsals to confirm the new boundaries and guardrails support painless database cutover)
