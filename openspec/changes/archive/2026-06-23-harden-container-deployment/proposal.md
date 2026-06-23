## Why

TCRT 目前可以用 `docker-compose.app.yml` 跑起來，但要把它當成「可重複部署、可水平擴充的生產服務」仍有數個會直接造成資料遺失或安全退化的地雷，重開或重建容器就會踩到：

- **簽章金鑰每次重建容器就重生**：RSA 金鑰對寫在 repo 相對路徑 `keys/`（[`app/auth/password_encryption.py:20`](app/auth/password_encryption.py:20)；`mkdir` 於 [:32](app/auth/password_encryption.py:32)；缺檔即重新生成於 [:51](app/auth/password_encryption.py:51)），而此目錄**沒有**對應任何 compose volume。每換一個新容器就重生一把金鑰，導致先前以舊公鑰加密過、尚未送達的登入 payload 在重部署後**無法解密**。
- **關鍵密鑰缺漏時靜默退化而非快速失敗**：`JWT_SECRET_KEY` 未設定時回退為**空字串**（[`app/config.py:483-486`](app/config.py:483)），等於用空密鑰簽 JWT，安全性靜默消失卻照常啟動；provider credential 的 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 雖在使用時才報錯（[`app/services/automation/provider_credential_service.py:22`](app/services/automation/provider_credential_service.py:22)），但要等到實際存取 provider 才爆，而非啟動即知。
- **部署設定綁死開發者本機路徑**：[`docker-compose.app.yml:15-16`](docker-compose.app.yml:15) 直接寫死 `/Users/hideman/tcrt_files/...`，換一台機器即無法套用。
- **AI helper 調校無法進容器**：`config.yaml` 被列入 [`.dockerignore:16`](.dockerignore:16)，映像檔不含此檔，容器只能跑在預設值上，AI helper 的 prompt／模型調校全部失效且無感。
- **bootstrap 無併發保護**：`database_init.py` 在**每次**容器啟動時跑（[`docker/app-entrypoint.sh:12-14`](docker/app-entrypoint.sh:12)），無 advisory lock；多副本或平行重啟時 Alembic upgrade 會互相競爭。
- **背景服務迫使單一 worker、擋住水平擴充**：排程器用 `threading.Thread` + 60 秒輪詢（[`app/services/scheduler.py:73`](app/services/scheduler.py:73)、[:139](app/services/scheduler.py:139)），automation ticker 用 `asyncio.create_task`（[`app/services/automation/background.py:50-51`](app/services/automation/background.py:50)），兩者都在 `@app.on_event("startup")`（[`app/main.py:330`](app/main.py:330)）內無條件啟動，跨行程**沒有任何鎖或 leader election**。N 個副本就會有 N 份 Lark 組織同步與 N 份 automation run-sync（webhook 重複扇出、寫入互相覆蓋），因此目前只能把 `WEB_CONCURRENCY` 釘在 `1`（[README:96](README.md)）。

本變更的目的，是把 TCRT 變成「**無痛、安全地可容器化／可生產部署**」：先拆掉上述會吃掉資料或靜默削弱安全的地雷（P0），再把映像檔與啟動流程硬化、讓設定能可靠送進容器、讓 bootstrap 併發安全（P1），最後以單一 leader 模型解開背景服務對單 worker 的限制（P1/L），使 web 層能水平擴充而不重複執行背景工作。

## What Changes

- **持久化簽章金鑰**：金鑰目錄改為可由環境變數設定（例如 `RSA_KEY_DIR`／`KEYS_DIR`），並掛上 named volume；金鑰在容器重建後 SHALL 存活。並於 design 中比較「持久化檔案 vs. 移入 secret／DB」與既有金鑰的遷移路徑。
- **關鍵密鑰快速失敗**：當 `enable_auth` 為真而 `JWT_SECRET_KEY` 為空時，啟動即失敗（不再回退空字串）；當系統內已存在 automation provider 資料卻缺 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 時，啟動即以明確錯誤中止，而非延遲到首次解密。
- **部署狀態改由環境變數驅動**：以 `${ATTACHMENTS_ROOT_DIR}` / `${REPORTS_ROOT_DIR}`（與金鑰目錄）取代 `docker-compose.app.yml` 中寫死的本機路徑；compose 不再內含任何特定開發者路徑。
- **讓設定可達容器**：標準化 `APP_CONFIG_PATH` 掛載（或將 `config.yaml` 納入映像／改由掛載提供），使 AI helper 等調校在容器內可生效；並於文件說明預設與覆寫關係。
- **bootstrap 併發安全**：以 DB advisory lock 包住 `database_init.py` 的 schema 變更，或將其改成一次性 init job（取代 per-container 無鎖執行），確保同時只有一個行程在做 migration。
- **映像硬化**：改 multi-stage build、以非 root `USER` 執行、在 Dockerfile 內加 `HEALTHCHECK`、最終映像不含 `build-essential`，縮小體積與攻擊面。
- **生命週期遷移**：將 `@app.on_event("startup"/"shutdown")` 遷移為 FastAPI `lifespan`（移除 deprecated 用法），背景服務的啟停一併收斂於此。
- **背景服務單一 leader**：排程器與 automation ticker 改為跨行程**僅一個 leader** 執行（以 DB advisory-lock leader election，或獨立 worker 行程承載），非 leader 的副本不啟動這些背景迴圈。據此移除 `WEB_CONCURRENCY=1` 的硬性限制，使 web 層可多 worker／多副本部署而不重複執行背景工作。

非目標（Non-Goals）：

- **不**把 attachments／reports 遷移到物件儲存（S3／MinIO 等）；本次僅以 volume + 環境變數讓本地路徑可攜，物件儲存列為**後續工作**。
- **不**改變排程器與 automation 的**業務邏輯**（同步什麼、跑什麼、webhook 內容），只改其 singleton／leadership 模型與啟動位置。
- **不**導入外部協調元件（如 ZooKeeper／Redis lock／K8s Lease）作為 leader election 來源；以既有資料庫的 advisory lock 為準（design 說明選型與替代）。
- **不**重寫 CI／部署管線，也不在本次新增 Kubernetes manifest；僅讓映像與 compose 具備可被這些平台安全採用的前提。

## Capabilities

### New Capabilities
- `container-deployment`：定義 TCRT 容器化與生產部署的可觀察行為——簽章金鑰跨重建存活、關鍵密鑰缺漏時啟動快速失敗、容器狀態由 volume／環境變數驅動（無寫死主機路徑）、設定可達容器、bootstrap 併發安全，以及映像硬化（非 root、HEALTHCHECK、精簡映像）。
- `background-service-scaling`：定義排程器與 automation 背景工作的單一 leader 執行模型——跨副本**恰好一個** leader 執行排程／automation 工作，使 web 層可水平擴充而不產生重複的背景執行或 webhook 重複扇出。

### Modified Capabilities
<!-- 本變更僅新增上述兩個部署／擴充 capability；不變更既有 capability 的需求（不改 scheduler 業務邏輯、不改 system-bootstrap 的 schema 規格）。 -->

## Impact

- **資料庫**：bootstrap 以 DB advisory lock 序列化 schema 變更（或改一次性 init job），避免多副本平行 Alembic upgrade 競爭；背景服務的 leader election 亦以同一資料庫的 advisory lock 為協調來源。`scheduled_services` 等狀態仍存於 DB，本次不改其 schema，僅改「由誰執行」。
- **後端**：`@app.on_event` 遷移為 `lifespan`；排程器（[`app/services/scheduler.py`](app/services/scheduler.py)）與 automation ticker（[`app/services/automation/background.py`](app/services/automation/background.py)）的啟動改為僅 leader 行程觸發；啟動流程加入關鍵密鑰檢查（[`app/config.py`](app/config.py)）。
- **部署/Docker**：`Dockerfile` 改 multi-stage、非 root `USER`、加 `HEALTHCHECK`、最終映像去除 `build-essential`；`docker-compose.app.yml` 路徑改環境變數驅動並為金鑰目錄掛 named volume；`docker/app-entrypoint.sh` 的 bootstrap 加鎖或拆為 init job；`config.yaml` 經 `APP_CONFIG_PATH` 掛載或納入映像；`.dockerignore` 視解法調整。
- **安全**：移除空 `JWT_SECRET_KEY` 的靜默回退（缺漏即啟動失敗）；簽章金鑰持久化避免重部署造成的可解密性破壞；非 root 執行縮小容器逃逸面；provider 加密金鑰缺漏在有資料時即快速失敗。
- **相容性**：（migration／rollback／compatibility，必填）
  - **既有金鑰遷移**：升級時須把現存 `keys/private_key.pem`／`public_key.pem` 複製到新的持久化金鑰目錄並掛 volume，舊金鑰即被沿用、不重生；未掛 volume 時行為與今日相同（仍可開但無持久化），屬非破壞性但失去保護。
  - **快速失敗為破壞性升級點**：升級後若部署未設 `JWT_SECRET_KEY`（在 `enable_auth=true` 下），啟動將失敗——這是刻意的安全把關；rollback 只需還原舊映像即恢復（會回到空密鑰的不安全狀態）。文件 SHALL 明列此前置設定。
  - **leader election 的 rollback**：若 leader 機制需停用，可退回單副本 + `WEB_CONCURRENCY=1` 的舊行為（背景服務在唯一行程上跑），無資料轉換；advisory lock 為 best-effort 協調，連線中斷時 lock 自動釋放、由其他副本接手。
  - **bootstrap 相容**：advisory lock 對既有單副本部署為無感（只有一個取鎖者）；改 init job 為可選路徑，預設仍可沿用 entrypoint 內 bootstrap（加鎖版）。
  - **設定相容**：`APP_CONFIG_PATH` 未設定時回退既有預設值（與今日「容器跑預設」一致），故為非破壞性；提供 `config.yaml` 後即生效。
