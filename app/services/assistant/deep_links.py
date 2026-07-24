"""Build frontend deep links from tool execution results.

Server-generated navigation URLs injected into tool result payload so the LLM
can include clickable markdown links in its path summary. URLs are relative
paths (``/``-prefixed), never external schemes; identifiers are type-validated
and URL-encoded.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

# tool_name -> (link_key, url_template, field_map)
# field_map: {placeholder_in_template: field_name_in_source_data}
# field_map values may use dotted paths (e.g. "metadata.test_case_set_id") for
# nested-field access; see _resolve_field in _build_single.
_LINK_RULES: dict[str, tuple[str, str, dict[str, str]]] = {
    # --- create / restart (IDs from result or args) ---
    "create_test_case": (
        "test_case",
        "/test-case-management?set_id={set_id}&tc={tc}",
        {"set_id": "test_case_set_id", "tc": "test_case_number"},
    ),
    "create_test_case_set": (
        "test_case_set",
        "/test-case-management?set_id={set_id}",
        {"set_id": "id"},
    ),
    "create_test_run_config": (
        "test_run",
        "/test-run-execution?config_id={config_id}",
        {"config_id": "id"},
    ),
    "create_test_run_set": (
        "test_run_set",
        "/test-run-management?set_id={set_id}",
        {"set_id": "id"},
    ),
    "restart_test_run": (
        "test_run",
        "/test-run-execution?config_id={config_id}",
        {"config_id": "new_config_id"},
    ),
    # --- get (single-resource detail) ---
    "get_test_case": (
        "test_case",
        "/test-case-management?set_id={set_id}&tc={tc}",
        {"set_id": "test_case_set_id", "tc": "test_case_number"},
    ),
    "get_test_case_set": (
        "test_case_set",
        "/test-case-management?set_id={set_id}",
        {"set_id": "id"},
    ),
    "get_test_run": (
        "test_run",
        "/test-run-execution?config_id={config_id}",
        {"config_id": "id"},
    ),
    "get_test_run_set": (
        "test_run_set",
        "/test-run-management?set_id={set_id}",
        {"set_id": "id"},
    ),
    # --- global read (cross-team) ---
    # get_test_case_global returns a flat dict with `set_id` (from
    # TestCaseLocal.test_case_set_id) and `test_case_number` already present.
    "get_test_case_global": (
        "test_case",
        "/test-case-management?set_id={set_id}&tc={tc}",
        {"set_id": "set_id", "tc": "test_case_number"},
    ),
}

# Tools where the ID source is tool_arguments (body_params) instead of result.
_ARGS_SOURCE_TOOLS: frozenset[str] = frozenset({
    "bulk_create_test_cases",
    "bulk_clone_test_cases",
})

# Args-source rules: tool_name -> (link_key, url_template, field_map)
_ARGS_LINK_RULES: dict[str, tuple[str, str, dict[str, str]]] = {
    "bulk_create_test_cases": (
        "test_case_set",
        "/test-case-management?set_id={set_id}",
        {"set_id": "test_case_set_id"},
    ),
    "bulk_clone_test_cases": (
        "test_case_set",
        "/test-case-management?set_id={set_id}",
        {"set_id": "test_case_set_id"},
    ),
}

# Tools whose result is a list of items — each item gets its own _deep_links.
# tool_name -> (link_key, url_template, field_map[, entity_type_filter])
#   entity_type_filter (optional 4th element): {"field": str, "value": str};
#   when present, only items where item[field] == value receive _deep_links.
_LIST_LINK_RULES: dict[str, tuple[str, str, dict[str, str]] | tuple[str, str, dict[str, str], dict[str, str]]] = {
    "list_test_cases": (
        "test_case",
        "/test-case-management?set_id={set_id}&tc={tc}",
        {"set_id": "test_case_set_id", "tc": "test_case_number"},
    ),
    "list_test_case_refs": (
        "test_case",
        "/test-case-management?set_id={set_id}&tc={tc}",
        {"set_id": "test_case_set_id", "tc": "test_case_number"},
    ),
    "list_test_case_sets": (
        "test_case_set",
        "/test-case-management?set_id={set_id}",
        {"set_id": "id"},
    ),
    "list_test_runs": (
        "test_run",
        "/test-run-execution?config_id={config_id}",
        {"config_id": "id"},
    ),
    "list_test_run_sets": (
        "test_run_set",
        "/test-run-management?set_id={set_id}",
        {"set_id": "id"},
    ),
    "list_test_run_items": (
        "test_run",
        "/test-run-execution?config_id={config_id}",
        {"config_id": "config_id"},
    ),
    "search_test_cases_global": (
        "test_case",
        "/test-case-management?set_id={set_id}&tc={tc}",
        {"set_id": "set_id", "tc": "test_case_number"},
    ),
    # search_knowledge returns heterogeneous entity types (test_case / usm_node /
    # jira_ticket). Only test_case entities have a TCRT page to deep-link to;
    # non-test_case items must be skipped. IDs live in `metadata` (dotted path).
    # The 4th tuple element is an optional entity_type_filter — see
    # build_list_deep_links for the skip rule.
    "search_knowledge": (
        "test_case",
        "/test-case-management?set_id={set_id}&tc={tc}",
        {"set_id": "metadata.test_case_set_id", "tc": "metadata.test_case_number"},
        {"field": "entity_type", "value": "test_case"},
    ),
}

# Fields that are string identifiers (not int-castable).
_STRING_ID_FIELDS = frozenset({"test_case_number"})


def _safe_id(field_name: str, raw: Any) -> str | None:
    """Validate and URL-encode a single ID value.

    *field_name* is the original (possibly dotted) field name. The check against
    ``_STRING_ID_FIELDS`` uses the last path segment so dotted paths
    (e.g. ``metadata.test_case_number``) still recognise string IDs.
    """
    if raw is None:
        return None
    leaf_name = field_name.rsplit(".", 1)[-1]
    if leaf_name in _STRING_ID_FIELDS:
        safe = str(raw)
    else:
        try:
            safe = int(raw)
        except (TypeError, ValueError):
            return None
    return urllib.parse.quote(str(safe), safe="")


def _resolve_field(source: dict[str, Any], field_name: str) -> Any:
    """Resolve a field by name, supporting dotted paths (e.g. ``metadata.x``)."""
    if "." not in field_name:
        return source.get(field_name)
    parts = field_name.split(".")
    val: Any = source
    for part in parts:
        if not isinstance(val, dict):
            return None
        val = val.get(part)
    return val


def _build_single(
    link_key: str, url_template: str, field_map: dict[str, str], source: dict[str, Any],
) -> dict[str, str] | None:
    """Build a single deep link dict from *source*.

    Field names in *field_map* may be dotted paths (``metadata.foo``) for
    nested-field access; flat names fall through to ``source.get(name)``.
    """
    fmt_kwargs: dict[str, str] = {}
    for placeholder, field_name in field_map.items():
        encoded = _safe_id(field_name, _resolve_field(source, field_name))
        if encoded is None:
            return None
        fmt_kwargs[placeholder] = encoded
    return {link_key: url_template.format(**fmt_kwargs)}


def build_deep_links(
    tool_name: str,
    result_payload: Any,
    tool_arguments: dict[str, Any],
) -> dict[str, str]:
    """Return ``{link_key: url}`` for single-resource tools.

    Returns an empty dict if *tool_name* is not in the rules table, a required
    identifier is missing, or an identifier fails type validation.
    """
    rule = _LINK_RULES.get(tool_name)
    if rule is not None:
        link_key, url_template, field_map = rule
        if not isinstance(result_payload, dict):
            return {}
        return _build_single(link_key, url_template, field_map, result_payload) or {}

    args_rule = _ARGS_LINK_RULES.get(tool_name)
    if args_rule is not None:
        link_key, url_template, field_map = args_rule
        if not isinstance(tool_arguments, dict):
            return {}
        return _build_single(link_key, url_template, field_map, tool_arguments) or {}

    return {}


def build_list_deep_links(
    tool_name: str,
    result_payload: Any,
) -> bool:
    """Inject ``_deep_links`` into each item of a list result in-place.

    Returns True if any item received ``_deep_links``.
    """
    rule = _LIST_LINK_RULES.get(tool_name)
    if rule is None:
        return False
    # Backward-compatible unpack: existing rules are 3-tuple, new rules
    # may carry an optional 4th element `entity_type_filter`.
    link_key, url_template, field_map = rule[:3]
    entity_type_filter = rule[3] if len(rule) > 3 else None

    items: list[Any] | None = None
    if isinstance(result_payload, list):
        items = result_payload
    elif isinstance(result_payload, dict) and isinstance(result_payload.get("items"), list):
        items = result_payload["items"]
    elif isinstance(result_payload, dict) and isinstance(result_payload.get("results"), list):
        items = result_payload["results"]

    if items is None:
        return False

    any_injected = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if entity_type_filter is not None:
            if item.get(entity_type_filter["field"]) != entity_type_filter["value"]:
                continue
        links = _build_single(link_key, url_template, field_map, item)
        if links:
            item["_deep_links"] = links
            any_injected = True
    return any_injected