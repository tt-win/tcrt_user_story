# Data-view state inventory

Change: `establish-data-view-state-contract` · Task 4.1  
Date: 2026-07-30

Reference pattern: `test_case_set_list.html` + `test-case-set-list/main.js` → `showSetsViewState('loading'|'content'|'empty'|'error'|'no-team')` with `#setsErrorRetryBtn` → reload.

Legend: **L** loading · **E** empty · **Err** error (inline) · **R** retry wired

---

## Priority pages (after task 4.2–4.3)

| Page / section | Template | JS | L | E | Err | R | Status |
|---|---|---|---|---|---|---|---|
| Team list | `team_management.html` | `team-management/main.js` | skeleton cards | `#no-teams-section` | `#teams-error-state` | `#teamsErrorRetryBtn` | **FIXED** |
| App Token modal | `components/app_token_modal.html` | `app-tokens.js` | text | text | text | ✗ | **DEFERRED** (modal) |
| Audit log table | `audit_logs.html` | `audit_logs.js` | spinner | `#auditEmptyState` | `#auditErrorState` | `#auditErrorRetryBtn` | **FIXED** |
| Audit team filter | same | same | n/a | n/a | ✗ | ✗ | **DEFERRED** (filter helper) |
| Provider list | `automation_provider_settings.html` | `providers/settings.js` | skeleton table | `#empty-state` | `#provider-error-state` | `#providerErrorRetryBtn` | **FIXED** |
| Provider health modal | same | same | ✓ | n/a | result UI | re-test | **SKIP** |
| Webhook list | `automation_webhook_config.html` | `webhooks/main.js` | skeleton table | `#webhook-empty` | `#webhook-error-state` | `#webhookErrorRetryBtn` | **FIXED** |
| Webhook runs modal | same | same | ✓ | ✓ | ✗ | ✗ | **DEFERRED** (modal) |
| AH Scripts / Tests | `automation_hub.html` | `suites/main.js` | spinner | `#scriptEmpty` | `#scriptError` | `#scriptErrorRetryBtn` | **FIXED** |
| AH Suites | same | same | spinner | `#suiteEmpty` | `#suiteError` | `#suiteErrorRetryBtn` | **FIXED** |
| AH Coverage | same | `coverage/main.js` | spinner | `#coverageEmpty` | `#coverageError` | `#coverageErrorRetryBtn` | **FIXED** |
| AH Settings summaries | same | `suites/main.js` | ✗ | text | ✗ | link | **DEFERRED** (summary cards) |
| AH Environments | same | `environments/settings.js` | ✗ | `#environmentEmpty` | `#environmentError` | `#environmentErrorRetryBtn` | **FIXED** |
| AH Script vars modal | same | `script-vars.js` | ✓ | inline | alert | ✗ | **DEFERRED** (modal) |
| TRM overview | `test_run_management.html` | `data.js` + `render.js` | skeleton cards | `#no-configs-section` | `#trmErrorState` + `#trmNoTeamState` | `#trmErrorRetryBtn` | **FIXED** |
| Ad-hoc runs (in TRM) | same | `data.js` | via parent | add-card | `#adhocErrorState` banner | `#adhocErrorRetryBtn` | **FIXED** |
| TRM set-detail automation runs | same modal | `run-history.js` | ✓ | ✓ | ✗ | ✗ | **DEFERRED** (detail panel) |

---

## Already good / out of scope

| Item | Status | Notes |
|---|---|---|
| `test_case_set_list` | **DONE** (reference) | L/E/Err/no-team + retry |
| `organization-management` user detail prompt | **SKIP** | Pattern source for `empty_state` |
| Dashboard / `index.js` | **OUT OF SCOPE** | Design: `refine-super-admin-dashboard` |

---

## Gaps before fix (historical)

1. **False empty** — catch called empty renderer (`showNoTeams`, `showNoConfigs`, `environments=[]`).
2. **Blank region** — loading hidden, content/empty never shown (providers, webhooks, hub).
3. **Console / toast only** — audit, adhoc.

## Deferred rationale

Modals and secondary panels already show some feedback; full-page blank / false-empty lists were prioritized. Revisit in Browser QA (task 5.3) if blanks remain.

---

## Completion notes (2026-07-30 apply session)

Fixed in this change:
- `/test-case-sets` — skeleton + empty + no-team + error/retry (`showSetsViewState`)
- `/team-management` — error separated from empty + retry
- `/audit-logs` — inline error + retry
- Automation provider / webhook — error state + retry wired
- Automation Hub scripts/suites/coverage/environments — error containers + retry
- `/test-run-management` — `trmErrorState` + adhoc retry
- Selection-dependent actions — `#pm-delete`/`#pm-reset`, batch buttons default disabled
- Native `alert`/`confirm` — zero hits under `app/static/js`

Deferred (documented above): modal secondary panels, dashboard (owned by other change).
