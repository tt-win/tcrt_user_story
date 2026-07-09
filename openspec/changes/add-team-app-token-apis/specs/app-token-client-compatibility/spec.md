# app-token-client-compatibility Specification

## ADDED Requirements

### Requirement: `/api/app/*` Becomes the Canonical External API Namespace
系統 SHALL 將 `/api/app/*` 定義為正式 app-token API namespace。`/api/mcp/*` SHALL 保留為 read-only compatibility namespace，直到明確移除計畫被建立並完成。

#### Scenario: app namespace 可讀取既有 MCP read 資料
- **WHEN** app token 呼叫 `/api/app/teams/{team_id}/test-cases`
- **THEN** response SHALL 提供與 `/api/mcp/teams/{team_id}/test-cases` 等價或向後相容的 read payload

#### Scenario: mutation 只存在於 app namespace
- **WHEN** client 對 `/api/mcp/*` 發送 POST / PUT / PATCH / DELETE mutation
- **THEN** 系統 SHALL 維持 read-only 拒絕
- **AND** mutation SHALL 只在 `/api/app/*` 提供

### Requirement: Legacy MCP Token Compatibility
既有 `mcp_read` machine token SHALL 在相容期內可繼續呼叫 `/api/mcp/*` read endpoints；新建 token SHALL 使用 app token terminology、scope model 與管理 UI。

#### Scenario: legacy token 仍可讀
- **WHEN** 既有 active `mcp_read` token 呼叫 `/api/mcp/teams`
- **THEN** 系統 SHALL 依既有 read-only scope rules 回應

#### Scenario: legacy token 不可寫
- **WHEN** legacy `mcp_read` token 呼叫 `/api/app/*` mutation endpoint
- **THEN** 系統 SHALL 回 403 scope denied

### Requirement: Stable Error Mapping
App-token API SHALL 使用穩定 machine-readable error code，讓 `tcrt_mcp` 與其他 client 可映射成 MCP ToolError 或 retry policy。`/api/app/*` 錯誤 SHALL 使用固定 HTTP status 與 `detail.code` 組合，完整清單為：

| HTTP | `detail.code` | 情境 |
| --- | --- | --- |
| 401 | `APP_TOKEN_REQUIRED` | request 未帶 bearer token |
| 401 | `APP_TOKEN_INVALID` | token 不存在、已撤銷或已過期（對外統一，不洩漏 token 狀態；deny audit 內細分原因） |
| 403 | `APP_TOKEN_TEAM_SCOPE_DENIED` | token 對目標 team 無授權 |
| 403 | `APP_TOKEN_SCOPE_DENIED` | token 缺少必要 operation scope |
| 400 | `APP_TOKEN_VALIDATION_ERROR` | payload 驗證失敗，含跨 team set/section/config/suite reference |
| 404 | `APP_TOKEN_RESOURCE_NOT_FOUND` | team 或 resource 不存在 |

FastAPI 既有的 422 request validation error SHALL 保持原生結構，client SHALL 視為等同 validation error 處理。

#### Scenario: scope denied error
- **WHEN** app token 缺少必要 operation scope
- **THEN** response SHALL 使用 `detail.code=APP_TOKEN_SCOPE_DENIED`

#### Scenario: team denied error
- **WHEN** app token 存取未授權 team
- **THEN** response SHALL 使用 `detail.code=APP_TOKEN_TEAM_SCOPE_DENIED`

#### Scenario: 無效 token 不洩漏狀態
- **WHEN** client 以已撤銷 token 與已過期 token 分別呼叫 `/api/app/*`
- **THEN** 兩者 response SHALL 相同：401 `APP_TOKEN_INVALID`
- **AND** deny audit SHALL 分別記錄 revoked 與 expired 原因

### Requirement: tcrt_mcp Server Migration
`tcrt_mcp` SHALL 從 `/api/mcp/*` read-only client 遷移為 `/api/app/*` app-token client，並保留設定相容層。新的 write-capable tools SHALL 以清楚名稱暴露，且每個 mutation tool SHALL 先做 client-side validation 再呼叫 TCRT。

#### Scenario: 設定相容
- **WHEN** `tcrt_mcp` config 仍使用 `machine_token`
- **THEN** server SHALL 可讀取該值作為 app token 的相容別名
- **AND** docs SHALL 建議新設定名改為 `app_token`

#### Scenario: write tools 命名清楚
- **WHEN** `tcrt_mcp` 新增建立或更新 test case 的 tool
- **THEN** tool name SHALL 包含動詞，例如 `create_test_case` 或 `update_test_case`
- **AND** description SHALL 明確標示會修改 TCRT 資料

#### Scenario: 破壞性 tool 需要明確 confirm
- **WHEN** `tcrt_mcp` 的 delete 或批次破壞性 tool 被呼叫且未帶 `confirm=true`
- **THEN** tool SHALL 不執行 mutation
- **AND** 在 TCRT impact preview endpoint 可用時，tool SHALL 回傳影響摘要供 caller 確認後重試

#### Scenario: audit redaction 延續
- **WHEN** write-capable MCP tool 的 request 或 response 含 credential 類 test data
- **THEN** `tcrt_mcp` local audit jsonl SHALL redacted 該 value
