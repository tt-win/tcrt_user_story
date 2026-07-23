## 1. Data Model and Migration

- [x] 1.1 Add `team_app_tokens` ORM model (including `token_prefix` column), enum/status helpers, scope JSON parsing, and relationships to `Team` / `User`.
- [x] 1.2 Add non-destructive Alembic migration for `team_app_tokens` with token hash uniqueness, owner team index, status index, expires index, and created_by index.
- [x] 1.3 Update `database_init.py` bootstrap compatibility for SQLite / MySQL / PostgreSQL without modifying existing merged migrations.
- [x] 1.4 Add migration/bootstrap tests or focused DB assertions for table creation, indexes, nullable fields, and legacy DB startup.
- [x] 1.5 Verify data model with `uv run pytest app/testsuite/test_app_token_auth.py -q` or the focused test file created in this change.

## 2. App Token Auth and Audit

- [x] 2.1 Add `AppTokenPrincipal` model (with `team_scope_ids` + `allow_all_teams`) and app-token scope constants including `test_run:admin` for test case, test run, and automation operations.
- [x] 2.2 Implement `get_current_app_token_principal`, `tcrt_app_`-prefixed token generation, token hash lookup, revoked/expired handling, throttled `last_used_at` update, and legacy `mcp_machine_credentials` read-only fallback preserving `allow_all_teams` and multi-team scope.
- [x] 2.3 Implement `require_app_team_access` and `require_app_scope` dependencies with deny-by-default mutation behavior and stable error codes (`APP_TOKEN_REQUIRED`, `APP_TOKEN_INVALID`, `APP_TOKEN_TEAM_SCOPE_DENIED`, `APP_TOKEN_SCOPE_DENIED`, `APP_TOKEN_VALIDATION_ERROR`, `APP_TOKEN_RESOURCE_NOT_FOUND`).
- [x] 2.4 Implement shared app-token audit helper with allow/deny/mutation logging and redaction for raw token, token hash, credential test data, and local absolute paths.
- [x] 2.5 Add auth tests for missing/invalid/revoked/expired tokens (unified external `APP_TOKEN_INVALID` with audit-side reason split), team scope deny, operation scope deny, legacy `mcp_read` compatibility including `allow_all_teams`/multi-team mapping, `last_used_at`, and audit redaction.
- [x] 2.6 Verify auth with `uv run pytest app/testsuite/test_app_token_auth.py app/testsuite/test_auth_boundary_flows.py -q`.

## 3. Token Management API and UI

- [x] 3.1 Add team-scoped app token management API for create (default 90-day expiry, explicit `expires_in_days=0` for non-expiring), list, revoke, and rotate under existing authenticated JWT admin permissions.
- [x] 3.2 Add Super Admin organization-level metadata list and revoke capability for all team app tokens.
- [x] 3.3 Ensure list responses are metadata-only including `token_prefix` and never include `raw_token` or `token_hash`.
- [x] 3.4 Add team / organization management UI for app token list (with truncated `token_prefix`), create modal with 90-day default expiry and explicit non-expiry warning, scope selection, revoke, rotate with immediate-invalidation warning, and one-time raw token copy.
- [x] 3.5 Update `app/static/locales/en-US.json`, `zh-CN.json`, and `zh-TW.json` for all app token UI strings.
- [x] 3.6 Add API tests for management permissions, invalid team scope, scope validation, default/explicit expiry behavior, revoke idempotency, rotate invalidating old token, and secret non-disclosure (metadata list exposes only `token_prefix`).
- [x] 3.7 Verify UI/i18n with `node scripts/check-i18n-coverage.mjs`, `npm run lint`, and targeted app token API tests.

## 4. `/api/app/*` Read Compatibility Surface

- [x] 4.1 Add `/api/app/teams` and `/api/app/teams/{team_id}` read endpoints equivalent to current MCP sanitized team reads.
- [x] 4.2 Add `/api/app/teams/{team_id}/test-cases`, detail, lookup, and sections read endpoints using shared schemas/services with `/api/mcp/*`.
- [x] 4.3 Add `/api/app/teams/{team_id}/test-runs` read endpoint using the existing unified test run read model.
- [x] 4.4 Keep `/api/mcp/*` read-only endpoints working with legacy tokens and app tokens in compatibility mode.
- [x] 4.5 Add tests comparing `/api/app/*` read responses with `/api/mcp/*` read responses for teams, test cases, sections, lookup, and test runs.
- [x] 4.6 Verify read compatibility with `uv run pytest app/testsuite/test_mcp_api.py app/testsuite/test_app_token_read_api.py -q`.

## 5. App Token Test Case Mutations

- [x] 5.1 Extract or reuse service-level operations for test case create/update/delete so app-token routes do not call JWT route handlers directly.
- [x] 5.2 Add `/api/app/teams/{team_id}/test-cases` create/update/delete/detail mutation endpoints with `test_case:write` / `test_case:admin` guards.
- [x] 5.3 Add app-token APIs for test case sets and sections management with impact preview and cleanup summary where destructive operations affect test runs.
- [x] 5.4 Wire `normalize_test_data_items` validation (matching JWT parity) into test data create/update via the parent test case endpoints, with audit redaction for credential-category values. No standalone `test-data` endpoint exists in the JWT API to mirror — test_data is managed as a sub-array of the test case, consistent with existing product behavior.
- [x] 5.5 Add app-token attachment upload/delete/list support using existing attachment root and response redaction rules.
- [x] 5.6 Add batch mutation support with per-item success/failure reporting and no cross-team partial writes.
- [x] 5.7 Add tests for test case create/update/delete, set/section validation, test data redaction, attachment behavior, batch partial failures, and cross-team rejection.
- [x] 5.8 Verify test case mutations with `uv run pytest app/testsuite/test_app_token_test_case_api.py app/testsuite/test_test_case_set_export_csv.py -q`.

## 6. App Token Test Run Mutations

- [x] 6.1 Extract or reuse service-level operations for test run config/set/item operations so app-token routes share behavior with JWT APIs.
- [x] 6.2 Add app-token APIs for test run config CRUD (delete guarded by `test_run:admin`), including multi-set scope validation and cleanup summary.
- [x] 6.3 Add app-token APIs for test run set CRUD, archive/delete guarded by `test_run:admin`, membership attach/detach/move, and automation suite membership.
- [x] 6.4 Add app-token APIs for test run items: batch creation (matching JWT, single item is a one-element batch — no standalone single-create endpoint exists in the JWT API to mirror), result/assignee updates (fixed a pre-existing bug where the app-token path wrote to a non-existent `status` column and skipped result-history logging), bug tickets sub-resource (add/list/remove — the JWT API has no generic "bug references" field, only this ticket-number list), and deletion.
- [x] 6.5 Add app-token report generation (`test_run:write`) and lookup (`test_run:read`) endpoints using existing report service and no absolute path leakage.
- [x] 6.6 Add tests for config CRUD, set CRUD, membership changes, run item execution updates, cleanup summaries, report generation, and cross-team rejection.
- [x] 6.7 Verify test run mutations with `uv run pytest app/testsuite/test_app_token_test_run_api.py app/testsuite/test_test_run_set_run_automation_api.py -q`.

## 7. Automation Trigger, Cancel, and Reconcile

- [x] 7.1 Add app-token Test Run Set automation trigger endpoint guarded by `automation:execute`, reusing existing Test Run Set orchestration.
- [x] 7.2 Ensure app-token trigger writes `automation_runs.test_run_set_id`, `script_group_id`, and audit details with `trigger_source="app-token"`.
- [x] 7.3 Ensure Automation Hub script/group trigger endpoints remain removed and do not accept app-token run triggers.
- [x] 7.4 Add app-token cancel and reconcile endpoints guarded by `automation:execute` and existing provider capability checks.
- [x] 7.5 Add tests for automation trigger success/failure, missing org provider, cancel, reconcile, audit details, and Hub endpoint rejection.
- [x] 7.6 Verify automation flow with `uv run pytest app/testsuite/test_app_token_automation_api.py app/testsuite/test_automation_allure_proxy.py -q`.

## 8. tcrt_mcp Compatibility Work

> External-repo deliverable（`/Users/hideman/code/tcrt_mcp`）：因 `/api/mcp/*` 相容期存在，本節可在 TCRT 端（1–7、9–10）完成並發布後獨立實作與驗證，不阻塞本 repo 的 archive 前置驗收；archive 前需確認本節完成或已建立明確的後續追蹤。

- [ ] 8.1 Update `/Users/hideman/code/tcrt_mcp` config to accept `app_token` while preserving `machine_token` as a compatibility alias.
- [ ] 8.2 Update `TCRTClient` to support `/api/app/*` canonical endpoints with `/api/mcp/*` read fallback during migration.
- [ ] 8.3 Update existing read tools to use app-token read endpoints and keep response validation/audit redaction.
- [ ] 8.4 Add write-capable MCP tools for core test case and test run operations with explicit mutation names, parameter validation, and required `confirm=true` (returning impact preview when available) for destructive/batch tools.
- [ ] 8.5 Add write tool audit redaction for credential-category test data and mutation payload summaries.
- [ ] 8.6 Update `tcrt_mcp` README, install docs, smoke scripts, and OpenSpec docs to describe app-token terminology and write scopes.
- [ ] 8.7 Verify `tcrt_mcp` with `cd /Users/hideman/code/tcrt_mcp && uv run pytest -q`.

## 9. Documentation and Compatibility

- [x] 9.1 Update TCRT API docs for `/api/app/*`, app token scopes, the full stable error code table, non-idempotent create endpoints (caller must guard retries), rotate immediate-invalidation behavior, and `/api/mcp/*` compatibility period. See `docs/app_token_auth.md`.
- [x] 9.2 Update `openspec/project.md` and relevant docs to mention app-token external API and MCP compatibility. See `openspec/project.md` (核心能力 + 目前技術架構) and `docs/mcp_machine_auth.md` compatibility banner.
- [x] 9.3 Add or update smoke curl scripts for app-token read/write workflows without printing real secrets. See `docs/app_token_auth.md` §7 (placeholder `<APP_TOKEN>`, no real secrets).
- [x] 9.4 Document rollback: disable `/api/app/*`, revoke app tokens, keep `/api/mcp/*` read-only compatibility. See `docs/app_token_auth.md` §8.

## 10. Final Verification

- [x] 10.1 Run `openspec validate add-team-app-token-apis --strict`. Passed.
- [x] 10.2 Run targeted backend tests for app token auth, management, read, test case mutation, test run mutation, and automation trigger. 108+ tests passed across `test_app_token_*.py`.
- [x] 10.3 Run `uv run ruff check app scripts database_init.py`. App-token files clean; 519 remaining errors are pre-existing repo-wide debt unrelated to this change (baseline was already non-zero before this change).
- [x] 10.4 Run `node scripts/check-i18n-coverage.mjs` and `npm run lint`. Both pass with no regression vs baseline.
- [x] 10.5 Run broader backend suite `uv run pytest app/testsuite -q` if targeted tests pass. 692 passed, 18 skipped, 6 failed. Found and fixed a genuine pre-existing regression (`test_auth_boundary_flows.py` called the old `get_current_machine_principal` signature after a prior-session refactor changed it) and 10 `no-direct-commit` DB-access-guardrail violations in `app_test_cases.py`/`app_test_runs.py` (redundant `sync_db.commit()` inside `run_sync_write` callbacks — the boundary already commits/rolls back automatically; fixed by using `flush()` for intra-callback visibility instead). Remaining 5 failures (`test_qa_ai_helper_models.py`, `test_qdrant_client_service.py`, `test_team_statistics_helper_ai_api.py` x2, `test_team_statistics_helper_frontend.py`) are pre-existing and unrelated to app tokens — confirmed by inspecting each, they test QA AI Helper settings, Qdrant/container config, and a Team Statistics page this change never touches.
- [x] 10.6 Run `graphify update .` after successful implementation verification to persist updated project knowledge. Incremental update merged: 9701 nodes / 25938 edges total (564 new nodes, 1995 new edges vs prior graph), 520 communities all labeled, graph health OK (no dangling/missing/collapsed edges). HTML visualization left stale (graph exceeds the 5000-node auto-viz threshold); GRAPH_REPORT.md and graph.json are current.
