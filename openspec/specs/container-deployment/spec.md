# container-deployment Specification

## Purpose
TBD - created by archiving change harden-container-deployment. Update Purpose after archive.
## Requirements
### Requirement: Signing keys survive container redeploy
系統 SHALL 將密碼加密用的 RSA 簽章金鑰對保存在可由環境變數設定、且對應持久化儲存（named volume）的位置，使金鑰在容器重建或替換後維持不變；只要持久化位置已存在金鑰，系統 SHALL 沿用既有金鑰而非重新生成。

#### Scenario: Existing keys reused after container replacement
- **WHEN** 金鑰目錄已掛載 named volume 且其中已有金鑰，容器被刪除並以新容器重建
- **THEN** 新容器載入既有金鑰（私鑰指紋不變）而不重新生成
- **AND** 以舊公鑰加密、尚未解密的登入 payload 在重建後仍可被解密

#### Scenario: Key directory is environment-configurable
- **WHEN** 部署以環境變數指定金鑰目錄
- **THEN** 系統於該目錄讀寫金鑰，而非固定於 repo 相對路徑

#### Scenario: First boot without existing keys generates once
- **WHEN** 持久化金鑰目錄為空且容器首次啟動
- **THEN** 系統生成一次金鑰並寫入該持久化目錄，後續重建沿用同一把

### Requirement: Startup fails fast on missing critical secrets
系統 SHALL 在啟動時驗證關鍵密鑰；當認證啟用而 JWT 簽章密鑰缺漏、或系統內已存在 automation provider 資料而 provider 加密金鑰缺漏時，系統 SHALL 以明確錯誤中止啟動，而非以不安全的回退值或延遲錯誤繼續運行。

#### Scenario: Empty JWT secret aborts startup
- **WHEN** `enable_auth` 為真且 `JWT_SECRET_KEY` 未設定（空）
- **THEN** 系統啟動失敗並回報缺少 JWT 簽章密鑰
- **AND** 不以空字串密鑰簽發任何 JWT

#### Scenario: Missing provider encryption key with existing providers aborts startup
- **WHEN** 系統內已存在 automation provider credential 資料，但 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 缺漏
- **THEN** 系統於啟動即以明確錯誤中止，而非等到首次解密才失敗

#### Scenario: Valid secrets allow normal startup
- **WHEN** 所有關鍵密鑰皆已正確設定
- **THEN** 系統正常完成啟動

### Requirement: Container state is volume and environment driven
系統的容器部署設定 SHALL 不含任何特定開發者或主機的寫死絕對路徑；attachments、reports 與金鑰等狀態目錄 SHALL 由環境變數指定並對應持久化 volume。

#### Scenario: No hardcoded host paths in compose
- **WHEN** 檢視容器部署設定（compose）
- **THEN** attachments／reports／金鑰目錄皆以環境變數（如 `${ATTACHMENTS_ROOT_DIR}`／`${REPORTS_ROOT_DIR}`）表示
- **AND** 不出現任何如 `/Users/<name>/...` 的特定開發者路徑

#### Scenario: Deployment on a different host works unchanged
- **WHEN** 在另一台主機設定對應環境變數後啟動容器
- **THEN** 服務以該主機的 volume 路徑正常運作，無需修改 compose 內容

### Requirement: Configuration reaches the container
系統 SHALL 提供標準化機制（`APP_CONFIG_PATH` 掛載或將設定納入映像）讓 `config.yaml` 在容器內可被讀取，使 AI helper 等可調項目於容器中生效；當未提供設定檔時，系統 SHALL 回退既有預設值且不中斷啟動。

#### Scenario: Mounted config takes effect
- **WHEN** 容器經 `APP_CONFIG_PATH`（或掛載）取得 `config.yaml`
- **THEN** 系統套用該檔內的設定（例如 AI helper 調校），而非僅跑預設值

#### Scenario: Missing config falls back to defaults
- **WHEN** 容器未提供 `config.yaml`
- **THEN** 系統以內建預設值啟動且不失敗（與既有行為一致）

### Requirement: Database bootstrap is concurrency-safe
系統 SHALL 確保資料庫 bootstrap（schema 變更／Alembic upgrade）在多副本或平行重啟下序列化執行——以 DB advisory lock 或一次性 init job 達成，使同一時間僅有一個行程進行 schema 變更。

#### Scenario: Parallel boots do not double-migrate
- **WHEN** 兩個應用程式行程幾乎同時啟動並嘗試 bootstrap
- **THEN** 僅有一個行程取得鎖並執行 schema 變更
- **AND** 另一個行程等待或略過，不會平行執行重複的 migration

#### Scenario: Single-instance boot is unaffected
- **WHEN** 單一副本啟動並執行 bootstrap
- **THEN** 該行程取得鎖、完成 bootstrap，行為與加鎖前一致

### Requirement: Hardened runtime image
系統的容器映像 SHALL 以非 root 使用者執行、於映像層級內建 `HEALTHCHECK`，且最終 runtime 映像 SHALL NOT 包含僅供建置使用的工具鏈（如 `build-essential`），以縮小體積與攻擊面。

#### Scenario: Container runs as non-root
- **WHEN** 以該映像啟動容器
- **THEN** 應用程式行程以非 root 使用者執行
- **AND** 金鑰與狀態目錄對該使用者可寫

#### Scenario: Image carries its own healthcheck
- **WHEN** 容器啟動並通過啟動期
- **THEN** 映像內建的 `HEALTHCHECK` 對 `/health` 回報健康狀態，無需依賴外部 compose 設定

#### Scenario: Build toolchain absent from final image
- **WHEN** 檢視最終 runtime 映像內容
- **THEN** 不含 `build-essential` 等僅建置期需要的套件

