## Why

助手在回合開始會依使用者角色與對話 scope 預過濾工具目錄（design D2），但 system prompt 完全不含「你是誰、在哪個 scope、哪些能力被拿掉」的資訊，且明文宣告「工具目錄以外的操作一律視為不可能」。結果 VIEWER 角色要求寫入操作時，助手把**權限限制**誤述為**能力限制**（「我沒有建立 Test case set 的 API 工具」），甚至在使用者追問「是不是我權限不夠」時明確否認，並建議改用網頁介面——而 Viewer 在網頁上同樣無法執行該操作。這是可驗證的錯誤歸因，會讓使用者對系統權限模型與助手可信度產生錯誤認知。

## What Changes

- 每個回合在組裝 system prompt 後，附加一段 per-turn **capability context**：對話 scope（global / 指定 team）、使用者角色、允許的權限等級、被隱藏的寫入能力**類別**、隱藏原因（角色不足 / 全域 scope）、以及對應的補救指引。此區塊不進入既有的全域 system prompt process cache。
- 修正 factory system prompt 中絕對化的能力宣告：離題拒絕規則不變，但工具目錄缺少某個 TCRT 寫入操作時，助手 MUST 依 capability context 歸因到角色權限或對話 scope，MUST NOT 聲稱該功能不存在，MUST NOT 把「改用網頁介面」當成權限不足的解法。
- 新增 read-only local 工具 `describe_capabilities`（`team_check=none`、`PermissionType.READ`、`execution_mode=local`），回傳機器可讀的 role / scope / allowed / withheld / remediation，讓助手在被追問時能查證而非推測。
- 隱藏能力類別由 registry 全集與過濾後集合**推導**，不維護第二份硬編清單，避免新增工具後語意漂移。
- 非目標：不改動 executor 的權限強制檢查（`assistant-tool-execution` 既有必要防線）、不改角色→權限映射、不放寬 VIEWER 的實際能力、不改確認卡流程、不新增前端 UI（唯讀 badge 留待後續變更）。

## Capabilities

### New Capabilities

（無新 capability；行為歸屬既有的 assistant agent loop 與 tool execution 契約。）

### Modified Capabilities

- `assistant-agent-loop`: 新增 Requirement——回合工具目錄預過濾時 MUST 注入 capability context（scope / role / withheld 類別 / 原因 / 補救），並規範預過濾後的拒絕語意歸因；system prompt 的能力宣告需能與 capability context 並存。
- `assistant-tool-execution`: 工具矩陣新增 local read 工具 `describe_capabilities`，並明確其 team_check / permission / projection 契約。

## Impact

- `app/services/assistant/assistant_agent_service.py`：`_run_llm_loop` 組裝 per-turn capability context 並傳給 LLM。
- `app/services/assistant/content_store.py`：per-turn 內容必須在 `_cache_system` 之外組裝（快取污染風險點）。
- `prompts/assistant/system.md`：能力宣告與拒絕語意段落調整；DB 內既有 system prompt 不需 migration（capability context 以 append 方式注入，不依賴模板 token）。
- `app/services/assistant/tools_misc.py`、`tool_executor.py`：新增 `describe_capabilities` 宣告與 local handler；`_run_local_read_tool` 需取得 `role`／scope。
- Context budget：capability context 受 `assistant-context-budget` 約束，以類別摘要控制長度。
- 無 DB schema 變更、無 migration、無 API 破壞性變更；LLM 供應商設定與 credential 路徑不變。
