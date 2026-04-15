# Capability: JIRA Ticket to Test Case PoC

## Purpose

提供一個概念驗證（Proof of Concept）工具，讓使用者能夠透過 JIRA Ticket 單號快速生成相關的 Test Cases。此工具整合 JIRA API、Qdrant 向量查詢和 LLM 生成能力，協助 QA 團隊自動化測試情境的產出。

## Requirements

### Requirement: TUI Input Interface

The system SHALL provide a Terminal User Interface (TUI) that allows users to input a JIRA ticket key (e.g., "PROJ-123").

#### Scenario: User enters ticket key
- **GIVEN** the PoC script is running
- **WHEN** the user types a JIRA ticket key into the input field
- **THEN** the system validates the input format (e.g., PROJECT-123)

### Requirement: JIRA Ticket Fetching

The system SHALL automatically fetch ticket details from JIRA API using the provided ticket key.

#### Scenario: Fetch ticket information
- **GIVEN** a valid JIRA ticket key has been entered
- **WHEN** the user confirms the input
- **THEN** the system retrieves: summary, description, components, labels, and status from JIRA

### Requirement: Component Detection

The system SHALL automatically detect and identify the component(s) associated with the JIRA ticket.

#### Scenario: Identify ticket component
- **GIVEN** JIRA ticket details have been fetched
- **WHEN** the system analyzes the ticket
- **THEN** it extracts the primary component for context

### Requirement: Qdrant Similar Test Case Retrieval

The system SHALL query the Qdrant vector database (localhost:6333) to find relevant historical test cases and user story maps based on the ticket description and component.

#### Configuration
- **Qdrant Host**: `localhost:6333`
- **Test Cases Collection**: `test_cases` (70% weight in results)
- **User Story Map Collection**: `usm_nodes` (30% weight in results)

#### Configuration
- **Total Results**: 20 items (test_cases: 14 items (70%), usm_nodes: 6 items (30%))

#### Scenario: Find similar test cases and user stories
- **GIVEN** JIRA ticket details are available
- **WHEN** the system queries Qdrant using the ticket description as search context
- **THEN** it retrieves 20 results total: 14 from test_cases (70%) and 6 from usm_nodes (30%)

### Requirement: LLM Test Case Generation

The system SHALL use OpenRouter API (with openrouter/free model) to generate comprehensive test cases based on:
- JIRA ticket description
- Retrieved similar test cases as reference examples
- Component context

#### Configuration
- **Model**: openrouter/free
- **Temperature**: 0.1
- **Test Case Quantity**: No fixed limit; determined by LLM based on ticket complexity and spec requirements
- **Two-Phase Process**:
  1. **Analysis Phase**: LLM analyzes ticket description and identifies acceptance criteria, assigns middle numbers
  2. **Generation Phase**: LLM generates test cases for each acceptance criteria with appropriate IDs

#### Scenario: Generate test cases
- **GIVEN** ticket details and similar test cases are available
- **WHEN** the system sends a prompt to OpenRouter LLM
- **THEN** it receives structured test cases in the standard format (Preconditions, Steps, Expected Results) with appropriate Test Case IDs

### Requirement: TUI Input for Initial Middle Number

The system SHALL provide an optional input field for users to specify the initial middle number for Test Case ID generation.

#### Scenario: User specifies initial middle number
- **GIVEN** the user is on the input screen
- **WHEN** the user enters an initial middle number (e.g., "010", "020")
- **THEN** the system uses this as the starting middle number; otherwise defaults to "010"

### Requirement: TUI Display of Generated Test Cases

The system SHALL display the generated test cases in a formatted TUI view, including a Test Case ID for each case, allowing the user to:
- View all generated test cases
- Copy test cases to clipboard
- Optionally edit or regenerate test cases

#### Scenario: Display generated results
- **GIVEN** LLM has generated test cases
- **WHEN** the results are received
- **THEN** they are formatted and displayed in the TUI with proper markdown styling

### Requirement: Test Case ID Naming Rules

The system SHALL assign Test Case IDs following the naming rule: `[TCG單號].[中間號].[尾號]`.

#### Rules
- **中間號決定**: 由 LLM 根據 JIRA Description 和 Qdrant 參考資料，分析並識別 Acceptance Criteria 數量，為每個 AC 分配不同的中間號
- **初始中間號**: 可由使用者輸入指定；若未輸入，預設從 `010` 開始
- **中間號遞增**: 不同的 acceptance criteria 使用不同的中間號，以 10 遞增（010, 020, 030...）
- **尾號遞增**: 同一 acceptance criteria 內的多個 test cases，尾號以 10 遞增（010, 020, 030...）

#### Scenario: Generate IDs per acceptance criteria
- **GIVEN** a TCG ticket with multiple acceptance criteria
- **WHEN** test cases are generated
- **THEN** LLM analyzes the description and assigns middle numbers starting from user input (or 010), with tail numbers incrementing by 10 within each AC group

### Requirement: Error Handling

The system SHALL handle errors gracefully, including:
- Invalid JIRA ticket keys
- JIRA API connection failures
- Qdrant query failures
- LLM API errors or timeout

#### Scenario: Handle API errors
- **GIVEN** an external API call fails
- **WHEN** the error occurs
- **THEN** the system displays a user-friendly error message in the TUI without crashing

## Non-Functional Requirements

### Technology Stack
- **TUI Framework**: textual (Python)
- **JIRA Integration**: app.services.jira_client (existing)
- **Vector DB**: qdrant_client (existing Qdrant instance)
- **LLM**: OpenRouter API with openrouter/free model

### Performance
- JIRA API call: < 3 seconds timeout
- Qdrant query: < 2 seconds timeout
- LLM generation: < 30 seconds timeout
- Total flow: < 60 seconds for typical tickets

### Output Format
Generated test cases SHALL follow the standard format:
```
Test Case ID: [TCG-123.010.010]
Test Case Title: [Descriptive title]
Precondition:
- [condition 1]
- [condition 2]

Steps:
1. [Action step 1]
2. [Action step 2]
3. ...

Expected Result:
- [Expected outcome 1]
- [Expected outcome 2]
```
