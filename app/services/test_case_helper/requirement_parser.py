from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Set, Tuple

HEADING_PATTERN = re.compile(r"^\s*h(?P<level>[1-6])\.\s*(?P<title>.+?)\s*$", re.IGNORECASE)
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s*(?P<hashes>#{1,6})\s*(?P<title>.+?)\s*$")
SCENARIO_PATTERN = re.compile(r"^(scenario|情境)\s*[:：]?\s*(?P<title>.+)$", re.IGNORECASE)
GWT_PATTERN = re.compile(r"^(given|when|then|and)\b[:：]?\s*(?P<content>.+)$", re.IGNORECASE)
LINK_PATTERN = re.compile(r"\[(?P<label>[^\]|]+)\|(?P<url>https?://[^\]]+)\]")
URL_PATTERN = re.compile(r"https?://[^\s\]\)\|]+")


class StructuredRequirementParser:
    """Parse Jira wiki style requirement text into structured contract."""

    def parse(self, requirement_markdown: str) -> Dict[str, Any]:
        text = str(requirement_markdown or "")
        lines = text.splitlines()

        structured: Dict[str, Any] = {
            "schema_version": "structured_requirement.v1",
            "menu_paths": [],
            "user_story_narrative": {
                "as_a": "",
                "i_want": "",
                "so_that": "",
            },
            "criteria": {"items": []},
            "technical_specifications": {"items": []},
            "acceptance_criteria": {"scenarios": []},
            "api_paths": [],
            "references": [],
            "requirement_units": [],
            "trace": {
                "detected_sections": [],
            },
        }

        current_section: Optional[str] = None
        current_scenario: Optional[Dict[str, Any]] = None
        seen_references: Set[Tuple[str, str]] = set()

        for raw_line in lines:
            line = str(raw_line or "")
            stripped = line.strip()
            if not stripped:
                continue
            if re.fullmatch(r"-{3,}", stripped):
                continue

            heading = self._parse_heading(stripped)
            if heading is not None:
                level, title = heading
                section_key = self._map_section(title)
                if section_key:
                    current_section = section_key
                    if section_key != "acceptance_criteria":
                        current_scenario = None
                    if section_key not in structured["trace"]["detected_sections"]:
                        structured["trace"]["detected_sections"].append(section_key)
                    continue
                if (
                    current_section == "acceptance_criteria"
                    and level >= 2
                    and title
                ):
                    current_scenario = self._new_scenario(
                        title=self._clean_text(title),
                        scenarios=structured["acceptance_criteria"]["scenarios"],
                    )
                    continue

            cleaned_line, refs = self._extract_links(stripped)
            for label, url in refs:
                token = (label, url)
                if token in seen_references:
                    continue
                seen_references.add(token)
                structured["references"].append({"label": label, "url": url})

            content = self._clean_text(cleaned_line)
            if not content:
                continue

            if current_section == "menu":
                structured["menu_paths"].append(content)
                continue

            if current_section == "user_story_narrative":
                self._consume_user_story_line(
                    content,
                    structured["user_story_narrative"],
                )
                continue

            if current_section == "criteria":
                structured["criteria"]["items"].append(content)
                continue

            if current_section == "technical_specifications":
                structured["technical_specifications"]["items"].append(content)
                continue

            if current_section == "api_paths":
                urls = URL_PATTERN.findall(content)
                if urls:
                    structured["api_paths"].extend(urls)
                else:
                    structured["api_paths"].append(content)
                continue

            if current_section == "acceptance_criteria":
                scenario_match = SCENARIO_PATTERN.match(content)
                if scenario_match:
                    scenario_title = self._clean_text(scenario_match.group("title"))
                    if scenario_title:
                        current_scenario = self._new_scenario(
                            title=scenario_title,
                            scenarios=structured["acceptance_criteria"]["scenarios"],
                        )
                    continue

                gwt_match = GWT_PATTERN.match(content)
                if gwt_match:
                    if current_scenario is None:
                        current_scenario = self._new_scenario(
                            title=f"Scenario {len(structured['acceptance_criteria']['scenarios']) + 1}",
                            scenarios=structured["acceptance_criteria"]["scenarios"],
                        )
                    clause = gwt_match.group(1).lower()
                    clause_content = self._clean_text(gwt_match.group("content"))
                    if clause_content:
                        current_scenario[clause].append(clause_content)
                    continue

                if current_scenario is None:
                    current_scenario = self._new_scenario(
                        title=f"Scenario {len(structured['acceptance_criteria']['scenarios']) + 1}",
                        scenarios=structured["acceptance_criteria"]["scenarios"],
                    )
                current_scenario["and"].append(content)
                continue

            # Fallback: try to absorb API links even outside API section
            urls = URL_PATTERN.findall(content)
            if urls:
                structured["api_paths"].extend(urls)

        self._normalize_structured_requirement(structured)
        self._build_requirement_units(structured)
        return structured

    @staticmethod
    def _parse_heading(line: str) -> Optional[Tuple[int, str]]:
        jira_match = HEADING_PATTERN.match(line)
        if jira_match:
            return int(jira_match.group("level")), jira_match.group("title").strip()
        markdown_match = MARKDOWN_HEADING_PATTERN.match(line)
        if markdown_match:
            return len(markdown_match.group("hashes")), markdown_match.group("title").strip()
        return None

    @staticmethod
    def _map_section(title: str) -> Optional[str]:
        normalized = re.sub(r"\s+", " ", str(title or "").strip().lower())
        normalized = normalized.replace("（", "(").replace("）", ")")
        if "menu" in normalized or "功能路徑" in normalized:
            return "menu"
        if "user story" in normalized or "使用者故事" in normalized:
            return "user_story_narrative"
        if "acceptance criteria" in normalized or "驗收標準" in normalized:
            return "acceptance_criteria"
        if "technical specification" in normalized or "技術規格" in normalized:
            return "technical_specifications"
        if normalized.startswith("criteria") or normalized == "criteria":
            return "criteria"
        if "api" in normalized and ("路徑" in normalized or "path" in normalized):
            return "api_paths"
        return None

    @staticmethod
    def _extract_links(line: str) -> Tuple[str, List[Tuple[str, str]]]:
        references: List[Tuple[str, str]] = []

        def _replace(match: re.Match[str]) -> str:
            label = str(match.group("label") or "").strip()
            url = str(match.group("url") or "").strip()
            if label and url:
                references.append((label, url))
            return label or url

        replaced = LINK_PATTERN.sub(_replace, line)
        return replaced, references

    @staticmethod
    def _strip_list_prefix(line: str) -> str:
        return re.sub(r"^\s*(?:\*+|-+|\d+\.)\s*", "", line).strip()

    def _clean_text(self, raw: Any) -> str:
        text = str(raw or "")
        text = self._strip_list_prefix(text)
        text = text.replace("{{{", "").replace("}}}", "")
        text = text.replace("{{", "").replace("}}", "")
        text = re.sub(r"`(.+?)`", r"\1", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"__(.+?)__", r"\1", text)
        text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _consume_user_story_line(
        self,
        content: str,
        user_story: Dict[str, str],
    ) -> None:
        normalized = content.strip()
        lower = normalized.lower()

        if lower.startswith("as a"):
            user_story["as_a"] = self._clean_text(normalized[4:].strip(" :："))
            return
        if lower.startswith("i want"):
            user_story["i_want"] = self._clean_text(normalized[6:].strip(" :："))
            return
        if lower.startswith("so that"):
            user_story["so_that"] = self._clean_text(normalized[7:].strip(" :："))
            return

        # Try soft matching for localized content.
        if "as a" in lower and not user_story.get("as_a"):
            user_story["as_a"] = self._clean_text(normalized.split("as a", 1)[-1])
        elif "i want" in lower and not user_story.get("i_want"):
            user_story["i_want"] = self._clean_text(normalized.split("i want", 1)[-1])
        elif "so that" in lower and not user_story.get("so_that"):
            user_story["so_that"] = self._clean_text(normalized.split("so that", 1)[-1])

    @staticmethod
    def _new_scenario(title: str, scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
        scenario = {
            "title": title or f"Scenario {len(scenarios) + 1}",
            "given": [],
            "when": [],
            "then": [],
            "and": [],
            "requirement_key": "",
        }
        scenarios.append(scenario)
        return scenario

    @staticmethod
    def _unique_preserve(values: List[str]) -> List[str]:
        result: List[str] = []
        seen: Set[str] = set()
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _normalize_structured_requirement(self, structured: Dict[str, Any]) -> None:
        structured["menu_paths"] = self._unique_preserve(structured.get("menu_paths") or [])
        structured["criteria"]["items"] = self._unique_preserve(
            structured.get("criteria", {}).get("items") or []
        )
        structured["technical_specifications"]["items"] = self._unique_preserve(
            structured.get("technical_specifications", {}).get("items") or []
        )
        structured["api_paths"] = self._unique_preserve(structured.get("api_paths") or [])

        scenarios = structured.get("acceptance_criteria", {}).get("scenarios") or []
        normalized_scenarios: List[Dict[str, Any]] = []
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                continue
            title = self._clean_text(scenario.get("title"))
            given = self._unique_preserve([self._clean_text(v) for v in (scenario.get("given") or [])])
            when = self._unique_preserve([self._clean_text(v) for v in (scenario.get("when") or [])])
            then = self._unique_preserve([self._clean_text(v) for v in (scenario.get("then") or [])])
            and_list = self._unique_preserve([self._clean_text(v) for v in (scenario.get("and") or [])])
            if not title and not (given or when or then or and_list):
                continue
            normalized_scenarios.append(
                {
                    "title": title or f"Scenario {len(normalized_scenarios) + 1}",
                    "given": given,
                    "when": when,
                    "then": then,
                    "and": and_list,
                    "requirement_key": "",
                }
            )
        structured["acceptance_criteria"]["scenarios"] = normalized_scenarios

    def _build_requirement_units(self, structured: Dict[str, Any]) -> None:
        units: List[Dict[str, Any]] = []
        used_keys: Set[str] = set()

        def _append(section: str, unit_type: str, content: str) -> str:
            requirement_key = self._generate_requirement_key(
                section=section,
                content=content,
                used_keys=used_keys,
            )
            units.append(
                {
                    "requirement_key": requirement_key,
                    "section": section,
                    "type": unit_type,
                    "content": content,
                }
            )
            return requirement_key

        user_story = structured.get("user_story_narrative") or {}
        if user_story.get("as_a"):
            _append("user_story_narrative", "as_a", str(user_story.get("as_a")))
        if user_story.get("i_want"):
            _append("user_story_narrative", "i_want", str(user_story.get("i_want")))
        if user_story.get("so_that"):
            _append("user_story_narrative", "so_that", str(user_story.get("so_that")))

        for item in structured.get("criteria", {}).get("items") or []:
            _append("criteria", "criteria_item", str(item))

        for item in structured.get("technical_specifications", {}).get("items") or []:
            _append("technical_specifications", "technical_spec_item", str(item))

        scenarios = structured.get("acceptance_criteria", {}).get("scenarios") or []
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                continue
            digest_source = "\n".join(
                [
                    str(scenario.get("title") or ""),
                    "|".join(scenario.get("given") or []),
                    "|".join(scenario.get("when") or []),
                    "|".join(scenario.get("then") or []),
                    "|".join(scenario.get("and") or []),
                ]
            )
            scenario_key = _append(
                "acceptance_criteria",
                "scenario",
                digest_source,
            )
            scenario["requirement_key"] = scenario_key

        structured["requirement_units"] = units

    @staticmethod
    def _generate_requirement_key(
        *,
        section: str,
        content: str,
        used_keys: Set[str],
    ) -> str:
        section_prefix_map = {
            "user_story_narrative": "USR",
            "criteria": "CRT",
            "technical_specifications": "TPS",
            "acceptance_criteria": "ACC",
        }
        prefix = section_prefix_map.get(section, "REQ")
        normalized = re.sub(r"\s+", " ", str(content or "").strip().lower())
        digest = hashlib.sha1(f"{section}|{normalized}".encode("utf-8")).hexdigest()[:8].upper()
        base_key = f"{prefix}-{digest}"
        key = base_key
        suffix = 2
        while key in used_keys:
            key = f"{base_key}-{suffix}"
            suffix += 1
        used_keys.add(key)
        return key
