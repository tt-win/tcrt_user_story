# Design: Global AI Assistant Session Architecture (v2.0)

## Architecture Overview

1. **Global Conversation Baseline**:
   - `createConversation()` creates conversations with `{ scope_type: 'global' }`.
   - `listRelevantConversations()` retrieves global and historical user conversations.
   - User switching workspace team does not terminate running turns or force-switch sessions.

2. **Target Disambiguation & JIT Casbin Enforcement**:
   - Agent prompts enforce asking clarifying questions if write/delete target team is ambiguous.
   - Tool execution checks user's active Casbin permissions dynamically at execution time.

3. **Frontend Context Snapshotting**:
   - Assistant turns capture `snapshot_team_name` at call time for consistent UI rendering.
