---
id: archive-not-delete
name: Archive is not delete
description: Archive a test run or run set with status/archive tools only; never map archive language to DELETE.
triggers:
  - archive
  - 歸檔
  - 收起來
  - delete
  - 刪除
  - 永久刪除
---

# Archive vs permanent delete

## Archive (reversible intent)

| Resource | Tool | Notes |
| --- | --- | --- |
| Test run (config) | `archive_test_run` or `set_test_run_status` with `archived` | Prefer the dedicated archive tool when available |
| Test run set | `archive_test_run_set` | Not DELETE |

## Permanent delete (only when user is explicit)

Use `delete_test_run_config` / `delete_test_run_set` / `delete_test_case*` **only** when the user says permanent delete / 永久刪除 and names the exact target.

## Disambiguation

If the user says「刪掉 / 移除 / 拿掉」without permanent wording, ask once whether they mean **archive** or **permanent delete** before any write tool.
