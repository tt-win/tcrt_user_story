## 1. Test Run assignee identity foundation

- [x] 1.1 在 `TestRunItem` ORM、JWT/Pydantic response schema 與 fixture 中加入 additive 的 `assignee_user_id` relationship、non-empty display snapshot 與安全 response projection 支援；維持 app-token／Assistant 最小 projection 不洩露 local id。
- [x] 1.2 實作跨路徑共用的 assignee normalizer：field-presence clear 語意、disjoint input／Lark id-email conflict validation、exact-candidate resolution、bulk preflight 與 active/write-capability target validation。
- [x] 1.3 將 JWT create/single/batch/filtered batch、app-token create/single/batch、Assistant name-only、Test Run restart/re-run clone 與 Test Run Set item construction 接至 normalizer；保留 legacy payload 相容、清除 stale local identity，並在 application User delete transaction scrub 可 machine-match 的 assignee identity。
- [x] 1.4 建立受 Test Run write permission 保護、最小 projection 且有限制的 local TCRT assignee lookup API，並接上指派選擇 UI。
- [x] 1.5 新增 main Alembic migration：nullable `assignee_user_id` FK（`ON DELETE SET NULL`）、兩個複合索引與僅 active/write-capable、candidate-count-one exact Lark／normalized-email 的 best-effort backfill；實作安全 downgrade 與 SQLite batch handling。

## 2. Role-aware Dashboard backend

- [x] 2.1 建立 `GET /api/dashboard` 的 current-user role dispatch、typed response model、`Cache-Control: no-store` 與 generic auth/error handling，不接受 client scope parameter。
- [x] 2.2 實作 Personal Dashboard main-DB read model：active/visible Team 範圍、active/draft queue、server-derived read-only／write action mode、resume state、local-FK-first legacy fallback、bounded stable sorting、minimal Team/Run/Set/Test Case projection 與 server-built deep links。
- [x] 2.3 實作 Result History 活動／最近七天成果聚合與 section isolation，確保 actor-id 精確比對、僅真實 result/execution-time transition 可做 resume／outcome、每個 Item 只計最新 completed result，未知 legacy enum 可安全降級，且 assignment-only／comment 更新不偽造 execution activity。
- [x] 2.4 以獨立 audit DB boundary 實作 allowlisted personal Audit fallback 與 per-section `ready`／`partial`／`unavailable` 降級行為。
- [x] 2.5 實作 Super Admin system summary assembler：固定 allowlist、section status、provider configured boolean、scheduled service 安全狀態、注意事件摘要與 management link allowlist；禁止 raw settings/log/error/credential pass-through。

## 3. Dashboard frontend and localization

- [x] 3.1 以現有 base layout 與 canonical TCRT component structure 重寫首頁 template、CSS、JS，依 server `dashboard_type` 渲染 Personal 或 System Administration Dashboard，並移除舊多 Team card flow。
- [x] 3.2 實作 Personal Dashboard 的 loading、empty、partial、generic-error、resume、assigned、activity、outcomes、quick action、Viewer read-only state 與安全文字渲染；所有動態 DOM 走既有 i18n lifecycle。
- [x] 3.3 實作 per-user localStorage preferred Team：明確 set-preference control、驗證／失效清除／無 storage fallback、AuthClient user/token request guard 與 BFCache revalidation；設定偏好不得切換 `AppUtils.currentTeam`，僅在使用者點擊 Team／Run／Set 入口時設定它。
- [x] 3.4 實作 System Administration Dashboard 的 system-scope 視覺、safe summary cards、unavailable states 與 server allowlisted management shortcuts；保留右下角 AI Assistant FAB overlay，不預留空白軌道。
- [x] 3.5 補齊 `en-US`、`zh-CN`、`zh-TW` Dashboard、狀態、無障礙與 assignee selector 文案，並確認 header／Team badge 呈現不把 `currentTeam` 當成首頁 scope。

## 4. Regression coverage and verification

- [x] 4.1 新增 Dashboard API／service tests：Super Admin/Admin/User/Viewer dispatch、Viewer no-execute、client scope tampering、降權／停用、inactive/no Team、identity collision、terminal／draft queue、null-safe `NULL → result` outcome、unknown legacy result partial isolation 與 no-store header。
- [x] 4.2 新增 Audit fallback／System summary security tests：audit DB failure partial response、raw Audit/provider/scheduled-service/log 資料不可出現在 payload、任一 section failure 不外洩 exception。
- [x] 4.3 新增 assignee normalizer tests：TCRT-only user、精確 Lark/email resolve、id-email conflict、名稱碰撞、omitted-vs-clear、bulk all-or-nothing 422、restart clone、legacy batch/app-token/Assistant compatibility、app-token minimal projection、FK priority、User delete identity reuse 與 assignment-only history 行為。
- [x] 4.4 新增 migration upgrade/backfill/downgrade tests，覆蓋 SQLite、MySQL、PostgreSQL fixture、normalized-email candidate collision、id-email conflict、inactive/read-only skip 與 User delete `SET NULL` 行為。
- [x] 4.5 新增首頁 component/JS tests：localStorage account isolation、explicit preference does not set currentTeam、invalid preference、late-response account switch、BFCache revalidation、deep link/currentTeam timing、dynamic escaping、read-only state、comment-not-outcome、三語 i18n、Assistant FAB 共存與響應式／empty states。
- [x] 4.6 執行目標 pytest、`uv run ruff check .`、`npm run lint`、`node scripts/check-i18n-coverage.mjs`、相關 JS syntax checks、`openspec validate add-personal-dashboard --strict` 與 `graphify update .`，修正本 change 造成的診斷。
- [x] 4.7 修正 Dashboard bootstrap 對既有 `/api/auth/me` `user_id` response contract 的處理，避免登入成功後永久停在 loading，並新增回歸測試。
- [x] 4.8 精簡首屏近期活動為五筆並提供完整近期活動 modal、修正快速功能 responsive layout、將偏好 Team 改為首次設定／單一入口／可修改 modal，並以 Lark name 優先、TCRT username 回退顯示問候。
- [x] 4.9 補齊上述首頁 refinement 的 component／JS／API regression tests 與三語文案，執行目標 pytest、Ruff、frontend lint、i18n coverage、JS syntax、OpenSpec strict validation、Graphify update 與 browser QA。
- [x] 4.10 移除 Personal Dashboard 的獨立「稽核活動摘要」卡片與未使用文案，保留後端 Audit fallback 安全契約，並補回歸與瀏覽器驗證。
- [x] 4.11 修正 Test Run 單筆／批次 assignee selector 丟失 local／Lark machine identity，確保指派後下一次 Dashboard request 可列入「指派給我」，並補 frontend／API 回歸與 browser QA。
- [x] 4.12 修正 Lark contact 同時送出 id/email 造成單筆指派 422：selector 改為 Lark id 優先、email fallback 的單一 machine identity，保留後端明確衝突防護，並補單筆／批次回歸測試。
- [x] 4.13 修正批次確認殘留 `assigneeName` 造成的 ReferenceError 與單筆清除傳入 `null` 的 TypeError，並新增由 pytest 執行的 Node runtime regression，覆蓋 local、Lark id、email fallback、自訂文字、清除、僅改結果與空白防護。
- [x] 4.14 將 Personal Dashboard 的 assigned Item 表格改為 server-side Team＋Test Run 聚合的緊湊 Run 清單，只顯示 run-level link 與精確 Item 數量，移除 Updated、個別 Test Case、Test Run Set、result 與獨立 Actions，並補三語文案、API／frontend regression；登入態 visual QA 因隔離 Browser session 無既有登入狀態而留待人工確認。
- [x] 4.15 修正完成結果後 Resume 消失：改為 active Run 的最近 execution transition 並按 Run 去重；Assigned Run 改為可展開的 bounded Item 預覽；Preferred Team 移除 Open 並讓 quick actions 使用偏好 Team context；依既有組織開關補回 Automation Hub quick action，並補 API／frontend／三語回歸。
- [x] 4.16 將 Resume Work 收斂為純 Test Run projection 與緊湊 Run-level UI，只顯示 Run、Team、上次操作時間及 Return CTA，移除 Item／Test Case／result／Set 資訊，並補 API／frontend／三語回歸與視覺檢核。
- [x] 4.17 將 Preferred Team 收斂為緊湊同列控制、將 Quick Actions 收斂為具 localized accessible name／tooltip 的 icon-only rail，消除 hover 位移裁切並以偏好 Team 解析 User Story Map team route；將 Outcomes 改為無外部依賴的 SVG donut-style pie chart 加總數與文字圖例，並補三語、frontend regression 與響應式視覺 QA。
- [x] 4.18 將 Dashboard 改為固定 viewport workspace 與 section body 內捲動、固定中央問候 hero；簡化近期活動摘要並重做 bounded detail modal；將 Resume 擴充為 Test Run、Test Case、User Story Map、Automation Hub 的安全跨功能近期工作 union，並補 API／frontend／三語與視覺回歸。
- [x] 4.19 將 Resume 工作收斂為桌面單列且跨列欄位對齊的高密度資訊列、Quick Actions icon-only 按鈕改為等寬填滿 rail，並將近期活動 modal 改為具足夠寬度、一筆一列的 canonical compact table；補 frontend／三語／responsive visual regression 與完整驗證。
- [x] 4.20 將 Outcomes card 改為頂端標題加自適應內容列，讓 SVG pie chart 依剩餘高度放大並與 responsive 圖例共同填滿卡片、消除上下無效留白；補 frontend 與桌面／窄螢幕 visual regression。
