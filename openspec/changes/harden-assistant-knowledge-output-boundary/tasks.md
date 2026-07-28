## 1. 降級訊息淨化（H1）

- [x] 1.1 在 `retrieval_service.py` 新增通用降級訊息常數，所有 degraded 回傳路徑改用它，移除 `message` 中對 `exc` 的內插
- [x] 1.2 確認 exception 路徑仍以 `LOGGER.warning(..., exc_info=True)` 保留原始例外於伺服器日誌
- [x] 1.3 確認 `analyze_impact` 降級路徑同樣不外洩後端細節

## 2. 知識結果包裝逃逸防護（INJ1）

- [x] 2.1 在 `_process_results_generator` 組 `xml_snippet` 前中和 `snippet`／`title` 的 `<knowledge_source>`／`</knowledge_source>` 與角括號
- [x] 2.2 確保中和在 `safe_truncate_text` 之後套用，避免截斷產生半截標籤
- [x] 2.3 確認 `build_rag_context_for_qa_helper` 的包裝沿用已淨化 snippet，無其他未淨化欄位進入包裝

## 3. 測試鎖定

- [x] 3.1 移除 `test_H1_backend_exception_detail_not_leaked_to_message` 的 `xfail`，改為正向斷言（message 不含後端細節）
- [x] 3.2 移除 `test_INJ1_indexed_content_cannot_escape_xml_envelope` 的 `xfail`，改為正向斷言（單一包裝、內容無字面 `</knowledge_source>`）

## 4. 驗證

- [x] 4.1 `uv run pytest app/testsuite/test_assistant_knowledge_redteam.py -q`（原兩個 xfail 轉 pass，其餘不回歸）
- [x] 4.2 知識相鄰回歸：`uv run pytest app/testsuite/test_knowledge_retrieval_service.py app/testsuite/test_tools_knowledge.py app/testsuite/test_knowledge_hybrid_search.py -q`
- [x] 4.3 `uv run ruff check app/services/knowledge/retrieval_service.py app/testsuite/test_assistant_knowledge_redteam.py`
- [x] 4.4 `openspec validate harden-assistant-knowledge-output-boundary --strict`
