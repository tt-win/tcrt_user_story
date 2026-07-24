## Tasks

- [ ] 1. **deep_links.py: Add `get_test_case_global` to `_LINK_RULES`** with `link_key="test_case"`, template `/test-case-management?set_id={set_id}&tc={tc}`, field_map `{"set_id": "set_id", "tc": "test_case_number"}`.
      → verify: unit test `test_get_test_case_global_deep_link` passes

- [ ] 2. **deep_links.py: Add `search_test_cases_global` to `_LIST_LINK_RULES`** with identical field_map (flat keys, no entity_type filter).
      → verify: unit test `test_search_test_cases_global_deep_links` passes

- [ ] 3. **deep_links.py: Add `search_knowledge` to `_LIST_LINK_RULES`** with field_map using dotted keys `{"set_id": "metadata.test_case_set_id", "tc": "metadata.test_case_number"}` and entity_type_filter `{"field": "entity_type", "value": "test_case"}`.
      → verify: unit test `test_search_knowledge_deep_links` passes (test_case entity gets link, usm_node entity does not)

- [ ] 4. **deep_links.py: Add dotted-path support in `_build_single`** — when `field_name` contains `.`, resolve by walking nested dicts. Existing flat field_map entries unaffected.
      → verify: existing unit tests for team-scoped tools still pass; new test for dotted path passes

- [ ] 5. **deep_links.py: Add entity_type_filter support in `build_list_deep_links`** — unpack optional 4th tuple element; skip items not matching `item[filter["field"]] == filter["value"]`.
      → verify: unit test confirms non-test_case items in search_knowledge are skipped

- [ ] 6. **deep_links.py: Add `{results: [...]}` envelope support in `build_list_deep_links`** — add `elif isinstance(result_payload, dict) and isinstance(result_payload.get("results"), list): items = result_payload["results"]`.
      → verify: unit test with `{"status": "success", "results": [...]}` payload injects per-item `_deep_links`

- [ ] 7. **tool_executor.py: Add `set_id` to `search_test_cases_global` SQL SELECT** — add `TestCaseLocal.test_case_set_id` to column list (line ~1007).
      → verify: code review confirms column added; integration test checks result dict has `set_id`

- [ ] 8. **tool_executor.py: Add `set_id` to `search_test_cases_global` result row dict** — add `"set_id": r.test_case_set_id` to each row (line ~1030-1038).
      → verify: unit test with fake rows verifies `set_id` in each result item

- [ ] 9. **tools_knowledge.py: Update `search_test_cases_global` summary** — change "Returns slim rows (number, title, priority, team_name, set_name)" to include `set_id`.
      → verify: `uv run ruff check` passes

- [ ] 10. **history_builder.py: Add `{results: [...]}` envelope branch to `_struct_compact_tool_content`** — mirror the `{items: [...]}` branch using `results` key. `_sample_deep_links_from_list` works unchanged.
       → verify: unit test with compacted `results` envelope preserves `_deep_links` sample

- [ ] 11. **New test file or extend existing**: Add tests in `app/testsuite/test_assistant_deep_links.py`:
       - `test_get_test_case_global_deep_link` — single-resource rule works
       - `test_search_test_cases_global_deep_links` — results envelope, per-item injection
       - `test_search_knowledge_deep_links` — dotted metadata path, entity_type filter
       - `test_search_knowledge_skips_non_test_case` — usm_node/jira_ticket items get no link
       - `test_results_envelope_in_build_list_deep_links` — verifies `results` key support
       - `test_dotted_path_resolution` — verifies `_resolve_field` helper
       - `test_set_id_missing_returns_no_link` — null set_id skipped
       - `test_history_compaction_preserves_results_deep_links` — compaction branch
       → verify: `uv run pytest app/testsuite/test_assistant_deep_links.py -q` passes with new tests

- [ ] 12. **Verify**: `uv run ruff check app/services/assistant/deep_links.py app/services/assistant/history_builder.py app/services/assistant/tool_executor.py app/services/assistant/tools_knowledge.py`
       → verify: no new warnings

- [ ] 13. **Verify**: `openspec validate extend-assistant-deep-links-global --strict`
       → verify: passes with 0 errors

- [ ] 14. **Verify**: `uv run pytest app/testsuite/test_assistant_deep_links.py -q`
       → verify: all existing and new tests pass
