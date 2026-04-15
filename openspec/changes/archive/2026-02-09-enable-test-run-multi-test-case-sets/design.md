## Context

The current Test Run stack has a split responsibility model:
- Test Run config metadata is stored in `test_run_configs`.
- Test Run items are resolved from `test_cases` by `(team_id, test_case_number)`.
- UI flow assumes one current set via `currentSetIdForCaseSelection`.
- Execution page preloads sections from one `testRunConfig.set_id`.

This means:
- The frontend prevents multi-set selection by design.
- The backend does not currently enforce set membership against config scope because config scope is single-set/implicit.
- Execution-side section hydration is incomplete when items span multiple sets.

## Goals / Non-Goals

**Goals:**
- Allow one Test Run to include multiple Test Case Sets.
- Enforce that all configured sets belong to the same team as the Test Run.
- Enforce that Test Run items can only come from configured set IDs.
- Preserve compatibility for existing single-set Test Runs.
- Keep UI and execution filtering behavior coherent when data spans multiple sets.

**Non-Goals:**
- Cross-team Test Run scope.
- Reworking Test Run Set (collection/grouping) semantics.
- Redesigning test case section data model.
- Migrating historical Test Run items between teams.

## Decisions

### 1) Canonical config scope becomes `test_case_set_ids`
- Add a multi-value set scope field on Test Run config (JSON list of integer IDs).
- Keep a transitional single-value compatibility mapping in API responses/requests where needed, but treat list scope as canonical for new behavior.
- Existing records with single-set semantics are interpreted as a one-item list.

Rationale:
- Minimal schema change with additive migration strategy (fits existing `database_init.py` pattern).
- Avoids immediate hard break for existing clients.

### 2) Backend validates team and set scope at write boundaries
- On config create/update:
  - Deduplicate and validate every set ID exists and belongs to `team_id`.
  - Reject empty set list.
- On Test Run item batch create:
  - Resolve each Test Case by team and case number.
  - Reject item if `test_case_set_id` is not in config set list.
- On config update that removes set IDs:
  - Remove existing Test Run items that reference removed set IDs.
- On Test Case Set deletion:
  - Remove existing Test Run items whose source Test Cases belonged to the deleted set.
- On Test Case set reassignment:
  - If a Test Case is moved to a set outside a Test Run scope, remove the corresponding Test Run item from that Test Run.
- Persist cleanup records/audit context so operators can trace why items disappeared.

Rationale:
- Makes integrity enforcement backend-authoritative rather than UI-assumed.
- Prevents hidden data drift from direct API usage.

### 3) Add impact preview endpoints before destructive operations
- Add server-side impact preview APIs for:
  - Deleting a Test Case Set.
  - Moving Test Cases to another Test Case Set.
- Preview result includes impacted Test Runs and per-run affected item counts.
- Write APIs return cleanup summary consistent with preview structure.

Rationale:
- User requirement explicitly asks for warning + visible impacted Test Runs before commit.
- Keeps confirmation logic accurate by using backend-authoritative impact calculations.

### 4) Management UI shifts from single selector to multi-set scope editor
- Config modal allows selecting multiple Test Case Sets.
- Case selection modal supports:
  - Unified list across selected sets.
  - Optional set filter for operator efficiency.
  - Preserving selected cases when switching filter.
- Edit flow no longer hard-locks to one set; it edits allowed set scope with backend validation and receives cleanup outcome when set removal prunes items.

Rationale:
- Aligns product behavior with requested full implementation.
- Keeps user workflow close to current UX while removing single-set constraints.

### 5) Test Case management UI requires explicit confirmation with impact visibility
- For Test Case Set deletion:
  - Confirmation dialog must display impacted Test Runs from preview API.
  - User explicitly confirms after reviewing affected runs.
- For Test Case move across sets (including batch move to another Test Set):
  - Confirmation dialog must display impacted Test Runs from preview API.
  - User can cancel without any data changes.

Rationale:
- Avoid silent cleanup side effects and improve operator trust.
- Matches requested behavior for both trigger paths.

### 6) Execution UI hydrates sections from all configured sets
- If config has multiple set IDs, fetch section trees for all and merge into one display tree/index.
- Keep existing item-based fallback hydration for missing section metadata.

Rationale:
- Maintains section grouping/filter utility without forcing a single-set constraint.

### 7) Search/index support for operational visibility
- Add searchable representation for set scope (similar to existing `tp_tickets_search` pattern) where useful.

Rationale:
- Keeps admin/debug and future query flows practical as scope becomes multi-valued.

## Risks / Trade-offs

- **Risk: Unexpected item disappearance** when set scope or case set changes trigger automatic cleanup.
  - Mitigation: show cleanup result count in API response/UI feedback and keep audit trail.
- **Risk: Impact preview drift** if data changes between preview and submit.
  - Mitigation: recompute impact in write transaction and return final cleanup summary; UI treats preview as estimate.
- **Risk: Heavier frontend state complexity** in case selection modal.
  - Mitigation: keep one canonical selected map by case number and make set filter view-only.
- **Risk: Large move-set selections cause heavy preview payloads.**
  - Mitigation: cap preview list length in UI with count + top-N details, keep full count in API metadata.
- **Risk: Mixed old/new payload usage** during rollout.
  - Mitigation: compatibility mapping plus API tests for both shapes during transition.
- **Trade-off: JSON list instead of normalized relation table**
  - Faster rollout and lower migration cost now, at the expense of relational query ergonomics.
