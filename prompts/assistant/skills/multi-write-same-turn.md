---
id: multi-write-same-turn
name: Multiple independent writes in one confirmation
description: When the user lists 2–50 fully specified, independent writes, use batch_execute_actions once; never for steps that need a newly created id.
triggers:
  - batch_execute_actions
  - 一次確認
  - 多個動作
  - several actions
---

# Multi-write batching

## Use `batch_execute_actions` when

- The user explicitly wants several writes in one request.
- Every action's arguments are complete **now** (no id produced by an earlier action in the same batch).
- Actions are independent (order still preserved, but failure stops the rest).

## Do NOT use it when

- Step 2 needs the id created by step 1 (create run → add items → report).
- You still need reads to discover targets — do reads first, then one write or one batch.

## Shape

```json
{
  "actions": [
    {"tool_name": "pin_entity", "arguments": {"entity_type": "test_case_set", "entity_id": 3}},
    {"tool_name": "pin_entity", "arguments": {"entity_type": "test_run_set", "entity_id": 5}}
  ]
}
```
