# Spec — knowledge-graph-config

## Purpose

TBD - description pending.

## ADDED Requirements

### Requirement: KnowledgeGraphConfig
The system MUST provide a `KnowledgeGraphConfig` class with the following fields and `from_env` class method.

#### Scenario: Default values
- WHEN `KnowledgeGraphConfig()` is created with no arguments
- THEN `enabled` is `False`
- AND `sync_interval_minutes` is `30`
- AND `backfill_batch_size` is `100`
- AND `backfill_progress_path` is `"data/knowledge_backfill_progress.json"`

#### Scenario: Env var loading
- WHEN `NEO4J_URI=http://n:7687` and `NEO4J_PASSWORD=p` are set
- THEN `Neo4jConfig.from_env()` returns config with those values

### Requirement: Skip-block opt-in
The system MUST skip placeholder expansion for the `knowledge_graph` config block when `enabled=false`.

#### Scenario: Disabled with no env vars
- WHEN `KNOWLEDGE_GRAPH_ENABLED=false` (or unset) and config.yaml contains `${NEO4J_PASSWORD}` in the knowledge_graph block
- AND the env var `NEO4J_PASSWORD` is unset
- THEN `Settings.from_env_and_file()` MUST NOT raise
- AND the knowledge_graph block is replaced with default values

#### Scenario: Enabled with missing QDRANT_URL
- WHEN `KNOWLEDGE_GRAPH_ENABLED=true` and `QDRANT_URL` is unset
- THEN config loads successfully
- AND `is_knowledge_graph_enabled()` returns `False` (graceful degradation)

### Requirement: Neo4jConfig
The system MUST provide a `Neo4jConfig` for read-only Neo4j connection (TCRT does not write to Neo4j).

#### Scenario: Default values
- WHEN `Neo4jConfig()` is created
- THEN `uri=""`, `username="neo4j"`, `database="neo4j"`, `max_connection_pool_size=50`, `connection_timeout=30`

### Requirement: QdrantConfig
The system MUST provide a `QdrantConfig` with multi-collection support and gRPC TLS options.

#### Scenario: Default values
- WHEN `QdrantConfig()` is created
- THEN collection names default to `jira_references`, `test_cases`, `usm_nodes`
- AND `prefer_grpc=False`, `grpc_use_tls=False`

### Requirement: EmbeddingConfig
The system MUST provide an `EmbeddingConfig` with API key, dimensions, base_url, concurrency, and cache path.

#### Scenario: Default values
- WHEN `EmbeddingConfig()` is created
- THEN `dimensions=1024`, `provider="openrouter"`, `base_url=""`, `batch_size=100`, `concurrency=1`, `max_tokens_per_text=8000`, `cache_path="/tmp/embedding_cache.db"`

#### Scenario: OpenAI-compatible provider via base_url
- WHEN `EMBEDDING_PROVIDER=openai` and `EMBEDDING_BASE_URL=https://my-llm.example.com` are set
- THEN `EmbeddingService` posts to `https://my-llm.example.com/v1/embeddings`
- AND `EMBEDDING_API_KEY` is optional (LMStudio-style local servers don't require it)

#### Scenario: Parallel embed batches
- WHEN `EMBEDDING_CONCURRENCY=8` is set
- AND `embed_batch` is called with N texts where N > `EMBEDDING_BATCH_SIZE`
- THEN the input is split into chunks of `EMBEDDING_BATCH_SIZE` and up to 8 chunks are in-flight at once via `asyncio.gather` + `asyncio.Semaphore`
