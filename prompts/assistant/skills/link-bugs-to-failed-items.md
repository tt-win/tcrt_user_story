---
id: link-bugs-to-failed-items
name: Link bug tickets to failed run items
description: List failed items then attach bug tickets; batch independent links with batch_execute_actions.
triggers:
  - bug ticket
  - 缺陷
  - link bug
---

# Link bugs to failed items

1. Resolve `config_id`.
2. `list_test_run_items` with fail filter / client filter.
3. For each mapping item_id → ticket from the user:
   - Prefer one `batch_execute_actions` of `add_item_bug_ticket` calls when all args are known.
4. Do not invent ticket numbers or item ids.
