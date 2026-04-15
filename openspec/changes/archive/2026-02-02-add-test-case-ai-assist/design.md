## Context
The test case editor uses a markdown toolbar per field (Precondition, Steps, Expected Result). There is no AI assist today. OpenRouter configuration already exists server-side.

## Goals / Non-Goals
- Goals: field-scoped AI assist, preview-first workflow, editable refined text, separate suggestions, language-aware output, no client-side API keys.
- Non-Goals: cross-field rewriting, background auto-editing, or storing suggestions in test case data.

## Decisions
- Decision: Add a server-side AI assist endpoint that calls OpenRouter using existing config (OPENROUTER_API_KEY). The client never sees the key.
- Decision: Use OpenRouter model openai/gpt-oss-120b:free with temperature 0.1 for deterministic output.
- Decision: Require the model to return strict JSON with fields: revised_text (string), suggestions (array of strings), detected_language (string).
- Decision: Determine output language from user input text; if unclear, fall back to the UI locale provided by the client.
- Decision: For Steps, include prompt rules for action-led instructions and Markdown bold emphasis for clickable/selectable object text.
- Decision: Use a Bootstrap modal as the preview UI with a two-column layout: revised text on the left (editable) and a suggestions column on the right (read-only), plus actions to re-run or apply to the target field.
- Decision: Applying changes updates only the target field; suggestions are advisory and not inserted automatically.

## Risks / Trade-offs
- Strict JSON responses can fail; mitigate with validation and clear error messaging without altering user content.
- Language detection is heuristic; allow manual edits and re-suggest from edited input.

## Migration Plan
No data migration. Add new API and UI elements with backward compatibility.

## Open Questions
None.
