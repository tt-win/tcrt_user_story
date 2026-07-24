# Design — integrate-knowledge-rag-engine

## Context

TCRT 現有 `HybridSearchService` 提供底層 Qdrant 語義搜尋與 Neo4j 圖查詢功能，`qa_knowledge_graph` 服務則負責將 Qdrant 的 `test_cases`, `usm_nodes`, `jira_references` 同步至 Neo4j。
本變更旨在建立高階 RAG 服務 (`KnowledgeRetrievalService`)，並將其連接至 AI Assistant 工具箱及 QA AI Helper，以提供領域 Grounding 能力。

## Architecture & Components

```
┌─────────────────────────────────────────────────────────────┐
│                      TCRT Application                       │
│                                                             │
│  ┌───────────────────────┐       ┌───────────────────────┐  │
│  │      AI Assistant     │       │      QA AI Helper     │  │
│  │ (search_knowledge &   │       │ (Test Case Generation │  │
│  │ analyze_knowledge_    │       │  RAG Grounding)       │  │
│  │ impact tools)         │       │                       │  │
│  └───────────┬───────────┘       └───────────┬───────────┘  │
│              │                               │              │
│              ▼                               ▼              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  KnowledgeRetrievalService (RAG 檢索與安全邊界層)       │  │
│  │  - asyncio.Semaphore(20) & Circuit Breaker            │  │
│  │  - team_id Payload & Cypher Enforcer                  │  │
│  │  - 2.5s Timeout (150ms Graph Timeout)                 │  │
│  │  - safe_truncate_text & Generator streaming           │  │
│  └───────────────────────────┬───────────────────────────┘  │
│                              │                              │
│                              ▼                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │            HybridSearchService / Qdrant / Neo4j        │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Detailed Specifications

### 1. `KnowledgeRetrievalService` (`app/services/knowledge/retrieval_service.py`)
- **並發控管**：`asyncio.Semaphore(20)` 控制全系統最高 20 個併發檢索，超額直接 Fast-fail。
- **Circuit Breaker**：連續 3 次異常時熔斷 30 秒，自動退回零點降級。
- **型別安全**：所有傳入之 `id`, `key` 經由 Pydantic / `str(id)` 強制轉型，防呆與防零匹配 (Silent Miss)。
- **Cypher 語法對齊 (`qa_knowledge_graph`)**：
  - `JiraTicket` / `TestCase` / `USMNode` Cypher 查詢包含 `WHERE tc.team_id = $team_id`。
  - 100% 使用 `$parameter` Map 傳遞，嚴禁 f-string 拼接。
- **記憶體保護 (Generator Streaming)**：使用 Yield 逐筆處理 `safe_truncate_text`，自動閉合未成對的三反引號（```）標籤與 `... [Truncated]`。

### 2. AI Assistant 知識工具 (`app/services/assistant/tools_knowledge.py`)
- `search_knowledge(query: str, collections: list[str] = None)`:
  - 單對話回合 (Turn) 最多允許呼叫 **2 次**。
  - 註冊至 `tools_catalog.py` 之 `ALL_TOOLS`。
- `analyze_knowledge_impact(entity_type: str, entity_id: str)`:
  - 查詢受影響的相依元件與測試鏈。

### 3. QA AI Helper Grounding 整合
- `build_rag_context_for_qa_helper(jira_ticket, requirement_text, team_id)`:
  - 自動檢索相關歷史高品質測案與 USM 脈絡，限制 context <= 2,000 tokens。

### 4. FastAPI Lifespan 優雅關閉 (`app/main.py`)
- `async with` 綁定 Session 生命週期。
- FastAPI lifespan 提供 5 秒 Shutdown 超時保護，清空連線池。
