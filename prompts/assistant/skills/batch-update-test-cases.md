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

1. Resolve targets with `list_test_case_refs` / `find_test_cases_by_tickets` / user-provided numbers or ids. Use `set_id` and `search` / `tcg_filter` to narrow results; ask the user only if filters are ambiguous.
2. Pull **all** matching refs in one call when the intent is clearly "the remaining cases matching X": pass `limit=200` (max) and inspect `has_next`; if more remain, continue paging with `skip` until you have every target. Do not silently cap at the default 50.
3. Prefer batch tools:
   - priority / TCG → `batch_update_test_cases`
   - section / set move → `batch_move_test_cases` (high impact; may trigger cleanup)
   - delete many → `batch_delete_test_cases` only with explicit permanent-delete intent
4. One confirmation covers the whole batch tool call.

## Anti-patterns

- N× `update_test_case` for the same field change.
- Using generic update to move set/section (use `move_test_case_scope` / batch move tools).
- Stopping after the first page of `list_test_case_refs` when the user said "all remaining" or "the rest".
