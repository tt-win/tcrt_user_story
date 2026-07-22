---
id: batch-update-test-cases
name: Batch update test cases
description: Change priority/TCG/section/set for many cases via batch tools; never loop update_test_case.
triggers:
  - batch update cases
  - 批次改
  - priority
  - 優先級
  - move section
---

# Batch update test cases

## Path

1. Resolve targets with `list_test_cases` / `find_test_cases_by_tickets` / user-provided numbers or ids.
2. Prefer batch tools:
   - priority / TCG → `batch_update_test_cases`
   - section / set move → `batch_move_test_cases` (high impact; may trigger cleanup)
   - delete many → `batch_delete_test_cases` only with explicit permanent-delete intent
3. One confirmation covers the whole batch tool call.

## Anti-patterns

- N× `update_test_case` for the same field change.
- Using generic update to move set/section (use `move_test_case_scope` / batch move tools).
