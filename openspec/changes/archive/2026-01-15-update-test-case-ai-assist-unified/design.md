## Context
The current AI assist runs per field (precondition, steps, expected result). This produces inconsistent phrasing and requires separate interactions. The new design unifies evaluation across all fields in a single pass, then presents a comparison UI with live Markdown preview and a single suggestions list.

## UX Goals
- Single action to evaluate all fields together for consistent voice and terminology.
- Clear before/after comparison for each field.
- Live Markdown preview for revised content while editing.
- Allow partial acceptance (apply selected) or full acceptance (apply all).
- Do not block when some fields are empty; keep empty fields unchanged.

## UI / Visual Direction (frontend-design)
- Preserve Bootstrap 5 patterns used in the editor while giving the AI assist modal a distinct, structured feel.
- Use a strong grid layout with clear column headers: Original, Revised, Preview.
- Give each field its own row with subtle background tint and consistent spacing to aid scanning.
- Keep typography aligned with existing UI (no global font changes), but add weight/contrast to section labels for clarity.
- Suggestions panel is a single, full-width block under the comparison grid with lightweight emphasis.

## Layout & Interaction
- Entry point: replace per-field AI assist buttons with one "AI Rewrite" action in the test case editor header area.
- Modal: modal-xl with a three-column comparison grid.
  - Column 1: Original (read-only textareas).
  - Column 2: Revised (editable textareas).
  - Column 3: Preview (live Markdown rendering for revised content).
- Suggestions: one shared list under the grid.
- Controls: "Regenerate", "Apply Selected", "Apply All", "Cancel".
- Selection: per-field checkbox to include/exclude on apply; default all selected.
- Live preview: debounce updates on revised text edits; use the same Markdown renderer as the editor.
- Responsive: on smaller screens, stack columns per field in order Original -> Revised -> Preview; suggestions remain last.

## API & Data Flow
- Request (unified):
  - precondition: string (optional)
  - steps: string (optional)
  - expected_result: string (optional)
  - ui_locale: string (optional)
- Response (unified):
  - revised_precondition: string
  - revised_steps: string
  - revised_expected_result: string
  - suggestions: string[]
  - detected_language: string
- Language detection: infer from concatenated input text; fallback to ui_locale.
- Empty handling: prompt instructs model to keep empty fields empty and never invent content.

## Prompting Rules
- Maintain existing constraints: do not add facts, keep order, no extra headings.
- Apply steps-specific formatting rules only to the steps field.
- Preserve and standardize terminology across all fields in a single response.
- Enforce strict JSON output for parsing.

## Error Handling
- On AI failure or invalid output, show error and do not modify any fields.
- Keep last user edits in the modal intact so they can retry.
