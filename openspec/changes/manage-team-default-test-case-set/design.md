## Context

目前系統中 team 的 default Test Case Set 邏輯是分散在多個流程（如 Test Case 建立、fallback、adhoc 處理）中的隱含規則。管理員（admin）無法直接將現有的特定 Test Case Set 指定為新的 default。這導致如果團隊的預設工作流程改變，無法將預設落點對齊實際作業方式，也造成 default policy 散落在各個 API 端點中難以維護。本設計旨在集中管理 default set resolution 邏輯，並提供 admin 權限切換團隊預設 Test Case Set 的能力。

## Goals / Non-Goals

**Goals:**
- 提供 admin 權限的 API 與 UI 入口，以設定同一個 team 下的既有 Test Case Set 為 default。
- 重構現有的 default set resolution 邏輯，收斂為共享的後端 service method，避免在各處重複查詢。
- 確保切換 default 時，舊的 default set 會自動降級為一般 set，且同一個 team 任一時間只存在一個 default set。
- 確保目標 set 在被設為 default 前具備可用的 `Unassigned` section。

**Non-Goals:**
- 不會因為切換 default set 而自動搬移或轉移原本在舊 default set 中的任何 Test Cases。
- 不改變既有的 Test Run impact preview 與 cleanup 機制本身，僅更新其依賴的 default fallback 目標。

## Decisions

1. **統一的 Default Resolution Service**
   - **Decision:** 在 `app/services/test_case_set_service.py` 中新增或重構一個統一的方法來處理尋找 default set 的邏輯。
   - **Rationale:** 避免在 `app/api/test_cases.py`、`app/api/adhoc.py` 等多處 API 重複實作 `is_default=True` 的資料庫查詢。
   - **Alternatives Considered:** 維持現狀在各個 API 內自行查詢。這會導致未來若 default 邏輯改變，需修改多處，容易產生 bug。

2. **切換 Default Set API**
   - **Decision:** 實作一個 (Admin-only) 端點。此端點會在同一個 Transaction 中，將原有的 default set (若存在) 的 `is_default` 設為 `False`，並將目標 set 的 `is_default` 設為 `True`。
   - **Rationale:** 使用資料庫 Transaction 保證資料一致性，避免出現多個 default set 或沒有 default set 的競爭危害 (Race Condition)。
   - **Alternatives Considered:** 讓前端發送兩次請求分別更新，這無法保證原子性 (Atomicity)。

3. **確保 `Unassigned` Section 存在**
   - **Decision:** 在切換 default set 的邏輯中，必須檢查並確保目標 set 擁有 `Unassigned` section。若無，則自動建立。
   - **Rationale:** 預設的 fallback 或新建的 Test Case 經常需要落入 `Unassigned` 區塊，如果缺乏此區塊，會導致建立 Test Case 失敗。

4. **UI 狀態與互動更新**
   - **Decision:** 於前端邏輯中，使 Test Case Set 列表清楚標示出目前的 default set，並為擁有 admin 權限的使用者提供一個「設為預設」的操作按鈕。

## Risks / Trade-offs

- **[Risk] 並發切換可能導致多個 Default Sets** → **Mitigation:** 在資料庫操作層級使用 Transaction，或在更新邏輯上確保強制更新同一 team 的其他 sets 的 `is_default` 屬性。
- **[Risk] 舊有的 Default Set 失去 Default 標記後，依賴其 UUID 的外部系統或書籤失效** → **Mitigation:** 內部 UUID 引用不變，僅有 fallback 行為改變，這屬於預期行為。
- **[Risk] 使用者誤以為切換 Default 會搬移 Test Cases** → **Mitigation:** 在 UI 的切換確認對話框中，明確提示「此操作僅變更未來的預設建立目標，不會移動任何現有的 Test Cases」。