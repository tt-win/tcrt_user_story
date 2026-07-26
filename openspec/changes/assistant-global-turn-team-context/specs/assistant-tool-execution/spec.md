## MODIFIED Requirements

### Requirement: in-process loopback 執行與 team_id 注入

工具執行 SHALL 透過 in-process ASGI loopback 呼叫既有 web JWT router，轉發啟動該 turn／confirm 請求的 Bearer JWT；`team_id` MUST 由 executor 注入 path template，MUST NOT 出現在 LLM 可控的參數 schema 中。注入值 MUST 取自**有效 team**的單一解析點：`scope_type=team` 的對話取對話綁定 team；`scope_type=global` 的對話取該 turn 的 context team 快照。有效 team 為空時，MUST NOT 執行任何需要 team 的工具。為支援 subscriber 斷線後 detached runner 繼續，JWT MAY 僅以 ephemeral in-memory runner context 保留至 turn 終態；MUST NOT 寫入 DB、queue payload、event、log、exception 或任何可重播資料，runner 終態／失敗時 MUST 立即釋放引用。loopback 請求 MUST 附 `X-TCRT-Assistant: 1` 與含 conversation key 的 User-Agent。

#### Scenario: LLM 無法指定其他 team

- **WHEN** LLM 產生的工具參數夾帶 team_id 欄位
- **THEN** 參數驗證拒絕未知欄位；實際 team_id 一律取自有效 team 解析點（對話綁定或 turn context team 快照）

#### Scenario: 全域對話以 context team 注入

- **WHEN** 全域對話的 turn 具 context team `ART`(id=1)，LLM 呼叫 `create_test_case_set`
- **THEN** executor 對 team 1 檢權後將 team_id=1 注入 path，LLM 未提供也無法提供該值

#### Scenario: 無有效 team 時拒絕執行

- **WHEN** 全域對話的 turn 無 context team，而 LLM 仍產生需要 team 的工具呼叫
- **THEN** executor 拒絕執行且不發出 loopback

### Requirement: sub-resource team 歸屬驗證

對 path template 不含 `{team_id}` 或操作可能跨 team 之 sub-resource（set_id/config_id/run_id/section_id/pin entity_id 等）的工具，registry MUST 宣告 `resource_team_check`（由參數解析目標資源實際所屬 team 的 resolver）；executor MUST 於 loopback 之前驗證解析出的 team：`scope_type=team` 的對話 MUST 等於對話綁定 team；`scope_type=global` 的對話 MUST 屬於使用者可存取 team 清單，且該 team 上的權限 MUST 涵蓋該工具宣告的 `PermissionType`。不符即拒絕（不發出請求）。此為結構性保證，MUST NOT 假設被呼叫端點會驗證 team 歸屬。

全域對話允許目標 team 不等於 context team（例如以全域搜尋找到其他 team 的資源後要求更新），因此該工具的確認卡與工具結果 MUST 顯示目標 team 名稱，使用者才能在確認前辨識受影響的 team。

#### Scenario: 跨 team 的 set_id 在 team 對話被拒

- **WHEN** 對話綁定 team 3，LLM 對 create_test_case_section 傳入屬於 team 5 的 set_id
- **THEN** executor 的 resource_team_check 解析出 team 5 ≠ 3，拒絕執行且不發出 loopback

#### Scenario: 全域對話對可存取的其他 team 資源放行並標示 team

- **WHEN** 全域對話 context team 為 team 1，LLM 對屬於 team 5 的 set_id 發動更新，且使用者在 team 5 具 write 權限
- **THEN** executor 以 team 5 檢權後放行，確認卡顯示目標 team 為 team 5 的名稱

#### Scenario: 全域對話對不可存取的 team 資源被拒

- **WHEN** 全域對話中 LLM 對使用者無權存取之 team 的資源發動操作
- **THEN** executor 拒絕執行且不發出 loopback
