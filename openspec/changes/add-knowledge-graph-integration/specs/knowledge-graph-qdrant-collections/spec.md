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

### Requirement: Canonical USM payload schema v2
Every `usm_nodes` point MUST use the same `usm_node_v2` payload contract.

#### Scenario: Required identity and provenance fields
- WHEN a USM row is converted to a Qdrant point
- THEN `schema_version` is `"usm_node_v2"`
- AND `resource_type` is `"usm_node"`
- AND `source` is `"tcrt_usm_mysql"`
- AND `entity_key` is `"{map_id}:{node_id}"`
- AND `map_id` and `team_id` are integers
- AND `node_id`, `map_name`, `team_name`, `title`, `description`, and `node_type` are strings

#### Scenario: Hierarchy and relation fields
- WHEN a USM row is converted to a Qdrant point
- THEN `parent_id` and `parent_key` are strings (empty for a root)
- AND `level` is an integer
- AND `children_ids`, `children_keys`, `related_node_ids`, `related_node_keys`, and `jira_tickets` are arrays of strings
- AND every child or related composite key includes its map ID

#### Scenario: Story and timestamp fields
- WHEN a USM row is converted to a Qdrant point
- THEN `as_a`, `i_want`, and `so_that` are strings
- AND `updated_at` is the source-row timestamp in RFC 3339 form
- AND `last_synced_at` is the Qdrant ingestion timestamp in RFC 3339 form
- AND `text` exactly equals the string sent to the embedding provider

#### Scenario: Null normalization
- WHEN an optional source string or JSON array is null
- THEN the payload stores an empty string or empty array of the declared type
- AND required keys are never omitted

### Requirement: Canonical USM payload indexes
The system MUST create payload indexes for fields used by identity, authorization, filtering, and incremental sync.

#### Scenario: New usm_nodes collection indexes
- WHEN a `usm_node_v2` collection is created
- THEN `entity_key`, `node_id`, and `node_type` have keyword indexes
- AND `map_id` and `team_id` have integer indexes
- AND `updated_at` and `last_synced_at` have datetime indexes

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
- THEN text lines are emitted in this deterministic order: map name, node type, title, description, `as_a`, `i_want`, `so_that`, Jira tickets
- AND empty optional values do not change the order of non-empty lines
- AND the same text is stored in payload field `text`

### Requirement: Deterministic point IDs
The system MUST use deterministic UUID5-based point IDs for idempotent upsert.

#### Scenario: Test case point ID
- WHEN the same test case is upserted multiple times
- THEN the same Qdrant point ID is used
- AND no duplicate points are created

#### Scenario: USM point identity across maps
- WHEN two USM rows have the same `node_id` but different `map_id`
- THEN their `entity_key` and deterministic UUID5 point IDs are different
- AND neither point overwrites the other
