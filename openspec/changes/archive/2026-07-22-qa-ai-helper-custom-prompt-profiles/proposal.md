# Change Cancelled: QA AI Helper Custom Prompt Profiles

This change was cancelled after the custom style feature was removed.

## Current Contract

- QA AI Helper no longer exposes Team Prompt Profile / custom style management.
- `/teams/{team_id}/qa-ai-helper/prompt-profiles` endpoints are not mounted.
- Legacy `prompt_profile_id` request fields are ignored by generation flows.
- Prompt rendering strips legacy `{team_style_block}` placeholders and does not inject style guidance.
- Existing database tables/columns may remain as legacy schema until a separately approved destructive migration removes them.

See `openspec/specs/helper-team-prompt-profiles/spec.md` for the retired-capability contract.
