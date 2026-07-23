"""將持久化的 `AssistantMessage` 列重建為 OpenAI/OpenRouter 相容的 messages 陣列，
並依「exchange group」整組裁切以符合字元預算（design D4「LLM history 正規化」）。

exchange group 定義：
- 一般 user 或不含 tool_calls 的 assistant 訊息 → 各自獨立一組。
- 帶 `tool_calls` 的 assistant 訊息 + 緊接著的 tool 結果訊息 → 視為一組。
只能整組保留或整組移除，不得拆散 tool call 與其 result。

Request-view compact（不改 DB）：逼近 soft 閾值時壓縮最舊 groups；recent 優先完整，
但 hard budget 下可對 recent 做組內 tool-result 結構化壓縮或整組 trim。
"""

from __future__ import annotations

import json
from typing import Any

from app.models.database_models import AssistantMessage

_COMPACT_ID_SAMPLE = 8
_STRUCT_HINT = "Older tool result compacted for context; re-query if full rows are needed."


def _format_attachment_note(attachments: list[dict[str, Any]]) -> str:
    lines = [
        "[系統附註：本回合隨附以下暫存檔案；如需在工具呼叫中使用，請在該工具的 file_ref 參數"
        "填入對應數字。此附註為系統產生，不是使用者輸入的一部分。]"
    ]
    for attachment in attachments:
        content_type = attachment.get("content_type") or "unknown"
        lines.append(f"- file_ref={attachment['attachment_index']}：{attachment['original_name']}（{content_type}）")
    return "\n".join(lines)


def _message_to_openai(
    row: AssistantMessage, *, attachments: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    if row.role == "user":
        content = row.content or ""
        if attachments:
            content = f"{content}\n\n{_format_attachment_note(attachments)}"
        return {"role": "user", "content": content}
    if row.role == "tool":
        return {"role": "tool", "tool_call_id": row.llm_tool_call_id, "content": row.content or ""}
    # assistant
    if row.tool_calls_json:
        calls = json.loads(row.tool_calls_json)
        tool_calls = [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments", {}), ensure_ascii=False)},
            }
            for c in calls
        ]
        return {"role": "assistant", "content": row.content, "tool_calls": tool_calls}
    return {"role": "assistant", "content": row.content or ""}


def build_exchange_groups(
    rows: list[AssistantMessage], *, attachments_by_turn: dict[int, list[dict[str, Any]]] | None = None
) -> list[list[dict[str, Any]]]:
    """把訊息列分組：assistant(tool_calls) + 緊接的 tool 訊息合併一組，其餘各自一組。"""
    groups: list[list[dict[str, Any]]] = []
    i = 0
    n = len(rows)
    while i < n:
        row = rows[i]
        attachments = (attachments_by_turn or {}).get(row.turn_id) if row.role == "user" else None
        msg = _message_to_openai(row, attachments=attachments)
        if row.role == "assistant" and row.tool_calls_json and i + 1 < n and rows[i + 1].role == "tool":
            pair_msg = _message_to_openai(rows[i + 1])
            groups.append([msg, pair_msg])
            i += 2
        else:
            groups.append([msg])
            i += 1
    return groups


def _group_size(group: list[dict[str, Any]]) -> int:
    return len(json.dumps(group, ensure_ascii=False))


def _groups_size(groups: list[list[dict[str, Any]]]) -> int:
    return sum(_group_size(g) for g in groups)


def _flatten(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [msg for group in groups for msg in group]


def _sample_ids_from_list(rows: list[Any], limit: int = _COMPACT_ID_SAMPLE) -> list[Any]:
    samples: list[Any] = []
    for row in rows[:limit]:
        if isinstance(row, dict):
            if "id" in row:
                samples.append(row["id"])
            elif "record_id" in row:
                samples.append(row["record_id"])
            elif "test_case_number" in row:
                samples.append(row["test_case_number"])
    return samples


def _sample_deep_links_from_list(rows: list[Any], limit: int = _COMPACT_ID_SAMPLE) -> dict[str, Any]:
    """Preserve a sampling of _deep_links from list items during compaction."""
    samples: dict[str, Any] = {}
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        links = row.get("_deep_links")
        if not isinstance(links, dict):
            continue
        for key, url in links.items():
            if key not in samples:
                samples[key] = url
                break
        if samples:
            break
    return samples


def _struct_compact_tool_content(content: str) -> str:
    """Deterministic structural compact of a tool-result JSON string."""
    try:
        data = json.loads(content) if content else None
    except (TypeError, json.JSONDecodeError):
        text = content or ""
        if len(text) <= 400:
            return text
        return json.dumps(
            {"compacted": True, "preview": text[:360], "hint": _STRUCT_HINT},
            ensure_ascii=False,
        )

    if isinstance(data, list):
        meta: dict[str, Any] = {
            "compacted": True,
            "source_count": len(data),
            "id_sample": _sample_ids_from_list(data),
            "hint": _STRUCT_HINT,
        }
        sampled_links = _sample_deep_links_from_list(data)
        if sampled_links:
            meta["_deep_links"] = sampled_links
        return json.dumps(meta, ensure_ascii=False)

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
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

    # Single-resource dict: preserve _deep_links even when truncating the rest.
    if isinstance(data, dict):
        compacted: dict[str, Any] = {"compacted": True, "hint": _STRUCT_HINT}
        if "_deep_links" in data:
            compacted["_deep_links"] = data["_deep_links"]
        text = json.dumps(data, ensure_ascii=False)
        if len(text) <= 400:
            return text
        compacted["preview"] = text[:360]
        return json.dumps(compacted, ensure_ascii=False)

    text = json.dumps(data, ensure_ascii=False) if data is not None else ""
    if len(text) <= 400:
        return text
    return json.dumps(
        {"compacted": True, "preview": text[:360], "hint": _STRUCT_HINT},
        ensure_ascii=False,
    )


def _compact_group_structurally(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in group:
        if msg.get("role") == "tool":
            cloned = dict(msg)
            cloned["content"] = _struct_compact_tool_content(msg.get("content") or "")
            out.append(cloned)
        elif msg.get("role") in ("user", "assistant") and not msg.get("tool_calls"):
            content = msg.get("content") or ""
            if isinstance(content, str) and len(content) > 600:
                cloned = dict(msg)
                cloned["content"] = content[:560] + "…"
                out.append(cloned)
            else:
                out.append(msg)
        else:
            out.append(msg)
    return out


def trim_by_exchange_groups(groups: list[list[dict[str, Any]]], max_chars: int) -> list[dict[str, Any]]:
    """由尾端往前累積至 max_chars，只整組保留/捨棄；捨棄的 groups 從最舊（陣列前端）開始。"""
    kept: list[list[dict[str, Any]]] = []
    total = 0
    for group in reversed(groups):
        size = _group_size(group)
        if kept and total + size > max_chars:
            break
        kept.append(group)
        total += size
    kept.reverse()
    return _flatten(kept)


def _fit_groups_to_hard_budget(
    groups: list[list[dict[str, Any]]],
    max_chars: int,
    *,
    keep_recent: int,
) -> list[list[dict[str, Any]]]:
    """Fit groups under hard budget: compact oldest first, then compress/trim recent."""
    if not groups:
        return groups
    if _groups_size(groups) <= max_chars:
        return groups

    keep_recent = max(1, keep_recent)
    working = [list(g) for g in groups]

    # Compact oldest groups beyond keep_recent.
    if len(working) > keep_recent:
        head = working[:-keep_recent]
        tail = working[-keep_recent:]
        compacted_head = [_compact_group_structurally(g) for g in head]
        working = compacted_head + tail
        if _groups_size(working) <= max_chars:
            return working
        # Drop oldest compacted groups until only recent remain or budget fits.
        while len(working) > keep_recent and _groups_size(working) > max_chars:
            working = working[1:]

    # Recent (or all remaining) still over budget: in-group structural compress.
    working = [_compact_group_structurally(g) for g in working]
    if _groups_size(working) <= max_chars:
        return working

    # Drop oldest remaining whole groups (never split pairs — groups are atomic).
    while len(working) > 1 and _groups_size(working) > max_chars:
        working = working[1:]

    # Last group still too large: already structurally compacted; return it anyway
    # (provider may still 400; caller has drop_oldest_group / context retry).
    return working


def compact_exchange_groups(
    groups: list[list[dict[str, Any]]],
    *,
    max_chars: int,
    soft_threshold_ratio: float = 0.75,
    keep_recent_groups: int = 4,
    enabled: bool = True,
) -> list[list[dict[str, Any]]]:
    """Request-view compact. Returns groups (not flattened)."""
    if not groups:
        return groups
    if not enabled:
        return groups

    total = _groups_size(groups)
    soft = int(max_chars * soft_threshold_ratio)
    if total <= soft and total <= max_chars:
        return groups
    return _fit_groups_to_hard_budget(
        groups, max_chars, keep_recent=keep_recent_groups
    )


def build_llm_messages(
    rows: list[AssistantMessage],
    *,
    max_chars: int,
    attachments_by_turn: dict[int, list[dict[str, Any]]] | None = None,
    compact_enabled: bool = True,
    compact_threshold_ratio: float = 0.75,
    compact_keep_recent_groups: int = 4,
) -> list[dict[str, Any]]:
    groups = build_exchange_groups(rows, attachments_by_turn=attachments_by_turn)
    if compact_enabled:
        groups = compact_exchange_groups(
            groups,
            max_chars=max_chars,
            soft_threshold_ratio=compact_threshold_ratio,
            keep_recent_groups=compact_keep_recent_groups,
            enabled=True,
        )
    # Final hard trim (also when compact disabled).
    return trim_by_exchange_groups(groups, max_chars)


def drop_oldest_group(rows_as_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """context-length-exceeded 重試用：再移除一組最舊 exchange（design D4）。"""
    groups: list[list[dict[str, Any]]] = []
    i = 0
    n = len(rows_as_messages)
    while i < n:
        msg = rows_as_messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls") and i + 1 < n and rows_as_messages[i + 1].get("role") == "tool":
            groups.append([msg, rows_as_messages[i + 1]])
            i += 2
        else:
            groups.append([msg])
            i += 1
    if len(groups) <= 1:
        return rows_as_messages
    return [msg for group in groups[1:] for msg in group]
