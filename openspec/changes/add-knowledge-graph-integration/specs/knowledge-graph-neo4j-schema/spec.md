# Spec — knowledge-graph-neo4j-schema (Reference Only)

## Purpose

**本 spec 僅供 TCRT Hybrid Search 查詢參考。Neo4j schema 的實際定義、初始化與遷移由獨立服務 `qa_knowledge_graph`（`~/code/qa_knowledge_graph`）負責。**

TCRT 的 `hybrid_search_service.py` 需要知道 Neo4j 的節點類型、關係類型與屬性結構，以便撰寫正確的 Cypher 查詢。

## ADDED Requirements

### Requirement: Neo4j read-only access
TCRT MUST only perform read-only Cypher queries against Neo4j.

#### Scenario: No write operations
- WHEN `Neo4jClient` is used by TCRT services
- THEN only `execute_read` is called
- AND no MERGE / CREATE / DELETE / SET operations are issued

### Requirement: Graceful degradation
TCRT MUST gracefully degrade when Neo4j is unavailable.

#### Scenario: Neo4j down
- WHEN `NEO4J_URI` is unset or Neo4j is unreachable
- THEN `hybrid_search` continues with Qdrant-only semantic search
- AND no exception is raised to the caller

### Requirement: Node label recognition
TCRT MUST recognize node types via dictionary keys (no class-based dispatch).

#### Scenario: JiraTicket identification
- WHEN a record contains `ticket_key`
- THEN the entity type is `jira_ticket`

#### Scenario: TestCase identification
- WHEN a record contains `test_case_number`
- THEN the entity type is `test_case`

#### Scenario: USMNode identification
- WHEN a record contains canonical `entity_key` or legacy `node_id`
- THEN the entity type is `usm_node`

### Requirement: Composite USM graph lookup
TCRT MUST use the map-scoped `entity_key` returned by a `usm_node_v2` semantic hit when
expanding that entity through Neo4j.

#### Scenario: Canonical graph expansion
- WHEN a semantic USM result has `entity_key="{map_id}:{node_id}"`
- THEN the Neo4j lookup parameter is that complete `entity_key`
- AND the query matches `USMNode.entity_key` or its canonical `id`
- AND the query does not fall back to globally ambiguous `node_id` for canonical nodes

#### Scenario: Legacy graph compatibility
- WHEN a legacy Neo4j USM node has no `entity_key`
- THEN the read-only query may match its legacy `node_id`
