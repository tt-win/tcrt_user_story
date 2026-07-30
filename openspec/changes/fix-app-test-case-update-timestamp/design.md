## Context

`TestCaseLocal.updated_at` 是應用程式維護的欄位，ORM column 沒有 `onupdate`。JWT 單筆更新與共用批次更新核心會顯式刷新時間戳，但 App Token generic `PUT` 只指派欄位後 flush，導致相同業務 mutation 因入口不同而有不同結果。團隊 Test Case trend 直接以目前 row 的 `updated_at` 分組，因此遺漏的時間戳會讓 API／`tcrt-app` skill 更新停留在舊日期。

## Goals / Non-Goals

**Goals:**

- 讓 App Token generic update 在至少一個持久化欄位實際改變時，於同一 main DB transaction 刷新 `updated_at`。
- 讓空 payload、同值重送、validation failure 與被拒絕的 cross-Set update 保持原時間戳。
- 以隔離資料庫回歸測試證明 API 更新與既有 `Updated` 統計查詢可組合運作。

**Non-Goals:**

- 不把 `Updated` 改成 audit event count；它仍是依目前 row 最後更新日計算的案例數。
- 不修改 batch update、guarded Set move、attachment endpoint 或 JWT route。
- 不新增 ORM-wide `onupdate`、DB trigger、schema migration 或歷史資料回填。
- 不觸發 Lark 或其他外部 Test Case 同步。

## Decisions

### 1. 在 App Token generic update route 顯式維護時間戳

Route 在完成 team／Set／Section 驗證與欄位正規化後，比較 mutation 前後的持久化值。若至少一個值實際不同，於同一 transaction、flush 前設定 `updated_at = datetime.utcnow()`；時間戳與內容因此一起 commit 或一起 rollback。

替代方案是為 ORM column 加 `onupdate` 或 DB trigger。該做法會改變所有寫入來源、需要跨 SQLite／MySQL／PostgreSQL 驗證，且超出本次只修正 App Token generic update 的範圍，因此不採用。

### 2. Effective no-op 不刷新時間戳

更新判斷以持久化後的語意值為準：scalar／Enum 比較其 canonical value，TCG 與 test data 比較正規化後要保存的 JSON 內容，同 Set／Section 重送比較既有 id。只有實際差異才刷新時間戳。

替代方案是在每次成功 PUT（包含空 payload或同值重送）無條件刷新。這會把 retry／read-modify-write no-op 計入更新日期並使 `Updated` 統計膨脹，因此不採用。

### 3. 回歸測試控制初始時間並驗證統計可見性

測試使用 disposable DB，先把案例的 `created_at` 與 `updated_at` 固定為相同的舊時間，再透過 App Token 更新內容。測試 SHALL 驗證內容與 `updated_at` 一起改變，並以既有 team statistics endpoint 驗證該案例進入更新統計；另驗證同值重送不再次推進時間戳。

## Risks / Trade-offs

- [JSON 表示不同但語意相同可能被誤判為更新] → 比較正規化資料結構或 canonical serialization，而不是任意原始 JSON 字串。
- [DB 時間精度造成 flaky assertion] → 測試使用固定的舊 baseline，只斷言新時間大於 baseline，不依賴短暫 sleep。
- [只修正單一路徑，其他 mutation 仍可能有既有差異] → 以 proposal 的 non-goal 明確限縮；後續若要建立全域 timestamp invariant，另開 change 盤點所有 endpoint。

## Migration Plan

1. 加入 route-level change detection 與 timestamp assignment。
2. 執行 focused App Token／statistics tests，以及專案既有 gates。
3. 部署不需 migration；後續有效更新自然刷新時間戳，不回填歷史資料。
4. 回退時還原 route 邏輯即可；已刷新時間戳保留為有效歷史，不執行破壞性資料回復。

## Open Questions

無。
