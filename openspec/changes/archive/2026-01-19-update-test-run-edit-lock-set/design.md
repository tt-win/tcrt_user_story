## Context
The Test Run management UI currently uses a Test Case Set selector in both the configuration form and the case selection modal. After a Test Run is created, re-selecting a set is unnecessary and can cause confusion or mismatches with existing items.

## UX Decisions
- Edit config modal: show the current Test Case Set as read-only text, keeping the hidden set ID unchanged.
- Edit test cases modal: show the current Test Case Set as read-only and lock the selector from changing.
- Create flow remains unchanged and still requires selecting a Test Case Set.

## Data Rules
- The edit UI should display the set name if available; fallback to "Set #<id>" when the name is unknown.
- The underlying set_id remains the same; no updates are allowed through edit flows.
- If the Test Run has no set_id, show the existing warning and block editing.
