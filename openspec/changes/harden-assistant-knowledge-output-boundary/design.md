## Context

`KnowledgeRetrievalService.search_knowledge`（`app/services/knowledge/retrieval_service.py`）在後端異常時走降級路徑，回傳 `{"status": "degraded", "message": ...}`。目前 `message` 直接嵌入原始例外字串：

```python
result = {"status": "degraded", "results": [],
          "message": f"Knowledge search unavailable: {exc}", ...}
```

`search_knowledge` 工具的 projection allowlist 為 `("status", "results", "message", "fallback_recommended")`，`message` 因此會進入 LLM context 與 `assistant_messages`。紅隊探針證實例外文字含 `bolt://host:port` 與資料庫帳號。

同檔 `_process_results_generator` 為每筆結果組出 `xml_snippet`：

```python
item["xml_snippet"] = f'<knowledge_source team_id="{t_id}" team_name="{t_name}">\n{item["snippet"]}\n</knowledge_source>'
```

`snippet` 來源是被索引的 test case／USM 內容（`hybrid_search_service._build_snippet`，取 steps／expected_result／precondition 前段），未經任何跳脫。若內容含 `</knowledge_source>`，即可在 LLM 眼中偽造包裝邊界並附加指令。

兩者都落在 `assistant-data-boundary` capability 既有的「外送資料範圍明定」與「洩漏防護自動化測試」精神內，屬缺口補強而非新行為。

## Goals / Non-Goals

**Goals:**
- 降級 `message` 對外（LLM／訊息／SSE）只呈現通用、與後端無關的字串；原始例外僅存在伺服器日誌。
- 知識結果內容進入 `xml_snippet` 前，中和 `<knowledge_source>` / `</knowledge_source>` 與角括號，使被索引內容無法逃出或偽造包裝。
- 翻轉既有紅隊測試的兩個 `xfail(strict=True)` 為正向斷言，鎖住行為。

**Non-Goals:**
- 不改團隊授權模型（全域助手、純 role），不碰 `get_user_accessible_teams`。
- 不改 Qdrant/Neo4j 查詢、collection、team filter。
- 不調整 projection allowlist 的欄位集合（`message` 仍在允許集合內，只是內容被淨化）。
- 不處理 A3/A3b 全域寫入意圖漂移（另案）。

## Decisions

**D1 — 降級訊息改為靜態常數，例外只進日誌。**
新增模組級常數（如 `_DEGRADED_MESSAGE = "Knowledge search is temporarily unavailable."`），所有 degraded 回傳路徑（kg_disabled／circuit_open／capacity／timeout／exception）統一使用它或既有的語意化短語，但**不得內插 `exc`**。原始 `exc` continue 走 `LOGGER.warning(..., exc_info=True)`。
- 替代方案：在 projection 端過濾 `message`。否決——projection 是欄位級 allowlist，`message` 是必要的降級語意載體（LLM 需要知道「不可用、請回退」），問題在內容而非欄位，應在來源淨化。

**D2 — 在 `xml_snippet` 組裝點中和分隔符。**
於 `_process_results_generator` 組 `xml_snippet` 前，對 `snippet`（與納入包裝的 `title`，如有）將 `<`、`>`、`"`、`'` 替換為對應全形字元，使其保留可讀性但不能被 XML parser 解讀為標籤或 attribute 分隔符。採全形中和而非 HTML entity escape，因為下游是給 LLM 讀的純文字包裝、非 HTML 渲染，entity（`&lt;`）會污染語義且仍可能被模型還原。
- 中和 MUST 在截斷（`safe_truncate_text`）之後、組 `xml_snippet` 之前，確保截斷不會製造新的半截標籤逃逸。
- 替代方案：改用非 XML 分隔（如 JSON）。否決——影響既有 prompt 慣例與 QA Helper grounding 格式，超出本次缺口範圍。

**D3 — 測試鎖定。**
把 `test_H1_backend_exception_detail_not_leaked_to_message` 與 `test_INJ1_indexed_content_cannot_escape_xml_envelope` 的 `xfail` 移除，改為正向斷言（message 不含後端細節；`xml_snippet` 僅一組包裝且 `snippet` 不含 `</knowledge_source>`）。

## Risks / Trade-offs

- [降級訊息變通用後，人工除錯線索變少] → 原始例外仍在伺服器日誌（`exc_info=True`），且 `degrade_reason`（kg_disabled／timeout／exception:<Type>）已另存於觀測性記錄（query log），除錯能力不受損。
- [剝除角括號可能改動含合法 `<` `>` 的正常內容（如程式碼片段）] → 僅作用於送 LLM 的 `xml_snippet` 摘要，且 snippet 已是截斷後的預覽；完整內容經 `get_test_case_global` 取得不受影響。權衡下防逃逸優先。
- [其他呼叫端（QA Helper `build_rag_context_for_qa_helper`）也組類似 `<knowledge_source>` 包裝] → 該路徑用的是 `search_knowledge` 的結果 `snippet`；於來源 snippet 淨化即同時保護該路徑。實作時一併確認其包裝不重新引入未淨化欄位。

## Migration Plan

- 純程式行為修正，無 schema／migration／設定變更。
- 部署即生效；回滾等於 git revert 單一 commit。
- 驗證：`uv run pytest app/testsuite/test_assistant_knowledge_redteam.py -q`（兩個原 xfail 轉 pass）＋知識相鄰回歸套件。

## Open Questions

- 無。分隔符中和策略（剝除 vs escape）已於 D2 定案為剝除。
