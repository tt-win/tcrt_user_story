## Context

助手的對話已全域化（`scope_type='global'`），但工具執行層仍假設「對話綁定單一 team」：

- [assistant_agent_service.py](app/services/assistant/assistant_agent_service.py) 對全域對話只給 `registry.discovery_only()`（10 個 `team_check=none` 的唯讀工具）。
- [tool_executor.resolve_team()](app/services/assistant/tool_executor.py:214) 對 `inject` 工具回傳 `conversation_team_id`；`run_read_tool` / `prepare_write_tool` 再要求 `resolved_team == conversation.team_id`。
- [check_permission()](app/services/assistant/tool_executor.py:205) 在 `team_id is None` 時只允許 READ 工具。
- [assistant.py:530](app/api/assistant.py:530) 的 confirm 端點對全域對話直接回 409 `SCOPE_INVALID`。

前端 [assistant-widget.js](app/static/js/assistant-widget.js) 只會建立全域對話，因此上述四道閘門疊加的結果是：77 個工具中 67 個（19 `inject` + 48 `resolve`）對所有角色永久不可用，助手實際上是唯讀的。使用者以 admin 身分要求「在 ART team 建立 test case set」被拒、切換工作區也無效，就是這個缺口。

既有約束：

- `assistant-tool-execution` 明訂 `team_id` MUST NOT 出現在 LLM 可控的參數 schema——本設計不得破壞此不變量。
- 確認卡的 fingerprint 綁定 canonical summary + stable target identity；summary 變動會產生 `CONFIRMATION_STALE`。
- `AssistantTurn` 目前沒有任何 team 欄位；`AssistantPendingAction` 亦無，audit 表 `AssistantToolExecution.team_id` 已存在。
- 專案支援 SQLite / MySQL 8 / PostgreSQL 16，schema 變更須為版本化 migration 且非破壞性。

## Goals / Non-Goals

**Goals:**

- 全域對話能在**明確、可稽核**的目標 team 上執行 team-scoped 讀寫，恢復助手的寫入能力。
- 目標 team 的決定權留在使用者與伺服器，不交給 LLM。
- 使用者在按下確認前，必然看得到「這個動作會落在哪個 team」。
- 缺少目標 team 時 fail-closed（退回唯讀 discovery），而不是猜一個 team。

**Non-Goals:**

- 不恢復 team-bound 對話入口，不改全域 session 的連續性。
- 不讓 LLM 指定 `team_id`，不放寬角色→權限映射，不改兩級確認卡分類。
- 不支援「一個 turn 內跨多個 team 的寫入批次」。
- 不做助手面板的唯讀 badge（沿用另一個變更的 Open Question）。

## Decisions

### D1: context team 由前端工作區提供，並在 turn 上快照

送訊息端點（multipart）新增 `context_team_id` 欄位，值為前端目前工作區 team；伺服器在 TurnStart Tx 一併寫入新欄位 `assistant_turns.context_team_id`。之後同一 turn 的所有工具執行、confirm 與 audit 都讀這份快照。

替代方案：

- **LLM 指定 team_id**——否決：破壞既有安全不變量，且模型可能從工具結果（＝不可信資料）推導出別的 team。
- **從 Referer／URL 推斷**——否決：脆弱、可偽造，且與前端狀態不同步。
- **重新把對話綁回 team**——否決：等於放棄全域 session（使用者選了方向 A）。
- **每次執行都讀「前端當下的工作區」**——否決：使用者在確認卡出現後切換工作區，就會把動作落到另一個 team；快照是這裡的安全關鍵（見 D4）。

### D2: context team 必須通過可存取性驗證，且 fail-fast

伺服器收到 `context_team_id` 時 MUST 以 `permission_service.get_user_accessible_teams(user_id)` 驗證；不在清單內即 422 拒絕建立 turn（不 silently 忽略、不降級為 discovery）。缺值（舊版前端、使用者未選工作區）則視為「無 context team」（D6），這是 fail-closed 的正常路徑，不是錯誤。

### D3: 單一 `effective_team` 解析點

新增一個解析函式：`effective_team(conversation, turn) = conversation.team_id if conversation.scope_type == "team" else turn.context_team_id`。executor 目前所有讀 `conversation.team_id` 的位置（`inject` 注入、`resolve` 比對、`check_permission`、journal／audit 的 `team_id`）改為統一取此值。理由：這個判斷若在四處各寫一次，任何一處漏改就是跨 team 越權或功能不通；集中一處才能用測試守住。

### D4: confirm 只信 turn 快照，不信 confirm 當下的前端狀態

confirm 端點移除全域對話的 `SCOPE_INVALID` 硬拒，改為：pending action → 其 turn → `context_team_id` 快照 → 重新 `check_team_permission` → 注入 loopback。confirm request **不接受** team 參數。

配套：確認卡 summary MUST 含目標 team 名稱（D5），因此「使用者在確認前切換工作區」不會改變已建立的 pending 的目標 team；而若目標資源本身被搬到別的 team，summary 變動會走既有的 `CONFIRMATION_STALE` 路徑要求重新確認。

### D5: `resolve` 類工具改為「可存取 + 該 team 檢權」，並強制 team 可見性

`resolve` 工具（48 個）由資源 id 反解 team 後，MUST 驗證該 team 在使用者可存取清單內、且該 team 上的權限涵蓋工具宣告的 `PermissionType`；不再要求等於 context team。理由：使用者常以全域搜尋找到某 team 的 case 再要求更新，若強制等於 context team 會無故失敗，且使用者已對該 team 有權限。

代價是「動到非當前工作區的 team」成為可能，因此 team 名稱進入確認卡與工具結果投影是這個決策的必要配套，不是選配。

### D5a: 批次寫入不放寬跨 team（實作期補充）

`batch_execute_actions` 的子動作仍要求全部落在有效 team（沿用等值比對）。單筆 `resolve` 工具可以作用於其他可存取 team，但一張確認卡只顯示一個 team 名稱；若批次混入多個 team，使用者無法從卡片判斷影響範圍。

### D5b: confirm 的判斷順序微調（實作期補充）

confirm 端點把「有效 team 為空」的判斷移到權限檢查**之前**：沒有 team 時 per-team 權限檢查沒有意義，且回 `SCOPE_INVALID` 才能說清原因（team 已刪除／turn 無快照）。兩條路徑都會原子 expire pending，安全性不變。

### D6: 無 context team → 維持 discovery-only 與 `no_team_context`

`effective_team` 為 None 時，工具目錄仍只給 discovery（現況行為），capability context 的原因由 `global_scope` 改為 `no_team_context`，補救改為「在介面選擇目標 team 的工作區後重試」（這是真的可行入口，與前一個變更修掉的死路不同）。舊 turn 的 NULL 快照自然落在此路徑。

### D7: 指名 team 與 context team 衝突 → 反問，不猜

capability context MUST 明示本回合 context team（名稱 + id），system prompt MUST 要求：使用者訊息指名的 team 與 context team 不一致時，反問或請使用者切換工作區後重試，MUST NOT 自行選一個 team 執行。理由：這是唯一「模型有機會誤判目標」的缺口，且錯誤代價是跨 team 寫入。

### D8: migration 非破壞性、跨引擎

`alembic/` 新增 revision：`assistant_turns` 加 `context_team_id`（`Integer`、nullable、FK `teams.id` ON DELETE SET NULL、加 index）。SQLite 需 `batch_alter_table` 才能加 FK；downgrade 移除欄位。既有資料一律 NULL → 走 D6，不需回填。

## Risks / Trade-offs

- **[跨 team 誤寫：LLM 選了別 team 的資源 id，使用者沒注意就確認]** → 三層：確認卡與工具結果強制顯示 team 名稱（D5）、每次執行對該 team 檢權、audit `AssistantToolExecution.team_id` 記錄實際生效 team；D7 要求衝突時反問。
- **[使用者在確認卡出現後切換工作區，動作落到非預期 team]** → context team 取 turn 快照而非當下前端狀態（D1/D4）；summary 已含 team 名稱，變動走 `CONFIRMATION_STALE`。
- **[前端未更新（瀏覽器快取舊 JS）不送 `context_team_id`]** → 視為無 context team，退回唯讀 discovery（fail-closed），不會誤用預設 team。
- **[使用者沒有選定工作區 team，卻期待助手能寫入]** → capability context 以 `no_team_context` 明確說明並給出可行補救；不猜 team。
- **[SQLite 無法直接加 FK]** → `batch_alter_table`；migration 在三種引擎的 disposable DB 各驗一次。
- **[`effective_team` 改動漏掉某個既有呼叫點，造成越權]** → 集中為單一 helper（D3），並以「全域對話 + 無 context team 的 write 一律被拒」的端對端測試守門。

## Migration Plan

1. 套用 alembic revision（新增 nullable 欄位，既有資料不動）。
2. 部署後端：舊前端仍可運作（無 `context_team_id` → 唯讀 discovery，與現況一致）。
3. 部署前端：開始送出工作區 team，寫入能力隨即恢復。
4. Rollback：程式碼 revert 即可（欄位 nullable，回退後不再讀取）；如需完全回退 schema，執行 downgrade 移除欄位。無資料回填、無破壞性轉換。

## Open Questions

- 是否允許使用者在助手對話內以自然語言切換目標 team（例如「改在 CID 建立」自動改 context team）？本設計選擇要求切換工作區，避免 LLM 影響目標 team；若後續要放寬，需重新評估 D7 的風險。
- 是否在助手面板顯示「目前操作 team」常駐提示（比只寫在確認卡更早暴露目標）。屬 UI 增強，未納入。
