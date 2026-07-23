# Proposal — add-knowledge-graph-integration

## Why

TCRT 目前的 QA AI Helper 走 IR-first 路線，直接從 Jira ticket 結構化解析需求，
不依賴向量搜尋。這在單一 ticket → test case 的場景運作良好，但有三類需求無法覆蓋：

1. **跨 ticket 語義搜尋**：「哪些 test case 提到東南亞彩？」、「某功能如何設定？」
   需要在 71,000+ Jira reference 中做語義相似度比對。
2. **功能影響分析**：「修改功能 A 會影響哪些 test case 和相關功能？」需要圖遍歷。
3. **Test case 生成佐證**：QA AI Helper 生成 test case 時，應能參考已有的相似
   test case 與相關需求規格，避免重複並提升品質。

Qdrant server（`http://10.81.1.49:6333`）仍在運行，`jira_references` collection
有 71,385 points（1024 維 / Cosine / schema v1）。先前 `remove-qdrant-support`
（2026-07-14）移除的是 TCRT 內嵌的死代碼（client / ETL / health check），proposal
明確保留「若未來要重新引入向量檢索，須開新 change 重新定義契約」的路徑。

本 change 重新引入 Qdrant 寫入支援（TCRT 管理的實體）並整合 Neo4j 知識圖譜
（**read-only**），形成 **Hybrid Search**（語義 + 圖譜）架構，供 AI Assistant
與 QA AI Helper 使用。

**Neo4j 的寫入與 schema 管理由獨立服務 `qa_knowledge_graph` 負責**（專案位於
`~/code/qa_knowledge_graph`），TCRT 不管理 Neo4j 的資料寫入或 schema 初始化。

## What Changes

- 新增 `app/services/knowledge/` 模組：
  - `qdrant_client.py`：async Qdrant client wrapper（連線池、retry、health check）
  - `neo4j_client.py`：async Neo4j driver wrapper（**read-only**，連線池、query helpers）
  - `embedding_service.py`：embedding 產生（封裝 OpenRouter 或 local model，維度 1024）
  - `knowledge_write_service.py`：TestCase / USM → Qdrant 寫入（embedding + upsert）
  - `hybrid_search_service.py`：混合搜尋（Qdrant 語義 + Neo4j 圖遍歷 + 結果合併）
  - `chunking.py`：長文件切塊策略（用於長文本 embedding）
- 擴充 `app/config.py`：新增 `Neo4jConfig`（read-only）、`QdrantConfig`、`EmbeddingConfig`、
  `KnowledgeGraphConfig`，整合到 `Settings`。
- 新增 Qdrant collections：`test_cases`、`usm_nodes`（與既有
  `jira_references` 對齊 1024 維 / Cosine）。
- 新增 `app/api/knowledge.py`（可選）：知識圖譜查詢 REST API。
- 新增 Python 依賴：`neo4j>=5.20`、`qdrant-client>=1.9`。
- 測試：`app/testsuite/test_knowledge_*.py`。

## Capabilities

### New Capabilities

- `knowledge-graph-qdrant-collections`: 定義 Qdrant 新 collections（test_cases、
  usm_nodes）的向量與 payload schema。
- `knowledge-qdrant-write`: 定義 TestCase / USM 資料寫入 Qdrant 的流程、
  embedding 產生、event-driven hooks。
- `knowledge-hybrid-search`: 定義混合搜尋的查詢介面、Qdrant 語義搜尋 + Neo4j
  圖遍歷（read-only）的合併排序策略。
- `knowledge-graph-config`: 定義 Qdrant / Neo4j（read-only）/ Embedding 的設定結構與 env 變數。

### Deferred to qa_knowledge_graph

以下能力由獨立服務 `qa_knowledge_graph` 負責，不在本 change 範圍內：

- Neo4j schema 定義與初始化（constraints、indexes）。
- Qdrant → Neo4j 增量同步（scroll Qdrant → MERGE Neo4j）。
- `jira_references` → Neo4j `JiraTicket` 節點回填。
- Inter-ticket 關係建立。
- 同步水位管理。

### Modified Capabilities

- `assistant-tool-execution`（未來 phase）：新增知識圖譜查詢工具供 AI Assistant 使用。
- `qa-ai-helper-context`（未來 phase）：擴充 QA AI Helper 的 context building，
  整合 hybrid search 結果作為 test case 生成佐證。

## Impact

- **後端**：新增 `app/services/knowledge/` 模組（6 個檔案）；擴充 `app/config.py`。
- **資料庫**：不修改 TCRT 主庫 / audit / USM 的 schema。Neo4j 為外部 read-only 服務。
- **API**：可選的 `/api/knowledge/*` endpoint，不影響現有 API；遵循既有 JWT auth + team scope。
- **前端**：本次不新增前端頁面，僅為後端服務層。
- **部署**：Neo4j 5.x 由 `qa_knowledge_graph` 專案負責部署與管理。Qdrant 已在 `10.81.1.49:6333` 運行。
  新增 `NEO4J_*`（read-only）、`QDRANT_*`、`EMBEDDING_*` 環境變數。
  知識圖譜功能為 opt-in，未設定 `QDRANT_URL` 時不啟動寫入服務；未設定 `NEO4J_URI` 時圖查詢停用。
- **依賴**：新增 `neo4j>=5.20`、`qdrant-client>=1.9` 到 `pyproject.toml` `[project.optional-dependencies] knowledge`。
- **i18n**：本次無使用者可見文案變更。
- **外部專案**：需同步開發 `qa_knowledge_graph`（`~/code/qa_knowledge_graph`）負責 Neo4j 寫入與 schema 管理。
