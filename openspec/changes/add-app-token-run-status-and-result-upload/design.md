# Design

## 1. Test Run Config 狀態轉換

### 狀態機（與 JWT 一致）

| 由 \ 到 | draft | active | completed | archived |
| --- | --- | --- | --- | --- |
| draft | – | ✅ | – | ✅ |
| active | – | – | ✅ | ✅ |
| completed | – | – | – | ✅ |
| archived | ✅ | ✅ | – | – |

日期副作用：
- archived → active：重設 `start_date=now`、清 `end_date`。
- → completed（且尚無 end_date）：設 `end_date=now`。
- → active：清 `end_date`；若無 `start_date` 則設 `start_date=now`。

### 共用 helper（避免漂移）

抽出 `apply_config_status_transition_sync(config_db, new_status)` 到
`app/services/test_run_set_status.py`（與 `recalculate_set_status_sync` 同模組,皆為 test-run 狀態邏輯）：
- 驗證轉換合法性,非法時 `raise ValueError`（各端點轉成 HTTP 400）。
- 套用 status + 日期副作用 + `updated_at`。
- **不**做 set 重算（由呼叫端負責,兩端都已持有 set membership）。

JWT `PUT /{config_id}/status` 與新的 app-token `/status` 都呼叫此 helper。JWT 端點行為不變
（僅把 inline 的狀態機/日期段落換成 helper 呼叫）。

### app-token 端點

`PUT /api/app/teams/{team_id}/test-run-configs/{config_id}/status`，scope `test_run:write`。
Body 重用 `StatusChangeRequest`（`status` 必填、`reason` 選填）。流程：載入 team-scoped config →
helper 轉換 → 若有所屬 set 則 `recalculate_set_status_sync` → 回 `_serialize_config`。

**保留一般 PUT 的 raw status 設定**（依決策）：狀態變更因此有兩條路徑——一般 PUT 直接設（不經狀態機）、
`/status` 經狀態機。文件會標明「要有生命週期驗證與日期連動請用 `/status`」。

## 2. Test Run Item 結果檔上傳

`POST /api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/upload-results`，
scope `test_run:execute`（屬執行證據,與更新結果同級）。

- multipart `files`（可多檔),重用 `get_attachments_root_dir()` 與 `build_attachment_metadata()`。
- 儲存路徑：`<attachments_root>/test-runs/{team_id}/{config_id}/{item_id}/`，檔名
  `{utc-timestamp}-{sanitized-original}`（與 JWT 相同 sanitize regex）。
- 更新 item：`execution_results_json`（追加 metadata list）、`result_files_uploaded`（>0 則 1）、
  `result_files_count`、`upload_history_json`（追加一筆上傳批次）——schema 與 JWT `/upload-results` 對齊。
- 回應：`{success, uploaded_files, upload_details, base_url:"/attachments"}`。
- Audit：`log_app_token_audit`，details 只含檔數,不含檔案內容。

## 3. 可攜式 client 的 multipart 設計

現況：`tcrt_api.sh` 用 curl config，只設 `Content-Type: application/json` + `data-binary=@json`；
`tcrt_api.py` 用 `urllib`，只送 JSON。兩者皆無 multipart。

新增 `--file field=@path`（可重複）：
- **sh client**：出現 `--file` 時,不寫 json 的 Content-Type/`data-binary`,改對每個檔寫
  curl config `form = "field=@path"`（curl 自動帶 multipart boundary 與 Content-Type）。
  既有「method+url+token 不得含特殊字元」的 guard 延伸到 `field` 與 `path`（拒絕 `"`、`\`、換行）,
  並檢查檔案存在;`--file` 與 `--data` 互斥。
- **python client**：出現 `--file` 時,手動組 `multipart/form-data` body（隨機 boundary、
  對每檔讀 bytes、附 `Content-Disposition`/`Content-Type`）,設對應 header。與 `--data` 互斥。
- 安全：token 仍只走 header、不入命令列可見處;不印檔案內容;`field`/`path` 經字元檢查。

## 4. 不納入

- 一般 PUT 改走狀態機（依決策保留 raw）。
- Test Run Set 層級的手動狀態轉換（現況為成員自動推導 + `/archive`,已足夠）。
- 刪除結果檔（JWT `/{item_id}/test-results/{file_token}`）——本次不含,可後續再議。
- client multipart 不寫進 OpenSpec spec（skill 為本機 gitignored,非追蹤契約）。
