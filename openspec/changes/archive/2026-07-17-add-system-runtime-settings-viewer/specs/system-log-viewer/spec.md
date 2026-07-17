# system-log-viewer Spec Delta

## MODIFIED Requirements

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
