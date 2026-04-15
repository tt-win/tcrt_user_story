## 1. Backend
- [ ] 1.1 Update AI assist request/response models for unified fields and single suggestions list.
- [ ] 1.2 Update prompt builder to accept all fields together and enforce empty-field behavior and consistency.
- [ ] 1.3 Update /ai-assist endpoint to parse unified JSON and return per-field revisions.
- [ ] 1.4 Update language detection to use combined input text with ui_locale fallback.

## 2. Frontend
- [ ] 2.1 Replace per-field AI assist buttons with a single unified entry point.
- [ ] 2.2 Build unified modal layout (Original / Revised / Preview grid) and shared suggestions panel.
- [ ] 2.3 Implement live Markdown preview for revised text inside the modal.
- [ ] 2.4 Implement apply-all and apply-selected with per-field checkboxes and empty-field handling.
- [ ] 2.5 Update API call payload/response handling and error display.
- [ ] 2.6 Add or update i18n strings.

## 3. Styling
- [ ] 3.1 Add CSS for comparison grid, preview panels, and responsive stacking.

## 4. Validation
- [ ] 4.1 Manual: unified assist evaluates all fields once and keeps language consistent.
- [ ] 4.2 Manual: empty fields are allowed and remain unchanged.
- [ ] 4.3 Manual: live Markdown preview updates on edit.
- [ ] 4.4 Manual: apply-all and apply-selected behave correctly.
- [ ] 4.5 Manual: AI failure shows error without changing any field.
