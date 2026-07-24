# Proposal — integrate-knowledge-rag-engine

## Intent

整合現有 Qdrant 向量資料庫與 Neo4j 圖資料庫（基於 `qa_knowledge_graph` 最新 Schema 實作），建立統一的 `KnowledgeRetrievalService` / RAG 檢索層。
為 AI Assistant 提供站內知識搜尋工具（`search_knowledge` 與 `analyze_knowledge_impact`），並為 QA AI Helper 提供歷史案例與 USM 脈絡的 Grounding 上下文，顯著提升 AI 回覆與測案產出的準確度與覆蓋率。

## Scope

- **IN Scope**:
  - 建立統一的 `KnowledgeRetrievalService` 服務模組 (`app/services/knowledge/retrieval_service.py`)。
  - 整合 `asyncio.Semaphore(20)` 並發控管、Circuit Breaker、2.5 秒 Async Timeout、150ms 圖超時、`safe_truncate_text` 防呆截斷及 Python Generator 記憶體保護。
  - 為 AI Assistant 新增知識工具 (`search_knowledge`, `analyze_knowledge_impact`) 並註冊至 `tools_catalog.py` 與系統提示詞中。
  - 在 QA AI Helper 中接入 `build_rag_context_for_qa_helper`，為需求導向的測試案例生成提供 0-shot / Few-shot Grounding 上下文。
  - 實作防護邊界：Qdrant Search-time `team_id` Payload Filter, Cypher `$team_id` 參數化查詢，與 `WHERE tc.team_id = $team_id` 團隊權限隔離。
  - FastAPI `lifespan` 5 秒 Graceful Shutdown 資源關閉流程。
  - 單元測試與整合測試 (`test_knowledge_retrieval_service.py`, `test_tools_knowledge.py`)。
- **OUT of Scope**:
  - 本次不改動 `qa_knowledge_graph` 獨立寫入服務之 Codebase。
  - 本次不新增前端 React/Vue 框架（沿用既有 Jinja2 + JS/CSS）。

## Core Principles & Trade-offs

- **安全第一 (Data Isolation First)**：所有向量與圖查詢必須強制帶有 `team_id` 隔離，防止跨團隊外洩。
- **平滑降級 (Graceful Degradation)**：RAG 作為增強層，當 Qdrant/Neo4j 服務異常或超時，核心 LLM Turn 與測案生成必須能無縫降級回零點 (0-shot) 續跑，絕不安靜崩潰或丟 500 錯誤。
- **記憶體與 Token 控制**：採用 Payload 投影與 Generator 逐筆切片，防止 OOM 暴脹。
