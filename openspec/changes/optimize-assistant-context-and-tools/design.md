## Context

Global assistant（`add-global-ai-assistant`）以 OpenRouter tool-calling 迴圈執行：history 以 **serialized character budget** 裁切 exchange groups、tool 結果經 projection → credential redaction → 字元截斷後入 LLM。現況預設：

| 參數 | 現值 | clamp 上界 | 問題 |
|------|------|------------|------|
| `history_max_chars` | 48_000 | 400_000 | 遠低於長 context 模型可用工作集 |
| `tool_result_max_chars` | 8_000 | 64_000 | list 約 20–40 筆 ITEM 即 hard-truncate 成 preview |
| truncate 策略 | 整包 → `{truncated, preview}` | — | 模型失去 id／分頁，無法續作 |
| `max_iterations` | 8 | 32 | 分頁＋組 batch＋確認鏈不足 |
| `turn_timeout_seconds` | 180 | 900 | 與較多步 tool 呼叫可能衝突 |
| `max_messages_per_conversation` | 200 | 100_000 | 長任務可能先撞訊息上限 |

**模型能力（2026-07 查證）**：DeepSeek V4 Flash（與 V4-Pro）官方 **1,000,000 tokens** context（非 262K）。社群／評測常見現象：標稱 1M 可用，但 **coding／agent 品質在 ~128k–256k 之後明顯下滑**，實務常用 150k–250k 工作窗。本設計 **不以 262K 為硬上限、亦不以 1M 為預設灌滿**。

操作痛點代表例：使用者要對 test run 內大量 item 批次改 assignee——現況需 `list_test_run_items` 拉完整 ITEM projection，結果被 8k 砍掉，模型拿不到穩定 id 列表。

## Goals / Non-Goals

**Goals:**

1. 把 conversation working budget 調整到「長 context 模型可完成多步 QA 操作」的等級，並可 env 調校。
2. 提供 **request-view compact**：逼近 budget 時壓縮最舊 history，DB 完整保留。
3. 依操作意圖提供 **slim／ref 讀取** 與必要 **特化 batch API**，避免為改 assignee 拉全文。
4. 合理提高 **每 turn 工具步數**（iterations）與 timeout 相容性。
5. 規格可測；**正式紅隊結論見同目錄 `red-team-review.md`（RT-01…22）**，非僅本節 Risks 短表。

**Non-Goals:**

- 精確 token 計數或 per-model tokenizer 內嵌。
- 預設 1M 全窗、或取消 list 上限。
- 取消 write confirmation、credential 聊天寫入。
- 重構整個 tool matrix 為兩階段 router。
- 改變 UI 端既有 pagination 預設（除非另開 UI change）。

## Decisions

### D1. 模型能力 vs 預設 working budget

| 層級 | 值 | 說明 |
|------|-----|------|
| 模型能力上限（文件／註解） | **1M tokens**（DeepSeek V4 Flash／Pro 官方） | 不是 262K |
| 預設 working history | **`history_max_chars = 480_000`**（約 ~120k tokens 粗估；使用者選定「更激進」檔） | 留 headroom 給 system／tools schema／本 turn tool results；仍遠低於 1M 標稱 |
| 預設 tool result | **`tool_result_max_chars = 64_000`** | 配合 soft list truncation；單次 tool 不吃光 history |
| hard clamp 上界 | history **1_200_000** chars；tool_result **200_000** chars | 允許 env 拉高，但拒絕無界 |
| soft compact 觸發 | 使用中 history 序列化長度 ≥ **`history_compact_threshold_ratio * history_max_chars`**（預設 **0.75**） | 先 compact 再 hard drop oldest groups |

**為何不用 262K tokens 當預設：** 來源不可靠；且 tokens≠chars。系統繼續用 **character budget**（既有 agent-loop 契約）。

**為何不用 1M 預設：** 延遲、費用、品質崖、tools schema 仍佔空間；admission／hourly limit 無法單獨擋住超大 prompt。

**Context-length 400 退讓：** 維持既有「尚未 mutation 副作用前 drop oldest group 一次」；compact 失敗或仍 400 則既有路徑。

### D2. List-aware soft truncation（取代毀滅式 preview）

在 `project_and_redact` 之後（R2 修補）：

1. 若 payload 為 **list of objects** 或 **`{items: [...]}` envelope**：
   - 裸陣列 MUST 正規化為 `{items, …meta}` envelope。
   - 在 `tool_result_max_chars` 內從前往後保留**完整列**。
   - meta：`truncated`、`returned_count`、`source_count`、`next_skip=(request_skip|0)+returned_count`、固定英文 `hint`。
   - executor MUST 傳入該次 tool call 的 `skip`。
   - 0 列可放入：回空 `items` + truncated meta，**禁止**對未 redact 內容 hard preview。
2. 非 list detail：超出則 hard truncate `{truncated, preview}`（已 redact）。
3. Soft meta **不得**寫入業務表或當 mutation body；順序 project→redact→truncate 不變。

### D3. Request-view compact（DB 完整保留）

```
DB messages (full, immutable for audit/UI)
        │
        ▼
 build_history() ──► soft/hard char budget
        │
        ├── below soft threshold ──► 送 LLM
        │
        └── ≥ soft threshold ──► compact oldest groups
                 │
                 ├── 結構化 compact（優先，deterministic）
                 │     舊 tool-result list 改存 meta+id 樣本；
                 │     舊純文字 assistant/user 可截斷預覽
                 └── 可選 LLM compact（僅對已結構化失敗的舊 prose groups）
                          摘要進 synthetic user/system 說明，
                          不產生假 tool_call
        │
        ▼
 protocol-valid messages[] → OpenRouter
```

規則：

- Compact **只改 request view**，不 UPDATE／DELETE `assistant_messages`。
- 必須 **整組 exchange group** 處理（與 history_builder 同一 group 定義）。
- 最近 **N 組**（預設 **4**，clamp ≥1）**優先**完整；但若 recent 自身超過 hard budget，MUST 組內壓縮 tool-result，再自最舊 recent 整組 trim（R2：RT-R2-03）。
- Compact 摘要 MUST NOT 成為 confirmation summary／fingerprint 輸入。
- 來源 tool-result 已 redact；LLM compact 不計入 max_iterations，計入 wall-clock；失敗／逾時 → 結構化 compact 或 hard trim。

### D4. 操作族盤點 → 工具／API 策略

#### 族別

| 族 | 典型使用者意圖 | 現況 | 本 change |
|----|----------------|------|-----------|
| **A. Discover** | 有哪些 run／統計如何 | list configs、get_run_statistics | 強化 skill：先 stats/count |
| **B. Select-refs** | 只要 id／case number 列表以便 mutation | 被迫 full ITEM／TC-LIST | **新增 slim 工具** |
| **C. Mutate-by-id** | 已知 id 改 result／assignee | batch_update_results 已支援 | 保持；skill 指引 |
| **D. Mutate-by-filter** | 「所有未指派改給 X」 | 需 list 全量再 batch | **特化 batch-by-filter API**（高價值） |
| **E. Structure** | set/section/scope | 既有 | 不變 |
| **F. Automation** | 觸發 CI | 既有 | 不變 |
| **G. Authoring** | 建 case／改 steps | detail 必要 | 維持 get detail 按需 |

#### 新增／調整（v1 封閉清單）

**讀取（loopback tools，優先）**

1. `list_test_run_item_refs`  
   - GET 新端點或既有 items + `view=refs`：回 `[{id, test_case_number, test_result, assignee_name}]`（**無 title/comment/timestamps**）  
   - 支援既有 filters + skip/limit；預設 limit **100**，上限 **500**（assistant 端 clamp；與 filter batch cap 對齊）  
   - Projection 對齊 slim allowlist

2. `list_test_case_refs`  
   - 同理：`record_id, test_case_number, title?, priority, test_case_set_id` 可配置；預設 **無 steps**  
   - 預設 limit **50**，上限 **200**（assistant）

3. 既有 `list_test_run_items` / `list_test_cases`  
   - 保留 full projection 給需要 title/comment 的場景  
   - 省略 limit → default ≤50；**不論是否傳入，clamp full list limit ≤100**（R2：RT-R2-01）；不改 UI 直連行為  
   - refs：default 100／clamp 500（items）、default 50／clamp 200（cases）  
   - registry 宣告 `default_limit`／`max_limit`；分頁列表穩定排序（id tie-break）

**寫入（特化 API，必要）**

4. `batch_update_test_run_items_by_filter`  
   - 封閉 filter：`test_result` 枚舉（含明確未執行值）、`assignee_unassigned` bool、可選 `assignee_name`／`search`  
   - matched cap **500**；**0 筆拒絕 pending**；>500 → 422  
   - fingerprint 含排序 matched ids digest；confirm 重 resolve → stale  
   - pending payload 存 **server 解析 id 集合**，不採信模型 id 列表  
   - high_impact + confirmation（count + filter + ≤10 samples）

5. **不在 v1 做**：任意 SQL-like filter、跨 config 全域 batch、無上限 matched。

**Skills**

- 新增／更新 skill：`batch-assign-run-items`、`review-run-progress`  
  - 路徑：statistics → item_refs（filter）→ batch_update(_by_filter) → 確認  
  - 禁止 skill 指示「先 list 全量 full items」

### D5. 步驟上限（iterations）與 timeout

| 參數 | 新預設 | 新 clamp 上界 |
|------|--------|----------------|
| `max_iterations` | **24** | **64** |
| `turn_timeout_seconds` | **300** | **900**（既有） |
| `max_messages_per_conversation` | **500** | 既有上界可維持 |

- Iteration 定義不變：每次 LLM 呼叫算一輪；read tool 後續跑；write 建 pending 結束本 turn。
- Confirm continuation **共用**同一 `max_iterations` 預算或 **獨立重置**？**定案：continuation 重置 iteration 計數**（與「新 turn」一致），避免 confirm 後無法收尾；仍受 turn_timeout 與 admission 約束。
- 達上限訊息維持系統固定文案（非 LLM 編造）。

### D6. 與既有安全契約的相容

- Write 一律 confirmation；特化 batch 不降級。
- team_id 仍 executor 注入；filter batch 的 matched items 必須 `config_id`+team 歸屬。
- credential 遮罩與禁止聊天寫入不變。
- 新端點 MUST 有 in-handler 或與既有 items 同等的 auth 依賴；executor permission 仍為必要防線。
- Journal／pending 不存 raw 超大 list；只存 redacted 參數與 confirmation summary。

### D7. 設定面

新增 config（皆可 env override + clamp）：

- `history_compact_threshold_ratio`（0.5–0.95，預設 0.75）
- `history_compact_keep_recent_groups`（1–20，預設 4）
- `history_compact_enabled`（bool，預設 true）
- `assistant_list_default_limit` / 或 per-tool 在 registry 宣告 `default_limit`／`max_limit`

文件註明：DeepSeek V4 Flash context **1M tokens**；TCRT 預設 working budget 刻意更低。

## Risks / Trade-offs

> **完整對抗審查：** `red-team-review.md`（RT-01…22、必測清單 §6、殘餘 §7）。下表僅摘要。

| 風險 | 緩解 | RT |
|------|------|-----|
| Compact 摘要被 tool-result prompt injection | 摘要不得驅動 confirmation；write 仍 server template；compact 優先結構化 | RT-08/09 |
| Filter batch 誤傷大量 items | matched cap 500；確認卡顯示 count+filter+sample；high_impact | RT-14/15 |
| 提高 budget → 費用／延遲 | 激進檔仍低於 1M；hourly message + admission；slim 工具降 payload；compact 降舊歷史 | RT-01/05/21 |
| 長 context 品質崖（>256k tokens 量級） | 預設 history 遠低於崖；compact 保持近期完整 | RT-01 / §7 |
| Soft truncate 改變 list shape，模型混淆 | 固定 envelope 欄位；skill／tool description 同步 | RT-03 |
| 新 API 與 UI 契約分叉 | 特化端點路徑明確（assistant 或 `view=`）；UI 不強迫遷移 | RT-19 |
| Continuation 重置 iterations 被濫用刷步數 | turn_timeout + message/hour + active turn limits | RT-20/21 |
| `max_iterations` 24 仍不足極長分頁 | filter batch 減少分頁需求；refs limit 500；skill 教 filter | RT-22 |

## Migration Plan

1. 先合入 config 預設與 soft truncation（行為相容、list 結果更可用）。
2. 再合入 ref 工具與 skills。
3. 再合入 filter batch API + confirmation。
4. 最後啟用 compact（feature flag 預設 on，可 env 關）。
5. **Rollback**：env 將 budget／iterations 調回舊值、`history_compact_enabled=false`、停用新工具（registry flag 或勿註冊）即可；DB 無破壞性 migration（compact 不改訊息表）。若新表／新欄位：僅 config 無需 migration；新 API 為 additive。

## Open Questions

**已定案（2026-07-22 使用者）：** 採用「更激進 budget」——`history_max_chars=480_000`、`tool_result_max_chars=64_000`、filter batch matched cap **500**、`max_iterations=24`。新 API 走一般 team JWT。

**紅隊：** R1 → R2（9 缺口已修）→ R3（無阻擋級疑慮）。見 `red-team-review.md`。  
**無未決 open question**；等使用者下令實作。
