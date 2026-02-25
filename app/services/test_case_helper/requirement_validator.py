from __future__ import annotations

from typing import Any, Dict, List


class RequirementCompletenessValidator:
    """Validate completeness of structured requirement contract."""

    REQUIRED_SECTIONS = (
        "menu_paths",
        "user_story_narrative",
        "criteria",
        "technical_specifications",
        "acceptance_criteria",
        "api_paths",
    )

    def validate(self, structured_requirement: Dict[str, Any]) -> Dict[str, Any]:
        payload = structured_requirement if isinstance(structured_requirement, dict) else {}

        missing_sections: List[str] = []
        missing_fields: List[str] = []

        menu_paths = payload.get("menu_paths") or []
        if not menu_paths:
            missing_sections.append("menu_paths")

        user_story = payload.get("user_story_narrative") if isinstance(payload.get("user_story_narrative"), dict) else {}
        for field in ("as_a", "i_want", "so_that"):
            if not str(user_story.get(field) or "").strip():
                missing_fields.append(f"user_story_narrative.{field}")
        if any(field.startswith("user_story_narrative") for field in missing_fields):
            missing_sections.append("user_story_narrative")

        criteria_items = payload.get("criteria", {}).get("items") if isinstance(payload.get("criteria"), dict) else []
        if not criteria_items:
            missing_sections.append("criteria")

        technical_items = (
            payload.get("technical_specifications", {}).get("items")
            if isinstance(payload.get("technical_specifications"), dict)
            else []
        )
        if not technical_items:
            missing_sections.append("technical_specifications")

        scenarios = (
            payload.get("acceptance_criteria", {}).get("scenarios")
            if isinstance(payload.get("acceptance_criteria"), dict)
            else []
        )
        if not scenarios:
            missing_sections.append("acceptance_criteria")
        else:
            for index, scenario in enumerate(scenarios, start=1):
                if not isinstance(scenario, dict):
                    missing_fields.append(f"acceptance_criteria.scenarios[{index}]")
                    continue
                if not (scenario.get("given") or []):
                    missing_fields.append(f"acceptance_criteria.scenarios[{index}].given")
                if not (scenario.get("when") or []):
                    missing_fields.append(f"acceptance_criteria.scenarios[{index}].when")
                if not (scenario.get("then") or []):
                    missing_fields.append(f"acceptance_criteria.scenarios[{index}].then")

        api_paths = payload.get("api_paths") or []
        if not api_paths:
            missing_sections.append("api_paths")

        missing_sections = self._dedupe(missing_sections)
        missing_fields = self._dedupe(missing_fields)

        issue_count = len(missing_sections) + len(missing_fields)
        quality_level = "high"
        if issue_count > 0:
            quality_level = "medium" if issue_count <= 4 else "low"

        is_complete = issue_count == 0
        return {
            "validation_contract_version": "requirement_validation.v1",
            "is_complete": is_complete,
            "quality_level": quality_level,
            "missing_sections": missing_sections,
            "missing_fields": missing_fields,
            "required_sections": list(self.REQUIRED_SECTIONS),
        }

    @staticmethod
    def _dedupe(values: List[str]) -> List[str]:
        seen = set()
        result: List[str] = []
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result
