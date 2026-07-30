## 1. App Token update timestamp

- [x] 1.1 Implement effective-change detection for scalar, Enum, scope, TCG, and test-data fields in the App Token single Test Case update route
- [x] 1.2 Refresh `updated_at` exactly once inside the same transaction when a persisted value changes, while preserving it for empty, same-value, rejected, and failed updates

## 2. Regression coverage

- [x] 2.1 Extend the existing App Token Test Case update test to verify a content mutation advances `updated_at` and an effective no-op preserves it
- [x] 2.2 Verify through the existing team statistics endpoint that the API-updated case is included in the `Updated` trend for its new update date

## 3. Verification and project records

- [x] 3.1 Run the focused App Token and reporting statistics tests plus strict OpenSpec validation
- [x] 3.2 Run repository Ruff, pytest, frontend lint, and i18n gates; self-review the scoped diff without touching unrelated worktree changes
- [x] 3.3 Incrementally update Graphify for changed relationships and append the required project worklog entry
