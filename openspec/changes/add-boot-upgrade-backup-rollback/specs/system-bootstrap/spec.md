# system-bootstrap Specification

## Purpose
擴充既有系統啟動 bootstrap 行為：既有系統啟動路徑納入「pending 升版偵測 → 政策化備份 → 升版 → 失敗回退」流程。

## MODIFIED Requirements

### Requirement: 系統啟動與資料庫初始化
系統啟動流程 SHALL 執行必要的資料庫初始化 / 驗證，並區分全新系統與既有系統啟動路徑。既有系統啟動時 SHALL 先偵測各 target 是否存在 pending schema 升版：無 pending 時 SHALL 只執行驗證、不產生備份副作用；有 pending 時 SHALL 依 `boot-upgrade-safety` 能力定義的備份政策先完成備份再升版，升版失敗時依失敗政策處理。

#### Scenario: 啟動全新系統
- **WHEN** 系統在空白資料環境下啟動
- **THEN** bootstrap 建立必要資料表與初始資料

#### Scenario: 啟動已存在的系統
- **WHEN** 系統在已有資料的環境啟動且無 pending schema 升版
- **THEN** bootstrap 只執行必要驗證與非破壞性修補，不覆寫既有資料，也不產生備份檔

#### Scenario: 啟動已存在的系統且有 pending 升版
- **WHEN** 系統在已有資料的環境啟動且偵測到 pending schema 升版
- **THEN** bootstrap 依備份政策完成升版前備份後執行升版，失敗時依 `BOOTSTRAP_ON_FAILURE` 政策回退或中止
