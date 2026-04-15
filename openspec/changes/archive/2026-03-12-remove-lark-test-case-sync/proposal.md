## Why

TCRT 最初的設計依賴從 Lark (飛書) Bitable 同步測試案例 (Test Case Sync)。隨著系統演進，TCRT 已經具備了完整的本地 Test Case 編輯、管理與儲存能力 (Test Case Repository)，不再需要依賴外部 Lark 表格作為唯一的資料來源。
保留 Lark 同步功能不僅增加了系統的複雜度（例如處理網路延遲、資料衝突、欄位對應與解析等問題），也違背了將 TCRT 打造為獨立 Test Case Management (TCM) 系統的產品方向。為了簡化架構並降低維護成本，我們決定將與 Lark Table 雙向/單向同步 Test Case 的功能從專案中完全移除。

## What Changes

- **BREAKING**: 完全移除 `TestCaseSyncService` 以及所有負責從 Lark 抓取、解析、更新 Test Case 的邏輯。
- 移除背景排程的同步任務（如 `database_sync_backup.py` 中的同步邏輯，若有）。
- 移除與 Lark 測試案例同步相關的 API 端點（如手動觸發同步的 API）。
- 移除 UI 介面中關於「從 Lark 同步」的按鈕、設定與狀態顯示。
- 保留本地的 `TestCase` Model 與 Repository，但移除其中為 Lark 對應而設的過度特定邏輯 (若有)。

## Capabilities

### Modified Capabilities
- `test-case-management`: 測試案例的管理行為將純粹基於 TCRT 內部系統，不再包含來自 Lark 的資料同步或更新操作。

### REMOVED Capabilities
- `test-case-lark-sync`: 移除系統從 Lark Bitable 同步測試案例資料的能力。

## Impact

- `app/services/test_case_sync_service.py` (將被刪除)
- 呼叫同步邏輯的 API endpoints 與 Router
- 背景或定時執行的同步腳本 (如 `scripts/sync_tcrt_to_lark.py` 或類似腳本)
- 前端 UI 中觸發同步的按鈕與其對應的 JavaScript (`static/js/` 內的相關邏輯)
- `app/models/database_models.py` 中可能僅為同步而存在的暫存欄位（需視情況清理）
- 不影響已匯入本地的測試案例資料，僅移除未來的同步機制。
