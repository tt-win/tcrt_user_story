## 1. Contract and red-team closure

- [x] 1.1 Reconcile API, safety, and Agent-UX red-team findings in proposal, design, and delta specs
- [x] 1.2 Complete a second red-team review with no unresolved blocking ambiguity and run strict OpenSpec validation

## 2. Guarded Test Case relocation

- [x] 2.1 Add typed preview/move request and response models, the three stable 409 App Token error codes, canonical record resolution, and full deletion-snapshot impact fingerprint generation
- [x] 2.2 Implement the audited App Token preview endpoint with `test_case:write` plus `test_run:read` scope enforcement
- [x] 2.3 Implement the atomic guarded move endpoint, target root Unassigned helper, optional single target Section, no-op preservation, cleanup summary, and 409 state-change protection
- [x] 2.4 Prevent App Token generic PUT and batch `update_test_set` from bypassing the guarded move workflow
- [x] 2.5 Add a cross-engine config-scope serialization helper and migrate App Token/JWT batch item create, rerun clone, and from-test-cases/generated item creation to lock then revalidate before insert
- [x] 2.6 Add regression tests for scopes, validation, deduplication/limits, same-Set no-op, target Section, cleanup, audit redaction, content-update races, and two-connection create/move interleavings

## 3. Test Run membership integrity

- [x] 3.1 Add typed attach, single move, and batch move models with required nullable targets, expected-membership preconditions, exact summaries, and stable errors
- [x] 3.2 Implement one row-locking relocation core with per-config previous-to-target mappings and exactly-once affected Set recalculation
- [x] 3.3 Migrate every production attach/detach caller: App Token and JWT config create, Set initial members, add-members, single/batch move, rerun clone, generated runs, and config deletion
- [x] 3.4 Enforce unassigned-only `/members`, implement atomic batch move/detach, preserve archived-target compatibility, and add audited recovery mappings
- [x] 3.5 Add regression tests for missing nullable fields, cross-team references, stale preconditions, mixed-source moves, no-ops, detach, concurrent relocation, every migrated caller, and source/target status integrity

## 4. Canonical tcrt-app skill

- [x] 4.1 Add exact `.gitignore` negations and a contract test proving `SKILL.md` plus both references are tracked while real `.env` remains ignored
- [x] 4.2 Rewrite the task index and exact recipes for Test Case Set creation, Section discovery, case batch create/copy/guarded move, and two-step Section forward recovery
- [x] 4.3 Document exact Test Run read-back shape, attach-versus-relocate decision, expected-membership payloads, batch detach, response interpretation, and timeout uncertainty
- [x] 4.4 Document the exact assignee boundary and the unsupported transfer/delete matrix without inventing lookup or move capabilities
- [x] 4.5 Update POSIX, PowerShell, and Python clients to validate origin-only base URLs and emit the stable stderr provenance contract without token disclosure
- [x] 4.6 Update skill contract tests for endpoints, payload keys, safety phrases, unsupported operations, PowerShell-only quoting guidance, and forbidden stale claims

## 5. Documentation and verification

- [x] 5.1 Synchronize `docs/app_token_api_reference.md`, `openspec/project.md`, and other canonical references affected by the new contracts
- [x] 5.2 Run targeted Ruff, focused API/skill tests, script syntax checks, i18n/lint gates when applicable, full-repo Ruff, and full pytest
- [x] 5.3 Run strict OpenSpec validation, self-review the diff for secrets/unrelated changes, and update the Graphify index
