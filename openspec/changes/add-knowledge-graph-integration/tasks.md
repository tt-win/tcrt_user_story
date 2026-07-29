# Tasks — add-knowledge-graph-integration

## Phase 1: Foundation (Config + Client Wrappers)

- [x] 1.1 Add `Neo4jConfig`（read-only）、`QdrantConfig`、`EmbeddingConfig`、`KnowledgeGraphConfig` to `app/config.py` with `from_env` class methods; add `knowledge_graph: KnowledgeGraphConfig` to `Settings`; implement skip-block for `enabled=false`
- [x] 1.2 Create `app/services/knowledge/__init__.py` with module docstring and lazy init pattern (module-level `get_*_service()` functions)
- [x] 1.3 Implement `app/services/knowledge/qdrant_client.py`: async wrapper around `qdrant_client.AsyncQdrantClient`, connection pool, health check, upsert/search/scroll helpers, multi-collection support, gRPC TLS config
- [x] 1.4 Implement `app/services/knowledge/neo4j_client.py`: async wrapper around `neo4j.AsyncGraphDatabase`（**read-only**）, connection pool, query helpers, health check
- [x] 1.5 Implement `app/services/knowledge/embedding_service.py`: embed text via OpenAI-compatible endpoint (provider="openrouter" → hardcoded URL; provider="openai" + `EMBEDDING_BASE_URL` → custom endpoint e.g. LMStudio), batch support, dimension validation (1024), defensive JSON parsing, rate-limit (429) handling, SQLite persistent cache (`/tmp/embedding_cache.db`, set `"none"` to disable), `EMBEDDING_API_KEY` optional for self-hosted
- [x] 1.6 Add `neo4j>=5.20` and `qdrant-client>=1.9` to `pyproject.toml` optional dependencies under `[project.optional-dependencies] knowledge`
- [x] 1.7 Implement `KnowledgeSyncTaskQueue`: in-memory `asyncio.Queue` + background worker, dedup via in-memory `set`, graceful shutdown (30s timeout), fire-and-forget semantics; `NullKnowledgeSyncTaskQueue` for disabled state
- [x] 1.8 Add unit tests: `app/testsuite/test_knowledge_config.py` (config loading, opt-in behavior, skip-block, graceful degradation)
- [x] 1.9 Add unit tests: `app/testsuite/test_knowledge_embedding_cache.py` (SQLite cache hit/miss, model/dimension invalidation)

## Phase 2: Qdrant Write Service

- [x] 2.1 Implement `app/services/knowledge/knowledge_write_service.py`: TestCase → embed → Qdrant upsert（via `MainAccessBoundary`）
- [x] 2.2 Implement USM → embed → Qdrant upsert（via `UsmAccessBoundary`）
- [x] 2.3 Implement incremental write: in-memory watermark per entity type, only process updated records
- [x] 2.4 Implement independent asyncio timer for scheduled writes（`asyncio.sleep(interval_minutes * 60)` + loop）
- [x] 2.5 Add event-driven write hooks: on TestCase create/update, enqueue to `KnowledgeSyncTaskQueue`; fire-and-forget semantics
- [x] 2.6 Implement initial bulk load (backfill): query ALL records, batch process (embed + upsert), progress tracking via JSON file (`data/knowledge_backfill_progress.json`), crash recovery from `last_processed_id`
- [x] 2.7 Implement backfill CLI entry point: `python -m app.services.knowledge backfill --entity test_cases|usm_nodes`
- [x] 2.8 Implement backfill REST API: `POST /api/knowledge/backfill`（admin-only, `Depends(require_admin)`）
- [x] 2.9 Implement auto-detect: first scheduled cycle checks if watermark exists and Qdrant collection is empty → auto-trigger backfill
- [x] 2.10 Implement backfill concurrency control: `is_backfill_in_progress` flag pauses incremental sync timer; event hooks continue normally
- [x] 2.11 Add integration tests: `app/testsuite/test_knowledge_qdrant_write.py` (test `MainAccessBoundary` / `UsmAccessBoundary` usage, test event hook enqueue, test idempotent upsert)
- [x] 2.12 Add backfill tests: `app/testsuite/test_knowledge_backfill.py` (test batch processing, progress persistence, crash recovery, auto-detect trigger, concurrency control)
- [x] 2.13 Add failure mode tests: `app/testsuite/test_knowledge_qdrant_down.py` (Qdrant offline during write), `test_knowledge_embedding_failure.py` (embedding API timeout/error, retry, `write_pending` marking)

## Phase 3: Hybrid Search Service

- [x] 3.1 Implement `app/services/knowledge/hybrid_search_service.py`: accept natural language query, run Qdrant semantic search across collections, run Neo4j graph queries（read-only）, merge and rank results
- [x] 3.2 Define search result model: `KnowledgeSearchResult` with `RelatedEntity` sub-model, source attribution, relevance score, sensitive field filtering
- [x] 3.3 Implement query-type detection: keyword extraction for Neo4j fulltext fallback, entity recognition for graph traversal
- [x] 3.4 Implement impact analysis query: given a Feature or JiraTicket, traverse graph to find affected TestCases, Features, and related tickets
- [x] 3.5 Implement context builder for QA AI Helper: given a Jira ticket key, return structured context
- [x] 3.6 Add optional REST API: `app/api/knowledge.py` with `GET /api/knowledge/search`, `GET /api/knowledge/impact/{entity_type}/{entity_id}`, `GET /api/knowledge/health`; all endpoints use JWT auth + team scope
- [x] 3.7 Implement runtime dimension validation: query Qdrant `collection_info`, verify dimensions match; mismatch → disable knowledge graph
- [x] 3.8 Add integration tests: `app/testsuite/test_knowledge_hybrid_search.py` (test auth, test team scope, test sensitive field filtering, test graceful degradation when Qdrant/Neo4j unavailable)

## Phase 4: Verification

- [x] 4.1 Run `uv run pytest app/testsuite/test_knowledge_*.py -q` and fix failures
- [x] 4.2 Run `uv run ruff check app/services/knowledge app/api/knowledge.py app/config.py` and fix lint
- [x] 4.3 Verify TCRT starts and operates normally without Neo4j/Qdrant configured (opt-in contract)
- [x] 4.4 Verify TCRT starts and connects when Neo4j/Qdrant are configured
- [x] 4.5 Verify graceful degradation: Qdrant unavailable → write disabled; Neo4j unavailable → semantic search only; embedding dimension mismatch → disable
- [x] 4.6 Run existing test suite `uv run pytest app/testsuite -q` to confirm no regressions
- [x] 4.7 Run `openspec validate add-knowledge-graph-integration --strict`

## Phase 5: Deferred (Future Phases)

以下任務延後至後續 phase，或由 `qa_knowledge_graph` 負責：

- [ ] 5.1 Feature node seed list and component → Feature mapping（由 `qa_knowledge_graph` 管理）
- [ ] 5.2 AutomationScript → Neo4j sync（由 `qa_knowledge_graph` 管理）
- [ ] 5.3 Tag nodes and TAGGED relationships（由 `qa_knowledge_graph` 管理）
- [ ] 5.4 Document chunks collection and sync（future phase）
- [ ] 5.5 Multi-worker write coordination（future phase, Redis/RQ or shared DB）
- [ ] 5.6 AI Assistant tool integration（future phase）
- [ ] 5.7 QA AI Helper context integration（future phase）

## Phase 6: USM Payload v2 and Dual-Qdrant Rebuild

- [x] 6.1 Inspect remote MySQL USM metadata read-only; record row counts, identity collisions, field types, nullability, and relation shapes without exposing row contents
- [x] 6.2 Define the merged `usm_node_v2` payload, composite `(map_id, node_id)` identity, deterministic embedding text, payload indexes, and coordinated rollback design in OpenSpec
- [x] 6.3 Implement canonical USM payload/text helpers and update runtime write, delete, queue dedup, backfill resume, and event hooks to use composite identity
- [x] 6.4 Implement the guarded remote-MySQL-to-Qdrant rebuild command with hidden credentials, read-only snapshot, backup/shadow preparation, validation, coordinated cutover, and rollback
- [x] 6.5 Add regression tests for payload types, legacy relation normalization, duplicate node IDs across maps, required confirmation, secret redaction, and cutover rollback
- [x] 6.6 Run targeted tests, Ruff, full knowledge tests, full repo Ruff, strict OpenSpec validation, and relevant project gates
- [x] 6.7 Create and validate backup/shadow collections on local and `10.81.1.49`, then replace both canonical `usm_nodes` collections from the remote MySQL source
- [x] 6.8 Verify both targets have identical v2 counts/schema/indexes and retain tested rollback collections
- [x] 6.9 Materialize both canonical names as physical `usm_nodes` collections, verify no canonical alias remains, and retain the verified v2 shadows for rollback
- [x] 6.10 Pass composite `entity_key` from semantic hits into Neo4j USM graph expansion, with legacy-only `node_id` fallback
