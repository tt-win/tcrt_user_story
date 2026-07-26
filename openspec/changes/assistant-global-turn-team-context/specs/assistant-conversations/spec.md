## ADDED Requirements

### Requirement: turn 的 context team 快照

送出訊息時，前端 MAY 附帶目前工作區 team 作為 `context_team_id`。伺服器 MUST 於建立 turn 的同一交易將其**快照**在 `assistant_turns.context_team_id`（nullable）；該快照於 turn 存續期間 MUST NOT 可變更，且 MUST 為該 turn 及其 confirm continuation 唯一的 context team 來源。

`context_team_id` 非空時，伺服器 MUST 以使用者可存取 team 清單驗證；不在清單內 MUST 以 422 拒絕建立 turn（MUST NOT 忽略該值、MUST NOT 降級為無 context team）。缺值 MUST 視為「無 context team」，屬正常的 fail-closed 路徑。

`context_team_id` MUST NOT 出現在任何 LLM 可控的參數 schema 中；LLM MUST NOT 能變更本回合的 context team。

#### Scenario: 訊息帶入工作區 team

- **WHEN** 使用者在工作區 team `ART`（id=1）的頁面向全域對話送出訊息
- **THEN** 該 turn 的 `context_team_id` 快照為 1，該回合的 team-scoped 工具以此 team 執行

#### Scenario: 不可存取的 team 被拒

- **WHEN** 送出訊息時帶入使用者無權存取的 `context_team_id`
- **THEN** 伺服器回 422 且不建立 turn

#### Scenario: 未帶 context team 時維持唯讀

- **WHEN** 前端未附帶 `context_team_id`（舊版前端或未選定工作區）
- **THEN** 該 turn 視為無 context team，只提供 discovery 類工具，MUST NOT 以任何預設 team 執行寫入

#### Scenario: 快照不受後續工作區切換影響

- **WHEN** 使用者在 turn 進行中或確認卡出現後切換工作區 team
- **THEN** 該 turn 與其 confirm continuation 仍使用建立時的 `context_team_id` 快照

## MODIFIED Requirements

### Requirement: 對話綁定單一團隊

每個對話 SHALL 於建立時設定不可變 `scope_type`（`global` 或 `team`）並綁定至多一個 team_id；`scope_type=team` 時建立當下 team_id MUST 非空，且存不可變 `source_team_id` 供刪除後辨識。mutation 類工具的 team_id MUST 由 executor 注入，來源為**有效 team**：`scope_type=team` 的對話取對話綁定 team；`scope_type=global` 的對話取該 turn 的 context team 快照（見「turn 的 context team 快照」）。`scope_type=global` 且該 turn 無 context team 時，SHALL 僅提供 discovery 類工具，MUST NOT 提供任何 mutation。scope/team 綁定於對話存續期間 MUST NOT 可變更。已知限制（明文接受）：現行 `check_team_permission` 由全域角色決定、team_id 僅為快取鍵；本綁定縮小預設操作面，不構成 team 粒度授權。

#### Scenario: 全域對話具 context team 時可執行 mutation

- **WHEN** 使用者在工作區 team `ART` 向全域對話要求建立 test case set
- **THEN** 助手可提出該 write 工具呼叫，executor 以 turn 的 context team（ART）檢權並注入 team_id

#### Scenario: 全域對話無 context team 時無 mutation 工具

- **WHEN** 使用者在無 context team 的全域對話中要求建立 test case
- **THEN** 目錄中沒有 mutation 工具可用，助手說明需先在介面選定目標 team 的工作區

#### Scenario: 團隊被刪除後對話轉唯讀

- **WHEN** 對話綁定的 team 被刪除（team_id 轉為 NULL）
- **THEN** 該對話因 `scope_type=team AND team_id IS NULL` 自動視為唯讀歷史，不得建立新 turn、呼叫 discovery 或 mutation；它不會被誤認為 `scope_type=global`，歷史仍可依 source_team_id 顯示原 scope

#### Scenario: 團隊刪除使既有 pending 失效

- **WHEN** 對話已有 pending action，而其有效 team 在 confirm 前被刪除
- **THEN** confirm 的 Tx A 前 scope 驗證將 action 原子標記 expired、清除 payload 並寫 synthetic tool result，不發出 loopback
