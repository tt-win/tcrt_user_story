"""工具目錄共用 JSON Schema 片段建構器，避免 64 個工具各自重複樣板。"""

from __future__ import annotations

from typing import Any


def s_str(description: str = "", enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if description:
        schema["description"] = description
    if enum:
        schema["enum"] = enum
    return schema


def s_str_or_int(description: str = "") -> dict[str, Any]:
    """產生同時接受 string 與 integer 的 schema；供 LLM 把 local id 以整數傳入的欄位使用。"""
    schema: dict[str, Any] = {"type": "string_or_integer"}
    if description:
        schema["description"] = description
    return schema


def s_int(description: str = "") -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "integer"}
    if description:
        schema["description"] = description
    return schema


def s_bool(description: str = "") -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "boolean"}
    if description:
        schema["description"] = description
    return schema


def s_array(items: dict[str, Any], description: str = "") -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "items": items}
    if description:
        schema["description"] = description
    return schema


def s_obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def body(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """`AssistantTool.body_schema` 的頂層 wrapper。"""
    return s_obj(properties, required)


TEST_DATA_ITEM_SCHEMA = s_obj(
    {
        "id": s_str("既有 test_data 項目 id（更新時可帶入）"),
        "name": s_str("欄位名稱"),
        "category": s_str(
            "text|number|credential|email|url|identifier|date|json|other",
            enum=["text", "number", "credential", "email", "url", "identifier", "date", "json", "other"],
        ),
        "value": s_str("欄位值"),
    },
    required=["name", "value"],
)
