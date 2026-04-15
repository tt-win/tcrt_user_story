# database-async Specification

## Purpose
定義 TCRT 在 web runtime 中全面採用 async DB access 的要求，並補上受管 session / boundary 的實際行為。

## Requirements
### Requirement: Web runtime 全面使用非同步 DB 存取
系統在 API handlers、背景任務與其他 web runtime 流程中 SHALL 使用受管的 async session 存取主庫、audit 與 USM。

#### Scenario: API 使用受管非同步 session
- **WHEN** API handler 存取資料庫
- **THEN** 使用受管 async session

#### Scenario: 背景任務使用受管非同步 session
- **WHEN** runtime 背景任務需要讀寫資料
- **THEN** 也使用受管 async session

### Requirement: 同步 DB 存取需隔離於離線工具或 threadpool
同步 DB 存取 SHALL 被限制在離線工具、初始化 / migration 腳本，或明確的 sync fallback 隔離邊界。

#### Scenario: Web runtime 不使用同步 session
- **WHEN** 服務在 web runtime 執行
- **THEN** 不直接用同步 session 進行 DB 存取

#### Scenario: 受管 boundary 需要 sync fallback
- **WHEN** 某些必要流程只能使用 sync fallback
- **THEN** 該 fallback 被侷限在受管 boundary 或 threadpool，而非任意散落於 runtime

### Requirement: 功能行為維持一致
async 化 SHALL 不改變既有 API 結果、資料副作用與功能流程。

#### Scenario: 既有流程回歸
- **WHEN** 使用者執行既有流程
- **THEN** 回應與資料行為對齊改寫前預期
