## Why

助手目前對**所有角色**都無法執行任何寫入操作。前端唯一的建立對話路徑（`assistant-widget.js` 的 `createConversation`）固定送 `scope_type: 'global'`，而 agent 迴圈對全域對話只提供 `discovery_only()` 的 10 個工具，confirm 端點更會對全域對話直接回 409 `SCOPE_INVALID`——77 個工具中有 67 個（19 個 `team_check=inject`、48 個 `resolve`）在實際產品中永遠不可用。使用者以 admin 角色要求「在 ART team 建立一個 test case set」仍被拒，切換工作區 team 也無效，因為對話 scope 不會改變。

這是 `global-assistant-session` 只完成工件、未實作 runtime 的缺口：對話已全域化，但工具執行仍假設對話綁定單一 team。

## What Changes

- 每個 turn 帶入一個 **context team**：前端隨訊息送出目前工作區 team，伺服器將其**快照**在 turn 上（新增 `assistant_turns.context_team_id`）。context team 由前端工作區狀態決定，**MUST NOT** 成為 LLM 可控參數（維持 `assistant-tool-execution`「team_id 不進 LLM schema」的不變量）。
- `team_check="inject"` 工具在全域對話改為注入 turn 的 context team（原本注入 `conversation.team_id`）；仍先對該 team 做 `check_team_permission`。
- `team_check="resolve"` 工具在全域對話改為：由資源 id 反解 team → 驗證該 team 在使用者可存取清單內 → 對該 team 檢權；移除「必須等於 conversation.team_id」的比對。
- confirm 端點移除全域對話的 `SCOPE_INVALID` 硬拒，改用 pending action 所屬 turn 的 context team 快照（不可變）重新檢權與注入；**BREAKING**（僅對內部 API 語意）：全域對話的 confirm 由必定 409 變為可成功。
- 確認卡與工具結果 MUST 顯示目標 team 名稱（`snapshot_team_name`），使用者才能確認「動到哪個 team」；跨 team 誤操作的風險靠此可見性 + context team 快照控制。
- 使用者訊息指名的 team 與 context team 不一致時（例如工作區在 ART 但說「在 CID 建立」），助手 MUST 反問或要求切換工作區，MUST NOT 自行選一個 team 執行。
- capability context（capability `assistant-agent-loop`）更新：全域對話有 context team 時不再回報 `global_scope`；沒有可用 context team 時原因改為 `no_team_context`，補救為「在介面選擇目標 team 的工作區後重試」。
- 非目標：不恢復 team-bound 對話入口；不放寬角色→權限映射；不讓 LLM 指定 team_id；不改確認卡的兩級風險分類；助手面板的唯讀 badge 仍不在範圍內。

## Capabilities

### New Capabilities

（無新 capability；行為歸屬既有的 assistant 對話／工具執行／確認卡契約。）

### Modified Capabilities

- `assistant-tool-execution`: `team_id` 注入來源由「對話綁定」擴充為「對話綁定或 turn context team 快照」；`resolve` 類工具的 team 比對由「等於對話 team」改為「屬於使用者可存取 team 且通過該 team 檢權」。
- `assistant-action-confirmation`: pending action 的執行 team 取自其 turn 的 context team 快照（不可變）；確認卡 MUST 顯示目標 team 名稱；全域對話不再一律 `SCOPE_INVALID`。
- `assistant-conversations`: 送出訊息時可帶 context team；turn 持久化其快照。
- `assistant-agent-loop`: 全域對話在具備 context team 時 MUST 提供該 team 的 team-scoped 工具（不再限於 discovery）；capability context 的原因改為 `no_team_context`；指名 team 與 context team 衝突時 MUST 反問。

## Impact

- 資料庫：`alembic/` 新增 migration 為 `assistant_turns` 加 `context_team_id`（nullable、FK `teams.id` ON DELETE SET NULL）；非破壞性，既有 turn 為 NULL。需檢查 `database_init.py`、bootstrap 與測試 fixture，並確認 SQLite / MySQL 8 / PostgreSQL 16 皆可套用。
- 後端：`app/api/assistant.py`（送訊息、confirm）、`app/services/assistant/conversation_service.py`（turn 建立與讀取）、`tool_executor.py`（`resolve_team`／`check_permission`／loopback 注入）、`capability_context.py`、`app/services/assistant/projection.py`（team 名稱可見性）。
- 前端：`app/static/js/assistant-widget.js` 送出訊息時附帶目前工作區 team、確認卡顯示 team 名稱；三語系文案（`app/static/locales/*.json`）。
- 安全：跨 team 寫入的把關由「對話綁定」換成「turn 快照 + 每次執行對該 team 檢權」；audit（`AssistantToolExecution.team_id`）記錄實際生效 team。
- 相依：本變更假設 `assistant-permission-aware-capability-context` 已合併（capability context 的 `global_scope` 原因由本變更改寫）。
