## ADDED Requirements

### Requirement: QA AI Agent MUST follow a seven-screen workflow

The system SHALL implement the new QA AI Agent as a fixed seven-screen journey:
1. `載入需求單`
2. `需求單內容確認`
3. `需求驗證項目分類與填充`
4. `Test Case 種子確認`
5. `Test Case 確認`
6. `Test Case Set 選擇`
7. `確認新增結果`

#### Scenario: User advances through the full journey
- **WHEN** the user completes each screen's required action in order
- **THEN** the system routes the user through all seven screens without falling back to the legacy helper flow

### Requirement: New helper MUST use independent UI and storage

The system SHALL implement the rewritten QA AI Agent as an independent UI flow and independent persistence model, and MUST NOT reuse the legacy helper's session/draft tables as the primary storage for the new workflow.

#### Scenario: New helper persists to dedicated tables
- **WHEN** the user creates or edits session, plan, seed, testcase draft, or telemetry state in the new helper
- **THEN** the system stores that state in dedicated new-helper persistence structures instead of the legacy helper session/draft records

#### Scenario: Legacy helper entry is hidden at rollout
- **WHEN** the new helper is enabled for production use
- **THEN** the user-facing entry for the legacy helper is hidden or removed so users do not operate the old and new flows in parallel by default

#### Scenario: Legacy helper runtime data is purged instead of migrated
- **WHEN** the rewritten helper replaces the previous implementations
- **THEN** the system removes legacy helper session, draft, and telemetry/statistics rows instead of migrating them into the new helper data model

#### Scenario: Rollout purge runs as a controlled migration
- **WHEN** production is prepared for V3 rollout
- **THEN** operators first create a database snapshot, then run a one-time migration that removes legacy helper runtime data instead of relying on startup-time auto cleanup

### Requirement: Requirement lock MUST gate screen-4 seed generation

The system SHALL require the screen-3 requirement plan to be locked before the user can enter or execute screen-4 seed generation.

#### Scenario: Unlocked plan cannot open seed generation
- **WHEN** the user has not locked the requirement plan
- **THEN** the `開始產生 Test Case 種子` action stays disabled

### Requirement: Seed lock MUST gate screen-5 testcase generation

The system SHALL require the current seed set to be locked before the user can execute screen-5 testcase generation.

#### Scenario: Seed changes require relock
- **WHEN** the user adds seed comments, updates existing comments, or changes seed inclusion on screen 4
- **THEN** the system requires the updated seed set to be locked again before `產生 Test Case` becomes available

### Requirement: Screen 6 MUST support existing or new Test Case Set selection

The system SHALL allow the user to either select an existing Test Case Set or create a new Test Case Set on screen 6 before commit is finalized.

#### Scenario: Exactly one target mode is active
- **WHEN** the user is on screen 6
- **THEN** the UI allows either choosing an existing set or entering a new-set form, but not both at the same time

#### Scenario: User creates a new target set
- **WHEN** the user chooses to create a new Test Case Set on screen 6
- **THEN** the helper creates that set and uses it as the commit target for the selected testcase drafts

#### Scenario: New target set requires valid required fields
- **WHEN** the user selects the new-set flow but leaves required fields empty
- **THEN** the commit action stays blocked until the new set payload is valid

### Requirement: Screen 7 MUST summarize commit results and redirect to the target set

The system SHALL show the result of the add operation on screen 7 and SHALL provide redirection to the committed Test Case Set view.

#### Scenario: Commit success opens target set context
- **WHEN** selected testcase drafts are committed successfully
- **THEN** screen 7 shows the added count, failures if any, and navigates to the target Test Case Set screen

#### Scenario: Partial failure still produces a structured result summary
- **WHEN** some selected testcase drafts are committed successfully but others fail
- **THEN** screen 7 shows created, failed, and skipped counts together with per-draft failure reasons and still links to the resolved target set when available

### Requirement: Screen 5 MUST only advance with valid selected testcase drafts

The system SHALL allow progression from screen 5 only when at least one valid testcase draft is explicitly selected for commit.

#### Scenario: Invalid or empty selection blocks screen 6
- **WHEN** the user has no selected testcase drafts, or all selected drafts still fail validation
- **THEN** the flow remains on screen 5 and surfaces the blocking validation state

### Requirement: AI provenance and adoption metrics MUST be queryable

The system SHALL retain enough metadata to identify which seeds and testcases were AI-generated, which were locked or selected by the user, and what their adoption rates are.

#### Scenario: Seed adoption rate is computed from generated versus included seeds
- **WHEN** a seed set is generated and the user explicitly includes only part of it for downstream testcase generation before locking
- **THEN** the system can compute `seed_adoption_rate = included_seed_count / generated_seed_count`

#### Scenario: Testcase adoption rate is computed from generated versus committed selections
- **WHEN** testcase drafts are generated and the user selects only part of them for commit
- **THEN** the system can compute `testcase_adoption_rate = selected_for_commit_count / generated_testcase_count`

#### Scenario: Adoption metrics start fresh from V3 rollout
- **WHEN** V3 is enabled after the previous helper implementations are retired
- **THEN** the system computes adoption metrics only from V3 seed/testcase artifacts and does not incorporate legacy helper statistics

### Requirement: New helper UI MUST follow existing TCRT visual and i18n patterns

The system SHALL implement the new helper UI using the existing TCRT/TestRail frontend patterns, including `base.html` block structure, `--tr-*` and `--btn-*` design tokens, standard card/table/modal class combinations, and the existing i18n retranslate lifecycle.

#### Scenario: New helper page uses existing page skeleton
- **WHEN** the system renders a new helper page or workspace
- **THEN** it extends `base.html` and uses the standard page title, subtitle, actions, content, and scripts blocks instead of introducing a disconnected page shell

#### Scenario: New helper dynamic content remains translatable
- **WHEN** the new helper creates or updates dynamic plan, seed, or testcase nodes
- **THEN** it uses `data-i18n` attributes and triggers `window.i18n.retranslate(...)` so zh-TW, zh-CN, and en-US remain consistent

### Requirement: New helper persistence MUST remain bootstrap- and migration-compatible

The system SHALL manage the new helper tables through Alembic-managed main-database schema and MUST remain compatible with `database_init.py` required-table verification and `scripts/db_cross_migrate.py`.

#### Scenario: Database bootstrap verifies new helper tables
- **WHEN** the system runs `database_init.py` for bootstrap or verify-target checks
- **THEN** the new helper tables are part of the main-database required-table set and are verified alongside other primary application tables

#### Scenario: Cross-database migration copies helper tables without custom handling
- **WHEN** `scripts/db_cross_migrate.py` migrates the main database between SQLite, MySQL, or PostgreSQL targets
- **THEN** the new helper tables use portable schema constructs and row data formats that can be copied without helper-specific post-processing

## REMOVED Requirements

### Requirement: TUI Input Interface
**Reason**: The new workflow is no longer modeled as a generic TUI-style intake with comment toggles and counter-only input.
**Migration**: Use the seven-screen UI journey, screen-1 ticket submission, and screen-3 section numbering controls instead.

### Requirement: Qdrant Similar Test Case Retrieval
**Reason**: Target set selection and AI provenance tracking are part of the requested redesign, but automatic Qdrant retrieval is not.
**Migration**: Keep historical reference support out of the default flow until a separate design explicitly reintroduces it.
