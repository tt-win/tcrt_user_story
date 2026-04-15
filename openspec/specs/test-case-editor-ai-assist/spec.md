# test-case-editor-ai-assist Specification

## Purpose

Provide AI assist capability for improving test case text with a unified preview-first workflow, while allowing UI exposure to be controlled for phased rollout.

## Requirements

### Requirement: Field-scoped AI assist actions

The system SHALL NOT display an AI assist action in the Precondition, Steps, and Expected Result toolbars in the standard test case editor UI. The AI assist capability MUST remain available in backend services without contract removal.

#### Scenario: Toolbar AI actions are not visible

- **WHEN** 使用者開啟 Test Case 編輯器 / user opens the test case editor
- **THEN** Precondition、Steps、Expected Result 區域皆不顯示 AI assist action button

#### Scenario: Backend capability remains intact

- **WHEN** 維護者使用既有 API contract 呼叫 AI assist endpoint / maintainer calls AI assist endpoint with existing contract
- **THEN** 服務仍回傳結構化改寫結果或既有錯誤格式，且不需 API schema migration

### Requirement: UI-hidden trigger policy

The system SHALL enforce a UI-hidden policy for AI assist in normal editor flow, and SHALL prevent direct user-trigger paths from visible controls.

#### Scenario: No direct UI trigger in normal flow

- **WHEN** 使用者在一般編輯流程檢視頁首、欄位工具列與常用操作區 / user checks editor header, field toolbars, and common action areas
- **THEN** 不存在可直接開啟 AI assist modal 的可見控制元件

### Requirement: Re-enable readiness without service rewrite

The system SHALL allow future re-enable of AI assist UI by frontend-level changes, and SHALL NOT require rewriting backend AI assist logic for that re-enable.

#### Scenario: Future UI re-enable path

- **WHEN** 團隊決定重新開放 AI 改寫 UI / team decides to re-enable AI rewrite UI
- **THEN** 可透過前端入口調整恢復能力，並沿用既有 API 與 prompt pipeline

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

The AI assist service SHALL call OpenRouter Chat Completions using the model configured in `ai.ai_assist.model`, with temperature 0.1. The API key MUST be server-side configuration from `openrouter.api_key` and MUST NOT be exposed to clients.

#### Scenario: Assist request

- **WHEN** the client requests AI assist
- **THEN** the server uses `ai.ai_assist.model` with server-side OpenRouter API key and returns structured AI output

#### Scenario: Legacy openrouter model field is not required

- **WHEN** `openrouter.model` is absent but `ai.ai_assist.model` is configured
- **THEN** AI assist request still succeeds and resolves model from `ai` configuration

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
