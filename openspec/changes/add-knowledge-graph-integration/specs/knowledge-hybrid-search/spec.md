# Spec — knowledge-hybrid-search

## Purpose

TBD - description pending.

## ADDED Requirements

### Requirement: HybridSearchService
The system MUST provide `HybridSearchService` that combines Qdrant semantic search with Neo4j graph traversal.

#### Scenario: Semantic search returns results
- WHEN `hybrid_search` is called with a query
- AND Qdrant has matching vectors
- THEN results include entity_type, entity_id, title, score, source="semantic"

#### Scenario: Graph expansion
- WHEN `include_graph_expansion=True` and Neo4j is configured
- THEN top 5 results have `related_entities` populated
- AND `source` is updated to `"both"` when related entities are found

#### Scenario: Graceful degradation
- WHEN Neo4j is unavailable
- THEN `hybrid_search` continues with Qdrant-only results
- AND no exception propagates to the caller

### Requirement: Impact analysis
The system MUST provide graph-based impact analysis.

#### Scenario: Impact on JiraTicket
- WHEN `impact_analysis(entity_type="jira_ticket", entity_id="TCG-1")` is called
- THEN Cypher traverses DESCRIBES, AFFECTS, TESTS relationships
- AND returns affected features and test cases

### Requirement: Context builder for QA AI Helper
The system MUST provide `context_for_qa_helper(jira_ticket_key)` for test case generation context.

#### Scenario: Returns structured context
- WHEN a Jira ticket key is provided
- THEN the result includes: ticket, features, existing_test_cases, related_tickets, subtasks

### Requirement: Search result model
The system MUST define `KnowledgeSearchResult` and `RelatedEntity` Pydantic models.

#### Scenario: Default values
- WHEN a `KnowledgeSearchResult` is created with only required fields
- THEN `related_entities` defaults to `[]`
- AND `metadata` defaults to `{}`
- AND `source` defaults to `"semantic"`

### Requirement: Team scope filtering
The system MUST support team_id filtering.

#### Scenario: Filter by team
- WHEN `team_id=1` is provided in search options
- THEN only results with `team_id=1` in metadata are returned
