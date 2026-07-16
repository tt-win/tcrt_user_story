## MODIFIED Requirements

### Requirement: 系統啟動與資料庫初始化
系統啟動流程 SHALL 執行必要的資料庫初始化 / 驗證，並區分全新系統與既有系統啟動路徑。既有系統啟動時 SHALL 先偵測各 target 是否存在 pending schema 升版：無 pending 時 SHALL 只執行驗證、不產生備份副作用；有 pending 時 SHALL 依 `boot-upgrade-safety` 能力定義的備份政策先完成備份再升版，升版失敗時依失敗政策處理。當 server database 已存在時，bootstrap SHALL 可使用僅具該目標 database schema 與資料權限的 app 帳號完成，不得額外要求存取 MySQL `mysql` 或 PostgreSQL `postgres` 管理 database；只有目標 database 明確不存在時才 SHALL 嘗試既有自動建庫路徑。

#### Scenario: 啟動全新系統
- **WHEN** 系統在空白但已建立的目標 databases 上以受限 app 帳號啟動
- **THEN** bootstrap 不連線管理 database，直接建立必要資料表與初始資料

#### Scenario: 啟動已存在的系統
- **WHEN** 系統在已有資料的環境啟動且無 pending schema 升版
- **THEN** bootstrap 只執行必要驗證與非破壞性修補，不覆寫既有資料，也不產生備份檔

#### Scenario: 啟動已存在的系統且有 pending 升版
- **WHEN** 系統在已有資料的環境啟動且偵測到 pending schema 升版
- **THEN** bootstrap 依備份政策完成升版前備份後執行升版，失敗時依 `BOOTSTRAP_ON_FAILURE` 政策回退或中止

#### Scenario: 目標 database 不存在
- **WHEN** 系統連線目標 database 得到明確 missing-database error
- **THEN** bootstrap 才連線對應管理 database，並在帳號權限允許時自動建立目標 database

#### Scenario: 目標連線因其他原因失敗
- **WHEN** 系統連線目標 database 因認證、網路或非 missing-database 錯誤失敗
- **THEN** bootstrap 原樣失敗且不得誤進自動建庫路徑
