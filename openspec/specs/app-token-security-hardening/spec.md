# app-token-security-hardening Specification

## Purpose
TBD - created by archiving change harden-app-token-security. Update Purpose after archive.
## Requirements
### Requirement: Test case number path safety

The system SHALL reject test case numbers containing path-manipulation characters at the request-model layer, so that no downstream file path (e.g. attachment storage) can be steered outside its intended root.

`test_case_number` on create, update, batch-create, and bulk-clone request models MUST NOT contain `/`, `\`, `..`, or NUL characters. Requests violating this MUST be rejected with HTTP 422 before any persistence or filesystem operation.

#### Scenario: Reject path-traversal test case number on create

- **WHEN** a client calls `POST /api/app/teams/{team_id}/test-cases` with `test_case_number` = `../../../../tmp/evil`
- **THEN** the API returns HTTP 422 and no test case record is created

#### Scenario: Reject path separators on update

- **WHEN** a client calls `PUT /api/app/teams/{team_id}/test-cases/{case_id}` with `test_case_number` containing `/` or `\`
- **THEN** the API returns HTTP 422 and the record is unchanged

#### Scenario: Accept normal test case number

- **WHEN** a client creates a test case with `test_case_number` = `TCG-93178.010.010`
- **THEN** the request succeeds

### Requirement: Attachment write stays within storage root

The system SHALL verify that a computed attachment path resolves within the attachments root directory BEFORE writing file content to disk.

#### Scenario: Containment check precedes write

- **WHEN** an attachment upload computes a stored path that resolves outside the attachments root
- **THEN** no file content is written to disk and the request fails with an error

### Requirement: App token update enforces team ownership of set and section

When an app token updates a test case's `test_case_set_id` or `test_case_section_id`, the system SHALL verify the target set belongs to the request's team and the target section belongs to that set, matching the create path and the interactive (JWT) update path.

#### Scenario: Reject cross-team set assignment

- **WHEN** an app token with `test_case:write` on team A calls `PUT /api/app/teams/{A}/test-cases/{case_id}` with a `test_case_set_id` owned by team B
- **THEN** the API returns HTTP 400 and the test case's set is unchanged

#### Scenario: Reject section not belonging to the target set

- **WHEN** the update body's `test_case_section_id` does not belong to the target `test_case_set_id`
- **THEN** the API returns HTTP 400

### Requirement: Authentication failure rate limiting

The system SHALL apply a per-client-IP rate limit to failed app token and MCP credential authentication attempts on `/api/app/*` and `/api/mcp/*`, short-circuiting before writing the deny-audit entry, so that an unauthenticated source cannot amplify audit writes or database load.

#### Scenario: Excess invalid-token requests are throttled

- **WHEN** a single client IP sends invalid-token requests exceeding the configured per-IP limit within the window
- **THEN** further requests receive HTTP 429 with a `Retry-After` header and do not generate additional deny-audit rows

#### Scenario: Valid authentication is unaffected

- **WHEN** a client authenticates with a valid, active token at normal request rates
- **THEN** requests are not rate limited

### Requirement: Legacy MCP credentials are confined to the MCP namespace

The system SHALL reject legacy MCP machine credentials (principals with `is_legacy = true`) on `/api/app/*` endpoints, confining them to their original `/api/mcp/*` read-only surface. New team app tokens (`is_legacy = false`) are unaffected.

#### Scenario: Legacy credential denied on the app namespace

- **WHEN** a legacy `mcp_read` credential (including one with `allow_all_teams = true`) is presented to any `/api/app/*` endpoint
- **THEN** the API returns HTTP 401 with the opaque `APP_TOKEN_INVALID` code and writes a deny-audit entry

#### Scenario: Legacy credential still works on the MCP namespace

- **WHEN** the same legacy credential is presented to a `/api/mcp/*` read endpoint within its team scope
- **THEN** the request succeeds as before

### Requirement: Audit retention enforcement

The system SHALL enforce audit-log retention by running `cleanup_old_records` on a scheduled interval using the configured `AUDIT_CLEANUP_DAYS`, and SHALL bound the in-memory retry buffer used when audit writes fail so that memory cannot grow without limit.

#### Scenario: Old audit records are pruned on schedule

- **WHEN** the scheduled audit cleanup runs and records exist older than `AUDIT_CLEANUP_DAYS`
- **THEN** those records are removed

#### Scenario: Retry buffer is bounded during audit outage

- **WHEN** audit writes fail repeatedly and the retry buffer reaches its configured maximum size
- **THEN** the oldest queued entries are dropped with a warning and process memory does not grow without bound

### Requirement: App token expiry bounds

`expires_in_days` on app token creation MUST be within a valid range: not negative, and not larger than the configured maximum. Out-of-range values MUST be rejected with HTTP 422.

#### Scenario: Reject negative expiry

- **WHEN** a client creates an app token with `expires_in_days` = `-1`
- **THEN** the API returns HTTP 422

#### Scenario: Reject excessively large expiry

- **WHEN** a client creates an app token with `expires_in_days` exceeding the configured maximum
- **THEN** the API returns HTTP 422 (not a 500)

### Requirement: Attachment deletion does not leak cross-team ownership

App token attachment deletion SHALL scope its lookup by team and return HTTP 404 when the target does not belong to the requesting team, so that a global resource id cannot be used as a cross-team existence oracle.

#### Scenario: Deleting an attachment on a foreign resource returns 404

- **WHEN** an app token for team A attempts to delete an attachment referencing a case id owned by team B
- **THEN** the API returns HTTP 404 without disclosing the owning team

### Requirement: Credential test data is redacted in read responses

Read responses on `/api/app/*` and `/api/mcp/*` SHALL redact test_data entries whose category is `credential`, so that read principals cannot retrieve plaintext credential test data.

#### Scenario: Credential test data is masked on read

- **WHEN** a read principal fetches a test case detail containing a `credential`-category test_data value
- **THEN** the value is returned redacted, not in plaintext

