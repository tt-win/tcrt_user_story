## ADDED Requirements

### Requirement: Requirement IR Extraction Contract
The system SHALL generate a machine-readable `requirement_ir` JSON artifact before analysis, and SHALL persist it as helper draft phase data for retry and audit.

#### Scenario: Generate IR from Jira requirement source
- **GIVEN** a helper session with fetched Jira ticket content
- **WHEN** analysis flow starts
- **THEN** the system generates `requirement_ir` JSON and stores it in draft phase `requirement_ir`

### Requirement: Table-to-IR Normalization
The system SHALL normalize table-like requirement content into structured IR entities instead of raw markdown tables.

#### Scenario: Convert Reference table into structured entities
- **GIVEN** the ticket description contains a Reference table
- **WHEN** `requirement_ir` is generated
- **THEN** each table row is converted into structured entities with sortable/fixed/format/style/edit-note semantics

### Requirement: IR-first Analysis Input
The system SHALL execute analysis using `requirement_ir` as primary context and SHALL keep traceability to original requirement IDs.

#### Scenario: Analysis references IR entities
- **WHEN** analysis stage is executed
- **THEN** generated analysis items include stable IDs that can be referenced by downstream coverage

### Requirement: Coverage Completeness Gate
The system SHALL validate coverage completeness against analysis items and sections before producing pre-testcase output.

#### Scenario: Coverage missing items triggers backfill
- **GIVEN** coverage output does not reference all analysis item IDs
- **WHEN** server-side completeness validation runs
- **THEN** the system triggers a coverage backfill round and blocks pre-testcase output until missing IDs are resolved

### Requirement: Retry Strategy Priority
The system SHALL prioritize full regeneration over JSON-only repair when coverage output cannot be parsed.

#### Scenario: Coverage parse failure fallback order
- **GIVEN** coverage first-pass output fails JSON parsing
- **WHEN** retry strategy is applied
- **THEN** the system retries full coverage generation first, and only then applies JSON repair as fallback
