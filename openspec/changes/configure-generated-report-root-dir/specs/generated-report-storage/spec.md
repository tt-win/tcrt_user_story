## ADDED Requirements

### Requirement: Configurable generated report root
The system SHALL allow configuring the root directory for generated HTML reports through `reports.root_dir` in `config.yaml`, and SHALL allow `REPORTS_ROOT_DIR` to override that value at runtime.

#### Scenario: Configured root directory from config file
- **WHEN** `reports.root_dir` is set to a non-empty path in `config.yaml`
- **THEN** generated HTML reports SHALL be written to and read from that configured path

#### Scenario: Environment variable override
- **WHEN** `REPORTS_ROOT_DIR` is set in the environment
- **THEN** the system SHALL use that path instead of the value from `config.yaml`

### Requirement: Default and consistent report storage behavior
The system SHALL default to `<project_root>/generated_report` when no custom report root is configured, and SHALL use the same resolved directory for `/reports` static file serving, report generation, and report existence checks.

#### Scenario: Default root directory
- **WHEN** `reports.root_dir` is empty and `REPORTS_ROOT_DIR` is unset
- **THEN** the system SHALL use the project root `generated_report` directory

#### Scenario: Create missing directories before use
- **WHEN** the resolved report root or its `.tmp` subdirectory does not exist
- **THEN** the system SHALL create the required directories before serving or writing report files
