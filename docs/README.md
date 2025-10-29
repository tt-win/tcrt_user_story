# Test Case Repository Web Tool

整合式測試案例管理系統，提供完整的測試案例生命週期管理、執行追蹤與缺陷單管理功能。基於 FastAPI 與 Bootstrap 建置，支援多語系（繁中/英文），並整合 Lark 多維表格與 JIRA。

## 主要功能

### 測試案例管理
- 智慧搜尋與進階篩選
- 即時編輯與批次操作
- Lark 多維表格同步
- 版本歷程追蹤

### 測試執行管理
- 完整的生命週期管理
  - 建立：從既有案例庫選取測試項目
  - 執行：彈性指派與進度追蹤
  - 結案：完整的結果統計與報表
- 多模式重測流程
  - 全部重測
  - 僅失敗項目
  - 待測項目
- 批次操作功能
  - 更新執行者
  - 修改測試結果
  - 批次刪除

### 團隊管理
- 團隊基本資訊設定
- Lark 多維表格來源配置
- JIRA 專案整合設定

### Bug 單管理 ✨
- 每個測試案例的 Bug 單完整 CRUD 操作
- 即時 JIRA 狀態同步
- Bug 單摘要與狀態篩選
- 懸停預覽與直接跳轉

### 國際化支援
- 完整繁體中文與英文支援
- 執行階段語言切換
- 使用者偏好儲存

## 開始使用

### 系統需求
- Python 3.10 以上版本
- pip 套件管理工具

### 安裝相依套件
```bash
pip install -r requirements.txt
```

### 設定專案
1. 複製設定範本
```bash
cp config.yaml.example config.yaml
```

2. 設定必要參數（擇一即可）
- Lark 多維表格（非必要）
  - `lark.app_id`
  - `lark.app_secret`
- JIRA（非必要）
  - `jira.url`
  - `jira.username`
  - `jira.api_token`

3. 啟動應用程式
```bash
uvicorn app.main:app --reload --port 9999
```

4. 開啟瀏覽器
```
http://localhost:9999
```

## 專案結構
```
app/
├── api/            # REST API 端點
├── models/         # 資料模型（Pydantic + SQLAlchemy）
├── services/       # 業務邏輯服務層
├── static/         # 靜態資源（JS、CSS、i18n）
├── templates/      # 頁面模板
├── database.py    # 資料庫引擎與連線
└── main.py        # FastAPI 應用程式入口
```

## API 端點說明

### 測試執行配置
- `GET /api/teams/{team_id}/test-run-configs`
  - 列出團隊所有測試執行
- `POST /api/teams/{team_id}/test-run-configs/{config_id}/restart`
  - 從既有配置複製新測試執行
  - 請求：`{ "mode": "all" | "failed" | "pending", "name"?: "重測 - 原名稱" }`
  - 回應：`{ success, mode, new_config_id, created_count }`

### 測試執行項目
- `GET /api/teams/{team_id}/test-run-configs/{config_id}/items`
  - 列出執行項目（支援排序與篩選）
- `PUT /api/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}`
  - 更新執行者/結果（自動記錄歷程）
- `POST /api/teams/{team_id}/test-run-configs/{config_id}/items/batch-update`
  - 批次更新操作

### Bug 單管理
- `POST /api/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/bug-tickets`
  - 新增 Bug 單
- `DELETE /api/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/bug-tickets/{ticket_number}`
  - 移除 Bug 單
- `GET /api/teams/{team_id}/test-run-configs/{config_id}/items/bug-tickets/summary`
  - 取得 Bug 單摘要與狀態統計

### JIRA 整合
- `GET /api/jira/ticket/{ticket_key}`
  - 取得即時票單資訊
- `GET /api/jira/projects`
  - 列出可用的 JIRA 專案

## 前端特色功能

### 智慧介面
- 統一的批次操作列
- 邏輯性的案例編號排序
- 多層 Modal 管理系統

### Bug 單整合
- 狀態分類篩選器
  - 全部、待辦、進行中
  - 已解決、已排程、已關閉
- 即時狀態更新與重整
- 測試案例中的懸停預覽

### 在地化支援
- 完整的雙語介面
- 即時語言切換
- 使用者偏好記憶

### 進階互動
- 重測命名建議
- 批次操作驗證
- 即時操作回饋

## 開發資訊

### 資料庫
- SQLite（自動建立）
- 資料模型：`app/models/database_models.py`

### 日誌
- 主控台輸出
- 配置：`app/main.py` 中的 `logging.basicConfig`

### 前端架構
- Bootstrap 5
- 原生 JavaScript
- 模組化元件設計

### 測試
- 執行：`pytest -q`
- 測試碼：`tests/` 目錄

## 最新更新（2025.09）

### 功能更新
- ✨ Bug 單管理系統上線
- 🔄 多層 Modal 系統優化
- 🎯 JIRA 整合強化
- 🌐 雙語系統完善
- 🎨 介面優化與互動提升

### 移除功能
- 團隊設定中移除通知與自動建 Bug 開關
  - 改由後端統一控管，提升一致性
  - 降低設定複雜度

## 授權說明
- 內部專案，未加入公開授權聲明
