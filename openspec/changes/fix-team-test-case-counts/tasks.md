## 1. Backend

- [x] 1.1 Add `_get_team_case_counts(db)` helper in `app/api/mcp.py` (grouped `COUNT(test_case_local.id)` by `team_id`) and use it in `list_teams`.
- [x] 1.2 Use the same helper in `app/api/app_read.py` `list_app_teams`.
- [x] 1.3 In `app/api/teams.py`, pass live counts to `team_db_to_model` for list (grouped map), detail and update (single COUNT), and `0` for create.

## 2. Tests

- [x] 2.1 Extend `app/testsuite/test_mcp_api.py` and `app/testsuite/test_app_token_read_api.py` to assert the teams-list `test_case_count` equals the actual case count.
- [x] 2.2 Run `uv run pytest app/testsuite/test_mcp_api.py app/testsuite/test_app_token_read_api.py -q`.

## 3. Verification

- [x] 3.1 `uv run ruff check app/api/mcp.py app/api/app_read.py app/api/teams.py` (no new F-class errors).
- [x] 3.2 `openspec validate fix-team-test-case-counts --strict`.
