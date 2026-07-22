---
id: assign-run-items-by-case-prefix
name: Assign test run items by case-number prefix
description: Assign some items in a test run (matching a test_case_number / ticket prefix) to one assignee in as few tool calls as possible.
triggers:
  - assign
  - assignee
  - 指派
  - 分配
  - 負責人
  - 前綴
  - prefix
---

# Assign run items by case-number prefix

## Goal

User asks something like:「把 test run X 裡單號以 `ABC-` 開頭的 items 指派給 Alice」。

## Hard rules

1. **Never** loop `update_test_run_item` once per item. Use **one** `batch_update_results` for all matching ids.
2. `batch_update_results` accepts assignee-only updates: each update may be `{"id": <item_id>, "assignee_name": "Alice"}` without `test_result`.
3. Do not change `test_result` unless the user also asked to change results.
4. Prefer `search` on `list_test_run_items` with the prefix string, then **client-filter** with `startswith` (API search is substring, not prefix-only).

## Minimal path

1. Resolve `config_id`
   - If the user already gave a numeric test-run id, use it.
   - Else `list_test_runs` (optional `status_filter`) and match by name; if ambiguous, ask the user.
2. Collect matching item ids
   - Prefer `list_test_run_item_refs` with `config_id`, `search=<prefix>`, `limit=100`, `skip=0` (slim rows).
   - Fall back to `list_test_run_items` only if you need fields refs omit.
   - Keep items whose `test_case_number` **starts with** the prefix (case-sensitive unless user said otherwise).
   - If soft-truncation / limit implies more rows, page with `skip+=limit` until done or you hit the iteration budget.
   - Keep only `id` + `test_case_number` (+ current `assignee_name` if useful). Do not dump full titles into the user reply.
3. If zero matches → tell the user; stop (no write).
4. One write: `batch_update_results` with
   ```json
   {
     "config_id": <config_id>,
     "updates": [
       {"id": 11, "assignee_name": "Alice"},
       {"id": 12, "assignee_name": "Alice"}
     ]
   }
   ```
5. After confirm succeeds, report **count** + a few example case numbers. Do not restate the whole update list.

## Anti-patterns

- Calling `update_test_run_item` N times (burns max_iterations and N confirmations).
- Guessing item ids without listing.
- Putting dependent steps into `batch_execute_actions` when ids come from a prior read in the same turn — reads first, then one batch write is enough.
- Clearing assignee unless user explicitly asks (API accepts empty/null to clear; do not do this by accident).

## Related skills

- `report-test-run-results` — when the user wants results (`pass`/`fail`/…) not just assignee.
- `batch-assign-failed-items` — when the filter is result=`fail` instead of case-number prefix.
