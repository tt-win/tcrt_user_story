## 1. P0: Portable enum value storage（主庫 + audit）

- [x] 1.1 盤點主庫 `app/models/database_models.py` 15 個裸 `Enum(PyEnum)` 欄位與 `app/audit/database.py` 3 個 `SQLEnum` 欄位，逐一記錄目前的儲存表示法（成員名稱）與對應的 `.value`，確認是否存在 name 與 value 不一致的 enum。
- [x] 1.2 將上述 enum 欄位改為可攜寫法（停用原生具名型別、改以 enum 值字串儲存），對齊 automation enum 既有的 `values_callable` 模式；保持 Python 屬性型別仍為 PyEnum。**自我修正**：初次實作只加了 `values_callable`（修正 name/value 儲存不一致），漏了「停用原生具名型別」（`native_enum=False`）本身——這代表 MySQL 仍會建原生 `ENUM(...)`、PostgreSQL 仍會建 named TYPE，新增 enum 值仍需要 `MODIFY COLUMN` / `ALTER TYPE`，不滿足 design.md 與任務 6.4 的可攜性目標。已在任務 6 驗證階段發現並補上：17 個主庫欄位＋3 個 audit 欄位（含 `action_type`，雖資料不變但型別仍需轉換）皆已加上 `native_enum=False`。
- [x] 1.3 撰寫主庫資料遷移 revision：將既有列以「名稱」儲存的 enum 值就地轉為「值」表示法；對 name 與 value 相同者為 no-op，對不同者建立明確的逐值映射。`migrate_enum_storage()` 新增 `target_native` 參數（預設 `False`）：upgrade 傳 `False`（轉換完成後留在可攜 VARCHAR/TEXT，不收斂回原生型別），downgrade 傳 `True`（轉換完成後收斂回原生 ENUM/named TYPE，還原 migration 執行前狀態）。
- [x] 1.4 撰寫 audit DB 對應的資料遷移 revision，套用相同的名稱→值轉換。新增 `action_type`（ActionType）群組（identity mapping，資料為 no-op，但型別轉換為必要）。
- [x] 1.5 為兩支資料遷移 revision 補上可逆的 `downgrade`（值→名稱）。downgrade 呼叫 `target_native=True`，正確收斂回原生具名型別。
- [x] 1.6 在 SQLite 上產生／套用 migration，確認 model 與 migration 同步、drift 檢查通過。SQLite 本來就無原生 enum 型別，`native_enum=False` 對 SQLite 渲染出的 DDL 無影響（維持 VARCHAR，無 CHECK 約束）。
- [x] 1.7 在 MySQL 8 與 PostgreSQL 16 上套用同一 head，確認不再要求原生 `ENUM` / named type，且資料值轉換正確。以隔離 schema 方式驗證（stamp 到前一版本→只執行這一步 upgrade→驗證資料與型別→downgrade→驗證還原）；主庫既有 migration chain（`b9d4e7a3c0f2`、`e7c3a9d1f2b4`）另有與本變更無關的 MySQL/PostgreSQL 相容性問題導致無法從空庫完整 bootstrap，已另開背景任務追蹤，細節見 `verification.md`。實測確認：upgrade 後 MySQL 欄位為 `varchar(64)`、PostgreSQL 欄位為 `text`（原具名 TYPE 已 drop、未重建），且皆能直接寫入從未宣告過的全新字串值（零 DDL）；downgrade 後正確收斂回 `ENUM(...)` / 重建 named TYPE。

## 2. P0: Symmetric large-text type & retire MySQL-only widen path

- [x] 2.1 確認三套 model（`database_models.py`、`audit/database.py`、`user_story_map_db.py`）的大型文字欄位皆以「一次宣告、依方言變體」的型別來源（SQLite/PG 為 `TEXT`、MySQL 為 `MEDIUMTEXT`）提供，無遺漏欄位。三者皆已 `from app.db_types import MediumText as Text`，本項無需變更。
- [x] 2.2 將既有以 `dialect.name == 'mysql'` 設限的 text 加寬 migration 標記為 legacy-only，並改寫為由 model 型別來源統一決定（不再於各引擎留下不對稱的物理欄位歷史）。
- [x] 2.3 退役 `database_init.py` 的 MySQL-only 開機自檢 gate（`verify_mysql_mediumtext_defaults`），改以引擎對稱的 drift 驗證涵蓋 large-text 一致性。改為 `verify_large_text_columns()`：非 MySQL 恆為 no-op，MySQL 上僅檢查 model 端宣告為 `MediumText` 的欄位，不做全表 `compare_metadata` 比對（會誤觸發既有、與本項無關的 schema drift，詳見 `verification.md`）。
- [x] 2.4 移除／調整僅針對該 gate 的測試，補上引擎對稱的 large-text 驗證測試。

## 3. P1: Enforce logically-required constraints in schema

- [x] 3.1 撰寫回填 + NOT NULL 強制 migration：在三引擎上把 `test_cases.test_case_set_id` 的 NULL 依既有派生規則（由 section 反推 set；無 section 則用 team 預設 set）回填，並確保欄位為 NOT NULL；對已滿足者為 no-op。見 `alembic/versions/9cd6393a4da6_backfill_test_case_set_id_and_enforce_.py`；無法決定歸屬時中止遷移（不靜默猜測），由 Change A 的備份/回退機制接手。
- [x] 3.2 將 `scripts/db_cross_migrate.py` 中 `test_case_set_id` 的臨時修補（`_repair_test_cases_payload`）改為僅在 schema 已保證時跳過，或移除其作為唯一保證的角色。已完全移除該函式與 `_build_test_case_repair_context`；正確性改由 3.1 的 migration 在 schema 層保證。
- [x] 3.3 以 schema 層一致定義 username 的大小寫不敏感唯一性，使 SQLite 與 MySQL/PG 行為一致。見 `alembic/versions/f5f2d075fd93_enforce_case_insensitive_username_.py`：以 `lower(username)` 建 unique index 取代原本 `unique=True`；MySQL 8.0.13+ 需要 functional key part 的雙層括號語法，已用 `sa.func.lower(...)` 讓 SQLAlchemy 依 dialect 自動產生正確 DDL 並在三引擎個別驗證。既有僅大小寫不同的重複 username 會讓遷移中止並列出衝突 id（不自動合併/刪除使用者列——這是需要人工判斷的業務決策）。
- [x] 3.4 移除 `scripts/db_cross_migrate.py` 中因大小寫差異而存在的 username 去重（`_dedup_users_payload_case_insensitive`）與其連帶的孤兒過濾（`_filter_orphan_user_refs`）對「正確性」的依賴。已完全移除兩個函式與 `_TABLES_WITH_USER_FK`；正確性改由 3.3 的 migration 在 schema 層保證。
- [x] 3.5 為兩支 schema 強制變更補上可逆 `downgrade`（NOT NULL 降回 nullable、唯一性定義還原）。兩支 migration 的 downgrade 皆已在 SQLite/MySQL/PostgreSQL 上驗證；username migration 因從不刪除/合併資料（衝突時直接中止），downgrade 不需處理資料還原問題。

## 4. P1: PostgreSQL sequence integrity in cross-migrate

- [x] 4.1 在 `scripts/db_cross_migrate.py` 以顯式 PK 載入完成後，針對 PostgreSQL 目標逐表將 identity / serial sequence 重置為 `max(pk) + 1`（或等效）。見 `reset_postgresql_sequences()`：用 `pg_get_serial_sequence` 找出每個整數 PK 欄位背後的 sequence，`setval` 到目前實際最大值（空表則重置為 1、`is_called=false`，避免略過 id=1）。
- [x] 4.2 僅對 PostgreSQL 目標執行 sequence 重置；SQLite / MySQL 目標不受影響。`run_job` 只在 `target_engine.dialect.name == "postgresql"` 時呼叫。
- [x] 4.3 新增測試：PG 搬遷後對受影響表插入新列不會與既有 PK 撞鍵。見 `test_db_cross_migrate_script.py::test_run_job_resets_postgresql_sequences_after_explicit_pk_copy`（真實 PostgreSQL，env-gated）+ 手動驗證空表邊界情況。

## 5. P2: De-duplicate copied infrastructure

- [x] 5.1 將 4 份 SQLite PRAGMA listener（`app/database.py` 兩處、`app/models/user_story_map_db.py`、`app/audit/database.py`）抽為單一共用 helper 並改為呼叫之。已抽為 `app/db_sqlite_pragma.py::apply_sqlite_pragma`。
- [x] 5.2 將 3 份近乎相同的 Alembic `env.py`（`alembic/`、`alembic_audit/`、`alembic_usm/`）的共用邏輯抽為共用模組，各 `env.py` 僅保留目標差異設定。已抽為 `app/alembic_env_shared.py::run_env`，三份 `env.py` 皆改為呼叫此函式的薄封裝。
- [x] 5.3 確認去重後三套 migration 與 PRAGMA 行為與去重前一致（無回歸）。已對三個 target 個別執行真實 Alembic upgrade/downgrade 驗證行為一致。

## 6. Cross-engine verification

- [x] 6.1 建立／更新跨引擎 schema 比對：對 SQLite / MySQL 8 / PostgreSQL 16 套用同一 head 後，比對邏輯 schema（表、欄位、型別語意、約束、唯一性）一致。**2026-07-14 更新**：擋住此項的既有 migration chain 問題（`b9d4e7a3c0f2`/`e7c3a9d1f2b4`/`c3e7a1f9d2b4`）已在同分支修復（見下方「主庫 migration chain 可攜性修復」），已可從空庫對三引擎完整跑「同一 head」（`f84bbca9a911`）。三引擎皆 58 個資料表（不含 `alembic_version`），欄位集合與 nullable 完全一致，零 mismatch；索引/唯一約束比對僅有的差異是 MySQL 對 FK 欄位自動建立的輔助索引（SQLite/PostgreSQL 不需要，屬既知、無害的物理變體，不視為 drift）與既有已記錄的 expression-index reflection 限制（`uq_users_username_lower`）。
- [x] 6.2 執行跨引擎搬遷 rehearsal（SQLite → MySQL、SQLite → PostgreSQL），確認不再依賴腳本端臨時修補即達成一致；輸出一致性摘要。以真實 disposable MySQL 8.4／PostgreSQL 16 執行：完整 bootstrap 一個 SQLite 主庫（含本 change 所有 migration）、seed 真實資料，透過 `scripts/db_cross_migrate.py` 搬到 MySQL（`--create-target-schema`，排除 `automation_scripts` 及其 3 個 FK 依賴表——三者皆因與本變更無關的既有 model/migration 問題無法建表，已追蹤於背景任務）與 PostgreSQL（手動建對齊 schema，繞過 `--create-target-schema` 對 SQLite reflect `DATETIME` 型別在 PG 上無法轉換的既有 SQLAlchemy 限制）。結果：60+ 個表 `row_counts_match=true`；enum 欄位皆為可攜值（如 `role='admin'`、`status='active'`）；`test_case_set_id` 正確回填且 NOT NULL；PostgreSQL sequence 正確重置（新增列不撞鍵，見任務 4）；case-insensitive username 唯一性在兩引擎皆正確擋下大小寫變體重複。額外發現並記錄一個 `--create-target-schema` 既有限制：SQLAlchemy reflect 無法還原 expression-based index（如 `uq_users_username_lower`），故透過該 shortcut 建的 target 不會有此保護；**不影響**正式 cutover-migrate 流程（`app/db_cutover_workflow.py` 一律先用真正的 Alembic migration 建 target schema），已在 `scripts/db_cross_migrate.py` 加註解說明。**2026-07-14 更新**：既有 migration chain 問題修復後，另外完整驗證了 `database_init.py`（真正的 production bootstrap 入口，非僅 raw alembic）對全新 MySQL 8.4 與 PostgreSQL 16 從空庫 bootstrap 到 head 皆成功（含 `verify_large_text_columns` 等驗證 gate），過程中新發現並修正一批（10 個）先前從未被驗證觸及的欄位缺少 MEDIUMTEXT 提升問題（見下方新增 migration）。
- [x] 6.3 執行 `pytest app/testsuite -q` 相關測試全部通過。全套 762 passed, 6 failed（皆為與本 change 無關的既有失敗：`test_db_access_guardrails_have_no_unexpected_violations`、`test_settings_loader_expands_qa_ai_helper_model_placeholders`、`test_settings_warns_when_container_runtime_uses_localhost_services`、`test_helper_ai_analytics_returns_gone_for_admin`、`test_helper_ai_analytics_still_requires_admin`、`test_team_statistics_template_no_longer_exposes_helper_tab_or_sections`——與 Change A/C 完成時確認的既有失敗集合完全相同，數量與名稱皆無變化，證實本 change 未引入任何回歸）, 29 skipped（皆為 env-gated 的真實 MySQL/PostgreSQL 整合測試，未設定對應環境變數時的預期 skip）。
- [x] 6.4 確認 enum 新增值的流程：在三引擎上新增一個 enum 值不再需要 `ALTER TYPE` / `MODIFY COLUMN` 即可讀寫（可攜表示法驗證）。任務 1.2 的 `native_enum=False` 修正是此項成立的關鍵；已在 SQLite（無 CHECK 約束）、真實 MySQL（`varchar(64)` 直接寫入全新字串值）、真實 PostgreSQL（`text` 直接寫入全新字串值，原 named TYPE 已 drop）上實測確認，並固化為 `test_db_migrations_enum_support.py` 的自動化測試。

## 7. 附加修復（2026-07-14，非原始 26 tasks 之一，但直接解鎖任務 6.1/6.2 的完整驗證）

原本任務 6.1/6.2 因主庫既有 migration chain 的 MySQL/PostgreSQL 相容性問題（獨立 spawn_task 追蹤，非本 change 原始範圍）只能做「隔離 schema」驗證。使用者核准後於同分支原地修復以下已 merge 的 migration（皆為「SQLite 路徑維持不變、MySQL/PostgreSQL 路徑從未成功執行過故無回溯相容性負擔」的修法）：

- [x] 7.1 `b9d4e7a3c0f2`（split_automation_provider_scope）：MySQL/PostgreSQL 改用 portable 的 `drop_constraint`+`create_foreign_key` 直接 retarget FK，取代 SQLite 專用的整表重建 raw SQL（該 raw SQL 對 MySQL 語法錯誤、對 PostgreSQL 用不存在的 `DATETIME` 型別）。SQLite 路徑逐欄逐字元核對維持不變（透過真實 schema dump diff 驗證，僅有的差異是 Python 原始碼縮排導致的字串內部空白，語意 100% 相同）。
- [x] 7.2 `e7c3a9d1f2b4`（add_ref_repo_for_multi_repo_storage）：`uq_automation_script_ref` 五欄複合唯一鍵在 MySQL utf8mb4 下超過 3072-byte 上限。MySQL/PostgreSQL 改用固定長度 `ref_key_hash`（SHA-256，`app/models/database_models.py::_automation_script_ref_key_hash`，由 `before_insert` event listener 維護）承載唯一性，另建 `(team_id, provider_id, ref_repo, ref_branch)` 一般索引維持既有批次查詢效能。SQLite 路徑维持原本 5 欄複合唯一鍵不變；新增 `f84bbca9a911` 讓既有 SQLite 資料庫（如已跑過舊版 `e7c3a9d1f2b4` 者）收斂到同一 `ref_key_hash` 機制。
- [x] 7.3 `c3e7a1f9d2b4`（drop_automation_smart_scan_runs）：移除多餘且在 MySQL 上會出錯的逐一 `DROP INDEX`（`DROP TABLE` 本身就會連同索引一起清除，三引擎皆然）。
- [x] 7.4 新增 `a371471a3008`：`database_init.py` 的 `verify_large_text_columns` gate 在全新 MySQL bootstrap 首次真正被驗證到時，抓到 10 個先前從未被觸及、遺漏 MEDIUMTEXT 提升的欄位（`test_run_sets.automation_suite_ids_json`、`system_automation_providers.config_json`/`credentials_encrypted` 等），比照既有 `8d3c1b4a6f20` legacy widen migration 的模式加一支新的 catch-up migration（採硬編碼欄位清單而非泛用掃描，確保 downgrade 只還原這批欄位、不誤傷更早期 migration 已提升的欄位）。
- [x] 7.5 驗證：`database_init.py`（真正的 production bootstrap 入口）對全新 MySQL 8.4 與 PostgreSQL 16 從空庫到 head 皆完整成功（含所有驗證 gate）；SQLite 全鏈路 upgrade/downgrade/re-upgrade 迴歸確認無變化；全套 `pytest app/testsuite -q` 762 passed（與既有 baseline 相同的 6 個既有失敗，零新增回歸——過程中一度抓到並修正真實回歸：`AutomationScript` 的 `before_insert` listener 未處理 `ref_repo` 為 `None`（測試 fixture 依賴 `server_default=""`）的情況）；`b9d4e7a3c0f2`/`e7c3a9d1f2b4` 的 downgrade 亦於真實 MySQL 上個別驗證正確（isolated bind-Operations 技術，避開另一支無關 migration `a1b2c3d4e5f6` 既有的 downgrade bug，已另開 spawn_task 追蹤，不屬本次範圍）。
- [x] 7.6 補上任務 6.1/6.2 原本因上述問題無法完成的完整版驗證：三引擎從空庫套用同一 head 後，58 個資料表、欄位集合、nullable 完全一致（零 mismatch）；索引/唯一約束的僅有差異是 MySQL 對 FK 欄位自動建立的輔助索引（無害物理變體）與既有已記錄的 expression-index reflection 限制。
