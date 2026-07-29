# personal-dashboard Specification

## Purpose
TBD - created by archiving change add-personal-dashboard. Update Purpose after archive.
## Requirements
### Requirement: Current-user Dashboard dispatch MUST be server authoritative

系統 SHALL 提供 `GET /api/dashboard`，以既有 Bearer authentication 取得目前 active user，且不得接受或使用 user id、role、team id、URL 作為 request scope。回應 MUST 帶 `Cache-Control: no-store` 與唯一 `dashboard_type`：目前角色為 `SUPER_ADMIN` 時為 `system_administration`；`ADMIN`、`USER`、`VIEWER` 時為 `personal`。每次請求 MUST 依伺服器當下的 User record 重新判定，且 response MUST 只含該類型 Dashboard 的資料。

#### Scenario: 一般角色取得 Personal Dashboard

- **WHEN** `USER`、`ADMIN` 或 `VIEWER` 以有效 Bearer token 呼叫 `GET /api/dashboard`
- **THEN** 系統回傳 200、`dashboard_type = "personal"`、`Cache-Control: no-store`，且 body 不含 System Administration Dashboard section

#### Scenario: Super Admin 取得系統管理 Dashboard

- **WHEN** `SUPER_ADMIN` 以有效 Bearer token 呼叫 `GET /api/dashboard`
- **THEN** 系統回傳 200、`dashboard_type = "system_administration"`、`Cache-Control: no-store`，且 body 不含 Personal Dashboard 的 resume、assigned、preference 或成果 section

#### Scenario: Client 不能偽造 Dashboard 角色或 scope

- **WHEN** client 修改 `localStorage.user_role`，或在 request 加入 user、role、team、URL query parameter
- **THEN** 回應類型與資料範圍仍只由 authenticated current user 決定，且 query parameter 不會擴張任何資料範圍

#### Scenario: 角色或帳號狀態在頁面開啟後改變

- **WHEN** 使用者被降權、停用或 token 失效後再次請求 Dashboard
- **THEN** 系統依當下帳號回傳另一種合法 Dashboard 或 401，且不得回傳先前的 Super Admin payload

### Requirement: Personal Dashboard SHALL expose only actionable, current-user work

Personal Dashboard MUST 以目前登入者為唯一 actor／assignee 範圍，且所有 row MUST 屬於 server-resolved、active、visible Team。`resume` MUST 是最多十筆、依 `last_activity_at` 與 deterministic identity tie-breaker 排序的跨功能 union。Test Run 候選必須同時符合：目前解析為該使用者、Run status 為 `active`、具既有 Test Run write capability，且存在 `changed_by_id == str(current_user.id)` 的實際 execution transition，並依 Team id＋Run id 去重；另可由本人 Audit 的 allowlisted `CREATE`／`UPDATE` 補入 Test Case、User Story Map、Automation Hub，Automation Hub 的功能層級返回亦可採本人最近 DELETE。Audit-derived candidate MUST 受可見 Team、固定 resource kind、受驗證 resource id 與 server route template 限制：Test Case `batch_`／`bulk_` 事件只能回 team-level management，User Story Map composite id 只能取正整數 map prefix 回 map route。Test Case／Map 的最新 resource-level 事件為 DELETE 時，較舊事件 MUST NOT 重新產生 stale deep link；Map relation DELETE 可回尚存在的 Map。READ 等不具續作語意的 Audit action MUST 在資源去重前忽略，不得遮蔽較舊的有效 CREATE／UPDATE。Resume 每列 MUST 只投影固定 kind、Team、`last_activity_at`、server-built relative link 與該 kind 所需的最小 Run／resource id；MUST NOT 投影 Test Run Item id、Item result、Test Run Set、Audit details／brief 或任意 URL。寬度足夠時，每筆 resume MUST 以單一高密度水平列顯示 kind、最小識別、Team、時間與返回動作，相同語意欄位 MUST 跨列對齊，且不得把同一筆工作拆成多層標題／metadata card。作為 Test Run 證據的 Item 當下結果即使是 `Passed`、`Not Required` 或 `Skip` 也不得讓 active Run 入口消失。`assigned` 來源 Item 必須目前解析為該使用者且 Test Run status 為 `draft` 或 `active`，response 與 UI MUST 按 Team id＋Test Run id 聚合；每個群組投影 Team、Run、精確 `item_count`、server-derived action mode、run-level link 與最多五筆 `preview_items`。每筆 preview 只可包含 Test Case number/title、result 與 server-built item deep link；常態摘要 MUST NOT 顯示個別 Test Case、result、Updated、Test Run Set 或獨立 Actions 欄，且 MUST 在套用 server-defined Run 上限前計算 count。沒有 write capability 的使用者可取得 read-only assigned Run／既有讀取導覽，但 MUST NOT 取得任何 resume 或 execute action。

目前 assignee 的解析順序 MUST 是 `assignee_user_id` 精確相等優先；只有 `assignee_user_id IS NULL` 時，才可用唯一精確 Lark id 或 normalized email 作 legacy fallback。系統 MUST NOT 以 assignee name、full name、username 或 display name 判斷「指派給我」或 resume。

#### Scenario: 目前指派且有 execution 歷程的 Item 產生 run-level resume 入口

- **WHEN** active Test Run Item 的 `assignee_user_id` 等於 current user，結果為 `Retest`，該使用者具 write capability，且該使用者有 result 或 execution-time 變動的 Result History
- **THEN** resume 以 Team、Test Run 與上次操作時間顯示一個 run-level 入口，不顯示該 Item、Test Case、result 或 Set metadata，且 assigned section 對應 Run 的 `item_count` 仍包含該 Item

#### Scenario: 完成結果後仍可返回 active Test Run

- **WHEN** current user 在仍為 active 且仍指派給自己的 Test Run Item 將結果更新為 `Passed`
- **THEN** resume 仍顯示該 Test Run 的最近工作入口，連結回到該 Run 且不把該 Item 標示為未完成

#### Scenario: 跨功能最近工作不只保留一筆 Test Run

- **WHEN** current user 最近依序更新 Test Case、User Story Map、Automation Hub，且另有兩個符合條件的 active Test Run
- **THEN** resume 依最近操作時間顯示最多十筆跨功能入口，不只顯示最新一筆；每筆使用固定 kind 與 server-built 同源 route，且不顯示 Audit 原文

#### Scenario: 可續作工作以單列呈現必要資訊

- **WHEN** Personal Dashboard 在桌面寬度顯示多筆 Test Run、Test Case、User Story Map 與 Automation Hub resume
- **THEN** 每筆工作只佔一個緊湊水平列，依序顯示類型、最小識別、Team、上次操作時間與返回動作，相同欄位跨列對齊，長名稱以 ellipsis 收斂而不增加列高

#### Scenario: 已刪除資源不會由舊 Audit 復活

- **WHEN** 某 Test Case 或 User Story Map 的最新 Audit event 為 DELETE，但 bounded scan 中仍有它較早的 UPDATE
- **THEN** resume 不產生該資源的 deep link；Automation Hub 的 delete activity 最多只返回該 Team 的 Hub 功能入口

#### Scenario: 已改派或 terminal Run 的舊工作不再被描述為可續作

- **WHEN** current user 曾更新某 Item，但目前 Item 已改派給其他 user，或 Run 已成為 terminal
- **THEN** 該舊操作不會使對應 Test Run 出現在 current user 的 resume

#### Scenario: 同名帳號不能取得另一人的 legacy 指派

- **WHEN** 兩個 TCRT 帳號具有相同 full name 或 username，且 legacy Item 只含相同 `assignee_name`
- **THEN** 系統不會將該 Item 視為任一帳號的 assigned，也不會因此產生 resume Run 入口

#### Scenario: Draft Item 保留在 assigned 並標示待開始

- **WHEN** current user 目前被指派至 `draft` Test Run 的 Item
- **THEN** Item 被計入 assigned 的 Draft Run 群組且該入口為 read-only，但不產生可立即執行的 resume Run 入口

#### Scenario: Test Run UI 指派後首頁立即可辨識

- **WHEN** 使用者在 Test Run 單筆或批次指派 selector 選取 current user 的 TCRT option，或選取能以 Lark id/email 精確解析至 current user 的 Lark contact
- **THEN** 寫入保留 local 或 structured machine identity，且下一次 `GET /api/dashboard` 將該 draft／active Item 計入對應 assigned Run 的 `item_count`；不得只保存顯示姓名而使首頁漏列

#### Scenario: Viewer 不會取得執行權限

- **WHEN** `VIEWER` 目前被指派到 active Test Run Item
- **THEN** 系統最多回傳 read-only assigned Run presentation／既有讀取導覽，且不回傳 resume 或 execute action

#### Scenario: 同一 Test Run 的多筆指派只佔一列

- **WHEN** current user 在同一 Team 的同一 Test Run 中有三個符合條件的 assigned Item
- **THEN** assigned section 只回傳並顯示一個可展開的該 Test Run 摘要與 `item_count = 3`；折疊時不顯示 Updated、個別 Test Case 或獨立 Actions，展開後顯示最多五筆最小 Item 預覽與完整 Run 入口

#### Scenario: 停用 Team 的工作不會留在個人佇列

- **WHEN** Item 所屬 Team 已非 active 或不在 server-resolved visible Team 範圍
- **THEN** Item 不出現在 assigned，且不會使對應 Test Run 出現在 resume

### Requirement: Personal activity and outcomes MUST use minimal, bounded projections

近期個人活動 MUST 以 `TestRunItemResultHistory.changed_by_id == str(current_user.id)` 為主要來源，且只投影 Item／Run／Team metadata、結果、時間與固定 source code。Audit 補充只能以 current user id 加上伺服器可見 Team 範圍查詢，且只投影 timestamp、固定 allowlist 的 action/resource；MUST NOT 投影 Audit event code、outcome、`details`、`action_brief`、reason、IP、User-Agent 或 raw error。

「execution transition」MUST 只包含既有 Result History 中以跨資料庫 null-safe 語意判定 `prev_result` 與 `new_result` 不同、或 `prev_executed_at` 與 `new_executed_at` 不同的 row；實作 MUST 正確視 `NULL → value` 與 `value → NULL` 為差異，不得只用 SQL `!=`。comment-only row 可作活動但 MUST NOT 成為 resume 或成果的證據。成果 MUST 使用最近 7 × 24 小時內每個 Item 的最後一筆 current-user execution transition，只統計 `Passed`、`Failed`、`Retest`、`Not Available`、`Not Required`、`Skip` 的 `new_result`；`NULL`、`Pending` 與未知 legacy 值 MUST 不計入成果。沒有可計數 execution 時 MUST 不回傳 pass rate。所有 personal list MUST 有 server-defined 上限與穩定的時間＋id 排序，且 client 不可要求無限制頁數。

resume、activity、outcomes MUST 各自可降級：遇到無法安全讀取的 legacy result enum 或 history query failure 時，該 section MUST 回傳 `partial` 或 `unavailable` 與 generic state、不得回傳底層例外或未知值；已成功查得的 Team／assigned section MUST 繼續可用。

Personal Dashboard 首屏 MUST 只顯示 activity section 最新五筆，且摘要只保留動作、結果與時間，不常駐顯示 Team、Run、Test Case title／number。只要 bounded response 至少有一筆活動，區塊 MUST 提供可存取的「查看全部」入口；modal MUST 使用 Bootstrap `modal-xl` 並在 `lg` 以下 fullscreen，內容 MUST 使用 canonical compact table。欄位標頭只顯示一次，桌面寬度下每筆活動只佔一列，並顯示本次 response 的全部 Team／Run context、Test Case、時間、結果與 server-built icon-only item link。窄螢幕 MUST 只在 modal table wrapper 內水平捲動。此展開 MUST NOT 觸發未受限查詢、為每筆活動建立重複 label card，或將詳細資料同時留在首屏。

Personal Dashboard MUST NOT 將 Audit fallback 渲染為獨立的「稽核活動摘要」卡片或列表。後端 MAY 保留符合上述最小投影與 section isolation 的 Audit section，但其存在不得增加首頁視覺層級或取代 Result History activity。

當 outcomes `total > 0` 時，Personal Dashboard MUST 以不依賴外部圖表套件的 SVG donut-style pie chart 顯示結果分布，並同時提供總數、每個結果的文字標籤與精確數量，不能只依賴顏色傳達資訊。成果卡 MUST 將標題維持在內容頂端，chart 與圖例共同使用其下方的剩餘高度；chart MUST 在不擠壓圖例或造成 card overflow 的前提下依可用高度放大，不能以固定小尺寸留出大面積上下空白。`total = 0` 時 MUST 維持既有空狀態，不渲染無意義圖形。

#### Scenario: Audit DB 不可用時 Personal Dashboard 可部分降級

- **WHEN** main DB 的 personal work 查詢成功但 audit DB session 失敗
- **THEN** Dashboard 仍回傳 200 與 main DB section，活動 Audit section 標示 `partial` 或 `unavailable`，且 body 不含底層例外文字

#### Scenario: Personal Dashboard 不顯示獨立稽核摘要

- **WHEN** personal Dashboard response 含 ready 或 unavailable 的 Audit fallback section
- **THEN** 首頁都不渲染「稽核活動摘要」卡片，其他工作與活動區塊維持原有順序與狀態

#### Scenario: 成果只計算該使用者每個 Item 的最新結果

- **WHEN** 同一 Item 在最近七天內由 current user 先設為 `Failed` 後設為 `Passed`
- **THEN** 成果統計只以該 Item 的最後一筆 `Passed` 計算一次

#### Scenario: 無 execution 時不產生誤導性百分比

- **WHEN** current user 在最近七天沒有任何可計數 execution history
- **THEN** Dashboard 顯示空成果或結果計數零值，且不顯示 pass rate／週目標百分比

#### Scenario: 成果以圓餅分布與精確圖例呈現

- **WHEN** 近七日成果含 `Passed = 3`、`Failed = 1`
- **THEN** Dashboard 顯示一個可存取、會利用標題下方可用高度放大的 pie chart、中心總數 `4`，並在文字圖例分別顯示兩種結果與精確數量，且卡片不留下由固定小圖造成的大面積上下空白

#### Scenario: Comment 不會被當成新的成果或續作證據

- **WHEN** current user 在最近七天只新增 comment，且該歷程的 result 與 execution time 都未變
- **THEN** comment 可出現在近期活動，但不產生 outcome count，也不產生 resume Run 入口

#### Scenario: 壞掉的 legacy result 不會中斷工作佇列

- **WHEN** 一筆 current-user Result History 含無法安全解析的 legacy result 值
- **THEN** 系統保留已成功查得的 Team／assigned 資料，受影響的 resume、activity 或 outcomes section 回傳 `partial`／`unavailable` 與 generic state，且 response 不含例外文字或未知 result

#### Scenario: 首屏活動保持精簡

- **WHEN** activity section 回傳八筆依穩定排序排列的近期活動
- **THEN** 首屏只顯示前五筆的動作、結果與時間，使用者可由「查看全部」modal 檢視該 response 八筆活動的結構化完整上下文

#### Scenario: 少於五筆活動仍可查看詳細資料

- **WHEN** activity section 只有兩筆活動
- **THEN** 首屏顯示兩筆簡化摘要並仍提供「查看全部」，modal 顯示兩筆詳細資料與安全 item link

#### Scenario: 活動明細以高密度表格呈現

- **WHEN** 使用者開啟含多筆活動的「查看全部」modal
- **THEN** Team／Run、Test Case、結果與時間的欄位標頭只出現一次，每筆活動在桌面寬度只佔一列，且導覽動作以具 accessible name 的 icon-only 按鈕呈現

### Requirement: Preferred Team and Dashboard deep links MUST not mutate Assistant context on load

Personal Dashboard SHALL 將偏好 Team 只存為 `tcrt:dashboard:preferred-team:<current-user-id>` 的 numeric Team id。載入時 MUST 驗證 id 存在於 server response 的 active、visible Team；key 不存在、失效或無法解析且至少有一個可見 Team 時，系統 MUST 顯示首次設定 modal，且候選只能來自該 response。完成選擇後 Team 區塊 MUST 以高密度水平列顯示標題、偏好 Team 與修改入口，寬度足夠時三者必須位於同一列，且不得再顯示 Open 動作；選擇或修改 MUST 只寫入該 user-scoped key 並更新入口，不得導航、呼叫 `AppUtils.setCurrentTeam()` 或改寫 `currentTeam`。localStorage 不可用時 MUST 允許以當頁記憶體選擇繼續使用，且不得影響資料 scope。載入 Dashboard MUST NOT 呼叫 `AppUtils.setCurrentTeam()` 或改寫 `currentTeam`；偏好 MUST NOT 過濾 cross-team resume、assigned、activity 或 outcomes。使用者點擊 Personal Dashboard quick action 時，前端 MUST 先以該偏好 Team 設定既有 `currentTeam` 再導航；若 Automation Hub 組織入口開關為 enabled，server quick-action allowlist MUST 包含 `/automation-hub`，disabled 時 MUST 省略。

Quick Actions MUST 使用緊湊水平 icon-only action rail，在寬度足夠時將區塊標題與所有入口放在同一列，不使用大型雙欄 tile。入口按鈕 MUST 不顯示文字、MUST 等寬延展並共同填滿標題後的可用 rail 寬度，且每一個都 MUST 提供依目前語系產生的 accessible name 與 hover tooltip；hover／focus MUST NOT 以位移超出 rail clipping boundary。在窄螢幕上 MUST 保留 keyboard focus 與完整點擊能力。User Story Map 入口 MUST 以 server allowlisted `/user-story-map/{team_id}` template 和 server-returned 偏好 Team id 解析成存在的 team-scoped route；沒有偏好 Team 時 MUST disabled，且不得導向不存在的 `/user-story-map`。

前端 MUST 將每個 Dashboard request 綁定發起當下的 AuthClient current user id 與 access-token snapshot。登入身分／token 改變、登出或晚到的舊 response MUST 被丟棄，不得 render、讀寫偏好或改寫 `currentTeam`。在 `pageshow` 表示由 browser back/forward cache 還原時，前端 MUST 先清除舊 Dashboard state 再重新取得 server response。

Dashboard 的 activity 與 assigned preview item-level Test Run link MUST 使用同源 `/test-run-execution?team_id=<id>&config_id=<id>&tc=<number>`；resume 與 assigned Run link MUST 使用同源 `/test-run-execution?team_id=<id>&config_id=<id>` 且不綁定任一 Test Case。使用者點擊 quick action／Run／Item link 時，前端才可用 response 中的偏好 Team 或工作 Team 資料設定 `currentTeam` 後導航。連結與 Team id 都 MUST 由 server data 產生，不能由 localStorage 或 user-supplied URL 產生。

#### Scenario: 共用瀏覽器的偏好不跨帳號套用

- **WHEN** User A 與 User B 在同一瀏覽器先後登入並各自選擇偏好 Team
- **THEN** 兩人的偏好使用不同 localStorage key，User B 不會讀取或套用 User A 的偏好

#### Scenario: 首次進入要求選擇偏好 Team

- **WHEN** current user 有可見 Team，但其 user-scoped preference key 不存在
- **THEN** Dashboard 顯示只包含 server-returned visible Team 的設定 modal，選擇完成後 Team 區塊只顯示該 Team

#### Scenario: 偏好 Team 已失效

- **WHEN** localStorage 中的偏好 Team 已不存在、非 active 或未出現在目前 response 的 Team 列表
- **THEN** 前端清除或忽略該值並顯示偏好設定 modal，且不自動導向或請求該 Team 資料

#### Scenario: 修改偏好不切換工作區

- **WHEN** 使用者由 Team 區塊點選「修改偏好」並選擇另一個可見 Team
- **THEN** 前端只將該 Team id 寫入目前 user 的 preference key 並改顯示該單一 Team，不導航也不改寫 `currentTeam`

#### Scenario: 偏好 Team 卡片不提供重複入口

- **WHEN** current user 已設定有效偏好 Team
- **THEN** Team 區塊只顯示 Team 名稱與修改偏好控制，不顯示 Open；使用者由下方 quick action 進入該 Team 功能

#### Scenario: Quick action 採用偏好 Team context

- **WHEN** current user 點擊 Test Run、Test Case、User Story Map 或已啟用的 Automation Hub quick action
- **THEN** 前端在該次使用者動作中先以偏好 Team 呼叫既有 `setCurrentTeam`，再導向 server allowlisted route

#### Scenario: 偏好 Team 與快速功能在桌面寬度保持緊湊

- **WHEN** Personal Dashboard 以桌面寬度顯示有效偏好 Team 與四個 quick action
- **THEN** 偏好 Team 標題、Team 名稱、修改控制位於同一列，Quick Actions 標題與四個等寬、共同填滿剩餘 rail 寬度的 icon-only 入口位於另一列，不渲染大型雙欄 tile，且每個 icon 按鈕都有 localized accessible name 與 tooltip

#### Scenario: localStorage 被瀏覽器拒絕

- **WHEN** 寫入 user-scoped preference key 產生例外
- **THEN** Dashboard 以當頁記憶體保留這次選擇、顯示該單一 Team 並保持其他 section 可用，不改寫 `currentTeam`

#### Scenario: Dashboard 載入不改變 Assistant 的現有 team context

- **WHEN** 使用者帶著既有 `currentTeam` 開啟 Dashboard
- **THEN** Dashboard 載入不改寫 `currentTeam`，而使用者點擊 quick action、Run 或 Item 入口後才切換既有工作區 context

#### Scenario: 共用瀏覽器的舊 response 不會覆蓋新登入者首頁

- **WHEN** User A 的 Dashboard request 尚未完成時登出，User B 登入並開始自己的 Dashboard request
- **THEN** User A 晚到的 response 被丟棄，不會 render、讀寫 User B 的 preference 或改寫 `currentTeam`

#### Scenario: 跨分頁更換帳號會清除舊首頁

- **WHEN** 另一個同源 browser tab 變更或移除 access token
- **THEN** 本頁立即清除既有 Dashboard、作廢未完成 request；若有新 token，僅可用新 token 重新取得 current-user Dashboard

#### Scenario: BFCache 還原後重新驗證 Dashboard

- **WHEN** 瀏覽器以 back/forward cache 還原先前的首頁
- **THEN** 前端先移除舊 Dashboard payload 並重新請求 `GET /api/dashboard`，不持續顯示可能已過期的 role-specific 資料

### Requirement: Personal Dashboard UI SHALL be safe, localized, and resilient

Personal Dashboard MUST 提供 `en-US`、`zh-CN`、`zh-TW` 的靜態與動態文案，依既有 i18n lifecycle 重新翻譯。它 MUST 支援 loading、no active Team、empty resume／assigned、partial activity 與 generic error 狀態。Team、Run、Test Case、活動與錯誤的動態資料 MUST 使用 `textContent`／等價 escaping；只有固定 allowlist 的 code 可作 i18n key 或快捷入口。

Personal Dashboard 的問候名稱 MUST 優先使用同一 authenticated AuthClient current-user response 中 trim 後非空的 Lark name；沒有時 MUST 回退至該 TCRT user 的 `username`。前端 MUST 保留 request 的同帳號 guard，且 MUST NOT 為顯示問候名稱額外呼叫外部 Lark 服務或依 activity／assignee snapshot 推斷姓名。

Personal Dashboard MUST 在目前 viewport 的中央內容區建立固定工作區，讓問候 hero 固定在最上列、不隨 section 捲動。桌面下方每個 section MUST 有受控高度，card header 與 header action MUST 保持可見，超量資料只在該 card body 內垂直捲動；body/document MUST NOT 因 section item 數增加而捲動。窄螢幕 MAY 讓 hero 下方 dashboard region 在 `.app-main` 內捲動以接觸所有 section，但 hero MUST 保持固定，且不得把 document scroll 恢復。AI Assistant FAB 仍可覆蓋內容，不需保留空白角落。

#### Scenario: 長清單不撐高整頁

- **WHEN** Resume、Assigned 與 Activity 都達到 server-defined 上限
- **THEN** 問候 hero 與各 card header 留在固定工作區，清單只在各自 card body 捲動，browser document 不產生 Dashboard 內容造成的垂直捲軸

#### Scenario: 無可用 Team 的一般使用者

- **WHEN** non-Super-Admin 的 Personal Dashboard 沒有 active、visible Team
- **THEN** 系統回傳正常空狀態與依既有權限可用的入口，而非改查所有 Team 或回傳 500

#### Scenario: 不可信資料不會成為 HTML 或翻譯 key

- **WHEN** Team、Run 或 Test Case title 包含 HTML-like 字串，或 Audit action/resource 為非 allowlist 值
- **THEN** 前端以安全文字顯示，未知 code 使用固定 fallback，且不執行 HTML 或動態解譯為 i18n key

#### Scenario: Lark 名稱優先且安全回退

- **WHEN** AuthClient current-user profile 同時含 Lark name 與 TCRT username
- **THEN** 問候顯示 Lark name；若 Lark name 缺少或只有空白則顯示 TCRT username
