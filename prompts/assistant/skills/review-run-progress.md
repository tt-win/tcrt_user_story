---
id: review-run-progress
name: Review test run progress
description: Summarize pass/fail/pending counts then drill into refs if needed.
triggers:
  - progress
  - 進度
  - pass rate
  - 通過率
  - statistics
  - 統計
---

# Review test run progress

## Goal
Report execution status without dumping full item lists.

## Steps
1. `get_run_statistics` for the config (preferred first step).
2. Only if the user needs case numbers: `list_test_run_item_refs` with
   `test_result_filter` (e.g. fail / null) and modest limit; paginate with skip.
3. Do **not** start with `list_test_run_items` full rows.
4. For reassignment or bulk result fixes, hand off to
   `batch-assign-run-items` or `batch_update_test_run_items_by_filter` /
   `batch_update_results`.
