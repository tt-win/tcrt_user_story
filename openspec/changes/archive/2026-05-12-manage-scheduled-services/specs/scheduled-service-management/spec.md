## ADDED Requirements

### Requirement: Super Admin can manage scheduled services in organization modal
The system SHALL provide a dedicated scheduled service management tab inside the organization sync management modal, and SHALL expose that tab only to Super Admin users.

#### Scenario: Super Admin sees service management tab
- **WHEN** a Super Admin opens the organization sync management modal
- **THEN** the modal SHALL show a service management tab alongside the existing advanced tabs

#### Scenario: Non-Super-Admin cannot access service management tab
- **WHEN** an admin or regular user opens the organization sync management modal
- **THEN** the UI SHALL hide the service management tab
- **AND** the scheduled service management API SHALL reject access without Super Admin permission

### Requirement: System exposes available schedulable services from backend registry
The system SHALL expose the list of currently schedulable services from the backend, including each service's key, display name, description, supported schedule type, current enablement, configured daily execution time, and runtime status summary.

#### Scenario: Load schedulable services
- **WHEN** the service management tab loads
- **THEN** the frontend SHALL retrieve the list of schedulable services from a backend API
- **AND** each entry SHALL include enough metadata to render service selection and status cards without hardcoded service definitions in frontend code

### Requirement: Super Admin can configure daily scheduled execution time
The system SHALL allow a Super Admin to enable or disable a schedulable service and set a daily execution time for that service.

#### Scenario: Save enabled daily schedule
- **WHEN** a Super Admin enables a service and submits a valid daily execution time
- **THEN** the system SHALL persist that schedule configuration
- **AND** the scheduler SHALL use that configuration to calculate the next execution time

#### Scenario: Disable scheduled service
- **WHEN** a Super Admin disables a previously scheduled service
- **THEN** the system SHALL persist the service as disabled
- **AND** the scheduler SHALL stop auto-triggering that service until it is enabled again

#### Scenario: Reject invalid daily time
- **WHEN** a Super Admin submits an invalid execution time format
- **THEN** the system SHALL reject the request with a validation error

### Requirement: Service management shows current runtime state and last execution result
The system SHALL expose current runtime state and last execution result for each scheduled service so that Super Admin can inspect the service health from the management tab.

#### Scenario: Show current running state
- **WHEN** a scheduled service is currently being executed by the scheduler
- **THEN** the service management tab SHALL show that service as running
- **AND** the backend response SHALL indicate the service is currently in progress

#### Scenario: Show last execution result
- **WHEN** a scheduled service has executed at least once
- **THEN** the service management tab SHALL show the last execution status, timestamps, and latest message or error summary

#### Scenario: Scheduler updates persisted service status after execution
- **WHEN** the scheduler finishes or fails a scheduled service execution
- **THEN** the system SHALL persist the final status, end time, message summary, and next execution time for that service

### Requirement: Scheduler restores persisted schedules on startup
The scheduler SHALL load persisted scheduled service configurations at application startup and seed missing registry-backed services so schedulable services remain manageable across restarts.

#### Scenario: Startup loads existing schedules
- **WHEN** the application starts and persisted scheduled services exist
- **THEN** the scheduler SHALL load those persisted configurations into its in-memory runtime state

#### Scenario: Startup seeds missing service record
- **WHEN** a registry-backed schedulable service has no persisted record yet
- **THEN** the system SHALL create a default disabled scheduled service record for that service

#### Scenario: Startup recovers stale running state
- **WHEN** a persisted scheduled service is marked running from a previous interrupted process
- **THEN** the scheduler SHALL mark that stale execution as interrupted or failed during startup recovery
- **AND** the service SHALL remain manageable with a recalculated next execution time
