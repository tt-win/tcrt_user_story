## Why

The AI Assistant's deep links (clickable markdown links to TCRT pages) only cover team-scoped tools from `add-assistant-deep-links`. Users now primarily call global/knowledge tools (`get_test_case_global`, `search_test_cases_global`, `search_knowledge`) which produce zero `_deep_links`. DB evidence confirms recent `assistant_messages` role=tool rows contain no `_deep_links` field and only use `search_knowledge`, `search_test_cases_global`, `analyze_knowledge_impact`. The system prompt (DB v15) already contains the deep-link requirement section, so the gap is purely implementation.

## What Changes

- Add single-resource deep-link rules for `get_test_case_global` (maps to existing `/test-case-management?set_id={set_id}&tc={tc}` pattern; result dict already has `set_id` and `test_case_number`).
- Add list deep-link rules for `search_test_cases_global` and `search_knowledge` (test_case entities only).
- Extend `build_list_deep_links()` to support `{results: [...]}` envelope alongside existing `list` / `{items: [...]}`.
- Extend `_build_single()` to support dotted paths in `field_map` for nested-field access (`metadata.test_case_set_id`).
- Add optional `entity_type_filter` tuple element to `_LIST_LINK_RULES` so `search_knowledge` only links test_case entities.
- Add `TestCaseLocal.test_case_set_id` (as `set_id`) to `search_test_cases_global` SELECT and result dict so its rows carry the set_id needed for deep-link URL generation.
- Add `{results: [...]}` envelope support to `_struct_compact_tool_content` in history_builder so per-item `_deep_links` survive compaction.
- Update `tools_knowledge.py` summary for `search_test_cases_global` to mention `set_id`.
- No system prompt change (DB v15 already has the rule section).
- No DB schema migration.
- No i18n.
- No frontend change.
- No projection allowlist change needed (injection is post-projection in conversation_service for local tools; `results` list items pass through projection unaltered).

## Capabilities

### New Capabilities

（無新 capability）

### Modified Capabilities

- `assistant-data-boundary`: Clarify that local/in-process tools' `_deep_links` injection happens in conversation_service after `project_and_redact` in tool_executor, so projection allowlist changes are not needed for local tools.
- `assistant-agent-loop`: Add explicit scenarios for deep links on global/knowledge tool results (`get_test_case_global`, `search_test_cases_global` test_case entities, `search_knowledge` test_case entities).

## Impact

- **程式碼**：`app/services/assistant/deep_links.py`（rule tables + results envelope + dotted path + entity_type filter）、`app/services/assistant/tool_executor.py`（search_test_cases_global SELECT add `set_id`）、`app/services/assistant/history_builder.py`（results envelope in compaction）、`app/services/assistant/tools_knowledge.py`（search_test_cases_global summary update `set_id`）。
- **Spec**：`assistant-data-boundary`、`assistant-agent-loop` delta specs。
- **API contract**：無公開 API 變更（search_test_cases_global 為執行模式 local 的工具，結果 dict 僅供 LLM context 使用）。
- **安全**：`_deep_links` 由 server 固定模板產生，ID 經 `int()` / `urllib.parse.quote` 驗證；無新增注入點。
- **資料庫**：無 schema 變更。
- **i18n**：不需要新 UI 文案。
