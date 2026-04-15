## Context

目前專案已經有 engine / session factory 級別的抽象，但 runtime DB access 仍明顯分散：

- `app/api/`、`app/services/`、`app/auth/` 內仍可見大量直接 `query` / `execute` / `add` / `commit`
- 多個 runtime 模組仍會自行建立 session，而不是透過單一 lifecycle 管理
- `main` / `audit` / `usm` 的邊界未被明確收斂，部分流程同時在同一 handler 內協調多套資料庫
- dialect-sensitive raw SQL 與 SQLite-specific 診斷仍散落在共享 runtime path
- `scripts/` 與 `ai/` 工具鏈尚未完全重用同一套受管資料存取邊界

這代表專案現在比較像「完成了 engine/migration readiness」，但尚未完成「runtime data access abstraction」。只要這些散落路徑仍存在，未來每次切換資料庫都還是得重新盤點整個 repo。

## Goals / Non-Goals

**Goals:**

- 為 `main`、`audit`、`usm` 建立一致且顯式的資料存取邊界。
- 將 session lifecycle、transaction ownership 與 sync fallback 收斂到單一治理方式。
- 將 runtime raw SQL、dialect branching 與跨資料庫協調集中到可驗證的抽象層。
- 讓 `scripts/`、`ai/`、背景任務與 web runtime 共用同一套 target-aware 存取契約。
- 將「可無痛切換 DB」轉成靜態守門、測試矩陣、smoke workflow、rehearsal 與 rollback 標準。

**Non-Goals:**

- 此 change 不直接執行正式環境 cutover，也不承諾一次把實際資料搬遷到新的生產資料庫。
- 此 change 不要求消滅所有 SQL；migration/bootstrap 與受管 boundary 內的 SQL 仍可存在，但必須被集中治理。
- 此 change 不重設既有 domain model、API contract 或業務功能定義；目標是收斂資料存取邊界，而不是同步做產品層重設計。

## Decisions

1. **三套資料庫都必須有顯式 access boundary**
   - `main`、`audit`、`usm` 各自擁有受管的 access boundary，runtime caller 只能透過 boundary 執行資料讀寫。
   - API handler、application/domain service、background task 不再直接持有 `AsyncSession`、ORM query 或 `commit` / `rollback` 細節。
   - 實作上可以是 repository、gateway、service adapter 或 unit-of-work 組合，但責任必須清楚落在專用 boundary layer，而不是繼續散落在 route/service 檔案。

2. **Session lifecycle 與 transaction ownership 集中治理**
   - session 的建立、關閉、commit、rollback 必須由受管 provider / boundary / unit-of-work 負責。
   - runtime path 中不得再自行 `SessionLocal()`、`get_async_session()` 或直接操作 sync session。
   - 若某些流程仍需 sync fallback，必須透過明確的 threadpool / bridge helper，由 boundary layer 持有，而不是在 handler/service 內臨時轉接。

3. **跨資料庫流程由協調層編排，不在 handler 內混用 session**
   - 任何同時觸及 `main`、`audit`、`usm` 的流程，都必須透過顯式 coordination layer 編排。
   - 每一個 boundary 只負責自己的資料庫；跨庫流程由上層 orchestration 決定呼叫順序、失敗回應與補償策略。
   - 本 change 不引入 distributed transaction；對於跨庫非原子性的風險，需在設計與 rollback/rehearsal 中明確處理。

4. **Raw SQL 與 dialect-sensitive 行為集中到受管模組**
   - shared runtime path 不得散落 SQLite-specific `PRAGMA`、`sqlite3.OperationalError` 偵錯邏輯或寫死某一方言的 SQL。
   - raw SQL 如有必要，僅允許存在於受管 boundary/infra 模組，並以 dialect-aware adapter 或明確例外處理包裝。
   - ORM 優先，但不是唯一手段；關鍵在於 SQL/dialect 差異必須有單一治理位置與測試覆蓋。

5. **Offline tools 必須重用同一套資料存取契約**
   - `scripts/`、`ai/`、維運工具與資料修補流程應透過與 runtime 一致的 boundary/config contract 存取資料庫。
   - 直接綁定 SQLite 檔案路徑、隱式 session factory 或各工具自行推導 driver/dialect 的做法必須移除。
   - migration/bootstrap/legacy inspection 可保留較低階實作，但要被明確分類為允許例外，而不是一般資料存取範式。

6. **以工程守門防止 direct DB access 回流**
   - 需要建立靜態規則，阻擋新的 runtime direct DB access 滲回 `app/api/`、`app/services/`、`app/auth/`、`scripts/`、`ai/`。
   - 守門不只檢查 `SessionLocal()`；也要涵蓋直接 `commit` / `rollback` / `execute(text(...))` / 多 DB handler 混用等模式。
   - 同時建立 SQLite / MySQL / PostgreSQL 的 smoke 與 rehearsal 矩陣，讓 portability 不再靠人工印象判斷。

## Architecture Sketch

```text
Before
------
API / Service / Auth / Script
    ├─ query / execute / add / commit
    ├─ SessionLocal() / get_async_session()
    └─ main + audit + usm mixed in runtime call sites

After
-----
API Handler / Background Task / Script
              │
              ▼
      Application Orchestrator
        ├─ Main Boundary
        ├─ Audit Boundary
        └─ USM Boundary
              │
              ▼
     Managed Session / Transaction
              │
              ▼
      Dialect-aware SQL / ORM Layer
              │
              ▼
          Engine / Driver
```

## Risks / Trade-offs

- **大範圍改造風險高**：此 change 會觸及 API、service、auth、scripts、ai 與測試 fixture。
  - **Mitigation:** 以邊界分類與熱區分批收斂，但在同一 change 內完成規格、守門與驗證閉環。
- **抽象層增加樣板碼**：repository/gateway/unit-of-work 會增加結構成本。
  - **Mitigation:** 優先按資料庫與責任切分，不做過度泛化；先解決 ownership 與 boundary 問題，再談共用抽象。
- **跨庫流程無法天然原子化**：收斂邊界後，跨 `main`/`audit`/`usm` 的一致性問題會被看得更清楚。
  - **Mitigation:** 在 orchestration layer 明確定義順序、失敗處理、補償與 rehearsal 驗證，不假裝它是單一 transaction。
- **驗證矩陣會變慢**：加入多資料庫 smoke 與靜態守門後，CI/本機驗證成本增加。
  - **Mitigation:** 區分 pre-merge guardrail、smoke workflow 與 rehearsal 層級，讓不同深度驗證各自可重複執行。

## Migration Plan

1. **盤點與分類**
   - 建立 direct DB access 熱區清單、允許例外清單與目標 boundary 分類。
   - 明確標示哪些路徑屬於 runtime、哪些屬於 migration/bootstrap/legacy inspection 例外。

2. **建立 access boundary 骨架**
   - 定義 `main`、`audit`、`usm` 的 boundary contract、session provider 與 transaction ownership 規則。
   - 建立跨庫 orchestration 的責任邊界與錯誤處理模式。

3. **重構 runtime 與 background flows**
   - 由熱區開始把 API/service/auth 中的 direct session、raw SQL 與 commit/rollback 邏輯搬入 boundary layer。
   - 消除 handler 內混用多資料庫 session 的做法。

4. **重構 scripts / ai / 維運工具**
   - 讓離線工具與資料修補腳本改走 target-aware boundary/config contract。
   - 移除直接依賴 SQLite 檔案路徑或個別工具自行建立 session 的實作。

5. **補齊守門與驗證**
   - 新增靜態規則、測試 fixture 對齊、multi-database smoke workflow、rehearsal 與 rollback 文件/輸出。
   - 以 SQLite、MySQL、PostgreSQL 至少各完成一次可重複的驗證路徑。

## Open Questions

- 無阻塞性 open question。此 change 的方向已經明確：關鍵不是再討論「要不要抽象」，而是把 boundary 位置、例外清單與驗證門檻寫成可執行任務並完整落地。
