## ADDED Requirements

### Requirement: Custom CA certificate configuration
The system SHALL allow configuring a custom CA certificate path via `jira.ca_cert_path` in `config.yaml` to be used for Jira TLS verification.

#### Scenario: Custom CA configured
- **WHEN** `jira.ca_cert_path` is configured with a readable certificate path
- **THEN** the Jira client SHALL use that CA for TLS verification and attempt to combine it with the system CA bundle when available

### Requirement: CA bundle fallback behavior
The system SHALL fall back to using the custom CA path directly when it cannot build a combined CA bundle.

#### Scenario: Bundle build fails
- **WHEN** the system CA bundle cannot be combined with the custom CA
- **THEN** the Jira client SHALL still verify TLS using the custom CA path

### Requirement: Default TLS verification
The system SHALL use default TLS verification when `jira.ca_cert_path` is not set.

#### Scenario: No custom CA configured
- **WHEN** `jira.ca_cert_path` is empty or missing
- **THEN** Jira requests SHALL use the default TLS verification behavior
