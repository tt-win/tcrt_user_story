# AI Helper Stage Debug Tool

本工具為本機除錯用途，提供 `AI Agent - Test Case Helper` 六階段逐步執行與 artifact 回放能力。

工具檔案：`tools/helper_stage_debug_runner.py`（`tools/` 已在 `.gitignore`）

輸出目錄：`.tmp/helper-debug-runs/<run-id>/`（已在 `.gitignore`）

## 支援階段

1. `requirement_ir`
2. `analysis`
3. `coverage`
4. `testcase`
5. `audit`
6. `final_testcase`

每個階段都會輸出兩個檔案：
- `NN-<stage>.json`：完整機器可讀 artifact（含 llm_calls）
- `NN-<stage>.md`：完整格式化呈現

## 使用方式

## 1) 互動式 TUI（無參數，建議）

```bash
python tools/helper_stage_debug_runner.py
```

或：

```bash
python tools/helper_stage_debug_runner.py tui
```

啟動後可直接在選單中操作：
- 執行完整流程
- 重跑單一階段
- 檢視指定 run/stage 輸出
- 列出既有 runs

## 2) 一次跑完整流程（參數模式備援）

```bash
python tools/helper_stage_debug_runner.py run \
  --ticket-key TCG-93178 \
  --run-id tcg-93178-debug-01 \
  --review-locale zh-TW \
  --output-locale zh-TW \
  --initial-middle 010
```

## 3) 只重跑單一階段（參數模式備援）

```bash
python tools/helper_stage_debug_runner.py stage-run \
  --run-id tcg-93178-debug-01 \
  --stage coverage \
  --force
```

## 4) 檢視階段輸出（格式化）

```bash
python tools/helper_stage_debug_runner.py show \
  --run-id tcg-93178-debug-01 \
  --stage coverage
```

## 5) 檢視階段輸出（JSON）

```bash
python tools/helper_stage_debug_runner.py show \
  --run-id tcg-93178-debug-01 \
  --stage coverage \
  --format json
```

## Artifact 內容重點

每個 stage artifact 包含：
- `inputs`：該階段輸入
- `llm_calls`：該階段所有 LLM 呼叫（含 prompt、response_content、error）
- `outputs`：該階段主輸出
- `error`：失敗時的完整例外
- `meta`：摘要資訊（count、locale、ticket_key 等）

若某階段失敗，可直接對該 stage 的 `.json/.md` 做檢討，再使用 `stage-run --force` 重跑該階段。
