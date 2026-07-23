## 1. Path traversal 修補 (H1)

- [x] 1.1 在 `app/models/test_case.py` 的 `TestCaseCreate` / `TestCaseUpdate`（及 batch / bulk-clone 使用的 model）為 `test_case_number` 加 field validator，拒絕 `/`、`\`、`..`、NUL → 422；顯示用 `TestCase` 基底不加限制。 → verify: `uv run pytest app/testsuite/test_app_token_test_case_api.py -q`
- [x] 1.2 在 `app/api/app_test_cases.py` attachment 上傳 loop，於 `open(stored_path, "wb")` 前加 `_ensure_within_root(stored_path, root_dir)`（或等效）。 → verify: 同 1.1 + 新增遍歷測試
- [x] 1.3 新增回歸測試：`test_case_number` 含 `../` 於 create/update 回 422；正常編號通過。 → verify: `uv run pytest app/testsuite/test_app_token_test_case_api.py -q`

## 2. 跨 team 授權完整性 (M1, L2)

- [x] 2.1 在 `PUT /api/app/teams/{team_id}/test-cases/{case_id}`（`app_test_cases.py:264-267`）寫入 set/section 前，比照 create 與 JWT 路徑驗證 set 屬 team、section 屬 set，不符回 400。 → verify: `uv run pytest app/testsuite/test_app_token_test_case_api.py -q`
- [x] 2.2 `_delete_attachment_common` 於 app-token 路徑以 `id + team_id` 過濾，找不到回 404，移除洩漏所屬 team 的 409 訊息；確認 JWT 路徑不受影響。 → verify: `uv run pytest app/testsuite/test_app_token_test_case_api.py -q`
- [x] 2.3 新增回歸測試：跨 team set/section 指派回 400；跨 team 附件刪除回 404。 → verify: 同上

## 3. Legacy MCP credential 收斂 (M3/D5)

- [x] 3.1 在 `/api/app/*` 的 principal 依賴（read / mutation 取得 principal 處）加入 `principal.is_legacy` 檢查，為真回 401 `APP_TOKEN_INVALID` 並寫 deny 審計；`/api/mcp/*` 不動。 → verify: `uv run pytest app/testsuite/test_app_token_read_api.py app/testsuite/test_mcp_api.py -q`
- [x] 3.2 新增回歸測試：legacy token（含 `allow_all_teams`）在 `/api/app/*` 一律 401；同 token 在 `/api/mcp/*` 仍可讀。 → verify: 同上
- [x] 3.3 在 tasks 相容性說明標註此為 BREAKING（改用 `/api/app/*` 的 legacy client 需改用正式 team app token）。 → verify: docstring / 變更說明審閱

## 4. 認證防濫用 rate limit (M4/D4)

- [x] 4.1 在 `app/config.py` 新增 app/mcp 認證失敗 rate limit 設定（capacity、window；預設保守如 30/min/IP）。 → verify: `uv run pytest app/testsuite/test_app_token_auth.py -q`
- [x] 4.2 在 `app/auth/app_token_dependencies.py` 對無效/缺失 token 路徑加 per-IP token bucket（重用 webhook 形狀），超限回 429 + `Retry-After`，且在寫審計前短路。 → verify: 同上
- [x] 4.3 新增測試：超限回 429；有效 token 不受限。 → verify: `uv run pytest app/testsuite/test_app_token_auth.py -q`

## 5. 審計保留與緩衝上限 (M4/D6)

- [x] 5.1 在 `app/services/scheduler.py` 的 `service_registry` 新增 audit cleanup service（daily，runner 呼叫 `audit_service.cleanup_old_records(AUDIT_CLEANUP_DAYS)`）。 → verify: `uv run pytest app/testsuite -q -k audit`
- [x] 5.2 為 `audit_service` 失敗重排的 in-memory buffer 設最大長度，超限丟最舊並記 warning。 → verify: 針對 buffer 上限的單元測試
- [x] 5.3 新增/更新測試涵蓋 cleanup 排程觸發與 buffer 上限行為。 → verify: 同 5.1

## 6. Expiry 邊界 (L1/D7)

- [x] 6.1 在 `AppTokenCreateRequest.expires_in_days` 加 `ge=0` 與上限（如 `le=3650`），超界回 422。 → verify: `uv run pytest app/testsuite/test_app_token_management_api.py -q`
- [x] 6.2 新增測試：負值與過大值回 422（非 500）；`0` 仍表不到期、`None` 仍為 90 天預設。 → verify: 同上

## 7. 敏感 test_data 遮蔽 (L6/D9)

- [x] 7.1 在 `/api/app/*` 與 `/api/mcp/*` 的 test case 詳情 payload 組裝（`app_read.py` / `mcp.py:_build_case_payload`）對 `category=="credential"` 的 test_data value 遮蔽。 → verify: `uv run pytest app/testsuite/test_app_token_read_api.py app/testsuite/test_mcp_api.py -q`
- [x] 7.2 新增測試：credential 類 test_data 於讀取回應被遮蔽。 → verify: 同上

## 8. 收尾驗證

- [x] 8.1 本 change 變更的檔案 ruff 乾淨（repo 既有 466 個 pre-existing 錯誤與本 change 無關，未動）。 → verify: `uv run ruff check <changed files>`
- [x] 8.2 相關子集全綠：`uv run pytest app/testsuite/test_app_token_auth.py app/testsuite/test_app_token_test_case_api.py app/testsuite/test_app_token_read_api.py app/testsuite/test_app_token_management_api.py app/testsuite/test_mcp_api.py -q`。 → verify: 該指令
- [x] 8.3 `openspec validate harden-app-token-security --strict` 通過。 → verify: 該指令
