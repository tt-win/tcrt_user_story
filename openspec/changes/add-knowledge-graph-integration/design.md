# Design — add-knowledge-graph-integration

## Context

TCRT 管理測試案例（Test Case）、測試執行（Test Run）、User Story Map（USM）、
Automation Hub，並整合 Jira / Lark / LLM。QA AI Helper 使用 IR-first 路線從 Jira
ticket 結構化解析需求後產生 test case。AI Assistant 提供全域對話式操作。

目前缺少跨實體的語義搜尋與關係分析能力。Qdrant server 已在
`http://10.81.1.49:6333` 運行，`jira_references` collection 有 71,385 points
（1024 維 / Cosine / `jira_sync_v4` / schema v1）。Neo4j 尚未部署。

### 已驗證的 `jira_references` payload 結構（2026-07-23）

```json
{
  "title": "[2G] 2J GAMES Transfer 問題修復",
  "jira_ticket": "TCG-141375",
  "component": "GPD VIS",
  "component_team": "GPD",
  "component_product": "VIS",
  "components": ["GPD VIS"],
  "components_parsed": [{"raw": "GPD VIS", "team": "GPD", "product": "VIS"}],
  "source": "jira_sync_v4",
  "text": "標題: ...\nJIRA: TCG-141375\nComponent: GPD VIS\n...",
  "resource_type": "jira_reference",
  "updated_at": "2026-05-19T14:35:16+08:00",
  "schema_version": "v1",
  "chunk_index": 0,
  "total_chunks": 1,
  "section": "...",
  "chunk_text": "描述: ..."
}
```

## Goals / Non-Goals

**Goals:**
- TCRT 負責將 TestCase / USM 資料寫入 Qdrant（embedding + upsert）。
- TCRT 提供 Hybrid Search service（Qdrant 語義搜尋 + Neo4j 圖遍歷 read-only）。
- 新增 `test_cases`、`usm_nodes` Qdrant collections（1024 維，與 `jira_references` 對齊）。
- 知識圖譜為 opt-in，未設定 Qdrant/Neo4j 時 TCRT 正常運作。

**Non-Goals:**
- **TCRT 不管理 Neo4j 的寫入、schema 初始化或同步水位** — 由獨立服務 `qa_knowledge_graph` 負責。
- 本次不修改 AI Assistant agent loop 或新增 assistant 工具。
- 本次不修改 QA AI Helper 的七屏流程或 prompt。
- 本次不新增前端頁面。
- 不取代 TCRT 主庫 SQLAlchemy 的資料存取；Neo4j 是補充層。
- 不做 Feature 節點的 AI 自動推斷（留待後續 phase）。

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      TCRT Application                         │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │ AI Assistant │  │ QA AI Helper │  │ TestCase/USM API   │  │
│  └──────┬──────┘  └──────┬───────┘  └─────────┬──────────┘  │
│         │                │                     │             │
│         └────────┬───────┘                     │             │
│                  ▼                             ▼             │
│  ┌────────────────────────────┐  ┌────────────────────────┐ │
│  │    Hybrid Search Service   │  │  Knowledge Write Svc   │ │
│  │  (Qdrant read + Neo4j read │  │  (embed + Qdrant write)│ │
│  │   + merge, read-only both) │  └──────────┬─────────────┘ │
│  └─────────┬──────────┬───────┘             │               │
│            │          │                     │               │
│  ┌─────────▼──┐ ┌─────▼──────────┐ ┌───────▼──────┐       │
│  │ Qdrant     │ │ Neo4j Client   │ │ Embedding Svc│       │
│  │ Client     │ │ (read-only)    │ └──────────────┘       │
│  └──────┬─────┘ └──────┬─────────┘                        │
│         │              │                                   │
└─────────┼──────────────┼───────────────────────────────────┘
          │              │
          ▼              ▼
   ┌──────────────┐  ┌──────────────┐
   │   Qdrant     │  │   Neo4j      │
   │ 10.81.1.49   │  │  (managed by │
   │ :6333        │  │ qa_knowledge │
   │              │  │ _graph svc)  │
   └──────┬───────┘  └──────┬───────┘
          │                 │
          │    ┌────────────┴──────────────┐
          └───▶│  qa_knowledge_graph       │
               │  (independent service)    │
               │  - scroll Qdrant          │
               │  - MERGE into Neo4j       │
               │  - schema management      │
               │  - sync watermarks        │
               └───────────────────────────┘
```

### 職責邊界

| 職責 | TCRT | qa_knowledge_graph |
|------|------|-------------------|
| Qdrant `test_cases` / `usm_nodes` 寫入 | ✅ | — |
| Qdrant `jira_references` 寫入 | — | — (靜態快照) |
| Qdrant 讀取（語義搜尋） | ✅ | ✅ (scroll for sync) |
| Neo4j 讀取（圖遍歷） | ✅ (read-only) | — |
| Neo4j 寫入（MERGE nodes/rels） | — | ✅ |
| Neo4j schema 初始化 | — | ✅ |
| Embedding 產生 | ✅ | — |
| 同步水位管理 | — | ✅ |
| Event hooks (TestCase create/update) | ✅ → Qdrant only | — |

## Decisions

### Decision 1：知識圖譜為獨立服務模組，opt-in 啟用

**選項：**
- A. 深度整合到現有 service 層，所有功能強制依賴。
- B. 獨立模組 `app/services/knowledge/`，透過 config flag opt-in。

**選擇 B。**

**理由：**
- 不影響現有 TCRT 部署（無 Neo4j/Qdrant 也能運行）。
- 服務模組獨立，測試可隔離。
- 符合漸進式整合策略。

### Decision 2：Neo4j 寫入由獨立服務負責，TCRT 僅 read-only

**選項：**
- A. TCRT 同時管理 Qdrant 寫入 + Neo4j 寫入 + schema。
- B. TCRT 只管 Qdrant 寫入 + Neo4j read-only；Neo4j 寫入由獨立服務 `qa_knowledge_graph` 負責。

**選擇 B。**

**理由：**
- TCRT 程式碼大幅簡化：無 `neo4j` write client、無 schema init、無 sync pipeline、無水位管理。
- TCRT 部署不需要 `NEO4J_PASSWORD` 等寫入憑證。
- 獨立服務可獨立部署、獨立擴展、獨立重啟，不影響 TCRT 穩定性。
- Neo4j schema 演進由 `qa_knowledge_graph` 自行管理（Alembic-style migration 或自行版本化）。
- 符合單一職責原則：TCRT 管 TCRT 資料，知識圖譜 sync 是獨立關注點。

### Decision 3：Neo4j 存圖結構、Qdrant 存向量，不做功能重疊

**選項：**
- A. 只用 Neo4j（含其向量搜尋功能）。
- B. 只用 Qdrant（加 payload 做粗略關係）。
- C. 雙引擎：Neo4j 存關係圖、Qdrant 存向量。

**選擇 C。**

**理由：**
- Qdrant 已有 71K+ Jira reference 向量，且語義搜尋是核心需求。
- Neo4j 的圖遍歷能力（影響分析、依賴鏈）是 Qdrant 無法取代的。
- 雙引擎 Hybrid Search 能同時回答語義問題和關係問題。

### Decision 4：embedding 維度統一 1024，與既有 jira_references 對齊

**理由：**
- 跨 collection 搜尋需要相同的 embedding space。
- 已驗證 jira_references 使用 1024 維。
- 新 collection 必須使用相同的 embedding model 和維度。

### Decision 5：Event-driven Qdrant write hook 使用 KnowledgeSyncTaskQueue

**方案：**
- 新增 `KnowledgeSyncTaskQueue`：in-memory `asyncio.Queue` + 背景 worker，支援 dedup。
- TestCase create/update → enqueue Qdrant write task（embed + upsert）。
- **Conditional activation：** 當知識圖譜停用時，hook 為 no-op（`NullKnowledgeSyncTaskQueue`）。
- Fire-and-forget：TestCase API 回應不等待 Qdrant write 完成。

### Decision 6：Initial Bulk Load（Backfill）支援首次全量寫入

**問題：** 首次啟用知識圖譜時，TCRT 資料庫中已有大量 TestCase / USM 資料，需要一次性全部寫入 Qdrant。

**方案：**
- **觸發方式：** CLI（`python -m app.services.knowledge backfill`）、REST API（`POST /api/knowledge/backfill`）、或首次排程自動偵測（watermark 不存在 + Qdrant collection 為空）。
- **批次處理：** `batch_size = 100`（可配置），每批 embed → batch upsert。
- **進度追蹤：** 持久化到 `data/knowledge_backfill_progress.json`，記錄 `processed_count`、`total_count`、`last_processed_id`、`status`。
- **中斷恢復：** 重啟後檢查進度檔，從 `last_processed_id` 繼續。
- **並行控制：** Backfill 期間暫停增量 sync（`is_backfill_in_progress` flag），event-driven hooks 仍正常運作。
- **完成後：** 設定 watermark 為當前時間，刪除進度檔，恢復增量 sync。

**效能估算：**
- 5000 test cases，batch_size=100 → 50 batches。
- Embedding API rate limit ~1000 req/min → 每批 1 API call → 約 5 分鐘完成。
- Qdrant batch upsert 100 points/batch，無瓶頸。

### Decision 7：Embedding cache 實作為磁碟 SQLite

**理由：**
- 71K+ documents × 1024 dims ≈ 290 MB 僅向量，in-memory 會造成 OOM 風險。
- SQLite：key = SHA256(content + model + dimensions)，value = embedding bytes。
- Cache hit 直接回傳，miss 才呼叫 API。

### Decision 8：Embedding dimension 必須在 runtime 驗證

**機制：**
- Config load 時：驗證 `EMBEDDING_DIMENSIONS > 0`。
- Knowledge graph 初始化時：對每個 target collection 呼叫 `QdrantClient.get_collection()` 讀取 `vector_params.size`，與 config 比對。
- 不匹配 → `LOG.error` + disable knowledge graph。

### Decision 9：知識圖譜 REST API 遵循既有 auth dependency

**規範：**
- `GET /api/knowledge/search`、`GET /api/knowledge/impact/{entity_type}/{entity_id}`
- 依賴 `Depends(get_current_user)` + `Depends(require_team_permission(team_id, PermissionType.READ))`。
- 回傳資料自動過濾敏感欄位。
- `GET /api/knowledge/health`：admin-only 或可配置為任何認證用戶。

### Decision 10：USM identity 使用 `(map_id, node_id)` 複合鍵

2026-07-29 對遠端 MySQL `10.81.0.13:3306` 的唯讀盤點結果：

- `tcrt_usm.user_story_map_nodes` 有 1,774 rows（17 maps）。
- `(map_id, node_id)` 有 1,774 個唯一值，但全域僅有 1,727 個唯一 `node_id`。
- 47 組 `node_id` 跨 map 重複；單獨以 `node_id` 產生 point ID 會覆蓋 47 rows。
- 所有 map 都有 `team_id`，且都能對應 `tcrt_main.teams`。

因此 canonical identity 為 `entity_key = "{map_id}:{node_id}"`，Qdrant point ID 使用
`UUID5("tcrt-usm-node:{entity_key}")`。`node_id` 保留為 map 內識別與 legacy consumer
相容欄位；delete、event queue dedup、backfill resume 與 graph relation key 都必須使用
複合 identity。

Hybrid Search 將 Qdrant hit 的 `entity_key` 原樣傳給 Neo4j graph expansion，並優先查詢
`USMNode.entity_key` / canonical `id`。只有缺少 `entity_key` 的 legacy Neo4j node 才允許
退回 `node_id`，避免 canonical v2 graph lookup 同時命中跨 map 的重複節點。

### Decision 11：`usm_node_v2` 融合 payload 與 embedding text

新版 payload 同時保留 TCRT writer 所需的 `last_synced_at`、`parent_id`、team scope，
以及舊版遠端 ETL 的 `text`、`resource_type`、`updated_at`、`children_ids`、
`related_node_ids`、`team_name`。額外加入複合關係鍵，避免跨 map 關係歧義：

- `entity_key`、`parent_key`
- `children_keys`
- `related_node_keys`
- `schema_version="usm_node_v2"`
- `source="tcrt_usm_mysql"`

所有 optional string 正規化為空字串、集合欄位正規化為 `list[str]`，避免同一欄位
混用 `null`、缺欄與不同 JSON 型別。`text` 是實際送入 embedding provider 的完整文字，
以 map、node type、title、description、BDD 與 Jira tickets 的固定順序組成；payload 與
embedding 不得使用不同內容。

### Decision 12：遠端 MySQL 唯讀重建與可回滾切換

USM rebuild 使用 `tcrt_usm.user_story_map_nodes` JOIN `user_story_maps` JOIN
`tcrt_main.teams` 作為唯一資料來源。連線必須開啟 read-only consistent snapshot，
不得對 MySQL 執行 DDL/DML。密碼不得放在 CLI argument、repo 或 log。

每個 Qdrant target 的流程：

1. 複製現有 `usm_nodes` 為 timestamped backup collection，並核對 exact count。
2. 建立 timestamped shadow collection（1024 / Cosine / on-disk vector+payload）。
3. 建立 `entity_key`、`node_id`、`map_id`、`team_id`、`node_type`、`updated_at`、
   `last_synced_at` payload indexes。
4. 從 MySQL 產生 payload 與 embedding，寫入 shadow。
5. 驗證 point count 等於來源 row count、所有複合鍵唯一、必填欄位覆蓋率 100%、
   vector 維度 1024，且兩端 shadow 結果一致。
6. 只有兩端 shadow 都通過時，才移除既有的 `usm_nodes` alias 或舊實體名稱，建立真正
   名為 `usm_nodes` 的 physical collection，從已驗證 shadow 複製完整 vectors/payload，
   並重建相同 payload indexes。
7. 再次驗證 physical `usm_nodes` 的 point IDs、payload checksum、vector 維度、indexes，
   且確認 `usm_nodes` 不再是 alias。任一 target 失敗時，已切換 target 以 backup alias
   恢復可用性。

alias 移除到 physical collection 建立完成之間會有短暫讀取中斷；此取捨換取 collection
列表與 API 均能直接看到實體 `usm_nodes`。兩端切換仍採協調式回滾，避免一端保留未驗證
結果。

舊 backup 不在同一操作中刪除。若需清除，必須另行取得明確核准。

## Module Layout

```
app/services/knowledge/
├── __init__.py
├── neo4j_client.py              # Neo4j async driver wrapper (read-only queries)
├── qdrant_client.py             # Qdrant async client wrapper (read + write)
├── embedding_service.py         # Embedding generation (OpenRouter/local)
├── knowledge_write_service.py   # TestCase/USM → embed → Qdrant upsert
├── hybrid_search_service.py     # Combined semantic + graph search (both read-only)
└── chunking.py                  # Long document chunking strategy
```

## Config Structure

```python
class Neo4jConfig(BaseModel):
    uri: str = ""                           # bolt://host:7687 (read-only)
    username: str = "neo4j"
    password: str = ""                      # env-only
    database: str = "neo4j"
    max_connection_pool_size: int = 50
    connection_timeout: int = 30

class QdrantConfig(BaseModel):
    url: str = ""                           # http://host:6333
    api_key: str = ""                       # env-only
    timeout: int = 30
    prefer_grpc: bool = False
    collection_jira_references: str = "jira_references"
    collection_test_cases: str = "test_cases"
    collection_usm_nodes: str = "usm_nodes"

class EmbeddingConfig(BaseModel):
    model: str = ""
    dimensions: int = 1024                  # aligned with jira_references
    provider: str = "openrouter"            # "openrouter" | "openai" (OpenAI-compatible)
    api_key: str = ""                       # EMBEDDING_API_KEY (optional for self-hosted)
    base_url: str = ""                      # EMBEDDING_BASE_URL — required when provider="openai"
    batch_size: int = 100
    concurrency: int = 1                     # EMBEDDING_CONCURRENCY: parallel in-flight requests
    max_tokens_per_text: int = 8000
    cache_path: str = "/tmp/embedding_cache.db"  # Docker-friendly; set "none" to disable

class KnowledgeGraphConfig(BaseModel):
    enabled: bool = False                   # opt-in
    neo4j: Neo4jConfig = Neo4jConfig()
    qdrant: QdrantConfig = QdrantConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    sync_interval_minutes: int = 30
    backfill_batch_size: int = 100
    backfill_progress_path: str = "data/knowledge_backfill_progress.json"
```

## Error Handling

- Neo4j / Qdrant 連線失敗：log warning，不阻擋 TCRT 啟動。
- Embedding API 失敗：retry with backoff，超過上限標記為 pending。
- Qdrant write 失敗：log error，不影響 TestCase/USM API 回應（fire-and-forget）。
- 知識圖譜查詢失敗：graceful degradation，回傳空結果而非 500。
- Neo4j 不可用：Hybrid Search 降級為 Qdrant-only 語義搜尋。
- Qdrant 不可用：Hybrid Search 降級為 Neo4j-only fulltext 搜尋（若可用）。
