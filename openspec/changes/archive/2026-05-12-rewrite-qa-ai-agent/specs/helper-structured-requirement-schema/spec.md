## ADDED Requirements

### Requirement: Structured requirement MUST follow the preclean-compatible schema

The system SHALL normalize loaded Jira content into a structured payload compatible with `scripts/qa_ai_helper_preclean.py`, including:
- `ticket_markdown`
- `structured_requirement.user_story_narrative`
- `structured_requirement.criteria`
- `structured_requirement.technical_specifications`
- `structured_requirement.acceptance_criteria[]`

#### Scenario: Parser preserves canonical section names
- **WHEN** the parser normalizes a valid Jira ticket
- **THEN** it emits the expected section names and does not rename them into helper-specific aliases

### Requirement: Acceptance Criteria MUST become ordered scenario objects

The system SHALL convert Acceptance Criteria into ordered scenario objects with `scenario_title`, `given[]`, `when[]`, `then[]`, and optional `and[]` clauses for screen-3 section planning.

#### Scenario: Scenario order is preserved
- **WHEN** the ticket contains multiple Acceptance Criteria scenarios
- **THEN** the parser preserves the original scenario order for downstream section numbering and left-panel display

### Requirement: Section display metadata MUST be derived from Acceptance Criteria

The system SHALL derive each screen-3 section's default display name from the Acceptance Criteria scenario title, and SHALL derive the default section identifier from `ticket_key + section number`.

#### Scenario: Scenario title becomes the section title
- **WHEN** the parser outputs `Scenario 1: 資料抓取排程 F5 與 F7 輪流拉取`
- **THEN** screen 3 uses that scenario title as the default section title for the corresponding section

### Requirement: Criteria and Technical Specifications MUST remain readable reference panes

The system SHALL preserve `Criteria` and `Technical Specifications` as read-only supporting context for screen 3, even when the editable area focuses on Acceptance-Criteria-derived sections.

#### Scenario: Supporting sections stay visible during verification editing
- **WHEN** the user edits one section on screen 3
- **THEN** the UI still shows `Criteria` and `Technical Specifications` in a lower reference area without converting them into editable verification items automatically

## MODIFIED Requirements

### Requirement: Requirement-rich planning context MUST be attached to each section

The system SHALL attach requirement-rich context to each section, including:
- `section_id`
- `section_title`
- `scenario_title`
- `given[]`
- `when[]`
- `then[]`
- `criteria_refs[]`
- `technical_refs[]`

#### Scenario: Section context retains requirement references
- **WHEN** the user opens a section on screen 3
- **THEN** the UI can show both the scenario summary and the linked supporting requirement context without reparsing the raw ticket
