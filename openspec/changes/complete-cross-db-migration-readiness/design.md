## Context

目前 `main`、`audit`、`usm` 三套資料庫都已納入 Alembic 與嚴格 legacy adoption，但系統仍保留數個 SQLite 時代的尾巴：driver 依賴未正式納入、USM 設定仍走環境變數特例、部分 runtime/service/script 仍直接依賴 `sqlite3` 或 `PRAGMA`、多數測試 fixture 仍用 `Base.metadata.create_all()` 建 schema。這些問題讓「可切換 URL」與「可實際 cutover 到另一個 DB」之間仍有落差。

本次設計目標不是直接切 production DB，而是把專案收斂到可重複驗證的 cross-database readiness 狀態，讓後續 MySQL 或 PostgreSQL cutover 只剩資料搬遷與環境切換，而不是再臨時清 runtime 相依。

## Goals / Non-Goals

**Goals:**
- 建立正式的 driver 與 sync/async dialect mapping，讓 MySQL 與 PostgreSQL 都能被一致初始化。
- 將 `main`、`audit`、`usm` 的資料庫 URL 收斂到統一設定模型，移除 USM 特例。
- 清除剩餘 SQLite 專屬 runtime、script 與診斷邏輯，改為 dialect-aware 或 SQLAlchemy error-based 實作。
- 將主要測試 fixture 改為透過 Alembic 建 schema，並補至少一套 server DB smoke/rehearsal 流程。
- 定義 cutover readiness 產出：preflight、schema/data verification、rollback steps。

**Non-Goals:**
- 不在本 change 內執行正式 production cutover。
- 不在本 change 內做跨資料庫資料型別的大規模重塑，例如將所有 `Text JSON` 一次改成原生 JSON 欄位。
- 不承諾所有測試都在每一種資料庫上全量執行；先建立可擴充的 smoke 與 fixture 基礎。

## Decisions

### 1. 支援的 driver matrix 明確化
- MySQL 採 `asyncmy` + `PyMySQL`。
- PostgreSQL 採 `asyncpg` + `psycopg`。
- `app/database.py`、`app/audit/database.py`、`app/models/user_story_map_db.py`、`app/db_migrations.py` 共用同一套 URL normalization 規則，避免同一個 target dialect 在不同模組映射到不同 driver。

**Rationale:** 現在程式已經有 URL normalization，但沒有正式依賴與一致 driver policy。先明確 driver matrix，才能把 preflight、文件與 smoke 自動化寫死。  
**Alternative considered:** 只先支援 MySQL。缺點是 PostgreSQL 仍停留在「看起來能切」但沒納入治理，會再留下第二批技術債。

### 2. 將 USM database URL 納入正式設定模型
- 在 `app/config.py` / `config.yaml.example` 新增 USM 專屬 config 區塊或等價的正式欄位。
- `user_story_map_db.py` 與 migration helper 不再直接以環境變數常數作為唯一來源，而是透過同一設定結構解析，再允許 env override。

**Rationale:** 現況只有 USM 是半特例，最容易在部署與 cutover 時漏配。  
**Alternative considered:** 保留 `USM_DATABASE_URL` 單一 env-only。缺點是設定面與 `main` / `audit` 不一致，無法形成完整 preflight。

### 3. 用「方言感知 + SQLAlchemy 例外」取代 SQLite 專屬路徑
- `admin.py` 不再 catch `sqlite3.OperationalError`，改為 catch SQLAlchemy/DBAPI 通用錯誤並以錯誤內容判定缺表。
- `test_case_sync_service.py` 的外鍵診斷只在 SQLite 執行 `PRAGMA foreign_key_check`；其他 dialect 使用通用訊息或略過。
- `scripts/migrate_tcg_format.py` 與 `TCGConverter` 改為吃設定後的 DB URL / session，不再綁 `sqlite3.connect()` 與 `.db` 檔名。

**Rationale:** 這些都是 cutover 時最容易炸在非 SQLite 環境的點，而且屬於低耦合、可直接收斂的問題。  
**Alternative considered:** 保留腳本層 SQLite only。缺點是實際資料搬遷排練時仍需維護平行工具鏈。

### 4. 測試 schema 一律優先走 Alembic
- 新增共用 test helper，支援為 `main` / `audit` / `usm` 在暫存 DB 上執行 `upgrade head`。
- 將目前直接 `Base.metadata.create_all()` 的主要 fixture 逐步切到 migration-based setup。
- 保留極少數 model-isolated 單元測試可直接建表，但需明確標註為 unit-only。

**Rationale:** `create_all()` 只能驗證 model 當下長相，不能驗證 revision chain、constraint 名稱與 migration drift。  
**Alternative considered:** 繼續用 `create_all()` 讓測試較快。缺點是會掩蓋 migration 層問題，與實際部署不一致。

### 5. Cutover readiness 以可重複腳本與文件產出為主
- 建立 preflight / rehearsal 指令或文件化流程，至少輸出：
  - driver 與 URL 檢查結果
  - Alembic revision 狀態
  - schema validation/adoption 狀態
  - 重要資料表 row count / 基本一致性檢查
  - rollback steps
- 先提供 MySQL 自動 smoke；PostgreSQL 至少提供同等配置與指令入口，方便後續接入。

**Rationale:** 真正的「無痛」來自可重複 rehearsal，而不是口頭 checklist。  
**Alternative considered:** 只更新 README。缺點是缺乏可執行驗證，不足以支撐實際切換。

## Risks / Trade-offs

- [Risk] 新增 PostgreSQL sync driver 後，現有 URL normalization 若仍使用裸 `postgresql://` 可能造成 driver 不一致  
  → Mitigation：在本 change 內明確改成單一 sync driver scheme，並補 mapping 測試。

- [Risk] 測試從 `create_all()` 切到 Alembic 後，執行時間可能增加  
  → Mitigation：先抽共用 fixture、避免每個 test function 重跑 migration，優先 module/session 級別初始化。

- [Risk] 部分 legacy script 轉成 session/engine 導向後，使用方式會改變  
  → Mitigation：保留相容 CLI 參數，並補 migration notes。

- [Risk] PostgreSQL 的 enum / JSON 行為可能與 SQLite/MySQL 不同，導致 smoke 不夠全面  
  → Mitigation：先把 smoke 聚焦在 bootstrap、CRUD 基線與 migration path，將進階查詢差異列入 follow-up。

## Migration Plan

1. 補 driver 依賴與 URL normalization 測試。
2. 正式化 `USM` 設定來源，更新文件與範例設定。
3. 清理剩餘 SQLite 專屬 runtime/script 路徑。
4. 抽共用 Alembic test fixture，替換主要 API/service 測試。
5. 建立 MySQL / PostgreSQL preflight 與 smoke/rehearsal 文件或腳本。
6. 執行 SQLite 回歸、server DB smoke，確認可在新 DB 上完成 bootstrap 與基本操作。

Rollback:
- 若 driver/config 變更造成啟動失敗，可回退到 SQLite 預設 URL 與既有 `.db` 檔。
- 若新增 smoke/test fixture 導致測試不穩，先保留舊 fixture 為 fallback，待新 fixture 穩定後再移除。

## Open Questions

- PostgreSQL smoke 在本 change 是否要落到自動化容器驗證，還是先提供文件化 rehearsal 入口即可？
- `scripts/migrate_tcg_format.py` 是否要完全重寫成 SQLAlchemy session 版，還是保留為 legacy SQLite-only 並新增替代工具？
- cutover data verification 要做到 row count + sample query，還是需要再加 checksum/aggregation 驗證？
