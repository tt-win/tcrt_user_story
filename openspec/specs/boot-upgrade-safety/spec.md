# boot-upgrade-safety Specification

## Purpose
TBD - created by archiving change add-boot-upgrade-backup-rollback. Update Purpose after archive.
## Requirements
### Requirement: Bootstrap SHALL 只在有 pending migration 時建立備份
Bootstrap 對每個 target（main / audit / usm）SHALL 比對資料庫目前 Alembic revision 與 migration script head：兩者一致時 SHALL NOT 產生備份或其他寫入副作用，只執行既有驗證；不一致時才進入備份與升版流程。全新（無任何業務表）的資料庫 SHALL 視為無可保護資料而跳過備份。

#### Scenario: 無 pending migration 的重複開機
- **WHEN** 容器以相同 image 重複重啟，三個 target 的 current revision 皆等於 head
- **THEN** bootstrap 不建立任何備份檔，直接執行驗證並成功結束

#### Scenario: 偵測到 pending migration
- **WHEN** 新 image 帶有尚未套用的 Alembic revision，target 的 current revision 不等於 head
- **THEN** bootstrap 先依備份政策完成該 target 備份，再執行 upgrade

#### Scenario: 全新資料庫首次 bootstrap
- **WHEN** target database 剛被建立、不含任何業務表
- **THEN** bootstrap 跳過備份直接建表升版，且失敗時不執行回退

### Requirement: 升版前備份 SHALL 支援 SQLite / MySQL / PostgreSQL 三引擎
備份 SHALL 依 target 的資料庫引擎分派：SQLite 使用 `sqlite3` backup API、MySQL 使用 `mysqldump --single-transaction`、PostgreSQL 使用 `pg_dump --format=custom`；備份檔 SHALL 統一寫入 `BOOTSTRAP_BACKUP_DIR` 下依 target 分目錄、檔名含 UTC 時戳與 from/to revision，並附帶 metadata sidecar。資料庫密碼 SHALL 僅以環境變數（`MYSQL_PWD` / `PGPASSWORD`）傳遞給 dump 工具，SHALL NOT 出現在命令列參數或日誌中。

#### Scenario: MySQL target 升版前備份
- **WHEN** main target 為 MySQL 且偵測到 pending migration
- **THEN** bootstrap 以 mysqldump 產生 gzip 備份於 `BOOTSTRAP_BACKUP_DIR/main/`，檔名含時戳與 revision 區間，日誌不含密碼

#### Scenario: SQLite target 升版前備份
- **WHEN** target 為 SQLite 且偵測到 pending migration
- **THEN** bootstrap 以 sqlite3 backup API 產生一致性快照，不受 WAL 模式影響

### Requirement: 備份政策 SHALL 以 BOOTSTRAP_BACKUP_MODE 分級
系統 SHALL 支援 `required`（預設）/ `best-effort` / `off` 三級：`required` 下備份失敗（含 dump client 不存在、備份目錄不可寫）SHALL 中止 bootstrap 且不執行 upgrade；`best-effort` 下備份失敗 SHALL 記錄警告並繼續升版；`off` SHALL 跳過備份。CLI `--no-backup` SHALL 等效於 `off` 且優先於環境變數。

#### Scenario: required 模式缺少 dump client
- **WHEN** `BOOTSTRAP_BACKUP_MODE=required`、target 為 MySQL、容器內找不到 mysqldump
- **THEN** bootstrap 以非零狀態退出且未執行任何 upgrade，錯誤訊息指出缺少的工具

#### Scenario: best-effort 模式備份失敗
- **WHEN** `BOOTSTRAP_BACKUP_MODE=best-effort` 且備份因任何原因失敗
- **THEN** bootstrap 記錄警告後繼續執行 upgrade

### Requirement: 備份 SHALL 依 retention 策略自動清理
每個 target 目錄 SHALL 依 `BOOTSTRAP_BACKUP_RETENTION`（預設 5）保留最近 N 份備份（依檔名時戳排序），成功建立新備份後 SHALL 刪除超出份數的最舊備份及其 metadata sidecar。

#### Scenario: 超出保留份數
- **WHEN** retention 為 5 且某 target 已累積 5 份備份，新升版再產生 1 份
- **THEN** 最舊的 1 份備份與其 sidecar 被刪除，目錄內恰保留 5 份

### Requirement: 升版失敗時 SHALL 依 BOOTSTRAP_ON_FAILURE 政策處理
`abort`（預設）下升版失敗 SHALL 維持現行為（記錄錯誤、非零退出）。`rollback` 下，任一 target 的 upgrade 或升版後驗證失敗時，bootstrap SHALL 以本次建立的備份**反序還原本次已升版的所有 target 與失敗中的 target**，使三套資料庫一致回到升版前狀態；還原成功 SHALL 以專屬狀態碼退出並說明「可換回舊版 image 立即啟動」；還原失敗 SHALL 以另一專屬狀態碼退出並輸出備份檔位置供人工還原。無論還原成敗，該次啟動 SHALL NOT 繼續開啟 web 服務。

#### Scenario: rollback 模式下第二個 target 升版失敗
- **WHEN** `BOOTSTRAP_ON_FAILURE=rollback`，main 已成功升版，audit 升版中途失敗
- **THEN** bootstrap 依 audit → main 的順序還原兩者至升版前 revision，以回退成功狀態碼退出，且換用舊版 image 後可直接正常開機

#### Scenario: rollback 模式但無可用備份
- **WHEN** `BOOTSTRAP_ON_FAILURE=rollback` 且該 target 因 `best-effort` 備份失敗而無備份
- **THEN** 行為退化為 abort，錯誤訊息說明因無備份而未回退

#### Scenario: MySQL 半套 schema 還原
- **WHEN** MySQL target 的 migration 在多個 DDL 之間失敗，留下部分新表
- **THEN** rollback 還原後資料庫不含失敗 migration 產生的任何新表，`alembic_version` 回到升版前值

### Requirement: 連續升版失敗 SHALL 被 failure marker 阻斷
每次升版失敗 SHALL 在備份目錄寫入／累加該 target 的 failure marker（含 head revision、嘗試次數、錯誤摘要、時間）。bootstrap 開始時 SHALL 檢查 marker：同一 head 的連續失敗次數達 `BOOTSTRAP_MAX_UPGRADE_ATTEMPTS`（預設 3）SHALL 直接以專屬狀態碼退出且不觸碰任何資料庫；head 改變（image 換版）SHALL 重新計數；該 target 升版成功 SHALL 清除 marker。系統 SHALL 提供 CLI 旗標供人工清除全部 marker。

#### Scenario: restart policy 造成的重複失敗
- **WHEN** 容器 restart policy 反覆重啟、同一 head 已連續失敗 3 次
- **THEN** 第 4 次開機在任何備份或 upgrade 之前即以拒絕狀態碼退出，日誌指示需人工介入

#### Scenario: 換版後重新計數
- **WHEN** marker 記錄的 head 與目前 image 的 head 不同
- **THEN** 視為新一輪升版，嘗試次數重新起算

#### Scenario: 人工解鎖
- **WHEN** 操作者修復問題後執行 marker 清除旗標
- **THEN** 全部 failure marker 被刪除，下次開機恢復正常升版流程

### Requirement: 備份與回退流程 SHALL 維持 bootstrap 併發安全
pending 偵測、備份、升版、回退與 marker 讀寫 SHALL 全部發生在既有 bootstrap 序列化鎖的臨界區內；多 worker / 多副本同時啟動時 SHALL 僅有一個行程執行上述流程。

#### Scenario: 兩副本同時開機且有 pending migration
- **WHEN** 兩個容器副本同時啟動且偵測到 pending migration
- **THEN** 僅一個行程執行備份與升版，另一行程等待鎖釋放後以「無 pending」路徑通過驗證

