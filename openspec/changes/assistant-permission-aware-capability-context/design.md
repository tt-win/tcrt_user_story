## Context

助手回合開始時，工具目錄會依「對話 scope」與「使用者角色」預過濾（design D2，`assistant-tool-execution` 明訂此為引導性質的第一層，executor 檢查才是必要防線）：

- 全域（無 team）對話 → 只給 `risk_level=read` 且 `team_check=none` 的 discovery 工具
- team 對話 → 依角色映射的權限等級過濾（VIEWER→read；USER→read+write；ADMIN→read+write+admin）

但送給 LLM 的 system prompt 由全域 process cache 供應，內容完全與使用者無關：沒有角色、沒有 scope、沒有「你少拿到了什麼」。同時 factory prompt 明文宣告「工具目錄以外的操作一律視為不可能」。兩者相加使模型只能得出唯一結論——「這個功能不存在」。實際觀察到的失敗：VIEWER 要求建立 test case set 時，助手回答「我手上的工具清單中沒有建立 Test case set 的 API 工具」，追問時進一步否認與權限有關，並建議改用網頁介面（Viewer 在網頁上同樣無權建立）。

約束：

- system prompt 模板的 runtime 真相在 main DB，管理員可編輯（capability `assistant-prompt-skills-admin`），因此不能假設任何模板 token 存在。
- 既有 prompt 組裝有短期 process cache（跨使用者共用），任何 per-user 內容都不得進入該快取。
- 回合 context 受 `assistant-context-budget` 約束，不能為了完整性而列舉全部工具名。
- 無法對 LLM 實際輸出做確定性斷言，驗證對象必須是「送進 LLM 的 system prompt 內容」與「工具回傳的結構化事實」。

## Goals / Non-Goals

**Goals:**

- 助手在能力被預過濾時，MUST 能正確歸因為「角色權限不足」或「此對話為全域 scope」，並給出可行的補救路徑。
- 助手 MUST NOT 把被過濾的 TCRT 能力描述為「系統不存在此功能」，MUST NOT 把「改用網頁介面」當成權限不足的解法。
- 提供機器可讀的能力自述，讓「是不是我權限不夠？」這類追問能被工具查證而非模型推測。
- 隱藏能力的描述隨工具矩陣自動演進，不產生第二份需人工同步的清單。

**Non-Goals:**

- 不改動 executor 權限強制檢查、角色→權限映射，或 VIEWER 的實際能力邊界。
- 不放棄工具目錄預過濾（不改成「全給 LLM、由 executor 擋」）。
- 不改確認卡流程、不改離題拒絕規則。
- 不做前端唯讀提示（Viewer badge／輸入框提示）——留待後續變更，需先由 API 曝露 capability 資訊。
- 不查詢並揭露「可以找誰申請權限」的具體管理員名單。

## Decisions

### D1: capability context 以 per-turn suffix 注入，組裝於全域快取之外

回合開始先取得共用的 base system prompt（保留現行 DB 讀取＋process cache），再由 agent loop 依本回合的 `role` / `scope_type` / `team` / 過濾後工具集合組出 capability context，附加於 base 之後送給 LLM。

替代方案：把 role/scope 併入快取鍵——被否決。快取的是「DB 模板＋skill catalog」這個與使用者無關的成本較高的部分；把 per-user 維度塞進去會讓快取碎片化，且一旦鍵設計遺漏維度就變成跨使用者資訊外洩，風險與收益不成比例。

### D2: 以 append 注入，不使用模板 token

capability context 一律 append 在 base prompt 之後，並以「本回合權威事實」語氣開頭，明確宣告其優先於任何一般性能力描述。理由：管理員可任意編輯 DB 內的 system prompt，若改用 `{{CAPABILITY_CONTEXT}}` 這類 token，管理員刪掉 token 就會靜默失效——退回今天的錯誤歸因。以 append + 優先宣告可同時壓過既有自訂 prompt 裡殘留的絕對化措辭（與現行 `ensure_tool_routing_rules` 同一策略）。

### D3: 隱藏能力以「類別」表達，由 registry 推導

capability context 描述被隱藏的是哪些**類別**的能力（例如 test case 建立／修改／刪除、test run 與 run item 寫入、test case set/section 寫入、pins 寫入、批次寫入），而非列出數十個工具名。類別由「registry 全集」減去「本回合過濾後集合」推導；每個 write 工具都必須能映射到一個類別，未覆蓋者落入一個明確的 fallback 類別，並以測試確保映射完整，避免新增工具後語意漂移。理由：context budget，以及讓描述長度不隨工具數線性成長。

### D4: 保留預過濾，不改為「全給 LLM、executor 擋」

替代方案是把 write 工具照樣送進 LLM，讓 executor 在執行前拒絕。被否決：VIEWER 會先看到一張確認卡、按下後才失敗，UX 比現況更糟；同時浪費 token 與迭代預算；也與 `assistant-tool-execution`「預過濾為引導層」的既定設計相衝突。本變更要修的是「模型不知道自己被過濾」，不是過濾本身。

### D5: 同時提供 local read 工具 `describe_capabilities`

除 prompt 注入外，新增 `execution_mode=local`、`team_check=none`、`PermissionType.READ` 的工具，回傳結構化的 `scope` / `role` / `allowed_permissions` / `withheld_capabilities` / `reason` / `remediation`。理由：

- prompt 是單向陳述，模型在被質疑時傾向自我懷疑；有可查證的工具結果可讓它給出一致答案。
- local 工具不打 ASGI、無 team 綁定，全域對話同樣可用（與既有 `list_skills` 同一模式）。
- 提供可確定性斷言的測試面（工具輸出），補足「無法斷言 LLM 輸出」的缺口。

`_run_local_read_tool` 目前不接收 `role`／scope，需由呼叫端傳入；`role` 在該呼叫點的外層方法已具備（權限檢查使用），屬純參數傳遞。

### D6: 歸因分類與並存處理

- `global_scope`：對話未綁 team。**補救不是「切換到 team 對話」**——前端 `assistant-widget.js` 的 `createConversation` 固定送 `scope_type: 'global'`，沒有任何建立 team 對話的入口，所以那是死路（實測確認：切換工作區 team 後仍無法建立）。目前唯一可行路徑是在 TCRT 網頁介面完成該寫入；助手全域對話支援 team-scoped 寫入屬另一個變更（見 Open Questions）。
- `role_insufficient`：角色權限不足。補救＝向團隊管理員申請提升角色，MUST NOT 引導去網頁介面自行操作（同一限制在網頁介面同樣成立）。
- 兩者並存（全域對話且角色為 VIEWER）：MUST 說明兩個限制彼此獨立（該操作本身也需要 write 權限），且 MUST 套用 `role_insufficient` 的禁止項——不得建議改用網頁介面。

### D7: 語言與資料邊界

capability context 沿用 system prompt 的 zh-TW 敘述，欄位值使用英文識別碼（`viewer` / `team` / `global`）。內容僅含角色名、scope、team id/name 與能力類別；不含使用者 email、JWT、其他 team 的資料。capability context 位於 system message，不受工具回傳資料影響，維持既有防注入邊界。

## Risks / Trade-offs

- **[快取污染：per-user 內容誤入全域 prompt 快取，導致跨使用者資訊外洩或錯誤歸因]** → capability context 一律在快取邊界之外組裝；測試以「同一 process 內連續兩個不同角色的回合」斷言各自 prompt 正確且互不影響。
- **[context 成本增加，擠壓歷史預算]** → 以類別摘要取代工具列舉，並將區塊長度納入測試斷言上限；`assistant-context-budget` 的歷史裁切邏輯不變。
- **[模型仍可能忽略指示、繼續說「沒有這個工具」]** → 屬 LLM 行為不可保證項；以三層降低機率（system prompt 規則、per-turn 權威事實、可查證的 `describe_capabilities`）。測試斷言限於 prompt／工具輸出，不對模型輸出做確定性斷言。
- **[管理員自訂的 DB prompt 內含絕對化措辭，與 capability context 衝突]** → capability context 以「本回合權威事實、優先於一般性描述」開頭並置於最後；同時修正 factory prompt 措辭，新環境不再帶入衝突文字。既有 DB prompt 不做自動改寫（避免動使用者內容）。
- **[write 工具新增後未納入類別映射，摘要出現空泛描述]** → 映射完整性以 registry 層測試守門（每個 write 工具都必須落在某個類別），失敗即測試紅燈。
- **[揭露「存在但你看不到」的能力，等於暴露系統功能面]** → 只揭露能力**類別**與角色門檻，不揭露端點、參數或其他 team 的資料；此資訊等同產品文件層級，且權限模型本身對使用者可見（角色顯示於介面）。

## Migration Plan

無 DB schema 變更、無 migration、無 API 破壞性變更。部署後下一個回合即生效（prompt 於每回合組裝）。Rollback＝revert 程式碼：DB 內的 system prompt 與 skills 未被改寫，`describe_capabilities` 消失後既有對話歷史中的該工具結果只會成為普通歷史訊息，不影響後續回合（工具名不存在時 LLM 不會再呼叫，且歷史 tool result 不需重放）。

## Open Questions

- **全域對話無法執行任何寫入**（實作本變更時查證）：前端只建立 `scope_type='global'` 對話，`_run_llm_loop` 對全域對話只給 `discovery_only()` 的 10 個工具，confirm 端點對全域對話回 409 `SCOPE_INVALID`——因此 67/77 個工具對所有角色皆不可用。這是 `global-assistant-session` 未完成的缺口，屬另一個變更（方向已定：前端工作區 team 作 per-turn context team、`resolve` 類工具改為依反解出的 team 檢權、語意不明時反問）。本變更只負責讓助手誠實歸因，不修這個缺口。
- 是否要在助手面板為 VIEWER 顯示唯讀 badge／輸入框提示（需 conversation bootstrap 回應曝露 capability 資訊，三語系文案）。本變更不含，待確認優先度後另開變更。
- `describe_capabilities` 是否進一步回傳「可申請權限的團隊管理員」清單。需額外查詢與隱私評估，暫不納入。
