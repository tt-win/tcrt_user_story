## ADDED Requirements

### Requirement: confirm 的有效 team 取自 turn 快照

confirm 端點 MUST 由 pending action 所屬 turn 取得有效 team（`scope_type=team` 取對話綁定 team；`scope_type=global` 取該 turn 的 `context_team_id` 快照），並以該 team 重新執行權限驗證與 team_id 注入。confirm request MUST NOT 接受任何 team 參數，MUST NOT 採用「confirm 當下前端工作區」作為 team 來源——否則使用者在確認卡出現後切換工作區，動作會落到非預期 team。

`scope_type=global` 的對話 MUST NOT 僅因 scope 為 global 而被拒絕 confirm；只有在有效 team 為空、team 已被刪除或該 team 上權限已失效時，才 MUST 原子 expire action、清 payload 並寫 synthetic tool result。

確認卡的 canonical summary MUST 含目標 team 名稱（伺服器 lookup、經 projection/redaction），且 MUST 納入 `confirmation_fingerprint` 的計算輸入；LLM 文字 MUST NOT 作為 team 標示來源。

#### Scenario: 全域對話的 confirm 可成功執行

- **WHEN** 全域對話的 turn 具 context team `ART`，使用者確認該 turn 建立的 write pending
- **THEN** confirm 以 ART 檢權並注入 team_id 後執行，不再因 scope 為 global 而回 409

#### Scenario: 確認前切換工作區不改變目標 team

- **WHEN** 使用者在確認卡出現後把工作區切到另一個 team，然後按下確認
- **THEN** 執行仍以 pending 所屬 turn 的 context team 快照為目標 team

#### Scenario: 確認卡標示目標 team

- **WHEN** 任一 write 的確認卡產生
- **THEN** 卡片 MUST 顯示該動作將作用的 team 名稱，且該值來自伺服器 lookup 並計入 fingerprint

#### Scenario: 有效 team 為空時 expire

- **WHEN** pending 所屬 turn 無 context team（或其 team 已被刪除）而使用者按下確認
- **THEN** 系統原子將 action 標記 expired、清除 payload、寫入 synthetic tool result，不發出 loopback

#### Scenario: 目標 team 權限失效時 expire

- **WHEN** pending 建立後，使用者在該 team 的權限被降級為唯讀，之後才按下確認
- **THEN** confirm 的認領前驗證失敗，action 原子 expire，不執行工具
