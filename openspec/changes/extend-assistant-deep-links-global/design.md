## Context

`app/services/assistant/deep_links.py` defines `_LINK_RULES` (single-resource), `_ARGS_LINK_RULES` (args-source), and `_LIST_LINK_RULES` (list). `build_deep_links()` / `build_list_deep_links()` are called by `conversation_service.py` (lines 703-707 for read path, lines 1544-1550 for confirm path) AFTER `project_and_redact()` has already run on the tool result payload.

The existing rule tables only cover team-scoped tools from `add-assistant-deep-links`. Three global/knowledge tools are called by users but produce no `_deep_links`:

| Tool | execution_mode | Result envelope | Fields present for deep link |
|------|---------------|-----------------|------------------------------|
| `get_test_case_global` | local | flat dict | `set_id`, `test_case_number` (both already in result) |
| `search_test_cases_global` | local | `{results: [...]}` | Rows MISSING `set_id` (not selected by SQL). Need to add. |
| `search_knowledge` | local | `{results: [...]}` | test_case entities have IDs in `metadata.test_case_set_id`, `metadata.test_case_number`. Other entity types skipped. |

`analyze_knowledge_impact` returns a dependency graph with no single-navigable resource page; excluded from scope.

Injection timing: `project_and_redact` runs on the local tool result inside `tool_executor.run_read_tool` (line 1158), THEN the result is returned to `conversation_service.append_tool_call_and_result` where `_deep_links` is injected (lines 703-707) before `json.dumps`. For local tools, `apply_projection` acts as a top-level-key filter (`results` is in the allowlist so the `results` list and its items pass through intact; items within `results` are NOT individually projected because `apply_projection` only special-cases `items` and direct `list` inputs). Therefore `set_id` added to each `results` row and `metadata` nested in each `results` row both survive projection without requiring allowlist additions.

History compaction (`_struct_compact_tool_content` in `history_builder.py`) currently handles `list`, `{items: [...]}`, and single-dict payloads. `{results: [...]}` falls into the single-dict branch, which only preserves top-level `_deep_links` — but `_deep_links` exists per-item inside the `results` list, not at the top level. So the compaction branch must be extended.

## Goals / Non-Goals

**Goals:** `get_test_case_global`, `search_test_cases_global` (test_case results), and `search_knowledge` (test_case entities only) produce clickable deep links identical in format to existing team-scoped tools. History compaction preserves a sampling of those links.

**Non-Goals:** `analyze_knowledge_impact` deep links (no single-page target). Non-test_case `search_knowledge` entities (USM nodes, Jira tickets). System prompt changes (DB v15 already has the rule section). DB schema migration. Projection allowlist changes (not needed — see analysis above). Frontend changes (assistant-widget.js already renders markdown `<a>` same-tab). i18n.

## Design

### 1. `get_test_case_global` — single-resource rule

The tool result at `tool_executor.py:933-948` is a flat dict containing `set_id` (from `row.test_case_set_id`) and `test_case_number`. This maps to the same template as `get_test_case`: `/test-case-management?set_id={set_id}&tc={tc}`.

Add to `_LINK_RULES`:

```python
"get_test_case_global": (
    "test_case",
    "/test-case-management?set_id={set_id}&tc={tc}",
    {"set_id": "set_id", "tc": "test_case_number"},
),
```

No change to tool_executor — `set_id` and `test_case_number` are already present in the returned dict.

### 2. `search_test_cases_global` — list rule + SQL add `set_id`

#### 2a. SQL SELECT change (`tool_executor.py:1006-1014`)

Add `TestCaseLocal.test_case_set_id` to the SELECT clause, and add `"set_id": r.test_case_set_id` to the result dict builder (line 1030-1038).

Current SELECT:
```python
select(
    TestCaseLocal.test_case_number,
    TestCaseLocal.title,
    TestCaseLocal.priority,
    TestCaseLocal.team_id,
    TestCaseSet.name.label("set_name"),
    Team.name.label("team_name"),
)
```

Add `TestCaseLocal.test_case_set_id` to the column list.

Current result row builder:
```python
results = [
    {
        "test_case_number": r.test_case_number,
        "title": r.title,
        "priority": r.priority.value if hasattr(r.priority, "value") else r.priority,
        "team_id": r.team_id,
        "team_name": r.team_name or f"Team-{r.team_id}",
        "set_name": r.set_name or "",
    }
    for r in rows
]
```

Add `"set_id": r.test_case_set_id` to each row dict.

Update `tools_knowledge.py` summary for `search_test_cases_global` to include `set_id` in the "Returns slim rows" description.

#### 2b. List rule

```python
"search_test_cases_global": (
    "test_case",
    "/test-case-management?set_id={set_id}&tc={tc}",
    {"set_id": "set_id", "tc": "test_case_number"},
),
```

No entity_type filter needed — all rows returned by this tool are test cases.

### 3. `search_knowledge` — list rule with entity_type filter + nested path

`search_knowledge` returns heterogeneous entity types. Only `entity_type=="test_case"` items have TCRT deep-link targets. The IDs are nested inside `metadata`: `metadata.test_case_set_id` and `metadata.test_case_number`.

#### 3a. Dotted-path support in `_build_single`

Modify `_build_single` in `deep_links.py` to resolve dotted field names. If `field_name` contains a `.`, split on `.` and walk into nested dicts. Existing field_map entries use flat names like `"test_case_set_id"`, so this is fully backward-compatible.

```python
def _resolve_field(source: dict, field_name: str) -> Any:
    if "." in field_name:
        parts = field_name.split(".")
        val = source
        for part in parts:
            if not isinstance(val, dict):
                return None
            val = val.get(part)
        return val
    return source.get(field_name)
```

#### 3b. Entity-type filter support in list rules

Extend `_LIST_LINK_RULES` tuple to optionally include a 4th element `entity_type_filter: dict[str, str] | None`. When present, only items where `item[filter["field"]] == filter["value"]` receive `_deep_links`.

Rule:
```python
"search_knowledge": (
    "test_case",
    "/test-case-management?set_id={set_id}&tc={tc}",
    {"set_id": "metadata.test_case_set_id", "tc": "metadata.test_case_number"},
    {"field": "entity_type", "value": "test_case"},
),
```

`build_list_deep_links` updated to unpack the 4th element when present and skip non-matching items. **向後相容解包**：`_LIST_LINK_RULES` 既有條目為 3 元素 tuple，新條目為 4 元素。解包 MUST 使用長度檢查或 slice，不可直接 `link_key, url_template, field_map, entity_type_filter = rule`（會對 3 元素 tuple raise `ValueError`）。建議：

```python
link_key, url_template, field_map = rule[:3]
entity_type_filter = rule[3] if len(rule) > 3 else None
```

既有 3 元素規則（`list_test_cases` 等）保持不變，`entity_type_filter=None` 時不過濾，行為與現狀完全一致。

#### 3c. No change to retrieval service

`search_knowledge` calls `get_retrieval_service().search_knowledge()` which returns knowledge entities with `entity_type`, `metadata`, etc. We read the existing fields — no change to the retriever.

### 4. `build_list_deep_links` — `results` envelope support

Current code only handles `list` and `{items: list}` payloads. Add a third branch for `{results: list}`:

```python
elif isinstance(result_payload, dict) and isinstance(result_payload.get("results"), list):
    items = result_payload["results"]
```

The `results` key is used by `search_test_cases_global` and `search_knowledge` (and `soft_truncate_results_envelope` preserves it). Since injection happens after truncation, the `results` list at injection time is already the (possibly truncated) list — correct for deep-link generation.

### 5. History compaction — `{results: [...]}` envelope

`_struct_compact_tool_content` must handle `{results: [...]}` similarly to `{items: [...]}`:

```python
if isinstance(data, dict) and isinstance(data.get("results"), list):
    items = data["results"]
    meta = {
        "compacted": True,
        "source_count": data.get("source_count", len(items)),
        "returned_count": data.get("returned_count", len(items)),
        "truncated": data.get("truncated", True),
        "id_sample": _sample_ids_from_list(items),
        "hint": _STRUCT_HINT,
    }
    sampled_links = _sample_deep_links_from_list(items)
    if sampled_links:
        meta["_deep_links"] = sampled_links
    return json.dumps(meta, ensure_ascii=False)
```

### 6. No projection allowlist changes

Analysis of `apply_projection` (`projection.py:21-35`):
- For `{results: [...]}` payloads, the allowlist (e.g. `("status", "results", "total")`) keeps `results` at top level, and list items within `results` pass through unprojected (no special `items`-style re-projection for `results` key).
- `_deep_links` is injected in `conversation_service` AFTER `project_and_redact` has already run in `tool_executor` (line 1158).
- Therefore: no allowlist change is operationally required for any of the three global tools. This differs from the existing team-scoped tools where `_deep_links` was added to the projection tuple defensively. For local/in-process tools, the post-projection injection point makes allowlist additions vestigial. `get_test_case_global` MAY still declare `_deep_links` in its projection for consistency, but it is NOT required.

The `assistant-data-boundary` delta clarifies: for local/in-process tools, the `_deep_links` field is injected by conversation_service after projection has already been applied in tool_executor, so the tool's projection allowlist need not list `_deep_links`. Server-generated navigation fields remain valid as a concept; the spec clarifies that injection timing (post-projection in conversation_service vs. in-executor) depends on execution_mode.

### 7. Injection point unchanged

`conversation_service.py:703-707`:
```python
deep_links = build_deep_links(tool_name, payload, arguments_for_history)
if deep_links and isinstance(payload, dict):
    payload = {**payload, "_deep_links": deep_links}
else:
    build_list_deep_links(tool_name, payload)
```

- `get_test_case_global`: found in `_LINK_RULES` → `build_deep_links` returns non-empty dict → injected at top level. Correct.
- `search_test_cases_global`: NOT in `_LINK_RULES` → `build_deep_links` returns `{}` (falsy) → `build_list_deep_links` called. Correct.
- `search_knowledge`: same as above. Correct.

`conversation_service.py:1544-1550` (confirm path) only calls `build_deep_links`. All three tools are read-only, so they never hit the confirm path. No change needed.

### 8. System prompt

No change. DB v15 already has the "工具結果含 `_deep_links` 時的連結規則（必做，不得遺漏）" section from the existing change. That section's requirement text ("任何 tool result ... 含 `_deep_links` 欄位時") is general and covers all tools. The new delta scenarios in `assistant-agent-loop` add specific examples for the global tools.

### 9. Entity type filter details

The optional filter is expressed as a dict `{"field": str, "value": str}`. In `build_list_deep_links`, when unpacking a 4-element tuple:

```python
link_key, url_template, field_map, entity_type_filter = rule
```

When iterating items, before building links:
```python
if entity_type_filter:
    if not isinstance(item, dict):
        continue
    if item.get(entity_type_filter["field"]) != entity_type_filter["value"]:
        continue
```

This is clean, explicit, and avoids per-tool hooks.

## Residual Risks

- LLM回覆失敗 → 連結消失（tool success 圖示仍為權威來源）。
- LLM自行編造URL → 最多404，DOMPurify阻擋XSS。
- `search_knowledge` 非test_case entity → 不產生連結（正確行為）。
- `search_test_cases_global` 若rows中有 `set_id` 為NULL（orphaned TC）→ `_safe_id`回傳None → 該row不產生連結。這是正確的安全行為：沒有set_id就無法導航到test case。
- 歷史裁切後 `_deep_links` 只保留採樣，非全部連結 → 符合既有設計（`_STRUCT_HINT`指示LLM該行為）。

## Architecture Diagram

```
tool result (local tool dict)
    ↓ project_and_redact() in tool_executor — top-level key filter; results list items pass through
    ↓ conversation_service.append_tool_call_and_result():
      ├─ get_test_case_global → build_deep_links() → {**payload, "_deep_links": {...}}
      └─ search_*_global/search_knowledge → build_list_deep_links() → per-item _deep_links injected
    ↓ assistant_messages (role=tool, content=JSON)
    ↓ history_builder._struct_compact_tool_content() — new {results: [...]} branch
    ↓ LLM context (compaction preserves _deep_links sample)
    ↓ LLM 生成 markdown 連結
    ↓ SSE text_delta → assistant-widget.js renderMarkdown() → <a> (same-tab)
```
