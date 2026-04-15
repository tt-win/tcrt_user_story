## Context

早期 TCRT 是作為一個輔助工具，依賴 Lark (Feishu) Bitable 上的 Test Case 資料，因此開發了 `TestCaseSyncService` 來定時或手動拉取 Lark 上的資料並寫入本地資料庫。隨著 TCRT 本身的編輯能力完善，系統已經具備自己的 Test Case 樹狀結構、版本控制與直接編輯功能，Lark 同步功能變得多餘且難以維護，特別是在處理不同環境、欄位變更或網路問題時經常出現例外狀況。

## Goals / Non-Goals

**Goals:**
- 安全地從專案中移除 `TestCaseSyncService` 相關程式碼。
- 移除相關的 API 端點，避免客戶端呼叫不存在的服務。
- 清理前端介面中（HTML/JS）關於從 Lark 同步測試案例的按鈕、狀態列和事件綁定。
- 清理可能僅用於 Lark 同步的背景任務腳本（如 `scripts/sync_tcrt_to_lark.py`）。

**Non-Goals:**
- 本次重構不包含刪除本地已有的 Test Case 資料（這類資料應繼續作為本地資源使用）。
- 本次不影響 Jira 相關的整合，因為 Jira 整合是專注於 Issue / Ticket 關聯，而非從外部作為唯一的 Test Case 來源。

## Decisions

1. **移除後端服務與 API**
   *   **決定：** 刪除 `app/services/test_case_sync_service.py` 檔案。
   *   **決定：** 刪除 `app/api/` 目錄下（可能是 `test_cases.py` 或獨立的 `sync.py`）負責觸發同步的 Router Endpoint。
   *   **Rationale：** 這是最直接的清理方式，確保系統不會再有機會觸發與 Lark 的資料同步。

2. **清理前端依賴**
   *   **決定：** 在 `app/templates` 與 `static/js` 中搜尋與「同步」 (sync_test_cases) 相關的 UI 元件並移除。
   *   **Rationale：** 確保使用者介面上不會出現失效的按鈕或錯誤提示。

3. **保留資料庫模型**
   *   **決定：** `TestCase` 在 `app/models/database_models.py` 中的定義將暫時保留，若其中有明確寫著「從 Lark 同步時暫存」的無用欄位，則可以考慮標記為 Deprecated，但為了避免複雜的 Schema Migration，這次先不主動刪除欄位，僅移除寫入邏輯。

## Risks / Trade-offs

- **[Risk] 部分團隊仍依賴 Lark 編輯** → 如果有使用者仍習慣在 Lark 編輯並期望 TCRT 自動同步，這項變更會打破他們的工作流程。
  - **Mitigation：** 這是一個產品決策，必須在發布前與 Stakeholders 溝通，說明未來所有 Test Case 管理都應在 TCRT 內進行。

- **[Risk] 移除程式碼時誤刪其他 Lark 整合** → TCRT 還有 Lark 使用者認證或 Lark 群組通知等功能，不能誤刪。
  - **Mitigation：** 嚴格限制刪除範圍在「Test Case Sync」，僅移除 `TestCaseSyncService` 與其相關腳本，保留 `LarkClient` 的其他共用功能。
