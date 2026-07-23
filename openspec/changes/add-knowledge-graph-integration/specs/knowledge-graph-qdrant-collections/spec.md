# Spec — knowledge-graph-qdrant-collections

## Purpose

TBD - description pending.

## ADDED Requirements

### Requirement: Qdrant collection vector configuration
The system MUST use 1024 dimensions and Cosine distance for all new Qdrant collections.

#### Scenario: New collection creation
- WHEN `QdrantKnowledgeClient.ensure_collection` is called for `test_cases` or `usm_nodes`
- THEN the collection is created with `size=1024` and `distance=COSINE`
- AND `on_disk_payload=true`

### Requirement: Collection names
The system MUST allow configurable collection names via env vars.

#### Scenario: Default collection names
- WHEN `QdrantConfig()` is created
- THEN `collection_test_cases` is `"test_cases"`, `collection_usm_nodes` is `"usm_nodes"`, `collection_jira_references` is `"jira_references"`

### Requirement: Embedding source
The system MUST concatenate test case fields in a deterministic order for embedding.

#### Scenario: Test case embedding text
- WHEN a test case is embedded
- THEN the text is `title + "\n" + precondition + "\n" + steps + "\n" + expected_result`

#### Scenario: USM node embedding text
- WHEN a USM node is embedded
- THEN the text is `title + "\n" + description + "\n" + "As a " + as_a + ", I want " + i_want + ", so that " + so_that`

### Requirement: Deterministic point IDs
The system MUST use deterministic UUID5-based point IDs for idempotent upsert.

#### Scenario: Test case point ID
- WHEN the same test case is upserted multiple times
- THEN the same Qdrant point ID is used
- AND no duplicate points are created
