#!/usr/bin/env python3
"""Jira -> deterministic parser -> YAML."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.jira_client import JiraAuthManager, JiraIssueManager


SECTION_ALIASES = {
    "menu": "Menu",
    "功能路徑": "Menu",
    "user story narrative": "User Story Narrative",
    "user story": "User Story Narrative",
    "使用者故事敘述": "User Story Narrative",
    "使用者故事": "User Story Narrative",
    "criteria": "Criteria",
    "technical specifications": "Technical Specifications",
    "technical specification": "Technical Specifications",
    "技術規格": "Technical Specifications",
    "acceptance criteria": "Acceptance Criteria",
    "驗收標準": "Acceptance Criteria",
}

SCENARIO_RE = re.compile(r"^\s*scenario\s+\d+\s*:\s*(.+?)\s*$", re.IGNORECASE)
GHERKIN_RE = re.compile(r"^\s*(Given|When|Then|And|But)\b[:\s]*(.*)$", re.IGNORECASE)
BULLET_RE = re.compile(r"^(?P<stars>\*+)\s+(?P<text>.+?)\s*$")
HEADING_RE = re.compile(r"^\s*h(?P<level>[1-6])\.\s*(?P<title>.+?)\s*$", re.IGNORECASE)
SEPARATOR_RE = re.compile(r"^\s*[-=]{4,}\s*$")
BRACKET_HEADING_RE = re.compile(r"^【(?P<label>[^】]+)】\s*(?P<rest>.*)$")
LABEL_SPLIT_RE = re.compile(r"^(?P<label>[^:：]{1,120})[:：]\s*(?P<rest>.*)$")
TRAILING_META_RE = re.compile(r"\s*[（(\[].*?[）)\]]\s*$")


@dataclass
class BulletNode:
    level: int
    text: str
    children: List["BulletNode"] = field(default_factory=list)
    continuations: List[str] = field(default_factory=list)

    def full_text(self) -> str:
        parts = [self.text] + self.continuations
        return " ".join(p for p in parts if p).strip()


def _coerce_jira_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _coerce_jira_text(item)).strip())
    if isinstance(value, dict):
        parts: List[str] = []

        text = value.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())

        content = value.get("content")
        if isinstance(content, list):
            for child in content:
                child_text = _coerce_jira_text(child)
                if child_text.strip():
                    parts.append(child_text.strip())

        if parts:
            return "\n".join(parts)

        return "\n".join(part for v in value.values() if (part := _coerce_jira_text(v)).strip())
    return str(value)


def fetch_issue(ticket_key: str, include_comments: bool) -> Dict[str, Any]:
    issue_manager = JiraIssueManager(JiraAuthManager())
    issue = issue_manager.get_issue(ticket_key, fields=["summary", "description", "comment"])
    if not issue:
        raise RuntimeError(f"找不到 Jira ticket: {ticket_key}")

    fields = issue.get("fields") or {}
    comments: List[str] = []

    if include_comments:
        for item in (fields.get("comment") or {}).get("comments", []):
            body = _coerce_jira_text(item.get("body"))
            if body.strip():
                comments.append(body.strip())

    return {
        "summary": _coerce_jira_text(fields.get("summary")).strip(),
        "description": _coerce_jira_text(fields.get("description")).strip(),
        "comments": comments,
    }


def remove_strikethrough(text: str) -> str:
    return re.sub(r"~~.*?~~", "", text, flags=re.DOTALL)


def clean_inline(text: str) -> str:
    value = str(text or "")
    value = value.replace("\u00a0", " ")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"\{color:[^}]+\}", "", value, flags=re.IGNORECASE)
    value = value.replace("{color}", "")
    value = value.replace("{quote}", "")
    value = value.replace("{*}", "")
    value = value.replace("{{{", "")
    value = value.replace("}}}", "")
    value = value.replace("{{", "")
    value = value.replace("}}", "")
    value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", value)
    value = re.sub(r"_(.+?)_", r"\1", value)
    value = re.sub(r"`(.+?)`", r"\1", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_heading_title(raw_title: str) -> str:
    title = clean_inline(raw_title).strip()
    candidates = [title]

    stripped_title = TRAILING_META_RE.sub("", title).strip()
    if stripped_title and stripped_title != title:
        candidates.append(stripped_title)

    for candidate in candidates:
        lower = candidate.lower()
        for alias, canonical in SECTION_ALIASES.items():
            if lower == alias:
                return canonical
    return title


def split_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current_section: Optional[str] = None

    for raw_line in text.splitlines():
        if SEPARATOR_RE.match(raw_line):
            continue

        heading = HEADING_RE.match(raw_line.strip())
        if heading:
            title = normalize_heading_title(heading.group("title"))
            if title in {
                "Menu",
                "User Story Narrative",
                "Criteria",
                "Technical Specifications",
                "Acceptance Criteria",
            }:
                current_section = title
                sections.setdefault(current_section, [])
                continue

        if current_section is None:
            continue

        sections[current_section].append(raw_line.rstrip())

    return sections


def parse_bullet_tree(lines: List[str]) -> List[BulletNode]:
    roots: List[BulletNode] = []
    stack: List[BulletNode] = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if SEPARATOR_RE.match(line):
            continue
        if HEADING_RE.match(line.strip()):
            continue

        bullet = BULLET_RE.match(line.lstrip())
        if bullet:
            level = len(bullet.group("stars"))
            text = clean_inline(bullet.group("text"))
            if not text:
                continue

            node = BulletNode(level=level, text=text)

            while stack and stack[-1].level >= level:
                stack.pop()

            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)

            stack.append(node)
            continue

        continuation = clean_inline(line)
        if not continuation:
            continue

        if stack:
            stack[-1].continuations.append(continuation)
        else:
            roots.append(BulletNode(level=1, text=continuation))

    return roots


def split_label(text: str) -> Tuple[str, str]:
    m = LABEL_SPLIT_RE.match(text.strip())
    if not m:
        return text.strip(), ""

    label = m.group("label").strip()
    rest = m.group("rest").strip()
    lower_label = label.lower()

    # Avoid treating URLs or full prose sentences as "label: value" pairs.
    if (
        len(label) > 40
        or lower_label.endswith(("http", "https"))
        or any(token in label for token in ("[", "]", "|", "`", ">"))
    ):
        return text.strip(), ""

    return label, rest


def extract_bracket_heading(text: str) -> Tuple[Optional[str], str]:
    m = BRACKET_HEADING_RE.match(text.strip())
    if not m:
        return None, text.strip()
    return m.group("label").strip(), m.group("rest").strip()


def node_to_text(node: BulletNode) -> str:
    label, rest = split_label(node.text)
    base_name = label.strip() if rest or node.text.rstrip().endswith((":", "：")) else node.text.strip()
    desc_parts: List[str] = []

    if rest:
        desc_parts.append(f"{label}: {rest}")
    elif node.continuations:
        desc_parts.append(" ".join(node.continuations).strip())

    if node.children:
        child_text = join_child_texts(node.children)
        if child_text:
            desc_parts.append(child_text)

    if desc_parts:
        return f"{base_name}: {'; '.join(p for p in desc_parts if p).strip()}"
    return base_name


def join_child_texts(children: List[BulletNode]) -> str:
    parts: List[str] = []
    for child in children:
        parts.append(node_to_text(child))
    return "; ".join(p for p in parts if p).strip()


def looks_like_intro_container(text: str) -> bool:
    t = text.strip().rstrip("：:")
    if not text.strip().endswith((":", "：")):
        return False

    intro_markers = [
        "以下",
        "如下",
        "需開發並對接",
        "需支援以下",
        "需更新",
        "包含以下",
        "包括以下",
        "to update",
        "include the following",
        "following",
    ]
    lower = t.lower()
    return any(marker in t for marker in intro_markers) or any(marker in lower for marker in intro_markers)


def item_from_node(node: BulletNode) -> List[Dict[str, str]]:
    if node.children and looks_like_intro_container(node.text):
        items: List[Dict[str, str]] = []
        for child in node.children:
            items.extend(item_from_node(child))
        return items

    label, rest = split_label(node.text)
    has_explicit_label = bool(rest) or node.text.rstrip().endswith((":", "："))

    if has_explicit_label:
        name = label.strip()
        desc_parts: List[str] = []
        if rest:
            desc_parts.append(f"{label}: {rest}")
        if node.continuations:
            desc_parts.append(" ".join(node.continuations).strip())
        if node.children:
            child_text = join_child_texts(node.children)
            if child_text:
                desc_parts.append(child_text)

        if desc_parts:
            return [{"name": name, "description": "; ".join(p for p in desc_parts if p).strip()}]
        return [{"name": name}]

    if node.children:
        desc = join_child_texts(node.children)
        if node.continuations:
            prefix = " ".join(node.continuations).strip()
            desc = f"{prefix}; {desc}" if desc else prefix
        if desc:
            return [{"name": node.text.strip(), "description": desc}]
        return [{"name": node.text.strip()}]

    if node.continuations:
        return [{"name": node.text.strip(), "description": " ".join(node.continuations).strip()}]

    return [{"name": node.text.strip()}]


def parse_structured_section(lines: List[str], default_category: str) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    roots = parse_bullet_tree(lines)
    result: Dict[str, Dict[str, List[Dict[str, str]]]] = {}

    def ensure_category(name: str) -> Dict[str, List[Dict[str, str]]]:
        key = name.strip() or default_category
        if key not in result:
            result[key] = {"items": []}
        return result[key]

    for root in roots:
        bracket_label, bracket_rest = extract_bracket_heading(root.text)

        if bracket_label:
            cat = ensure_category(bracket_label)
            if bracket_rest:
                temp_node = BulletNode(
                    level=root.level,
                    text=bracket_rest,
                    children=root.children,
                    continuations=root.continuations,
                )
                cat["items"].extend(item_from_node(temp_node))
            else:
                for child in root.children:
                    cat["items"].extend(item_from_node(child))
                if not root.children and root.continuations:
                    cat["items"].append({"name": " ".join(root.continuations).strip()})
            continue

        if root.children and not root.text.rstrip().endswith((":", "：")):
            cat = ensure_category(root.text.strip())
            for child in root.children:
                cat["items"].extend(item_from_node(child))
            if not root.children and root.continuations:
                cat["items"].append({"name": " ".join(root.continuations).strip()})
            continue

        cat = ensure_category(default_category)
        cat["items"].extend(item_from_node(root))

    return {k: v for k, v in result.items() if v.get("items")}


def parse_menu(lines: List[str]) -> Optional[Dict[str, Any]]:
    roots = parse_bullet_tree(lines)
    path_text = ""

    if roots:
        path_text = roots[0].full_text()
    else:
        for raw in lines:
            cleaned = clean_inline(raw)
            if cleaned:
                path_text = cleaned
                break

    if not path_text:
        return None

    parts = [part.strip() for part in path_text.split(">") if part.strip()]
    if not parts:
        return None

    root: Dict[str, Any] = {"name": parts[0]}
    current = root
    for part in parts[1:]:
        child = {"name": part}
        current["children"] = [child]
        current = child

    return {"path": root}


def parse_user_story(lines: List[str]) -> Dict[str, str]:
    result = {"As a": "", "I want": "", "So that": ""}
    roots = parse_bullet_tree(lines)

    texts: List[str] = []
    for node in roots:
        texts.append(node.full_text())

    for raw in texts:
        text = clean_inline(raw)
        if not text:
            continue

        lower = text.lower()
        if lower.startswith("as a "):
            result["As a"] = text[5:].strip().rstrip(",")
        elif lower.startswith("i want to "):
            result["I want"] = text[10:].strip().rstrip(",")
        elif lower.startswith("i want "):
            result["I want"] = text[7:].strip().rstrip(",")
        elif lower.startswith("so that "):
            result["So that"] = text[8:].strip().rstrip(",")
        elif lower.startswith("so that,"):
            result["So that"] = text[8:].strip().rstrip(",")

    return result


def parse_acceptance_criteria(lines: List[str]) -> List[Dict[str, Any]]:
    scenarios: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    last_keyword: Optional[str] = None

    def start_scenario(name: str) -> Dict[str, Any]:
        scenario = {
            "Scenario": {
                "name": name.strip(),
                "Given": [],
                "When": [],
                "Then": [],
            }
        }
        scenarios.append(scenario)
        return scenario

    def add_step(keyword: str, text: str) -> None:
        nonlocal current
        if current is None:
            current = start_scenario("Unnamed Scenario")
        current["Scenario"][keyword].append(text.strip())

    for raw in lines:
        stripped = raw.strip()
        if not stripped or SEPARATOR_RE.match(stripped):
            continue

        heading = HEADING_RE.match(stripped)
        if heading:
            title = clean_inline(heading.group("title"))
            scenario_match = SCENARIO_RE.match(title)
            if scenario_match:
                current = start_scenario(title)
                last_keyword = None
            continue

        bullet = BULLET_RE.match(stripped)
        text = clean_inline(bullet.group("text")) if bullet else clean_inline(stripped)
        if not text:
            continue

        scenario_match = SCENARIO_RE.match(text)
        if scenario_match:
            current = start_scenario(text)
            last_keyword = None
            continue

        gherkin = GHERKIN_RE.match(text)
        if gherkin:
            keyword = gherkin.group(1).capitalize()
            content = gherkin.group(2).strip()

            if keyword in {"Given", "When", "Then"}:
                add_step(keyword, content)
                last_keyword = keyword
            elif keyword in {"And", "But"}:
                target = last_keyword if last_keyword in {"Given", "When", "Then"} else "Then"
                add_step(target, content)
                last_keyword = target
            continue

        if text.lower().startswith("note:") or text.startswith("NOTE:") or text.startswith("備註"):
            continue

        if current is not None:
            target = last_keyword if last_keyword in {"Given", "When", "Then"} else "Then"
            add_step(target, text)
            last_keyword = target

    return scenarios


def build_output(description: str, comments: List[str]) -> Dict[str, Any]:
    merged = remove_strikethrough(description)
    if comments:
        merged += "\n\n" + remove_strikethrough("\n\n".join(comments))

    sections = split_sections(merged)

    output: Dict[str, Any] = {}

    menu = parse_menu(sections.get("Menu", []))
    if menu:
        output["Menu"] = menu

    output["User Story Narrative"] = parse_user_story(sections.get("User Story Narrative", []))
    output["Criteria"] = parse_structured_section(sections.get("Criteria", []), default_category="需求項目")
    output["Technical Specifications"] = parse_structured_section(
        sections.get("Technical Specifications", []),
        default_category="技術規格",
    )
    output["Acceptance Criteria"] = parse_acceptance_criteria(sections.get("Acceptance Criteria", []))

    return output


def validate_output_structure(data: Dict[str, Any]) -> None:
    required = [
        "User Story Narrative",
        "Criteria",
        "Technical Specifications",
        "Acceptance Criteria",
    ]
    for key in required:
        if key not in data:
            raise RuntimeError(f"缺少必要區塊: {key}")

    if "Menu" in data and not isinstance(data["Menu"], dict):
        raise RuntimeError("Menu 必須是 object")
    if not isinstance(data["Acceptance Criteria"], list):
        raise RuntimeError("Acceptance Criteria 必須是 list")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticket-key", required=True, help="Jira ticket key，例如 TCG-123456")
    parser.add_argument("--include-comments", action="store_true", help="一併抓取 comments")
    parser.add_argument("--output", type=Path, help="輸出 yaml 路徑")
    args = parser.parse_args()

    issue = fetch_issue(args.ticket_key, args.include_comments)
    output = build_output(issue["description"], issue["comments"])
    validate_output_structure(output)

    yaml_output = yaml.safe_dump(
        output,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )

    output_dir = PROJECT_ROOT / "scripts" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output or (output_dir / f"{args.ticket_key}.yaml")
    output_path.write_text(yaml_output, encoding="utf-8")

    print(f"YAML generated -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
