---
id: pin-frequent-sets
name: Pin test case sets or run sets
description: Pin frequently used sets with pin_entity; unpin with unpin_entity.
triggers:
  - pin
  - 釘選
  - unpin
---

# Pin / unpin sets

1. Resolve entity id via `list_test_case_sets` or `list_test_run_sets`.
2. `pin_entity` with `entity_type` + `entity_id` (idempotent_write).
3. Unpin with `unpin_entity` when asked to remove a pin.
4. Multiple independent pins → one `batch_execute_actions` if all ids known.

Never invent entity ids.
