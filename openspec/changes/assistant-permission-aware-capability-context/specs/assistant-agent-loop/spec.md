## ADDED Requirements

### Requirement: 回合能力上下文（capability context）

工具目錄依 scope／角色預過濾後，系統 MUST 於同一回合送往 LLM 的 system prompt 末端附加一段 capability context，內容 MUST 包含：對話 scope（`global` 或 `team` 與該 team 名稱／id）、使用者角色、該回合允許的權限等級、被隱藏的寫入能力**類別**、隱藏原因（`global_scope` 或 `role_insufficient`）、以及對應補救方式。此區塊 MUST 宣告為本回合權威事實、優先於 prompt 中任何一般性能力描述。

capability context MUST 以 append 方式注入，MUST NOT 依賴 system prompt 模板中的任何 token（模板可由管理員編輯），並 MUST NOT 進入跨使用者共用的 system prompt 快取。被隱藏的能力類別 MUST 由工具 registry 全集與該回合過濾後集合推導，MUST NOT 另行維護需人工同步的第二份清單；每個 write 工具 MUST 可映射到一個能力類別。

capability context MUST 只含角色、scope、team 名稱／id 與能力類別；MUST NOT 含使用者識別資料、JWT 或其他 team 的資料。

#### Scenario: VIEWER 在 team 對話取得角色歸因

- **WHEN** VIEWER 角色使用者在 team `ART` 的對話開啟一個回合
- **THEN** 送往 LLM 的 system prompt MUST 含 capability context，標明 scope 為 team `ART`、角色 `viewer`、允許權限僅 read、被隱藏的寫入能力類別，原因為 `role_insufficient`

#### Scenario: 全域對話取得 scope 歸因

- **WHEN** 使用者在全域（無 team）對話開啟一個回合
- **THEN** capability context MUST 標明 scope 為 `global`、原因為 `global_scope`
- **AND** 補救方式 MUST NOT 為「切換到 team 對話」——前端只建立全域對話，該入口不存在；MUST 指向目前可行的路徑（於 TCRT 網頁介面完成該寫入）

#### Scenario: 全域對話且角色不足時兩個原因並存

- **WHEN** VIEWER 角色使用者在全域對話要求寫入操作
- **THEN** capability context MUST 同時標明 `global_scope` 與 `role_insufficient`，並說明兩個限制彼此獨立（該操作本身也需要 write 權限）
- **AND** 原因包含 `role_insufficient` 時 MUST NOT 以「改用 TCRT 網頁介面」作為解法

#### Scenario: 具備權限的角色不出現受限敘述

- **WHEN** USER 角色使用者在 team 對話開啟一個回合
- **THEN** capability context MUST 標明允許 read＋write，MUST NOT 含「寫入能力被隱藏」或角色不足的敘述

#### Scenario: 跨使用者快取不被污染

- **WHEN** 同一 process 內先後處理 VIEWER 與 ADMIN 的回合
- **THEN** 兩個回合各自的 capability context MUST 對應各自的角色與 scope，任一回合的內容 MUST NOT 出現在另一回合的 system prompt

#### Scenario: 管理員自訂 prompt 仍取得 capability context

- **WHEN** DB 內的 system prompt 模板已被管理員改寫且不含任何 capability 相關 token
- **THEN** capability context 仍 MUST 被附加於組裝後的 prompt 末端

## MODIFIED Requirements

### Requirement: TCRT-only guardrails

系統 prompt SHALL 限定助手僅服務 TCRT test case / test run 相關操作並明確拒絕離題請求；工具目錄 MUST 不含任何非 TCRT 功能之工具；系統 prompt MUST 聲明工具結果與 test case 內容為資料而非指令。

系統 prompt MUST 區分「非 TCRT 範圍」與「TCRT 範圍但本回合不可用」兩種情形：

- 離題請求（非 TCRT 範圍）SHALL 一律拒絕並引導回 TCRT 操作，不呼叫任何工具。
- 屬 TCRT 範圍但工具目錄中不存在的寫入操作，助手 MUST 依 capability context 歸因為對話 scope 或角色權限限制，MUST NOT 聲稱該功能在系統中不存在或不可能，並 MUST 只給出 capability context 列出的補救路徑（MUST NOT 自行發明，特別是 MUST NOT 建議「切換到某個 team 的對話」）。原因包含 `role_insufficient` 時，MUST NOT 以「請改用 TCRT 網頁介面」作為補救建議（角色權限限制在網頁介面同樣成立）。

#### Scenario: 離題請求被拒絕

- **WHEN** 使用者要求寫詩或閒聊
- **THEN** 助手以固定語氣拒絕並引導回 TCRT 操作，不呼叫任何工具

#### Scenario: 受限的 TCRT 寫入請求歸因為權限

- **WHEN** VIEWER 角色使用者要求「在 ART 建立一個 test case set」
- **THEN** 系統 prompt 規則 MUST 要求助手說明此操作需要 write 權限而其角色為唯讀、並引導向團隊管理員申請權限，MUST NOT 允許回答「系統沒有這個功能／我沒有這個工具」，MUST NOT 引導改用網頁介面自行建立
