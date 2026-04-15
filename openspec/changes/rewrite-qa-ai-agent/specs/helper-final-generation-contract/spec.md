## ADDED Requirements

### Requirement: Seed generation MUST use a locked requirement plan and a high-tier model

The system SHALL generate Test Case Seeds from the locked requirement plan on screen 4, and SHALL use a high-tier model for that generation step.

#### Scenario: Locked plan produces the first seed set
- **WHEN** the user clicks `開始產生 Test Case 種子` from a locked screen-3 plan
- **THEN** the system sends the locked sections, verification items, and check conditions to the configured high-tier seed-generation model and persists a seed set

### Requirement: Each seed MUST remain traceable to section and verification-item context

The system SHALL persist each generated seed with references to:
- `section_id`
- `verification_item_id`
- `check_condition_ids[]`
- `coverage categories`

#### Scenario: Seed references its originating verification item
- **WHEN** a generated seed is displayed on screen 4
- **THEN** the UI can show which section and verification item produced that seed

### Requirement: Seed review MUST support per-seed comments and diff-only refinement

The system SHALL allow users to add comments to individual seeds, and SHALL support a refinement action that only sends new or updated comments to the model.

#### Scenario: User comment updates only one affected seed
- **WHEN** the user adds or updates a comment on one seed and triggers refinement
- **THEN** the refinement payload only contains that comment and the target seed context instead of regenerating the full seed set

### Requirement: Seed set MUST support explicit lock before testcase generation

The system SHALL require a locked seed set before screen-5 testcase generation can begin.

#### Scenario: Unlocked seed set blocks testcase generation
- **WHEN** the user tries to generate full testcases from an unlocked seed set
- **THEN** the system blocks progression and requires the user to lock the current seed set first

### Requirement: Seed review MUST support explicit include or exclude decisions for downstream generation

The system SHALL allow users to explicitly decide whether each seed is included in downstream testcase generation so seed adoption can be measured meaningfully.

#### Scenario: Generated seeds default to included
- **WHEN** the initial seed set is created on screen 4
- **THEN** each seed starts with `included_for_testcase_generation = true` until the user excludes it

#### Scenario: Excluded seed is not expanded into a testcase draft
- **WHEN** the user marks one seed as excluded before locking the seed set
- **THEN** that seed is omitted from the screen-5 testcase-generation payload and counts as not adopted

#### Scenario: Included seeds define seed adoption rate
- **WHEN** the user locks a seed set after marking some seeds included and others excluded
- **THEN** the system computes `seed_adoption_rate = included_seed_count / generated_seed_count`

#### Scenario: Section bulk action flips all seeds in that section
- **WHEN** the user chooses a section-level include-all or exclude-all action on screen 4
- **THEN** all seed items in that section update their include state together without changing other sections

### Requirement: Screen 4 MUST not support manual seed creation or deletion

The system SHALL preserve screen-4 seed traceability by disallowing manual seed creation or deletion in V3.

#### Scenario: User cannot manually add or delete a seed
- **WHEN** the user reviews the seed list on screen 4
- **THEN** the UI provides comment editing and include/exclude controls, but does not provide manual add-seed or delete-seed actions

### Requirement: Testcase generation MUST use locked seeds and a lower-tier model

The system SHALL expand locked seeds into full testcase drafts on screen 5 using a lower-tier model than the seed-generation stage by default.

#### Scenario: Locked seeds produce testcase drafts
- **WHEN** the user clicks `產生 Test Case` from a locked seed set
- **THEN** the system sends only the locked seeds that remain included for downstream generation to the configured testcase-generation model and persists testcase drafts for screen 5 review

### Requirement: Model output MUST carry seed references but MUST NOT assign final IDs

The system SHALL require the testcase-generation model to return testcase body fields together with the originating seed reference, and MUST assign final testcase IDs locally after model output is received.

#### Scenario: Model returns reference keys only
- **WHEN** the testcase-generation model responds
- **THEN** the response contains seed or item references for local merge, and the model does not decide the final testcase numbering

### Requirement: Local numbering MUST use section and verification-item block allocation

The system SHALL assign testcase IDs with the pattern `[ticket_key].[section].[tail]`, where:
- section numbers come from screen-3 section allocation
- the first testcase in a section starts tail allocation at `010`
- each subsequent testcase in the same section increments by `10`
- verification items do not create separate numbering blocks

#### Scenario: Later verification items continue the same sequence
- **WHEN** section `TCG-93178.010` has two verification items and the first item uses tails `010` and `020`
- **THEN** the first seed of the second verification item becomes `TCG-93178.010.030`

#### Scenario: Numbering stays sequential across many generated testcases
- **WHEN** a section already has generated testcase tails through `110`
- **THEN** the next testcase tail becomes `120`

### Requirement: Screen 5 MUST support testcase editing and selected-only commit

The system SHALL allow users to edit testcase details on screen 5, and SHALL require users to explicitly mark which testcase drafts will be committed.

#### Scenario: Only body fields are editable
- **WHEN** the user edits one testcase draft on screen 5
- **THEN** the UI allows changes only to `title`, `priority`, `preconditions`, `steps`, and `expected_results`, while testcase ID and seed/reference fields remain read-only

#### Scenario: Drafts start unselected
- **WHEN** testcase drafts are first shown on screen 5
- **THEN** they are not implicitly selected for commit until the user explicitly checks them

#### Scenario: Unselected testcase is excluded from commit
- **WHEN** the user leaves one testcase draft unchecked
- **THEN** that testcase is excluded from the commit payload and counts as not adopted

#### Scenario: Only valid selected drafts enter commit
- **WHEN** the user proceeds from screen 5 to screen 6
- **THEN** the commit payload includes only testcase drafts that are both selected and validation-clean

### Requirement: Screen 5 selection MUST be blocked by validation failures

The system SHALL validate testcase drafts before they can be selected for commit or moved to screen 6.

#### Scenario: Invalid draft cannot be selected
- **WHEN** one testcase draft has an empty title, no steps, or no expected results
- **THEN** that draft cannot be selected for commit until the validation issue is fixed

#### Scenario: No valid selections blocks screen-6 progression
- **WHEN** the user has not selected any valid testcase draft
- **THEN** the flow cannot advance to screen 6

### Requirement: Screen 5 MUST not support manual testcase-draft creation or deletion

The system SHALL preserve traceability by disallowing manual testcase-draft add/delete operations in V3.

#### Scenario: User cannot manually add or delete a testcase draft
- **WHEN** the user reviews testcase drafts on screen 5
- **THEN** the UI provides edit and selection controls only, without manual add-draft or delete-draft actions

### Requirement: Testcase drafts MUST be superseded when the upstream seed set changes

The system SHALL invalidate the current testcase draft set whenever screen-4 seed data changes after testcase generation.

#### Scenario: Seed change invalidates existing testcase drafts
- **WHEN** the seed set is refined, unlocked, or has include/exclude changes after screen-5 drafts were generated
- **THEN** the current testcase draft set becomes superseded and screen 5 requires regeneration from the new locked seed set

### Requirement: Commit execution MUST preserve per-draft outcomes

The system SHALL preserve per-draft commit outcomes so screen 7 can distinguish created, failed, and skipped testcase drafts.

#### Scenario: Partial commit retains per-draft status
- **WHEN** one selected testcase draft is created successfully and another selected testcase draft fails during commit
- **THEN** the system records the created testcase linkage for the successful draft and retains the failed draft result with its error reason for screen-7 reporting

## REMOVED Requirements

### Requirement: Final generation contracts MUST be split by responsibility
**Reason**: The new design still separates responsibilities, but the primary contract boundary is now `seed generation -> seed refinement -> testcase generation -> local numbering/commit`, not the prior internal/model/post-merge structure.
**Migration**: Keep internal traceability data, but express the contract around the two explicit model stages and their lock gates.

### Requirement: Runtime MUST downshift batch size when consistency risk is high
**Reason**: Batch downshifting and complexity scoring are not part of the currently requested redesign.
**Migration**: If batching controls are needed later, they can be reintroduced as an operational enhancement without changing the screen flow.
