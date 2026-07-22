---
id: count-cases-in-set
name: Count test cases in a team or set
description: Use count_test_cases (and set_id filter) instead of paging entire lists.
triggers:
  - count
  - 數量
  - how many
---

# Count cases

1. Optional resolve set id via `list_test_case_sets`.
2. One `count_test_cases` with filters (query param set_id, priority, etc.).
3. Prefer count over listing thousands of cases.
