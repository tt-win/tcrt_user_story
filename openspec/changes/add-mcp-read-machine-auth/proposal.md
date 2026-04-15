## Purpose

建立 MCP 專用的機器對機器（M2M）唯讀授權能力，讓 MCP Server 可在無互動 UI 登入的情況下安全取得團隊、Test Case、Test Run 資訊。  
Introduce secure machine-to-machine read access for MCP endpoints without interactive user login.

## Why

目前 TCRT 主要依賴一般使用者 JWT 登入流程，不適合 MCP Server 的自動化長期執行場景。  
缺少 MCP 專用唯讀權限與機器憑證，會導致整合成本高、權限邊界不清晰，且不利於最小權限控管。

## What Changes

- 新增 `mcp_read` 權限語意，供 MCP 讀取端點授權使用。
- 新增機器憑證驗證流程（service account JWT / machine token）供非互動式登入。
- 新增 MCP 專用讀取端點群組（`/api/mcp/*`），僅回傳整合需要的唯讀資料。
- 建立 team scope 控制與審計紀錄，確保機器帳號只能讀取授權團隊。
- 對既有敏感欄位做輸出收斂（避免回傳 wiki token 等設定機密）。

## Requirements

- R1（M2M 認證）
  - **Given** MCP Server 持有有效機器憑證  
  - **When** 呼叫 MCP 讀取 API  
  - **Then** 系統 SHALL 驗證憑證並建立機器身分上下文

- R2（最小權限）
  - **Given** 機器身分未具備 `mcp_read` 或超出 team scope  
  - **When** 請求 MCP 讀取 API  
  - **Then** 系統 SHALL 回傳授權失敗且 SHALL NOT 洩漏目標資料

- R3（唯讀資料存取）
  - **Given** 機器身分具備 `mcp_read` 且 team scope 合法  
  - **When** 查詢團隊/Test Case/Test Run  
  - **Then** 系統 SHALL 回傳一致、可過濾的唯讀資料模型

## Non-Functional Requirements

- 安全性：短效 token、可撤銷、可輪替、完整 audit trail。
- 相容性：不破壞現有使用者 JWT 登入流程與既有 API 契約。
- 可維運性：以明確 schema 與集中驗證邏輯降低後續擴充成本。

## Capabilities

### New Capabilities

- `mcp-machine-auth`: MCP 專用機器身分驗證與 `mcp_read` 授權模型。
- `mcp-read-api`: MCP 專用唯讀 API（teams / test-cases / test-runs）與過濾能力。

### Modified Capabilities

- (none)

## Impact

- 影響模組：`app/auth/*`, `app/api/*`, `app/models/*`, `app/config.py`, `database_init.py`。
- 影響 API：新增 `/api/mcp/*`，既有 API 行為不變。
- 影響資料：新增機器憑證/權限相關資料結構與索引（需 migration/兼容初始化邏輯）。
