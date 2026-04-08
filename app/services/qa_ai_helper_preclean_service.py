"""V3 wrapper around scripts.qa_ai_helper_preclean.

此模組保留 `scripts/qa_ai_helper_preclean.py` 的 deterministic parser，
並額外提供畫面二所需的格式 gate 與錯誤碼。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from scripts.qa_ai_helper_preclean import build_output


def _issue(
    code: str,
    message: str,
    *,
    section: str | None = None,
    field: str | None = None,
    scenario_index: int | None = None,
    scenario_name: str | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if section:
        payload["section"] = section
    if field:
        payload["field"] = field
    if scenario_index is not None:
        payload["scenario_index"] = scenario_index
    if scenario_name:
        payload["scenario_name"] = scenario_name
    return payload


def _count_criteria_items(criteria: Any) -> int:
    if not isinstance(criteria, dict):
        return 0

    total = 0
    for category in criteria.values():
        if not isinstance(category, dict):
            continue
        for item in category.get("items") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
            if name or description:
                total += 1
    return total


def _scenario_payloads(acceptance_criteria: Any) -> List[Tuple[int, Dict[str, Any]]]:
    if not isinstance(acceptance_criteria, list):
        return []

    items: List[Tuple[int, Dict[str, Any]]] = []
    for index, entry in enumerate(acceptance_criteria):
        if not isinstance(entry, dict):
            continue
        scenario = entry.get("Scenario")
        if isinstance(scenario, dict):
            items.append((index, scenario))
    return items


def validate_preclean_output(parsed: Dict[str, Any]) -> Dict[str, Any]:
    missing_sections: List[Dict[str, Any]] = []
    missing_fields: List[Dict[str, Any]] = []
    scenario_errors: List[Dict[str, Any]] = []
    parser_errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    narrative = parsed.get("User Story Narrative")
    criteria = parsed.get("Criteria")
    acceptance_criteria = parsed.get("Acceptance Criteria")
    technical_specs = parsed.get("Technical Specifications")

    if "User Story Narrative" not in parsed:
        missing_sections.append(
            _issue(
                "missing_user_story_narrative",
                "缺少必要區塊：User Story Narrative",
                section="User Story Narrative",
            )
        )
    if "Criteria" not in parsed:
        missing_sections.append(
            _issue(
                "missing_criteria",
                "缺少必要區塊：Criteria",
                section="Criteria",
            )
        )
    if "Acceptance Criteria" not in parsed:
        missing_sections.append(
            _issue(
                "missing_acceptance_criteria",
                "缺少必要區塊：Acceptance Criteria",
                section="Acceptance Criteria",
            )
        )
    if "Technical Specifications" not in parsed or not technical_specs:
        warnings.append(
            _issue(
                "missing_technical_specifications",
                "Technical Specifications 缺漏，畫面三將顯示空白參考區。",
                section="Technical Specifications",
            )
        )

    if isinstance(narrative, dict):
        for field_name, code in (
            ("As a", "missing_user_story_as_a"),
            ("I want", "missing_user_story_i_want"),
            ("So that", "missing_user_story_so_that"),
        ):
            value = str(narrative.get(field_name) or "").strip()
            if not value:
                missing_fields.append(
                    _issue(
                        code,
                        f"User Story Narrative 缺少 {field_name}",
                        section="User Story Narrative",
                        field=field_name,
                    )
                )
    elif "User Story Narrative" in parsed:
        parser_errors.append(
            _issue(
                "invalid_user_story_narrative",
                "User Story Narrative 必須為 object",
                section="User Story Narrative",
            )
        )

    criteria_item_count = _count_criteria_items(criteria)
    if "Criteria" in parsed and criteria_item_count < 1:
        missing_fields.append(
            _issue(
                "criteria_has_no_items",
                "Criteria 至少需要一筆有效項目",
                section="Criteria",
            )
        )

    if "Acceptance Criteria" in parsed and not isinstance(acceptance_criteria, list):
        parser_errors.append(
            _issue(
                "acceptance_criteria_not_list",
                "Acceptance Criteria 必須為 list",
                section="Acceptance Criteria",
            )
        )

    scenario_items = _scenario_payloads(acceptance_criteria)
    if "Acceptance Criteria" in parsed and isinstance(acceptance_criteria, list) and len(scenario_items) < 1:
        missing_fields.append(
            _issue(
                "empty_acceptance_criteria",
                "Acceptance Criteria 至少需要一個有效 scenario",
                section="Acceptance Criteria",
            )
        )

    for scenario_index, scenario in scenario_items:
        scenario_name = str(scenario.get("name") or "").strip()
        if not scenario_name or scenario_name == "Unnamed Scenario":
            scenario_errors.append(
                _issue(
                    "unnamed_acceptance_scenario",
                    "Acceptance Criteria scenario 不可為 Unnamed Scenario",
                    section="Acceptance Criteria",
                    scenario_index=scenario_index,
                    scenario_name=scenario_name or "Unnamed Scenario",
                )
            )

        for clause, code in (
            ("Given", "scenario_missing_given"),
            ("When", "scenario_missing_when"),
            ("Then", "scenario_missing_then"),
        ):
            values = [str(item).strip() for item in (scenario.get(clause) or []) if str(item).strip()]
            if not values:
                scenario_errors.append(
                    _issue(
                        code,
                        f"Scenario 缺少 {clause}",
                        section="Acceptance Criteria",
                        field=clause,
                        scenario_index=scenario_index,
                        scenario_name=scenario_name or "Unnamed Scenario",
                    )
                )

    error_count = (
        len(missing_sections)
        + len(missing_fields)
        + len(scenario_errors)
        + len(parser_errors)
    )
    return {
        "is_valid": error_count == 0,
        "missing_sections": missing_sections,
        "missing_fields": missing_fields,
        "scenario_errors": scenario_errors,
        "parser_errors": parser_errors,
        "warnings": warnings,
        "stats": {
            "criteria_item_count": criteria_item_count,
            "acceptance_scenario_count": len(scenario_items),
        },
    }


def parse_ticket_to_requirement_payload(
    description: str,
    comments: List[str] | None = None,
) -> Dict[str, Any]:
    try:
        structured_requirement = build_output(description or "", comments or [])
    except Exception as exc:  # noqa: BLE001
        validation_result = {
            "is_valid": False,
            "missing_sections": [],
            "missing_fields": [],
            "scenario_errors": [],
            "parser_errors": [
                _issue(
                    "parser_exception",
                    f"Parser 執行失敗：{exc}",
                )
            ],
            "warnings": [],
            "stats": {
                "criteria_item_count": 0,
                "acceptance_scenario_count": 0,
            },
        }
        return {
            "structured_requirement": {},
            "validation_result": validation_result,
        }

    return {
        "structured_requirement": structured_requirement,
        "validation_result": validate_preclean_output(structured_requirement),
    }
