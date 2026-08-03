---
id: latest-test-case
name: Find the latest test case in a team
description: Resolve a named team and retrieve its newest test case by created_at, never by record-id order.
triggers:
  - latest test case
  - newest test case
  - recently created test case
  - 最新建立的 test case
  - 最新測試案例
  - 最近建立的測試案例
---

# Find the latest test case

## Path

1. If the user names a team, call `list_teams` first and use the exact `{id, name}` pair as `target_team` for every team-scoped call. Do not guess an id or reuse the page team.
2. Call `list_test_case_refs` with `target_team`, `sort_by="created_at"`, `sort_order="desc"`, and `limit=1`. Use `list_test_cases` instead when the user explicitly needs the full case content.
3. Treat the first returned item as the newest case because the server sorted by `created_at DESC` with a deterministic id tie-breaker. Never infer recency from record-id order or from the last array item.
4. If the result is empty, state that the team has no matching test cases. Do not invent a result.

## Response

- Identify the team by name.
- Report the test case number, title, and `created_at` when available.
- Include the returned test-case deep link when `_deep_links` is present.
