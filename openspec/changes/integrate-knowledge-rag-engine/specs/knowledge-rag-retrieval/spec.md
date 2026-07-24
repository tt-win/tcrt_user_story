# Spec — knowledge-rag-retrieval

## Purpose

定義 `KnowledgeRetrievalService` 的 API 介面、隔離規則、超時與降級邏輯。

## ADDED Requirements

### Requirement: Unified RAG retrieval with team isolation
`KnowledgeRetrievalService` MUST enforce `team_id` filtering on all Qdrant vector searches and Neo4j Cypher queries.

#### Scenario: Cross-team data prevention
- WHEN `search_knowledge` or `build_rag_context` is executed for `team_id = X`
- THEN Qdrant search payload filter contains `team_id == X`
- AND Neo4j Cypher queries contain `WHERE tc.team_id == X`

### Requirement: Fault tolerance and graceful degradation
`KnowledgeRetrievalService` MUST catch timeouts, DB connection failures, and circuit breaker trips, returning degraded empty/fallback results without raising uncaught exceptions.

#### Scenario: Service timeout
- WHEN Qdrant or Neo4j search exceeds 2.5 seconds or circuit breaker is open
- THEN `KnowledgeRetrievalService` returns a degraded response object
- AND the caller continues execution cleanly
