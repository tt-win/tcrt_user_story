## Context

MCP machine token 的建立面已完整（[`create_mcp_machine_token`](app/api/organization_sync.py:104)：產生 raw token、SHA256 存 hash、寫稽核、回一次性明文），但**管理面缺席**——沒有列出，也沒有撤銷。Super Admin 關掉建立結果後就無從盤點或回收 token。

關鍵既有事實，本設計直接沿用：

- 資料模型 `MCPMachineCredential`（[`database_models.py:1694`](app/models/database_models.py:1694)）已具備 `status`（`ACTIVE`/`REVOKED`，[enum:59](app/models/database_models.py:59)）、`last_used_at`、`team_scope_json` 等欄位——撤銷所需狀態欄位**已存在**。
- 驗證端 [`mcp_dependencies.py:212`](app/auth/mcp_dependencies.py:212) **已**檢查 `status == ACTIVE`，非 ACTIVE 即回 401 `MACHINE_TOKEN_REVOKED` 並寫 denied 稽核。撤銷的「生效」路徑已現成，本 change 不需動 auth 程式。
- create 端點的既定模式：`MainAccessBoundary`（`run_read`/`run_write`）存取 DB、`require_super_admin()` 授權、`audit_service.log_action(...)` 稽核、回應包成 `{ "success": true, "data": {...} }`。
- 前端 MCP Token 分頁（[`team_management.html:443`](app/templates/team_management.html:443) + [`main.js:132`](app/static/js/team-management/main.js:132)）已有建立表單、`AuthClient.fetch`、`getI18n`、`AppUtils.show*`、`escapeHtml`、`formatIsoDatetime` 等可重用零件，分頁可視由 `tab-mcp-token` 權限規則控管。

## Goals / Non-Goals

**Goals:**
- 讓 Super Admin 能在 UI 列出所有已核發 token 的 metadata（狀態／scope／到期／最後使用），並撤銷不再需要的 token。
- 後端兩個端點與既有 create 端點在 router 位置、DB 存取、授權、稽核、回應包裝上**完全一致**，把新增認知成本壓到最低。
- 撤銷為非破壞性軟刪，端到端可被驗收（DB 變 REVOKED → 下次 MCP 呼叫被拒）。

**Non-Goals:**
- 不重現 raw token（明文未留存，hash 不可逆）。
- 不編輯既有 token 設定、不硬刪、不分頁（token 量級小）。
- 不改動 create 端點與 auth 驗證程式。

## Decisions

### D1：端點放在 `organization_sync.py`，不放 `mcp.py`
token 管理是**人類 Super Admin** 透過 JWT 操作的 admin API（`/api/organization/...`），與 `mcp.py`（machine-token 驗證的對外唯讀 API，`/api/mcp/...`）職責正交。緊鄰既有 create 端點可直接複用其 import 與模式。
- *替代*：新開 router 檔——僅兩個端點且 create 已在此，徒增檔案，否決。

### D2：回應沿用 `{success, data}`，不用 MCP 的 `{team_id, items, page}`
本端點是 organization admin API，sibling create 回 `{success:true, data:{...}}`。列表回 `{success:true, data:{items:[...], total:N}}` 與之對齊；不採 `mcp.py` 的 `MCPPageMeta` 分頁模型（那是另一個 API 家族的慣例）。

### D3：撤銷用 `DELETE /{credential_id}`（軟刪語意）
資源在語意上「停用」，REST 上以 DELETE 表達最直覺；實作為軟刪（改 status），於 spec／design 寫明「DELETE = 軟刪、保留資料列」。
- *替代*：`POST /{id}/revoke`——語意更顯式，但本系統 admin API 未見此風格，且 DELETE 已足夠表達；否決以維持一致。

### D4：重複撤銷為 idempotent（回 200 no-op），非 409
撤銷是「使其失效」的意圖式操作，對已撤銷者再撤銷無害。idempotent 對前端與自動化更友善（重按、競態重送都安全）。實作上：載入 credential，若已 `REVOKED` 直接回 200 且**不**重複寫稽核；否則改狀態 + 寫一筆 `ActionType.UPDATE` 稽核。
- *替代*：已撤銷回 409——徒增前端錯誤處理，否決。

### D5：撤銷稽核用 `ActionType.UPDATE`，非 `DELETE`
ActionType 列舉無 `REVOKE`；撤銷是狀態變更、資料列保留，`UPDATE` 比 `DELETE`（語意上的整列移除）更貼實。`resource_type=SYSTEM`、`resource_id="mcp_machine_credential:{id}"`、`action_brief="撤銷 MCP machine token: {name}"`，與 create 稽核對齊。

### D6：列表序列化採欄位白名單，杜絕 secret 外洩
不直接 dump ORM 物件，而以明確 dict 組裝白名單欄位（見 spec），`token_hash` 永不進入序列化路徑。`team_scope_ids` 由 `team_scope_json` 以既有解析邏輯還原（沿用 `_normalize_team_scope_ids` / `json.loads` 的既有模式）。對應測試直接斷言回應不含 `token_hash`。

### D7：顯示狀態（active／revoked／expired）由前端衍生，後端只回真相
後端 `status` 僅 `ACTIVE`/`REVOKED`；「過期」是 auth 當下以 `expires_at` 判定，DB 不會把過期者改成別的 status。故列表回 `status` + `expires_at` 原值，前端據此衍生三態徽章（`revoked` 優先；否則 `expires_at` 已過 → `expired`；否則 `active`）。後端不對 status 說謊，避免與 auth 判定不一致。

### D8：前端列表載入時機
`loadMcpTokens()` 於三處觸發：MCP Token 分頁首次顯示（Bootstrap `shown.bs.tab`）、建立 token 成功後、手動 Refresh 鈕。撤銷成功後重載列表並以 `AppUtils.showSuccess` 回饋。撤銷前以 confirm 對話框顯示 token 名稱，避免誤撤。

### D9：列表為主畫面、核發改用 modal
MCP Token 分頁以「已核發 Token」列表為主畫面，核發表單移入疊加 modal（`#mcpTokenCreateModal`，由列表卡 header 的「核發 Token」鈕開啟）。開啟方式採 JS `new bootstrap.Modal(el).show()`（比照 [`org-automation-infra.js`](app/static/js/team-management/org-automation-infra.js) 等本專案所有 modal）；**不**使用 Bootstrap `data-bs-toggle="modal"` data-API——本專案無任何 modal 走 data-API，實測該路徑在此環境不被觸發。理由：此頁的日常情境是**盤點與撤銷既有 token**，建立屬低頻動作；列表優先符合管理直覺，建立收進 modal 降低視覺干擾。一次性 raw token 結果顯示於 modal 內（關閉前可複製）；modal 每次開啟（`show.bs.modal`）重整可選團隊並 reset 表單，避免殘留上一次的明文。表單 id（`mcpTokenForm` 等）原封保留，故既有提交／複製／reset 邏輯不變。
- *替代*：列表與建立並列雙卡——但建立表單長、會把列表擠到下方，與「以既有 token 為主」的目標相悖，否決。

## Risks / Trade-offs

- **[列表意外外洩 secret]** → 白名單序列化（D6）+ 測試斷言回應無 `token_hash`／`raw_token`。
- **[誤撤錯誤的 token]** → 撤銷以 `credential_id` 精準定位；前端 confirm 顯示 token 名稱再執行。
- **[列表與撤銷之間 token 被使用的競態]** → 可接受：auth 每次請求即時重查 status，撤銷在下一次呼叫即生效；不需鎖。
- **[同名 active/expired 視覺混淆]** → D7 由前端明確衍生三態徽章。
- **[建立者資訊缺失]** → 列表先只回 `created_by_user_id`（model 已有），不 join users 取 username；若日後需要顯示建立者名稱再增強（見 Open Questions）。

## Migration Plan

- **無 DB migration**：重用既有 `mcp_machine_credentials` 表與 `REVOKED` enum 值。
- 部署即純程式 + 前端資源更新；無資料轉換、無 bootstrap 變更。
- **Rollback**：還原程式即可；已撤銷者狀態留在 DB（資料安全，不因 rollback 復活）。必要時可直接改 DB `status` 還原個別 token（非本次 UI 範圍）。

## Open Questions

- 列表是否要顯示「建立者 username」？目前傾向只回 `created_by_user_id`，避免每筆 join；如 UX 需要再加一次 batch 解析。
- 是否需要在列表提供「依狀態過濾（只看 active）」？預設不做（量級小、前端可本地過濾），保留為後續增強。
