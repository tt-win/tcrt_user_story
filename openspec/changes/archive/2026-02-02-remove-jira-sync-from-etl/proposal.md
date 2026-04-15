## Why

The current ETL script (`ai/etl_all_teams.py`) includes JIRA ticket synchronization functionality that is no longer needed. This functionality adds unnecessary complexity, requires additional dependencies (JiraClient, LarkClient), and increases the execution time of the ETL process. By removing JIRA ticket sync, we can simplify the codebase and focus on the core data synchronization for test cases and user story map nodes.

## What Changes

- **Remove** JIRA ticket synchronization logic from the ETL script
- **Remove** all JIRA-related imports and dependencies (JiraClient, LarkClient)
- **Remove** JIRA-related functions: `process_jira_reference()`, `build_jira_reference_item()`, `fetch_jira_reference_items()`, `fetch_lark_tcg_tickets()`, JIRA-related utility functions
- **Remove** `COLLECTION_NAME_JIRA_REF` constant and associated Qdrant collection creation
- **Remove** JIRA reference data processing from `main()` function
- **Keep** test cases and user story map synchronization intact
- **Simplify** Qdrant collection initialization to only create `test_cases` and `usm_nodes` collections

## Capabilities

### New Capabilities
- None (this is a refactoring/removal change)

### Modified Capabilities
- `etl-all-teams`: Simplify the ETL process by removing JIRA ticket sync while keeping core test case and USM sync functionality

## Impact

**Affected Code:**
- `ai/etl_all_teams.py` - Main ETL script

**Dependencies to Remove:**
- `JiraClient` import from `app.services.jira_client`
- `LarkClient` import from `app.services.lark_client`
- All JIRA-related configuration constants

**Qdrant Collections:**
- Will no longer create or use `jira_references` collection
- `test_cases` and `usm_nodes` collections remain unchanged

**Behavior Changes:**
- ETL script will no longer synchronize JIRA tickets from Lark tables
- Script execution time will be reduced
- Simpler maintenance and debugging
