## MODIFIED Requirements

### Requirement: Stable Error Mapping

App-token API SHALL 使用穩定 machine-readable error code，讓 client 可區分不可重試的 validation error 與必須重做 read/preview 的 optimistic-concurrency conflict。既有 400/401/403/404 與原生 422 mapping SHALL 保持不變，並新增：

| HTTP | `detail.code` | 情境 |
| --- | --- | --- |
| 409 | `APP_TOKEN_IMPACT_CHANGED` | Test Case move 的 impact fingerprint 與 transaction 內現況不符；client 必須重做 preview/確認 |
| 409 | `APP_TOKEN_STATE_CHANGED` | Test Run membership 與 expected source 不符；client 必須重做 read-back |
| 409 | `APP_TOKEN_INTEGRITY_CONFLICT` | legacy data 破壞單一 canonical target 假設（例如多個 root Unassigned）；server 不擅自修復 |

Generic endpoint 誤用（例如以 generic Test Case update 取代 guarded move，或以 attach-only route 搬移已歸組 config）SHALL 使用既有 400 `APP_TOKEN_VALIDATION_ERROR`，不得發明未列入契約的 409 code。

#### Scenario: Case impact precondition changed
- **WHEN** guarded Test Case move 的 fingerprint 已過時
- **THEN** response SHALL 使用 409 `APP_TOKEN_IMPACT_CHANGED`
- **AND** client SHALL NOT 原樣盲目重試

#### Scenario: Membership precondition changed
- **WHEN** Test Run membership 與 request 中的 expected source 不符
- **THEN** response SHALL 使用 409 `APP_TOKEN_STATE_CHANGED`
- **AND** client SHALL 重新讀取 membership 後再決定是否重送

#### Scenario: Legacy integrity conflict blocks mutation
- **WHEN** guarded operation 發現多個 canonical root Unassigned 等無法唯一解析的 legacy state
- **THEN** response SHALL 使用 409 `APP_TOKEN_INTEGRITY_CONFLICT`
- **AND** SHALL NOT 擅自選擇或修改任一筆
