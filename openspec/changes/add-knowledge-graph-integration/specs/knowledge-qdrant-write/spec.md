# Spec — knowledge-qdrant-write

## Purpose

TBD - description pending.

## ADDED Requirements

### Requirement: Write strategies
The system MUST support three write modes: incremental, event-driven, and initial bulk load.

#### Scenario: Incremental write
- WHEN scheduled write runs
- THEN only test cases with `updated_at > watermark` are processed
- AND the watermark is updated to current time

#### Scenario: Event-driven write
- WHEN TestCase is created or updated via TCRT API
- THEN a write task is enqueued to `KnowledgeSyncTaskQueue`
- AND the API response does not wait for the write to complete (fire-and-forget)

#### Scenario: Event hook is no-op when disabled
- WHEN knowledge graph is disabled
- THEN `NullKnowledgeSyncTaskQueue` is used
- AND enqueue returns `False`

### Requirement: Initial bulk load
The system MUST support a one-time bulk load of all existing records.

#### Scenario: Backfill command
- WHEN `python -m app.services.knowledge backfill --entity test_cases` is run
- THEN ALL test cases are read from the DB
- AND processed in batches of `backfill_batch_size` (default 100)
- AND upserted to Qdrant

#### Scenario: Backfill progress persistence
- WHEN a backfill is running
- THEN progress is saved to `data/knowledge_backfill_progress.json` after each batch
- AND contains `processed_count`, `last_processed_id`, `status`, `started_at`, `updated_at`

#### Scenario: Backfill crash recovery
- WHEN a backfill crashes and is restarted
- AND the progress file has `status="in_progress"`
- THEN it resumes from `last_processed_id`, skipping already-processed records

#### Scenario: Backfill watermark on completion
- WHEN a backfill completes successfully
- THEN the watermark is set to the current time
- AND the progress status is set to `"completed"`

#### Scenario: Backfill concurrency control
- WHEN a backfill is in progress
- AND another backfill is triggered
- THEN the second one fails with `RuntimeError("Another backfill is already in progress")`

### Requirement: KnowledgeSyncTaskQueue
The system MUST provide an in-memory asyncio queue with dedup and graceful shutdown.

#### Scenario: Dedup same entity
- WHEN the same entity is enqueued twice in quick succession
- THEN only one task is actually processed
- AND the second enqueue returns `False`

#### Scenario: Graceful shutdown
- WHEN the queue is stopped
- THEN it waits up to 30s for in-flight tasks to complete
- THEN it cancels workers

### Requirement: Auto-detect
The system MUST auto-detect when backfill is needed at the first scheduled cycle.

#### Scenario: First-run auto-detect
- WHEN the first scheduler tick runs
- AND the watermark is missing
- AND the Qdrant collection is empty
- THEN a log message is emitted indicating backfill is required
- AND the actual backfill must be started via CLI

### Requirement: Runtime dimension validation
The system MUST validate that configured embedding dimensions match the existing Qdrant collection.

#### Scenario: Dimension mismatch
- WHEN `_ensure_collections` runs
- AND the existing collection has different dimensions than configured
- THEN the knowledge graph is disabled (`config.enabled = False`)
- AND no further writes are performed

### Requirement: Access boundaries
The system MUST use the correct access boundary for each entity type.

#### Scenario: TestCase read
- WHEN reading test cases
- THEN `MainAccessBoundary` is used

#### Scenario: USM read
- WHEN reading USM nodes
- THEN `UsmAccessBoundary` is used (NOT `MainAccessBoundary`)

### Requirement: Remote MySQL USM rebuild source
The guarded USM rebuild workflow MUST read `tcrt_usm.user_story_map_nodes`, its parent map,
and `tcrt_main.teams` from the explicitly configured remote MySQL server.

#### Scenario: Read-only consistent source snapshot
- WHEN a rebuild starts
- THEN MySQL uses a read-only consistent transaction
- AND the workflow executes no INSERT, UPDATE, DELETE, DDL, or schema migration
- AND credentials are supplied via an environment variable or hidden interactive prompt
- AND credentials are never printed or persisted by the workflow

#### Scenario: Composite identity source validation
- WHEN source rows are loaded
- THEN `(map_id, node_id)` is unique for every row
- AND missing map/team relationships or empty required identity fields abort the rebuild

### Requirement: Guarded dual-target replacement
The workflow MUST prepare and validate both Qdrant targets before replacing either canonical collection.

#### Scenario: Confirmation required
- WHEN the rebuild command is run without explicit confirmation
- THEN it may inspect redacted targets and source counts
- BUT it performs no Qdrant mutation

#### Scenario: Backup and shadow validation
- WHEN execution is explicitly confirmed
- THEN each existing `usm_nodes` is cloned to a timestamped backup
- AND each rebuilt dataset is first written to a timestamped shadow collection
- AND exact source/backup/shadow counts and the `usm_node_v2` contract are verified

#### Scenario: Coordinated cutover
- WHEN both shadow collections pass all checks
- THEN local and remote expose physical collections literally named `usm_nodes`
- AND neither canonical name remains an alias
- AND each physical collection is an exact vector/payload copy of its validated shadow
- AND backup collections remain available

#### Scenario: Failed preparation or cutover
- WHEN any target fails preparation, validation, or cutover
- THEN no unvalidated shadow becomes canonical
- AND any incomplete physical canonical collection is removed
- AND any already-switched target restores logical availability through its verified backup
