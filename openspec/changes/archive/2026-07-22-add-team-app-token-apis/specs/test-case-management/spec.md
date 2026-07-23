# test-case-management Specification

## MODIFIED Requirements

### Requirement: 測試案例的本地化管理
系統 SHALL 將測試案例的所有建立、編輯、刪除操作保留在本地系統內，不再嘗試從外部資料源（如 Lark）同步或覆寫本地資料。此規則 SHALL 同時適用於人類 JWT API 與 app-token API；app-token 寫入 SHALL 沿用相同本地資料語意、team boundary、default set/section 驗證與 audit 要求。

#### Scenario: 編輯測試案例
- **WHEN** 使用者在 TCRT 系統中編輯一個現有的測試案例
- **THEN** 變更會直接儲存至本地資料庫，並且不會觸發任何外部的同步 API，也不會被外部資料覆寫。

#### Scenario: 建立測試案例
- **WHEN** 使用者透過 UI 手動建立新的測試案例
- **THEN** 測試案例成為本地管理的唯一資源，不再需要包含任何 Lark record_id 才能運作。

#### Scenario: App token 建立測試案例
- **WHEN** app token 具備 `test_case:write` 並透過 `/api/app/*` 建立測試案例
- **THEN** 測試案例 SHALL 成為本地管理資源
- **AND** 系統 SHALL NOT 呼叫 Lark 或其他外部同步 API

#### Scenario: App token 更新測試案例
- **WHEN** app token 具備 `test_case:write` 並更新同 team 測試案例
- **THEN** 變更 SHALL 儲存至本地資料庫
- **AND** audit SHALL 記錄 app-token principal，而不是人類 user
