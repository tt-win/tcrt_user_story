# Team Statistics - Test Run Metrics 按團隊顯示修改說明

## 修改概述

修改 team-statistics 頁面的 test run metrics，使其按照分 team 來顯示數據，類似於 test case trends 的顯示方式。

## 修改內容

### 1. 後端 API 修改 (`app/api/team_statistics.py`)

修改 `/admin/team_statistics/test_run_metrics` 端點，使其返回按團隊分組的數據：

#### 新增返回欄位：
- `dates`: 日期座標列表
- `per_team_daily`: 團隊別每日執行統計
- `per_team_pass_rate`: 團隊別每日通過率統計  
- `overall`: 全域彙總（包含 `daily_executions` 和 `pass_rate_trend`）

#### 數據結構範例：
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
    }
  ],
  "per_team_pass_rate": [
    {
      "team_id": 1,
      "team_name": "Team A",
      "daily": [
        {"date": "2025-01-01", "pass_rate": 85.5, "pass_count": 8, "total_count": 10},
        {"date": "2025-01-02", "pass_rate": 90.0, "pass_count": 14, "total_count": 15}
      ],
      "total_pass": 22,
      "total_count": 25,
      "overall_pass_rate": 88.0
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

#### SQL 查詢改進：
1. **每日執行次數按團隊分組**：
   ```sql
   SELECT team_id, date(created_at) as day, COUNT(*) as cnt
   FROM test_run_items
   WHERE date(created_at) BETWEEN :start_date AND :end_date
   GROUP BY team_id, day
   ```

2. **通過率按團隊分組**：
   ```sql
   SELECT
       trirh.team_id,
       date(trirh.changed_at) as day,
       SUM(CASE WHEN trirh.new_result = 'Pass' THEN 1 ELSE 0 END) as pass_count,
       COUNT(*) as total_count
   FROM test_run_item_result_history trirh
   WHERE date(trirh.changed_at) BETWEEN :start_date AND :end_date
   GROUP BY trirh.team_id, day
   ```

### 2. 前端 JavaScript 修改 (`app/static/js/team_statistics.js`)

#### 修改 `loadTestRunMetrics` 函數：
- 從 API 讀取 `dates`、`per_team_daily`、`per_team_pass_rate`
- 傳遞團隊數據到圖表渲染函數

#### 修改圖表渲染函數：

1. **`renderTestRunDailyChart(dates, perTeam)`**：
   - 從單線圖改為多線圖（每個團隊一條線）
   - 使用 `buildTeamDatasets` 函數構建多團隊數據集
   - 顯示圖例以區分不同團隊

2. **`renderTestRunPassRateChart(dates, perTeam)`**：
   - 從單線圖改為多線圖（每個團隊一條線）
   - 使用 `buildTeamDatasets` 函數構建多團隊數據集
   - Y軸範圍設定為 0-100%

#### 利用現有的 `buildTeamDatasets` 函數：
此函數已存在於程式碼中（用於 test case trends），可以重用來生成團隊色彩和數據集配置。

### 3. HTML 模板修改 (`app/templates/team_statistics.html`)

更新圖表標題以反映按團隊分組的特性：
- 「每日執行次數」→「各團隊每日執行次數」
- 「通過率趨勢」→「各團隊通過率趨勢」

## 技術細節

### 資料處理流程：
1. 從資料庫查詢按團隊和日期分組的原始數據
2. 建立完整的日期範圍（填補缺失日期為 0）
3. 為每個團隊構建完整的時間序列數據
4. 計算全域彙總數據（所有團隊的總和）
5. 按執行數量或通過率排序團隊

### 相容性考量：
- 保持 `by_status` 和 `by_team` 欄位不變，確保現有表格顯示正常
- 新增 `overall` 欄位提供全域數據（向後相容）
- 前端處理空數據情況（無團隊數據時顯示空白圖表）

## 測試建議

1. **無數據情況**：確認沒有 test run 時圖表正確顯示
2. **單一團隊**：確認只有一個團隊時圖表正常顯示
3. **多個團隊**：確認多團隊時顏色區分明顯，圖例清晰
4. **日期範圍切換**：測試 7天/30天/90天 切換功能
5. **通過率計算**：驗證通過率計算準確性

## 相關檔案

- `app/api/team_statistics.py` - 後端 API
- `app/static/js/team_statistics.js` - 前端邏輯
- `app/templates/team_statistics.html` - HTML 模板

## 完成時間

2025-10-14
