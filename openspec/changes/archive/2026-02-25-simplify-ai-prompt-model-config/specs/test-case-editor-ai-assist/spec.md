## MODIFIED Requirements

### Requirement: OpenRouter model and temperature

The AI assist service SHALL call OpenRouter Chat Completions using the model configured in `ai.ai_assist.model`, with temperature 0.1. The API key MUST be server-side configuration from `openrouter.api_key` and MUST NOT be exposed to clients.

#### Scenario: Assist request

- **WHEN** the client requests AI assist
- **THEN** the server uses `ai.ai_assist.model` with server-side OpenRouter API key and returns structured AI output

#### Scenario: Legacy openrouter model field is not required

- **WHEN** `openrouter.model` is absent but `ai.ai_assist.model` is configured
- **THEN** AI assist request still succeeds and resolves model from `ai` configuration
