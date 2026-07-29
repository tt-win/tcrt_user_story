"""Canonical ``usm_node_v2`` payload and identity helpers.

The helpers in this module are shared by the runtime writer and the guarded
remote-MySQL rebuild command so both paths emit byte-for-byte compatible
payload shapes and deterministic point IDs.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

USM_SCHEMA_VERSION = "usm_node_v2"
USM_RESOURCE_TYPE = "usm_node"
USM_SOURCE = "tcrt_usm_mysql"


def _as_string(value: Any) -> str:
    return "" if value is None else str(value)


def _as_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc


def _json_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _dedupe_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _as_string(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _rfc3339(value: Any, *, fallback: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return fallback
    else:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def usm_entity_key(map_id: Any, node_id: Any) -> str:
    normalized_map_id = _as_int(map_id, field="map_id")
    normalized_node_id = _as_string(node_id).strip()
    if not normalized_node_id:
        raise ValueError("node_id must not be empty")
    return f"{normalized_map_id}:{normalized_node_id}"


def usm_point_id(map_id: Any, node_id: Any) -> str:
    entity_key = usm_entity_key(map_id, node_id)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"tcrt-usm-node:{entity_key}"))


def _related_references(value: Any, *, current_map_id: int) -> list[tuple[int, str]]:
    references: list[tuple[int, str]] = []
    seen: set[str] = set()
    for item in _json_list(value):
        if isinstance(item, str):
            related_map_id = current_map_id
            related_node_id = item.strip()
        elif isinstance(item, dict):
            related_node_id = _as_string(item.get("node_id") or item.get("nodeId")).strip()
            raw_map_id = item.get("map_id") or item.get("mapId") or current_map_id
            try:
                related_map_id = _as_int(raw_map_id, field="related.map_id")
            except ValueError:
                continue
        else:
            continue
        if not related_node_id:
            continue
        key = usm_entity_key(related_map_id, related_node_id)
        if key in seen:
            continue
        seen.add(key)
        references.append((related_map_id, related_node_id))
    return references


def build_usm_embedding_text(node: dict[str, Any]) -> str:
    """Build the deterministic text stored in payload and sent for embedding."""
    jira_tickets = _dedupe_strings(_json_list(node.get("jira_tickets")))
    ordered_lines = (
        ("地圖", _as_string(node.get("map_name")).strip()),
        ("類型", _as_string(node.get("node_type")).strip()),
        ("標題", _as_string(node.get("title")).strip()),
        ("描述", _as_string(node.get("description")).strip()),
        ("As a", _as_string(node.get("as_a")).strip()),
        ("I want", _as_string(node.get("i_want")).strip()),
        ("So that", _as_string(node.get("so_that")).strip()),
        ("Jira", ", ".join(jira_tickets)),
    )
    return "\n".join(f"{label}: {value}" for label, value in ordered_lines if value)


def build_usm_payload(
    node: dict[str, Any],
    *,
    synced_at: str | None = None,
) -> dict[str, Any]:
    """Return a fully populated and type-stable ``usm_node_v2`` payload."""
    sync_timestamp = synced_at or utc_now_rfc3339()
    map_id = _as_int(node.get("map_id"), field="map_id")
    team_id = _as_int(node.get("team_id"), field="team_id")
    node_id = _as_string(node.get("node_id")).strip()
    entity_key = usm_entity_key(map_id, node_id)

    parent_id = _as_string(node.get("parent_id")).strip()
    children_ids = _dedupe_strings(_json_list(node.get("children_ids")))
    related = _related_references(node.get("related_ids"), current_map_id=map_id)
    related_node_ids = [related_node_id for _, related_node_id in related]
    related_node_keys = [
        usm_entity_key(related_map_id, related_node_id)
        for related_map_id, related_node_id in related
    ]
    jira_tickets = _dedupe_strings(_json_list(node.get("jira_tickets")))
    text = build_usm_embedding_text({**node, "jira_tickets": jira_tickets})
    if not text:
        raise ValueError(f"USM node {entity_key} has no embeddable text")

    return {
        "schema_version": USM_SCHEMA_VERSION,
        "resource_type": USM_RESOURCE_TYPE,
        "source": USM_SOURCE,
        "entity_key": entity_key,
        "node_id": node_id,
        "title": _as_string(node.get("title")),
        "description": _as_string(node.get("description")),
        "node_type": _as_string(node.get("node_type")),
        "map_id": map_id,
        "map_name": _as_string(node.get("map_name")),
        "team_id": team_id,
        "team_name": _as_string(node.get("team_name")),
        "parent_id": parent_id,
        "parent_key": usm_entity_key(map_id, parent_id) if parent_id else "",
        "level": _as_int(node.get("level") or 0, field="level"),
        "children_ids": children_ids,
        "children_keys": [usm_entity_key(map_id, child_id) for child_id in children_ids],
        "related_node_ids": related_node_ids,
        "related_node_keys": related_node_keys,
        "as_a": _as_string(node.get("as_a")),
        "i_want": _as_string(node.get("i_want")),
        "so_that": _as_string(node.get("so_that")),
        "jira_tickets": jira_tickets,
        "text": text,
        "updated_at": _rfc3339(node.get("updated_at"), fallback=sync_timestamp),
        "last_synced_at": sync_timestamp,
    }
