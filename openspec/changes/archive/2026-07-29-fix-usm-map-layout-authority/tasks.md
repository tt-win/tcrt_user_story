> 實作順序即為本檔順序。第 1～2 節是純函式與純 bug 修復，可獨立驗證；第 3～5 節才改變使用者可見行為，**第 3、4、5 節必須同一次發版**（只做第 3 節而缺第 5 節，會讓自動排版在使用者點第一下時被固化成混合座標）。

## 0. 前置與基準

- [x] 0.1 取一份可拋棄的 `userstorymap.db` 副本作為驗證環境（禁止對正式資料庫做任何寫入驗證）；本 change 全程不需要 schema 變更、不需要 migration
- [x] 0.2 在副本上跑一次基準量測腳本，輸出每張地圖的：節點數、TB 指紋比例（`position_y == 250 + depth*100`，depth 由 `parent_id` 鏈推導）、重疊節點比例（節點盒 200×110）、完全重合座標點數、x/y 步距、y 跨度。結果須與下方 §9.1 的驗收基準表一致；不一致代表資料已變動，需重新確認基準
- [x] 0.3 確認節點實際佔位為 200×110：`app/static/css/user-story-map.css:15-23`（`width:200px; min-height/max-height:110px`）＋ Bootstrap 的 `box-sizing:border-box`，與 `user_story_map.js:885`／`:949` 的 `g.setNode(…, {width:200, height:110})` 一致。三處常數目前各自維護，實作時集中為單一來源
- [x] 0.4 確認格線常數：健康圖實測 x pitch = 275（節點寬 200 + `ranksep` 75）、y pitch = 150（節點高 110 + `nodesep` 40）。`ranksep`/`nodesep` 本次**不得更動**

## 1. 純函式模組 `app/static/js/usm-layout.js`

新檔，不依賴 dagre / React / DOM，掛在 `window.UsmLayout`，可由 Node vm 沙箱載入測試。

- [x] 1.1 `computeDepths(nodes)`：由 `parent_id` 鏈推導每個節點深度；使用 visited set，遇自環／循環／指向不存在的父節點時終止並記為深度 0；回傳 `Map<nodeId, depth>` 與 `{orphanIds, cyclicIds}`
- [x] 1.2 `assessLayoutHealth(nodes, options)`：回傳 `{verdict: 'healthy' | 'hint' | 'unhealthy', reasons: string[], overlapRatio, overlapNodeCount, tbRatio}`
  - TB 指紋：`nodes.length >= 3` 且樹深 ≥ 2 且 `tbRatio >= 0.9`，其中 `tbRatio` = 滿足 `|position_y − (250 + depth*100)| < 0.01` 的節點比例
  - 重疊比例：涉入至少一次 `|Δx| < 200 && |Δy| < 110` 的節點數 ÷ 總節點數
  - `unhealthy` = TB 指紋成立 **或** `overlapRatio >= 0.20`；`hint` = `0 < overlapRatio < 0.20`；其餘 `healthy`
  - `options` 可覆寫 `nodeWidth / nodeHeight / tbBaseY / tbStep / overlapThreshold`，預設 `200 / 110 / 250 / 100 / 0.20`
- [x] 1.3 `deriveHiddenPositions(layoutedVisible, allNodes, collapsedIds)`：為每個隱藏節點指派座標＝其最近可見祖先的座標（可加固定微小偏移以利除錯）；輸出必須只相依於 `(樹結構, collapsedIds)`，不得參考節點原有座標
- [x] 1.4 `translateAll(nodes, dx, dy)`：對**所有**節點（含 `hidden`）套用平移，取代 `user_story_map.js:3898` 目前只平移非隱藏節點的寫法
- [x] 1.5 `nextEdgeHiddenState(edges, hiddenStatus)`：計算每條邊的 `hidden`；**若所有邊的 `hidden` 都沒有變化，MUST 回傳傳入的同一個陣列參考**（這是第 2.1 項收斂的關鍵）
- [x] 1.6 `app/templates/user_story_map.html`：在 `{% block scripts %}` 內、`{{ asset_url('js/user_story_map.js') }}`（`:982`）之前加入 `<script src="{{ asset_url('js/usm-layout.js') }}"></script>`；popup 樣板不動
- [x] 1.7 `node --check app/static/js/usm-layout.js` 通過

## 2. 顯示更新的終止性與結構防護（純 bug 修復，無行為變更）

- [x] 2.1 修正收合 effect 自我觸發：`user_story_map.js:3907-3912` 改用 `UsmLayout.nextEdgeHiddenState`，無變化時 `setEdges` 收到同一參考；**deps（`:3941`）保留 `edges`**
  - 已實測否決的替代方案：把 deps 改成 `edgesRef` 雖然也只跑 1 次，但 `applyHighlight`（`:2449`）動態插入的 relation 邊建立時沒有 `hidden` 欄位，改 ref 後永遠拿不到 → 漏更新
- [x] 2.2 `shouldHide`（`:3853-3862`）、`applyLayoutWithCollapsedNodes` 的可見性判定（`:937-944`）、`countDescendants`（`deleteNode` 內）三處 `while (parentId)` / stack 走訪改為使用 `UsmLayout.computeDepths` 的結果或自帶 visited set
- [x] 2.3 把 `:942`（filter 內 find）、`:954-955`（每條邊 some）、`:965`（`visibleNodes.includes`）、`:1224-1231`（收合預設計算內的 find）改為 `Map`/`Set` 查表
- [x] 2.4 瀏覽器手動驗證：在 `:3844` 開頭暫時加計數 log，開啟 346 節點的地圖靜置 5 秒，effect 執行次數應為個位數（修正前為無界）

## 3. 載入時的排版權威

- [x] 3.1 `loadMap`（`:1030-1261`）：以 `UsmLayout.assessLayoutHealth(map.nodes)` 取代 `hasSavedLayout`（`:1160-1163`）
  - `healthy` → 沿用 DB 座標（現行行為）
  - `hint` → 沿用 DB 座標 + 顯示可關閉提示（含觸發自動排版的入口）
  - `unhealthy` → 以自動排版取代顯示座標 + 顯示「已改用自動排版顯示、尚未寫入」通知
- [x] 3.2 移除已成死碼的 `computeLayout` fallback（`:1133-1157`）——`create_map` 把 root 寫死 `(250,250)`（`app/api/user_story_maps.py:767`）且 API 以 `or 0` 消除 NULL，該分支自始不可達；改由 3.1 的判定統一入口
- [x] 3.3 送進排版的邊必須先清理：把 `:1176-1179` 的「濾掉指向不存在節點的邊」與 `:1181-1209` 的「全空時由 parent/related 重建」當作**一組整體**移到排版之前。只搬過濾而不搬重建，會讓邊集為空的地圖全部落在 rank 0 → 單一直欄，等於親手製造要修的症狀
- [x] 3.4 排版只使用 parent 邊（`edge_type === 'parent'`），關聯邊不參與 rank 計算；**主視窗適用，popup 不動**
- [x] 3.5 `reflowDirectiveRef`（`:1235-1237`）語意調整：`unhealthy` 時載入即重排並 `fitView`；`healthy`/`hint` 維持現行不重排、僅框景
- [x] 3.6 確認與 `focusNode`（`:3505-3529`、`:3593-3599` 的 100ms `setTimeout`）無競態：重排完成後才執行聚焦，避免 `setCenter` 使用重排前座標
- [x] 3.7 修正 `findReparentTarget`（`:1411-1422`）與 `focusNode setCenter`（`:3524-3529`）的座標語意：dagre 回傳中心座標而 React Flow 的 `position` 是左上角，目前兩處命中判定偏 (100, 55)。排版輸出統一轉為左上角（`x − 100`, `y − 55`）

## 4. 收合狀態下的整樹一致排版

- [x] 4.1 `applyLayoutWithCollapsedNodes`（`:924-976`）：可見節點照舊只餵 dagre（保持緊湊），隱藏節點改由 `UsmLayout.deriveHiddenPositions` 推導；**刪除 `:974` 的「保持隱藏節點的原始位置」**
- [x] 4.2 `:3895-3899` 的 anchor 平移改用 `UsmLayout.translateAll`，套用到所有節點（含 `hidden`）
- [x] 4.3 確認排版為 `(樹結構, collapsedIds)` 的純函式：移除對「前一狀態座標」的相依，使收合→展開→收合回到相同座標
- [x] 4.4 `autoLayout`（`:3603-3614`）改用收合感知版本；**不加 `scheduleSave`**（`app/static/js/user-story-map-inline.js:75` 會在切回視覺化 tab 時呼叫它，加了等於切 tab 就整張 PUT）
- [x] 4.5 修正 `autoLayout` 的權限判斷不一致：按鈕顯示看 `nodeUpdate`（`:77`）、handler 卻檢查 `nodeAdd`（`:3604`、`:4758`）。統一為顯示與執行看 `nodeUpdate`、寫入看 `mapUpdate`
- [x] 4.6 `user-story-map-inline.js:75` 的 tab 切換路徑改呼叫 silent 版本（不彈權限錯誤 toast）——目前唯讀使用者每次切回視覺化 tab 都會吃一個錯誤訊息

## 5. 單一座標框架寫入

- [x] 5.1 在 `loadMap` 的 requestId 守門（`:1040`）之後建立影子副本 `originalPositionsRef: Map<nodeId, {x, y}>` 與 `layoutFrameRef: 'db' | 'recomputed'`；切換地圖時一併重設
- [x] 5.2 `saveMap`（`:1327-1345`）：`layoutFrameRef === 'recomputed'` 時，`position_x/position_y` 一律取自影子副本；新增節點（影子中沒有的 id）送畫面座標；刪除節點同步從影子移除
- [x] 5.3 框架升級（promote）：`layoutFrameRef` 轉為 `'db'`、影子副本以畫面座標重建，之後儲存整張送畫面座標。入口只有兩個：
  - `onNodeDragStop`（`:1441-1456`）且 `dragStart` 與 `dragStop` 座標**確實不同**
  - 「套用此排版」按鈕
- [x] 5.4 ReactFlow props（`:4105-4130`）加 `nodeDragThreshold: 3`；`reactflow@11.11` 預設為 0，單擊即觸發 `onNodeDragStop` → `scheduleSave(400)`（今天每點一次節點就發一次整張 PUT）
- [x] 5.5 `nodesDraggable`（`:4120`）接上權限：`!moveMode && hasUsmAccess('mapUpdate')`；無權限者不得拖出無法儲存的畫面
- [x] 5.6 `saveMap` 的 `mapUpdate` 檢查在 `silent = true` 時目前靜默 return（`:1312-1317`）；改為至少提示一次，避免使用者以為已存檔
- [x] 5.7 新增「套用此排版」按鈕（`app/templates/user_story_map.html` 工具列，與 `autoLayoutBtn` 同群組，顯示條件 `mapUpdate`）：
  - 按下後先確認（顯示將覆寫已儲存座標）
  - **強制展開全部節點**後再計算與寫入——否則寫入的是「隱藏節點互疊」的狀態，會立刻被下一次健康度判定判成不健康，形成永遠重排的迴圈
  - 寫入前把被覆寫的節點座標（`node_id / position_x / position_y`）寫入稽核記錄
- [x] 5.8 確認稽核記錄可容納最大地圖（346 節點）的座標快照；若欄位長度不足，改存摘要（節點數、判定結果、前後 bounding box）並在 change 內註明

## 6. 新節點與文字匯入的座標來源

- [x] 6.1 `user_story_map.js:27-29`：`CHILD_HORIZONTAL_OFFSET` 180 → **275**、`SIBLING_VERTICAL_SPACING` 140 → **150**（對齊實測格線；280/140 會造出新的 off-grid 欄並讓兄弟間距每次累積 10px 偏移）
- [x] 6.2 `ROOT_START_X/Y`（`:26-27`，目前 100/100）與 `create_map` 的 root `(250, 250)`（`app/api/user_story_maps.py:767-768`）不一致，統一為同一組常數
- [x] 6.3 `app/services/usm_text_parser.py:316-334`：`_calculate_positions` 不再輸出座標，所有節點 `position_x = position_y = 0`（函式可保留為 no-op 或移除呼叫點 `:96`）
  - 現行 `CHILD_HORIZONTAL_OFFSET = 150` < 節點寬 200、`SIBLING_VERTICAL_SPACING = 100` < 節點高 110，且 `level_counters` 不分父節點（同層全部擠成一直欄往下），是唯一還活著的壞座標產生器
  - 改完後行為才與 `docs/USM_TEXT_MODE_README.md:297`、`docs/USM_TEXT_FORMAT_SPEC.md:240-241` 的既有說明一致
- [x] 6.4 確認全 0 座標的地圖在 3.1 的判定下走 `unhealthy`（重疊比例 100%）→ 匯入後自動以樹狀排版顯示

## 7. i18n（三語系同批，缺一即未完成）

- [x] 7.1 `app/static/locales/{en-US,zh-CN,zh-TW}.json` 的 `usm` 命名空間新增：
  - `layoutAutoRelayoutNotice`：此地圖的已儲存座標不正確，目前以自動排版顯示（尚未寫入）
  - `layoutOverlapHint`：偵測到 `{count}` 個節點位置重疊，可套用自動排版整理（帶參數，需用 `data-i18n-params`）
  - `applyLayoutBtn`：套用此排版
  - `applyLayoutConfirm`：將以目前排版覆寫已儲存座標，舊座標會保留在稽核記錄。要繼續嗎？
  - `applyLayoutDone`：排版已儲存
- [x] 7.2 動態插入的通知／提示使用既有 i18n lifecycle（`data-i18n` / `data-i18n-params`，必要時 `window.i18n.retranslate(...)`），不得硬寫字串
- [x] 7.3 `node scripts/check-i18n-coverage.mjs` 零警告

## 8. 測試

- [x] 8.1 新增 `app/testsuite/js/usm-layout.test.mjs`（比照 `app/testsuite/js/version-checker.test.mjs` 的 vm 沙箱做法，不需要 dagre／React）：
  - `computeDepths`：正常樹、orphan parent、自環父、循環父子 → 皆終止且結果正確
  - `assessLayoutHealth`：TB 指紋 fixture（100% 與 90% 兩種）→ `unhealthy`；健康 dagre 格線 fixture → `healthy`；5% / 15% 重疊 → `hint`；25% 重疊 → `unhealthy`；單一 root 的新地圖 → `healthy`（節點數 < 3 的守門）；全 0 座標 → `unhealthy`
  - `deriveHiddenPositions`：隱藏節點貼齊最近可見祖先；同輸入同輸出；不參考節點原座標
  - `translateAll`：隱藏節點同樣被平移
  - `nextEdgeHiddenState`：無變化時回傳**同一參考**（`assert.strictEqual`）；有變化時回傳新陣列且內容正確
- [x] 8.2 新增 `app/testsuite/test_usm_text_parser_positions.py`：解析後所有節點 `position_x == 0 and position_y == 0`；`convert_usm_nodes_to_db_format` 輸出同樣為 0
- [x] 8.3 以 §9.1 的 17 張地圖座標建立 fixture，對 `assessLayoutHealth` 做參數化回歸，斷言每張圖的 verdict 與基準表一致（這是防止判定式日後被誤調的鎖）
- [x] 8.4 手動驗證清單（在 §0.1 的資料庫副本上，逐張開啟）：
  - MRS / ACS / ACS-AE（BSD）→ 由層級往下堆疊變成左右樹狀，且顯示自動排版通知
  - USS-SE / USS-AE（BSD）→ 畫面與修改前完全相同、無通知
  - GPD / WSD → 自動重排；重新整理後資料庫座標未變
  - OPD / TAD / PCD → 沿用既有座標，只顯示重疊提示
  - 任一張圖：點一下節點 → 不寫入；拖動節點 → 整張以新框架寫入
  - 唯讀角色開啟 MRS → 看得到正確排版、無法拖動、無寫入
  - 收合→展開→收合 → 座標回到原位
  - 文字匯入一份不含座標的內容 → 自動以樹狀排版顯示

## 9. 驗收基準與 gates

- [x] 9.1 判定結果須與下表完全一致（座標取自正式站等同資料，2026-07-29 量測）：

  | map | team | 名稱 | 節點 | TB | 重疊節點% | 預期判定 |
  |---|---|---|---|---|---|---|
  | 33 | BSD | MRS 新版玩家等级系统 | 40 | 100% | 100% | 重排 |
  | 36 | BSD | ACS 账户和交易系统 | 58 | 100% | 100% | 重排 |
  | 38 | BSD | ACS-AE | 5 | 100% | 100% | 重排 |
  | 35 | BSD | USS-SE 用户登入系统 | 35 | 0 | 0% | 沿用 |
  | 37 | BSD | USS-AE 用户信息管理 | 148 | 0 | 0% | 沿用 |
  | 1 | UMD | UMD | 53 | 100% | 100% | 重排 |
  | 7 | GED | LGS | 6 | 100% | 100% | 重排 |
  | 8 | GED | CBS | 263 | 100% | 100% | 重排 |
  | 9 | GED | DCS | 2 | 100% | 100% | 重排（節點數 < 3，由重疊比例命中） |
  | 10 | GED | ICS | 154 | 100% | 100% | 重排 |
  | 3 | CID | GPD | 122 | 0 | 64% | 重排 |
  | 29 | WSD | WSD 相关测试 | 346 | 0 | 33% | 重排 |
  | 6 | DPD | OPD | 163 | 0 | 11% | 提示 |
  | 27 | PAD | TAD | 240 | 0 | 15% | 提示 |
  | 23 | PED | PCD | 75 | 0 | 5% | 提示 |
  | 2 | CRD | CRD | 63 | 0 | 0% | 沿用 |
  | 26 | NCD/CCD | Interact Management | 1 | 0 | 0% | 沿用 |

- [x] 9.2 `uv run ruff check app/services/usm_text_parser.py app/testsuite/test_usm_text_parser_positions.py`，再跑 `uv run ruff check .`，零診斷、不得新增 `# noqa`
- [x] 9.3 `uv run pytest app/testsuite/test_usm_text_parser_positions.py app/testsuite/test_user_story_map_db_access.py app/testsuite/test_component_spec.py -q`
- [x] 9.4 `node --check app/static/js/usm-layout.js`、`node --check app/static/js/user_story_map.js`、`node app/testsuite/js/usm-layout.test.mjs`
- [x] 9.5 `npm run lint`、`node scripts/check-i18n-coverage.mjs`
- [x] 9.6 `openspec validate fix-usm-map-layout-authority --strict`
- [x] 9.7 更新 `openspec/project.md` 的能力清單（若需要），並確認 `docs/USM_TEXT_MODE_README.md` 與實作一致

## 10. 上線與回滾

- [x] 10.1 第 3、4、5 節必須同一次發版；只上第 3 節而缺第 5 節會讓重排結果在使用者點第一下時被固化成混合座標
- [x] 10.2 回滾方式：revert 該 commit 即可。本 change 無 schema 變更、無 data migration，資料庫座標在使用者按下「套用此排版」或實際拖動節點之前完全不會被改寫
- [x] 10.3 上線後對正式站重跑 §0.2 的基準量測，確認未發生非預期的座標改寫
- [x] 10.4 通知 BSD／GED／UMD：在此之前的臨時解是按工具列的「展開全部節點」（無權限限制、會觸發一次乾淨重排、不寫資料庫）
