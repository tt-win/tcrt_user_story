# test-case-editor-ai-assist Specification

## Purpose
Provide a unified AI assist workflow that evaluates precondition, steps, and expected result together, with clear comparison and live Markdown preview.

## ADDED Requirements
### Requirement: Unified AI assist evaluation
The system SHALL accept precondition, steps, and expected result in a single AI assist request and SHALL return revised text for each field in a single response. The revised output MUST be consistent in tone and terminology across fields.

#### Scenario: Single request returns unified revisions
- **WHEN** the user triggers AI assist with precondition, steps, and expected result
- **THEN** the system returns revised_precondition, revised_steps, and revised_expected_result in one response with consistent wording

### Requirement: Empty field handling
The system SHALL allow empty fields in the unified AI assist request and MUST keep empty fields empty in the response.

#### Scenario: Empty precondition remains empty
- **WHEN** precondition is empty and steps/expected result are provided
- **THEN** the revised_precondition is empty and other fields are revised

### Requirement: Single suggestions list
The system SHALL provide a single suggestions list for the unified response and display it once in the UI.

#### Scenario: Suggestions shown once
- **WHEN** the unified response is displayed
- **THEN** only one suggestions list is shown for all fields

### Requirement: Comparison UI with live Markdown preview
The system SHALL present a unified AI assist UI that shows Original, Revised, and live Markdown Preview for each field in a side-by-side comparison layout.

#### Scenario: Open unified modal
- **WHEN** the user opens the AI assist UI
- **THEN** each field shows original text, revised text, and a live Markdown preview

### Requirement: Live preview updates on edit
The system SHALL update the Markdown preview as the user edits revised text.

#### Scenario: Edit revised steps
- **WHEN** the user edits revised steps in the modal
- **THEN** the preview reflects the changes without leaving the modal

### Requirement: Apply all or selected fields
The system SHALL allow users to apply all revised fields or only selected fields to the editor. Unselected fields MUST remain unchanged.

#### Scenario: Apply selected fields only
- **WHEN** the user applies only the steps field
- **THEN** only steps are updated in the editor and other fields are unchanged

### Requirement: Steps formatting rules
When rewriting steps, the system SHALL use action-led instructions, preserve list numbering, and bold clickable/selectable object text using Markdown **...**.

#### Scenario: Action-oriented step with emphasis
- **WHEN** the input includes a step to click Login
- **THEN** the revised step uses an action verb and bolds "Login"

### Requirement: Language selection
The AI assist service SHALL infer output language from the combined input content; if ambiguous, it SHALL use the current UI locale provided by the client.

#### Scenario: Fallback to UI locale
- **WHEN** the combined input language is ambiguous
- **THEN** the output uses the UI locale language

### Requirement: Failure handling
If AI assist fails or returns invalid output, the system SHALL show an error and MUST NOT change any field content.

#### Scenario: AI service error
- **WHEN** the AI service returns an error
- **THEN** the editor fields remain unchanged and the user receives an error message
