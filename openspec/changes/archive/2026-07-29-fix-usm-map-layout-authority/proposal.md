## Why

部分團隊的 User Story Map（BSD 的 `MRS 新版玩家等级系统`、`ACS 账户和交易系统`、`ACS-AE`，以及 GED 的 `LGS`/`CBS`/`DCS`/`ICS`、UMD 的 `UMD`）在畫布上不是左→右的樹狀，而是**層級往下堆疊、且節點橫豎都互相重疊**。

實測後真因確定，且不在排版演算法：

- 這些地圖的座標由**已刪除的 Lark 匯入工具**寫入——`app/services/lark_usm_import_service.py::_assign_node_positions`（commit `6490719`，2026-07-16 移除）採 `y = base_y + level*100`、`x_spacing = 150`、`start_x = base_x − (n−1)×75`。層級走 Y、兄弟走 X，且步距（150 / 100）小於節點尺寸（200×110），因此橫豎都疊。以 UMD level 4 的 16 個節點驗算 `250 − 15×75 = −875`，與資料庫實測最小 x 完全吻合。全庫 17 張圖中，符合 `position_y == 250 + depth*100` 這個指紋的是 8 張，且**per-map 全有或全無**（8 張 100%、9 張 0%），命中的正好是使用者回報的團隊。
- 這些壞座標永遠不會被修正，因為 `app/static/js/user_story_map.js:1160` 的 `hasSavedLayout` 判準是「所有節點有座標且任一非 0」。而 `create_map` 把 root 寫死在 `(250, 250)`（`app/api/user_story_maps.py:767`），加上 API 以 `n.position_x or 0` 把 NULL 轉成 0，**每一張地圖從建立那一刻起就恆被視為「使用者已手動排版」**，載入時一律不重排（`:1236-1238` 的 `reflowDirectiveRef` 被設為 null）。同一份資料在 popup 是正常的——popup 完全不讀座標、每次現算 dagre（`app/static/js/user_story_map_popup.js:362-391`），這個對照本身就是診斷證據。

同時發現三個會讓修復失效或再度製造災情的既有缺陷：

- 收合／展開的重排明文保留隱藏節點的舊座標（`user_story_map.js:964`、`:3898` 的 anchor 位移排除 `hidden`）。載入時預設收合含 user story 的父節點，因此「只修可見節點」會把兩代座標混在一起；`GPD` 目前 24 個座標點疊了 59 個節點、全部落在合法 dagre 格線上、且每個重合點的 parent 互不相同——正是這個機制留下的指紋。
- `reactflow@11.11` 的 `nodeDragThreshold` 預設為 0（UMD bundle 內 `nodeOrigin:[0,0],nodeDragThreshold:0`），**單擊節點就會觸發 `onNodeDragStop` → `scheduleSave(400)` → 整張圖 PUT**。任何顯示層重排若沒有寫入規則，會在使用者點第一下時被固化。
- `app/services/usm_text_parser.py:316-334` 仍在產生壞座標（`CHILD_HORIZONTAL_OFFSET = 150` < 節點寬 200、`SIBLING_VERTICAL_SPACING = 100` < 節點高 110，且 `level_counters` 不分父節點，同層全部擠成一直欄），與自家 `docs/USM_TEXT_MODE_README.md:297`「不保留精確的 X/Y 座標（需自動佈局）」的說明相反。

另外，收合狀態同步的 effect（`user_story_map.js:3844-3941`）deps 含 `edges`，而 `:3907-3912` 的 `setEdges(eds => eds.map(...))` 必定回傳新陣列 → effect 自我觸發。以 React 18 實測為無界迴圈（保險絲 301 次；移除 deps 中的 `edges` 後為 1 次），production build 無警告，靜默燒 CPU 並每圈重建全部節點物件。

## What Changes

- **載入時的排版權威改為健康度判定**：以「TB 指紋」與「重疊節點比例」取代 `hasSavedLayout`。不健康 → 以樹狀自動排版顯示；輕微重疊 → 只提示不動；健康 → 沿用既有座標。這是本 change 的核心行為變更，**推翻 commit `5700894`「Respect manually-saved node positions on load」的既有決策**，理由是該決策的前提（座標非 0 ⇒ 使用者手排）在 `create_map` 寫死 root 座標後從未成立。
- **重排一律涵蓋整棵樹**：收合狀態下的排版仍讓可見節點緊湊，但隱藏節點的座標必須由同一次排版推導（貼齊最近可見祖先），不得保留上一代座標；anchor 平移套用到所有節點。排版結果必須是 `(tree, collapsedIds)` 的純函式，收合→展開→收合回到相同座標。
- **單一座標框架寫入**：自動重排的結果預設不寫回資料庫（重新整理即回到原狀，天然可逆）。任何一次儲存只能屬於單一座標框架——不得出現「使用者拖的那顆用新框架、其餘用舊框架」。使用者實際拖動節點（位移 > 門檻）或按下新增的「套用此排版」，才把整張圖升級到新框架並一次寫入，寫入前把舊座標留存到稽核記錄。
- **新節點與匯入座標對齊排版格線**：`CHILD_HORIZONTAL_OFFSET` 180 → **275**（節點寬 200 + ranksep 75）、`SIBLING_VERTICAL_SPACING` 140 → **150**（節點高 110 + nodesep 40）；`usm_text_parser` 不再輸出座標（一律 0），讓排版權威單一化到前端排版器。
- **顯示更新的終止性**：修正收合 effect 的自我觸發（`setEdges` 在無變更時回傳同一參考，deps 保留 `edges`）；所有節點祖先走訪加 visited 保護，避免自環父節點造成無窮迴圈。
- 新增純函式模組 `app/static/js/usm-layout.js`（健康度判定、深度計算、隱藏節點座標推導、邊 hidden 狀態計算），可在 Node vm 沙箱測試、不依賴 dagre/React。
- 新增三語系文案（自動重排通知、重疊提示、「套用此排版」按鈕與確認）。
- **無 schema 變更、無 migration、無 API contract 變更。**

## Non-goals

- 不改變 dagre `rankdir: 'LR'` 的排版隱喻（已與使用者確認：乾淨的 LR 樹狀是預期樣貌）。
- 不新增 `layout_mode` 欄位。單一座標框架 + 健康度判定已足夠，加欄位會多出遷移、三引擎、response model、並發覆寫等風險線而不帶來新能力。
- 不動 popup（`user_story_map_popup.js`）與關聯圖 modal：popup 目前完全不讀座標、行為正確，是唯一健康的視圖；本次不抽共用排版模組。
- 不修 `import-text` / `export-text` 缺少 `_require_usm_permission` 的授權漏洞（`app/api/user_story_maps.py:2090`、`:2284`）——這是真實安全問題但與排版症狀無關，另開獨立 change。
- 不收斂 `user_story_maps.nodes/edges` JSON 與 `user_story_map_nodes` 表的雙真相來源、不加 `UNIQUE(map_id, node_id)`、不加 PUT 樂觀鎖、不處理 CDN 無 fallback。全部另案。
- 不改 `usm_text_parser` 的 `node_id` 產生器（毫秒時間戳會碰撞，但正式資料 0 筆重複、0 筆 self-parent，曝險低）。本次只加前端的 visited 防護以免被既有髒資料吊死。

## Capabilities

### Added Capabilities

- `user-story-map-layout`：User Story Map 畫布的排版權威與座標寫入規則——載入時的健康度判定、收合一致的整樹排版、單一座標框架寫入、新節點與匯入的座標來源、顯示更新的終止性。

## Impact

- **前端**：新檔 `app/static/js/usm-layout.js`（純函式）；`app/static/js/user_story_map.js`（載入判定 `:1130-1170`、收合 effect `:3844-3941`、`applyLayoutWithCollapsedNodes` `:924-976`、`saveMap` `:1311-1384`、`onNodeDragStop` `:1441-1456`、`addNode` 常數 `:27-29`、ReactFlow props `:4105-4130`）；`app/templates/user_story_map.html` 增加一個 script 標籤。
- **後端**：`app/services/usm_text_parser.py::_calculate_positions` 停止輸出座標；套用排版時寫一筆含舊座標的稽核記錄。
- **i18n**：`app/static/locales/{en-US,zh-CN,zh-TW}.json` 的 `usm` 命名空間新增 5 個 key（三語系同批）。
- **資料**：不執行任何 data migration。既有壞座標留在資料庫，直到使用者在該張圖明確採用新排版才被覆寫（並留有稽核快照）。
- **既有測試**：`app/testsuite/test_component_spec.py`（`/user-story-map/1` 樣板 smoke）會經過新的 script 標籤；`test_user_story_map_db_access.py`、`test_related_nodes*.py` 不受影響。USM 目前**沒有任何 API 端點測試、沒有前端測試、`usm_text_parser` 沒有測試**，本次新增的測試是從零建立的第一層安全網。
- **風險**：健康度判定是啟發式。以正式站現況 17 張圖實測，判定結果為——自動重排 10 張（8 張 TB 指紋 + GPD 64%、WSD 33%）、只提示 3 張（OPD 11%、TAD 15%、PCD 5%）、沿用 4 張（CRD、USS-SE、USS-AE、Interact Management）。GPD 與 WSD 確實有人工排版痕跡，經使用者確認採「重排」；因為不寫回資料庫，重新整理即回到原狀。
