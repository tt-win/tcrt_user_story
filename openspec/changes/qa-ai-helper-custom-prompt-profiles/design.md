# Design: Cancelled Custom Prompt Profiles

The custom style / Team Prompt Profile design is no longer active.

Runtime behavior now intentionally fails closed:

- No profile CRUD router is mounted.
- Session creation does not resolve team defaults.
- Testcase generation does not resolve, inject, snapshot, or emit profile metadata.
- `QAAIHelperPromptService` removes legacy `{team_style_block}` placeholders and ignores replacement attempts for that key.
- QA AI Helper UI does not render profile controls and does not call retired endpoints.

Database cleanup is intentionally deferred because dropping tables or columns is destructive and requires explicit approval.
