## MODIFIED Requirements

### Requirement: Web runtime 全面使用非同步 DB 存取
系統在 Web runtime（API handler、背景任務）中 SHALL 以 AsyncSession 存取主 DB / audit DB / USM DB；這些 AsyncSession 必須由受管的 access boundary/provider 提供與持有。 Runtime caller MUST NOT 在 handler、service 或 task 本體內直接建立 session 或直接操作 query/transaction 細節。

#### Scenario: API 使用受管非同步 session
- **WHEN** 任一 API handler 需要存取資料庫
- **THEN** 該存取透過受管 access boundary 使用 AsyncSession，而不是在 handler 內直接建立 session 或呼叫 ORM query

#### Scenario: 背景任務使用受管非同步 session
- **WHEN** 背景任務需要存取 `main`、`audit` 或 `usm`
- **THEN** 任務透過受管 boundary/provider 取得 AsyncSession，且 session lifecycle 不由任務本體自行管理

### Requirement: 同步 DB 存取需隔離於離線工具或 threadpool
系統 SHALL 將同步 DB 存取限制於離線工具（例如初始化、migration、批次腳本）或明確的 threadpool 隔離，且該隔離必須由受管 boundary/infra 層持有，不得直接暴露到 Web runtime caller。 The web runtime MUST NOT directly open or manage synchronous sessions.

#### Scenario: Web runtime 不使用同步 session
- **WHEN** 服務以 Web runtime 模式執行
- **THEN** handler、service 與 background task 不得直接使用同步 session 進行 DB 存取

#### Scenario: 受管 boundary 需要 sync fallback
- **WHEN** 某個受管 boundary 必須呼叫同步資料庫邏輯
- **THEN** 該呼叫透過明確的 threadpool / bridge helper 執行，且 caller 不直接持有同步 session

### Requirement: 功能行為維持一致
本次改寫 SHALL 保持既有 API 回應、資料副作用與流程行為一致，不得因 session lifecycle 重整、boundary 抽離或跨資料庫協調重構造成可觀察的功能破壞。

#### Scenario: 既有流程回歸
- **WHEN** 使用者執行既有 API、背景任務與工具鏈流程
- **THEN** 回應結果、資料變更與外部可觀察行為應與改寫前一致
