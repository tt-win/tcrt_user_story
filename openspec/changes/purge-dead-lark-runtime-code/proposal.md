## Why

`remove-team-lark-repo-settings` 移除了 team settings 的 Lark 欄位，但刻意把「本次變更之前就已經無法運作或無人呼叫」的 Lark 後端程式碼留給後續 change（見該 change 的 design D4）。這批殘骸目前仍掛在 API surface 上：

- `app/api/test_runs.py` 的 8 支 Lark record CRUD 路由讀取 `config.table_id`，但 `TestRunConfig` model **沒有這個欄位**——任何呼叫都必定 `AttributeError` → 500。它們是壞掉的端點，不是可用功能。
- `app/api/attachments.py` 的 6 支 Lark 上傳／附加／刪除路由沒有任何前端或測試呼叫者；測試案例附件早已改走 `app/api/test_cases.py` 的本機 `attachments/test-cases/...`。
- `app/api/test_run_items.py:486` 的 `_get_lark_client_for_team` 定義後從未被呼叫。
- `app/services/test_result_file_service.py`（406 行）全 repo 零 importer。
- `app/models/test_run.py`（436 行，含 `from_lark_record` / `to_lark_fields` 的 Lark 欄位映射）唯一的 importer 就是上述要移除的 8 支路由。

留著它們的成本不只是死程式碼：這些路由對外看起來像可用 API，其中 6 支還會真的對 Lark 發出網路請求（對仍保有歷史 token 的舊 team）。

## What Changes

- **移除 `app/api/test_runs.py` 的所有 Lark record 端點**：`GET/POST/PUT/DELETE .../records*`、`.../records/count`、`.../statistics`、`.../batch-update-results`，連同 `get_lark_client_for_test_run()`、`filter_test_runs()`、`sort_test_runs()`、`log_test_run_action()` 與 Lark 相關 import。**保留** `POST .../generate-html` 與 `GET .../report`（前端 `test-run-execution/reports.js` 實際使用，且本來就不碰 Lark）。
- **移除 `app/api/attachments.py` 的 6 支 Lark 寫入路由**：testcase upload、test-run record upload、upload-screenshot、upload-file-token、attach-token、remove attachment。**保留** `GET .../attachments/download` 下載代理（見下方「不在範圍」）。
- **刪除 `app/models/test_run.py`**（隨最後一個 importer 一起消失）與 **`app/services/test_result_file_service.py`**（零 importer）。
- **移除 `app/api/test_run_items.py` 的死 helper** `_get_lark_client_for_team` 與其 `LarkClient` import。
- **新增 capability `lark-runtime-boundary`**：把「test run 資料只以本地 DB 為真實來源、系統不提供任何 Lark record 讀寫端點」「Lark 附件寫入路徑已移除、僅保留唯讀下載代理」寫成正式契約，避免日後有人把這類端點加回來。

## Capabilities

### Added Capabilities
- `lark-runtime-boundary`: 定義系統剩餘的 Lark 出站邊界——哪些路徑已永久移除、哪些為了既有資料相容而保留。

## Impact

- **API surface**：移除 14 支端點（test_runs 8 + attachments 6）。其中 test_runs 的 8 支對所有 team 本來就是 500，attachments 的 6 支無任何呼叫者，因此**沒有任何可用功能被移除**。
- **後端檔案**：`app/api/test_runs.py`（1000+ 行 → 只剩報告端點）、`app/api/attachments.py`、`app/api/test_run_items.py`；刪除 `app/models/test_run.py`、`app/services/test_result_file_service.py`。
- **資料庫**：無 schema 變更、無 migration、無資料異動。
- **前端**：無變更（唯一使用中的 `generate-html` 保留）。
- **i18n**：無變更。
- **測試**：`app/testsuite/test_attachment_proxy_contract.py` 必須繼續通過（它鎖的是保留下來的下載代理）。

## 明確不在本次範圍

以下兩條路徑**仍會對 Lark 發出請求**，但它們服務的是既有資料、且有現行契約保護，關閉它們需要先確認生產資料，不在本次「清死碼」的範圍：

1. **`GET /api/attachments/teams/{team_id}/attachments/download` 的 Lark 回退（優先級 4）**：`openspec/specs/async-runtime-performance/spec.md` 明文規定其上游狀態碼映射（401→401、404→404、其他→502、逾時→504），且有 `test_attachment_proxy_contract.py` 鎖定。舊 team 的 token 仍在 DB，這是它們唯一還能取回 legacy Lark 附件的路徑。
2. **`TestResultCleanupService._remove_files_from_test_case_sync()`**：刪除 test run item 時對 legacy 資料（`result_files_uploaded==1` 且 `upload_history_json` 帶 `file_token`）解除 Lark 附件關聯。

關閉這兩條的前置條件是掃描生產 DB 確認不存在帶 Lark `file_token` 的 `execution_results_json` / `upload_history_json`。屆時 `async-runtime-performance` 的相關 requirement 也需要一併改寫。
