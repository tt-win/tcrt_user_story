## 1. Backend
- [x] 1.1 Define request/response models for AI assist (field, input_text, ui_locale, revised_text, suggestions).
- [x] 1.2 Implement OpenRouter client call with model openai/gpt-oss-120b:free and temperature 0.1.
- [x] 1.3 Add AI assist API endpoint with auth/permission checks and JSON parsing/validation.
- [x] 1.4 Add language detection heuristic with UI locale fallback.

## 2. Frontend
- [x] 2.1 Add AI assist button to Precondition, Steps, Expected Result toolbars.
- [x] 2.2 Add preview modal UI with source input, revised text editor, suggestions list, and action buttons.
- [x] 2.3 Wire JS to call AI assist endpoint, scope to target field, and apply revised text only.
- [x] 2.4 Add i18n strings for button labels, modal text, suggestions, and error messages.

## 3. Validation
- [x] 3.1 Manual: AI assist for each field only updates that field.
- [x] 3.2 Manual: Steps are action-oriented with bold object emphasis.
- [x] 3.3 Manual: language selection follows input content; falls back to UI locale.
- [x] 3.4 Manual: API failure shows error without changing field content.
