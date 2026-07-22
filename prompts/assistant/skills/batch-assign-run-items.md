---
id: batch-assign-run-items
name: Batch assign test run items
description: Assign many run items by filter or refs without loading full item rows.
triggers:
  - assign
  - 指派
  - assignee
  - 負責人
  - unassigned
---

# Batch assign test run items

## Goal
Change assignee for many items in one test run with minimal context.

## Steps
1. `get_run_statistics` or `get_test_run` if you need config identity / counts.
2. Prefer **one** of:
   - `batch_update_test_run_items_by_filter` with
     `filter.assignee_unassigned=true` (or other closed filters) and
     `patch.assignee_name="<name>"`
   - OR `list_test_run_item_refs` (filter + limit) then `batch_update_results` with
     `{"id":…,"assignee_name":"…"}` rows only.
3. Never call `list_test_run_items` full projection for bulk assign.
4. Wait for user confirmation on the write tool; do not loop single-item updates.

## Notes
- Filter batch max matched = 500; if rejected, narrow filter or page with refs.
- `test_result: "null"` / `"pending"` means unexecuted items.
