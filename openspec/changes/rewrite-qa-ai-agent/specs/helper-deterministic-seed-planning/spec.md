## ADDED Requirements

### Requirement: Section planning MUST run locally without LLM dependency

The system SHALL build screen-3 sections, verification items, and lockable requirement-plan data with deterministic local code, and MUST NOT require an LLM call before seed generation starts.

#### Scenario: Local planning payload is produced from parser output
- **WHEN** screen 2 validation passes
- **THEN** the system locally prepares the section list and verification workspace payload for screen 3 without invoking a model

### Requirement: Acceptance Criteria MUST drive section allocation

The system SHALL use Acceptance Criteria scenarios as the primary section boundaries for screen 3, and SHALL assign section IDs using `ticket_key + editable start number + 10-step increments`.

#### Scenario: User edits the starting section number
- **WHEN** the user changes the section start value from `010` to `030`
- **THEN** the system reassigns the first section to `ticket_key.030` and increments subsequent sections by `10`

### Requirement: Verification items MUST use one of four categories

The system SHALL allow each section to contain one or more verification items, and each item MUST use one of these categories:
- `API`
- `UI`
- `功能驗證`
- `其他`

#### Scenario: API verification item stores endpoint detail
- **WHEN** the user creates an `API` verification item
- **THEN** the item captures the API URL field and may leave that field blank if the endpoint is not yet known

#### Scenario: UI verification item stores page context
- **WHEN** the user creates a `UI` verification item
- **THEN** the item captures the page, field, button, or equivalent UI context being verified

#### Scenario: Functional verification item stores feature intent
- **WHEN** the user creates a `功能驗證` verification item
- **THEN** the item captures the feature behavior being verified, such as create, delete, sort, or schedule behavior

#### Scenario: Other verification item stores free-form definition
- **WHEN** the user creates an `其他` verification item
- **THEN** the item stores a user-defined description without forcing it into API, UI, or feature-specific fields

### Requirement: Each verification item MUST contain one or more check conditions

The system SHALL require at least one check condition under every verification item.

Each check condition MUST contain:
- natural-language condition text
- one coverage category:
  - `Happy Path`
  - `Error Handling`
  - `Edge Test Case`
  - `Permission`

#### Scenario: Check condition cannot be saved without coverage
- **WHEN** the user adds a check condition but leaves coverage empty
- **THEN** the system blocks save for that condition and surfaces the missing coverage requirement

### Requirement: Requirement-plan editing MUST autosave every five seconds

The system SHALL autosave screen-3 edits at least every five seconds, and SHALL also provide a manual `儲存` action.

#### Scenario: Autosave persists current section edits
- **WHEN** the user continues editing verification items on screen 3
- **THEN** the system persists the current plan snapshot within five seconds without requiring a full-screen submit

### Requirement: Requirement plan MUST support explicit lock and unlock

The system SHALL require a locked requirement plan before seed generation, and SHALL disable seed generation again if the plan is unlocked.

#### Scenario: Locked requirement plan enables seed generation
- **WHEN** the user clicks `鎖定需求`
- **THEN** the current plan snapshot becomes locked and the `開始產生 Test Case 種子` action becomes available

#### Scenario: Unlock disables seed generation
- **WHEN** the user clicks `解開鎖定`
- **THEN** the current plan becomes editable again and the `開始產生 Test Case 種子` action becomes disabled until the plan is locked again

## REMOVED Requirements

### Requirement: Seed coverage taxonomy MUST include four baseline categories
**Reason**: The new design no longer generates seeds locally; coverage taxonomy now governs screen-3 check conditions, but V3 no longer uses those tags to generate automatic screen-4 suggestions.
**Migration**: Keep coverage tags as part of screen-3 requirement structure only; screen-4 refinement is driven by per-seed comments instead of derived suggestion candidates.

### Requirement: Planner MUST expand explicit requirement combinations into a verification matrix
**Reason**: The new workflow relies on user-authored verification items and check conditions, not an automatically expanded verification matrix.
**Migration**: If combination expansion is needed later, it should be modeled as a future enhancement to refinement or planning, not as the current primary planner output.
