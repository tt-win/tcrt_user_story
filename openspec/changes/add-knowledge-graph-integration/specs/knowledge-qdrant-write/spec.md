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
