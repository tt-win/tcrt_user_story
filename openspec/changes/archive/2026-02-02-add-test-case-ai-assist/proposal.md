# Change: Add AI assist for test case editor fields

## Why
Users need fast, consistent help improving test case wording and step clarity without leaving the editor.

## What Changes
- Add an AI assist action to the Precondition, Steps, and Expected Result toolbars.
- Show a preview UI (modal/bubble) with revised text plus a separate Suggestions section.
- Allow users to edit the revised text and re-run AI suggestions from the preview.
- Add a backend API that calls OpenRouter with model openai/gpt-oss-120b:free at temperature 0.1.
- Apply action-oriented steps and bold emphasis for clickable/selectable objects when assisting Steps.
- Select output language based on user input; fall back to UI locale when unclear.

## Impact
- Affected specs: test-case-editor-ai-assist (new)
- Affected code: app/templates/test_case_management.html, frontend JS for markdown toolbars, new API route/service, OpenRouter config usage
