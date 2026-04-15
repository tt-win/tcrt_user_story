## Task List

### Phase 1: Project Setup and Dependencies

- [x] 1.1 Create `ai/jira_to_test_case_poc.py` file structure with shebang and encoding
- [x] 1.2 Add required imports (textual, asyncio, dataclasses, typing, etc.)
- [x] 1.3 Verify `textual` is available in project (add to requirements if needed)
- [x] 1.4 Create basic App class structure extending `App` from textual

### Phase 2: Data Models and JIRA Integration

- [x] 2.1 Create `JiraTicket` dataclass with fields: key, summary, description, components, labels, status
- [x] 2.2 Implement `fetch_jira_ticket(ticket_key: str)` async function using JiraClient
- [x] 2.3 Add ticket key validation (regex pattern: `^[A-Z]+-\d+$`)
- [x] 2.4 Add error handling for JIRA API failures with user-friendly messages

### Phase 3: Qdrant Integration

- [x] 3.1 Implement `get_embeddings(text: str)` function (reuse pattern from etl_all_teams.py)
- [x] 3.2 Create Qdrant client connection setup
- [x] 3.3 Implement `search_similar_test_cases(ticket_description, component, limit=5)` function
- [x] 3.4 Add error handling for Qdrant connection and query failures

### Phase 4: LLM Integration (OpenRouter)

- [x] 4.1 Create prompt template for test case generation
- [x] 4.2 Implement `generate_test_cases(ticket, similar_cases)` async function
- [x] 4.3 Add OpenRouter API call with openrouter/free model
- [x] 4.4 Parse and structure LLM response into test case format
- [x] 4.5 Add retry logic for LLM failures (max 3 retries with exponential backoff)

### Phase 5: TUI Screens

#### Input Screen
- [x] 5.1 Create `InputScreen` class with textual
- [x] 5.2 Add input field for JIRA ticket key with placeholder text
- [x] 5.3 Add submit/enter button
- [x] 5.4 Implement input validation and error display
- [x] 5.5 Add CSS styling for input screen

#### Loading Screen
- [x] 5.6 Create `LoadingScreen` class with progress indicators
- [x] 5.7 Add animated status messages: "Fetching JIRA...", "Querying Qdrant...", "Generating with LLM..."
- [x] 5.8 Implement cancel button (optional for PoC)
- [x] 5.9 Add CSS styling for loading animations

#### Result Screen
- [x] 5.10 Create `ResultScreen` class with markdown display
- [x] 5.11 Add generated test cases display using `Markdown` widget
- [x] 5.12 Add "Copy to Clipboard" button functionality
- [x] 5.13 Add "Regenerate" button to restart the flow
- [x] 5.14 Add "New Ticket" button to go back to input screen
- [x] 5.15 Add CSS styling for result display and buttons

### Phase 6: Main Application Logic

- [x] 6.1 Wire up screen transitions: Input → Loading → Result
- [x] 6.2 Implement async workflow orchestration in main App class
- [x] 6.3 Add global error handler with modal dialog display
- [x] 6.4 Add logging for debugging purposes
- [x] 6.5 Implement proper async cancellation on app exit

### Phase 7: Error Handling and Edge Cases

- [x] 7.1 Handle invalid JIRA ticket format
- [x] 7.2 Handle JIRA ticket not found (404)
- [x] 7.3 Handle JIRA API authentication/permission errors
- [x] 7.4 Handle Qdrant connection failures
- [x] 7.5 Handle Qdrant no results found
- [x] 7.6 Handle OpenRouter API rate limiting
- [x] 7.7 Handle OpenRouter API timeouts
- [x] 7.8 Handle malformed LLM responses

### Phase 8: Testing and Validation

- [x] 8.1 Test with a valid JIRA ticket (manual test)
- [x] 8.2 Test error scenarios (invalid ticket, API failures)
- [x] 8.3 Test UI responsiveness during async operations
- [x] 8.4 Verify test case output format matches specification
- [x] 8.5 Test copy to clipboard functionality
- [x] 8.6 Run script and verify no import errors

### Phase 9: Documentation and Polish

- [x] 9.1 Add module-level docstring explaining the script
- [x] 9.2 Add inline comments for complex logic
- [x] 9.3 Add usage instructions at top of file
- [x] 9.4 Verify code formatting (black/isort if available)
- [x] 9.5 Create simple README section in docstring

### Phase 10: Optional Enhancements (if time permits)

- [x] 10.1 Add configuration file support for settings (timeouts, model selection)
- [x] 10.2 Add history/last used tickets list
- [x] 10.3 Add option to export test cases to file
- [x] 10.4 Add dark/light theme toggle
- [x] 10.5 Add keyboard shortcuts (Ctrl+C to copy, R to regenerate, N for new)
