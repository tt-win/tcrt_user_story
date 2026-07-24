# Design: Session Manager Modal & Auto-Approve Mode (v2.0)

## Architecture Overview

1. **Backend Batch Delete API (`POST /api/assistant/conversations/batch-delete`)**:
   - Accepts `{ "conversation_ids": [int, ...] }`.
   - Stops active tasks and deletes conversations in a single database transaction.

2. **Auto-Approve Mode**:
   - Header toggle switch with state saved in `localStorage`.
   - Bypasses manual confirmation for `READ` or `SAFE_WRITE` actions.
   - Forces manual user confirmation for `HIGH_IMPACT` / `IRREVERSIBLE` / `DESTRUCTIVE` actions.

3. **Session Manager Modal with Inline Confirmation**:
   - Replaces `window.confirm` with custom modal.
   - Includes search input, multi-select checkboxes, select-all, and inline confirmation banner.
