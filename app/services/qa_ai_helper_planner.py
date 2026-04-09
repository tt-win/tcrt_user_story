"""Deterministic planning engine for the rewritten QA AI Helper."""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from hashlib import sha1
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.models.qa_ai_helper import QAAIHelperApplicabilityStatus
from app.services.qa_ai_helper_common import json_compact_dumps

SCENARIO_HEADING_RE = re.compile(r"(?im)^(?:h2\.\s*)?(?:\[[^\]]+\]\s*)?scenario\s+\d+\s*[:：]?\s*(.+?)\s*$")
GIVEN_RE = re.compile(r"(?im)^\s*given\s+(.+?)\s*$")
WHEN_RE = re.compile(r"(?im)^\s*when\s+(.+?)\s*$")
THEN_RE = re.compile(r"(?im)^\s*then\s+(.+?)\s*$")
AND_RE = re.compile(r"(?im)^\s*and\s+(.+?)\s*$")
BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
INDENTED_BULLET_RE = re.compile(r"^(?P<indent>\s+)(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
SECTION_HEADING_RE = re.compile(
    r"(?im)^\s*(?:h[1-6]\.\s*)?"
    r"(?P<heading>User Story(?: Narrative)?|User Story|Criteria|Technical Specifications?|Acceptance Criteria)"
    r"\s*(?:[|｜:：-]\s*(?P<label>.+))?\s*$"
)
URL_RE = re.compile(r"https?://[^\s)>\"]+")
TICKET_REF_RE = re.compile(r"\b[A-Z]{2,}-\d+\b")
VERSION_TAG_RE = re.compile(
    r"(?:\(\d{4}\s*update[^)]*\)|\(\d{2}/\d{2}\s*update[^)]*\)|\[[^\]]*update[^\]]*\]|【\d{4}\s*更新[^】]*】)",
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(r"\b(TBD|TODO|N/A|UNKNOWN)\b|待補|待確認|同上|略", re.IGNORECASE)
ASSERTION_VALUE_RE = re.compile(r"(?P<label>[^:：\n]{2,40})[:：]\s*(?P<values>[^\n]+)")
DATE_FORMAT_RE = re.compile(r"(yyyy[-/]MM[-/]dd|yyyy[-/]mm[-/]dd|HH:mm:ss|hh:mm:ss)")
PATH_RE = re.compile(r"(/\w[\w\-./{}]*)")
NUMBER_RE = re.compile(r"\b\d+\b")
FIELD_QUOTE_RE = re.compile(r"[\"“”「『](.+?)[\"”」』]")


TRAIT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "permission": ("permission", "role", "權限", "角色", "unauthorized", "forbidden"),
    "field_display": ("display", "顯示", "欄位", "field", "title", "label"),
    "state_transition": ("status", "state", "running", "paused", "calculating", "狀態"),
    "validation_rule": ("format", "validation", "驗證", "must", "必須", "not allow"),
    "date_time_rule": ("date", "time", "timezone", "時區", "日期", "時間"),
    "history_retention": ("retain", "retention", "30 days", "保留", "歷史", "history"),
    "import_export": ("import", "export", "download", "upload", "匯入", "匯出", "下載"),
    "integration_reference": ("api", "endpoint", "doc", "reference", "jira", "ticket"),
    "rename_only_change": ("rename", "改為", "shown as", "displayed as"),
    "localization": ("language", "翻譯", "中文", "english", "locale"),
    "ui_navigation": ("open", "page", "tab", "modal", "click", "頁面", "視窗", "tab"),
    "modal_interaction": ("modal", "popup", "tooltip", "hover", "彈窗"),
    "chart_display": ("chart", "bar", "axis", "scroll", "圖表", "柱狀圖"),
}

AXIS_VALUE_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "entry_source": ("audience list", "package overview", "列表", "概覽", "overview"),
    "creation_type": ("rule-based", "import-based", "rule create", "import create", "規則", "導入"),
    "operation_status": ("running", "paused", "calculating", "成功", "失敗", "已暫停", "正常運行"),
    "date_picker_mode": (
        "today",
        "yesterday",
        "last 7 days",
        "last 14 days",
        "last 30 days",
        "今天",
        "昨日",
        "過去 7 天",
        "過去 14 天",
        "過去 30 天",
    ),
    "interaction_type": ("click", "hover", "點擊", "hover"),
    "calculation_frequency": ("daily", "every 6 hours", "6 hours", "每天", "每6小時"),
    "comparison_outcome": ("increase", "decrease", "no change", "增加", "減少", "無變化"),
}

ROW_CATEGORY_HINTS = {
    "error_handling": ("error", "fail", "invalid", "denied", "unauthorized", "失敗", "錯誤", "拒絕"),
    "boundary": (
        "max",
        "min",
        "boundary",
        "limit",
        "format",
        "edge",
        "30",
        "23:59:59",
        "06:59:59",
        "邊界",
        "上限",
        "下限",
        "格式",
    ),
    "edge": ("mixed", "scroll", "cross", "empty", "different", "異動", "跨", "空", "混合"),
}

NOT_APPLICABLE_LABEL = QAAIHelperApplicabilityStatus.NOT_APPLICABLE.value
MANUAL_EXEMPT_LABEL = QAAIHelperApplicabilityStatus.MANUAL_EXEMPT.value
APPLICABLE_LABEL = QAAIHelperApplicabilityStatus.APPLICABLE.value
MAX_COMBINABLE_AXES_PER_GROUP = 2
MAX_CARTESIAN_ROWS_PER_GROUP = 12


def _slugify(value: str, default: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", str(value or "").strip().lower()).strip("-")
    if normalized:
        return normalized[:80]
    return default


def _stable_hash(parts: Sequence[str]) -> str:
    return sha1("||".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:10]


def _non_empty_lines(text: str) -> List[str]:
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def _normalize_bullet_text(text: str) -> str:
    value = str(text or "").strip()
    match = BULLET_RE.match(value)
    if match:
        return match.group(1).strip()
    return value


def _detect_language(text: str) -> str:
    content = str(text or "")
    if not content.strip():
        return "unknown"
    han_count = len(re.findall(r"[\u4e00-\u9fff]", content))
    alpha_count = len(re.findall(r"[A-Za-z]", content))
    if han_count and han_count >= alpha_count:
        return "zh"
    if alpha_count:
        return "en"
    return "unknown"


def _split_source_blocks(description: str, comments: Sequence[str]) -> List[Dict[str, Any]]:
    raw_blocks = re.split(r"\n{2,}", str(description or "").strip())
    comment_blocks = [str(comment or "").strip() for comment in comments if str(comment or "").strip()]
    blocks: List[Dict[str, Any]] = []
    for raw in list(raw_blocks) + comment_blocks:
        content = raw.strip()
        if not content:
            continue
        source_type = "comment" if content in comment_blocks else "description"
        lowered = content.lower()
        if "http://" in lowered or "https://" in lowered:
            source_type = "reference" if source_type != "comment" else source_type
        if "update" in lowered or "更新" in lowered:
            source_type = "update_note"
        title = _normalize_bullet_text(content.splitlines()[0])[:120]
        blocks.append(
            {
                "block_id": f"block-{len(blocks) + 1:03d}",
                "source_type": source_type,
                "language": _detect_language(content),
                "title": title,
                "content": content,
                "metadata": {
                    "line_count": len(_non_empty_lines(content)),
                },
            }
        )
    return blocks


def _extract_structured_refs(description: str, comments: Sequence[str]) -> Dict[str, Any]:
    merged = "\n".join([str(description or "").strip(), *[str(item or "").strip() for item in comments]])
    ticket_refs = sorted(set(match.group(0) for match in TICKET_REF_RE.finditer(merged)))
    version_tags = sorted(set(match.group(0).strip() for match in VERSION_TAG_RE.finditer(merged)))
    references = sorted(set(match.group(0).strip() for match in URL_RE.finditer(merged)))
    return {
        "ticket_refs": ticket_refs,
        "version_tags": version_tags,
        "references": references,
    }


def _extract_sections_from_text(text: str) -> Dict[str, str]:
    matches = list(SECTION_HEADING_RE.finditer(str(text or "")))
    if not matches:
        return {}
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = str(match.group("heading") or "").strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if "user story" in heading:
            key = "userStoryNarrative"
        elif "criteria" == heading:
            key = "criteria"
        elif "technical" in heading:
            key = "technicalSpecifications"
        else:
            key = "acceptanceCriteria"
        sections[key] = content
    return sections


def _extract_user_story_summary(summary: str, description: str) -> str:
    merged = "\n".join([str(summary or "").strip(), str(description or "").strip()]).strip()
    lines = _non_empty_lines(merged)
    as_line = next((line for line in lines if line.lower().startswith("as ")), "")
    want_line = next((line for line in lines if "i want" in line.lower()), "")
    so_line = next((line for line in lines if "so that" in line.lower()), "")
    if as_line or want_line or so_line:
        return "\n".join(value for value in [as_line, want_line, so_line] if value).strip()
    if summary:
        return f"As a user\nI want {summary.strip()}\nSo that the requirement can be validated"
    return ""


def _extract_acceptance_fallback(text: str) -> str:
    scenario_matches = list(SCENARIO_HEADING_RE.finditer(str(text or "")))
    if scenario_matches:
        blocks: List[str] = []
        for index, match in enumerate(scenario_matches):
            start = match.start()
            end = scenario_matches[index + 1].start() if index + 1 < len(scenario_matches) else len(text)
            blocks.append(text[start:end].strip())
        return "\n\n".join(blocks).strip()
    return ""


def _parse_bullet_items(text: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    pending_parent: Optional[Dict[str, Any]] = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        bullet_match = BULLET_RE.match(line)
        if bullet_match:
            item = {
                "text": bullet_match.group(1).strip(),
                "children": [],
            }
            items.append(item)
            pending_parent = item
            continue
        child_match = INDENTED_BULLET_RE.match(line)
        if child_match and pending_parent is not None:
            pending_parent["children"].append(child_match.group(2).strip())
            continue
        items.append({"text": line.strip(), "children": []})
        pending_parent = items[-1]
    return items


def _canonical_clause_match(pattern: re.Pattern[str], block: str) -> List[str]:
    return [match.group(1).strip() for match in pattern.finditer(str(block or "")) if match.group(1).strip()]


def _parse_acceptance_scenarios(text: str) -> List[Dict[str, Any]]:
    raw_text = str(text or "").strip()
    if not raw_text:
        return []
    matches = list(SCENARIO_HEADING_RE.finditer(raw_text))
    blocks: List[Tuple[str, str]] = []
    if matches:
        for index, match in enumerate(matches):
            title = match.group(1).strip() or f"Scenario {index + 1}"
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
            blocks.append((title, raw_text[start:end].strip()))
    else:
        blocks.append(("Scenario 1", raw_text))

    scenarios: List[Dict[str, Any]] = []
    for index, (title, body) in enumerate(blocks, start=1):
        given = _canonical_clause_match(GIVEN_RE, body)
        when = _canonical_clause_match(WHEN_RE, body)
        then = _canonical_clause_match(THEN_RE, body)
        and_lines = _canonical_clause_match(AND_RE, body)
        if not any([given, when, then, and_lines]):
            clauses = _non_empty_lines(body)
            if clauses:
                given = [clauses[0]]
                then = clauses[1:] or []
        scenarios.append(
            {
                "scenario_key": f"ac.scenario_{index:03d}",
                "title": title,
                "given": given,
                "when": when,
                "then": then,
                "and": and_lines,
                "raw_text": body,
                "order": index,
            }
        )
    return scenarios


def _detect_traits(texts: Iterable[str]) -> List[str]:
    content = "\n".join(str(text or "") for text in texts).lower()
    detected: List[str] = []
    for trait, keywords in TRAIT_KEYWORDS.items():
        if any(keyword.lower() in content for keyword in keywords):
            detected.append(trait)
    return sorted(set(detected))


def _extract_hard_facts(texts: Iterable[Tuple[str, str]]) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()
    for source_key, text in texts:
        content = str(text or "").strip()
        if not content:
            continue
        candidates: List[Tuple[str, str]] = []
        for match in DATE_FORMAT_RE.finditer(content):
            candidates.append(("format", match.group(1)))
        for match in PATH_RE.finditer(content):
            candidates.append(("path", match.group(1)))
        for match in FIELD_QUOTE_RE.finditer(content):
            candidates.append(("field_label", match.group(1)))
        values_match = ASSERTION_VALUE_RE.search(content)
        if values_match:
            candidates.append(("mapping", values_match.group("values").strip()))
        if not candidates:
            numbers = NUMBER_RE.findall(content)
            if numbers:
                candidates.extend(("number", number) for number in numbers[:4])
        for fact_type, value in candidates:
            key = (fact_type, value)
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                {
                    "fact_id": f"hf-{len(facts) + 1:03d}",
                    "type": fact_type,
                    "value": value,
                    "text": content,
                    "source_key": source_key,
                }
            )
    return facts


def _assertion_category(text: str) -> str:
    lowered = str(text or "").lower()
    for category, keywords in ROW_CATEGORY_HINTS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return category
    return "happy"


def _build_assertions(
    *,
    scenarios: Sequence[Dict[str, Any]],
    criteria_items: Sequence[Dict[str, Any]],
    technical_items: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    assertions: List[Dict[str, Any]] = []
    for scenario in scenarios:
        clause_index = 0
        for clause_type in ("given", "when", "then", "and"):
            for clause_text in scenario.get(clause_type, []):
                clause_index += 1
                source_key = f"{scenario['scenario_key']}.{clause_type}.{clause_index:03d}"
                assertions.append(
                    {
                        "assertion_id": f"as-{len(assertions) + 1:03d}",
                        "requirement_key": scenario["scenario_key"],
                        "source_key": source_key,
                        "scope": "acceptance_criteria",
                        "clause_type": clause_type,
                        "text": clause_text,
                        "category_hint": _assertion_category(clause_text),
                    }
                )
    for item in criteria_items:
        item_requirement_key = f"criteria.{_slugify(item['text'], f'item-{len(assertions) + 1}')}"
        assertions.append(
            {
                "assertion_id": f"as-{len(assertions) + 1:03d}",
                "requirement_key": item_requirement_key,
                "source_key": item_requirement_key,
                "scope": "criteria",
                "clause_type": "rule",
                "text": item["text"],
                "category_hint": _assertion_category(item["text"]),
            }
        )
        for child in item.get("children", []):
            child_requirement_key = f"criteria.{_slugify(child, f'item-{len(assertions) + 1}')}"
            assertions.append(
                {
                    "assertion_id": f"as-{len(assertions) + 1:03d}",
                    "requirement_key": child_requirement_key,
                    "source_key": child_requirement_key,
                    "scope": "criteria",
                    "clause_type": "rule",
                    "text": child,
                    "category_hint": _assertion_category(child),
                }
            )
    for item in technical_items:
        item_requirement_key = f"tech.{_slugify(item['text'], f'item-{len(assertions) + 1}')}"
        assertions.append(
            {
                "assertion_id": f"as-{len(assertions) + 1:03d}",
                "requirement_key": item_requirement_key,
                "source_key": item_requirement_key,
                "scope": "technical_specifications",
                "clause_type": "rule",
                "text": item["text"],
                "category_hint": _assertion_category(item["text"]),
            }
        )
        for child in item.get("children", []):
            child_requirement_key = f"tech.{_slugify(child, f'item-{len(assertions) + 1}')}"
            assertions.append(
                {
                    "assertion_id": f"as-{len(assertions) + 1:03d}",
                    "requirement_key": child_requirement_key,
                    "source_key": child_requirement_key,
                    "scope": "technical_specifications",
                    "clause_type": "rule",
                    "text": child,
                    "category_hint": _assertion_category(child),
                }
            )
    return assertions


def _project_constraints_for_section(
    section_title: str,
    section_clauses: Sequence[str],
    assertions: Sequence[Dict[str, Any]],
    traits: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    section_text = " ".join([section_title, *section_clauses]).lower()
    section_tokens = {token for token in re.findall(r"[a-z0-9\u4e00-\u9fff]+", section_text) if len(token) >= 2}
    relevant_constraints: List[Dict[str, Any]] = []
    relevant_assertions: List[Dict[str, Any]] = []
    for assertion in assertions:
        text = str(assertion.get("text") or "")
        lowered = text.lower()
        tokens = {token for token in re.findall(r"[a-z0-9\u4e00-\u9fff]+", lowered) if len(token) >= 2}
        trait_match = any(
            any(keyword.lower() in lowered for keyword in TRAIT_KEYWORDS.get(trait, ())) for trait in traits
        )
        overlap = bool(section_tokens.intersection(tokens))
        if assertion.get("requirement_key", "").startswith("ac.") or overlap or trait_match:
            relevant_constraints.append(
                {
                    "constraint_id": f"pc-{len(relevant_constraints) + 1:03d}",
                    "text": text,
                    "assertion_id": assertion["assertion_id"],
                    "source_key": assertion["source_key"],
                    "requirement_key": assertion["requirement_key"],
                    "scope": assertion["scope"],
                }
            )
            relevant_assertions.append(assertion)
    return relevant_constraints, relevant_assertions


def _extract_axis_candidates(
    texts: Sequence[Tuple[str, str]], section_assertions: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    axes: List[Dict[str, Any]] = []
    for source_key, text in texts:
        content = str(text or "").strip()
        if not content:
            continue
        match = ASSERTION_VALUE_RE.search(content)
        values: List[str] = []
        axis_key = ""
        label = ""
        if match:
            label = match.group("label").strip()
            raw_values = re.split(r"\s*(?:/|\||,|、)\s*", match.group("values").strip())
            values = [value.strip(" -") for value in raw_values if value.strip(" -")]
            axis_key = _slugify(label, "axis")
        if len(values) < 2:
            lowered = content.lower()
            for candidate_key, keywords in AXIS_VALUE_KEYWORDS.items():
                matched_values = [keyword for keyword in keywords if keyword.lower() in lowered]
                if len(set(matched_values)) >= 2:
                    axis_key = candidate_key
                    label = candidate_key.replace("_", " ")
                    values = list(dict.fromkeys(matched_values))
                    break
        if len(values) < 2:
            continue
        related_assertion_ids = [
            assertion["assertion_id"]
            for assertion in section_assertions
            if source_key == assertion["source_key"]
            or any(value.lower() in assertion["text"].lower() for value in values)
        ]
        axes.append(
            {
                "axis_key": axis_key or f"axis-{len(axes) + 1:03d}",
                "label": label or f"Axis {len(axes) + 1}",
                "values": list(dict.fromkeys(values)),
                "source_key": source_key,
                "assertion_refs": related_assertion_ids,
            }
        )
    deduped: Dict[str, Dict[str, Any]] = {}
    for axis in axes:
        signature = axis["axis_key"]
        if signature not in deduped or len(axis["values"]) > len(deduped[signature]["values"]):
            deduped[signature] = axis
    return list(deduped.values())


def _factorize_axes(axes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not axes:
        return []
    grouped_axes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for axis in axes:
        grouped_axes[str(axis.get("source_key") or axis.get("axis_key") or "").strip()].append(axis)
    groups: List[Dict[str, Any]] = []
    for source_key, component in grouped_axes.items():
        groups.append(
            {
                "group_key": f"rg-{len(groups) + 1:03d}",
                "label": component[0]["label"],
                "source_key": source_key,
                "axes": component,
            }
        )
    return groups


def _expand_row_group(
    *,
    group: Dict[str, Any],
    section_key: str,
    section_assertions: Sequence[Dict[str, Any]],
    overrides: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    axes = group.get("axes", [])
    if not axes:
        row_key = f"{section_key}.{group['group_key']}.row-001"
        override = overrides.get(row_key, {})
        return {
            **group,
            "rows": [
                {
                    "row_key": row_key,
                    "axis_values": {},
                    "assertion_refs": [assertion["assertion_id"] for assertion in section_assertions],
                    "applicability": override.get("status", APPLICABLE_LABEL),
                    "override_reason": override.get("reason"),
                }
            ],
        }

    axis_values = [axis["values"] for axis in axes]
    cartesian_size = 1
    for values in axis_values:
        cartesian_size *= max(1, len(values))
    rows: List[Dict[str, Any]] = []
    if len(axes) > MAX_COMBINABLE_AXES_PER_GROUP or cartesian_size > MAX_CARTESIAN_ROWS_PER_GROUP:
        row_index = 1
        for axis in axes:
            assertion_refs = sorted(set(axis.get("assertion_refs", []))) or [
                assertion["assertion_id"] for assertion in section_assertions
            ]
            for value in axis.get("values", []):
                row_key = f"{section_key}.{group['group_key']}.row-{row_index:03d}"
                row_index += 1
                override = overrides.get(row_key, {})
                rows.append(
                    {
                        "row_key": row_key,
                        "axis_values": {axis["axis_key"]: value},
                        "assertion_refs": assertion_refs,
                        "applicability": override.get("status", APPLICABLE_LABEL),
                        "override_reason": override.get("reason"),
                    }
                )
        return {**group, "rows": rows}

    for row_index, combination in enumerate(itertools.product(*axis_values), start=1):
        mapping = {axes[index]["axis_key"]: value for index, value in enumerate(combination)}
        assertion_refs = sorted(
            set(itertools.chain.from_iterable(axis.get("assertion_refs", []) for axis in axes))
        ) or [assertion["assertion_id"] for assertion in section_assertions]
        row_key = f"{section_key}.{group['group_key']}.row-{row_index:03d}"
        override = overrides.get(row_key, {})
        rows.append(
            {
                "row_key": row_key,
                "axis_values": mapping,
                "assertion_refs": assertion_refs,
                "applicability": override.get("status", APPLICABLE_LABEL),
                "override_reason": override.get("reason"),
            }
        )
    return {**group, "rows": rows}


def _dedupe_low_value_rows(groups: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped_groups: List[Dict[str, Any]] = []
    for group in groups:
        seen: set[Tuple[str, ...]] = set()
        rows: List[Dict[str, Any]] = []
        for row in group.get("rows", []):
            signature = tuple(
                [
                    json_compact_dumps(row.get("axis_values", {})),
                    ",".join(sorted(row.get("assertion_refs", []))),
                    row.get("applicability", APPLICABLE_LABEL),
                ]
            )
            if signature in seen:
                continue
            seen.add(signature)
            rows.append(row)
        deduped_groups.append({**group, "rows": rows})
    return deduped_groups


def _find_fact_refs_for_assertions(
    assertions: Sequence[Dict[str, Any]],
    hard_facts: Sequence[Dict[str, Any]],
) -> Dict[str, List[str]]:
    fact_refs_by_assertion: Dict[str, List[str]] = {}
    for assertion in assertions:
        text = assertion.get("text", "")
        refs = [
            fact["fact_id"]
            for fact in hard_facts
            if fact["source_key"] == assertion["source_key"]
            or str(fact.get("value") or "").lower() in str(text or "").lower()
            or str(fact.get("text") or "").lower() in str(text or "").lower()
        ]
        fact_refs_by_assertion[assertion["assertion_id"]] = list(dict.fromkeys(refs))
    return fact_refs_by_assertion


def _infer_missing_required_facts(
    *,
    row_assertions: Sequence[Dict[str, Any]],
    hard_fact_refs: Sequence[str],
    hard_facts: Sequence[Dict[str, Any]],
) -> List[str]:
    facts_by_id = {fact["fact_id"]: fact for fact in hard_facts}
    available_types = {
        str(facts_by_id[ref]["type"])
        for ref in hard_fact_refs
        if ref in facts_by_id and str(facts_by_id[ref].get("type") or "").strip()
    }
    missing: List[str] = []
    for assertion in row_assertions:
        text = str(assertion.get("text") or "")
        lowered = text.lower()
        if PLACEHOLDER_RE.search(text):
            missing.append("placeholder")
        if DATE_FORMAT_RE.search(text) and "format" not in available_types:
            missing.append("format")
        if (PATH_RE.search(text) or "path" in lowered or "endpoint" in lowered or "api" in lowered) and not (
            {"path", "mapping"} & available_types
        ):
            missing.append("path")
        if (
            FIELD_QUOTE_RE.search(text)
            or "shown as" in lowered
            or "displayed as" in lowered
            or "rename" in lowered
            or "改為" in text
        ) and not ({"field_label", "mapping"} & available_types):
            missing.append("field_label")
        if NUMBER_RE.search(text) and any(
            keyword in lowered
            for keyword in (
                "max",
                "min",
                "limit",
                "boundary",
                "days",
                "hours",
                "count",
                "records",
                "page size",
                "rows",
                "至少",
                "上限",
                "下限",
                "天",
                "小時",
                "筆",
            )
        ):
            if "number" not in available_types:
                missing.append("number")
    return list(dict.fromkeys(missing))


def _build_generation_items(
    *,
    ticket_key: str,
    section_id: str,
    section_title: str,
    row_groups: Sequence[Dict[str, Any]],
    assertions: Sequence[Dict[str, Any]],
    hard_facts: Sequence[Dict[str, Any]],
    fact_refs_by_assertion: Dict[str, List[str]],
    tail_start: int,
    source_revision: int,
    extension_seed_hints: Sequence[Dict[str, Any]] | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    assertion_lookup = {item["assertion_id"]: item for item in assertions}
    items: List[Dict[str, Any]] = []
    coverage_map: Dict[str, List[str]] = defaultdict(list)
    tail = tail_start
    covered_categories: set[str] = set()
    for group in row_groups:
        for row in group.get("rows", []):
            if row.get("applicability") == NOT_APPLICABLE_LABEL:
                continue
            row_assertions = [
                assertion_lookup[assertion_id]
                for assertion_id in row.get("assertion_refs", [])
                if assertion_id in assertion_lookup
            ]
            required_assertions = [
                {
                    "assertion_id": item["assertion_id"],
                    "text": item["text"],
                    "scope": item["scope"],
                }
                for item in row_assertions
            ]
            hard_fact_refs = sorted(
                set(
                    itertools.chain.from_iterable(
                        fact_refs_by_assertion.get(item["assertion_id"], []) for item in row_assertions
                    )
                )
            )
            missing_required_facts = _infer_missing_required_facts(
                row_assertions=row_assertions,
                hard_fact_refs=hard_fact_refs,
                hard_facts=hard_facts,
            )
            axis_text = ", ".join(f"{key}={value}" for key, value in (row.get("axis_values") or {}).items())
            base_text = row_assertions[0]["text"] if row_assertions else section_title
            category = _assertion_category(" ".join([base_text, axis_text]))
            covered_categories.add(category)
            item_key = f"{ticket_key}.{section_id.split('.')[-1]}.{tail:03d}"
            tail += 10
            item = {
                "item_key": item_key,
                "item_index": len(items),
                "seed_id": item_key,
                "row_key": row["row_key"],
                "row_group_key": group["group_key"],
                "section_id": section_id,
                "scenario_title": section_title,
                "coverage_category": category,
                "title_hint": base_text,
                "intent": base_text,
                "priority": "Medium",
                "required_assertions": required_assertions,
                "assertion_refs": [item["assertion_id"] for item in row_assertions],
                "hard_fact_refs": hard_fact_refs,
                "missing_required_facts": missing_required_facts,
                "precondition_hints": [
                    f"已進入 {section_title} 對應流程",
                    "已準備符合此案例條件的資料與角色",
                ],
                "step_hints": [
                    "進入對應頁面或操作入口",
                    f"執行案例操作：{base_text}",
                    "檢查系統畫面或回應結果",
                ],
                "expected_hints": [
                    axis_text or base_text,
                ],
                "source_revision": source_revision,
                "applicability": row["applicability"],
                "override_reason": row.get("override_reason"),
            }
            for assertion_ref in item["assertion_refs"]:
                coverage_map[assertion_ref].append(item_key)
            items.append(item)

    fallback_assertion = assertions[0] if assertions else None
    if not items and fallback_assertion is not None:
        category = _assertion_category(fallback_assertion["text"])
        item_key = f"{ticket_key}.{section_id.split('.')[-1]}.{tail:03d}"
        tail += 10
        item = {
            "item_key": item_key,
            "item_index": len(items),
            "seed_id": item_key,
            "row_key": f"{section_id}.baseline.{category}",
            "row_group_key": "baseline",
            "section_id": section_id,
            "scenario_title": section_title,
            "coverage_category": category,
            "title_hint": fallback_assertion["text"],
            "intent": fallback_assertion["text"],
            "priority": "Medium",
            "required_assertions": [
                {
                    "assertion_id": fallback_assertion["assertion_id"],
                    "text": fallback_assertion["text"],
                    "scope": fallback_assertion["scope"],
                }
            ],
            "assertion_refs": [fallback_assertion["assertion_id"]],
            "hard_fact_refs": fact_refs_by_assertion.get(fallback_assertion["assertion_id"], []),
            "missing_required_facts": _infer_missing_required_facts(
                row_assertions=[fallback_assertion],
                hard_fact_refs=fact_refs_by_assertion.get(fallback_assertion["assertion_id"], []),
                hard_facts=hard_facts,
            ),
            "precondition_hints": [
                f"已進入 {section_title} 對應流程",
                f"此案例需驗證 {category} 類型 coverage",
            ],
            "step_hints": [
                "進入對應頁面或操作入口",
                f"執行 {category} 類型檢查",
                "確認系統行為符合需求",
            ],
            "expected_hints": [fallback_assertion["text"]],
            "source_revision": source_revision,
            "applicability": APPLICABLE_LABEL,
            "override_reason": None,
        }
        coverage_map[fallback_assertion["assertion_id"]].append(item_key)
        items.append(item)

    for extension_hint in extension_seed_hints or []:
        item_key = f"{ticket_key}.{section_id.split('.')[-1]}.{tail:03d}"
        tail += 10
        title_hint = str(extension_hint.get("title_hint") or section_title).strip()
        if not title_hint:
            continue
        assertion_refs = [assertions[0]["assertion_id"]] if assertions else []
        required_assertions = (
            [
                {
                    "assertion_id": assertions[0]["assertion_id"],
                    "text": assertions[0]["text"],
                    "scope": assertions[0]["scope"],
                }
            ]
            if assertions
            else []
        )
        item = {
            "item_key": item_key,
            "item_index": len(items),
            "seed_id": item_key,
            "row_key": f"{section_id}.extension.{len(items) + 1:03d}",
            "row_group_key": "extension",
            "section_id": section_id,
            "scenario_title": section_title,
            "coverage_category": str(extension_hint.get("category") or "happy").strip() or "happy",
            "title_hint": title_hint,
            "intent": title_hint,
            "priority": "Medium",
            "required_assertions": required_assertions,
            "assertion_refs": assertion_refs,
            "hard_fact_refs": [],
            "missing_required_facts": [],
            "precondition_hints": list(extension_hint.get("precondition_hints") or []),
            "step_hints": list(extension_hint.get("step_hints") or []),
            "expected_hints": list(extension_hint.get("expected_hints") or []),
            "source_revision": source_revision,
            "applicability": APPLICABLE_LABEL,
            "override_reason": "team_extension",
        }
        for assertion_ref in assertion_refs:
            coverage_map.setdefault(assertion_ref, []).append(item_key)
        items.append(item)
    return items, dict(coverage_map)


def _estimate_token_size(section_payload: Dict[str, Any]) -> int:
    return max(1, len(json_compact_dumps(section_payload)) // 4)


def _prepare_plan_context(content: Dict[str, Any]) -> Dict[str, Any]:
    criteria_items = _parse_bullet_items(str(content.get("criteria") or ""))
    technical_items = _parse_bullet_items(str(content.get("technicalSpecifications") or ""))
    scenarios = _parse_acceptance_scenarios(str(content.get("acceptanceCriteria") or ""))
    traits = _detect_traits(
        [
            str(content.get("criteria") or ""),
            str(content.get("technicalSpecifications") or ""),
            str(content.get("acceptanceCriteria") or ""),
        ]
    )
    hard_facts = _extract_hard_facts(
        list((f"criteria.{index:03d}", item["text"]) for index, item in enumerate(criteria_items, start=1))
        + list((f"tech.{index:03d}", item["text"]) for index, item in enumerate(technical_items, start=1))
        + list((scenario["scenario_key"], scenario["raw_text"]) for scenario in scenarios)
    )
    assertions = _build_assertions(
        scenarios=scenarios,
        criteria_items=criteria_items,
        technical_items=technical_items,
    )
    fact_refs_by_assertion = _find_fact_refs_for_assertions(assertions, hard_facts)
    return {
        "criteria_items": criteria_items,
        "technical_items": technical_items,
        "scenarios": scenarios,
        "detected_traits": traits,
        "hard_facts": hard_facts,
        "assertions": assertions,
        "fact_refs_by_assertion": fact_refs_by_assertion,
    }


def _rebuild_coverage_index(sections: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    coverage_index: Dict[str, List[str]] = defaultdict(list)
    for section in sections:
        for item in section.get("generation_items", []):
            for assertion_ref in item.get("assertion_refs", []):
                coverage_index[str(assertion_ref)].append(item["item_key"])
    return dict(coverage_index)


def _compact_projected_constraints(constraints: Sequence[Any]) -> List[str]:
    compacted: List[str] = []
    for item in constraints:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            compacted.append(text)
    return compacted


def _compact_assertion_catalog(assertions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for item in assertions:
        assertion_id = str(item.get("assertion_id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not assertion_id or not text:
            continue
        catalog.append(
            {
                "assertion_id": assertion_id,
                "text": text,
                "scope": str(item.get("scope") or "").strip(),
            }
        )
    return catalog


def _compact_axes(axes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "axis_key": str(axis.get("axis_key") or "").strip(),
            "label": str(axis.get("label") or "").strip(),
            "values": list(axis.get("values") or []),
        }
        for axis in axes
        if str(axis.get("axis_key") or "").strip()
    ]


def _compact_row_groups(row_groups: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    for group in row_groups:
        compacted.append(
            {
                "group_key": str(group.get("group_key") or "").strip(),
                "label": str(group.get("label") or "").strip(),
                "axes": _compact_axes(group.get("axes") or []),
                "rows": [
                    {
                        "row_key": str(row.get("row_key") or "").strip(),
                        "axis_values": dict(row.get("axis_values") or {}),
                        "applicability": row.get("applicability", APPLICABLE_LABEL),
                        "override_reason": row.get("override_reason"),
                    }
                    for row in (group.get("rows") or [])
                    if str(row.get("row_key") or "").strip()
                ],
            }
        )
    return compacted


def _compact_generation_items(generation_items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compacted: List[Dict[str, Any]] = []
    for item in generation_items:
        compacted.append(
            {
                "item_key": item["item_key"],
                "item_index": item.get("item_index"),
                "seed_id": item.get("seed_id"),
                "row_key": item.get("row_key"),
                "row_group_key": item.get("row_group_key"),
                "section_id": item.get("section_id"),
                "scenario_title": item.get("scenario_title"),
                "coverage_category": item.get("coverage_category"),
                "title_hint": item.get("title_hint"),
                "intent": item.get("intent"),
                "priority": item.get("priority"),
                "assertion_refs": list(item.get("assertion_refs") or []),
                "hard_fact_refs": list(item.get("hard_fact_refs") or []),
                "missing_required_facts": list(item.get("missing_required_facts") or []),
                "precondition_hints": list(item.get("precondition_hints") or []),
                "step_hints": list(item.get("step_hints") or []),
                "expected_hints": list(item.get("expected_hints") or []),
                "applicability": item.get("applicability", APPLICABLE_LABEL),
                "override_reason": item.get("override_reason"),
            }
        )
    return compacted


def _compact_section_for_persistence(section: Dict[str, Any]) -> Dict[str, Any]:
    generation_items = _compact_generation_items(section.get("generation_items") or [])
    return {
        "section_id": section.get("section_id"),
        "scenario_key": section.get("scenario_key"),
        "scenario_title": section.get("scenario_title"),
        "middle": section.get("middle"),
        "matrix": {
            "row_groups": _compact_row_groups(((section.get("matrix") or {}).get("row_groups") or [])),
        },
        "generation_budget": {
            **dict(section.get("generation_budget") or {}),
            "planned_row_count": len(generation_items),
        },
    }


def _build_sections_from_context(
    *,
    ticket_key: str,
    canonical_revision_id: int,
    context: Dict[str, Any],
    counter_settings: Dict[str, Any],
    applicability_overrides: Dict[str, Dict[str, Any]],
    team_extensions: Sequence[Dict[str, Any]] | None = None,
    scenario_filter_keys: Optional[set[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    middle = int(str(counter_settings.get("middle") or "010"))
    tail_start = int(str(counter_settings.get("tail") or "010"))
    sections: List[Dict[str, Any]] = []
    unresolved_rows: List[str] = []

    scenarios = context["scenarios"]
    traits = context["detected_traits"]
    assertions = context["assertions"]
    hard_facts = context["hard_facts"]
    fact_refs_by_assertion = context["fact_refs_by_assertion"]

    for scenario_index, scenario in enumerate(scenarios, start=1):
        if scenario_filter_keys and scenario["scenario_key"] not in scenario_filter_keys:
            continue
        scoped_extensions = [
            extension
            for extension in (team_extensions or [])
            if not extension.get("scenario_key") or extension.get("scenario_key") == scenario["scenario_key"]
        ]
        section_traits = sorted(
            set(traits).union(
                str(trait).strip()
                for extension in scoped_extensions
                for trait in (extension.get("traits") or [])
                if str(trait).strip()
            )
        )
        section_middle = middle + (scenario_index - 1) * 10
        section_suffix = f"{section_middle:03d}"
        section_id = f"{ticket_key}.{section_suffix}"
        section_clauses = [
            *scenario.get("given", []),
            *scenario.get("when", []),
            *scenario.get("then", []),
            *scenario.get("and", []),
        ]
        projected_constraints, section_assertions = _project_constraints_for_section(
            section_title=scenario["title"],
            section_clauses=section_clauses,
            assertions=assertions,
            traits=section_traits,
        )
        for extension in scoped_extensions:
            for constraint_text in extension.get("constraints") or []:
                normalized_constraint = str(constraint_text or "").strip()
                if not normalized_constraint:
                    continue
                projected_constraints.append(
                    {
                        "constraint_id": f"pc-ext-{len(projected_constraints) + 1:03d}",
                        "text": normalized_constraint,
                        "assertion_id": None,
                        "source_key": "team_extension",
                        "requirement_key": scenario["scenario_key"],
                        "scope": "team_extension",
                    }
                )
        axis_sources = [(item["source_key"], item["text"]) for item in projected_constraints]
        axes = _extract_axis_candidates(axis_sources, section_assertions)
        row_groups = _factorize_axes(axes)
        if not row_groups:
            row_groups = [
                {
                    "group_key": "rg-001",
                    "label": scenario["title"],
                    "axes": [],
                }
            ]
        expanded_groups = [
            _expand_row_group(
                group=group,
                section_key=section_id,
                section_assertions=section_assertions,
                overrides=applicability_overrides,
            )
            for group in row_groups
        ]
        deduped_groups = _dedupe_low_value_rows(expanded_groups)
        for group in deduped_groups:
            for row in group.get("rows", []):
                if row.get("applicability") not in {
                    APPLICABLE_LABEL,
                    NOT_APPLICABLE_LABEL,
                    MANUAL_EXEMPT_LABEL,
                }:
                    unresolved_rows.append(row["row_key"])
        generation_items, _section_coverage = _build_generation_items(
            ticket_key=ticket_key,
            section_id=section_id,
            section_title=scenario["title"],
            row_groups=deduped_groups,
            assertions=section_assertions,
            hard_facts=hard_facts,
            fact_refs_by_assertion=fact_refs_by_assertion,
            tail_start=tail_start,
            source_revision=canonical_revision_id,
            extension_seed_hints=[
                hint for extension in scoped_extensions for hint in (extension.get("seed_hints") or [])
            ],
        )
        sections.append(
            {
                "section_id": section_id,
                "scenario_key": scenario["scenario_key"],
                "scenario_title": scenario["title"],
                "middle": section_suffix,
                "given": scenario.get("given", []),
                "when": scenario.get("when", []),
                "then": scenario.get("then", []),
                "and": scenario.get("and", []),
                "detected_traits": section_traits,
                "projected_constraints": projected_constraints,
                "team_extensions": scoped_extensions,
                "hard_facts": [
                    fact
                    for fact in hard_facts
                    if fact["source_key"] == scenario["scenario_key"]
                    or fact["source_key"].startswith("criteria.")
                    or fact["source_key"].startswith("tech.")
                ],
                "assertions": section_assertions,
                "matrix": {
                    "axes": axes,
                    "row_groups": deduped_groups,
                },
                "generation_items": generation_items,
                "generation_budget": {
                    "planned_row_count": len(generation_items),
                    "estimated_prompt_tokens": _estimate_token_size(
                        {
                            "scenario_title": scenario["title"],
                            "generation_items": generation_items,
                            "constraints": projected_constraints,
                        }
                    ),
                    "estimated_output_tokens": max(1, len(generation_items) * 160),
                },
            }
        )
    return sections, unresolved_rows


class QAAIHelperPlanner:
    def resolve_raw_sources(
        self,
        *,
        summary: str,
        description: str,
        comments: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        comment_list = [str(item or "").strip() for item in (comments or []) if str(item or "").strip()]
        source_blocks = _split_source_blocks(description=description, comments=comment_list)
        refs = _extract_structured_refs(description=description, comments=comment_list)
        language_variants: Dict[str, List[str]] = defaultdict(list)
        for block in source_blocks:
            language_variants[block["language"]].append(block["block_id"])
        return {
            "summary": str(summary or "").strip(),
            "description": str(description or "").strip(),
            "comments": comment_list,
            "source_blocks": source_blocks,
            "language_variants": dict(language_variants),
            "version_tags": refs["version_tags"],
            "references": refs["references"] + refs["ticket_refs"],
        }

    def suggest_canonical_content(
        self,
        *,
        summary: str,
        description: str,
        canonical_language: Optional[str],
        raw_source_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        sections = _extract_sections_from_text(description)
        suggestion = {
            "userStoryNarrative": sections.get("userStoryNarrative")
            or _extract_user_story_summary(summary, description),
            "criteria": sections.get("criteria") or str(description or "").strip(),
            "technicalSpecifications": sections.get("technicalSpecifications") or "unknown",
            "acceptanceCriteria": sections.get("acceptanceCriteria")
            or _extract_acceptance_fallback(description)
            or "unknown",
            "assumptions": [],
            "unknowns": ["請確認缺漏的 canonical sections"]
            if "unknown" in {sections.get("technicalSpecifications"), sections.get("acceptanceCriteria")}
            else [],
            "rawSourceMetadata": {
                **raw_source_metadata,
                "canonical_language": canonical_language,
            },
        }
        return suggestion

    def validate_canonical_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        missing_sections: List[str] = []
        missing_fields: List[str] = []
        unresolved_items: List[str] = []
        user_story = str(content.get("userStoryNarrative") or "").strip()
        criteria = str(content.get("criteria") or "").strip()
        technical = str(content.get("technicalSpecifications") or "").strip()
        acceptance = str(content.get("acceptanceCriteria") or "").strip()
        mapping = {
            "userStoryNarrative": user_story,
            "criteria": criteria,
            "technicalSpecifications": technical,
            "acceptanceCriteria": acceptance,
        }
        for key, value in mapping.items():
            if not value:
                missing_sections.append(key)
        if user_story and not re.search(r"(?im)^\s*as\s+", user_story):
            missing_fields.append("userStoryNarrative.as_a")
        if user_story and "i want" not in user_story.lower():
            missing_fields.append("userStoryNarrative.i_want")
        if user_story and "so that" not in user_story.lower():
            missing_fields.append("userStoryNarrative.so_that")
        for key, value in mapping.items():
            if value and PLACEHOLDER_RE.search(value):
                unresolved_items.append(key)
        assumptions = [str(item).strip() for item in content.get("assumptions", []) if str(item).strip()]
        unknowns = [str(item).strip() for item in content.get("unknowns", []) if str(item).strip()]
        if not assumptions and not unknowns and unresolved_items:
            quality_level = "low"
        elif missing_sections:
            quality_level = "low"
        elif missing_fields or unresolved_items:
            quality_level = "medium"
        else:
            quality_level = "high"
        return {
            "missing_sections": missing_sections,
            "missing_fields": missing_fields,
            "unresolved_items": unresolved_items,
            "quality_level": quality_level,
            "override_required": bool(unresolved_items and not (assumptions or unknowns)),
        }

    def apply_requirement_delta(
        self,
        *,
        content: Dict[str, Any],
        delta: Dict[str, Any],
    ) -> Dict[str, Any]:
        updated = deepcopy(content)
        target_scope = str(delta.get("target_scope") or "").strip()
        proposed_content = deepcopy(delta.get("proposed_content") or {})
        delta_type = str(delta.get("delta_type") or "").strip()
        if target_scope == "Acceptance Criteria":
            scenarios = _parse_acceptance_scenarios(str(updated.get("acceptanceCriteria") or ""))
            scenario_key = str(delta.get("target_scenario_key") or "").strip()
            if delta_type == "add":
                title = str(proposed_content.get("title") or f"Scenario {len(scenarios) + 1}").strip()
                body = str(proposed_content.get("raw_text") or proposed_content.get("text") or "").strip()
                scenarios.append(
                    {
                        "scenario_key": scenario_key or f"ac.scenario_{len(scenarios) + 1:03d}",
                        "title": title,
                        "given": _canonical_clause_match(GIVEN_RE, body),
                        "when": _canonical_clause_match(WHEN_RE, body),
                        "then": _canonical_clause_match(THEN_RE, body),
                        "and": _canonical_clause_match(AND_RE, body),
                        "raw_text": body,
                        "order": len(scenarios) + 1,
                    }
                )
            else:
                kept: List[Dict[str, Any]] = []
                for scenario in scenarios:
                    if scenario["scenario_key"] != scenario_key:
                        kept.append(scenario)
                        continue
                    if delta_type == "modify":
                        scenario["title"] = str(proposed_content.get("title") or scenario["title"]).strip()
                        raw_text = str(
                            proposed_content.get("raw_text") or proposed_content.get("text") or scenario["raw_text"]
                        ).strip()
                        scenario["raw_text"] = raw_text
                        scenario["given"] = _canonical_clause_match(GIVEN_RE, raw_text)
                        scenario["when"] = _canonical_clause_match(WHEN_RE, raw_text)
                        scenario["then"] = _canonical_clause_match(THEN_RE, raw_text)
                        scenario["and"] = _canonical_clause_match(AND_RE, raw_text)
                        kept.append(scenario)
                scenarios = kept
            blocks: List[str] = []
            for index, scenario in enumerate(scenarios, start=1):
                body_lines: List[str] = []
                for clause_type in ("given", "when", "then", "and"):
                    for value in scenario.get(clause_type, []):
                        body_lines.append(f"{clause_type.title()} {value}")
                blocks.append(f"Scenario {index}: {scenario['title']}\n" + "\n".join(body_lines))
            updated["acceptanceCriteria"] = "\n\n".join(blocks).strip()
            return updated

        key_map = {
            "User Story Narrative": "userStoryNarrative",
            "Criteria": "criteria",
            "Technical Specifications": "technicalSpecifications",
        }
        section_key = key_map.get(target_scope)
        if not section_key:
            return updated
        current_text = str(updated.get(section_key) or "").strip()
        proposed_text = str(proposed_content.get("text") or "").strip()
        if delta_type == "add":
            updated[section_key] = f"{current_text}\n- {proposed_text}".strip()
        elif delta_type == "delete":
            updated[section_key] = "\n".join(
                line for line in current_text.splitlines() if proposed_text and proposed_text not in line
            ).strip()
        elif delta_type == "modify":
            target_requirement_key = str(delta.get("target_requirement_key") or "").strip()
            if target_requirement_key and proposed_content.get("original_text"):
                updated[section_key] = current_text.replace(
                    str(proposed_content.get("original_text") or ""),
                    proposed_text,
                )
            else:
                updated[section_key] = proposed_text or current_text
        return updated

    def analyze_requirement_delta_impact(
        self,
        *,
        previous_content: Dict[str, Any],
        updated_content: Dict[str, Any],
        delta: Dict[str, Any],
    ) -> Dict[str, Any]:
        target_scope = str(delta.get("target_scope") or "").strip()
        if target_scope != "Acceptance Criteria":
            return {
                "mode": "full",
                "reason": "cross_section_scope",
                "impacted_scenario_keys": [],
                "removed_scenario_keys": [],
            }

        previous_scenarios = _parse_acceptance_scenarios(str(previous_content.get("acceptanceCriteria") or ""))
        updated_scenarios = _parse_acceptance_scenarios(str(updated_content.get("acceptanceCriteria") or ""))
        previous_keys = [item["scenario_key"] for item in previous_scenarios]
        updated_keys = [item["scenario_key"] for item in updated_scenarios]

        earliest_diff: Optional[int] = None
        for index in range(max(len(previous_keys), len(updated_keys))):
            before = previous_keys[index] if index < len(previous_keys) else None
            after = updated_keys[index] if index < len(updated_keys) else None
            if before != after:
                earliest_diff = index
                break

        if earliest_diff is None:
            scenario_key = str(delta.get("target_scenario_key") or "").strip()
            if scenario_key and scenario_key in updated_keys:
                return {
                    "mode": "scoped",
                    "reason": "single_scenario_modify",
                    "impacted_scenario_keys": [scenario_key],
                    "removed_scenario_keys": [],
                }
            return {
                "mode": "full",
                "reason": "unresolved_acceptance_change",
                "impacted_scenario_keys": updated_keys,
                "removed_scenario_keys": [],
            }

        impacted_scenario_keys = updated_keys[earliest_diff:]
        removed_scenario_keys = [key for key in previous_keys[earliest_diff:] if key not in updated_keys]
        return {
            "mode": "scoped",
            "reason": "scenario_sequence_changed",
            "impacted_scenario_keys": impacted_scenario_keys,
            "removed_scenario_keys": removed_scenario_keys,
            "earliest_diff_index": earliest_diff,
        }

    def build_plan(
        self,
        *,
        ticket_key: str,
        canonical_revision_id: int,
        canonical_language: str,
        content: Dict[str, Any],
        counter_settings: Dict[str, Any],
        applicability_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
        selected_references: Optional[Dict[str, Any]] = None,
        team_extensions: Optional[Sequence[Dict[str, Any]]] = None,
        previous_plan: Optional[Dict[str, Any]] = None,
        delta_impact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        context = _prepare_plan_context(content)
        overrides = applicability_overrides or {}
        scoped_mode = bool(previous_plan and delta_impact and delta_impact.get("mode") == "scoped")
        if scoped_mode:
            impacted_keys = set(delta_impact.get("impacted_scenario_keys") or [])
            rebuilt_sections, unresolved_rows = _build_sections_from_context(
                ticket_key=ticket_key,
                canonical_revision_id=canonical_revision_id,
                context=context,
                counter_settings=counter_settings,
                applicability_overrides=overrides,
                team_extensions=team_extensions,
                scenario_filter_keys=impacted_keys or None,
            )
            previous_sections_by_key = {
                section.get("scenario_key"): deepcopy(section)
                for section in (previous_plan or {}).get("sections", [])
                if section.get("scenario_key")
            }
            rebuilt_sections_by_key = {section["scenario_key"]: section for section in rebuilt_sections}
            sections = []
            for scenario in context["scenarios"]:
                scenario_key = scenario["scenario_key"]
                section = rebuilt_sections_by_key.get(scenario_key)
                if section is None:
                    section = previous_sections_by_key.get(scenario_key)
                if section is not None:
                    sections.append(section)
        else:
            sections, unresolved_rows = _build_sections_from_context(
                ticket_key=ticket_key,
                canonical_revision_id=canonical_revision_id,
                context=context,
                counter_settings=counter_settings,
                applicability_overrides=overrides,
                team_extensions=team_extensions,
            )

        all_generation_items = [item for section in sections for item in section.get("generation_items", [])]
        coverage_index = _rebuild_coverage_index(sections)
        impact_summary = {
            "sections": len(sections),
            "generation_items": len(all_generation_items),
            "unresolved_rows": unresolved_rows,
            "selected_reference_count": len((selected_references or {}).get("section_references", {})),
            "replanning_mode": "scoped" if scoped_mode else "full",
            "impacted_scenario_keys": list((delta_impact or {}).get("impacted_scenario_keys") or []),
            "removed_scenario_keys": list((delta_impact or {}).get("removed_scenario_keys") or []),
        }
        return {
            "canonical_revision_id": canonical_revision_id,
            "canonical_language": canonical_language,
            "counter_settings": counter_settings,
            "criteria_items": context["criteria_items"],
            "technical_items": context["technical_items"],
            "scenarios": context["scenarios"],
            "detected_traits": context["detected_traits"],
            "hard_facts": context["hard_facts"],
            "assertions": context["assertions"],
            "sections": sections,
            "generation_items": all_generation_items,
            "coverage_index": coverage_index,
            "selected_references": selected_references or {"section_references": {}},
            "team_extensions": list(team_extensions or []),
            "impact_summary": impact_summary,
            "plan_signature": _stable_hash(
                [
                    str(canonical_revision_id),
                    json_compact_dumps(counter_settings),
                    json_compact_dumps(overrides),
                    json_compact_dumps(selected_references or {}),
                    json_compact_dumps(team_extensions or []),
                ]
            ),
            "derived_at": datetime.utcnow().isoformat(),
        }

    def build_persistable_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        sections = [_compact_section_for_persistence(section) for section in (plan.get("sections") or [])]
        generation_item_keys = [
            item["item_key"] for item in (plan.get("generation_items") or []) if str(item.get("item_key") or "").strip()
        ]
        return {
            "canonical_revision_id": plan.get("canonical_revision_id"),
            "canonical_language": plan.get("canonical_language"),
            "counter_settings": dict(plan.get("counter_settings") or {}),
            "sections": sections,
            "generation_items": generation_item_keys,
            "selected_references": dict(plan.get("selected_references") or {"section_references": {}}),
            "team_extensions": list(plan.get("team_extensions") or []),
            "impact_summary": dict(plan.get("impact_summary") or {}),
            "plan_signature": plan.get("plan_signature"),
            "derived_at": plan.get("derived_at"),
        }

    def rebuild_coverage_index(self, sections: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
        return _rebuild_coverage_index(sections)

    def compute_complexity(
        self, section: Dict[str, Any], history_failures: int = 0, repair_failure_history: bool = False
    ) -> Dict[str, Any]:
        generation_budget = section.get("generation_budget", {})
        seed_count = len(section.get("generation_items", []))
        token_estimate = int(generation_budget.get("estimated_prompt_tokens", 0)) + int(
            generation_budget.get("estimated_output_tokens", 0)
        )
        projected_constraints_count = len(section.get("projected_constraints", []))
        detected_traits_count = len(section.get("detected_traits", []))
        selected_references_count = len(((section.get("selected_references") or {}).get("selected_references") or []))
        score = 0
        if seed_count > 6:
            score += 2
        if token_estimate > 1800:
            score += 2
        if projected_constraints_count > 8:
            score += 2
        if detected_traits_count > 4:
            score += 1
        if selected_references_count > 3:
            score += 1
        if history_failures:
            score += min(history_failures, 2)
        if repair_failure_history:
            score += 2

        hard_trigger = (
            seed_count >= 10
            or token_estimate > 2800
            or history_failures >= 2
            or repair_failure_history
            or any(item.get("missing_required_facts") for item in section.get("generation_items", []))
        )
        if hard_trigger:
            batch_mode = "one-seed-per-call"
        elif score <= 4:
            batch_mode = "section-batch"
        elif score <= 8:
            batch_mode = "row-group-batch"
        else:
            batch_mode = "one-seed-per-call"
        return {
            "score": score,
            "batch_mode": batch_mode,
            "seed_count": seed_count,
            "token_estimate": token_estimate,
            "projected_constraints_count": projected_constraints_count,
            "detected_traits_count": detected_traits_count,
            "selected_references_count": selected_references_count,
            "history_failures": history_failures,
            "repair_failure_history": repair_failure_history,
            "hard_trigger": hard_trigger,
        }

    def build_model_facing_payload(
        self,
        *,
        ticket_key: str,
        output_language: str,
        section: Dict[str, Any],
        section_references: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        complexity = self.compute_complexity(section)
        selected_references = section_references or []
        generation_items = []
        for item in section.get("generation_items", []):
            if item.get("applicability") == NOT_APPLICABLE_LABEL:
                continue
            generation_items.append(
                {
                    "item_index": len(generation_items),
                    "item_key": item["item_key"],
                    "category": item["coverage_category"],
                    "title_hint": item["title_hint"],
                    "intent": item["intent"],
                    "priority": item.get("priority", "Medium"),
                    "required_assertions": item.get("required_assertions", []),
                    "precondition_hints": item.get("precondition_hints", []),
                    "step_hints": item.get("step_hints", []),
                    "expected_hints": item.get("expected_hints", []),
                    "hard_fact_refs": item.get("hard_fact_refs", []),
                    "missing_required_facts": item.get("missing_required_facts", []),
                }
            )
        return {
            "contract_version": "helper.model_generation.v1",
            "ticket_key": ticket_key,
            "output_language": output_language,
            "section_summary": {
                "section_id": section["section_id"],
                "scenario_key": section["scenario_key"],
                "scenario_title": section["scenario_title"],
                "given": section.get("given", []),
                "when": section.get("when", []),
                "then": section.get("then", []),
                "and": section.get("and", []),
            },
            "shared_constraints": section.get("projected_constraints", []),
            "selected_references": selected_references,
            "generation_items": generation_items,
            "generation_rules": {
                "min_steps": 3,
                "min_preconditions": 1,
                "complexity": complexity,
            },
        }
