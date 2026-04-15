## 1. Config 與 Prompt 擴充 (Config and Prompt Extension)

- [x] 1.1 新增 `requirement_ir` 與 `coverage_backfill` prompt 設定鍵到 `config.yaml.example`（Add new prompt keys in config example）
- [x] 1.2 更新 `app/config.py` typed config，讓新 prompt 可由 `settings.ai.jira_testcase_helper.prompts` 讀取（Update typed config mapping）
- [x] 1.3 補齊 `config.yaml` 實際環境預設值，與現行四階段 prompt 相容（Populate runtime config defaults）

## 2. Requirement IR 階段實作 (Requirement IR Stage Implementation)

- [x] 2.1 在 helper service 新增 `build_requirement_ir()`，將 Jira/requirement 轉為 machine-readable JSON（Implement IR builder）
- [x] 2.2 將 IR 寫入 `ai_tc_helper_drafts.phase=requirement_ir`，並保留重試可覆寫行為（Persist IR draft with versioning）
- [x] 2.3 新增 IR schema 正規化函式，確保必填欄位與型別一致（Add IR normalization and validation）

## 3. Analysis/Coverage IR-first 改造 (IR-first Analysis/Coverage Refactor)

- [x] 3.1 改寫 analysis prompt 輸入來源為 `requirement_ir_json`（Switch analysis input to IR）
- [x] 3.2 改寫 coverage prompt，加入完整覆蓋契約與 trace 欄位（Enhance coverage prompt with completeness contract）
- [x] 3.3 實作 coverage parse fail 時「先重生、後 repair」的 fallback 順序（Implement regenerate-first retry policy）

## 4. 完整性 Gate 與補全回合 (Completeness Gate and Backfill Round)

- [x] 4.1 新增 `validate_coverage_completeness()` 比對 `analysis_ids` 與 `coverage_refs`（Add server-side completeness validator）
- [x] 4.2 實作 coverage backfill 回合，僅補 `missing_ids/missing_sections` 並與原 coverage 合併（Implement targeted backfill and merge）
- [x] 4.3 在 gate 未通過時阻擋 pre-testcase 產出並回傳可追蹤錯誤資訊（Block stage progression on incomplete coverage）

## 5. 表格語義保留與可追蹤性 (Table Semantics Preservation and Traceability)

- [x] 5.1 將 Reference table row 轉為 `reference_columns[]` 結構（Convert table rows to structured entities）
- [x] 5.2 保留 `sortable/fixed_lr/format_rules/cross_page_param/edit_note` 欄位語義（Preserve column rule semantics）
- [x] 5.3 將 IR trace 關聯到 analysis item 與 coverage seed（Link IR trace to downstream artifacts）

## 6. 測試與回歸驗證 (Tests and Regression Validation)

- [x] 6.1 新增單元測試：IR 產生、表格正規化、typed config 載入（Add unit tests for IR and config）
- [x] 6.2 新增服務測試：coverage completeness gate、backfill merge、retry 順序（Add service tests for gate/backfill/retry）
- [x] 6.3 使用 `TCG-93178` 建立回歸案例，驗證 pre-testcase 覆蓋率與穩定度提升（Add regression scenario for TCG-93178）

## 7. 觀測與上線 (Observability and Rollout)

- [x] 7.1 新增日誌欄位：analysis item 數、coverage 覆蓋數、missing ids、backfill 次數（Add quality telemetry logs）
- [x] 7.2 以 config 開關分階段啟用 IR-first 流程並提供快速回退（Enable staged rollout with rollback switch）
- [x] 7.3 更新操作文件，說明 IR-first 流程與故障排查路徑（Update operational documentation）
