## ADDED Requirements

### Requirement: 全域回合依 context team 提供工具目錄

全域對話的回合 MUST 依該 turn 的 context team 決定工具目錄：具 context team 時 MUST 提供該 team 的 team-scoped 工具（依角色權限過濾，與 team-bound 對話同一規則）；無 context team 時 MUST 僅提供 discovery 類工具。

capability context MUST 標明本回合的 context team（名稱與 id）。無 context team 時，被隱藏能力的原因 MUST 為 `no_team_context`、補救 MUST 為「在介面選定目標 team 的工作區後重試」；MUST NOT 再以 `global_scope` 作為原因，MUST NOT 建議「切換到某個 team 的對話」。

#### Scenario: 具 context team 的全域回合可看到寫入工具

- **WHEN** USER 角色使用者在工作區 team `ART` 向全域對話送出訊息
- **THEN** 該回合送往 LLM 的目錄包含 ART 的 team-scoped 讀寫工具，capability context 標明 context team 為 ART 且無受限敘述

#### Scenario: 無 context team 的全域回合仍為唯讀

- **WHEN** 使用者未選定工作區 team（turn 無 context team）
- **THEN** 目錄僅含 discovery 類工具，capability context 原因為 `no_team_context` 並指向「選定工作區 team 後重試」

#### Scenario: VIEWER 在具 context team 的回合仍被角色限制

- **WHEN** VIEWER 角色使用者在工作區 team `ART` 要求寫入
- **THEN** 目錄仍不含寫入工具，capability context 原因為 `role_insufficient`（非 `no_team_context`），補救為向團隊管理員申請權限

### Requirement: 指名 team 與 context team 衝突時必須消歧

使用者訊息指名的 team 與本回合 context team 不一致時，助手 MUST 反問確認或請使用者切換工作區後重試，MUST NOT 自行選定其中一個 team 執行寫入。system prompt MUST 明載此規則，capability context MUST 提供 context team 名稱供比對。

#### Scenario: 指名其他 team 的寫入請求先消歧

- **WHEN** context team 為 `ART`，使用者說「在 CID 建立一個 test case set」
- **THEN** 助手 MUST 先說明目前工作區為 ART 並請使用者切換到 CID（或明確確認要在 ART 建立），MUST NOT 直接在任一 team 建立

#### Scenario: 指名與 context team 相同時直接執行

- **WHEN** context team 為 `ART`，使用者說「在 ART 建立一個 test case set」
- **THEN** 助手直接提出該 write 工具呼叫並進入確認流程，不需額外反問
