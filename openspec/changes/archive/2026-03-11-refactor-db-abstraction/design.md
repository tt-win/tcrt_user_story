## Context

目前 TCRT 系統的資料庫依賴雖然使用了 SQLAlchemy 作為 ORM 抽象層，但在許多效能敏感或特定邏輯處，直接採用了寫死 SQLite 語法 (Raw SQL) 或特有功能的方式。例如：
1. 資料庫連線初始化中直接執行 `PRAGMA` 優化指令。
2. 查詢 JSON 結構時使用 `json_each`。
3. 資料寫入時使用 `INSERT OR REPLACE`。
4. 模型定義時使用 `sqlite_autoincrement=True`。
這造成系統與 SQLite 深度耦合，未來難以平滑遷移到其他關聯式資料庫 (如 MySQL 或 PostgreSQL)。

## Goals / Non-Goals

**Goals:**
- 將所有資料庫連線中針對 SQLite 的優化指令 (如 `PRAGMA`) 抽離至僅在連接為 SQLite 時執行。
- 將 `test_case_repo_service.py` 中的 `json_each` 改寫為透過 SQLAlchemy 或更通用的 SQL 語法實作。
- 將 `tcg_converter.py` 中的 `INSERT OR REPLACE` 替換為跨資料庫的 Upsert 語法，或依不同 `Dialect` 採用對應寫法。
- 移除所有模型中專屬於 SQLite 的設定參數。
- 確保所有測試案例在修改後仍能正常執行，以驗證不影響現有系統運作。

**Non-Goals:**
- 此次重構不包含將目前生產環境的資料庫從 SQLite 實際遷移至其他資料庫。
- 此次重構不包含 `database_init.py` 的全面替換（例如不強制引入 Alembic），僅調整其中無法在跨資料庫環境執行的 SQL 語法或在必要時加上判斷。

## Decisions

1. **資料庫連線的 PRAGMA 處理**
   *   **決定：** 透過 SQLAlchemy 的 `Connection.dialect.name` 或連線 URL 判斷，僅在連接為 `sqlite` 時才執行 `PRAGMA` 初始化指令。
   *   **Rationale：** 這是侵入性最小的做法，可以保留 SQLite 環境下的優化，又能避免其他資料庫在連線時拋錯。

2. **移除 `json_each` 查詢**
   *   **決定：** 修改 `app/services/test_case_repo_service.py` 裡的邏輯。因為 SQLite 和 MySQL 等對 JSON 操作的原生語法差異極大，我們會優先嘗試將資料取回應用程式層進行過濾，或依據 `engine.dialect.name` 動態生成針對不同資料庫支援的查詢字串。
   *   **Rationale：** 若要在 SQL 層解決，這會是最複雜的差異點；考量資料量，若能統一透過簡單的 `LIKE` 或 ORM 來實作會是最乾淨的，不然就需要使用方言分岔 (dialect branching)。

3. **替換 `INSERT OR REPLACE` 邏輯**
   *   **決定：** 在 `tcg_converter.py` 中，捨棄 `INSERT OR REPLACE`，改用 SQLAlchemy 的 `insert(Table)` 並結合 `.on_conflict_do_update()` (針對支援的資料庫) 或是改為先嘗試更新，若失敗或不存在再新增的傳統 Upsert 模式。
   *   **Rationale：** 標準的 SQLAlchemy ORM 語法能確保更高的相容性，且能更容易被測試覆蓋。

4. **模型定義的修改**
   *   **決定：** 將 `app/models/database_models.py` 中的 `sqlite_autoincrement=True` 移除，改用標準的 `autoincrement=True` 搭配主鍵定義。
   *   **Rationale：** 這是最簡單的修改，SQLAlchemy 會自動幫忙轉換成不同資料庫的實作。

## Risks / Trade-offs

- **[Risk] JSON 查詢效能下降** → 改用跨資料庫的方法 (如應用層過濾或通用 `LIKE` 查詢) 可能會導致原本透過 `json_each` 獲得的索引效能優勢喪失。
  - **Mitigation：** 若測試後發現效能瓶頸，則採「Dialect Branching」策略，在 Python 層判斷資料庫類型並組裝不同的 Raw SQL 查詢。
- **[Risk] Upsert 併發衝突** → 若改用先查後寫的傳統方式，在高併發環境下可能會有 Race condition。
  - **Mitigation：** 盡量使用 SQLAlchemy 針對不同 Dialect 提供的 Upsert 擴展 (例如 SQLite 的 `dialects.sqlite.insert`)，並在統一的 Abstraction 函式中做轉接。
