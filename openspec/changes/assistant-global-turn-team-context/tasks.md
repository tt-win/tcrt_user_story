## 1. Contract and adversarial design

- [x] 1.1 Reproduce page-coupled catalog behavior and trace frontend → turn snapshot → tool filter → prompt remediation
- [x] 1.2 Define page-independent global selector contract (`target_team: {id,name}`)
- [x] 1.3 Split transient read routing from immutable pending mutation target
- [x] 1.4 Run red-team design review covering forged/inaccessible selectors, duplicate names, rename/delete, permission revocation, resource mismatch, prompt injection, replay and mixed-team batches
- [x] 1.5 Incorporate blocking controls: role-only authorization disclosure, selector/resource equality, fail-closed team card, immutable pending target, raw-selector audit, execution-time batch checks and page decoupling

## 2. Schema and persistence

- [ ] 2.1 Add main Alembic migration for pending target id/name/raw selector and journal raw selector; preserve target id across team deletion
- [ ] 2.2 Backfill existing pending targets only from server-generated confirmation summary team id; expire and clear payload when safe backfill is impossible
- [ ] 2.3 Remove `assistant_turns.context_team_id`, old FK and index after backfill
- [ ] 2.4 Update ORM models, pending creation transaction, confirm claim continuation and journal target source
- [ ] 2.5 Verify migration upgrade/downgrade on disposable SQLite and inspect MySQL/PostgreSQL-compatible operations

## 3. Server-resolved target selector

- [ ] 3.1 Add dynamic global team-scoped tool schema with required strict `{id,name}` selector
- [ ] 3.2 Keep team-bound historical tool schemas fixed to conversation team without selector
- [ ] 3.3 Resolve selector against accessible team ids and current DB name with generic fail-closed errors
- [ ] 3.4 Strip selector before path/query/body splitting and loopback transport
- [ ] 3.5 Reorder read/write permission checks to run on the resolved target
- [ ] 3.6 Require resource resolver result to equal selector target for global calls
- [ ] 3.7 Require every batch child target to equal the parent selector
- [ ] 3.8 Persist resolved target in pending and use it for summary/fingerprint/audit

## 4. Global session and capability behavior

- [ ] 4.1 Remove message endpoint `context_team_id` input and turn-start snapshot
- [ ] 4.2 Remove frontend page team from send payload
- [ ] 4.3 Use a single global active-conversation localStorage key and page-independent reload flow
- [ ] 4.4 Make global catalog role-based rather than context-team-based
- [ ] 4.5 Remove `no_team_context` capability reason and workspace-switch remediation
- [ ] 4.6 Update system prompt for cross-team read, explicit mutation disambiguation and exact selector use
- [ ] 4.7 Allow global attachment staging while preserving turn/file ownership checks

## 5. Focused contract tests

- [ ] 5.1 Global no-page-context catalog contains role-authorized team read/write tools
- [ ] 5.2 Selector schema is required only for global team-scoped tools and rejects extra/malformed fields
- [ ] 5.3 Cross-team read from arbitrary page targets exact accessible team and records correct journal team
- [ ] 5.4 Inaccessible, stale-name and duplicate-name selectors fail closed without information leak
- [ ] 5.5 Resource/selector mismatch blocks read and write before transport/pending
- [ ] 5.6 Explicit global write creates pending with immutable target and visible team name
- [ ] 5.7 Confirm ignores page/query target, rechecks permission, and uses pending target for routing/audit
- [ ] 5.8 Rename produces stale confirmation; deletion/permission loss expires action
- [ ] 5.9 Mixed-team batch and prompt-injection selector attempts are rejected
- [ ] 5.10 Widget source/runtime test proves no `context_team_id` and one global conversation key

## 6. Adversarial review and fixes

- [ ] 6.1 Run independent red-team code review against implementation and threat matrix
- [ ] 6.2 Reproduce every high/critical finding and fix source cause
- [ ] 6.3 Run independent adversarial verifier scenarios after fixes
- [ ] 6.4 Confirm no unresolved high-risk uncertainty remains

## 7. Verification and delivery

- [ ] 7.1 Run focused global targeting, capability, confirmation, registry, API and frontend tests
- [ ] 7.2 Run applicable assistant test suites and resolve real regressions
- [ ] 7.3 Run `openspec validate assistant-global-turn-team-context --strict`
- [ ] 7.4 Run `openspec validate global-assistant-session --strict`
- [ ] 7.5 Run Ruff, JavaScript syntax/tests, npm lint and i18n coverage
- [ ] 7.6 Smoke-test: from a page without team context, read one team then another and create/confirm a mutation on the explicitly selected team
- [ ] 7.7 Inspect migration state, final diff and repository status; update completed checkboxes
