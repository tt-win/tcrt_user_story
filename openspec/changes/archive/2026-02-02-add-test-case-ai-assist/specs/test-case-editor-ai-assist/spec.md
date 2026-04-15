# test-case-editor-ai-assist Specification

## Purpose
Provide field-scoped AI assistance for improving test case text with a preview-first workflow, suggestions, and action-oriented steps.

## ADDED Requirements
### Requirement: Field-scoped AI assist actions
The system SHALL provide an AI assist action in the Precondition, Steps, and Expected Result toolbars. The AI assist action MUST operate only on the selected field.

#### Scenario: Assist Steps only
- **WHEN** the user clicks AI assist in the Steps toolbar
- **THEN** the preview UI opens for Steps and no other field content is modified

### Requirement: Preview and refinement workflow
The system SHALL present a preview UI (modal or bubble) containing the revised text and a separate "Suggestions" section shown on the right side of the preview UI. Users MUST be able to edit the revised text and request new suggestions from the preview.

#### Scenario: Edit and regenerate suggestions
- **WHEN** the user edits the revised text and clicks Regenerate
- **THEN** the system re-runs AI assist using the edited content and refreshes revised text and suggestions

#### Scenario: Suggestions appear on the right
- **WHEN** the preview UI opens
- **THEN** the Suggestions section is shown on the right side of the preview UI

### Requirement: Steps formatting rules
When assisting Steps, the system SHALL rewrite steps as action-led instructions and MUST bold clickable/selectable object text using Markdown **...**.

#### Scenario: Action-oriented step with emphasis
- **WHEN** the input includes a step to click Login
- **THEN** the revised step uses an action verb and bolds "Login"

### Requirement: OpenRouter model and temperature
The AI assist service SHALL call OpenRouter Chat Completions with model openai/gpt-oss-120b:free and temperature 0.1. The API key MUST be server-side configuration and MUST NOT be exposed to clients.

#### Scenario: Assist request
- **WHEN** the client requests AI assist
- **THEN** the server uses the configured OpenRouter key and returns structured AI output

### Requirement: Language selection
The AI assist service SHALL infer output language from the input content; if the language cannot be determined, it SHALL use the current UI locale provided by the client.

#### Scenario: Fallback to UI locale
- **WHEN** the input language is ambiguous
- **THEN** the output uses the UI locale language

### Requirement: Failure handling
If AI assist fails or returns invalid output, the system SHALL show an error and MUST NOT change the field content.

#### Scenario: OpenRouter error
- **WHEN** OpenRouter returns an error
- **THEN** the field content remains unchanged and the user receives an error message
