from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Set


class PretestcasePresenter:
    """Build requirement-rich pre-testcase payload for UI and downstream generation."""

    def enrich_stage1_payload(
        self,
        *,
        stage1_payload: Dict[str, Any],
        analysis_payload: Optional[Dict[str, Any]] = None,
        requirement_ir: Optional[Dict[str, Any]] = None,
        structured_requirement: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = deepcopy(stage1_payload or {})
        analysis = analysis_payload if isinstance(analysis_payload, dict) else {}
        ir_payload = requirement_ir if isinstance(requirement_ir, dict) else {}
        structured = structured_requirement if isinstance(structured_requirement, dict) else {}

        entries = payload.get("en") if isinstance(payload.get("en"), list) else []
        if not entries:
            entries = []
            for section in payload.get("sec", []) or []:
                if not isinstance(section, dict):
                    continue
                for entry in section.get("en", []) or []:
                    if isinstance(entry, dict):
                        entries.append(entry)

        scenario_index = self._build_ir_scenario_index(ir_payload)
        analysis_index = self._build_analysis_index(analysis)

        enriched_entries: List[Dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            normalized_entry = deepcopy(entry)

            original_category = str(normalized_entry.get("cat") or "").strip()
            normalized_category = self.normalize_category(original_category)
            normalized_entry["cat"] = normalized_category

            trace = normalized_entry.get("trace") if isinstance(normalized_entry.get("trace"), dict) else {}
            trace["ref_tokens"] = self._to_list(normalized_entry.get("ref"))
            trace["rid_tokens"] = self._to_list(normalized_entry.get("rid"))
            if original_category and original_category != normalized_category:
                trace["legacy_category"] = original_category

            requirement_context = self._build_requirement_context(
                entry=normalized_entry,
                structured_requirement=structured,
                scenario_index=scenario_index,
                analysis_index=analysis_index,
            )
            normalized_entry["requirement_context"] = requirement_context
            normalized_entry["requirement_key"] = requirement_context.get("requirement_key")
            normalized_entry["trace"] = trace

            enriched_entries.append(normalized_entry)

        payload["en"] = enriched_entries
        payload["sec"] = self._rebuild_sections(payload.get("sec"), enriched_entries)
        payload.setdefault("pretestcase_contract_version", "pretestcase.requirement-rich.v1")
        return payload

    @staticmethod
    def normalize_category(raw_value: Any) -> str:
        normalized = str(raw_value or "").strip().lower()
        if normalized in {"happy", "negative", "boundary"}:
            return normalized
        if normalized in {"positive", "normal", "success"}:
            return "happy"
        if normalized in {"error", "fail", "failed", "invalid", "permission", "forbidden"}:
            return "negative"
        if normalized in {"edge", "limit"}:
            return "boundary"
        return "happy"

    def _build_requirement_context(
        self,
        *,
        entry: Dict[str, Any],
        structured_requirement: Dict[str, Any],
        scenario_index: Dict[str, Dict[str, Any]],
        analysis_index: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        rid_tokens = self._to_list(entry.get("rid"))
        ref_tokens = self._to_list(entry.get("ref"))
        req_items = entry.get("req") if isinstance(entry.get("req"), list) else []

        summary = str(entry.get("t") or "").strip()
        if not summary and req_items:
            summary = str((req_items[0] or {}).get("t") or "").strip()
        if not summary:
            summary = "需求驗證"

        matched_scenarios = self._resolve_scenarios(
            rid_tokens=rid_tokens,
            ref_tokens=ref_tokens,
            scenario_index=scenario_index,
            analysis_index=analysis_index,
        )

        requirement_content = self._unique_preserve(
            [summary]
            + [str(item.get("t") or "").strip() for item in req_items if isinstance(item, dict)]
            + [str(item.get("title") or "").strip() for item in matched_scenarios]
        )

        spec_requirements = self._unique_preserve(
            [
                *self._flatten_req_items(req_items, keys=("det", "chk")),
                *self._to_list((structured_requirement.get("criteria") or {}).get("items")),
                *self._to_list((structured_requirement.get("technical_specifications") or {}).get("items")),
            ]
        )

        verification_points = self._unique_preserve(
            [
                *self._to_list(entry.get("chk")),
                *self._flatten_req_items(req_items, keys=("chk",)),
                *self._flatten_scenario_fields(matched_scenarios, fields=("given", "when", "then", "and")),
            ]
        )

        expected_outcomes = self._unique_preserve(
            [
                *self._to_list(entry.get("exp")),
                *self._flatten_req_items(req_items, keys=("exp", "expected")),
                *self._flatten_scenario_fields(matched_scenarios, fields=("then",)),
            ]
        )

        source_requirement_keys = self._unique_preserve(
            [
                *[str(item.get("requirement_key") or "").strip() for item in matched_scenarios],
                *[token for token in rid_tokens if token],
            ]
        )
        requirement_key = source_requirement_keys[0] if source_requirement_keys else self._fallback_requirement_key(summary)

        return {
            "requirement_key": requirement_key,
            "source_requirement_keys": source_requirement_keys,
            "summary": summary,
            "content": requirement_content,
            "spec_requirements": spec_requirements,
            "verification_points": verification_points,
            "validation_requirements": verification_points,
            "expected_outcomes": expected_outcomes,
        }

    @staticmethod
    def _build_ir_scenario_index(requirement_ir: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        scenarios = requirement_ir.get("scenarios") if isinstance(requirement_ir.get("scenarios"), list) else []
        index: Dict[str, Dict[str, Any]] = {}
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                continue
            item = deepcopy(scenario)
            rid = str(item.get("rid") or "").strip()
            requirement_key = str(item.get("requirement_key") or "").strip()
            title = str(item.get("t") or item.get("title") or "").strip()
            if rid:
                index[rid] = item
            if requirement_key:
                index[requirement_key] = item
            if title:
                index[title.lower()] = item
        return index

    @staticmethod
    def _build_analysis_index(analysis_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        result: Dict[str, Dict[str, Any]] = {}
        for item in analysis_payload.get("it", []) or []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if item_id:
                result[item_id] = item
        return result

    def _resolve_scenarios(
        self,
        *,
        rid_tokens: List[str],
        ref_tokens: List[str],
        scenario_index: Dict[str, Dict[str, Any]],
        analysis_index: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        matched: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        def _append_if_exists(key: str) -> None:
            key_norm = str(key or "").strip()
            if not key_norm:
                return
            item = scenario_index.get(key_norm) or scenario_index.get(key_norm.lower())
            if not item:
                return
            requirement_key = str(item.get("requirement_key") or item.get("rid") or key_norm).strip()
            if requirement_key in seen:
                return
            seen.add(requirement_key)
            matched.append(item)

        for rid in rid_tokens:
            _append_if_exists(rid)

        for ref in ref_tokens:
            analysis_item = analysis_index.get(ref)
            if not isinstance(analysis_item, dict):
                continue
            for rid in self._to_list(analysis_item.get("rid")):
                _append_if_exists(rid)

        return matched

    @staticmethod
    def _flatten_req_items(req_items: Sequence[Any], *, keys: Sequence[str]) -> List[str]:
        result: List[str] = []
        for item in req_items:
            if not isinstance(item, dict):
                continue
            for key in keys:
                result.extend(PretestcasePresenter._to_list(item.get(key)))
        return result

    @staticmethod
    def _flatten_scenario_fields(
        scenarios: Sequence[Dict[str, Any]],
        *,
        fields: Sequence[str],
    ) -> List[str]:
        result: List[str] = []
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                continue
            for field in fields:
                value = scenario.get(field)
                if isinstance(value, list):
                    result.extend([str(item).strip() for item in value if str(item).strip()])
                elif str(value or "").strip():
                    result.append(str(value).strip())
        return result

    @staticmethod
    def _to_list(raw_value: Any) -> List[str]:
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        if isinstance(raw_value, str):
            normalized = raw_value.strip()
            return [normalized] if normalized else []
        return []

    @staticmethod
    def _unique_preserve(values: Sequence[str]) -> List[str]:
        result: List[str] = []
        seen: Set[str] = set()
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @staticmethod
    def _fallback_requirement_key(summary: str) -> str:
        normalized = str(summary or "").strip()
        if not normalized:
            return "REQ-UNKNOWN"
        token = normalized[:24].upper().replace(" ", "-")
        return f"REQ-{token}"

    @staticmethod
    def _rebuild_sections(
        sections: Any,
        entries: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        section_sn_map: Dict[str, str] = {}
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                group = str(section.get("g") or "").strip()
                sn = str(section.get("sn") or "").strip()
                if group and sn:
                    section_sn_map[group] = sn

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for entry in entries:
            group = str(entry.get("g") or "未分類").strip() or "未分類"
            grouped.setdefault(group, []).append(entry)

        rebuilt: List[Dict[str, Any]] = []
        for group, group_entries in grouped.items():
            rebuilt.append(
                {
                    "g": group,
                    "sn": section_sn_map.get(group) or str((group_entries[0] or {}).get("sn") or ""),
                    "en": group_entries,
                }
            )
        return rebuilt
