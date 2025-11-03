# USM 關聯節點功能實作計劃

## 目標與背景
- 讓 USM 節點之間可以建立跨層級、跨地圖的關聯，並在視覺化呈現與操作流程上提供一致體驗。
- 提供搜尋與選擇介面協助使用者快速建立關聯，並支援後續的高亮與完整相關圖分析。

## 功能需求拆解與對應策略
1. **related_ids 紀錄關聯**：把 `related_ids` 升級為可儲存物件的結構（保留向下相容字串 ID），內容包含 `relation_id`、`target_node_id`、`target_map_id`、`target_team_id`、顯示名稱等。新增儲存面邏輯同時更新當前節點與目標節點。
2. **跨 USM 關聯**：`related_ids` 物件化後可以攜帶 map/team 等資訊。後端提供跨地圖節點查詢與權限驗證，前端把結果帶入關聯設定程序。
3. **USM Toolbar 新增按鈕**：在「新增同級節點」右側放置「設定關聯」按鈕，控制 Modal 開啟並要求先選擇節點。
4. **關聯設定 Modal**：新增 Bootstrap Modal，內含目前節點資訊、搜尋輸入、結果列表、已選清單及儲存按鈕。
5. **搜尋介面與跨圖選項**：Modal 中提供查詢欄位、節點類型過濾、是否搜尋外部地圖的切換。呼叫新的 `/api/user-story-maps/search-nodes` API；若勾選跨圖，加入 team/map 範圍參數。
6. **節點屬性顯示關聯**：在側欄節點屬性加入「關聯節點」區塊，列出「團隊名稱 / USM 名稱 / 節點名稱」，並支援點擊後聚焦對應節點（同圖直接聚焦、跨圖開啟確認提示後切換地圖）。
7. **高亮路徑擴充**：既有 `highlightPath` 內部已有 `relatedSameMap` 結構，強化邏輯：
   - 將同圖關聯節點加入高亮集合。
   - 透過新增 `relatedEdges` 狀態繪製虛線（`type: 'default'`, 自訂 `strokeDasharray`）。
8. **新增「節點完整相關圖」**：在「高亮路徑」右側放置新按鈕，開啟後呼叫 `showNodeRelationGraph`，並以專用 Modal 呈現：
   - 結合高亮路徑節點 + 全部關聯節點（同圖與跨圖）。
   - 同圖節點維持 React Flow 呈現；跨圖節點以摘要卡片顯示於 Modal 或側邊資訊區，標示團隊/USM。
9. **標示來源資訊**：在高亮與完整相關圖中，於節點標籤或提示文字顯示 `team_name + map_name`，供使用者辨識。

## 系統設計概述

### 權限實作要求
- 所有與 USM 關聯節點相關的 API（例如查詢、建立、刪除關聯、跨圖搜尋）都必須整合既有的 RBAC 與團隊層級權限檢查，確保 `viewer` 角色僅能讀取。
- 前端在套用 UI 能力時需遵循 `permission_service.get_ui_config` 回傳的設定，並在操作流程中再次檢查，以避免使用者繞過 UI 限制。
- 後端在資料庫層面需以 `_require_usm_permission` 或等效機制保護每一條路徑，並為跨圖行為加入目標地圖/團隊權限驗證，避免資料洩漏或越權編輯。
- 新增單元測試與整合測試覆蓋 Viewer/User/Admin 角色的正反案例，確保權限矩陣變動時能快速發現回歸。

### 資料模型
- **前端**：`node.data.relatedIds` 改為陣列物件 `{ relationId, nodeId, mapId, mapName, teamId, teamName, displayTitle }`。
- **後端**：
  - 更新 `UserStoryMapNode.related_ids` 與 `UserStoryMapNodeDB.related_ids` 的序列化邏輯，讀寫時做向下相容。
  - 更新 `/user-story-maps/{map_id}` 讀寫流程，確保 `related_ids` 物件化後存回 sqlite JSON 欄位。
  - 新增關聯維護 API（例如 `/user-story-maps/{map_id}/nodes/{node_id}/relations`）。
  - 新增跨圖搜尋 API：支援依關鍵字、節點類型、團隊、USM 名稱等查詢，回傳必要欄位。

### 前端 React Flow 邏輯
- **狀態管理**：
  - `useState` 新增 `relatedEdges` 或在 `edges` 中標記 `relation` 類型。
  - 透過 `setEdges` 在儲存/載入時建立虛線邊（只針對同圖節點）。
- **操作流程**：
  1. 使用者選取節點 → 點擊「設定關聯」。
  2. Modal 載入目前節點的關聯清單並顯示搜尋結果。
  3. 使用者搜尋並選擇目標節點，支援多選。
  4. 點擊儲存後呼叫後端 API，成功後刷新地圖資料或局部更新節點與邊、呼叫 `saveMap(true)`。
- **UI 調整**：
  - Toolbar 新增按鈕及 tooltip。
  - Modal 內容包含：搜尋輸入、節點類型下拉、跨圖切換、結果列表（顯示 team/map/node）、已選列表、確認與取消。
  - 側欄顯示關聯節點資訊，可透過 `focusNode` 或觸發跨圖開啟流程。
- **高亮與完整相關圖**：
  - `highlightPath` 擴充：同圖關聯節點加入高亮集合並同步邊樣式；跨圖關聯節點顯示於 `highlightInfo` 區塊。
  - 新增 `showFullRelationGraph` 函式（控制專用 Modal 顯示）：
    * 組合高亮路徑節點 + 全關聯節點資料。
    * 更新節點 `badge` 或 tooltip 顯示 `team/map`。
    * 專用 Modal 內展示跨圖節點清單與摘要資訊。

### 後端 API 調整
- **關聯維護**：
  - `POST/DELETE` 端點管理節點間關聯，確保雙向同步與權限檢查（只能關聯同團隊或有權限的 map）。
  - 更新 `update_map` 流程，於儲存時同步 `UserStoryMapNodeDB.related_ids`。
- **搜尋服務**：
  - 新增 `search_nodes_global` API，可接受 `include_external=true`；若為 false 時僅限當前 map。
  - 回傳欄位：`map_id`, `map_name`, `team_id`, `team_name`, `node_id`, `node_title`, `breadcrumb`（optional）。
- **資料一致性**：
  - 建議建立唯一 `relation_id`（UUID），方便刪除時辨識。
  - `UserStoryMapNodeDB` 更新欄位時，同步儲存序列化後的物件。

## 互動流程摘要
1. 使用者選擇節點 → 按「設定關聯」。
2. Modal 開啟，顯示現有關聯與搜尋介面。
3. 輸入關鍵字並選擇是否搜尋外部地圖。
4. 從結果中挑選目標節點後儲存 → 前端呼叫 API 建立關聯。
5. 同圖節點立即建立虛線連線並儲存；跨圖節點紀錄於 `related_ids`，在屬性面板與 highlight 介面中呈現。
6. 「高亮路徑」與「節點完整相關圖」會同步顯示同圖關聯的虛線及跨圖資訊。

## 風險與後續考量
- SQLite JSON 欄位的舊資料需向下相容（仍可能是單純字串 ID）。
- 跨圖關聯涉及權限檢查，需要確認使用者是否對目標 map 有存取權。
- React Flow 邊數量增加時，需評估效能（預計節點數 < 200 時可接受）。
- 若將來需要視覺化跨圖節點，可能要引入多地圖並呈或另開視圖，此次先以資訊面呈現。
- 測試需涵蓋：建立/移除同圖與跨圖關聯、儲存後重新載入資料、highlight 兩種模式、跨圖資訊呈現。

---
此計劃完成後再依此實作前後端改動與測試項目。
