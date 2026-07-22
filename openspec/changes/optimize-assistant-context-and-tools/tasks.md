## 1. Config 與預算預設

- [x] 1.1 更新 `AssistantConfig`：`history_max_chars=480000`、`tool_result_max_chars=64000`、`max_iterations=24`、`turn_timeout_seconds=300`、`max_messages_per_conversation=500`，以及新 clamp 上界
- [x] 1.2 新增 compact 相關設定：`history_compact_enabled`、`history_compact_threshold_ratio`、`history_compact_keep_recent_groups` 與 `TCRT_ASSISTANT_*` env 解析／clamp
- [x] 1.3 在 config 註解或 runtime settings 可見處記載 DeepSeek V4 Flash 官方 1M tokens 與 TCRT working budget 差異
- [x] 1.4 補 config 單元測試（預設值與 clamp）

## 2. List soft truncation

- [x] 2.1 擴充 `projection.py`：list／`items` envelope soft truncation；裸陣列正規化 envelope；0 列可放入路徑
- [x] 2.2 executor 傳入 `skip` 計算 `next_skip`；order = project → redact → truncate；meta 不寫業務表
- [x] 2.3 測試：完整前列 + meta；0 列路徑；credential；非 list hard path

## 3. History compact（request-view）

- [x] 3.1 實作 exchange-group 結構化 compact（list tool-result meta 化）
- [x] 3.2 soft 閾值觸發、keep_recent；**recent 自身爆 budget 時組內壓縮 + 整組 trim**
- [x] 3.3 compact 不寫回 DB；失敗降級；flag 關閉
- [x] 3.4 測試：不拆 tool pair、注入不繞過 confirmation、recent 爆 budget、flag 關閉

## 4. 精簡讀取工具與預設／clamp limit

- [x] 4.1 item refs API／工具（projection；default 100；**clamp ≤500**；穩定排序）
- [x] 4.2 case refs API／工具（無 steps；default ≤50；**clamp ≤200**）
- [x] 4.3 Executor：full list 省略 limit 注入 ≤50，且 **clamp ≤100**；僅 loopback
- [x] 4.4 Registry：`default_limit`／`max_limit` 契約測試
- [x] 4.5 權限／team 歸屬測試（refs）

## 5. Filter 批次更新 API

- [x] 5.1 endpoint：封閉 filter（含 `assignee_unassigned`／明確未執行枚舉）+ patch；cap 500；0 筆拒絕；>500 → 422
- [x] 5.2 high_impact 工具：server count + filter + samples；pending 存 server matched ids
- [x] 5.3 fingerprint 含 matched ids digest；confirm 重 resolve → STALE
- [x] 5.4 測試：更新成功、0 筆、超限、stale、team mismatch、未確認不執行

## 6. Skills、prompt、iterations

- [x] 6.1 更新／新增 skills：`batch-assign-run-items`、`review-run-progress`（Discover → refs／filter → mutate）
- [x] 6.2 更新 `prompts/assistant/system.md` 工具優先序與禁止全量 full list 預設路徑
- [x] 6.3 確認 continuation turn 重置 `max_iterations` 計數；達上限固定文案仍有效
- [x] 6.4 調整 agent-loop 相關測試的 iteration／timeout 假設

## 7. 驗證與文件

- [x] 7.1 `uv run pytest` 針對 assistant／新 API 相關 tests
- [x] 7.2 `uv run ruff check` 變更路徑
- [x] 7.3 必要時同步 `tool-matrix` 附錄或 change 內矩陣 delta 註記
- [x] 7.4 `openspec validate optimize-assistant-context-and-tools --strict`
