## Why

### Purpose
目前專案雖已完成部分 cross-database readiness work，例如 Alembic migration、driver mapping 與部分 SQLite-specific cleanup，但 runtime DB access 仍分散在 `app/api/`、`app/services/`、`app/auth/`、`scripts/`、`ai/` 中，存在大量直接 `query` / `execute` / `add` / `commit`、自行建立 session，以及 `main` / `audit` / `usm` 邊界混用。As long as these access paths remain scattered, every future database cutover will still require repo-wide rediscovery instead of a repeatable cutover process.

### Requirements
#### Scenario: 切換資料庫不再需要逐檔盤點 (Cutover without repo-wide rediscovery)
Given maintainer 將 `main`、`audit`、`usm` 的 database URLs 切換到 MySQL 或 PostgreSQL  
When 系統執行 bootstrap、主要 API 流程、背景任務與離線工具  
Then 不需要再逐檔搜尋臨時 session、raw SQL 或跨庫誤用才能完成切換驗證

#### Scenario: Runtime DB access 經過顯式邊界 (Explicit runtime DB access boundaries)
Given 任一 web request、background task 或 domain service 需要存取資料庫  
When 該流程讀寫 `main`、`audit` 或 `usm`  
Then 存取必須經過顯式的 access boundary，而不是在 handler / service 內直接分散持有 transaction 與 query 細節

### Non-Functional Requirements
- 本 change MUST 保持既有功能行為與 API contract 穩定，避免以跨資料庫名義引入功能回歸。
- 本 change MUST 保留 SQLite 本機開發流程，同時建立 MySQL / PostgreSQL 的可重複驗證路徑。
- 本 change MUST 將「是否已可無痛切換 DB」轉為可檢查的工程門檻，而不是口頭判斷。

## What Changes

- 移除過於狹窄的 `cross-db-migration-scripts` active change，改以全面 DB access abstraction 為主軸重立 change。
- 建立 `main`、`audit`、`usm` 三套資料庫的一致 access boundary、session lifecycle 與 transaction ownership 規範。
- 清除 runtime 內自行建立 session、直接持有 ORM query/commit 細節、以及多資料庫 handler 內混雜協調的做法。
- 將 dialect-sensitive raw SQL、cross-database coordination、offline tooling 與 cutover verification 收斂到可治理的抽象層與驗證流程。
- 補齊 DB cutover readiness 的驗收條件、測試矩陣、靜態守門規則與 rollback/rehearsal 要求。

## Capabilities

### New Capabilities
- `database-access-boundaries`: 定義 runtime、background tasks、offline tools 對 `main` / `audit` / `usm` 的顯式資料存取邊界與責任分工。
- `database-cutover-readiness`: 定義「可無痛切換 DB」所需的驗證矩陣、rehearsal、rollback 與守門條件。

### Modified Capabilities
- `database-async`: 將需求從「使用 AsyncSession」提升為「session lifecycle 與 sync fallback 必須被集中治理」。
- `database-operations`: 將需求從「SQLite-specific syntax cleanup」擴充為「runtime dialect behavior 與 raw SQL 必須集中抽象化」。
- `database-migration`: 將 migration 治理延伸到 multi-database cutover validation 與 access-boundary alignment。

## Impact

- `app/api/`, `app/services/`, `app/auth/`, `app/audit/`
- `app/database.py`, `app/audit/database.py`, `app/models/user_story_map_db.py`
- `scripts/`, `ai/`, `app/testsuite/`
- OpenSpec delta specs for `database-async`, `database-operations`, `database-migration`, and new cutover/boundary capabilities
