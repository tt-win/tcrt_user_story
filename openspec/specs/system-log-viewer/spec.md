# system-log-viewer Specification

## Purpose
TBD - created by archiving change add-super-admin-log-viewer. Update Purpose after archive.
## Requirements
### Requirement: In-memory log 捕捉不改變 stdout 行為
系統 SHALL 以額外的 in-memory ring buffer handler 捕捉應用 log（root logger 與 `uvicorn.access`、`uvicorn.error` 各恰好捕捉一次），且 MUST NOT 改變既有 stdout log 輸出的格式與數量；`docker logs` SHALL 持續呈現與現況相同的完整 log。handler 掛載 MUST 為 idempotent，重複初始化不得造成重複捕捉。

#### Scenario: stdout 輸出不受影響
- **WHEN** 應用寫入任一 log record
- **THEN** 該 record 照常輸出到 stdout（格式與數量與未安裝本功能時一致），且同時被複製一份進入 in-memory buffer

#### Scenario: 各 logger 恰好捕捉一次
- **WHEN** root logger、`uvicorn.access`、`uvicorn.error` 各寫入一筆 log
- **THEN** buffer 中每筆各出現恰好一次，不因 propagate 或重複掛載而重複

#### Scenario: 重複掛載被防止
- **WHEN** logging 初始化流程被執行多次（如測試或 reload）
- **THEN** ring buffer handler 只掛載一份，後續 log 不被重複捕捉

#### Scenario: buffer 具容量上限
- **WHEN** buffer 內筆數達到設定上限（設定值非法或未設定時使用安全預設值，且不得超過硬上限）
- **THEN** 最舊的 record 被移除，新 record 進入 buffer，且不影響 log 寫入路徑的效能與正確性

#### Scenario: 捕捉元件故障不影響主服務
- **WHEN** ring buffer handler 內部發生任何例外
- **THEN** 例外被吞掉且不向 log 呼叫端傳播，stdout 輸出與業務功能不受影響

#### Scenario: 訊息保留 traceback 並標示截斷
- **WHEN** log record 帶有 exc_info 或多行訊息，或格式化後長度超過單條上限
- **THEN** buffer 儲存含 traceback 的完整格式化內容（多行保留）；超長時截斷並附上明確的截斷標記

### Requirement: 跨 thread 捕捉與並發存取安全
log 可能由非 event-loop thread 寫入，SSE 消費發生在 event loop。系統 SHALL 以明確的同步機制保護 buffer、序號配發與訂閱者名單（單一 lock）。跨 thread 投遞 SHALL 採「有界 pending 結構 + 合併喚醒」：寫入端直接對各訂閱者的有界 pending 結構 append（滿即淘汰最舊未投遞筆），並僅在無未執行喚醒時排程一次 event-loop 喚醒；MUST NOT 每筆 log 個別排程 event-loop callback（有界 queue 無法約束 callback backlog）。log 寫入路徑 MUST NOT 因任何訂閱者而阻塞。

#### Scenario: 非 event-loop thread 寫入 log
- **WHEN** 背景 thread 寫入 log 且存在作用中的 SSE 訂閱者
- **THEN** record 正確進入 buffer 並投遞給訂閱者，無例外、無資料競態

#### Scenario: snapshot 與 append 併發
- **WHEN** 快照讀取與新 log 寫入同時發生
- **THEN** 快照回傳一致性的複本，不發生迭代中修改錯誤

#### Scenario: 慢速消費者不阻塞 log 路徑
- **WHEN** 某訂閱者的有界 pending 結構已滿
- **THEN** 淘汰該訂閱者最舊的未投遞訊息（可由序號缺口察覺），log 寫入路徑不被阻塞、其他訂閱者不受影響

#### Scenario: 投遞不得外洩例外
- **WHEN** 跨 thread 投遞過程發生 pending 已滿、loop 已關閉或任何內部錯誤
- **THEN** event loop exception handler 不得收到任何例外，emit 呼叫端亦不受影響

#### Scenario: 喚醒排程不隨 log 筆數成長
- **WHEN** log 產生速度快於 event loop 消化速度（event loop 暫未 yield 期間大量 emit）
- **THEN** 每個訂閱者同時至多存在一個未執行的 event-loop 喚醒排程，pending 資料受有界結構約束，不隨 log 筆數無界累積

#### Scenario: 訂閱建立與回放原子一致
- **WHEN** 新訂閱建立的同一瞬間持續有新 log 寫入
- **THEN** 訂閱註冊、replay snapshot 複製與回放分界序號在同一 critical section 內決定；client 先收到分界前的存量回放、再收到分界後的即時事件，無遺失且無重複

### Requirement: Log 記錄可選 structured 欄位
系統 log 捕捉層與快照／串流 API 的每筆 record SHALL 在既有必填欄位（seq、timestamp、level、logger_name、message、pid）之外，MAY 包含可選字串欄位 `event_code` 與 `outcome`。當 message **最後一行**的行尾符合 ops 尾碼慣例（最後一個 ` | ` 之後含 `event=<code>` 與 `outcome=<outcome>`，code 匹配 `[a-z0-9._-]+`）時，捕捉層 MUST 解析並填入；否則 MUST 省略可選欄位。解析失敗或 message 含 traceback 多行時，MUST 只嘗試最後一行且失敗時不得丟棄整筆 log 或影響 stdout handler 拓樸。

#### Scenario: 可解析尾碼帶出 event_code
- **WHEN** message 為 `hello | event=tcrt.ops.example.action outcome=failure` 並被捕捉
- **THEN** snapshot 與 SSE log event 中該 record 的 event_code 與 outcome 正確，message 仍為完整原文

#### Scenario: human 正文含分隔符時以最後一個分隔為準
- **WHEN** message 為 `a | b | event=tcrt.ops.example.action outcome=success`
- **THEN** event_code 解析為 tcrt.ops.example.action（以最後一個 ` | ` 之後為準）

#### Scenario: 普通 message 仍可捕捉
- **WHEN** free-form log 不含 structured 尾碼
- **THEN** record 含既有必填欄位；event_code 與 outcome 省略或為 null

### Requirement: Snapshot 與 SSE 共用 record schema
`GET /api/admin/system-logs` 快照中的每筆 record 與 SSE `log` event 的 JSON payload SHALL 使用同一 record schema（必填欄位相同；可選 event_code／outcome 規則相同）。

#### Scenario: stream 與 snapshot 欄位一致
- **WHEN** 同一筆含 event_code 的 log 分別出現在 snapshot 與 SSE log event
- **THEN** 兩處皆含相同 seq 語意下的 level、message、event_code、outcome 等對應欄位

### Requirement: 前端可顯示 event_code
`/system-logs` 的 Logs 分頁 SHALL 在 record 具有 event_code 時顯示該值；無該欄位時行為與現況一致。MUST NOT 引入 server-side keyword 或 `q` 查詢參數。

#### Scenario: 有 event_code 時顯示
- **WHEN** Super Admin 檢視含 event_code 的 log 列
- **THEN** UI 可見該 event_code

#### Scenario: 仍無 server keyword
- **WHEN** 客戶端呼叫 system-logs 快照或串流 API
- **THEN** 伺服器不接受亦不依 keyword／q 參數過濾

### Requirement: Super Admin 專用 log 快照 API
系統 SHALL 提供 log 快照查詢 API `GET /api/admin/system-logs`，MUST 僅允許 Super Admin 角色存取、MUST NOT 出現在公開 API schema。查詢參數 SHALL 僅有 `level`（最低門檻語意）、`logger`（名稱前綴比對）、`limit`（有預設值與伺服器上限，超過即收斂；語意為 tail——篩選後取**最新** N 筆再依序號遞增回傳）；**MUST NOT 提供 keyword 參數**（避免敏感搜尋字串進入 access log 與 URL）。回應 SHALL 依序號遞增排序，附 worker instance 識別與序號範圍，且 SHALL 帶 `Cache-Control: no-store` 與 `Pragma: no-cache`。每筆 record SHALL 含序號、ISO 8601 UTC 時間戳、level、logger 名稱、訊息、PID，並 MAY 含 `event_code` 與 `outcome`。

#### Scenario: Super Admin 取得快照
- **WHEN** Super Admin 以有效憑證呼叫 `GET /api/admin/system-logs`（可帶 level / logger / limit）
- **THEN** 回傳符合條件、依序號遞增的 record（每筆含序號、ISO 8601 UTC 時間戳、level、logger 名稱、訊息、PID；若有則含 event_code／outcome），以及 worker instance 識別與最舊/最新序號

#### Scenario: level 為最低門檻
- **WHEN** 以 `level=WARNING` 查詢
- **THEN** 回傳 WARNING 與更嚴重等級的 record，不含 INFO/DEBUG

#### Scenario: limit 超過上限被收斂
- **WHEN** 呼叫端帶入超過伺服器上限的 limit
- **THEN** 伺服器以上限值處理，不報錯、不放行極端值

#### Scenario: limit 取最新而非最舊
- **WHEN** 篩選後符合的 record 數多於 limit
- **THEN** 回傳序號最大的 N 筆（log tail），再依序號遞增排序，不得回傳 buffer 最舊的 N 筆

#### Scenario: 非 Super Admin 被拒絕
- **WHEN** 未登入使用者或非 Super Admin 角色呼叫快照或串流 API
- **THEN** 回傳 401 或 403，且不洩漏任何 log 內容

#### Scenario: 可選 structured 欄位不破壞舊客戶端
- **WHEN** 回應中部分 record 含 event_code／outcome
- **THEN** 其餘必填欄位語意不變，未知欄位可被舊客戶端忽略

### Requirement: Super Admin 專用 SSE 即時串流 API
系統 SHALL 提供 SSE 串流 API `GET /api/admin/system-logs/stream`，MUST 僅允許 Super Admin 存取、MUST NOT 出現在公開 API schema。回應 SHALL 帶 `Cache-Control: no-store`、`Pragma: no-cache`、`X-Accel-Buffering: no`。SSE 契約 SHALL 定義：`id` 為 record 序號；`meta` event（連線首個 event，含 worker instance 識別、PID、序號範圍、串流生命週期）；`log` event（record JSON）；`gap` event（回放無法涵蓋時，含估計遺失筆數）；`end` event（達最大生命週期收尾）；並週期性送出 keep-alive comment。

#### Scenario: 即時串流與存量回放
- **WHEN** Super Admin 開啟串流並帶上先前收到的最後序號與 instance 識別，且 instance 相符
- **THEN** 先送 `meta`，回放 buffer 中序號較新的存量 record，再持續推送新 record

#### Scenario: instance 不符時全量回放
- **WHEN** 重連帶上的 instance 識別與目前 worker 不符（不同 worker 或應用已重啟）、或帶了序號但未帶 instance 識別
- **THEN** 伺服器忽略舊序號 cursor，送出 `meta` 後全量回放 buffer

#### Scenario: 序號確有遺失才標示缺口
- **WHEN** instance 相符且 `since_seq < oldest_seq - 1`
- **THEN** 先送 `gap` 且遺失筆數為 `oldest_seq - since_seq - 1`，再從 `oldest_seq` 回放；若 `since_seq = oldest_seq - 1`（恰可完整涵蓋）則完整回放且不送 `gap`

#### Scenario: 序號超前或非法視為 reset
- **WHEN** `since_seq > latest_seq` 或序號非法（非整數字串如 `abc`、負數如 `-1`）
- **THEN** 忽略 cursor，視為未提供而全量回放；連線以 200 建立 SSE，MUST NOT 因參數型別驗證回 422（參數以 raw string 接收、於 handler 內解析）

#### Scenario: 空 buffer 的邊界值
- **WHEN** buffer 為空時建立連線
- **THEN** `meta` 中 oldest/latest 序號為空值（null），不回放存量、不送 `gap`，直接進入即時推送

#### Scenario: 串流連線數上限
- **WHEN** 同時串流連線數已達設定上限而再開新連線
- **THEN** 新連線被拒絕並回傳 429

#### Scenario: 串流具最大生命週期
- **WHEN** 串流連線持續達到設定的最大生命週期
- **THEN** 伺服器送出 `end` event 並關閉連線

#### Scenario: 串流期間權限失效
- **WHEN** 串流建立後使用者 token 到期、帳號停用或被降權
- **THEN** 既有連線最遲於最大生命週期屆滿時終止，重新連線時整條認證與授權鏈重新驗證並回傳 401 或 403

#### Scenario: 連線終止必釋放資源
- **WHEN** 串流因 client 斷線、取消、例外或生命週期屆滿而結束
- **THEN** 該訂閱者被解除註冊、stream slot 被釋放，後續連線不受殘留狀態影響

### Requirement: 敏感資訊遮罩
API（快照與串流）對外輸出 log 內容前 SHALL 套用 redact filter，以大小寫不敏感規則遮罩疑似 secret 的片段：Bearer token、類 JWT 字串，以及常見秘密欄位名（至少含 `password`、`secret`、`api_key`、`access_token`、`refresh_token`、`client_secret`、`token`、`authorization`）在 `key=value`、URL query、JSON（`"key": "..."`）與 Python dict repr（`'key': '...'`）格式中的值。

#### Scenario: token 片段被遮罩
- **WHEN** buffer 中的 log 訊息含有 `Bearer <token>` 或類 JWT 字串
- **THEN** 快照與串流輸出中該片段被替換為遮罩標記，不以明文送達瀏覽器

#### Scenario: 多種賦值格式被遮罩
- **WHEN** log 訊息含 `?token=...` URL query、`"access_token": "..."` JSON、`'api_key': '...'` dict repr 或大小寫變體（如 `PASSWORD=...`）
- **THEN** 各格式中的秘密值均被遮罩標記取代

### Requirement: log viewer 存取稽核
Super Admin 成功建立 log 串流（通過權限檢查並取得 stream slot）時，系統 SHALL 嘗試寫入一筆 audit 紀錄：`ActionType.READ`、`ResourceType.SYSTEM`、固定 resource_id（`system-logs-stream`），含使用者、來源 IP、User-Agent 與 worker instance 識別。audit 停用或寫入失敗 SHALL NOT 阻斷串流（與既有 audit service 的 best-effort 行為一致）。

#### Scenario: 開啟串流留下稽核紀錄
- **WHEN** audit 功能啟用且 Super Admin 成功建立 log 串流連線
- **THEN** audit 系統新增一筆含上述欄位的存取紀錄

#### Scenario: audit 失敗不阻斷串流
- **WHEN** audit 停用或寫入失敗
- **THEN** 串流照常建立與推送，錯誤僅記錄於伺服器 log

### Requirement: Super Admin 專用即時 log 檢視頁面

系統 SHALL 提供 `/system-logs` 頁面：即時 tail、暫停/續播、level 與 logger 篩選（含一鍵隱藏 access log）、keyword 篩選與 highlight（**完全於前端對已取得資料進行，keyword MUST NOT 送往伺服器**）、下載目前畫面內容，並常駐顯示 worker instance 識別與 PID。頁面導覽入口 SHALL 位於既有「數據與記錄」下拉選單且僅對 Super Admin 顯示；頁面文案 SHALL 提供 en-US、zh-CN、zh-TW 三語系。

頁面 SHALL 以分頁（tabs）組織：**Logs** 分頁承載上述即時 log 能力；**Runtime Settings** 分頁承載 runtime 運作設定唯讀檢視（契約見 capability `system-runtime-settings-viewer`）。路由 MUST 維持單一 `/system-logs`。HTML 頁面 shell 的後端授權模型 MUST 與本 capability 既有行為一致（導覽入口隱藏；log 與設定**資料**由受 `require_super_admin` 保護的 API 提供；不得僅因本變更而要求 HTML GET 本身必須後端拒絕非 Super Admin，除非另有獨立 change 強化 HTML route）。

Tab 面板（panel）SHOULD 具備 `tabindex="0"` 以符合可聚焦內容區之無障礙慣例；鍵盤切換 tab 行為 MAY 沿用 Bootstrap 5.3 tab 外掛（方向鍵、Home／End）。

#### Scenario: 即時 tail 與自動捲動

- **WHEN** Super Admin 開啟頁面且新 log 持續產生
- **THEN** 新 record 即時出現並自動捲動至最新；使用者手動上捲時暫停跟隨，回到底部後恢復

#### Scenario: keyword 僅在前端處理

- **WHEN** 使用者輸入 keyword 進行篩選或 highlight
- **THEN** 比對只發生在瀏覽器已取得的資料上，keyword 不出現在任何對伺服器的請求中

#### Scenario: 篩選與 highlight

- **WHEN** 使用者設定 level／logger 篩選或輸入 keyword
- **THEN** 畫面僅顯示符合條件的 record，keyword 命中片段被 highlight

#### Scenario: 斷線自動重連與未授權停止

- **WHEN** 串流因斷線或 `end` event 結束
- **THEN** 前端自動帶序號與 instance 識別重連；若收到 401 或 403 則停止重連並顯示未授權狀態

#### Scenario: 重連具退避

- **WHEN** 重連持續失敗（如伺服器停機或持續回 429/500）
- **THEN** 前端以指數退避加抖動重試（429 遵循 `Retry-After`），不形成緊密重連迴圈；成功收到 `meta` 後退避重置

#### Scenario: 暫停不中斷資料接收

- **WHEN** 使用者按下暫停
- **THEN** DOM 更新與自動捲動停止，但串流與底層資料模型持續接收（仍受環形上限）；續播時以資料模型重繪

#### Scenario: worker instance 切換時重置前端資料

- **WHEN** 重連收到的 `meta` 中 worker instance 識別與目前資料模型的來源不同
- **THEN** 前端清空既有 record 資料模型、畫面與 cursor，插入「資料來源已切換」標示後接受新 worker 的全量回放；不得將不同 instance 的序號混入同一序列

#### Scenario: 遺失訊息在畫面上標示

- **WHEN** 前端偵測到序號缺口或收到 `gap` event
- **THEN** log 流中插入「遺失 N 筆」標示，重連回放可涵蓋的部分自然回補

#### Scenario: 非 Super Admin 看不到入口

- **WHEN** 非 Super Admin 角色瀏覽系統
- **THEN** 導覽中不顯示 system logs 入口；即使直接輸入頁面網址，其後續 API 呼叫仍被後端拒絕

#### Scenario: 前端顯示行數上限

- **WHEN** 累積的 log 筆數超過前端上限
- **THEN** DOM 與底層 record 資料模型同步環形移除最舊筆，兩者皆維持有界，不得只清 DOM 而讓資料模型無界成長

#### Scenario: 頁面含 Logs 與 Runtime Settings 分頁

- **WHEN** Super Admin 開啟 `/system-logs`
- **THEN** 頁面顯示可切換的 Logs 與 Runtime Settings 分頁，預設顯示 Logs 分頁的 log 工具列與輸出區

#### Scenario: Logs 與 Settings 分頁狀態隔離

- **WHEN** 使用者自 Logs 切換至 Runtime Settings 再切回，且未離開頁面
- **THEN** Logs 分頁的串流連線、篩選狀態與畫面緩衝不得僅因分頁切換而被強制銷毀；Runtime Settings 快照 API 失敗時使用者仍可使用 Logs 分頁

#### Scenario: Settings 與 Logs 的 worker mismatch 判定

- **WHEN** Logs 與 Settings 兩側的 `worker_instance_id` 皆為非空字串且值不同
- **THEN** UI 顯示 worker mismatch 提示

#### Scenario: instance 缺失時不因 PID 判定 mismatch

- **WHEN** Logs 或 Settings 任一方缺少非空的 `worker_instance_id`
- **THEN** UI 不得僅因 PID 不同而顯示 mismatch（PID 僅供顯示）

### Requirement: log 內容以未受信任輸入處理（XSS 防護）
前端渲染 log 訊息與 keyword highlight 時 SHALL 僅以 text node（`textContent` / `createTextNode`）與逐片段建立的 `<mark>` 元素寫入 DOM；MUST NOT 將未 escape 的 log 內容或 keyword 插入 `innerHTML`；keyword 用於比對前 SHALL escape regex 特殊字元。

#### Scenario: 惡意 HTML 不被執行
- **WHEN** log 訊息含 `<img onerror=...>`、`<script>` 等 HTML/JS 注入字串且被顯示或被 highlight
- **THEN** 內容以純文字呈現，不觸發任何 script 或事件處理器

#### Scenario: 特殊字元安全處理
- **WHEN** log 訊息或 keyword 含引號、換行或 regex 特殊字元
- **THEN** 顯示與 highlight 行為正確，無語法錯誤、無注入

### Requirement: 設定集中管理且全數有界
log viewer 的所有可調參數（buffer 筆數、同時串流數、單條訊息長度、訂閱 pending 深度、keep-alive 間隔、串流最大生命週期）SHALL 整合於應用既有集中設定機制（`app/config.py` 的 Settings），每項 SHALL 定義安全預設值與**明確的合法範圍（含下限與上限）**——時間類參數的下限尤須防止過短值（如 1 秒 lifetime 造成持續重連與 audit 噪音）；範圍外或非法值 SHALL fallback 到預設值而非失敗或放行。除單欄位上限外，系統 SHALL 對容量組合施加固定的 per-worker aggregate budget（buffer 與訂閱端的「筆數 × 單條長度」乘積上限）；組合超出預算時相關欄位 SHALL 整組回落預設值並記錄 warning。文件 SHALL 說明所有容量均為 per-worker，總量須乘上 `WEB_CONCURRENCY`。

#### Scenario: 未設定時使用預設值
- **WHEN** 相關 env 均未設定
- **THEN** 功能以文件記載的預設值正常運作

#### Scenario: 極端值被拒絕
- **WHEN** env 被設為非正整數、低於合法下限（如 keep-alive 1 秒、lifetime 10 秒）或超過硬上限的值
- **THEN** 系統使用預設值，不因此啟動失敗，也不配置極端資源或極端行為

#### Scenario: 單欄位合法但組合超出預算
- **WHEN** 各欄位皆在單欄位上限內，但「筆數 × 單條長度」乘積超過 per-worker aggregate budget
- **THEN** 相關欄位整組回落預設值並記錄 warning，實際配置的記憶體維持在預算內

### Requirement: 多 worker 視野限制須透明
在多 worker 部署（`WEB_CONCURRENCY > 1`）下，單一連線僅呈現處理該連線之 worker 的 log。系統 SHALL 於快照回應與 SSE `meta` event 提供 worker instance 識別（PID + 啟動識別），頁面 SHALL 常駐顯示，且文件 SHALL 記載此限制與 `docker logs` fallback。

#### Scenario: 顯示 worker 識別
- **WHEN** Super Admin 檢視快照或串流
- **THEN** 回應與頁面明確標示資料來源的 worker instance 識別與 PID

