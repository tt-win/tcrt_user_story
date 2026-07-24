# Proposal: Session Manager Modal & Auto-Approve Mode

## Intent
Provide an interactive Session Manager Modal with batch deletion and inline confirmation (replacing native browser alerts), alongside a safety-bounded Auto-Approve Mode for non-destructive AI Assistant actions.

## Scope
- Implement `POST /api/assistant/conversations/batch-delete` backend endpoint for atomic session cleanup.
- Add Auto-Approve toggle in `assistant-widget.js` with hard whitelist boundaries for high-risk tools.
- Add Session Manager Modal in `assistant-widget.js` with search, batch selection, and inline confirmation banner.

## Verification
- `openspec validate session-manager-auto-approve --strict`
- `node --check app/static/js/assistant-widget.js`
- `uv run ruff check app/api/assistant.py`
- `uv run pytest app/testsuite/test_assistant_conversations_api.py -q`
