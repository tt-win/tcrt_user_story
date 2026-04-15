# system-bootstrap Specification

## Purpose
定義 TCRT 啟動時的 bootstrap 行為，確保資料庫初始化、必要檢查與既有資料升級流程一致且可預測。

## Requirements
### Requirement: 系統啟動與資料庫初始化
系統啟動流程 SHALL 執行必要的資料庫初始化 / 驗證，並區分全新系統與既有系統啟動路徑。

#### Scenario: 啟動全新系統
- **WHEN** 系統在空白資料環境下啟動
- **THEN** bootstrap 建立必要資料表與初始資料

#### Scenario: 啟動已存在的系統
- **WHEN** 系統在已有資料的環境啟動
- **THEN** bootstrap 只執行必要驗證與非破壞性修補，不覆寫既有資料
