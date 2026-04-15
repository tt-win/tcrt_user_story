# Capability: ETL All Teams

## Purpose

Synchronize test cases and user story map (USM) nodes from all teams to Qdrant vector database for RAG (Retrieval-Augmented Generation) context retrieval. This ETL process extracts data from the application's database, generates embeddings using OpenRouter's embedding API, and stores them in Qdrant for efficient semantic search.

## Requirements

### Requirement: Synchronize Test Cases

The system SHALL extract all test cases for each team and synchronize them to the `test_cases` Qdrant collection with appropriate embeddings and metadata.

#### Scenario: Full test case sync for a team
- **GIVEN** a team exists in the system
- **WHEN** the ETL process runs for that team
- **THEN** all test cases are fetched, embedded, and stored in Qdrant

### Requirement: Synchronize USM Nodes

The system SHALL extract all user story map nodes for each team and synchronize them to the `usm_nodes` Qdrant collection with appropriate embeddings and metadata.

#### Scenario: Full USM node sync for a team
- **GIVEN** a team exists in the system  
- **WHEN** the ETL process runs for that team
- **THEN** all USM nodes are fetched, embedded, and stored in Qdrant

### Requirement: Batch Processing

The system SHALL process items in configurable batches to avoid timeouts and memory issues during embedding generation and Qdrant upserts.

#### Scenario: Large dataset processing
- **GIVEN** a team has more than 50 test cases or USM nodes
- **WHEN** the ETL process runs
- **THEN** data is processed in batches of 50 items with progress reporting

### Requirement: Error Handling and Recovery

The system SHALL handle errors gracefully for individual teams without failing the entire ETL process. Errors SHALL be logged but not prevent other teams from being processed.

#### Scenario: Partial failure recovery
- **GIVEN** the ETL process is running for multiple teams
- **WHEN** one team's data fetch or processing fails
- **THEN** the error is logged and processing continues for remaining teams

### Requirement: Deterministic Point IDs

The system SHALL generate deterministic UUIDs for Qdrant points based on collection name and item ID to enable idempotent updates.

#### Scenario: Re-running ETL
- **GIVEN** the ETL has been run before
- **WHEN** it runs again with updated data
- **THEN** existing points are updated (not duplicated) based on deterministic IDs

## Removed Requirements

The following requirements have been removed as part of this refactoring:

### ~~Requirement: JIRA Ticket Synchronization~~ (REMOVED)

~~The system SHALL fetch JIRA ticket references from Lark tables and synchronize them to the `jira_references` Qdrant collection.~~

~~#### ~~Scenario: JIRA reference sync from Lark~~
~~- **GIVEN** a Lark table contains TCG ticket references~~
~~- **WHEN** the ETL process runs~~
~~- **THEN** corresponding JIRA tickets are fetched and stored in Qdrant~~

**Rationale**: This functionality is no longer needed and has been removed to simplify the ETL process.
