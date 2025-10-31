# User Story Map 需求實現檢查清單

## ✅ 已完成的需求

### 1. 預設以樹狀圖呈現，由左到右，節點的每一階層對齊
- ✅ 整合 Dagre 佈局引擎
- ✅ 設定為左到右 (LR) 排列
- ✅ 節點自動依階層對齊
- ✅ 提供「自動排版」按鈕手動觸發
- **實現位置**: `app/static/js/user_story_map.js` - `applyTreeLayout()` 函數

### 2. 可以清楚呈現階層式的節點關係
- ✅ parent-child 關係支援
- ✅ 不同節點類型有獨特顏色標示
- ✅ Smoothstep 連線樣式用於父子關係
- ✅ 新增 level 欄位記錄層級
- **實現位置**: `app/models/user_story_map.py` - `UserStoryMapNode`

### 3. 節點之間可以做關係連結
- ✅ 拖曳連接點建立連線
- ✅ 支援 parent-child 連結
- ✅ 支援 related 關係（animated 樣式）
- ✅ 箭頭標記顯示方向
- **實現位置**: React Flow 原生功能 + `onConnect` callback

### 4. 節點可以記錄團隊資訊
- ✅ 使用 `team` 欄位保存單一團隊名稱
- ✅ 節點卡片以徽章呈現團隊名稱
- ✅ 屬性面板提供團隊欄位編輯
- **實現位置**: 
  - `app/models/user_story_map.py` - `UserStoryMapNode`
  - `app/static/js/user_story_map.js` - CustomNode component

### 5. 能夠計算兩個節點之間的相關聯程度
- ⚠️ 部分實現：可追蹤 parent-child 和 related 路徑
- 📝 建議：需要額外的演算法計算關聯度分數
- **待實現**: 關聯度計算 API

### 6. 節點能夠連結到 TCG/TP ticket，子節點關係會往上傳送
- ✅ jira_tickets 欄位支援多個 tickets
- ✅ aggregated_tickets 欄位儲存聚合結果
- ✅ 遞迴演算法計算子節點票證
- ✅ API 端點觸發計算
- ✅ UI 顯示聚合票證（黃色 badge）
- ✅ 「計算票證」按鈕
- **實現位置**: 
  - `app/api/user_story_maps.py` - `calculate_aggregated_tickets()`
  - `app/static/js/user_story_map.js` - aggregated tickets 顯示

### 7. 能夠使用特徵搜尋節點，符合條件的節點才會亮起
- ✅ 搜尋欄位：文字、JIRA ticket
- ✅ 搜尋結果列表顯示
- ✅ 符合條件的節點加上陰影高亮
- ✅ 顯示票證資訊
- **實現位置**: 
  - `app/api/user_story_maps.py` - `search_nodes()`
  - `app/static/js/user_story_map.js` - 搜尋事件處理

### 8. 可以選定樹狀圖的特定路徑顯示，其他節點/路徑淡化
- ✅ 「高亮路徑」按鈕
- ✅ 路徑追蹤從選定節點到根節點
- ✅ 路徑節點正常顯示（opacity: 1）
- ✅ 其他節點淡化（opacity: 0.3）
- ✅ 路徑連線正常，其他連線淡化
- ✅ 「清除高亮」按鈕恢復顯示
- **實現位置**: 
  - `app/api/user_story_maps.py` - `get_node_path()`
  - `app/static/js/user_story_map.js` - `highlightPath()` & `clearHighlight()`

### 9. 節點必須要能夠拖移
- ✅ React Flow 原生支援
- ✅ 拖移後位置自動保存
- ✅ 平滑的拖移體驗
- **實現位置**: React Flow 內建功能

### 10. 節點之間的連接線會自動適應版面變化
- ✅ React Flow 自動重新計算連線路徑
- ✅ 拖移節點時連線即時更新
- ✅ 使用 Bezier 或 Smoothstep 曲線平滑連接
- **實現位置**: React Flow 內建功能

### 11. 可以從節點跟 Test case 管理程式互動
- ⚠️ 部分準備：節點已包含 jira_tickets 資訊
- 📝 待實現：
  - 整合現有 test run API
  - 從 TCG tickets 選擇 test cases
  - 多團隊自動建立 test runs
- **建議實現**: 新增 API 端點與前端 modal

### 12. 需要可以任意地放大，縮小
- ✅ 放大按鈕（Zoom In）
- ✅ 縮小按鈕（Zoom Out）
- ✅ 適應畫面按鈕（Fit View）
- ✅ 滑鼠滾輪縮放
- ✅ MiniMap 快速導航
- ✅ Controls 面板
- **實現位置**: React Flow Controls component

### 13. 支援切割視窗比對模式
- ❌ 未實現
- 📝 建議實現方式：
  - 新增「比對模式」按鈕
  - 使用 CSS Grid 或 Flexbox 分割畫面
  - 允許同時載入兩個地圖
  - 同步縮放和捲動（可選）
- **預估工作量**: 2-3 天

### 14. 新增地圖時要預設新增一個根節點
- ✅ 建立地圖時自動產生根節點
- ✅ 根節點 ID: `root_{timestamp}`
- ✅ 根節點類型: Epic
- ✅ 根節點標題: "Root"
- ✅ 根節點描述: "根節點"
- ✅ 固定位置: (250, 250)
- ✅ 同步建立資料庫索引記錄
- **實現位置**: `app/api/user_story_maps.py` - `create_map()`

---

## 📊 實現狀況統計

- ✅ 完全實現: 11 項 (78.6%)
- ⚠️ 部分實現: 2 項 (14.3%)
- ❌ 未實現: 1 項 (7.1%)

---

## 🔧 技術債務與未來改進

### 高優先級
1. **Requirement 11**: Test run 整合
   - 需要與現有 test case 管理 API 整合
   - 建立從 User Story Map 啟動 test run 的流程

### 中優先級
2. **Requirement 13**: 分割視窗比對
   - UI/UX 設計
   - 雙地圖同步控制

3. **Requirement 5**: 關聯度演算法
   - 設計評分機制
   - 考慮多種關聯類型權重

### 低優先級
4. 效能優化
   - 大型地圖（>200 節點）的渲染優化
   - 虛擬化技術

5. 協作功能
   - 即時多人編輯
   - 變更歷史記錄

---

## 🚀 部署檢查清單

- [ ] 執行資料庫遷移腳本
- [ ] 驗證現有地圖資料向下相容
- [ ] 測試新建地圖自動產生根節點
- [ ] 測試自動排版功能
- [ ] 測試票證聚合計算
- [ ] 測試路徑高亮功能
- [ ] 測試搜尋與高亮
- [ ] 驗證節點拖移與連線
- [ ] 測試縮放和導航功能
- [ ] 確認節點顯示所屬團隊名稱
- [ ] 檢查瀏覽器相容性
- [ ] 效能測試（大型地圖）

---

## 📚 相關文件

- [完整功能說明](./USER_STORY_MAP_FEATURES.md)
- [快速參考指南](./USM_QUICK_REFERENCE.md)
- [資料模型](../app/models/user_story_map.py)
- [API 文件](../app/api/user_story_maps.py)
- [遷移腳本](../scripts/migrate_usm_db.py)
