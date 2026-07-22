"""將持久化的 `AssistantMessage` 列重建為 OpenAI/OpenRouter 相容的 messages 陣列，
並依「exchange group」整組裁切以符合字元預算（design D4「LLM history 正規化」）。

exchange group 定義：
- 一般 user 或不含 tool_calls 的 assistant 訊息 → 各自獨立一組。
- 帶 `tool_calls` 的 assistant 訊息 + 緊接著的 tool 結果訊息 → 視為一組（configuration/write 皆同）。
只能整組保留或整組移除，不得拆散 tool call 與其 result。
"""

from __future__ import annotations

import json
from typing import Any

from app.models.database_models import AssistantMessage


def _message_to_openai(row: AssistantMessage) -> dict[str, Any]:
    if row.role == "user":
        return {"role": "user", "content": row.content or ""}
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


def build_exchange_groups(rows: list[AssistantMessage]) -> list[list[dict[str, Any]]]:
    """把訊息列分組：assistant(tool_calls) + 緊接的 tool 訊息合併一組，其餘各自一組。"""
    groups: list[list[dict[str, Any]]] = []
    i = 0
    n = len(rows)
    while i < n:
        row = rows[i]
        msg = _message_to_openai(row)
        if row.role == "assistant" and row.tool_calls_json and i + 1 < n and rows[i + 1].role == "tool":
            pair_msg = _message_to_openai(rows[i + 1])
            groups.append([msg, pair_msg])
            i += 2
        else:
            groups.append([msg])
            i += 1
    return groups


def trim_by_exchange_groups(groups: list[list[dict[str, Any]]], max_chars: int) -> list[dict[str, Any]]:
    """由尾端往前累積至 max_chars，只整組保留/捨棄；捨棄的 groups 從最舊（陣列前端）開始。"""
    kept: list[list[dict[str, Any]]] = []
    total = 0
    for group in reversed(groups):
        size = len(json.dumps(group, ensure_ascii=False))
        if kept and total + size > max_chars:
            break
        kept.append(group)
        total += size
    kept.reverse()
    return [msg for group in kept for msg in group]


def build_llm_messages(rows: list[AssistantMessage], *, max_chars: int) -> list[dict[str, Any]]:
    groups = build_exchange_groups(rows)
    return trim_by_exchange_groups(groups, max_chars)


def drop_oldest_group(rows_as_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """context-length-exceeded 重試用：再移除一組最舊 exchange（design D4）。

    因輸入已是攤平後的 messages 而非 group 結構，重新分組再裁切一組更穩健。
    """
    # 以「role 序列」重新切回 group：assistant(tool_calls)+tool 視為一組，其餘各自一組。
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
