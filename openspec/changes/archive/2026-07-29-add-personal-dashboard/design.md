## Context

TCRT 的 `/` 目前是 Jinja2 shell，瀏覽器從 `localStorage` 取得 JWT 後才以 Bearer header 呼叫 API；HTML navigation 本身不會攜帶 JWT。因此首頁不能在 server-render 階段安全地依角色選 template。現況也以 `AppUtils.currentTeam` 作為全域工作區，AI Assistant 會以它作為每回合的 team context；首頁的「偏好 Team」不能覆寫它。

Test Run Item 的 assignee 是一組可空的 Lark／顯示名稱 snapshot，沒有本地 `User` foreign key。Result History 有 actor id 與時間，但只在 execution／comment 有實質變更時寫入；Audit 位於獨立 audit DB，且其 detail、raw message 與 service/provider 設定不可用於一般 Dashboard 顯示。Test Run 與 Test Run Set 的 membership 為一對一，現有頁面已支援 Test Run execution 與 Set detail 的 query-string 深連結。

本設計同時改變首頁、建立跨 main/audit DB read model、增加 main DB identity 欄位，並需保持 SQLite、MySQL 8、PostgreSQL 16 相容。

## Goals / Non-Goals

**Goals:**

- 為非 Super Admin 建立以個人可行動工作為中心的首頁，並為 Super Admin 建立不混入個人工作區塊的系統管理首頁。
- 以 server-authoritative 身分、角色與資料範圍提供固定、最小化且可部分降級的 Dashboard response。
- 讓 TCRT-only 帳號成為 Test Run Item 的穩定 assignee，同時不破壞既有 Lark／name-only client。
- 保護 AI Assistant 現有 `currentTeam` context、既有頁面深連結、三語 i18n 與 component convention。

**Non-Goals:**

- 不改變全域角色導向的 Team authorization model，不把 legacy `UserTeamPermission` 變成新的存取真相。
- 不建立跨裝置偏好同步、可自訂 Dashboard、週目標、deadline、監控／告警平台或新的 Audit schema。
- 不讓 app-token 或 Assistant 的 name-only tool 成為模糊 TCRT user assignment surface。
- 不在 Dashboard 顯示 raw log、provider health、credentials、Audit detail、Test Case steps／附件或任意外部 URL。

## Decisions

### 1. 使用單一 current-user Dashboard endpoint 做角色分流

新增 `GET /api/dashboard`，以 `get_current_user` 驗證 Bearer token，且不接受 user、role、team 或 URL query parameter。服務在每次請求重新讀取 current user：

- `SUPER_ADMIN` 回傳 `dashboard_type: "system_administration"`。
- 其餘 active role 回傳 `dashboard_type: "personal"`。
- 每一種 response 只包含對應的 payload；不先產生兩種資料再由 client 隱藏。

前端先完成現有 `AuthClient` 初始化，再 fetch endpoint，依 server response render。401 使用現有登入 redirect；403／5xx 顯示安全的 i18n error，不顯示後端例外。所有 response 加 `Cache-Control: no-store`。

替代方案是讓 `/` server-render 兩種 template，或由 client 讀 `user_role`。前者不適用於 JWT localStorage 架構，後者可被竄改且會在角色異動後過期，因此不採用。

### 2. Dashboard 聚合器以 main DB 為必要來源、audit DB 為獨立 optional section

建立 Dashboard service/read model，所有 main DB 查詢經 `MainAccessBoundary` 執行，先取得 role、Team visibility、Test Run metadata 與 personal queue。personal Audit 補充改用 audit DB 專用 session，獨立捕捉失敗並回傳 section status `ready`／`partial`／`unavailable`；audit 無法讀取時不得失敗整個 Dashboard。

personal activity 的可信 actor 條件固定為 `ResultHistory.changed_by_id == str(current_user.id)`。Audit fallback 以相同 user id 與 server-resolved Team scope 篩選，只投影 timestamp 與固定 allowlist 的 action/resource；不投影 event code、outcome、`details`、`action_brief`、reason、IP、UA 或 error text。

Audit fallback 保留在 read model 以維持既有 section isolation 與安全 contract，但 Personal Dashboard 不渲染獨立的 Audit 摘要卡片。Audit query 可在同一次 bounded scan 額外投影 `id`、`team_id`、`resource_id` 供跨功能 resume routing 使用；這些欄位不得進入 `audit.items`，只可經固定 mapping 轉成 `test_case`、`user_story_map`、`automation_hub` resume item。單筆 Test Case resource id 必須通過保守格式驗證後 URL encode，`batch_`／`bulk_` 事件只能回 Test Case Management team-level route；User Story Map 可接受正整數 map id 或既有 `map_id:node/relation` composite id 的正整數 prefix，兩者都只回 map route；Automation Hub 只回 team-level Hub route。Map／Case 的 resource-level DELETE tombstone 會阻止較舊事件復活成 stale deep link，relation DELETE 則仍可返回尚存在的 Map；READ 等不具續作語意的 action 必須在資源去重前忽略，不能遮蔽較舊的有效更新。任何 Audit 原始文字與任意 URL 都不進入 response。

Result History 是歷史資料且可能含舊 enum 值；resume、activity、outcomes 必須各自隔離失敗。任何一個 history section 無法安全讀取或遇到未知 result 時，只回傳 `partial`／`unavailable` 與 generic state，忽略該不可信值，不能讓已成功查到的 Team／assigned section 失敗，也不能回傳 ORM／資料庫例外。

替代方案是直接重用 `/audit/logs` 或讓 client 同時呼叫多個既有 API。前者只適合管理者且會放大資料面；後者會讓 client 決定 scope、使 loading/error 難以一致，也無法保證最小投影，因此不採用。

### 3. Personal queue、activity 與成果採固定資料語意與上限

- 所有 personal queue／activity query 都先限制在目前 server-resolved、active、visible Team。Test Run resume 候選必須同時符合：目前解析為該使用者、Run status 為 `active`、使用者具既有 Test Run write capability，且有該使用者的實際 execution transition；不再以目前 Item result 排除候選。候選以最近 transition 決定排序並依 Team＋Run 去重，Item 僅作內部判定依據。接著與 Audit-derived Test Case／User Story Map／Automation Hub 候選合併，以 `last_activity_at` 及 deterministic identity tie-breaker 排序並限制十筆。共同 projection 只有固定 `kind`、Team、`last_activity_at`、server-built `link`，再依 kind 附 Run 或受驗證的 resource id；唯讀者完全不取得 resume。前端在桌面寬度以固定 CSS grid column 放置 kind icon／label、最小識別、Team、時間與返回動作，使相同欄位跨列對齊；動作欄需容納三語完整 CTA，較窄 viewport 則切換為保留 accessible label 的 icon-only 模式。長內容採 ellipsis 與緊湊間距，不把一筆工作拆成多行卡片。Audit 失敗時保留 main DB Test Run items 並把 resume 標成 partial，main history 失敗而 Audit 可用時則保留跨功能 items 並標成 partial。
- Assigned section 仍以目前解析為該使用者且 Run 為 `draft`／`active` 的 Item 為來源；read model 先以 Team＋Run 聚合並在套用 Run 上限前計算精確 Item 數量，再以跨 SQLite／MySQL 8／PostgreSQL 16 的 window rank 對每個已選 Run 取得最多五筆最新 Item 預覽，避免 N+1 或單一大 Run 壟斷全域 limit。前端每個 Run 常態只 render 可展開摘要與 count badge，展開後才顯示 Test Case number/title、result、item deep link 與完整 Run 入口；不顯示 Updated、Test Run Set 或常駐 Actions 欄。無 write capability 或 Draft Run 的入口維持 read-only；active 且可寫入的入口可進入執行頁。
- Legacy Lark/email fallback 只套用在 `assignee_user_id IS NULL`，優先於任何名稱處理；名稱永遠不是 identity predicate。
- 「實際 execution transition」固定為既有 Result History 中 result 或 execution timestamp 有變動的 row，兩者都必須採跨資料庫的 null-safe difference 判定（不可只用 SQL `!=`）；comment-only row 可留在 activity，但不可做為 resume 證據或成果候選。成果使用最近 7 × 24 小時內、每個 item 的最後一筆 current-user execution transition，且只計 `Passed`、`Failed`、`Retest`、`Not Available`、`Not Required`、`Skip` 的 `new_result`；`NULL`、`Pending`、未知 legacy 值都不計。無可計數 execution 時不計算百分比。
- Outcomes 前端使用原生 SVG donut-style pie chart；每個 segment 只使用固定 result-to-token mapping，並併列總數與文字圖例，避免只靠顏色。卡片 body 採「頂端標題＋剩餘內容列」grid，chart figure 與圖例在內容列垂直置中；chart 以內容列的 definite height、最大尺寸與 `aspect-ratio` 自適應放大，窄螢幕則套較小上限，避免固定 5.5rem 圖形造成上下留白或撐出 card。此設計不新增 JavaScript 圖表套件，也不改變 outcomes API projection。
- 各 section 使用 server-defined limit、`changed_at`／`updated_at` descending 加 id tie-breaker，且不開放未受限制的 client pagination。Activity response 保留 bounded recent items，首屏只 render 前五筆的 action、result 與 timestamp；只要至少一筆就顯示「查看全部」。modal 使用 Bootstrap `modal-xl`，在 `lg` 以下轉為 fullscreen；內容採 canonical compact table，欄位標頭只出現一次，每筆活動在桌面寬度只佔一列，呈現 Team＋Run context、Test Case、時間、結果與 icon-only item link；窄螢幕由 modal 內 table-responsive 捲動，不再發出未受限查詢，也不再為每筆活動建立重複欄位卡。

Dashboard 的 activity projection 使用 server-built item-level relative link。Resume 採 kind union：Test Run 使用 `/test-run-execution?team_id=&config_id=`，Test Case 使用 `/test-case-management?team_id=&tc=&mode=edit`，User Story Map 使用 `/user-story-map/{team}/{map}`，Automation Hub 使用 `/automation-hub?team_id=`；前端不自行拼接。Assigned projection 帶 Team、Run、精確 `item_count`、server-derived action mode、run-level link 與每 Run 最多五筆的最小 preview；preview item link 使用 `&tc=`。點擊時才以回應中的 Team object 呼叫 `AppUtils.setCurrentTeam()`，再導航。

### 4. 偏好 Team 是 per-user client preference，與工作區 context 分離

使用 `tcrt:dashboard:preferred-team:<user-id>` 保存純數字 Team id。載入後只在 server response 的 active／visible Team 集合內採用；key 不存在、parse error、失效 id 或權限／狀態改變都視為尚未設定，清除不可信值並在有可見 Team 時開啟首次設定 modal。modal 只列 server response 內的 Team；選擇後只寫該 key，並以無分離 header 的緊湊水平 card body 在同一列呈現標題、Team 名稱與修改入口；不再放置 Open 按鈕，也不能在選擇時導航或寫入 `currentTeam`。Personal quick action 才是偏好 Team 的功能入口：使用者點擊時以偏好 Team 設定 `currentTeam` 後導航；需要 path parameter 的 User Story Map 由 server allowlisted `/user-story-map/{team_id}` template 與該偏好 Team id 解析，未選偏好時入口 disabled，不可落到不存在的 `/user-story-map`。Automation Hub action 由 server 依既有組織入口開關加入或省略。Quick Actions 同樣以無分離 header 的緊湊 icon-only action rail 呈現，桌面寬度下與標題同列；每個固定 allowlist action 以 Font Awesome icon 顯示並以 `flex: 1 1 0` 等寬延展，完整填滿 rail 在標題後的可用寬度。localized label 僅放在 `aria-label` 與 `title` tooltip，不渲染可見文字，也不回到大型兩欄 tile。hover／focus 不以位移超出 rail clipping boundary。localStorage exception 時以 user-scoped 的當頁記憶體選擇維持可用，重新載入可再次提示。偏好不能過濾 cross-team queue／activity、影響 API scope或自動導航。每次 fetch 都捕捉開始時的 AuthClient user id／access-token snapshot；完成後若身分已不同，立即丟棄 response，既不 render 也不觸碰 preference。`pageshow` 的 back/forward-cache restore 必須先清空舊 payload再重新 fetch，配合 `no-store` 避免降權或切換帳號後顯示過期首頁。

問候名稱重用已由 AuthClient 取得的 current-user profile：trim 後有 Lark name 則優先，否則使用 TCRT `username`。Dashboard read model 的安全 fallback 也使用 `username`；不因首頁 render 再查 Lark 或依 full name／歷程資料推斷，避免外部整合讓 Dashboard loading 失敗。

Personal Dashboard shell 使用固定 viewport workspace：`body`／`.app-main` 對本頁關閉 document scroll，`dashboard-content` 用 `auto + minmax(0, 1fr)` 兩列固定 hero 與下方 grid。桌面兩欄以明確 grid row 配額容納各 section，card 為 column flex，header 固定、body 設 `min-height: 0; overflow-y: auto`，避免任何列表撐高文件；窄螢幕僅讓 hero 下方的 dashboard region 成為內部 scroll container，hero 仍位於中央內容區固定首列。這不使用 `position: fixed` 覆蓋內容，也不替右下 Assistant FAB 預留空白。

替代方案是延用共用 `currentTeam` 或寫入 User DB。前者會無意切換 Assistant context，後者會新增跨裝置偏好與同步／隱私契約，兩者都超出需求。

### 5. System Administration Dashboard 採固定安全摘要，而非通用系統觀測介面

Super Admin response 由固定 assembler 產生，僅允許：安全統計／availability、排程 enabled/running/timestamp/outcome code、CI／Result slot configured boolean、需要注意事件的 count/timestamp，以及 server allowlisted management links。每個來源獨立 `unavailable`，不進行 provider connection probe。

assembler 不可序列化 system log message、scheduled-service `last_error`／`last_run_message`、provider config／credential、runtime URL／host、Audit details／action brief、IP／UA 或 exception。動態文字在前端一律 `textContent`／等價 escaping；可作 i18n lookup 的 code 只可來自固定 allowlist。

替代方案是直接嵌入既有 System Logs／Runtime Settings API 或複製 Organization Management 完整資料。它們分別含 raw operational content 或過多設定資料，且會把首頁變成監控／設定平台，故不採用。

### 6. `assignee_user_id` 與 assignee normalizer 建立單一寫入真相

在 `test_run_items` 新增 `assignee_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL`，加 ORM relationship；保留所有既有 assignee snapshot 欄位。所有 Item create、single update、batch update、filtered batch、app-token 路徑、Assistant、Test Run restart/re-run clone 與 Test Run Set 產生的 Item 都必須呼叫同一個 normalizer（無指派建立也使用明確 unassigned intent），而不是各自 set 欄位。

normalizer 的 assignment intent 以 Pydantic／dict 的 field-presence 判斷，而不是以 `None`／空字串 truthiness 猜測：update 未帶任何 assignee field 時必須保持原值；只帶一種 representation 的 `null`／空字串才是 clear。`assignee_user_id`、structured Lark `assignee`、legacy `assignee_name` 至多一種；local id 與 structured Lark 可並存，前提是兩者精確解析至同一 user；其他混合或不一致 payload 為 422。bulk endpoint 必須先完成所有 assignment payload 的 validation，任何一個失敗就以 422 回應且不寫入任一 Item identity。選擇 local user 時驗證 active 與既有 Team execute/write authorization，保存非空的 `full_name` fallback `username` display snapshot，並清除不相符或未驗證為同一人的 Lark snapshot。Lark id 以非空 trim 後 exact match、email 以 `trim + lower` match；同一 object 同時有 id/email 時兩個候選必須是同一人，否則 422；只有 candidate active 且具既有 Team write capability 時才可建立 local FK，否則只保存純 Lark snapshot。name-only 永不解析、永遠清除 local FK。clear 操作清除所有 identity 欄位。

新增 team-scoped assignee lookup，需既有 Test Run write permission，回傳有限筆數的 `{id, display_name, lark_linked}`；不重用 admin user list，不帶 email、role、token 或其他 profile。Test Run 單筆與批次 selector 必須保留使用者實際選取的 representation：TCRT option 送 `assignee_user_id`；Lark contact 送 structured `assignee`，有 Lark id 時只以 id 作 machine identity，沒有 id 時才回退 normalized email，避免 contact snapshot 中可能尚未同步的 email 被後端解讀為第二個一致性宣告；只有手動輸入且未選取候選時送 `assignee_name`。否則 UI 雖顯示已指派，Dashboard 會因安全禁止姓名比對而無法列出。Assistant/app-token 保留 name-only 相容，因而不能建立 TCRT-native assignment；它們透過 normalizer 防止 stale FK。restart/re-run clone 將來源 identity 交給 normalizer 重新驗證：來源 local user 已停用或不再有 write capability時，新的 Item 只保留安全 display snapshot，不保留可匹配 local／外部 identity。

應用程式永久刪除 User 時，必須在同一 main-DB transaction 先清除所有精確比對該 User 的 local FK、Lark id 或 normalized email 的 Item 之 `assignee_id`、`assignee_email`、`assignee_json` 和 local FK，保留非機器可比對的 display snapshot，再刪除 User；FK 仍提供 `ON DELETE SET NULL` 的資料庫層保護。這避免日後重建／重用相同 Lark id 或 email 的帳號承接舊工作。

替代方案是以 `assignee_name` 作唯一鍵、只在 Dashboard 查詢時 heuristic match，或把 `User` 取代 Lark 欄位。名稱會碰撞、runtime match 無法修正舊寫入，後者會破壞整合，故不採用。

### 7. Schema migration 為可回復的精確 backfill

main Alembic migration 依序：加入 nullable column、以跨引擎安全方式建立 FK／索引、針對每筆 legacy row 只以 active、具現有角色 write capability 且 candidate count 恰為一的 exact Lark id 或 `trim + lower` email 回填、id/email 同時存在卻不一致時跳過，並保留不匹配／歧義／read-only 資料。新增索引為 `(assignee_user_id, updated_at)` 與 `(changed_by_id, changed_at)`；audit DB 無 migration。

對 SQLite 使用 Alembic batch operation 處理 FK alter；MySQL/PostgreSQL 使用 portable Alembic operation。downgrade 只移除 FK、索引與新欄位，保留原始 assignee snapshot。應用程式 rollout 先執行 migration，再部署依賴新欄位的程式；回滾時先回退程式，再 downgrade schema。

### 8. 首頁是 cross-team UI，但不改變現有 Assistant 或 authorization 行為

首頁不把舊 `currentTeam` badge 當作 Dashboard scope；System Administration Dashboard 顯示 system scope。既有 Assistant widget 維持其 fixed FAB、對話與 turn context 行為，Dashboard 不主動清除或設定它。所有深連結仍由目標頁面的既有權限檢查守門，Dashboard link 不是授權憑證。

## Risks / Trade-offs

- [舊姓名／不完整 Lark 資料無法安全回填] → 只回填精確唯一 Lark id／email；其餘留在 legacy 狀態，不以名稱猜測。
- [多個舊寫入／clone 路徑可能留下 stale FK] → 以單一 normalizer 覆蓋 JWT、batch、assistant、app-token、restart/re-run 與 Set item construction，並在 bulk 寫入前 preflight identity。
- [comment 被誤算為 execution 或結果] → 固定以 result／execution-time transition 做 resume 與成果 predicate，comment 僅可列為 activity。
- [歷史表含未知 legacy enum] → 對 resume／activity／outcome 分區隔離，未知值不計數且不得中斷 assigned／Team 資料。
- [刪除帳號後 identity 被重用] → app-level delete transaction scrub 可機器比對的 external identity，DB FK 僅做 SET NULL 防護。
- [audit DB 不可用或延遲] → main DB 結果為必要來源，audit section 非阻斷、明示 partial。
- [Super Admin 摘要意外洩漏設定／log] → 固定 serializer allowlist、payload-level negative tests，禁止 pass-through DTO。
- [shared browser / localStorage 被竄改] → preference per-user key、server revalidation、no server scope input、no-store response。
- [Dashboard 查詢放大] → server-side limits、精確複合索引、必要欄位 projection、無 N+1 relationship traversal。
- [首頁與既有 shared-component refactor 併行修改] → 實作前 rebase 並沿用當下 canonical base/component structure，不複製舊 index inline-style pattern。

## Migration Plan

1. 在 disposable SQLite、MySQL、PostgreSQL fixture 驗證 migration upgrade、backfill、downgrade；確認 legacy snapshot 在三者皆保留。
2. 先部署 main migration；若 migration 失敗，停止應用程式 rollout，保留既有 schema／程式，依 Alembic failure state 執行 forward recovery，不以手動資料刪除修復。
3. 部署支援新欄位且保留 legacy input/output 的應用程式，並以 Dashboard read endpoint 與 assignee write regression tests 驗證。
4. 發現 application fault 時先回退 application；只有確認沒有運行中的版本依賴新欄位時才執行 downgrade。因 downgrade 不刪除 legacy snapshot，可用重新 upgrade 恢復欄位結構，但不承諾還原當時已清除的 FK 值。

## Open Questions

無。首版的角色分流、可續作狀態、結果時間窗、identity precedence、legacy fallback、System Admin allowlist 與 localStorage 行為均已由 proposal 與本設計固定；後續變更必須以新的 requirement／change 明示提出。
