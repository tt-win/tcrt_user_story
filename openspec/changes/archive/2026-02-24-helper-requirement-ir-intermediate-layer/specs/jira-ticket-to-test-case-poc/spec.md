## MODIFIED Requirements

### Requirement: LLM Test Case Generation
The system SHALL use an IR-first multi-stage LLM process to generate comprehensive test cases based on:
- structured `requirement_ir` context
- analysis and coverage outputs with stable ID references
- ticket metadata and configured prompt/model strategy

#### Configuration
- **Model Routing**: Stage-specific models from `config.yaml`
- **Temperature**: Stage-specific values from `config.yaml`
- **Test Case Quantity**: Determined by stage-1 entry count (1:1 mapping)
- **Three-Phase Process**:
  1. **IR Extraction Phase**: LLM normalizes requirement into `requirement_ir`
  2. **Analysis + Coverage Phase**: LLM produces analysis items and coverage seeds with refs
  3. **Generation + Audit Phase**: LLM generates test cases and performs audit correction

#### Scenario: Generate test cases from IR-first workflow
- **GIVEN** requirement IR, analysis output, and coverage output are available
- **WHEN** the system executes generation and audit stages
- **THEN** it returns structured test cases in standard format with deterministic IDs and section mapping context

## ADDED Requirements

### Requirement: Coverage Completeness Validation in Existing Capability
The system SHALL enforce completeness validation so that coverage output references all analysis items before stage-1 entries are finalized.

#### Scenario: Prevent incomplete stage-1 entry creation
- **GIVEN** analysis contains item IDs not referenced by coverage seeds
- **WHEN** the system prepares pre-testcase entries
- **THEN** the system MUST reject direct continuation and perform coverage backfill until missing references are resolved or fail explicitly

### Requirement: Structured Handling for Complex Reference Tables
The system SHALL preserve complex table requirements as structured semantics in IR and SHALL keep traceability into analysis and coverage outputs.

#### Scenario: Keep format/style and interaction semantics from Reference table
- **GIVEN** the ticket has column-level rules such as sortable/fixed/format/style/cross-page mapping
- **WHEN** analysis and coverage are generated
- **THEN** those rules SHALL remain represented as traceable IDs and SHALL NOT be silently dropped during summarization
