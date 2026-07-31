## ADDED Requirements

### Requirement: Global conversation 不依賴 workspace team

Global Assistant conversation 與 turn SHALL NOT 接受、保存或推導目前頁面的 team 作為 routing 或 authorization input。送出訊息 API MUST NOT 接受 `context_team_id`；切換 workspace team MUST NOT 切換 active global conversation，也 MUST NOT 改變進行中回合的工具目錄。

#### Scenario: 從無 team 的頁面查詢指定 team

- **GIVEN** 使用者可存取 ART
- **WHEN** 使用者在不具 workspace team context 的頁面要求查詢 ART 的 test cases
- **THEN** global conversation 維持同一 session，且可透過明確 target selector 執行查詢
- **AND** 系統不得要求使用者先導覽至 ART 頁面

#### Scenario: 頁面切換不改變 active conversation

- **WHEN** 使用者在 ART 與 CID 頁面間切換後重新開啟 Assistant
- **THEN** 前端載入同一個 global active conversation key
- **AND** 不建立或切換為按 workspace team 分流的 conversation

### Requirement: Pending action 持久化 authoritative target team

每個 team-scoped pending mutation MUST 在建立 pending 的同一交易寫入 `assistant_pending_actions.target_team_id`、`target_team_name_snapshot` 與 `target_selector_json`。這些欄位 MUST 取自 executor 已完成 selector identity、角色 permission 與 resource ownership equality 驗證的 resolved team；MUST NOT 取自前端頁面、confirm request 或未驗證參數。Sensitive execution payload MUST 內含同一 target id，confirm 時必須與 pending target 相等。

欄位為 nullable 以容納歷史終態資料，但 runtime MUST 拒絕任何 target id/name 為 NULL 的 pending/executing action。`target_team_id` 不使用刪除時會改寫值的 FK；team 刪除後保留原 id供稽核，confirm 以 server lookup 不存在而 fail-closed。

#### Scenario: 建立 pending 時快照目標

- **WHEN** global conversation 對 ART 建立 write pending
- **THEN** pending 的 target id/name snapshot 為 ART identity，並保存 LLM 原始 selector
- **AND** confirmation summary 顯示由伺服器 lookup 的 `ART (#id)`

#### Scenario: team 刪除使 pending 失效

- **WHEN** pending target team 在 confirm 前被刪除
- **THEN** pending 仍保留原 target id，但 confirm lookup 不到 team，原子 expire action、清除 payload、寫 synthetic result，且不 dispatch

## MODIFIED Requirements

### Requirement: 對話 scope 與 team 綁定

每個對話 SHALL 有不可變 `scope_type`（`global` 或 `team`）。`scope_type=team` 的 historical conversation 繼續固定使用 conversation `team_id`；`scope_type=global` SHALL 不綁定 team，每個 team-scoped tool call 必須使用伺服器驗證的明確 selector。Global tool catalog MUST NOT 因缺少 workspace team 而降級為 discovery-only。

#### Scenario: Global 回合提供角色允許的 mutation 工具

- **WHEN** USER 或 ADMIN 在 global conversation 開始回合且頁面沒有 team context
- **THEN** tool catalog 仍包含其角色允許的 team-scoped write 工具
- **AND** 每個 team-scoped schema 要求明確 `target_team`

#### Scenario: Team-bound historical conversation 維持固定 team

- **WHEN** historical team conversation 執行 team-scoped tool
- **THEN** executor 使用 conversation 綁定 team
- **AND** LLM schema 不接受 global `target_team` selector
