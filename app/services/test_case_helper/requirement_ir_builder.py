from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional


class RequirementIRBuilder:
    """Merge parser output into requirement IR with stable keys."""

    def merge_with_structured_requirement(
        self,
        *,
        requirement_ir: Dict[str, Any],
        structured_requirement: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        ir_payload = dict(requirement_ir or {})
        structured = structured_requirement if isinstance(structured_requirement, dict) else {}

        scenario_key_map = self._build_scenario_key_map(structured)
        trace_map: Dict[str, str] = {}

        scenarios = ir_payload.get("scenarios") if isinstance(ir_payload.get("scenarios"), list) else []
        normalized_scenarios: List[Dict[str, Any]] = []
        for index, scenario in enumerate(scenarios, start=1):
            if not isinstance(scenario, dict):
                continue
            current = dict(scenario)
            rid = str(current.get("rid") or "").strip()
            title = str(current.get("t") or current.get("title") or "").strip()

            requirement_key = ""
            if rid and rid in scenario_key_map:
                requirement_key = scenario_key_map[rid]
            elif title:
                requirement_key = scenario_key_map.get(self._normalize_lookup_key(title), "")

            if not requirement_key:
                requirement_key = self._fallback_requirement_key(rid=rid, title=title, index=index)

            current["requirement_key"] = requirement_key
            normalized_scenarios.append(current)
            if rid:
                trace_map[rid] = requirement_key

        if normalized_scenarios:
            ir_payload["scenarios"] = normalized_scenarios

        if structured:
            ir_payload["structured_requirement"] = {
                "schema_version": structured.get("schema_version") or "structured_requirement.v1",
                "menu_paths": structured.get("menu_paths") or [],
                "user_story_narrative": structured.get("user_story_narrative") or {},
                "criteria": structured.get("criteria") or {"items": []},
                "technical_specifications": structured.get("technical_specifications") or {"items": []},
                "acceptance_criteria": structured.get("acceptance_criteria") or {"scenarios": []},
                "api_paths": structured.get("api_paths") or [],
                "references": structured.get("references") or [],
                "requirement_units": structured.get("requirement_units") or [],
            }

        trace_index = ir_payload.get("trace_index") if isinstance(ir_payload.get("trace_index"), list) else []
        trace_index.append(
            {
                "kind": "requirement_key_map",
                "mapping": trace_map,
            }
        )
        ir_payload["trace_index"] = trace_index
        return ir_payload

    def _build_scenario_key_map(self, structured: Dict[str, Any]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}

        for unit in structured.get("requirement_units") or []:
            if not isinstance(unit, dict):
                continue
            section = str(unit.get("section") or "").strip()
            requirement_key = str(unit.get("requirement_key") or "").strip()
            content = str(unit.get("content") or "").strip()
            if section == "acceptance_criteria" and requirement_key and content:
                mapping[self._normalize_lookup_key(content)] = requirement_key

        for scenario in (structured.get("acceptance_criteria") or {}).get("scenarios") or []:
            if not isinstance(scenario, dict):
                continue
            requirement_key = str(scenario.get("requirement_key") or "").strip()
            title = str(scenario.get("title") or "").strip()
            if requirement_key and title:
                mapping[self._normalize_lookup_key(title)] = requirement_key

        # Allow direct rid mapping when parser and IR share key format.
        for scenario in (structured.get("acceptance_criteria") or {}).get("scenarios") or []:
            if not isinstance(scenario, dict):
                continue
            requirement_key = str(scenario.get("requirement_key") or "").strip()
            title = str(scenario.get("title") or "").strip()
            if requirement_key and title:
                legacy_rid = self._legacy_rid_from_title(title)
                if legacy_rid:
                    mapping[legacy_rid] = requirement_key

        return mapping

    @staticmethod
    def _normalize_lookup_key(raw_value: str) -> str:
        normalized = re.sub(r"\s+", " ", str(raw_value or "").strip().lower())
        return normalized

    @staticmethod
    def _legacy_rid_from_title(title: str) -> str:
        match = re.search(r"\bREQ-\d{3}\b", str(title or "").upper())
        return match.group(0) if match else ""

    @staticmethod
    def _fallback_requirement_key(*, rid: str, title: str, index: int) -> str:
        if rid:
            return rid
        normalized = re.sub(r"\s+", " ", str(title or "").strip().lower())
        if normalized:
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8].upper()
            return f"REQ-{digest}"
        return f"REQ-{index:03d}"
