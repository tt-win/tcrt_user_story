## 1. Requirement 契約與解析基礎 (Requirement Contract and Parsing Foundation)

- [x] 1.1 定義 `structured_requirement` schema 與欄位版本（Define `structured_requirement` schema and versioned fields）
- [x] 1.2 實作 Jira wiki 標題/清單解析器（Implement Jira wiki heading and list parser）
- [x] 1.3 實作 `As a / I want / So that` 子欄位抽取（Implement `As a / I want / So that` field extraction）
- [x] 1.4 實作 Acceptance Criteria 的 Given/When/Then scenario 拆解（Implement Given/When/Then scenario decomposition）
- [x] 1.5 實作穩定 `requirement_key` 生成規則（Implement stable `requirement_key` generation rules）

## 2. 完整性檢查與警告流程 (Completeness Validation and Warning Flow)

- [x] 2.1 實作 requirement completeness validator（Implement requirement completeness validator）
- [x] 2.2 輸出 `missing_sections`/`missing_fields`/`quality_level` 契約（Output validation contract fields）
- [x] 2.3 擴充 analyze 入口支援 override 決策參數（Extend analyze entry for override decision inputs）
- [x] 2.4 寫入 override trace（使用者、時間、缺漏快照）（Persist override trace with actor/time/missing snapshot）

## 3. Pre-testcase 呈現重構 (Pre-testcase Presentation Refactor)

- [x] 3.1 在 pretestcase payload 新增 `requirement_context` 結構（Add `requirement_context` to pretestcase payload）
- [x] 3.2 將規格條件與驗證要求映射到 `spec_requirements`/`verification_points`（Map spec requirements and verification points）
- [x] 3.3 調整 `ref/rid` 為 trace metadata 非主顯示內容（Demote `ref/rid` to trace metadata）
- [x] 3.4 實作 pre-testcase category 三值正規化（Implement category normalization to happy/negative/boundary）

## 4. Service 模組化與相容層 (Service Modularization and Compatibility Layer)

- [x] 4.1 抽離 `requirement_parser` 模組（Extract `requirement_parser` module）
- [x] 4.2 抽離 `requirement_validator` 與 `requirement_ir_builder` 模組（Extract validator and IR builder modules）
- [x] 4.3 抽離 `pretestcase_presenter` 與 adapter（Extract pretestcase presenter and compatibility adapter）
- [x] 4.4 保留 orchestrator 並整合 phase transition（Keep orchestrator and integrate phase transitions）
- [x] 4.5 統一 draft payload envelope（`schema_version/phase/data/quality/trace`）（Unify draft payload envelope）

## 5. 前端互動與顯示更新 (Frontend Interaction and Rendering Updates)

- [x] 5.1 重用既有 confirm modal 實作「返回修正 / 仍要繼續」（Reuse existing confirm modal for proceed warning）
- [x] 5.2 顯示缺漏段落與欄位清單的 warning 文案（Render missing-section/missing-field warning details）
- [x] 5.3 更新 pre-testcase UI 主顯示 requirement/spec/verification 區塊（Render requirement-rich pre-testcase blocks）
- [x] 5.4 對齊前端 category 選項與後端三值語義（Align frontend categories with backend semantics）
- [x] 5.5 盤點並鎖定既有 Helper UI 可重用元件清單（Inventory and lock reusable Helper UI components）
- [x] 5.6 以「必要最小改動」原則套用 UI 更新，避免重做現有三步驟框架（Apply minimal UI deltas without rebuilding stepper framework）
- [x] 5.7 若需新增/調整 UI，實作時使用 `$tcrt-ui-style` 並遵循 TCRT UI 風格（Use `$tcrt-ui-style` for any necessary UI changes under TCRT style guardrails）

## 6. Prompt 與設定來源收斂 (Prompt and Configuration Source Consolidation)

- [x] 6.1 收斂 helper prompt 契約為單一設定來源（Consolidate helper prompt contract to single config source）
- [x] 6.2 在 prompt 與 payload 增加契約版本欄位（Add contract version fields in prompt and payload）
- [x] 6.3 建立 prompt render snapshot 測試避免 drift（Add prompt render snapshot tests to prevent drift）
- [x] 6.4 將 analyze 流程改為單次 prompt 合併輸出 analysis+coverage（Switch analyze flow to single-prompt merged analysis+coverage output）
- [x] 6.5 停用 coverage 初次生成呼叫，coverage 缺漏/不完整直接回報 analysis 失敗（Disable standalone coverage generation call; fail analysis directly on missing/incomplete coverage）
- [x] 6.6 僅保留 LLM 呼叫層補救（重試/JSON repair），不新增 coverage second-call 與 deterministic fallback 分支（Keep only LLM-level retry/JSON repair; remove coverage second-call and deterministic fallback branches）
- [x] 6.7 強化 testcase/testcase_supplement/audit prompt：明確要求完整 preconditions/steps/expected result，並禁止 pre/s/exp 使用占位詞（REF/同上/略/TBD/N/A）（Harden testcase-family prompts with explicit completeness and placeholder bans）

## 7. 測試與回歸驗證 (Testing and Regression Validation)

- [x] 7.1 新增 parser 測試覆蓋兩組 requirement 範例（Add parser tests for the two requirement examples）
- [x] 7.2 新增 validator + override 流程測試（Add validator and override-flow tests）
- [x] 7.3 新增 pre-testcase requirement-rich 呈現測試（Add requirement-rich pre-testcase rendering tests）
- [x] 7.4 新增 category 正規化與 legacy 映射測試（Add category normalization and legacy mapping tests）
- [x] 7.5 新增 API/前端整合測試驗證 warning gate（Add API/frontend integration tests for warning gate）
- [x] 7.6 新增 UI 回歸測試，確認既有 Helper 主要互動與版面未被破壞（Add UI regression tests for existing Helper interaction/layout preservation）
- [x] 7.7 新增 generate 流程回歸：當 LLM testcase 含禁止詞時不應中斷，系統需自動修補後繼續（Add generate regression for forbidden placeholders with non-interrupting auto-repair）

## 8. 文件、觀測與上線準備 (Docs, Observability, and Rollout Readiness)

- [x] 8.1 更新 helper runbook（格式契約、warning 流程、override 說明）（Update helper runbook with contract and warning flow）
- [x] 8.2 補強 telemetry 指標（warning 次數、override 比率、缺漏類型）（Add telemetry for warning and override quality signals）
- [x] 8.3 定義 rollout 與 rollback 操作步驟（Define staged rollout and rollback procedures）
