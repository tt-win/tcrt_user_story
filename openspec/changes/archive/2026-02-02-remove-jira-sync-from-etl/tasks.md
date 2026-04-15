## Task List

### Phase 1: Remove JIRA-Related Imports and Constants

- [x] 1.1 Remove `JiraClient` import from `app.services.jira_client`
- [x] 1.2 Remove `LarkClient` import from `app.services.lark_client`
- [x] 1.3 Remove `JIRA_BATCH_SIZE` constant (line 37)
- [x] 1.4 Remove `LARK_REFERENCE_TABLE_URL` constant (line 38)
- [x] 1.5 Remove `LARK_REFERENCE_TICKET_FIELD` constant (line 39)
- [x] 1.6 Remove `COLLECTION_NAME_JIRA_REF` constant (line 35)

### Phase 2: Remove JIRA-Related Functions

- [x] 2.1 Remove `parse_lark_table_url()` function (lines 91-109)
- [x] 2.2 Remove `dedupe_preserve_order()` function (lines 111-122)
- [x] 2.3 Remove `flatten_lark_field()` function (lines 124-149)
- [x] 2.4 Remove `extract_tcg_tickets()` function (lines 151-168)
- [x] 2.5 Remove `parse_component_name()` function (lines 170-180)
- [x] 2.6 Remove `normalize_jira_description()` function (lines 182-191)
- [x] 2.7 Remove `extract_adf_text()` function (lines 193-207)
- [x] 2.8 Remove `parse_jira_datetime()` function (lines 209-220)
- [x] 2.9 Remove `fetch_lark_tcg_tickets()` function (lines 222-234)
- [x] 2.10 Remove `build_jira_reference_item()` function (lines 236-273)
- [x] 2.11 Remove `fetch_jira_reference_items()` function (lines 275-305)
- [x] 2.12 Remove `process_jira_reference()` function (lines 307-329)

### Phase 3: Modify Core Functions

- [x] 3.1 Update `init_qdrant()` to remove `COLLECTION_NAME_JIRA_REF` from collection list (line 33)
- [x] 3.2 Update `main()` to remove `process_jira_reference(qdrant)` call (lines 51-55)

### Phase 4: Verification and Testing

- [x] 4.1 Run script and verify no import errors
- [x] 4.2 Verify test cases are still synchronized correctly
- [x] 4.3 Verify USM nodes are still synchronized correctly
- [x] 4.4 Confirm no `jira_references` collection is created in Qdrant
- [x] 4.5 Check that script execution time is reduced
- [x] 4.6 Run lint/type checks if available

### Phase 5: Cleanup

- [x] 5.1 Remove any unused imports that may surface after deletions
- [x] 5.2 Verify code formatting is consistent
- [x] 5.3 Update any documentation references if needed
