# User Story Map Feature

## 概述
User Story Map 功能讓團隊能夠視覺化管理使用者故事、功能規劃和任務分解。

## 功能特點

### 1. 視覺化故事地圖
- 使用 React Flow 建立互動式的故事地圖
- 支援拖放操作調整節點位置
- 支援縮放和平移操作
- 迷你地圖導航

### 2. 節點類型
- **Epic**: 史詩級功能
- **Feature**: 功能特性
- **User Story**: 使用者故事
- **Task**: 具體任務

### 3. 節點屬性
每個節點包含以下屬性：
- **Title**: 標題
- **Description**: 描述
- **父節點**: Parent Node
- **子節點**: Children Nodes
- **關係節點**: Related Nodes
- **Comment**: 註解
- **JIRA Tickets**: 相關的 JIRA 工單
- **Product**: 所屬產品
- **Team**: 所屬團隊

### 4. 搜尋功能
支援多種搜尋條件：
- 關鍵字搜尋（標題、描述、註解）
- 節點類型篩選
- 產品篩選
- 團隊篩選
- JIRA Ticket 篩選

### 5. 多地圖管理
- 一個團隊可以建立多張故事地圖
- 每張地圖獨立管理
- 支援地圖列表瀏覽和切換

### 6. 獨立資料庫
使用獨立的 SQLite 資料庫 (`userstorymap.db`) 管理故事地圖資料：
- `user_story_maps`: 地圖主表
- `user_story_map_nodes`: 節點索引表（用於快速搜尋）

## 技術架構

### 後端
- **Framework**: FastAPI
- **Database**: SQLite (userstorymap.db)
- **ORM**: SQLAlchemy
- **Models**: 
  - `app/models/user_story_map.py`: Pydantic 模型
  - `app/models/user_story_map_db.py`: SQLAlchemy 資料庫模型
- **API**: `app/api/user_story_maps.py`

### 前端
- **React Flow**: 11.11.0 (via CDN)
- **React**: 18 (via CDN)
- **Bootstrap**: 5.3.0
- **Template**: `app/templates/user_story_map.html`
- **JavaScript**: `app/static/js/user_story_map.js`

## API 端點

### 獲取團隊的所有地圖
```
GET /api/user-story-maps/team/{team_id}
```

### 獲取特定地圖
```
GET /api/user-story-maps/{map_id}
```

### 建立新地圖
```
POST /api/user-story-maps/
Body: {
  "team_id": int,
  "name": string,
  "description": string (optional)
}
```

### 更新地圖
```
PUT /api/user-story-maps/{map_id}
Body: {
  "name": string (optional),
  "description": string (optional),
  "nodes": array (optional),
  "edges": array (optional)
}
```

### 刪除地圖
```
DELETE /api/user-story-maps/{map_id}
```

### 搜尋節點
```
GET /api/user-story-maps/{map_id}/search?q={keyword}&node_type={type}&product={product}&team={team}&jira_ticket={ticket}
```

## 使用方式

### 1. 進入 User Story Map
在團隊管理頁面，點擊團隊卡片上的「Story Map」按鈕。

### 2. 建立地圖
點擊「新增地圖」按鈕，輸入地圖名稱和描述。

### 3. 新增節點
點擊「新增節點」按鈕，選擇節點類型並填寫相關資訊。

### 4. 編輯節點
點擊節點後，右側邊欄會顯示節點屬性，可以編輯各項資訊。

### 5. 連接節點
拖動節點上的連接點到另一個節點，建立關係。

### 6. 儲存地圖
點擊「儲存」按鈕保存所有變更。

### 7. 搜尋節點
點擊「搜尋」按鈕，輸入搜尋條件尋找節點。

## 資料庫結構

### user_story_maps 表
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | INTEGER | 主鍵 |
| team_id | INTEGER | 團隊 ID |
| name | VARCHAR(255) | 地圖名稱 |
| description | TEXT | 地圖描述 |
| nodes | JSON | 節點資料 |
| edges | JSON | 連接線資料 |
| created_at | DATETIME | 建立時間 |
| updated_at | DATETIME | 更新時間 |

### user_story_map_nodes 表（索引表）
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | INTEGER | 主鍵 |
| map_id | INTEGER | 地圖 ID (外鍵) |
| node_id | VARCHAR(100) | 節點 ID |
| title | VARCHAR(255) | 標題 |
| description | TEXT | 描述 |
| node_type | VARCHAR(50) | 節點類型 |
| parent_id | VARCHAR(100) | 父節點 ID |
| children_ids | JSON | 子節點 IDs |
| related_ids | JSON | 關係節點 IDs |
| comment | TEXT | 註解 |
| jira_tickets | JSON | JIRA Tickets |
| product | VARCHAR(255) | 產品 |
| team | VARCHAR(255) | 團隊 |
| position_x | FLOAT | X 座標 |
| position_y | FLOAT | Y 座標 |
| created_at | DATETIME | 建立時間 |
| updated_at | DATETIME | 更新時間 |

## 樣式設計
User Story Map 遵循系統的整體設計風格：
- 使用 Bootstrap 5.3.0 組件
- 配色與其他頁面保持一致
- 響應式設計，支援不同螢幕尺寸

## 權限控制
- 使用現有的認證系統 (`get_current_user`)
- 用戶需要登入才能訪問和操作 User Story Map
- 團隊成員可以查看和編輯所屬團隊的地圖

## 未來改進方向
1. 支援匯出為圖片或 PDF
2. 支援範本功能
3. 增加協作編輯功能
4. 整合 JIRA API 自動同步工單狀態
5. 增加版本控制功能
6. 支援評論和討論功能
