## Context

目前 Helper 主流程已具備多階段（Requirement IR -> Analysis -> Coverage -> Testcase -> Audit），但故障排查主要依賴即時 log，缺乏「單次執行完整 artifact」可回放資料。當 LLM 在特定階段回傳格式偏差或內容截斷時，工程師難以重建當下輸入與模型輸出，造成修復迭代慢、誤判率高。

此變更需要一個離線/除錯導向的統一工具，不改動使用者 UI 流程，專注提供 stage-level 可重跑與可觀測性。

## Goals / Non-Goals

**Goals:**
- 提供單一 debug runner，覆蓋六個階段且每階段可獨立執行。
- 每階段寫入完整 artifact（input/prompt/raw response/parsed/error/meta）。
- 支援由 stage artifact 回放與格式化檢視，便於人工檢討。
- 工具與輸出預設位於 git ignore 路徑，不污染版本庫。

**Non-Goals:**
- 不改動線上 API 契約與前端互動流程。
- 不替代正式審計紀錄（audit.db）；本工具只做工程排障資料。
- 不引入新外部基礎建設（沿用既有 Jira/OpenRouter/Qdrant clients）。

## Decisions

### Decision 1: 以 `scripts/` 新增 CLI runner，不嵌入 API 路由
- Rationale: 減少線上風險與耦合，便於本機/測試環境重跑。
- Alternatives:
  - 新增後端 debug API：會增加權限與安全面，且可能誤用到 production。
  - 直接在 service 加落檔：會污染主流程，難控制輸出量。

### Decision 2: 每階段使用固定 artifact schema（JSON）
- Rationale: 方便機器比對與後續自動化分析。
- Artifact 最小欄位：`stage`, `started_at`, `ended_at`, `inputs`, `prompt`, `llm_raw`, `llm_parsed`, `error`, `meta`。
- Alternatives:
  - 只存文本 log：可讀性低，難以程式化 diff。

### Decision 3: 每階段函式獨立 + 可由前一階段檔案重建輸入
- Rationale: 支援「只重跑失敗階段」，縮短迭代時間。
- Alternatives:
  - 僅整條 pipeline：每次都要重跑前面階段，成本高。

### Decision 4: final testcase 以 deterministic 合併輸出
- Rationale: 明確區分 `audit` 原始輸出與最終提交前 canonical payload。
- Alternatives:
  - 直接沿用 audit 原樣：會失去一致化檢查機會。

## Risks / Trade-offs

- [Risk] Artifact 含敏感內容（ticket/模型輸出）落地本機
  → Mitigation: 預設輸出到 `.tmp/helper-debug-runs/`，文件明確標示僅本機除錯使用。
- [Risk] 工具與主流程 service 行為不一致
  → Mitigation: 直接重用現有 service/prompt/llm client，不重寫核心邏輯。
- [Risk] 單次執行產生大量檔案
  → Mitigation: run-id 分目錄，提供 stage 單跑模式與摘要輸出。

## Migration Plan

1. 新增 debug runner 腳本與 artifact dataclass。
2. 新增六個 stage 函式與 stage loader/formatter。
3. 新增 `.tmp/helper-debug-runs/.gitkeep` 並更新 `.gitignore` 規則。
4. 加入基本測試：stage artifact 寫入、讀取、格式化呈現。
5. 提供使用方式文件（命令與輸出路徑）。

Rollback:
- 移除 `scripts/` 新增檔案與 `.tmp` 目錄規則即可，不影響既有資料庫/API。

## Open Questions

- 是否需要後續加入 artifact 脫敏（PII masking）開關？
- 是否需要在 CI 加入「重播固定 fixture ticket」的長測？
- formatter 是否要提供 markdown table 與純文字兩種模式？
