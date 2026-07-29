# 設計決策

## 1. 為什麼是「健康度判定」而不是 `layout_mode` 欄位

三個方案被實際比較過：

| 方案 | 效果 | 否決理由 |
|---|---|---|
| `layout_mode`（'auto' / 'manual'）欄位 | 意圖明確、可查詢 | 需要 alembic_usm migration、三引擎驗證、response model 相容（`UserStoryMapResponse` 欄位皆必填，NULL 會 500）、`--adopt-legacy-usm-db` 會因 model/schema diff 直接 exit 4、`database_init.py` 的升版自動備份目前是停用狀態。**而且核心問題（整包 PUT 帶座標、沒有 per-field 寫入）加了欄位也不會消失。** |
| 座標全部歸零 | 最簡單，直接讓現行判準失效 | 不可逆；且任何人拖一下就又鎖死 |
| 在既有 JSON 欄位塞 layout 版本號 | 免 migration | `nodes`/`edges` 是陣列、沒有 map 級 metadata 位置；會被 PUT / move-node / import-text 三處整包覆寫，變成第三個不同步點 |

選定：**健康度判定 + 單一座標框架**。零 schema 變更、零遷移風險，且因為預設不寫回，重新整理即回到資料庫原狀——可逆性比加欄位更強。

## 2. 判定式為什麼長這樣

判定在載入時對「資料庫來的座標」計算，節點盒以 200×110 計（與 CSS `.custom-node` 及 `g.setNode(…, {width:200,height:110})` 一致）：

- **TB 指紋**：節點數 ≥ 3、樹深 ≥ 2，且 ≥90% 的節點滿足 `position_y == 250 + depth*100`（容差 0.01）。
  - depth **由 parent_id 鏈計算**，不採信 `level` 欄位——`level` 是前端送什麼存什麼（`saveMap` 送 `node.data.level || 0`），WSD 已有 2 筆與實際深度不符。
  - 用 90% 而非 100%：避免「有人拖過一個節點」就讓整條規則失效。實測全庫 8 張命中圖是 100%、9 張健康圖是 0%，安全邊際極大。
- **重疊比例**：涉入至少一次 bbox 重疊（`|dx| < 200 且 |dy| < 110`）的節點數 ÷ 總節點數。
  - **≥ 20% → 不健康（自動重排）**；`0 < x < 20% → 只提示`；`0 → 沿用`。
  - 不用「重疊配對數 > 0」：那會命中 PCD（4 個節點 / 75）、OPD（11%）、TAD（15%）這些 95% 完好的手排圖，把人家的排版整張換掉。
- 兩條是 OR。

以正式站現況（`userstorymap.db`，經使用者確認等同正式站）逐圖驗證結果見 `tasks.md` 的驗收基準表。

## 3. 為什麼「重排必須涵蓋隱藏節點」不是潔癖

載入時預設收合含 user story 子節點的父節點（`user_story_map.js:1222-1232`），而 `applyLayoutWithCollapsedNodes:964-975` 明文「保持隱藏節點的原始位置」、`:3898` 的 anchor 平移也只套用非隱藏節點。若只重排可見節點，畫面乾淨但資料是「可見＝新框架、隱藏＝TB 舊框架」的混合體；使用者接著點一下節點（`nodeDragThreshold` 預設 0）就會把混合體 PUT 回資料庫。**GPD 現在的 24 個重合點就是這個機制的產物**——修復本身會製造出它要修的損傷。

可行形狀只有一種：dagre 只餵可見節點（保持緊湊），隱藏節點的座標由同一次結果推導——貼齊最近可見祖先的槽位加上固定偏移。推導出的隱藏節點彼此會疊在一起，這是刻意的，且因此**「套用此排版」必須先強制展開全部節點再計算與寫入**，否則寫進去的狀態會立刻被下一次健康度判定判成不健康，形成永遠重排的迴圈。

排版另需為 `(tree, collapsedIds)` 的純函式：現行 anchor 的 `dx/dy` 是相對「前一個狀態」算的，路徑相依，收合→展開→收合會漂移，也讓 golden test 不可能穩定。

## 4. 單一座標框架的狀態機

每次載入建立一個 session 級狀態：

```
frame = 'db'          // 判定健康：畫面 = DB 座標
frame = 'recomputed'  // 判定不健康：畫面 = 重排座標，DB 仍是舊座標
```

- `frame == 'db'`：行為與現況相同，儲存送畫面座標。
- `frame == 'recomputed'`：
  - 未升級前，`saveMap` 送出的座標一律取自**載入時的影子副本**（DB 原值），使標題／屬性／關聯等非座標編輯可以正常存檔而不污染座標。
  - 升級（promote）只有兩個入口：① 使用者真的拖動節點（`dragStart` 與 `dragStop` 座標不同，且 `nodeDragThreshold` 設為 3）；② 按下「套用此排版」。
  - 升級後 `frame` 轉為 `'db'`，該次儲存整張送出畫面座標——**永遠是單一框架**。
  - 升級需要 `mapUpdate` 權限；無權限者不升級、不寫入（並把 `nodesDraggable` 接上權限，避免 viewer 拖出無法儲存的畫面）。

影子副本的生命週期定義（每個都必須有明確答案，否則會錯配）：

| 事件 | 影子副本 |
|---|---|
| `loadMap` 成功且通過 requestId 守門（`:1040`） | 以本次回應重建；`frame` 依判定設定 |
| 切換地圖 | 連同 `frame` 一併重設 |
| 新增節點 | 新節點沒有 DB 原值 → 影子登記為「無」，儲存時送畫面座標（單一節點的新座標本來就屬於新資料，不構成混框） |
| 刪除節點 | 從影子移除 |
| `performMoveNode` 後的 `loadMap(reflowAnchor)` | 走 loadMap 路徑重建；搬移後的視覺整理若未 promote 就不落地（既有行為即如此） |
| text import 後重載 | 走 loadMap 路徑重建 |
| 過期回應 | requestId 守門之後才寫，避免舊圖座標蓋掉影子 |

## 5. 收合 effect 自我觸發的修法（兩個變體實測過）

| 變體 | 掛載後 effect 次數 | 後續插入的 relation 邊是否拿到 `hidden` |
|---|---|---|
| 現況（deps 含 `edges` + 每次新陣列） | 無界（保險絲 301） | 會 |
| 改用 `edgesRef`、deps 拿掉 `edges` | 1 | **不會**（`applyHighlight` 於 `:2449` 動態插入的 relation 邊建立時沒有 `hidden` 欄位，今天完全靠這個 effect 補上） |
| **保留 deps，`setEdges` 在無變更時回傳同一參考** | 2（收斂） | 會 |

採第三種。第二種是漏更新，實測已否決。

## 6. 座標格線常數

以健康圖實測反推（`map 2 / 27 / 37`）：**x pitch 275、y pitch 150**，對應 `ranksep 75 + 節點寬 200`、`nodesep 40 + 節點高 110`（dagre 在 `rankdir:'LR'` 會先交換寬高再排，最後交換 XY，所以 ranksep 是水平欄距、nodesep 是同欄垂直間距）。

因此 `addNode` 的位移必須是 **275 / 150**。先前提過的 280/140 是錯的：280 會造出新的 off-grid 欄（等同現在 map 3/6/29 各有一個的 `x=555` 節點），140 會讓每多一個兄弟就累積 10px 偏移。

`ranksep`/`nodesep` 本身維持 75/40 不動——它們不是本次的槓桿，改動會讓格線位移並使既有座標與新座標混不到一起。

## 7. 測試策略：不要測 dagre

`dagre` 只從 CDN 載入、不在 `node_modules`，而「排完不重疊」是 dagre 的性質不是本專案的。因此把可測的邏輯全部放進 `usm-layout.js` 純函式（健康度判定、深度計算、隱藏節點推導、邊 hidden 計算、參考相等性），用既有 `app/testsuite/js/*.test.mjs` 的 vm 沙箱做法測；dagre 的呼叫留在 `user_story_map.js`，以固定輸入的 fake 驗證前後處理即可。
