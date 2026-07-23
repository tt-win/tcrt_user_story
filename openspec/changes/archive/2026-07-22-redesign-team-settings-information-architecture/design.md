## Context

`/team-management`（`team_management.html`，1034 行）目前是 7 個功能區塊的唯一入口：

| # | 功能區塊 | 現況掛載位置 | 存取層級 | 既有 spec |
|---|---|---|---|---|
| 1 | Team CRUD + Lark Bitable 連結 | 頁面本體 `#teams-section` | 一般使用者可見自己所屬 team | 無 |
| 2 | 人員管理 | modal 分頁 `#tab-pane-personnel` | ADMIN+ | 無 |
| 3 | 組織同步（Lark 部門/使用者同步） | modal 分頁 `#tab-pane-org` | ADMIN+ | 無 |
| 4 | Service 管理（排程服務） | modal 分頁 `#tab-pane-service-management` | Super Admin | `scheduled-service-management` |
| 5 | MCP Machine Token 簽發 | modal 分頁 `#tab-pane-mcp-token` | Super Admin | 無（`mcp-machine-auth` 只管 token 的認證行為，不管簽發 UI） |
| 6 | 組織自動化基礎設施（CI/Result provider + Automation Hub 入口開關） | modal 分頁 `#tab-pane-org-automation-infra` | Super Admin | `automation-hub-provider-framework`（明文規定 UI 位置） |
| 7 | App Token（per-team） | 獨立 modal，從 team 卡片選單開啟 | team 內有權限者 | 無 |

後端權限設定（`config/permissions/ui_capabilities.yaml`）已經預留 `pages.organization` 區塊，內含 `tab-personnel-li`、`tab-org`、`tab-service-management`、`tab-mcp-token` 四個元件鍵——但從未有任何 template 用 `page=organization` 渲染成真正獨立頁面；`tab-org-automation-infra` 甚至完全不在 yaml 內，改由 JS（`applyOrganizationUiVisibilityByRoleFallback`）用寫死的角色判斷處理。這代表「組織層設定應該獨立」這個意圖，其實在權限層已經存在，只是前端從未實作出對應頁面。

repo 內已有的拆分前例：
- `system_logs.html`（spec: `system-log-viewer`）與 `assistant_admin.html` 都已從 team_management 拆成獨立頁面，只在 team_management 留一顆連結按鈕。
- `automation_provider_settings.html` 是 per-team 的「Git 來源設定」頁，從 Automation Hub 情境進入，完全不掛在 team_management 底下。

## Goals / Non-Goals

**Goals:**
- 決定新的資訊架構：哪些功能屬於「team 自己的資料/設定」（留在 `/team-management`），哪些屬於「org-wide、通常 Super Admin 專用的系統設定」（搬到新的「組織與系統設定」頁面）。
- 訂出新頁面的 URL、template 名稱、導覽 shell 結構、與既有 permission page key 的對應關係。
- 訂出 `automation-hub-provider-framework`、`scheduled-service-management` 兩份既有 spec 的 delta 內容，讓「UI 位置」的 spec 描述與新架構一致。
- 明確切出「本 change 直接落地」與「留給後續 change 執行」的邊界，並列出後續 change 的相依順序。

**Non-Goals:**
- 不重新設計任何功能區塊「內部」的操作流程／欄位／API contract（例如不改人員管理的欄位、不改 MCP Token 的簽發邏輯、不改 Automation Hub provider 的 CRUD 行為）——本 change 只動「這些功能長在哪個頁面、哪個入口」。
- 不引入新的權限模型或新的 Casbin policy；一律沿用既有 `feature` 分類（`team_management` / `user_management` / `organization_management`）。
- 不處理 App Token 是否該有更豐富的管理頁面（如列表搜尋、批次操作）——僅決定它目前該掛在哪裡。
- 不在本 change 內清理與本次無關的既存 drift（如孤兒的 `home.org-entry`、`organization.tab-test-cases` 這兩個目前看似未使用的 yaml key）——只記錄在 Open Questions，留給維護者決定是否另開 change 清理。

## Decisions

### D1. 新頁面沿用既有 `organization` permission page key 作為技術路由對應；頁面顯示文字沿用現有「組織與系統設定」字樣，不發明新詞彙

**決定**：新頁面路由為 `/organization-management`，template 為 `app/templates/organization_management.html`，`GET /api/permissions/ui-config?page=organization` 直接沿用（不需要新增合法值，這部分純屬技術層面的 page key 對應）。**頁面標題／導覽入口文字沿用既有、使用者已經看過的 i18n key `orgSync.modalTitle`「組織與系統設定」**，只是從「modal 標題」變成「頁面標題」；不使用「組織管理」這個字樣。

**修正說明（紅隊審查後修正）**：最初決定曾誤稱「組織管理」為既有 i18n 慣例，經審查確認這是錯的——`organization` 只是內部 permission page key／feature 名稱，從未出現在任何使用者可見文字中；真正使用者已經看過的字樣是按鈕與 modal 標題「組織與系統設定」（`orgSync.openButton`／`orgSync.modalTitle`），modal 內的「組織」分頁另有其名（`orgSync.tabTitle`，對應 `#tab-org` 組織同步功能本身）。若把新頁面取名「組織管理」，會與既有「組織」（=組織同步）字樣過度相似，讓使用者誤以為整個頁面只管組織架構同步，看不出裡面還有人員管理／MCP Token／自動化基礎設施。因此改為沿用「組織與系統設定」這個使用者已經熟悉、且字面上就暗示「不只組織資料」的既有字樣作為頁面標題，只搬地方、不改名詞，直接解決命名疑慮（原 Open Question 3，見下方已標記解決）。

**理由**：`ui_capabilities.yaml` 的 `pages.organization` 區塊已經存在多時且元件鍵命名（`tab-personnel-li`、`tab-org`、`tab-service-management`、`tab-mcp-token`）與本次要搬遷的分頁一一對應，代表這本來就是設計時預留的容器，沿用它作為**路由/權限鍵**可以把變更定位成「把早就規劃好、只是沒蓋出來的頁面蓋出來」；但頁面**顯示文字**是使用者真正會看到、記住、討論的東西，兩者是不同層次的決定，不應該因為技術 key 叫 `organization` 就連帶把顯示文字也改叫「組織管理」。

**考慮過的替代方案**：
- 造新詞「系統管理 / system-administration」：優點是語意更中性，但會與既有 `organization_management` feature、`orgSync.*` i18n namespace 並存兩套幾乎同義的詞彙，且使用者要重新學習一個從沒看過的名詞，成本高於直接沿用「組織與系統設定」。否決。
- 「組織管理」（原始決定）：經紅隊審查確認會與既有「組織」（組織同步）字樣混淆，且並非真正既有慣例，只是內部 key 名稱的誤用。否決，改為本次決定。
- 保留在 team_management 內但改成獨立分頁而非 modal：不解決「team 資料與 org 設定混在同一個網址下」的核心問題，只是換一種 UI 元件，否決。

### D2. 五個組織層分頁在新頁面內維持「單頁多分頁」結構（不拆成 5 個獨立網址）

**決定**：`/organization-management` 內部延續現有 tab 結構（人員管理／組織同步／Service 管理／MCP Token／組織自動化基礎設施 5 個 tab），只是從「team_management 裡的 modal」搬到「獨立頁面裡的 tab」。不把 5 個分頁各自拆成 5 條路由。

**理由**：這 5 個分頁的存取層級高度重疊（多數 Super Admin，人員管理/組織同步是 ADMIN+），使用情境也高度重疊（同一個 Super Admin 在同一次操作中可能依序看排程服務、MCP Token、provider 設定），拆成 5 個獨立頁面會增加導覽成本卻沒有額外收益。維持 tab 結構也讓既有 JS（`initMcpTokenTab`、`org-automation-infra.js` 的 `applyTabVisibility`）大部分邏輯可以整段搬移而非重寫。

**考慮過的替代方案**：每個分頁各自獨立頁面（如 `/organization/personnel`、`/organization/mcp-tokens`）：更符合「一個網址一個關注點」的嚴格 REST 精神，但對這個以 Jinja2 + 無 build pipeline 為前提的專案，會讓每個分頁都要重複一份頁面骨架（header/nav/權限守門），維護成本高於單頁多 tab。否決，但留在 Open Questions 供 red team 挑戰。

**紅隊審查後補充說明（承認的取捨）**：這個決定本質上是「依存取層級（多數 Super Admin）分組」而非「依功能性質分組」，紅隊審查正確指出這是把原本「team 資料 vs org 設定混雜」的問題，換成一個較輕微的版本「5 種不同的 org 設定混在同一個頁面」。這是本次刻意接受的取捨，理由是：這 5 個分頁目前都還小（每個都只是一張表格 + 一兩個 modal），拆頁的維運成本現在大於效益；一旦其中任何一個分頁未來成長到需要獨立導覽/獨立網址（例如組織自動化基礎設施若擴增更多 provider 類型），這個決定的設計不阻礙「單獨把那一個分頁再拆出去成獨立頁面」——因為每個分頁本來就有自己的 tab id、自己的 JS 模組、自己的 API，抽出去不需要重新設計。也就是說，D2 是一個可逆的中繼決定，不是把 5 個關注點永久焊死在一起。

### D3. `/team-management` 縮小為「team 資料 CRUD + App Token 入口」，不含任何 org-wide 內容

**決定**：`/team-management` 保留：team 清單、新增/編輯/刪除 team（含 Lark Bitable 連結欄位）、team 卡片操作選單（進入團隊各功能頁、App Token 入口）。移除「組織與系統設定」整顆按鈕與 modal，改為一顆固定的「組織與系統設定」連結（依 `organization_management:view` 權限決定是否顯示），置於頁面工具列，與既有「新增團隊」按鈕同排。

**理由**：這讓 `/team-management` 的心智模型單純化為「管理你能存取的 team 清單」，與頁面名稱一致；符合 D1／D2 決定的必然結果。

### D4. App Token 暫時維持在 `/team-management`（team 卡片選單），不搬到「組織與系統設定」頁

**決定**：App Token 是 per-team 憑證（scope 綁定單一 team，含 test_case/test_run/automation 權限），本質與「team 資料」同層級而非「org-wide 系統設定」，因此維持現狀掛在 team 卡片選單，不搬動。

**理由**：App Token 的存取層級與生命週期都綁定單一 team（`teams/{team_id}/app-tokens`），與人員管理／組織同步等「跨 team、org-wide」的性質不同；搬到「組織與系統設定」頁反而會製造新的混淆（使用者要去該頁面找「某個 team 的憑證」）。

**考慮過的替代方案**：
- 搬到 Automation Hub 內（因為 App Token 主要給 automation/CI 消費）——但 App Token 的 scope 不只 automation，也涵蓋 test_case/test_run 讀寫，放在 Automation Hub 情境反而窄化了它的定位。否決。
- 搬到「組織與系統設定」頁、放在 MCP Token 旁邊（因為兩者都是「憑證/token」的心智模型，紅隊審查明確指出這個角度）——否決，理由是：MCP Token 的存取層級是 Super Admin、且 token 本身是**跨 team**（可設定 allow-all-teams 或單一 team scope，但簽發者與管理者是 org 層級的人）；App Token 是**team 內有權限者自行為自己 team 簽發**，簽發者與消費者都是該 team 的人。兩者「像不像 token」不是決定落點的關鍵因素，「誰在管理、管理誰的東西」才是——這正是本次重新設計全篇的分類原則（team-scoped vs org-wide），若因為表面上都叫 token 就放在一起，等於用「功能形狀」取代「權限主體」作為分類依據，會自相矛盾。

**承認的殘留疑慮**：這個決定目前仍缺一個更完整的「team 設定」歸屬地——team 卡片編輯（`teamModal`）與 App Token（`appTokenModal`）目前是兩個各自獨立的 modal，本 change 不處理是否該合併成一個「team 設定」子頁面，僅確認兩者都應該留在 team-scoped 範圍。列入 Open Questions。

### D5. 既有 spec 的 delta 內容

- `automation-hub-provider-framework`：「Org-level provider UI MUST live in team management's org-sync modal」→ RENAMED 為「Org-level provider UI MUST live in the organization management page」，內容改為指向 `organization-management-console` 定義的分頁容器，並同步更新 audit/權限 scenario 中提到 `/team-management` 的敘述改為 `/organization-management`。`/automation-provider-settings`（Git 來源設定）相關 requirement 不變。**紅隊審查修正**：此 requirement 不重複描述 `tab-org-automation-infra` 的守門機制細節（避免與 `organization-management-console` 形成兩個權威來源），只引用後者。
- `scheduled-service-management`：Requirement 標題 RENAMED 為「Super Admin can manage scheduled services in organization management page」，內容改為指向「組織與系統設定」頁面。**紅隊審查修正**：delta 機制（ADDED/MODIFIED/REMOVED/RENAMED Requirements）沒有可以改「## Purpose」段落的操作，因此 Purpose 文字「團隊管理 / 組織管理流程」無法透過 delta 檔案本身修正，只能在實作驗收、sync 進主 spec 時**手動**編輯 `openspec/specs/scheduled-service-management/spec.md` 的 Purpose 行；tasks.md 已將此列為明確任務並加入驗證 checklist（見 10.2、11.6），不能只靠 delta 檔案自動帶過。

### D6.（紅隊審查後新增）`tab-org-automation-infra` 的 yaml action 值必須釘死為 `advanced`，不可留白

**決定**：`config/permissions/ui_capabilities.yaml` 內 `pages.organization.components.tab-org-automation-infra` SHALL 設為 `{ feature: organization_management, action: advanced }`，與同頁其他 Super-Admin-only 分頁（`tab-org`、`tab-service-management`、`tab-mcp-token`）採用完全相同的 action 值。

**理由（紅隊審查發現的真實風險）**：`app/auth/permission_service.py` 的 fallback 邏輯對 `organization_management` feature 的 `view` action 會放行 ADMIN 角色，但 `advanced` action 只放行 Super Admin。目前 `org-automation-infra.js` 是寫死 `role !== 'super_admin'` 的 fail-closed 判斷；若任務 8.2 把它改成讀 yaml 設定時，選錯 action 值（例如誤用 `view` 或籠統寫「或既有等義 action」而未明確指定）會讓 Admin 角色第一次能看到組織層 CI/Result provider 設定與 Automation Hub 開關——這是本次重新設計「不引入新權限模型」這個 Non-Goal 下絕對不能發生的真實權限提升風險，不是單純的過渡期時序問題。因此本決定明確釘死數值，不留給實作階段自行判斷。

## Risks / Trade-offs

- **[Risk] 使用者既有操作習慣被打斷**——長期使用者已經記得「組織與系統設定」在 team_management 頁面。→ **Mitigation**：`/team-management` 保留一顆顯眼的「組織與系統設定」入口連結（沿用原本開 modal 按鈕的視覺位置與完全相同的文字，見 D1 修正），且沿用完全相同的 tab id／component id，降低重新學習成本。
- **[Risk] 分頁錨點與內部文件連結失效，且會是「靜默」失效而非明顯錯誤**（紅隊審查加強）——`docs/`、`manual/` 或使用者書籤可能引用舊的 `#tab-pane-*` 錨點；由於 `/team-management` 頁面本身不會下架，訪問舊錨點只會正常載入頁面、但找不到對應 DOM／不會捲動到任何東西，使用者可能誤以為功能消失而非搬家，比明顯的 404 更難察覺。→ **Mitigation**：(a) design 階段先盤點 `docs/`、`manual/` 內對這些錨點/截圖的引用並同步更新（見 tasks.md 1.1）；(b) 新增一個輕量 JS 相容性提示：`/team-management` 載入時若偵測到 URL hash 命中已搬遷的舊分頁 id（`#tab-pane-personnel` 等 5 個），顯示一次性提示條「此功能已搬至組織與系統設定頁面」並附連結，不做完整 client-side redirect（成本效益不對等），但避免使用者誤判功能消失。
- **[Risk] JS 職責拆分若逐分頁進行，會在遷移期間打斷尚未搬遷的其他分頁**（紅隊審查發現，原設計低估此風險）——`main.js` 目前用單一 `openSyncModal()` 作為全部 5 個分頁共用的 modal 啟動函式，且 `loadSyncModalData()` 內部同時呼叫組織同步與排程服務兩個分頁的載入邏輯，`applyOrganizationUiVisibility()` 一次性守門 4 個分頁；這些分頁不是彼此獨立的模組，逐一搬遷會在中間狀態打斷還沒搬完的分頁（例如搬走 `openSyncModal` 後，尚未搬遷的排程服務/MCP Token/自動化基礎設施分頁會因為共用的 modal 開啟入口消失而變成無法觸達）。→ **Mitigation**：見下方修正後的 Migration Plan——改為「新頁面內容全部就緒後才一次性切換」，而非逐分頁切換；共用的啟動/守門函式在切換前保持原樣不拆分。
- **[Risk] `tab-org-automation-infra` 從 JS 寫死角色判斷改成讀取 yaml 設定時，若 action 值選錯會造成真實的權限提升**（紅隊審查發現，非單純時序風險）——見 D6，已將 action 值明確釘死為 `advanced`，並要求 yaml 設定與讀取該設定的 JS 改動在同一個 commit／同一次部署內一起上線，避免任一方單獨先上線造成不一致。
- **[Risk] 目前沒有任何自動化測試覆蓋這 5 個分頁的角色可視性行為**（紅隊審查發現）——`app/testsuite` 內現有的 permission-ui-config 測試只涵蓋 `tab-mcp-token`、`tab-service-management` 兩個分頁，且都只測後端設定回傳，沒有涵蓋 `tab-org`、`tab-personnel-li`，更沒有涵蓋尚未存在的 `tab-org-automation-infra`；前端 DOM/可視性行為完全沒有自動化測試。→ **Mitigation**：tasks.md 新增明確任務，要求在導入 `tab-org-automation-infra` 的 yaml 設定時同步補上對應的 permission-ui-config 測試案例（Admin=false、Super Admin=true），不能只靠人工點擊驗證。
- **[Risk] `automation-hub-provider-framework` 是跨 skill 同步義務規格**——`openspec/project.md` 規定該 spec 的命名/掃描規則變動需同步更新 `tools/skills/tcrt-automation-pomify/`。本次只動 UI 位置文字，不動掃描規則/命名規則，不觸發同步義務，但需要在該 delta spec 的 PR 描述明確 opt-out 並附理由，避免審查誤判。→ **Mitigation**：tasks.md 內明列此 opt-out 說明義務。
- **[Trade-off] 單頁多 tab（D2）換來的是「所有組織層設定仍在一次 page load 內」**——對權限最低的 Super Admin 情境沒有效能疑慮（現況已是如此），是可逆的中繼決定（見 D2 補充說明）。
- **[Pre-existing risk，非本次引入，但審查中被發現，需明確揭露]** `app/api/organization_sync.py` 內 `GET /sync/status`、`GET /stats`、`POST /sync`、`POST /sync/background`、`DELETE /cleanup` 五個端點目前**完全沒有** `Depends(get_current_user)` 或任何角色檢查（同檔案內的 MCP Token／排程服務端點則有正確的 `Depends(require_super_admin())`）。這是現有系統既存的安全缺口，與本次「只搬 UI 位置、不改後端 contract」的範圍無關，本 change **不修復**它；但因為本 change 直接搬遷這幾個端點對應的「組織同步」分頁 UI，紅隊審查認為必須在此明確揭露，建議另開一個獨立的安全加固 change 補上這 5 個端點的伺服器端授權檢查，不應該被本次 IA 重排順帶掩蓋或遺忘。
- **[Pre-existing pattern，非本次引入]** `/team-management`（以及依計畫新增的 `/organization-management`）目前都只有前端 `ui-config` 可視性 gating，route 本身沒有伺服器端角色檢查（`system_logs.html`、`assistant_admin.html` 等既有頁面也是同樣模式）。本次新增的 `/organization-management` 頁面延續既有模式，不會讓現況變差，但因為它是一個具名、更容易被直接嘗試存取的獨立網址，建議列入 Open Questions 供決定是否要順手加一層輕量 route-level 守門作為 defense-in-depth（非必要，但風險發現後應決策一次，不應該預設略過）。

## Migration Plan

本 change 本身只產出規劃與 spec delta；實作分成以下可獨立驗收的階段（詳細任務見 `tasks.md`；**此處已依紅隊審查修正遷移順序**，不再逐分頁切換，改為「新頁面內容全部就緒才一次性 cutover」）：

1. **後端/權限**：`pages.organization` yaml 補上 `tab-org-automation-infra` 元件鍵（action 值釘死為 `advanced`，見 D6）；`pages.team_management` 移除已搬遷元件鍵。無 DB migration。yaml 變更與任何讀取它的 JS 改動須同一次部署上線，不可分批。
2. **建置新頁面（尚未對外連結）**：新增 `organization_management.html` + 對應 route，先搬「殼」（nav/tab 骨架、權限守門），5 個分頁內容依序搬入**新頁面**，但 `team_management.html` 內的「組織與系統設定」modal 與共用啟動函式（`openSyncModal`、`loadSyncModalData` 等）在此階段維持原樣、繼續服務既有使用者，兩邊 DOM/JS 暫時並存（新頁面的程式碼可以獨立開發、獨立驗收，不受尚未搬完的其他分頁影響，因為它不觸碰舊頁面）。
3. **逐分頁驗收（在新頁面上）**：每個分頁搬入新頁面後，針對 4 種角色（viewer/user/admin/super_admin）各驗證一次可視性與功能，全部通過前不對外開放新頁面連結。
4. **原子性 Cutover**：待 5 個分頁在新頁面全數驗收通過後，**一次性**移除 `team_management.html` 內的「組織與系統設定」modal DOM 與 `main.js` 內對應的共用函式，改為工具列上的「組織與系統設定」連結導向新頁面；同一個 commit 內完成 DOM 移除與 JS 清理，避免半殘留狀態。
5. **Spec/文件同步**：`automation-hub-provider-framework`、`scheduled-service-management` 的 delta spec 於 Cutover 完成後 sync 進主 spec（含手動更新 Purpose 文字，見 D5）；`docs/`、`manual/` 內相關敘述同步更新。

**Rollback**：階段 1-3（yaml、新頁面建置、逐分頁驗收）期間，舊頁面完全未受影響，可隨時單獨回退任一分頁的新頁面實作而不影響其他分頁或舊頁面。階段 4（原子性 Cutover，`tasks.md` 任務群組 9）**必須整批回退**——因為它是單一 commit 內完成 DOM 移除＋JS 清理＋yaml 元件鍵移除，回退時必須連同該 commit 一起還原，不可只回退部分檔案（否則會出現「modal 部分分頁已被刪、部分還在」的不一致中間態）。**（紅隊第二輪審查補充）** 若 Cutover 已上線一段時間、且任務群組 10（spec sync 進主 spec、`docs/`／`manual/` 文件更新）已經合併，此時才發現需要回退 Cutover，SHALL 一併回退任務群組 10 對應的 commit（尤其是已經 sync 進 `openspec/specs/` 的 spec 變更與手動編輯的 Purpose 文字），否則會出現「UI 已還原成舊版，但 spec／文件仍宣稱新頁面是唯一事實」的不一致；也就是說，一旦任務群組 10 上線，Cutover 就不再是「單獨可回退」的最終邊界，而是需要與其後續 spec/文件同步一起評估回退範圍。沒有資料層變更，無需資料回復。

## Open Questions

**已透過紅隊審查解決：**

1. ~~命名風險：「組織管理」是否會被誤解成只管組織同步？~~ **已解決**：改用既有字樣「組織與系統設定」作為頁面標題，不使用「組織管理」，見 D1 修正。
2. ~~新頁面上線節奏：逐分頁切換是否安全？~~ **已解決**：逐分頁切換在共用 modal 啟動函式的現況下不可行，改為「新頁面就緒後一次性 cutover」，見修正後的 Migration Plan。
3. ~~`tab-org-automation-infra` 的 yaml action 值~~ **已解決**：釘死為 `organization_management:advanced`，見 D6。

**仍待決策（不阻礙本 proposal 定案，留給 design 執行前最後確認或後續 change）：**

4. D2（單頁多 tab vs 5 個獨立頁面）：目前傾向單頁多 tab 且視為可逆的中繼決定（見 D2 補充說明）；若日後任一分頁明顯長大，可單獨拆出而不需重新設計其餘分頁。
5. D4（App Token 落點）：確認維持在 team_management 卡片選單；殘留疑慮是 team 卡片編輯（`teamModal`）與 App Token（`appTokenModal`）目前是兩個各自獨立的 modal，是否該合併成一個「team 設定」子頁面——本 change 不處理，留給後續 change。
6. `docs/`、`manual/` 內是否有大量圖文引用舊 UI 位置：範圍大小影響 tasks.md 工作量估計，需在 tasks 執行階段先盤點（見 tasks.md 1.1）再排入。
7. **（紅隊審查新增）** `app/api/organization_sync.py` 內 5 個組織同步端點完全沒有伺服器端授權檢查——這是預先存在、範圍外的安全缺口，但因為本 change 直接搬遷該功能的 UI，是否應該在同一批 PR 順帶补上最基本的 `Depends(get_current_user)`（甚至 `require_super_admin`），還是嚴格保持「本 change 只動 UI 位置」的範圍、另開專門的安全加固 change？**建議**：另開獨立 change 處理（避免把安全修復與 IA 重排的 code review 混在一起、互相拖慢），但本 proposal 必須在 Risks 中明確揭露此發現，不能略過不提——已完成揭露（見 Risks 第 7 條）。
8. **（紅隊審查新增）** 是否要為新的 `/organization-management`（以及既有 `/team-management`）route 加一層伺服器端角色檢查，作為 defense-in-depth，而不是只靠前端 `ui-config` 隱藏？現況（含 `system_logs.html`、`assistant_admin.html`）都是同樣模式，本次不強制要求，但建議在實作階段評估一次性補上（低成本：只是在對應 `app/main.py` route handler 加一個 `Depends`），而不是預設略過不討論。
