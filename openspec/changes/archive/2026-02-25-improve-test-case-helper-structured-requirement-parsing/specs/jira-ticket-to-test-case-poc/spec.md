## MODIFIED Requirements

### Requirement: LLM Test Case Generation
The system SHALL use a requirement-contract-first multi-stage process to generate comprehensive test cases based on:
- standardized `structured_requirement` context
- structured `requirement_ir` context
- analysis and coverage outputs with stable requirement trace keys
- ticket metadata and configured prompt/model strategy

#### Configuration
- **Model Routing**: Stage-specific models from `config.yaml`
- **Temperature**: Stage-specific values from `config.yaml`
- **Test Case Quantity**: Determined by stage-1 entry count (1:1 mapping)
- **Three-Phase Process**:
  1. **Requirement Contract Phase**: parser/validator produces `structured_requirement` and completeness result
  2. **IR + Analysis + Coverage Phase**: pipeline generates requirement IR, analysis items, and coverage seeds
  3. **Generation + Audit Phase**: pipeline generates testcases and performs audit correction

#### Scenario: Generate test cases from requirement-contract-first workflow
- **WHEN** the system executes helper analyze and generate stages
- **THEN** it returns structured test cases that are traceable to stable requirement keys and requirement-rich pre-testcase context

### Requirement: TUI Display of Generated Test Cases
The system SHALL present pre-testcase and testcase authoring context in a requirement-rich way so users can continue authoring without reopening analysis artifacts.

#### Scenario: Pre-testcase view keeps requirement and verification context
- **WHEN** the user reviews pre-testcase entries before testcase generation
- **THEN** each entry shows requirement summary, specification requirements, verification points, and expected outcomes
- **THEN** analysis/coverage reference tokens are treated as optional trace metadata, not primary presentation content

### Requirement: Existing Helper UI Preservation
The system SHALL preserve existing Test Case Helper UI architecture and interaction assets as the primary baseline, and MUST only introduce minimal UI changes required by the new requirement flow.

#### Scenario: Apply new flow without rebuilding helper UI
- **WHEN** the new requirement validation and warning flow is integrated
- **THEN** the implementation reuses the existing three-step helper modal, interaction patterns, and core components instead of rebuilding the UI from scratch

## ADDED Requirements

### Requirement: Incomplete Requirement Warning on Continuation
The system SHALL warn users before continuation when requirement completeness is insufficient and SHALL support explicit proceed override.

#### Scenario: Proceed with warning in helper flow
- **WHEN** requirement validation result is incomplete and the user clicks continue
- **THEN** the helper flow displays a warning and requires explicit confirmation before analyze starts

### Requirement: Pre-testcase Category Normalization
The system SHALL normalize pre-testcase category semantics to `happy|negative|boundary` for downstream consistency.

#### Scenario: Normalize legacy or non-standard category values
- **WHEN** pre-testcase entries contain non-standard category labels
- **THEN** the system maps them to standard categories while preserving original labels in trace metadata if needed

### Requirement: TCRT UI Style Governance for Necessary UI Changes
The system MUST ensure that any necessary UI modification follows TCRT UI style conventions and existing design language.

#### Scenario: Necessary UI update follows TCRT style guardrails
- **WHEN** a new UI element or visual adjustment is unavoidable for the new flow
- **THEN** the resulting UI follows TCRT style tokens, component conventions, and established page interaction behavior
