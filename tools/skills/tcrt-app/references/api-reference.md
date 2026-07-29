# TCRT App Token API Reference

All paths are relative to `TCRT_BASE_URL`. Every `/api/app/*` request requires
an App Token bearer header. `GET` endpoints require either `test_case:read` or
`test_run:read`; writes require the scope listed below.

## Scopes

| Scope | Grants |
| --- | --- |
| `test_case:write` | Create/update test cases, test data, and attachments |
| `test_case:admin` | Delete test cases, sets, sections, and attachments |
| `test_run:write` | Create/update test run configs/sets, membership, items, reports |
| `test_run:execute` | Update run results and bug tickets |
| `test_run:admin` | Archive Test Run Sets; permanently delete Test Run Configs/Sets/items |
| `automation:execute` | Trigger, cancel, reconcile Test Run Set automation |

## Read endpoints

| Method | Path |
| --- | --- |
| GET | `/api/app/teams` |
| GET | `/api/app/teams/{team_id}/test-cases` |
| GET | `/api/app/teams/{team_id}/test-cases/{case_id}` |
| GET | `/api/app/test-cases/lookup` |
| GET | `/api/app/teams/{team_id}/test-case-sections` |
| GET | `/api/app/teams/{team_id}/test-runs` |
| GET | `/api/app/teams/{team_id}/test-run-configs/{config_id}/items` |

### Test data on read

`GET /api/app/teams/{team_id}/test-cases` and `GET /api/app/test-cases/lookup`
omit `test_data` by default; pass `include_test_data=true` to include it per
case. The single-case detail endpoint always returns it. Each entry keeps
`id`, `name`, `category`
(`text|number|credential|email|url|identifier|date|json|other`), and `value`.
Values of `category=credential` entries are always returned as `[REDACTED]` on
every read and mutation response — the API never emits them in plaintext.

The list endpoint also accepts `assignee`, `tcg`, and `ticket` keyword filters
(`tcg` and `ticket` both match the case's ticket list; giving both matches
either), plus `search`, `priority`, `test_result`, `set_id`, `section_id`,
`include_content`, `skip`, and `limit`. The response echoes every filter back
under `filters`.

### Test case counts

`GET /api/app/teams/{team_id}/test-cases` returns every team Test Case Set in
`sets`. Each `sets[]` item includes `id`, `name`, and the team-wide
`test_case_count` for that set, including `0` for an empty set. `page.total`
is instead the count of cases after the current query filters; use
`set_id=<set-id>` to obtain one set's filtered case-list total. Set summary
counts do not change when `set_id`, search, priority, or result filters are
used.

## Test case endpoints

| Method | Path | Scope | Notes |
| --- | --- | --- | --- |
| POST | `/api/app/teams/{team_id}/test-cases` | `test_case:write` | Create one case |
| PUT | `/api/app/teams/{team_id}/test-cases/{case_id}` | `test_case:write` | Update non-Set fields or a Section in the current Set. Changing Set returns 400; use guarded move. |
| DELETE | `/api/app/teams/{team_id}/test-cases/{case_id}` | `test_case:admin` | |
| POST | `/api/app/teams/{team_id}/test-cases/batch` | `test_case:write` | Batch **create** — body `{"items":[...]}` |
| POST | `/api/app/teams/{team_id}/test-cases/batch-operations` | `delete` → `test_case:admin`; others → `test_case:write` | Batch **operate** — `delete`, `update_priority`, `update_tcg`, same-Set `update_section`. Legacy `update_test_set` parses but returns 400 and points to guarded move. |
| POST | `/api/app/teams/{team_id}/test-cases/impact-preview/move-test-set` | `test_case:write` + `test_run:read` | Preview 1–100 cases; body `{"record_ids":["TC-1"],"target_test_set_id":9}`. Returns canonical ids, impacted Runs, and `impact_fingerprint`. Writes audit only, not business data. |
| POST | `/api/app/teams/{team_id}/test-cases/move-test-set` | `test_case:write` + `test_run:read` | Atomic guarded move; send preview body plus `impact_fingerprint`, and optional `target_section_id` for a single case. Returns `target_test_case_set_id`, ordered `placements[]`, and cleanup summary. |
| POST | `/api/app/teams/{team_id}/test-cases/bulk-clone` | `test_case:write` | Clone cases — body `{"items":[{"source_record_id":"42","test_case_number":"TC-NEW-1","title":"optional"}]}`. Copies title/priority/precondition/steps/expected_result/test_data only; any duplicate new number rejects the whole batch |
| POST | `/api/app/teams/{team_id}/test-cases/{case_id}/attachments` | `test_case:write` | multipart `files` upload |
| GET | `/api/app/teams/{team_id}/test-cases/{case_id}/attachments` | `test_case:read` | |
| DELETE | `/api/app/teams/{team_id}/test-cases/{case_id}/attachments/{target}` | `test_case:admin` | |

### Test case sets and sections

| Method | Path | Scope | Notes |
| --- | --- | --- | --- |
| POST | `/api/app/teams/{team_id}/test-case-sets` | `test_case:admin` | Create set (`name`, `description`) |
| PUT | `/api/app/teams/{team_id}/test-case-sets/{set_id}` | `test_case:admin` | Update set `name`, `description` |
| GET | `/api/app/teams/{team_id}/test-case-sets/{set_id}/impact-preview` | `test_case:admin` | Preview delete impact |
| DELETE | `/api/app/teams/{team_id}/test-case-sets/{set_id}` | `test_case:admin` | Delete set (default set cannot be deleted) |
| POST | `/api/app/teams/{team_id}/test-case-sets/{set_id}/sections` | `test_case:admin` | Create section (`name`, `description`, `parent_section_id`) |
| PUT | `/api/app/teams/{team_id}/test-case-sets/{set_id}/sections/{section_id}` | `test_case:admin` | Update section `name`, `description` |
| DELETE | `/api/app/teams/{team_id}/test-case-sets/{set_id}/sections/{section_id}` | `test_case:admin` | Delete section |

A Test Case Set's own mutable attributes are `name` and `description`, both
updatable via the `PUT` above. Same-Set case movement uses `update_section` with
`update_data.section_id`; cross-Set case movement uses preview then guarded move.
Section-tree cross-Set move/reorder remains unsupported.

## Test run endpoints

A "test run" is a Test Run Config. Create it with a `set_id` to file it under a Test Run
Set immediately, or attach it later with the membership endpoints below.

| Method | Path | Scope | Notes |
| --- | --- | --- | --- |
| POST | `/api/app/teams/{team_id}/test-run-configs` | `test_run:write` | Create a test run. Body may include `set_id`, `name`, `description`, `test_case_set_ids`, `test_version`, `test_environment`, `build_number`, `related_tp_tickets`, `status`, `start_date`, notification fields |
| PUT | `/api/app/teams/{team_id}/test-run-configs/{config_id}` | `test_run:write` | Update `name`, `description`, `test_version`, `test_environment`, `build_number`, `status`, `test_case_set_ids`, `related_tp_tickets` |
| PUT | `/api/app/teams/{team_id}/test-run-configs/{config_id}/status` | `test_run:write` | Lifecycle transition (`{"status":"active"}`): enforces the state machine, sets `start_date`/`end_date`, and recalculates the parent set. Use this to advance draft→active→completed→archived. To archive, send `{"status":"archived"}`; never use DELETE. |
| DELETE | `/api/app/teams/{team_id}/test-run-configs/{config_id}` | `test_run:admin` | Permanently deletes the config and its Test Run Items. Never use to archive. |
| GET | `/api/app/teams/{team_id}/test-run-configs/{config_id}/items` | `test_run:read` | Paginated execution snapshot. Each item only includes `id`, `test_case_number`, `test_result`, `executed_at`, `execution_duration`, `assignee_name`, and `updated_at`. |
| POST | `/api/app/teams/{team_id}/test-run-configs/{config_id}/items` | `test_run:write` | Batch **create** run items (`{"items":[{"test_case_number":"..."}]}`); this is not cross-config move/copy. |
| PUT | `/api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}` | `test_run:execute` | Update result fields or Test Run Item assignee snapshot. |
| POST | `/api/app/teams/{team_id}/test-run-configs/{config_id}/items/batch-update-results` | `test_run:execute` | Batch update results/assignees/comments. Invalid items are reported per-item. |
| DELETE | `/api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}` | `test_run:admin` | |
| POST | `/api/app/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/upload-results` | `test_run:execute` | Upload execution result files (multipart `files`); use the client's `--file` mode |
| GET | `.../test-run-configs/{config_id}/items/{item_id}/bug-tickets` | `test_run:read` | |
| POST | `.../test-run-configs/{config_id}/items/{item_id}/bug-tickets` | `test_run:execute` | `{"ticket_number":"..."}` |
| DELETE | `.../test-run-configs/{config_id}/items/{item_id}/bug-tickets/{ticket_number}` | `test_run:execute` | |

> The plain Test Run `PUT` does not change notification settings or `start_date`/`end_date`. Use
> the `/status` endpoint to advance the lifecycle — it applies the state machine and sets the
> start/end dates. Notifications are set at creation or in the web app.

Test Run Item assignee writes accept exactly one representation: structured
Lark snapshot `{"assignee":{"id":"ou_...","name":"Alice","en_name":null,"email":"alice@example.com"}}`
(`id` or trusted normalized email required), or legacy name-only
`{"assignee_name":"Alice"}`. Clear exactly one representation with `null`.
Do not mix them, infer an id/email from a name, or send `assignee_user_id`.
This contract does not apply to Test Case create/update.

## Test run set endpoints

| Method | Path | Scope | Notes |
| --- | --- | --- | --- |
| POST | `/api/app/teams/{team_id}/test-run-sets` | `test_run:write` | Create set (`name`, `description`, `related_tp_tickets`, `automation_suite_ids`, `default_automation_environment`, `initial_config_ids`) |
| PUT | `/api/app/teams/{team_id}/test-run-sets/{set_id}` | `test_run:write` | Update `name`, `description`, `status`, `related_tp_tickets`, `automation_suite_ids`, `default_automation_environment` |
| POST | `/api/app/teams/{team_id}/test-run-sets/{set_id}/members` | `test_run:write` | Attach only configs verified in `unassigned[]`: `{"config_ids":[12],"expected_memberships":[{"config_id":12,"set_id":null}]}`. |
| POST | `/api/app/teams/{team_id}/test-run-sets/members/batch-move` | `test_run:write` | Atomic explicit move/detach, 1–100 configs. Required `target_set_id` may be null; include one expected membership per config. |
| POST | `/api/app/teams/{team_id}/test-run-sets/members/{config_id}/move` | `test_run:write` | Single move `{"target_set_id":7,"expected_source_set_id":5}`; detach sends an explicit null target. |
| POST | `/api/app/teams/{team_id}/test-run-sets/{set_id}/archive` | `test_run:admin` | Archives only; preserves the set and its runs. |
| DELETE | `/api/app/teams/{team_id}/test-run-sets/{set_id}` | `test_run:admin` | Permanently deletes the set and its runs. Never use to archive. |
| POST | `/api/app/teams/{team_id}/test-run-sets/{set_id}/generate-report` | `test_run:write` | Generate the set HTML report |
| GET | `/api/app/teams/{team_id}/test-run-sets/{set_id}/report` | `test_run:read` or `test_run:write` | Report status |
| POST | `/api/app/teams/{team_id}/test-run-sets/{set_id}/run-automation` | `automation:execute` | Trigger Test Run Set automation |
| POST | `/api/app/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}/cancel` | `automation:execute` | Cancel a non-terminal automation run |
| POST | `/api/app/teams/{team_id}/test-run-sets/{set_id}/runs/{run_id}/reconcile` | `automation:execute` | Reconcile an automation run's status from the provider |

A Test Run Set's mutable attributes (`name`, `description`, `status`, `related_tp_tickets`,
`automation_suite_ids`, `default_automation_environment`) are all updatable via the `PUT` above;
its membership is managed with the attach-only `members`, explicit `batch-move`,
and single `move` endpoints. Read membership before and after with
`GET .../test-runs?include_archived=true`; IDs appear in
`sets[].test_runs[].id` and `unassigned[].id`.

## Pins

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/api/app/teams/{team_id}/pins` | either read scope |
| POST | `/api/app/teams/{team_id}/pins` | `test_case:write` for `test_case_set`; otherwise `test_run:write` |
| DELETE | `/api/app/teams/{team_id}/pins/{entity_type}/{entity_id}` | same as POST |

Pins are team-scoped and shared. POST on an existing pin returns
`already_pinned: true`; DELETE on an absent pin returns `deleted: 0`.

## Read API behavior notes

The six read endpoints (`teams`, `test-cases`, `test-case-detail`, `lookup`,
`test-case-sections`, `test-runs`) share a single implementation in
`app/services/external_read/`.

- **`strict_set`**: unknown `set_id` defaults to ignoring the set filter and
  returning the whole team with `filters.set_not_found = true`. Pass
  `strict_set=true` for a 404.
- **`include_archived`**: test-runs exclude archived sets by default; pass
  `include_archived=true` to include them.
- **lookup filters**: `q` / `test_case_number` / `ticket` are combined with
  AND (intersection), not OR.

## Common error codes

| HTTP | Code | Meaning |
| --- | --- | --- |
| 401 | `APP_TOKEN_REQUIRED` / `APP_TOKEN_INVALID` | Missing, expired, revoked, or invalid token |
| 403 | `APP_TOKEN_TEAM_SCOPE_DENIED` | Requested team is not accessible |
| 403 | `APP_TOKEN_SCOPE_DENIED` | Token lacks the endpoint scope |
| 400 | `APP_TOKEN_VALIDATION_ERROR` | Invalid payload or cross-team reference |
| 404 | `APP_TOKEN_RESOURCE_NOT_FOUND` | Team or resource is absent |
| 409 | `APP_TOKEN_IMPACT_CHANGED` | Guarded case preview is stale; preview and confirm again |
| 409 | `APP_TOKEN_STATE_CHANGED` | Expected membership is stale; read membership again |
| 409 | `APP_TOKEN_INTEGRITY_CONFLICT` | Legacy data has no unique canonical target; stop for repair |
