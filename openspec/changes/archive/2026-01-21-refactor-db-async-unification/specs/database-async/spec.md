## ADDED Requirements

### Requirement: Web runtime 全面使用非同步 DB 存取
系統在 Web runtime（API handler、背景任務）中 SHALL 以 AsyncSession 存取主 DB / audit DB / USM DB。

#### Scenario: API 使用非同步 session
- **WHEN** 任一 API handler 需要存取資料庫
- **THEN** 該存取 SHALL 使用 AsyncSession

### Requirement: 同步 DB 存取需隔離於離線工具或 threadpool
系統 SHALL 將同步 DB 存取限制於離線工具（例如初始化或批次腳本）或明確的 threadpool 隔離，不得直接用於 Web runtime。

#### Scenario: Web runtime 不使用同步 session
- **WHEN** 服務以 Web runtime 模式執行
- **THEN** 不得直接使用同步 session 進行 DB 存取

### Requirement: 功能行為維持一致
本次改寫 SHALL 保持既有 API 回應、資料副作用與流程行為一致，不得造成可觀察的功能破壞。

#### Scenario: 既有流程回歸
- **WHEN** 使用者執行既有 API 與流程
- **THEN** 回應結果與資料變更應與改寫前一致
