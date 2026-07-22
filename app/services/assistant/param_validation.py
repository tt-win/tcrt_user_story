"""輕量 JSON Schema 驗證器，僅支援 `schema_helpers.py` 產生的子集。

不引入 `jsonschema` 依賴（repo 尚未使用該套件，新增依賴需先決策）；
本模組只需驗證我們自己生成的 schema 形狀（object/array/string/integer/boolean + enum +
required + additionalProperties=false），足以支撐 executor 的「未知/缺漏參數即拒絕」需求。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str]


def _validate_value(value, schema: dict, path: str, errors: list[str]) -> None:
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object")
            return
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", True)
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: missing required field")
        if additional is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key}: unknown field not allowed")
        for key, sub_schema in properties.items():
            if key in value:
                _validate_value(value[key], sub_schema, f"{path}.{key}", errors)
    elif t == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected array")
            return
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                _validate_value(item, item_schema, f"{path}[{i}]", errors)
    elif t == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: expected string")
            return
        enum = schema.get("enum")
        if enum and value not in enum:
            errors.append(f"{path}: must be one of {enum}")
    elif t == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{path}: expected integer")
    elif t == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path}: expected boolean")
    # 未知/未宣告 type 一律略過（不阻擋）


def validate_arguments(arguments: dict, schema: dict | None) -> ValidationResult:
    """`schema` 為 None 代表此工具不接受任何參數（arguments 必須為空 dict）。"""
    errors: list[str] = []
    if schema is None:
        if arguments:
            errors.append("this tool does not accept any parameters")
        return ValidationResult(ok=not errors, errors=errors)
    _validate_value(arguments, schema, "$", errors)
    return ValidationResult(ok=not errors, errors=errors)
