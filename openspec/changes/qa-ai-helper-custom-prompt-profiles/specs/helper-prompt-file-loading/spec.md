## MODIFIED Requirements

### Requirement: Prompt rendering MUST strip retired custom style placeholders

Prompt files and fallback templates SHALL NOT require `{team_style_block}`. If a legacy prompt still contains that placeholder, `render_stage_prompt` SHALL remove it and SHALL ignore any `team_style_block` replacement value.

#### Scenario: Legacy placeholder is stripped
- **WHEN** a prompt template contains `{team_style_block}`
- **THEN** rendered output does not contain the placeholder or custom style guidance

#### Scenario: Replacement cannot inject retired style content
- **WHEN** replacements include `team_style_block`
- **THEN** rendered output ignores that replacement
