# Proposal: Global AI Assistant Session & Seamless Workspace Navigation

## Intent
Transform AI Assistant conversation sessions from team-isolated workspaces into unified global sessions (`scope_type: 'global'`) while maintaining strict Casbin permissions, disambiguation prompts, and frontend context snapshotting.

## Scope
- Update `assistant-widget.js` to create and list global conversations by default.
- Modify `onTeamChanged` to maintain active conversation across team workspace switching.
- Attach `snapshot_team_name` to assistant turns for unambiguous confirmation card rendering.
- Add disambiguation system prompt rules for ambiguous write/delete instructions.

## Verification
- `openspec validate global-assistant-session --strict`
- `node --check app/static/js/assistant-widget.js`
- `npm run lint`
- `uv run pytest app/testsuite/test_assistant_*.py -q`
