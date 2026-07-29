## Why

目前首頁以多個 Team 並列卡片為中心。一般使用者仍需自行判斷要進入哪個團隊與功能，無法快速掌握「我正在做什麼、接下來要做什麼、最近完成了什麼」；負責全系統治理的 Super Admin 也被導向同一套 Team-first 入口，而不是系統健康與管理事項。

此外，Test Run Item 現行指派主要依 Lark 身分或顯示名稱。只有 TCRT 帳號的使用者沒有可靠且可查詢的本地指派身分，因而無法安全提供「指派給我」清單。此 change 會建立依角色分流的首頁，並補齊 TCRT-native 指派識別，同時保留 Lark 與既有客戶端相容性。

## What Changes

- 已認證首頁改為 role-aware dashboard：只有 `UserRole.SUPER_ADMIN` 顯示 System Administration Dashboard；`ADMIN`、`USER`、`VIEWER` 顯示 Personal Dashboard。Super Admin 不將個人續作、指派項目或偏好 Team 作為首屏內容。
- `/` 是 cross-team 入口，不把既有 `currentTeam` badge 當成 Dashboard 篩選器或偏好 Team 的替代品；System Administration Dashboard 的頁首明確標示 system scope。這只調整首頁呈現，不能清除或偷偷改寫既有 Assistant 的 team context。
- `/` 維持既有、未帶 Bearer token 的共用 HTML shell。前端經既有認證初始化後呼叫一個無使用者／Team query parameter 的 `GET /api/dashboard`；伺服器每次依目前登入者重新判定角色並回傳唯一 `dashboard_type`。前端不得信任 `localStorage.user_role` 或自行推斷角色；401 沿用既有登入導向，角色變更後的下一次回應必須清除前一種 Dashboard 的資料。
- Personal Dashboard 以單一受保護、`Cache-Control: no-store` 的 read model 顯示，所有 Team 均須為 server-resolved、active 且目前可見的 Team：
  - 可續作工作：以最多十筆、跨功能且依最近操作時間排序的安全工作入口呈現，不只保留一筆。Test Run 仍以目前屬於該使用者、Run 為 `active`、具 write capability 且本人曾留下 null-safe execution transition 為必要條件，依 Team＋Run 去重並只提供 run-level 入口；另外以本人、可見 Team 範圍內的 Audit `CREATE`／`UPDATE` 最小投影補入 Test Case、User Story Map 與 Automation Hub 工作。Audit-derived 入口只能由 resource type allowlist、Team id 與受格式驗證的 resource id 組成既有同源路由，不讀 `details`／`action_brief`、不接受任意 URL；已刪除的 Test Case／Map 不得由較舊事件重新生成入口。各類入口只呈現工作類型、最小識別、Team、上次操作時間與返回動作，不呈現 Test Run Item、result、Set 或 Audit 原文；桌面版每個入口以單一高密度水平列呈現，且相同語意欄位跨列對齊，不為同一筆資料建立多層標題／metadata 區塊。
  - 指派給我：目前指派給該使用者的 `draft` 或 `active` Test Run Item 先按 Team＋Test Run 聚合；每個 Run 常態只顯示一次可展開摘要與精確的指派 Item 數量，不顯示 Updated、Test Run Set 或常駐 Actions 欄。展開後可預覽 server-bounded 的 Test Case number/title、result 與 item deep link，並提供明確的完整 Test Run 入口；具 write capability 且 Run active 時可執行，其他情況維持唯讀導覽。
  - 近期個人活動：以 `TestRunItemResultHistory.changed_by_id == str(current_user.id)` 為主，允許包含既有 comment 與 execution event；Audit 僅保留為 API 的 best-effort 安全來源，不以姓名比對，也不在 Personal Dashboard 另列「稽核活動摘要」卡片。首頁首屏只顯示最新五筆的動作、結果與時間，不常駐顯示 Run／Test Case／Team 細節；只要有活動就提供「查看全部」，在 `modal-xl`、中小桌面可 fullscreen 的 scrollable modal 以欄位標頭只出現一次的高密度明細表顯示本次 bounded response，每筆活動只佔一列並保留完整 Team／Run／Test Case／結果／時間與 item-level 入口。
  - 近期成果：使用最近七個 rolling 24-hour window 中該使用者每個 Item 的最新「實際 execution transition」的 completed result（`Passed`、`Failed`、`Retest`、`Not Available`、`Not Required`、`Skip`）計數；不把 comment、`Pending`、`NULL` 或未知 legacy 值算成成果，不新增週目標欄位，也不在分母為零時顯示 pass rate。非零成果以原生 SVG donut-style pie chart、總數與文字圖例呈現；chart 需利用標題下方的可用 card 高度自適應放大，避免固定小圖造成上下無效留白，且不新增圖表套件。
  - 依既有權限可用的快速入口、空狀態與讀取失敗狀態；既有 Automation Hub 組織入口開關為 enabled 時，快速入口必須包含 Automation Hub。Preferred Team 與 Quick Actions 都使用高密度水平控制列，寬度足夠時將標題、內容與操作放在同一列，不再使用大型入口 tile；Quick Actions 的入口只顯示圖示、以等寬方式延展並填滿 action rail 的可用寬度，但每個按鈕必須保留三語 accessible name 與 tooltip。
- Personal Dashboard 的偏好 Team 只存瀏覽器 `localStorage`，key 必須依目前 user id 命名空間化，值只存 Team id。若目前使用者有可見 Team 但 key 不存在、無法解析或已失效，第一次進入時顯示只能從 server-returned visible Team 選擇的設定 modal；完成後首頁 Team 區塊以單列緊湊控制顯示標題、該偏好 Team 與「修改偏好」入口，不另提供重複的 Open 動作。設定或修改只更新偏好顯示，不導航、不呼叫 `AppUtils.setCurrentTeam()`。Dashboard 載入不得改寫 `currentTeam`；使用者點擊快速入口、Run 或 Item 深連結時，才以伺服器回傳的偏好 Team／工作資料設定它。瀏覽器拒絕 localStorage 時，當頁仍可用記憶體內選擇完成設定並正常使用，但重新載入後可再次要求選擇。
- Personal Dashboard 問候名稱優先採既有 AuthClient current-user response 的非空 Lark 名稱，沒有時回退到同一個 TCRT 帳號的 `username`；不得為首頁額外呼叫外部 Lark 服務，也不得以活動或 assignee snapshot 猜測人名。
- Dashboard 在桌面可用高度內採固定工作區：中央問候區固定於內容區頂端，不跟隨卡片捲動；下方兩欄各 section 取得受控高度，card header／動作固定而 card body 自行垂直捲動，文件本身不得因 section 項目數增加而捲動。窄螢幕可讓下方 dashboard region 在中央內容區內捲動，但問候區仍固定且不得讓 body/document 捲動。
- 首頁前端必須以目前 AuthClient 的 user id／access-token snapshot 綁定每一次 Dashboard request；登入身分變更、登出或較舊 request 晚到時，舊回應不得渲染、不得讀寫任何帳號的偏好、也不得改寫 `currentTeam`。瀏覽器以 back/forward cache 還原首頁時，前端必須先清除舊 Dashboard state 再重新請求 `GET /api/dashboard`。
- Dashboard 的 Team 可見性與快速入口一律由伺服器套用目前的 canonical role／permission policy；此 change 不重新詮釋或啟用既有 `UserTeamPermission` 資料，也不改變既有的全域角色授權模型。個人 Dashboard 沒有可用 Team 時回傳正常空狀態；Super Admin 即使沒有 active Team 仍維持系統管理首頁。
- 新增 Super Admin 專用的 System Administration Dashboard。它只呈現固定 allowlist 的系統管理摘要：安全的統計／可用性狀態、排程服務的 enabled／running／時間／結果碼、CI／Result provider 是否已設定、需要關注事件的計數與時間，以及既有組織管理、系統日誌、稽核日誌、統計分析等管理入口。它不得回傳或顯示 credential、token、URL、host、原始 runtime setting、raw system-log message、scheduled-service 的 error/message、Audit `details`、IP／User-Agent 或任何原始例外文字；provider 僅可呈現「已設定／未設定」，不得將其當成 connection health。每個摘要區塊須可獨立回報 `unavailable`，不阻斷其餘區塊；回應使用 `Cache-Control: no-store`。
- 在 `TestRunItem` 新增 nullable `assignee_user_id`，為 `users.id` 的 `ON DELETE SET NULL` foreign key。非 null 指派只能指向有效且在寫入當下依既有角色授權可執行該 Team Test Run 的 TCRT 帳號；migration 回填與 Lark 自動解析也必須符合此條件，否則只保留 legacy Lark snapshot。本 change 不新增 Team membership 模型。應用程式永久刪除 User 前，必須清除所有可精確比對其 local FK、Lark id 或 normalized email 的既有 Item 的可機器比對 Lark identity（保留僅供歷史顯示的名稱 snapshot），避免日後重用 email／Lark id 的新帳號承接舊指派。
- 新增受既有 Test Run 寫入權限保護的 TCRT assignee lookup，僅回傳選擇器所需的最小欄位（local id、顯示名稱、是否連結 Lark），並限制搜尋與回傳筆數；不得重用管理員使用者清單或洩露 email、角色、帳號狀態以外的資料。Test Run 單筆與批次 UI 選取 TCRT user 時必須送出 local id；選取 Lark contact 時必須保留 structured machine identity，優先送穩定的 Lark id，只有沒有 id 時才回退 normalized email，不得把同一 contact snapshot 的 id/email 當成兩個獨立一致性宣告；只有明確自訂文字才可降級為 name-only snapshot。
- 所有 Test Run Item 建立／單筆更新／批次更新／app-token 寫入、Assistant 寫入、Test Run restart/re-run clone 與由 Test Run Set 產生的 Item 都共用一個 assignee normalizer：
  - update 以欄位「是否出現在 payload」而非 truthiness 判斷 assignment intent；省略欄位保持既有 identity，明確的單一 representation `null`／空字串才是 clear。一次更新僅可指定一種 assignment representation：明確 `assignee_user_id`、結構化 Lark `assignee` 或 legacy `assignee_name`。唯一例外是本地 id 與結構化 Lark assignee 可同時傳入，但兩者必須解析為同一帳號；其餘組合或不一致值一律 422，且批次先完整 preflight，不得留下部分 identity 寫入。
  - 明確 `assignee_user_id` 會驗證目標帳號並保存本地顯示名稱 snapshot；若未同時提供且驗證為相同人的結構化 Lark assignee，必須清除舊 Lark 欄位，避免殘留另一人的外部身分。
  - Lark 結構化 assignee 僅能以唯一、精確的 `lark_user_id` 或經 `trim + lower` 正規化且候選數恰為一的 email 解析本地帳號；物件同時帶 id/email 時，兩者不得解析到不同帳號。解析成功時保存兩種身分，否則僅保留既有 Lark 欄位。
  - legacy `assignee_name` 更新永遠清除 `assignee_user_id`，不得以名稱模糊解析；清空 assignee 時同時清除本地與外部身分欄位。既有 app-token name-only payload 保持可用並採相同清除規則。
  - 既有 JWT/Test Run Item response 新增 additive 的 `assignee_user_id`，既有 Lark／名稱欄位與 payload 不移除；app-token 與 Assistant 的最小 projection 不因此擴張或洩露 local user id。
- Migration 先加入 nullable FK 與 `test_run_items(assignee_user_id, updated_at)`、`test_run_item_result_history(changed_by_id, changed_at)` 索引，再以 active、具 write capability 且唯一精確的 Lark id／經 `trim + lower` 正規化後候選恰為一的 email best-effort 回填；禁止以名稱回填。id/email 同時存在卻衝突或歧義時不回填。未匹配列保留既有欄位。downgrade 只移除本 change 的 FK／索引／欄位，不修改既有指派 snapshot。Migration 與測試必須支援 SQLite、MySQL 8、PostgreSQL 16；audit DB 不變更 schema。
- Dashboard 不把純指派異動或 comment 偽裝成執行成果：成果與 Test Run resume 的 execution predicate 必須是 result 或 execution-time 的真實變動，並採 null-safe 比較（不得以 SQL `!=` 漏掉 `NULL → value`）；跨功能 resume 則只使用 allowlisted Audit action/resource 的最小 routing projection，不把 Audit 當成 execution outcome。所有列表由伺服器固定上限、穩定排序；activity 與 Assigned preview 的 Test Run Item 連結採既有 `/test-run-execution?team_id=<id>&config_id=<id>&tc=<number>`，Test Run resume 與 Assigned Run 不帶 `tc`，Test Case／User Story Map／Automation Hub resume 只採各自固定的同源 route template，絕不接受或儲存 URL。
- 若歷史資料含無法讀取的 legacy result enum 或歷程子查詢失敗，已成功取得的 assigned／Team 資料仍必須可用；resume、activity、outcomes 依各自 section 回傳 `partial` 或 `unavailable` 與 generic state，並省略不可信／未知 result，而非把資料庫例外送到 Dashboard。
- 沿用既有全域 AI Assistant widget：FAB 固定浮在右下角並可覆蓋 Dashboard，不預留安全空白，也不改變其顯示權限、對話或 team-context 契約。所有新增文案提供 `en-US`、`zh-CN`、`zh-TW`，並具備 loading、empty、partial-failure、error 與響應式／無障礙狀態。

非目標：跨裝置同步偏好 Team、使用者自訂 Dashboard 版面、每週目標／到期日、儲存導頁 URL、建立新的監控平台、改變既有全域 Team 授權模型、補登舊資料的名稱型 activity、或向一般使用者開放管理員 Audit Log。Super Admin 仍可由管理入口進入既有 Team 功能，但此 change 不在其首頁混入 Personal Dashboard。

## Adversarial Boundaries

- Personal read model 只回傳目前使用者可讀的 Test Run metadata；不得包含 Test Case steps、expected result、附件、`assignee_json`、Bug 內容或其他使用者的指派識別。Test Run Set membership 目前為一對一：若 Item 的 Run 沒有 Set，回應明確為 null 且不產生 Set 連結。
- Test Run resume / assigned query 以目前指派為準，且只查 active、visible Team；本地 FK 比對優先，legacy Lark／email fallback 僅可用於 `assignee_user_id IS NULL` 且仍具可機器比對外部 identity 的列，且絕不以名稱比對。曾由使用者操作、但已被改派或已進入 terminal Run 的 Item 不會產生可續作 Run。active Run 中由本人實際更新過的 Item 即使結果為 `Passed`、`Not Required` 或 `Skip`，仍可作為保留該 Run 入口的內部證據，但 resume projection 不回傳 Item 層級資訊。唯讀者不取得任何 resume／execute 行動。
- personal Audit 只以目前 user id 加上伺服器可見 Team 範圍過濾。既有 fallback list 仍只投影時間與固定 allowlist 的 action/resource；只有跨功能 resume 的內部 routing projection 可額外讀取 Audit id、Team id 與 resource id，且只能產生 `test_case`、`user_story_map`、`automation_hub` 三種固定 kind 及 server-built 相對路徑，不投影 event code、outcome、`details`、`action_brief`、reason 或 raw error。Audit DB 不可用時跨功能 resume 標記 partial，但 main DB Test Run 入口與其餘 Dashboard 仍可用。
- System Administration Dashboard 的 detail 頁仍由各既有 route/API 執行授權；首頁快捷入口是伺服器 allowlist，不能把首頁摘要當成管理權限或健康檢查。Super Admin 降權、停用或 token 失效後，不得繼續取得先前 system response。
- local preference 只影響單一 Team 入口的呈現，從不過濾 cross-team 工作／活動資料、不擴張資料權限或導致自動導航。所有 Dashboard response 都不得根據前端提供的 user id、role、team id 或 URL 改變 scope。
- Assistant registry、filtered batch 與 app-token 的既有 name-only 指派介面維持 legacy 相容：它們不接受模糊的 TCRT 帳號名稱，也不會建立新的本地 assignee 關聯；任何 name-only 變更都依 normalizer 清除舊關聯。Test Run restart/re-run 必須重新驗證被複製的 local assignee；若已停用或不再可執行，新的 Item 不得保留 local identity。TCRT-native 指派由受保護的使用者介面與明確 `assignee_user_id` 負載完成。
- Dashboard 前端把 Team、Run、Set、Test Case、活動與錯誤資料一律以 `textContent`／等價 escaping 渲染；i18n key、狀態碼和快捷入口都只可取自固定 allowlist。API 的 4xx／5xx 與 partial section 不得把內部例外、Audit／provider 原始內容回送至畫面。

## Capabilities

### New Capabilities

- `personal-dashboard`: 定義一般使用者首頁、續作／指派／活動／成果、Team 偏好、相對深連結、資料最小化、降級行為及 AI Assistant 共存。
- `system-administration-dashboard`: 定義 Super Admin 首頁、伺服器端角色分流、固定 allowlist 的系統摘要、敏感資料邊界、partial-failure 與管理入口。
- `test-run-item-assignment-identity`: 定義 Test Run Item 的本地 TCRT assignee 關聯、TCRT-only 帳號選擇、所有寫入路徑的正規化、Lark 相容性、回填及 migration 行為。

### Modified Capabilities

- 無。既有 `assistant-widget-ui`、`audit-event-envelope`、Team 授權模型與 Test Run 導覽契約維持不變；本 change 以新增 read model 與本地 assignee 關聯組合既有能力。

## Impact

- 首頁與前端：`app/templates/index.html`、首頁專用 JS/CSS、三語 locale、component／互動測試；需維持 base layout 與全域 Assistant widget。
- API 與服務：新增 current-user Dashboard endpoint、角色分流聚合器、最小化 assignee lookup、server-side section status，並經既有 main/audit DB access boundary 讀取。
- Test Run 指派：ORM、schema、全部寫入／回應路徑、指派選擇器、main Alembic migration、fixture 與跨資料庫測試。
- 驗證重點：Bearer-shell role dispatch、Super Admin / Admin / Viewer 分流、token／降權後不殘留資料、localStorage 隔離與失效、Audit 不可用、無 Team、legacy name collision、精確 Lark/email 回填、assignment clear、user delete、app-token 相容、深連結與 Assistant context、三種資料庫 migration／downgrade。
- 外部依賴：不新增套件或外部服務；不建立 Jira Ticket。
