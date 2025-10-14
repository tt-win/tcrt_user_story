# Team Statistics Test Run Metrics - 修改前後對比

## 修改前 (Before)

### API 返回結構
```json
{
  "daily_executions": [
    {"date": "2025-01-01", "count": 25},
    {"date": "2025-01-02", "count": 30}
  ],
  "pass_rate_trend": [
    {"date": "2025-01-01", "pass_rate": 80, "pass_count": 20, "total_count": 25},
    {"date": "2025-01-02", "pass_rate": 85, "pass_count": 26, "total_count": 30}
  ],
  "by_status": {...},
  "by_team": [...]
}
```

### 圖表顯示
- **每日執行次數圖表**: 單條線，顯示所有團隊的總執行次數
- **通過率趨勢圖表**: 單條線，顯示所有團隊的總通過率

### 問題
- 無法看出各團隊的執行狀況
- 無法比較不同團隊的表現
- 無法識別哪個團隊執行最多/最少
- 無法識別哪個團隊通過率最高/最低

---

## 修改後 (After)

### API 返回結構
```json
{
  "dates": ["2025-01-01", "2025-01-02", ...],
  "per_team_daily": [
    {
      "team_id": 1,
      "team_name": "Team A",
      "daily": [
        {"date": "2025-01-01", "count": 10},
        {"date": "2025-01-02", "count": 15}
      ],
      "total_executions": 25
    },
    {
      "team_id": 2,
      "team_name": "Team B", 
      "daily": [
        {"date": "2025-01-01", "count": 15},
        {"date": "2025-01-02", "count": 15}
      ],
      "total_executions": 30
    }
  ],
  "per_team_pass_rate": [
    {
      "team_id": 1,
      "team_name": "Team A",
      "daily": [
        {"date": "2025-01-01", "pass_rate": 80, "pass_count": 8, "total_count": 10},
        {"date": "2025-01-02", "pass_rate": 85, "pass_count": 13, "total_count": 15}
      ],
      "total_pass": 21,
      "total_count": 25,
      "overall_pass_rate": 84
    },
    {
      "team_id": 2,
      "team_name": "Team B",
      "daily": [
        {"date": "2025-01-01", "pass_rate": 85, "pass_count": 13, "total_count": 15},
        {"date": "2025-01-02", "pass_rate": 90, "pass_count": 14, "total_count": 15}
      ],
      "total_pass": 27,
      "total_count": 30,
      "overall_pass_rate": 90
    }
  ],
  "by_status": {...},
  "by_team": [...],
  "overall": {
    "daily_executions": [...],
    "pass_rate_trend": [...]
  }
}
```

### 圖表顯示
- **各團隊每日執行次數圖表**: 多條線，每個團隊一條線，不同顏色區分
  - Team A (藍色): 顯示 Team A 的每日執行趨勢
  - Team B (綠色): 顯示 Team B 的每日執行趨勢
  - Team C (紅色): 顯示 Team C 的每日執行趨勢
  - 圖例清楚標示各團隊名稱

- **各團隊通過率趨勢圖表**: 多條線，每個團隊一條線，不同顏色區分
  - Team A (藍色): 顯示 Team A 的通過率變化
  - Team B (綠色): 顯示 Team B 的通過率變化
  - Team C (紅色): 顯示 Team C 的通過率變化
  - Y軸範圍 0-100%

### 優勢
✓ 可以清楚看出每個團隊的執行狀況
✓ 可以比較不同團隊的執行頻率
✓ 可以識別哪個團隊最活躍
✓ 可以比較各團隊的測試通過率
✓ 可以發現哪些團隊需要改進測試品質
✓ 與 Test Case Trends 頁面的顯示風格保持一致

---

## 視覺效果對比

### 修改前
```
每日執行次數圖表:
    │
 30 │           ●
    │       ●
 20 │   ●
    │●
  0 └─────────────────→
    1/1  1/2  1/3  1/4
    
    單一線條，看不出團隊分佈
```

### 修改後
```
各團隊每日執行次數圖表:
    │
 30 │       ▲
    │   ●   │ ▲
 20 │   │●  │
    │●  │   ■──■
  0 └─────────────────→
    1/1  1/2  1/3  1/4
    
    ● Team A (最活躍)
    ■ Team B (穩定)
    ▲ Team C (增長中)
    
    多條線，清楚顯示各團隊趨勢
```

---

## 技術實現

### 後端改動
- SQL 查詢增加 `GROUP BY team_id, day`
- 按團隊組織數據結構
- 計算每個團隊的總數和通過率
- 填補缺失日期為 0

### 前端改動  
- 使用現有的 `buildTeamDatasets` 函數
- 傳遞團隊數據到圖表
- 啟用圖例顯示
- 使用團隊配色方案

### 向後相容
- 保留 `by_team` 和 `by_status` 欄位
- 新增 `overall` 欄位提供全域數據
- 不影響其他頁面功能
