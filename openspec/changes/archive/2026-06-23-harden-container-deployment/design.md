## Context

TCRT 已有 `Dockerfile` 與 `docker-compose.app.yml`，能在開發機跑起來，但要當成「可重複部署、可水平擴充」的服務，有數個跨模組的地雷已在 proposal 列出。本設計聚焦四個需要決策的面向：**簽章金鑰持久化與遷移**、**背景服務的 leader election**、**bootstrap 的 advisory-lock 取法**，以及**rollback／相容性**。其餘（compose 路徑改環境變數、Dockerfile multi-stage/非 root/HEALTHCHECK、`config.yaml` 掛載、`@app.on_event` → `lifespan`）為相對直接的硬化工作，於 tasks 追蹤，不在此展開設計取捨。

直接沿用的既有事實：

- 金鑰服務 [`PasswordEncryptionService`](app/auth/password_encryption.py:16) 已是「缺檔則生成、有檔則載入」的 classmethod 模式（[load:35](app/auth/password_encryption.py:35) / [generate:48](app/auth/password_encryption.py:48)）；唯一缺口是 `KEY_DIR`（[:20](app/auth/password_encryption.py:20)）寫死且未掛 volume。
- provider 加密金鑰**已**會在缺漏時丟 `CredentialEncryptionError`（[`provider_credential_service.py:24`](app/services/automation/provider_credential_service.py:24)），但只在實際加解密時觸發。
- 排程器狀態存於 DB（`scheduled_services`），執行卻綁在行程內 thread（[`scheduler.py:73`](app/services/scheduler.py:73)）；automation ticker 為行程內 asyncio task（[`background.py:50`](app/services/automation/background.py:50)）。兩者皆於 [`startup_event`](app/main.py:330) 無條件啟動。
- 資料庫存取走既有 async boundary／engine（`app/database.py`），故 advisory lock 可直接借用同一連線層，無須新元件。

## Goals / Non-Goals

**Goals:**
- 金鑰在容器重建後存活，且提供既有金鑰的明確遷移路徑（不重生、不破壞既有可解密性）。
- 背景服務跨副本恰好一個 leader 執行，使 web 層可多 worker／多副本而不重複扇出；解開 `WEB_CONCURRENCY=1`。
- bootstrap 在平行啟動下序列化，避免雙重 migration。
- 變更可安全 rollback，且對既有單副本部署無感。

**Non-Goals:**
- 不把 attachments／reports 移到物件儲存（後續工作）。
- 不改排程／automation 的業務邏輯，只改 singleton／leadership 模型與啟動位置。
- 不引入外部協調元件（ZooKeeper／Redis／K8s Lease）作為 leadership 來源。

## Decisions

### D1：金鑰持久化採「可設定目錄 + named volume」，不移入 DB／secret（本次）
`KEY_DIR` 改讀環境變數（如 `RSA_KEY_DIR`），缺省回退現行 repo 相對 `keys/`；compose 為該目錄掛 named volume。理由：對既有「檔案載入」程式衝擊最小，遷移只是把現有 `*.pem` 搬進 volume；可解密性立即保住。
- *替代 A：金鑰移入 DB（如隨設定表）*——可天然隨 DB 一起持久化與備份，但需改寫載入路徑、考慮金鑰在 DB 的加密保護（又回到「用什麼金鑰加密金鑰」的問題），本次過重，列為後續可選。
- *替代 B：以 container secret／外部 KMS 注入*——最安全，但需部署平台支援與額外運維；非本次無痛目標範圍。設計保留此演進方向（D1 的目錄抽象不阻擋日後改由 secret 提供路徑）。

### D2：既有金鑰遷移為「複製進 volume，啟動即沿用」
升級程序：建立持久化目錄並掛 volume → 將現存 `keys/private_key.pem`、`keys/public_key.pem`（連同 `0600` 權限）複製進去 → 設定 `RSA_KEY_DIR` 指向它。啟動時 [`initialize`](app/auth/password_encryption.py:27) 走「有檔則載入」分支，**不**重生。
- 驗收：以私鑰指紋於遷移前後比對相同；舊公鑰加密的樣本 payload 解密成功。
- 邊界：未掛 volume 時退化為今日行為（可啟動但每次重建重生），屬非破壞性但失去保護；文件 SHALL 標明這是必須的部署前置。

### D3：背景服務 leadership 採 DB advisory lock（單一固定 lock key）
以資料庫的 advisory lock（單一固定 key，代表「背景服務 leader」）作為 leadership 來源：行程於 `lifespan` 啟動時嘗試非阻塞取鎖，**取得者**才 `task_scheduler.start()` 與 `automation_background_manager.start()`；未取得者略過背景啟動但照常服務 HTTP。lock 與行程／連線生命週期綁定——行程結束或連線斷，lock 自動釋放，其他副本可接手。
- 理由：協調來源就是系統唯一的真實狀態存放處（DB），無需新增 Redis／ZK；advisory lock 為 best-effort 但對「單例背景工作」的語意足夠（業務寫入本身仍由 DB 事務保護）。
- *替代 A：獨立 worker 行程（entrypoint 分流 web / worker）*——語意最乾淨（web 完全無背景碼），但需改部署拓撲與 compose 服務切分；設計**容許**此路徑作為 D3 的等價實作（spec 以「恰好一個 leader」為準，不綁定機制），可作為後續演進。
- *替代 B：DB 上自建 leases 表 + 心跳/TTL*——可跨「同一連線」之外更彈性，但要自行處理時鐘、過期、續租，複雜度高於 advisory lock；否決為本次預設，保留為未來在多節點 DB 連線池下的強化選項。

### D4：leader 接手語意——非阻塞重試 + 失效釋放
非 leader 行程定期（低頻）嘗試取鎖；當現任 leader 失效使 lock 釋放，下一次嘗試的行程成為新 leader 並啟動背景服務。任一時刻僅一個持鎖者，故不會雙 leader。排程器本身已具「啟動時回收殘留 running 狀態」能力（[`scheduler.initialize(recover_running=True)`](app/services/scheduler.py:60)），接手後可回收前任未竟狀態，避免工作永久停擺。
- 風險：接手有延遲（取決於重試間隔）；可接受，因排程為分鐘級、automation ticker 為 60s／1h 級，非即時關鍵路徑。

### D5：bootstrap 用 DB advisory lock 序列化，預設仍走 entrypoint
`database_init.py` 的 schema 變更段以一支**獨立**的 bootstrap advisory lock（與 D3 的背景 leader lock 不同 key）包住：平行啟動時僅取鎖者執行 Alembic upgrade，其餘等待鎖釋放後再繼續（schema 已就緒即 no-op）。entrypoint（[`app-entrypoint.sh:12`](docker/app-entrypoint.sh:12)）仍呼叫 bootstrap，但走加鎖版本；`SKIP_DATABASE_BOOTSTRAP` 開關語意保留。
- *替代：拆成 Kubernetes/Compose 的一次性 init job*——最符合雲原生慣例，列為**可選路徑**（spec 以「同一時間僅一個行程做 schema 變更」為準，不強制機制），預設保留 entrypoint 加鎖以對既有單副本部署無感。

### D6：`@app.on_event` → `lifespan`，背景啟停收斂於此
將 [`startup_event`](app/main.py:330) / [`shutdown_event`](app/main.py:400) 遷到 `lifespan` async context manager：進入時做密鑰檢查、audit/USM/金鑰初始化、嘗試背景 leadership；離開時 `stop()` 排程器與 automation ticker（僅 leader 行程實際持有並停止）。
- 理由：移除 deprecated 用法，並讓「是否啟動背景服務」的判斷與啟停成對地落在同一處，降低多 worker 下的啟停推理成本。

### D7：快速失敗的範圍與時機
JWT 檢查置於設定載入／啟動最前段（[`AuthConfig.from_env`](app/config.py:480) 或 `lifespan` 起點）：`enable_auth=true` 且 `JWT_SECRET_KEY` 空 → 立即 raise，不再回退空字串。provider 金鑰檢查置於 `lifespan`：當 DB 內存在 provider credential 列且 `AUTOMATION_PROVIDER_ENCRYPTION_KEY` 缺 → 立即 raise（沿用 [`provider_credential_service`](app/services/automation/provider_credential_service.py:14) 的錯誤訊息語意），而非延遲到首次解密。
- 注意：provider 檢查需「有資料才強制」，避免全新空庫部署被無謂擋下（無 provider 時不需此金鑰）。

## Risks / Trade-offs

- **[未掛 volume 仍會重生金鑰]** → D2 文件把「掛 volume + 設 `RSA_KEY_DIR`」列為部署前置；未掛時退化為今日行為（非破壞，但失保護）。
- **[advisory lock 為 best-effort]** → 連線中斷即釋放可能造成短暫雙啟動窗口；以「非阻塞取鎖 + 任一時刻單一持鎖者」收斂，且業務寫入本身由 DB 事務保護，重複扇出風險限於極短交接窗。可接受。
- **[快速失敗使既有未設 `JWT_SECRET_KEY` 的部署升級後起不來]** → 這是刻意把關；在 proposal 相容性與 README 明列前置設定；rollback 還原舊映像即恢復（回到不安全的空密鑰狀態）。
- **[leader 接手延遲]** → 排程／ticker 為分鐘～小時級，延遲可接受；接手後靠既有 `recover_running` 回收殘留狀態。
- **[bootstrap 鎖與背景 leader 鎖混用]** → D5 明確使用**不同** lock key，兩者互不阻擋（bootstrap 取鎖時背景服務尚未啟動）。

## Migration Plan

1. **金鑰**：建立持久化目錄與 named volume → 複製現存 `keys/*.pem`（含 `0600`）→ 設 `RSA_KEY_DIR`。啟動後以私鑰指紋驗證未變（D2）。
2. **密鑰前置**：部署環境設妥 `JWT_SECRET_KEY`；若已有 provider 資料，設妥 `AUTOMATION_PROVIDER_ENCRYPTION_KEY`。未設者升級後啟動會快速失敗——屬預期把關。
3. **compose/設定**：以 `${ATTACHMENTS_ROOT_DIR}`／`${REPORTS_ROOT_DIR}` 取代寫死路徑；經 `APP_CONFIG_PATH` 掛 `config.yaml`。
4. **bootstrap**：沿用 entrypoint（加鎖版）即可；採 init job 為可選。
5. **擴充**：確認 leader election 生效（多行程僅一份背景執行）後，方移除 `WEB_CONCURRENCY=1` 限制並調大 worker／副本。

**Rollback：**
- 還原舊映像／舊 compose 即恢復原行為；金鑰已在 volume 內，rollback 不影響可解密性。
- 停用 leader 機制：退回單副本 + `WEB_CONCURRENCY=1`，背景服務於唯一行程上跑，無資料轉換。
- bootstrap advisory lock 對單副本無感（唯一取鎖者）；移除亦無資料影響。
- 快速失敗 rollback：還原舊版會回到空 `JWT_SECRET_KEY` 的不安全回退——僅在緊急時為之，並儘速補設密鑰。

## Open Questions（實作後已解決）

- ~~advisory lock 在各 DB 後端是否皆支援 session-scoped 自動釋放？~~ **已解決**：實作於 `app/runtime_locks.py`——PostgreSQL 用 `pg_advisory_lock` / `pg_try_advisory_lock`、MySQL 用 `GET_LOCK`（皆 session-scoped，連線中斷即自動釋放）；**SQLite 及其他**後端則退回 `portalocker` 檔案鎖（行程結束 / handle 關閉即釋放）。因此不需自建 leases+TTL，亦無「某後端不支援」的缺口。bootstrap 鎖在 PG/MySQL 改連 maintenance DB，避免 target DB 尚未建立時無法上鎖。
- ~~leader 是否對運維可見？~~ **已解決（log 標記）**：leader 行程啟動時記 `背景服務已啟動（本行程為 leader）`，非 leader 記 `本行程非背景服務 leader…將定期重試接手`，接手時記對應訊息。暫不加健康端點。
- ~~`config.yaml` 採掛載或納入映像？~~ **已解決（掛載）**：`.dockerignore` 維持排除 `config.yaml`，compose 以 `${APP_CONFIG_FILE:-./config.yaml}:/app/config.yaml:ro` 唯讀掛載並設 `APP_CONFIG_PATH=/app/config.yaml`；`app/config.py` 與 `app/db_migrations.py` 皆讀 `APP_CONFIG_PATH`。
