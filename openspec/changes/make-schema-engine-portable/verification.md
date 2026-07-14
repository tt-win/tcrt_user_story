# Verification — make-schema-engine-portable

## 自動化測試

```
uv run pytest app/testsuite -q
# 762 passed, 6 failed, 29 skipped
#
# 6 個失敗皆為與本 change 無關的既有失敗（與 Change A/C 完成時確認的既有失敗集合完全相同，
# 數量與名稱皆無變化，證實本 change 未引入任何回歸）：
#   test_db_access_guardrails.py::test_db_access_guardrails_have_no_unexpected_violations
#   test_qa_ai_helper_models.py::test_settings_loader_expands_qa_ai_helper_model_placeholders
#   test_qdrant_client_service.py::test_settings_warns_when_container_runtime_uses_localhost_services
#   test_team_statistics_helper_ai_api.py::test_helper_ai_analytics_returns_gone_for_admin
#   test_team_statistics_helper_ai_api.py::test_helper_ai_analytics_still_requires_admin
#   test_team_statistics_helper_frontend.py::test_team_statistics_template_no_longer_exposes_helper_tab_or_sections
#
# 29 個 skip 皆為 env-gated 的真實 MySQL/PostgreSQL 整合測試（TCRT_TEST_MYSQL_URL /
# TCRT_TEST_POSTGRES_URL 未設定時的預期 skip）；設定後皆通過，見下方各段落。

uv run ruff check app scripts database_init.py
# All checks passed!

openspec validate make-schema-engine-portable --strict
# Change 'make-schema-engine-portable' is valid
```

新增/修改的測試檔案：`test_db_migrations_enum_support.py`（enum 可攜性，含 MySQL/PostgreSQL
`target_native` 兩方向）、`test_db_migrations_test_case_set_and_username.py`（test_case_set_id
回填 + username 大小寫不敏感唯一性，三引擎）、`test_db_cross_migrate_script.py`（新增 PostgreSQL
sequence reset 端到端測試；移除已失效的 `test_copy_table_data_repairs_missing_test_case_set_with_default_section`）、
`test_database_init.py`（`verify_large_text_columns` 取代 `verify_schema_drift`）。

## 實作中發現並修正的既有 bug（非本次新增功能的迴歸，但會影響本次驗證或正確性）

### 1. `native_enum=False` 遺漏（自我發現並修正，發生在本 change 內，非跨 change 既有 bug）

Task 1 初次實作只把 enum 欄位改成 `values_callable`（修正「儲存 member.name 而非 .value」的
不一致），但漏了 design.md 明確要求的「停用原生具名型別」（`native_enum=False`）。這代表：

- MySQL 仍會建立原生 `ENUM(...)` 欄位。
- PostgreSQL 仍會建立具名 `CREATE TYPE ... AS ENUM` 並讓欄位引用該 type。

兩者都代表「新增一個 enum 值」仍需要 `MODIFY COLUMN` / `ALTER TYPE`，與 design.md
「MySQL 不再要求原生 ENUM，PostgreSQL 不再要求 named type」和任務 6.4 的可攜性目標直接衝突。

**發現時機**：任務 6.4 驗證階段，實際檢查 `Column.type.compile(dialect=mysql.dialect())` /
`compile(dialect=postgresql.dialect())` 才發現仍輸出 `ENUM('active',...)` / `teamstatus`（named type
參照），而非預期的 `VARCHAR`。

**修正**：

- `app/models/database_models.py` 17 個欄位、`app/audit/database.py` 3 個欄位（含 `action_type`——
  雖然資料不變但型別仍需轉換為 VARCHAR）皆加上 `native_enum=False`。
- `app/db_migrations_enum_support.py::migrate_enum_storage()` 新增 `target_native: bool = False` 參數：
  - `target_native=False`（upgrade 方向）：MySQL 轉換完成後留在 `VARCHAR(widen_length)`，不收斂回
    `ENUM(...)`；PostgreSQL 轉換完成後留在 `TEXT`，不重建 named TYPE。
  - `target_native=True`（downgrade 方向）：MySQL 收斂回 `mysql.ENUM(*new_labels)`；PostgreSQL 重建
    named TYPE 並讓所有共用該 TYPE 的欄位改回該 TYPE——完整還原成這支 migration 執行前的具名型別狀態。
- 兩支 migration（`21a93e84da75` 主庫、`4e8f3d57b312` audit）的 `upgrade()`/`downgrade()` 分別傳入
  `target_native=False`/`True`。
- audit 的 `action_type`（ActionType）補上 identity mapping 群組（`CREATE→CREATE` 等，資料 no-op），
  確保它也轉為可攜 VARCHAR，不再是三個 audit enum 中唯一維持原生型別的例外。

**驗證**（真實 MySQL 8.4 / PostgreSQL 16，見下方「真實伺服器驗證」）：upgrade 後 MySQL 欄位確認為
`varchar(64)`、PostgreSQL 欄位確認為 `text`（原 named TYPE 已 `DROP TYPE`、未重建），且皆可直接寫入
「從未在任何地方宣告過」的全新字串值，全程零 DDL；downgrade 後正確收斂回 `ENUM(...)` / 重建 named TYPE
並可正確拒絕該全新值（型別限制生效）。

### 2. `verify_mysql_mediumtext_defaults` → `verify_schema_drift` 的過度範圍設計（自我發現並修正）

Task 2.3 原本嘗試用 Alembic `compare_metadata`（透過既有 `validate_legacy_database()`）做全表 schema
比對取代 MySQL-only 的 MEDIUMTEXT 檢查。實測發現：目前 schema 與 model metadata 之間存在大量與
large-text 型別完全無關的既有落差（`ai_tc_helper_sessions`/`ai_tc_helper_stage_metrics`/
`ai_tc_helper_drafts` 等表存在於 DB 但不在 model；`qa_ai_helper_*` 系列表有數十個索引/FK 落差）——
若把這個無範圍限縮的 drift gate 接進開機路徑，會讓**所有**現有部署（包含原本運作正常的 SQLite
環境）直接無法開機，是遠超出「large-text 一致性」這個任務範圍的嚴重回歸。

**修正**：改為 `verify_large_text_columns(engine, target_name, logger, label)`——非 MySQL 恆為
no-op；MySQL 上只走 model metadata，僅檢查明確宣告為 `app.db_types.MediumText` 的欄位，逐一比對
`inspect(engine)` 回報的實際型別是否為 `MEDIUMTEXT`/`LONGTEXT`，不做無關欄位/索引/FK 的全表比對。

### 3. 主庫既有 migration chain 對 MySQL/PostgreSQL 全新部署不可攜（沿用 Change C 已回報的既有 bug，本次追加一個新發現）

`alembic/versions/b9d4e7a3c0f2_split_automation_provider_scope.py` 與
`e7c3a9d1f2b4_add_ref_repo_multi_repo_storage.py` 皆有與本 change 無關的既有 MySQL/PostgreSQL
相容性問題（`DROP INDEX IF EXISTS` 語法、FK 綁定索引無法直接砍、raw SQL 用 `DATETIME` 在
PostgreSQL 不存在），Change C 驗證階段已回報（spawn_task）。本次 Change B 驗證階段追加發現同一個
`automation_scripts` 表的 model 層問題：

```
uq_automation_script_ref = UniqueConstraint(team_id, provider_id, ref_repo(255), ref_path(500), ref_branch(200))
```

在 `utf8mb4` 下（4 bytes/char）換算超過 MySQL 3072 bytes 的索引鍵長度上限
（`Specified key was too long; max key length is 3072 bytes`）。這是 **model 層**的問題（不只是舊
migration 的 raw SQL），即使繞過 Alembic chain、改用 `metadata.create_all()` 直接建表也會撞到同一個
限制（見下方「跨引擎搬遷 rehearsal」的驗證方式）。已併入既有的 spawn_task
（`task_50b68fe9`，「Audit and fix main-DB migration chain for real MySQL/PostgreSQL bootstrap」）一併
追蹤，明確不屬於本次 schema-portability 改動範圍。

## 真實 MySQL 8.4 / PostgreSQL 16 驗證

環境：`docker-compose.mysql.yml` / `docker-compose.postgres.yml` 起的 disposable 服務
（`tcrt-mysql` port 33060、`tcrt-postgres` port 5433）。

### 隔離 schema 驗證（逐項功能，繞過既有 migration chain 的不可攜段落）

對每個新／修改的 migration，個別建立涵蓋所需欄位的最小 schema、seed 舊表示法資料、透過
`Operations`（`MigrationContext.configure(connection)` + `monkeypatch.setattr(module, "op", ...)`）
直接呼叫 `upgrade()`/`downgrade()`，逐一驗證：

- **enum 可攜性**（`21a93e84da75`／`4e8f3d57b312`）：10 個主庫 enum 群組 + 3 個 audit enum 群組，
  upgrade 後資料為 portable value、型別為 VARCHAR/TEXT（無原生具名型別）；downgrade 後資料還原為
  name、型別收斂回 ENUM/named TYPE。額外驗證 `ResourceType`（19 成員 vs 原本 DB 內只有 11 個標籤的
  既有 drift）與 `TeamAppTokenStatus`（大小寫）等既有 bug 已被此次轉換一併修正。
- **`test_case_set_id` 回填 + NOT NULL**（`9cd6393a4da6`）：由 section 反推 set、由 team 預設 set
  回填、無法決定時中止（`RuntimeError`，不靜默猜測）、已滿足時 no-op，四種情境皆在 SQLite/MySQL/
  PostgreSQL 上驗證；downgrade 正確把欄位降回 nullable。
- **username 大小寫不敏感唯一性**（`f5f2d075fd93`）：`sa.func.lower(...)` 讓 SQLAlchemy 依 dialect
  自動產生正確 DDL（MySQL 8.0.13+ 的 functional key part 需要雙層括號
  `((lower(username)))`，SQLite/PostgreSQL 為單層 `(lower(username))`——已用
  `CreateIndex(idx).compile(dialect=...)` 離線確認三種輸出，再各自於真實 server 執行 DDL 確認
  語法正確、大小寫變體重複正確被拒絕）；既有重複資料時中止遷移並列出衝突 id；downgrade 還原
  大小寫敏感唯一性。
- **PostgreSQL sequence reset**（`scripts/db_cross_migrate.py::reset_postgresql_sequences`）：
  顯式 PK 資料載入後，`pg_get_serial_sequence` + `setval` 正確把 sequence 移到 `max(pk)`；空表邊界
  情況（`is_called=false`）正確從 1 開始，不略過 id=1；MySQL/SQLite 不受影響（AUTO_INCREMENT/
  ROWID 本來就依表內實際值續號）。

### 跨引擎搬遷 rehearsal（`scripts/db_cross_migrate.py`，真實資料流）

完整 bootstrap 一個 SQLite 主庫（套用本 change 所有新 migration 到 head）、用 ORM seed 一筆真實
team/user/test_case_set/test_case 資料，透過 `db_cross_migrate.py` 搬到：

- **MySQL**（`--create-target-schema`，排除 `automation_scripts` 及其 3 個 FK 依賴表
  `automation_script_case_links`/`automation_script_env_vars`/`automation_runs`——原因見上方
  bug #3）：60+ 個表全數 `row_counts_match=true`；`users.role='admin'`、
  `teams.status='active'`、`teams.default_priority='Medium'`、`test_cases.sync_status='synced'`
  皆為 portable value；`test_cases.test_case_set_id` 為 `int NOT NULL` 且正確回填。
- **PostgreSQL**（手動建對齊 schema，繞過 `--create-target-schema`——原因：SQLAlchemy reflect
  SQLite 的 `DATETIME` 型別直接對 PostgreSQL `create_all()` 會產生
  `type "datetime" does not exist`，這是 SQLAlchemy 跨 dialect reflection 的既有限制，與本
  change 無關，也不影響正式 cutover-migrate 流程——見下方說明）：同樣資料正確搬入，且：
  - 新增一筆不帶顯式 PK 的 `teams` 列，`id` 正確接續為 `2`（sequence reset 生效，不撞鍵）。
  - 嘗試插入大小寫變體重複 username（`'Alice'` vs 已存在的 `'alice'`）正確被
    `uq_users_username_lower` 唯一約束拒絕。

**額外發現的 `--create-target-schema` 既有限制（已加註解說明，不修正）**：SQLAlchemy
`MetaData.reflect()` 無法還原 expression-based index（例如 `uq_users_username_lower` 這種
`lower(username)` 唯一索引，reflect 時會印出
`SAWarning: Skipped unsupported reflection of expression-based index`）。這代表透過
`db_cross_migrate.py --create-target-schema` 這個 standalone 捷徑建出的 target，不會有這個
大小寫不敏感唯一性保護（已實測 MySQL rehearsal 上插入 `'Alice'` 確實成功，印證此限制）。**不影響
正式 cutover-migrate 流程**：`app/db_cutover_workflow.py` 的 `_run_migrate_workflow` 一律先呼叫
真正的 `database_init.py`（走 Alembic migration）bootstrap target schema，`_run_cross_migrate` 只
負責資料搬移、從未傳遞 `--create-target-schema`。已在 `scripts/db_cross_migrate.py` 的
`create_target_schema` 分支加註解說明此限制與影響範圍，避免未來有人誤以為這個 flag 可以完全取代
正式 migration。

## 2026-07-14 更新：主庫 migration chain 可攜性問題已修復，補完整版跨引擎驗證

上一版本文件記載的「未完成／延後事項」（主庫從空庫對 MySQL/PostgreSQL 完整 bootstrap）已解決。
使用者核准後於同分支原地修復以下已 merge migration（皆為「SQLite 路徑逐位元組核對不變、
MySQL/PostgreSQL 路徑此前從未成功執行過故無回溯相容性負擔」的修法，詳見 tasks.md 第 7 節）：

1. **`b9d4e7a3c0f2`（split_automation_provider_scope）**：MySQL 原本因 `DROP INDEX IF EXISTS`
   語法錯誤與「索引被 FK 綁定無法直接砍」失敗；PostgreSQL 原本因 raw SQL 用不存在的 `DATETIME`
   型別失敗。改為：SQLite 維持原本的整表重建 raw SQL 不變（真實 schema dump diff 驗證，唯一差異
   是 Python 縮排造成的字串內部空白，語意 100% 相同——連續兩次獨立跑同一支未修改的原始 migration，
   `qa_ai_helper_sessions` 的 FK 子句順序都不同，證實這與本次修改無關，是既有的、與 dict/set
   疊代順序有關的既有非決定性行為）；MySQL/PostgreSQL 改用 `op.drop_constraint`+
   `op.create_foreign_key` 直接 retarget FK，不做整表重建。
2. **`e7c3a9d1f2b4`（add_ref_repo_for_multi_repo_storage）**：`uq_automation_script_ref` 五欄
   複合唯一鍵（`team_id, provider_id, ref_repo(255), ref_path(500), ref_branch(200)`）在 MySQL
   utf8mb4 下換算 3820+ bytes，超過 3072-byte 索引鍵長度上限——這是 **model 層**問題，即使繞過
   Alembic 改用 `metadata.create_all()` 建表也會撞到同一限制。MySQL/PostgreSQL 改用固定長度
   `ref_key_hash`（`CHAR(64)`，SHA-256，見 `app/models/database_models.py::
   _automation_script_ref_key_hash`）承載唯一性，由 `before_insert` ORM event listener 維護
   （這 5 個欄位建立後不可變，只需要 before_insert，不需要 before_update，已確認
   `app/services/automation/script_service.py` 從未在建立後修改過這些欄位）；另建
   `(team_id, provider_id, ref_repo, ref_branch)` 一般索引維持既有批次查詢（`existing_by_path`
   那類「抓某 repo+branch 下所有 script」查詢）的效能。SQLite 維持原本 5 欄複合唯一鍵不變；
   新增 `f84bbca9a911` 讓已跑過舊版 e7c3a9d1f2b4 的既有 SQLite 資料庫（例如使用者自己的
   `test_case_repo.db`）收斂到同一 `ref_key_hash` 機制（僅 SQLite 生效，MySQL/PostgreSQL 已在
   e7c3a9d1f2b4 拿到，此遷移對它們是 no-op）。
3. **`c3e7a1f9d2b4`（drop_automation_smart_scan_runs）**：移除多餘且在 MySQL 上會出錯（同樣是
   FK 綁定索引無法直接砍）的逐一 `DROP INDEX`——`DROP TABLE` 本身就會連同索引一起清除，三引擎
   皆然，原本的逐一 drop 純屬多餘防禦性程式碼。
4. **新增 `a371471a3008`**：`database_init.py` 的 `verify_large_text_columns` gate 在全新 MySQL
   bootstrap **首次真正被驗證到**時（先前被上述 chain 問題擋住，從未有人跑到這一步），抓到 10 個
   先前從未被觸及、遺漏 MEDIUMTEXT 提升的欄位（`test_run_sets.automation_suite_ids_json`、
   `system_automation_providers.config_json`/`credentials_encrypted`、
   `automation_scripts.declared_vars_json`、`automation_environments.description`、
   `automation_environment_params`/`automation_script_env_vars` 的 `value_plaintext`/
   `value_encrypted` 共 10 欄）。比照既有 `8d3c1b4a6f20` legacy widen migration 的模式加一支新的
   catch-up migration，但採**硬編碼欄位清單**而非泛用掃描——泛用掃描的 `downgrade()` 會連
   `8d3c1b4a6f20` 等更早期 migration 已提升的欄位一併誤傷降級，已用真實 MySQL 資料庫驗證
   downgrade 只還原這 10 欄、`test_cases.steps`（`8d3c1b4a6f20` 提升）等不受影響。

**過程中發現並修正一個真實回歸**：`AutomationScript` 的 `before_insert` listener 原本直接讀取
`target.ref_repo` 計算 hash，但 `ref_repo` 欄位有 `server_default=""`——測試 fixture 若未顯式
設定該欄位，Python 物件層級仍是 `None`（DB 端的 server_default 要到真正 INSERT 時才生效），
導致 `hashlib`/`str.join` 對 `None` 拋 `TypeError`。全套 pytest 因此一度出現 17 failed/101
errors；修正為 `target.ref_repo or ""`（比照欄位本身的 server_default）後，重跑全套恢復到
762 passed（與既有 baseline 完全一致的 6 個既有失敗，零新增回歸）。

**發現另一個獨立、範圍外的既有 bug**：`a1b2c3d4e5f6`（add_team_app_tokens）的 `downgrade()` 在
真實 MySQL 上也會因「FK 綁定索引無法直接砍」失敗（與上述 bug 1/3 同類，但是不同的 migration、
只影響 downgrade 不影響 upgrade）。已另開 spawn_task 追蹤，不屬本次修復範圍
（Phase 1 的驗證門檻是「upgrade 到 head 成功」，這個 bug 不影響此門檻）。

### 驗證結果

- `database_init.py`（真正的 production bootstrap 入口，非僅 raw alembic）對全新 MySQL 8.4 與
  PostgreSQL 16 從空庫到 head（`f84bbca9a911`）皆完整成功，含所有驗證 gate。這是首次有任一
  MySQL 或 PostgreSQL 環境成功走完主庫的完整 migration chain。
- `b9d4e7a3c0f2`／`e7c3a9d1f2b4` 的 `downgrade()` 個別在真實 MySQL 上驗證正確（用 isolated
  bind-Operations 技術單獨呼叫，避開上述無關的 `a1b2c3d4e5f6` downgrade bug）。
- SQLite 全鏈路 upgrade/downgrade/re-upgrade 迴歸確認無變化。
- 補齊任務 6.1 原本因 chain 問題無法完成的完整版跨引擎 schema 比對：三引擎從空庫套用同一 head
  後，58 個資料表（不含 `alembic_version`）、欄位集合、nullable 完全一致，零 mismatch；
  索引/唯一約束的僅有差異是 MySQL 對 FK 欄位自動建立的輔助索引（無害物理變體，SQLite/PostgreSQL
  不需要）與既有已記錄的 expression-index reflection 限制。
- `AutomationScript.ref_key_hash` 的 `before_insert` 計算與唯一性拒絕行為，在 SQLite/MySQL/
  PostgreSQL 三引擎皆用 ORM insert 測試確認一致（相同輸入產生相同 hash；重複值皆正確被
  `IntegrityError`/`UniqueViolation` 拒絕）。
- 全套 `uv run pytest app/testsuite -q`：762 passed（與 baseline 完全相同的 6 個既有失敗），
  29 skipped，零新增回歸。`uv run ruff check` 對所有新增/修改檔案皆乾淨。

## 未完成／延後事項

- `a1b2c3d4e5f6`（add_team_app_tokens）的 downgrade 在真實 MySQL 上失敗，已開 spawn_task
  （`task_3c498e8b`）追蹤，不影響 upgrade 路徑。
