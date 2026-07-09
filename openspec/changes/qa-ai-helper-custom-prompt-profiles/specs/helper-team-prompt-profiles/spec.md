## MODIFIED Requirements

### Requirement: QA AI Helper MUST NOT expose Team Prompt Profile runtime behavior

QA AI Helper SHALL treat Team Prompt Profile / custom style as a retired capability. Runtime SHALL NOT mount profile management endpoints, SHALL NOT show profile UI controls, and SHALL ignore legacy `prompt_profile_id` inputs during session creation and generation.

#### Scenario: Management endpoints are retired
- **WHEN** client calls `/teams/{team_id}/qa-ai-helper/prompt-profiles`
- **THEN** the route is not found

#### Scenario: Generation ignores legacy profile id
- **WHEN** testcase generation receives `prompt_profile_id`
- **THEN** generation proceeds without profile lookup, prompt injection, snapshot metadata, or profile telemetry
