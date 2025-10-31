# User Story Map 功能實現說明

> **注意**：最新版本已移除節點類型、產品屬性與 `team_tags` 多團隊標籤。以下章節保留歷史實作記錄，僅供參考。

## 已實現功能

### 1. 預設樹狀圖呈現，由左到右排列
- ✅ 使用 Dagre 圖形佈局演算法實現自動樹狀排版
- ✅ 左到右 (LR) 方向排列，節點間距可調整
- ✅ 新增「自動排版」按鈕，可隨時重新套用樹狀佈局

### 2. 清楚呈現階層式節點關係
- ✅ 支援 parent-child 關係（透過 parent_id 和 children_ids）
- ✅ 節點類型包含：Epic, Feature, User Story, Task
- ✅ 不同節點類型有不同的顏色和視覺樣式
- ✅ 新增 level 欄位記錄節點層級

### 3. 節點之間可以做關係連結
- ✅ 支援 parent-child 連結（smoothstep 樣式）
- ✅ 支援 related 關係連結（animated 動畫樣式）
- ✅ 使用 React Flow 的連線功能，拖曳即可建立連結

### 4. 節點顯示所屬團隊
- ✅ 使用單一 `team` 欄位代表負責團隊
- ✅ 自動帶入地圖所屬團隊名稱，使用者無需手動輸入
- ✅ 節點卡片與屬性面板顯示團隊資訊

### 5. 計算兩個節點之間的相關聯程度
- ⚠️ 基礎實現：透過 parent-child 和 related 關係追蹤
- 📝 進階功能待實現：計算關聯度分數演算法

### 6. 節點能夠連結 TCG/TP ticket，子節點關係往上傳送
- ✅ 節點支援 jira_tickets 欄位（陣列）
- ✅ 新增 aggregated_tickets 欄位，聚合所有子節點的 tickets
- ✅ 提供 API 端點計算聚合 tickets：`POST /api/user-story-maps/{map_id}/calculate-aggregated-tickets`
- ✅ 在節點屬性面板顯示聚合後的 tickets
- ✅ 新增「計算票證」按鈕，手動觸發計算

### 7. 使用特徵搜尋節點，符合條件的節點會亮起
- ✅ 搜尋功能支援：文字描述、節點類型、產品、團隊、JIRA ticket
- ✅ 搜尋結果會顯示符合條件的節點列表
- ✅ 搜尋結果的節點會加上視覺高亮效果（陰影）
- ✅ 在搜尋結果中顯示節點的 JIRA tickets

### 8. 選定樹狀圖特定路徑顯示，其他節點淡化
- ✅ 新增「高亮路徑」功能按鈕
- ✅ 選擇節點後，可追蹤從根節點到該節點的完整路徑
- ✅ 路徑上的節點保持正常顯示，其他節點淡化（opacity: 0.3）
- ✅ 路徑上的連線保持正常，其他連線也會淡化
- ✅ 新增「清除高亮」按鈕，恢復正常顯示
- ✅ 提供 API 端點：`GET /api/user-story-maps/{map_id}/path/{node_id}`

### 9. 節點必須要能夠拖移
- ✅ React Flow 內建支援節點拖移
- ✅ 拖移後的位置會保存到 position_x 和 position_y

### 10. 連接線自動適應版面變化
- ✅ React Flow 自動處理連接線的重新繪製
- ✅ 拖移節點時，連接線會自動調整路徑
- ✅ 連接線始終保持與節點的連接

### 11. 從節點與 Test case 管理程式互動
- 📝 待實現：需要整合現有的 test run 建立 API
- 📝 未來功能：
  - 從節點的 TCG tickets 選擇 test cases
  - 自動建立跨多個團隊的 test runs

### 12. 可以任意放大、縮小
- ✅ 提供放大（Zoom In）按鈕
- ✅ 提供縮小（Zoom Out）按鈕
- ✅ 提供「適應畫面」按鈕，自動調整縮放比例
- ✅ React Flow 內建 MiniMap 和 Controls 元件

### 13. 支援切割視窗比對模式
- 📝 待實現：需要額外的 UI 開發
- 📝 未來功能：並排顯示兩個地圖進行比對

### 14. 新增地圖時預設新增一個根節點
- ✅ 建立新地圖時自動建立 root 節點
- ✅ Root 節點類型為 Epic
- ✅ Root 節點標題為 "Root"，描述為 "根節點"
- ✅ Root 節點位置固定在 (250, 250)

## 資料模型變更

### UserStoryMapNode
新增欄位：
- `team_tags`: List[TeamTag] - 多團隊標籤（取代單一 team 欄位）
- `aggregated_tickets`: List[str] - 聚合的 tickets（含子節點）
- `level`: int - 節點層級

### TeamTag (新增)
```python
class TeamTag(BaseModel):
    team_name: str
    labels: List[str]
    comment: Optional[str]
```

## API 端點新增

1. `POST /api/user-story-maps/{map_id}/calculate-aggregated-tickets`
   - 計算並更新所有節點的聚合 tickets

2. `GET /api/user-story-maps/{map_id}/path/{node_id}`
   - 獲取從根節點到指定節點的路徑

## 前端增強

### 新增按鈕
- 自動排版：套用樹狀圖佈局
- 計算票證：觸發聚合 tickets 計算
- 高亮路徑：顯示選定節點的完整路徑
- 清除高亮：恢復正常顯示

### 視覺增強
- 多團隊標籤顯示為獨立的 badges
- 聚合 tickets 以不同顏色標示
- 路徑高亮時使用淡化效果
- 搜尋結果節點添加陰影高亮

## 技術棧

- **前端**：React + React Flow 11.11.0
- **佈局引擎**：Dagre 0.8.5
- **後端**：FastAPI + SQLAlchemy (Async)
- **資料庫**：SQLite (獨立的 userstorymap.db)

## 使用方式

1. **建立新地圖**：點擊「新增地圖」按鈕，輸入名稱和描述，系統會自動建立一個根節點
2. **新增節點**：點擊「新增節點」按鈕，選擇類型並填寫資訊
3. **連接節點**：拖曳節點邊緣的連接點到另一個節點
4. **自動排版**：點擊「自動排版」按鈕，系統會自動調整為樹狀佈局
5. **搜尋節點**：點擊「搜尋」按鈕，輸入條件查找節點
6. **高亮路徑**：選擇節點後，點擊「高亮路徑」查看從根到該節點的完整路徑
7. **計算票證**：點擊「計算票證」按鈕，系統會自動聚合所有子節點的 JIRA tickets
8. **儲存**：完成編輯後，點擊「儲存」按鈕保存變更

## 向下相容性

所有變更都保持向下相容：
- 舊的 `team` 欄位仍然支援
- 新的 `team_tags` 為可選欄位
- 現有地圖可正常載入和使用

## 未來改進方向

1. **測試整合**：整合 test run 建立功能
2. **分割視窗**：實現並排比對模式
3. **關聯度演算法**：實現更精確的節點關聯度計算
4. **批次操作**：支援多選節點進行批次編輯
5. **匯出功能**：支援匯出為 PNG, SVG, JSON 等格式
6. **版本控制**：記錄地圖的變更歷史
7. **協作功能**：即時多人協作編輯
8. **權限控制**：細粒度的團隊權限管理
