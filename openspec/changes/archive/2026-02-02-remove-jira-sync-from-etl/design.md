## Architecture

The ETL script follows a sequential pipeline architecture:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌─────────────┐
│   Qdrant    │     │    JIRA      │     │    Teams    │     │   Cleanup   │
│  Setup      │────▶│  References  │────▶│  Processing │────▶│    Close    │
│ (init_qdrant)│     │   (REMOVED)  │     │(process_team)│     │   DB Conn   │
└─────────────┘     └──────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       ▼                   ▼                   ▼
  Create TC            REMOVED           For each team:
  USM collections                        1. Test Cases
                                         2. USM Nodes
```

**Key Design Decisions:**

1. **Remove JIRA Sync Stage**: The entire `process_jira_reference()` function call and its logic tree will be removed from the main flow. This eliminates the dependency on LarkClient and JiraClient.

2. **Simplified Qdrant Init**: The `init_qdrant()` function will only create `test_cases` and `usm_nodes` collections, removing `COLLECTION_NAME_JIRA_REF`.

3. **Preserved Team Processing**: The core `process_team()` function remains unchanged, continuing to handle test case and USM node synchronization.

## Key Components

### Modified Components

1. **Import Statements**
   - Remove: `from app.services.jira_client import JiraClient`
   - Remove: `from app.services.lark_client import LarkClient`
   - Remove: JIRA/Lark-related configuration constants (lines 38-39)

2. **Global Constants**
   - Remove: `COLLECTION_NAME_JIRA_REF = "jira_references"`
   - Remove: `JIRA_BATCH_SIZE = 50`
   - Remove: `LARK_REFERENCE_TABLE_URL` and `LARK_REFERENCE_TICKET_FIELD`

3. **Functions to Remove**
   - `parse_lark_table_url()` - Lines 91-109
   - `dedupe_preserve_order()` - Lines 111-122 (unless used elsewhere)
   - `flatten_lark_field()` - Lines 124-149
   - `extract_tcg_tickets()` - Lines 151-168
   - `parse_component_name()` - Lines 170-180
   - `normalize_jira_description()` - Lines 182-191
   - `extract_adf_text()` - Lines 193-207
   - `parse_jira_datetime()` - Lines 209-220
   - `fetch_lark_tcg_tickets()` - Lines 222-234
   - `build_jira_reference_item()` - Lines 236-273
   - `fetch_jira_reference_items()` - Lines 275-305
   - `process_jira_reference()` - Lines 307-329

4. **Modified Functions**
   - `init_qdrant()`: Remove `COLLECTION_NAME_JIRA_REF` from collection list
   - `main()`: Remove call to `process_jira_reference(qdrant)`

### Preserved Components

1. **Core ETL Functions**
   - `get_embeddings()` - Embedding generation via OpenRouter
   - `process_items_in_batches()` - Batch processing logic
   - `process_team()` - Team-level data extraction
   - `main()` - Entry point (minus JIRA call)

2. **Data Classes**
   - `EmbeddingItem` - Data structure for items to be embedded
   - `MockUser` - Mock user for API calls

3. **Core Constants**
   - `COLLECTION_NAME_TC` and `COLLECTION_NAME_USM`
   - `BATCH_SIZE` for batch processing
   - `VECTOR_SIZE` for embeddings
   - OpenRouter configuration

## Data Flow

### Before (Current State)
```
main()
  ├─► init_qdrant() [TC, USM, JIRA_REF]
  ├─► process_jira_reference() [REMOVED]
  │     ├─► parse_lark_table_url()
  │     ├─► fetch_lark_tcg_tickets()
  │     ├─► fetch_jira_reference_items()
  │     │     ├─► JiraClient.search_issues()
  │     │     ├─► build_jira_reference_item()
  │     │     │     ├─► parse_component_name()
  │     │     │     ├─► normalize_jira_description()
  │     │     │     └─► extract_adf_text()
  │     │     └─► parse_jira_datetime()
  │     └─► process_items_in_batches()
  │
  ├─► For each team:
  │     ├─► process_team()
  │           ├─► get_test_cases_context()
  │           ├─► process_items_in_batches() [TC]
  │           ├─► get_usm_context()
  │           └─► process_items_in_batches() [USM]
  │
  └─► Cleanup
```

### After (Target State)
```
main()
  ├─► init_qdrant() [TC, USM] ← Removed JIRA_REF
  │
  ├─► For each team:
  │     ├─► process_team()
  │           ├─► get_test_cases_context()
  │           ├─► process_items_in_batches() [TC]
  │           ├─► get_usm_context()
  │           └─► process_items_in_batches() [USM]
  │
  └─► Cleanup
```

## Error Handling

The existing error handling in `process_team()` will continue to work:
- Individual team processing failures are caught and logged
- Failures do not prevent other teams from being processed
- Database connections are properly closed in `finally` block

## Testing Strategy

1. **Manual Testing**: Run the modified ETL script and verify:
   - Test cases are synchronized correctly
   - USM nodes are synchronized correctly
   - No JIRA-related logs appear
   - Script completes without errors

2. **Verification Steps**:
   - Check Qdrant collections exist: `test_cases`, `usm_nodes`
   - Verify no `jira_references` collection is created
   - Confirm data count matches expected team data
