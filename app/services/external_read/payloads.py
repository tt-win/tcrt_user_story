"""Payload assembly helpers for the shared external read surface.

These are moved verbatim from ``app/api/mcp.py`` (Phase 2) to keep a single
source of truth for case/config payload construction.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import orjson

from app.models.database_models import (
    TestCaseLocal as TestCaseLocalDB,
    TestRunConfig as TestRunConfigDB,
)
from app.models.test_case import redact_credential_test_data


def to_text(value: Any) -> str:
    if value is None:
        return ""
    return value.value if hasattr(value, "value") else str(value)


def parse_assignee(assignee_json: Optional[str]) -> Optional[str]:
    if not assignee_json:
        return None
    try:
        payload = json.loads(assignee_json)
    except (TypeError, ValueError):
        return assignee_json

    if isinstance(payload, dict):
        return payload.get("name") or payload.get("en_name") or payload.get("email")

    if isinstance(payload, list):
        names: list[str] = []
        for item in payload:
            if isinstance(item, dict):
                candidate = item.get("name") or item.get("en_name") or item.get("email")
                if candidate:
                    names.append(str(candidate))
            elif item:
                names.append(str(item))
        if names:
            return ", ".join(names)

    return assignee_json


def parse_tcg_list(tcg_json: Optional[str]) -> list[str]:
    if not tcg_json:
        return []
    try:
        parsed = json.loads(tcg_json)
    except (TypeError, ValueError):
        return []

    if isinstance(parsed, list):
        return [str(item) for item in parsed if item]
    if isinstance(parsed, str):
        return [parsed]
    return []


def parse_json_list(raw_json: Optional[str]) -> list[Dict[str, Any]]:
    # MCP read API 對 JSON 陣列欄位（如 test_data, attachments）採 dict 直接 passthrough，
    # 不做欄位正規化，保留 id/name/category/value 四欄位；credential 類 test_data 的 value
    # 由 build_case_payload 於回應組裝時以 redact_credential_test_data() 遮蔽。
    if not raw_json:
        return []
    try:
        parsed = orjson.loads(raw_json)
    except (TypeError, ValueError):
        return []

    if not isinstance(parsed, list):
        return []

    normalized: list[Dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            normalized.append(item)
        elif item is not None:
            normalized.append({"value": item})
    return normalized


def parse_json_dict(raw_json: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw_json:
        return None
    try:
        parsed = json.loads(raw_json)
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def build_case_payload(
    row: TestCaseLocalDB,
    *,
    include_content: bool = False,
    include_extended: bool = False,
    include_test_data: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": row.id,
        "record_id": row.lark_record_id or str(row.id),
        "test_case_number": row.test_case_number,
        "title": row.title,
        "priority": to_text(row.priority),
        "test_result": to_text(row.test_result) or None,
        "assignee": parse_assignee(row.assignee_json),
        "tcg": parse_tcg_list(row.tcg_json),
        "test_case_set_id": row.test_case_set_id,
        "test_case_section_id": row.test_case_section_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "last_sync_at": row.last_sync_at,
    }
    if include_content:
        payload.update(
            {
                "precondition": row.precondition,
                "steps": row.steps,
                "expected_result": row.expected_result,
            }
        )
    if include_extended:
        payload.update(
            {
                "attachments": parse_json_list(row.attachments_json),
                "test_results_files": parse_json_list(row.test_results_files_json),
                "user_story_map": parse_json_list(row.user_story_map_json),
                "parent_record": parse_json_list(row.parent_record_json),
                "raw_fields": parse_json_dict(row.raw_fields_json),
                "test_data": redact_credential_test_data(parse_json_list(row.test_data_json)),
            }
        )
    elif include_test_data:
        payload["test_data"] = redact_credential_test_data(parse_json_list(row.test_data_json))
    return payload


def lookup_match_type(
    row: TestCaseLocalDB,
    *,
    keyword: Optional[str],
    test_case_number: Optional[str],
    ticket: Optional[str],
) -> str:
    number_value = (row.test_case_number or "").lower()
    title_value = (row.title or "").lower()
    tcg_values = [item.lower() for item in parse_tcg_list(row.tcg_json)]

    if test_case_number:
        normalized = test_case_number.lower()
        if number_value == normalized:
            return "test_case_number_exact"
        if normalized in number_value:
            return "test_case_number_partial"

    if ticket:
        normalized = ticket.lower()
        if any(normalized in item for item in tcg_values):
            return "ticket"

    if keyword:
        normalized = keyword.lower()
        if number_value == normalized:
            return "keyword_number_exact"
        if normalized in number_value:
            return "keyword_number_partial"
        if any(normalized in item for item in tcg_values):
            return "keyword_ticket"
        if normalized in title_value:
            return "keyword_title"

    return "matched"


def config_payload(config: TestRunConfigDB) -> Dict[str, Any]:
    return {
        "id": config.id,
        "name": config.name,
        "status": to_text(config.status),
        "total_test_cases": config.total_test_cases or 0,
        "executed_cases": config.executed_cases or 0,
        "passed_cases": config.passed_cases or 0,
        "failed_cases": config.failed_cases or 0,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }
