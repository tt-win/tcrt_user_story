#!/usr/bin/env python3
"""用 Gemini 模型驗證 QA AI Helper 前置清洗與 matrix blueprint 概念。

流程：
1. 從 Jira 抓 ticket summary / description / comments
2. 本地 deterministic preclean：清理 JIRA markup、保留有意義段落與標題
3. 低階模型做多語去重與 canonical JSON 正規化
4. 高階模型以 AC 為單位拆出 matrix blueprint
5. 驗證輸出是否具備 lineage 與 matrix 結構
6. 將結果輸出成 JSON 供人工檢查

這支 script 只做概念驗證，不會寫入資料庫。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.services.jira_client import JiraAuthManager, JiraIssueManager

OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ALIAS = {
    "google/gemini-3-flash": "google/gemini-3-flash-preview",
    "gemini-3-flash": "google/gemini-3-flash-preview",
}

LINK_RE = re.compile(r"\[(?P<label>[^\]|]+)\|(?P<url>https?://[^\]]+)\]")
URL_RE = re.compile(r"https?://[^\s)>\"]+")
TICKET_REF_RE = re.compile(r"\b[A-Z]{2,}-\d+\b")
VERSION_TAG_RE = re.compile(
    r"(?:\(\d{4}\s*update[^)]*\)|\(\d{2}/\d{2}\s*update[^)]*\)|\[[^\]]*update[^\]]*\]|【\d{4}\s*更新[^】]*】)",
    re.IGNORECASE,
)
JIRA_COLOR_OPEN_RE = re.compile(r"\{color:[^}]+\}", re.IGNORECASE)
JIRA_HEADING_RE = re.compile(r"^\s*h(?P<level>[1-6])\.\s*(?P<title>.+?)\s*$", re.IGNORECASE)
SCENARIO_HEADING_RE = re.compile(r"^\s*scenario\s+\d+\s*[:：]?\s*(?P<title>.+?)\s*$", re.IGNORECASE)


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
        for child in value.get("content") or []:
            child_text = _coerce_jira_text(child)
            if child_text.strip():
                parts.append(child_text.strip())
        return "\n".join(parts)
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("模型回傳空內容")
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as exc:
            raise ValueError(f"模型回傳非合法 JSON: {exc}") from exc
    raise ValueError("模型回傳中找不到 JSON object")


def _normalize_model_name(value: str) -> str:
    normalized = str(value or "").strip()
    return MODEL_ALIAS.get(normalized, normalized)


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


def _replace_link(match: re.Match[str]) -> str:
    label = str(match.group("label") or "").strip()
    url = str(match.group("url") or "").strip()
    if label and url:
        return f"{label} ({url})"
    return label or url


def _strip_inline_markup(text: str) -> str:
    value = str(text or "")
    value = LINK_RE.sub(_replace_link, value)
    value = JIRA_COLOR_OPEN_RE.sub("", value)
    value = value.replace("{color}", "")
    value = value.replace("{quote}", "")
    value = value.replace("{{{", "").replace("}}}", "")
    value = value.replace("{{", "").replace("}}", "")
    value = value.replace("{*}", "")
    value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", value)
    value = re.sub(r"_(.+?)_", r"\1", value)
    value = re.sub(r"`(.+?)`", r"\1", value)
    value = value.replace("→", "->")
    value = value.replace("\u00a0", " ")
    return value


def _preclean_text(text: str) -> str:
    lines: List[str] = []
    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _strip_inline_markup(raw_line).strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if re.fullmatch(r"-{3,}", line):
            if lines and lines[-1] != "":
                lines.append("")
            continue
        heading_match = JIRA_HEADING_RE.match(line)
        if heading_match:
            level = int(heading_match.group("level"))
            title = str(heading_match.group("title") or "").strip()
            lines.append(f"H{level}: {title}")
            continue
        lines.append(re.sub(r"\s+", " ", line).strip())
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _infer_block_type(title: str, content: str, *, source_type: str) -> str:
    lowered = f"{title}\n{content}".lower()
    if source_type == "comment":
        return "comment"
    if "acceptance criteria" in lowered or "驗收標準" in lowered or SCENARIO_HEADING_RE.search(lowered):
        return "acceptance_criteria"
    if "technical specification" in lowered or "技術規格" in lowered:
        return "technical_specifications"
    if re.search(r"\bcriteria\b|標準|條件", lowered):
        return "criteria"
    if "user story" in lowered or "使用者故事" in lowered:
        return "user_story"
    if "menu" in lowered or "路徑" in lowered:
        return "menu"
    if "doc" in lowered or "translation" in lowered or "permission" in lowered:
        return "reference"
    if "update" in lowered or "更新" in lowered or "note" in lowered:
        return "update_note"
    if "http://" in lowered or "https://" in lowered:
        return "reference"
    return source_type


def _split_clean_blocks(*, description: str, comments: Sequence[str]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []

    def _append_block(title: str, content_lines: List[str], *, source_type: str) -> None:
        content = "\n".join(content_lines).strip()
        if not content:
            return
        block_title = str(title or "").strip() or content.splitlines()[0][:120]
        block_id = f"block-{len(blocks) + 1:03d}"
        blocks.append(
            {
                "block_id": block_id,
                "source_type": _infer_block_type(block_title, content, source_type=source_type),
                "language": _detect_language(content),
                "title": block_title[:120],
                "content": content,
                "metadata": {
                    "line_count": len([line for line in content.splitlines() if line.strip()]),
                },
            }
        )

    def _consume_text(raw_text: str, *, source_type: str) -> None:
        title = ""
        chunk: List[str] = []
        for line in str(raw_text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            heading_match = re.match(r"^H(?P<level>[1-6]):\s*(?P<title>.+?)\s*$", stripped)
            scenario_match = SCENARIO_HEADING_RE.match(stripped.lower())
            if heading_match or scenario_match:
                if chunk:
                    _append_block(title, chunk, source_type=source_type)
                    chunk = []
                if heading_match:
                    title = str(heading_match.group("title") or "").strip()
                    chunk.append(stripped)
                else:
                    title = stripped
                    chunk.append(stripped)
                continue
            chunk.append(stripped)
        if chunk:
            _append_block(title, chunk, source_type=source_type)

    _consume_text(description, source_type="description")
    for comment in comments:
        _consume_text(comment, source_type="comment")
    return blocks


def _build_preclean_payload(*, summary: str, description: str, comments: Sequence[str]) -> Dict[str, Any]:
    cleaned_summary = _preclean_text(summary)
    cleaned_description = _preclean_text(description)
    cleaned_comments = [_preclean_text(comment) for comment in comments if _preclean_text(comment).strip()]
    merged = "\n".join([cleaned_summary, cleaned_description, *cleaned_comments])
    blocks = _split_clean_blocks(description=cleaned_description, comments=cleaned_comments)
    language_variants: Dict[str, List[str]] = {}
    for block in blocks:
        language_variants.setdefault(block["language"], []).append(block["block_id"])
    return {
        "summary": cleaned_summary,
        "description": cleaned_description,
        "comments": cleaned_comments,
        "source_blocks": blocks,
        "language_variants": language_variants,
        "version_tags": sorted(set(match.group(0).strip() for match in VERSION_TAG_RE.finditer(merged))),
        "references": sorted(set(match.group(0).strip() for match in URL_RE.finditer(merged))),
        "ticket_refs": sorted(set(match.group(0).strip() for match in TICKET_REF_RE.finditer(merged))),
    }


def _suggest_canonical_language(preclean_payload: Dict[str, Any]) -> str:
    languages = list((preclean_payload.get("language_variants") or {}).keys())
    if "zh" in languages:
        return "zh-TW"
    return "en"


def _build_normalizer_prompt(
    *,
    ticket_key: str,
    preclean_payload: Dict[str, Any],
    canonical_language: str,
) -> str:
    compact_blocks = [
        {
            "block_id": block.get("block_id"),
            "source_type": block.get("source_type"),
            "language": block.get("language"),
            "title": block.get("title"),
            "content": block.get("content"),
        }
        for block in (preclean_payload.get("source_blocks") or [])
    ]
    schema = {
        "canonical_language": canonical_language,
        "canonical_sections": {
            "user_story_narrative": {
                "text": "",
                "source_block_ids": ["block-001"],
            },
            "criteria": [
                {
                    "item_key": "crt-001",
                    "text": "",
                    "source_block_ids": ["block-001"],
                }
            ],
            "technical_specifications": [
                {
                    "item_key": "tps-001",
                    "text": "",
                    "source_block_ids": ["block-001"],
                }
            ],
            "acceptance_criteria": [
                {
                    "scenario_key": "ac.scenario_001",
                    "title": "",
                    "given": [],
                    "when": [],
                    "then": [],
                    "and": [],
                    "raw_text": "",
                    "source_block_ids": ["block-001"],
                }
            ],
        },
        "duplicate_groups": [
            {
                "canonical_block_id": "block-001",
                "duplicate_block_ids": ["block-002"],
                "reason": "same requirement in another language",
            }
        ],
        "excluded_blocks": [
            {
                "block_id": "block-009",
                "reason": "reference-only block",
            }
        ],
        "unresolved_questions": [],
    }
    return (
        "你是 QA AI Helper 的低階 requirement normalizer。\n"
        "你的工作是：在不改變原意的前提下，對已預清洗的 ticket blocks 做多語去重、重複需求合併、並重排成後續可供程式與高階模型處理的 JSON。\n"
        "嚴格遵守以下規則：\n"
        "1. 不可發明需求，不可補齊 ticket 未明示的規則。\n"
        "2. 不可使用 Markdown；只輸出 JSON object。\n"
        "3. 每個 retained item 都必須帶 source_block_ids。\n"
        "4. 每個 source block 必須被保留、判定為 duplicate，或判定為 excluded；禁止 silent drop。\n"
        "5. 若為雙語鏡像或重複需求，只保留一份 canonical 意義，但 duplicate block 仍要留 lineage。\n"
        "6. user_story_narrative / criteria / technical_specifications / acceptance_criteria 必須是後續 planner 可直接使用的 canonical JSON，不要保留 doc links、translation sheet、示意例子等雜訊。\n"
        "7. 若你無法確定是否為 duplicate 或是否應保留，放進 unresolved_questions，不要自行腦補。\n"
        "8. acceptance_criteria 必須盡量完整保留顯式 Scenario 結構；不要只挑幾個重點 scenario。\n\n"
        f"TICKET_KEY={ticket_key}\n"
        f"CANONICAL_LANGUAGE={canonical_language}\n"
        f"PRECLEAN_PAYLOAD={_json_dumps({'summary': preclean_payload.get('summary'), 'references': preclean_payload.get('references'), 'ticket_refs': preclean_payload.get('ticket_refs'), 'version_tags': preclean_payload.get('version_tags'), 'source_blocks': compact_blocks})}\n"
        f"OUTPUT_SCHEMA={_json_dumps(schema)}\n"
    )


def _build_matrix_prompt(
    *,
    ticket_key: str,
    canonical_language: str,
    normalized: Dict[str, Any],
) -> str:
    schema = {
        "scenarios": [
            {
                "scenario_key": "ac.scenario_001",
                "title": "",
                "source_refs": ["ac.scenario_001"],
                "assertions": [
                    {
                        "assertion_key": "as-001",
                        "text": "",
                        "source_refs": ["ac.scenario_001", "crt-001"],
                    }
                ],
                "dimensions": [
                    {
                        "dimension_key": "entry_source",
                        "label": "",
                        "selection_mode": "single_select",
                        "options": [
                            {
                                "option_key": "audience_list",
                                "text": "",
                                "source_refs": ["ac.scenario_001"],
                            }
                        ],
                    }
                ],
                "constraints": [
                    {
                        "constraint_type": "mutex_dimension",
                        "dimension_key": "entry_source",
                        "reason": "same axis options are mutually exclusive",
                        "source_refs": ["ac.scenario_001"],
                    }
                ],
                "forbidden_combinations": [
                    {
                        "all": [
                            {"dimension_key": "creation_type", "option_key": "import_based"},
                            {"dimension_key": "field", "option_key": "calculation_time_zone"},
                        ],
                        "reason": "",
                        "source_refs": ["crt-001"],
                    }
                ],
                "applicability_rules": [
                    {
                        "target_dimension_key": "field",
                        "target_option_key": "calculation_time_zone",
                        "applicable_if_all": [
                            {"dimension_key": "creation_type", "option_key": "rule_based"},
                            {"dimension_key": "calculation_mode", "option_key": "automatic"},
                        ],
                        "reason": "",
                        "source_refs": ["crt-001"],
                    }
                ],
                "unresolved_constraints": [],
            }
        ]
    }
    canonical_sections = normalized.get("canonical_sections") or {}
    return (
        "你是 QA AI Helper 的高階 AC matrix planner。\n"
        "你的工作是：根據已正規化的 canonical JSON，以 Acceptance Criteria 為單位拆出 matrix blueprint，供本地程式後續產生 plan。\n"
        "嚴格遵守以下規則：\n"
        "1. 一次只處理已存在的 AC scenario，不可新增 scenario。\n"
        "2. 你的輸出是 matrix blueprint，不是 testcase，也不是最終 plan。\n"
        "3. 只拆出該 AC 真正要驗證的 assertions、dimensions、options、constraints。\n"
        "4. 只有在可證明可同時成立時，才保留可做 cross-product 的 dimensions；明顯互斥或不確定者，請用 constraints / unresolved_constraints 表達，不要自行硬乘。\n"
        "5. 每個 assertion / dimension / option / constraint 都必須帶 source_refs，且 source_refs 只能引用 canonical item keys 或 scenario keys。\n"
        "6. 若 AC 內存在 filter、option、狀態或入口等明示組合維度，請拆出 dimension；若只是補充說明、例子或背景，不要誤當 dimension。\n"
        "7. 只輸出 JSON object，禁止 Markdown、說明文字或 code fence。\n\n"
        f"TICKET_KEY={ticket_key}\n"
        f"CANONICAL_LANGUAGE={canonical_language}\n"
        f"NORMALIZED_CANONICAL_JSON={_json_dumps(canonical_sections)}\n"
        f"OUTPUT_SCHEMA={_json_dumps(schema)}\n"
    )


def _base_headers() -> Dict[str, str]:
    settings = get_settings()
    api_key = (settings.openrouter.api_key or "").strip()
    if not api_key:
        raise RuntimeError("OpenRouter API key 未設定，無法執行 Gemini smoke test")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    base_url = settings.app.get_base_url() if settings.app else ""
    if base_url:
        headers["HTTP-Referer"] = base_url
        headers["X-Title"] = "TCRT QA AI Helper Normalization Smoke"
    return headers


def _call_openrouter(*, model: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        OPENROUTER_CHAT_COMPLETIONS_URL,
        headers=_base_headers(),
        json=payload,
        timeout=180,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenRouter 呼叫失敗: HTTP {response.status_code} {response.text}")
    return response.json()


@dataclass
class ValidationSummary:
    ok: bool
    errors: List[str]
    warnings: List[str]


def _validate_normalization_result(
    *,
    preclean_payload: Dict[str, Any],
    normalized: Dict[str, Any],
) -> ValidationSummary:
    errors: List[str] = []
    warnings: List[str] = []
    source_blocks = preclean_payload.get("source_blocks") or []
    source_block_ids = {str(block.get("block_id") or "").strip() for block in source_blocks}

    canonical_sections = normalized.get("canonical_sections")
    if not isinstance(canonical_sections, dict):
        errors.append("canonical_sections 必須是 object")
        return ValidationSummary(ok=False, errors=errors, warnings=warnings)

    retained_block_ids: Set[str] = set()

    def _validate_source_block_ids(path: str, refs: Any) -> None:
        if not isinstance(refs, list) or not refs:
            errors.append(f"{path}.source_block_ids 必須是非空陣列")
            return
        for ref in refs:
            block_id = str(ref or "").strip()
            if block_id not in source_block_ids:
                errors.append(f"{path}.source_block_ids 包含未知 block_id: {ref}")
                continue
            retained_block_ids.add(block_id)

    user_story = canonical_sections.get("user_story_narrative")
    if not isinstance(user_story, dict):
        errors.append("canonical_sections.user_story_narrative 必須是 object")
    else:
        if not isinstance(user_story.get("text"), str):
            errors.append("canonical_sections.user_story_narrative.text 必須是字串")
        _validate_source_block_ids("canonical_sections.user_story_narrative", user_story.get("source_block_ids"))

    criteria_items = canonical_sections.get("criteria")
    if not isinstance(criteria_items, list):
        errors.append("canonical_sections.criteria 必須是陣列")
    else:
        for index, item in enumerate(criteria_items):
            if not isinstance(item, dict):
                errors.append(f"canonical_sections.criteria[{index}] 必須是 object")
                continue
            if not str(item.get("item_key") or "").strip():
                errors.append(f"canonical_sections.criteria[{index}].item_key 不可為空")
            if not isinstance(item.get("text"), str):
                errors.append(f"canonical_sections.criteria[{index}].text 必須是字串")
            _validate_source_block_ids(f"canonical_sections.criteria[{index}]", item.get("source_block_ids"))

    technical_items = canonical_sections.get("technical_specifications")
    if not isinstance(technical_items, list):
        errors.append("canonical_sections.technical_specifications 必須是陣列")
    else:
        for index, item in enumerate(technical_items):
            if not isinstance(item, dict):
                errors.append(f"canonical_sections.technical_specifications[{index}] 必須是 object")
                continue
            if not str(item.get("item_key") or "").strip():
                errors.append(f"canonical_sections.technical_specifications[{index}].item_key 不可為空")
            if not isinstance(item.get("text"), str):
                errors.append(f"canonical_sections.technical_specifications[{index}].text 必須是字串")
            _validate_source_block_ids(f"canonical_sections.technical_specifications[{index}]", item.get("source_block_ids"))

    acceptance = canonical_sections.get("acceptance_criteria")
    if not isinstance(acceptance, list) or not acceptance:
        errors.append("canonical_sections.acceptance_criteria 必須是非空陣列")
    else:
        for index, scenario in enumerate(acceptance):
            if not isinstance(scenario, dict):
                errors.append(f"canonical_sections.acceptance_criteria[{index}] 必須是 object")
                continue
            if not str(scenario.get("scenario_key") or "").strip():
                errors.append(f"canonical_sections.acceptance_criteria[{index}].scenario_key 不可為空")
            if not str(scenario.get("title") or "").strip():
                errors.append(f"canonical_sections.acceptance_criteria[{index}].title 不可為空")
            for clause_key in ("given", "when", "then", "and"):
                clause_value = scenario.get(clause_key)
                if not isinstance(clause_value, list):
                    errors.append(f"canonical_sections.acceptance_criteria[{index}].{clause_key} 必須是陣列")
            _validate_source_block_ids(f"canonical_sections.acceptance_criteria[{index}]", scenario.get("source_block_ids"))

    duplicate_groups = normalized.get("duplicate_groups") or []
    duplicate_block_ids: Set[str] = set()
    if not isinstance(duplicate_groups, list):
        errors.append("duplicate_groups 必須是陣列")
    else:
        for index, group in enumerate(duplicate_groups):
            if not isinstance(group, dict):
                errors.append(f"duplicate_groups[{index}] 必須是 object")
                continue
            canonical_block_id = str(group.get("canonical_block_id") or "").strip()
            if canonical_block_id not in source_block_ids:
                errors.append(f"duplicate_groups[{index}].canonical_block_id 未知: {canonical_block_id}")
            duplicate_ids = group.get("duplicate_block_ids")
            if not isinstance(duplicate_ids, list) or not duplicate_ids:
                errors.append(f"duplicate_groups[{index}].duplicate_block_ids 必須是非空陣列")
                continue
            for block_id in duplicate_ids:
                normalized_id = str(block_id or "").strip()
                if normalized_id not in source_block_ids:
                    errors.append(f"duplicate_groups[{index}] 包含未知 block_id: {normalized_id}")
                    continue
                duplicate_block_ids.add(normalized_id)

    excluded_blocks = normalized.get("excluded_blocks") or []
    excluded_block_ids: Set[str] = set()
    if not isinstance(excluded_blocks, list):
        errors.append("excluded_blocks 必須是陣列")
    else:
        for index, item in enumerate(excluded_blocks):
            if not isinstance(item, dict):
                errors.append(f"excluded_blocks[{index}] 必須是 object")
                continue
            block_id = str(item.get("block_id") or "").strip()
            if block_id not in source_block_ids:
                errors.append(f"excluded_blocks[{index}] 包含未知 block_id: {block_id}")
                continue
            excluded_block_ids.add(block_id)
            if not str(item.get("reason") or "").strip():
                errors.append(f"excluded_blocks[{index}].reason 不可為空")

    covered_block_ids = retained_block_ids | duplicate_block_ids | excluded_block_ids
    missing_block_ids = sorted(source_block_ids - covered_block_ids)
    if missing_block_ids:
        errors.append(f"以下 source blocks 未被 canonical/duplicate/excluded 覆蓋: {', '.join(missing_block_ids)}")

    if not normalized.get("unresolved_questions"):
        warnings.append("unresolved_questions 為空；若 ticket 很大，需人工確認是否真的沒有未決資訊")

    return ValidationSummary(ok=not errors, errors=errors, warnings=warnings)


def _collect_valid_canonical_refs(normalized: Dict[str, Any]) -> Set[str]:
    canonical_sections = normalized.get("canonical_sections") or {}
    refs: Set[str] = set()
    for item in canonical_sections.get("criteria") or []:
        item_key = str((item or {}).get("item_key") or "").strip()
        if item_key:
            refs.add(item_key)
    for item in canonical_sections.get("technical_specifications") or []:
        item_key = str((item or {}).get("item_key") or "").strip()
        if item_key:
            refs.add(item_key)
    for item in canonical_sections.get("acceptance_criteria") or []:
        scenario_key = str((item or {}).get("scenario_key") or "").strip()
        if scenario_key:
            refs.add(scenario_key)
    return refs


def _validate_matrix_blueprint(
    *,
    normalized: Dict[str, Any],
    matrix_blueprint: Dict[str, Any],
) -> ValidationSummary:
    errors: List[str] = []
    warnings: List[str] = []
    valid_refs = _collect_valid_canonical_refs(normalized)
    known_scenarios = {
        str((item or {}).get("scenario_key") or "").strip()
        for item in ((normalized.get("canonical_sections") or {}).get("acceptance_criteria") or [])
        if str((item or {}).get("scenario_key") or "").strip()
    }

    def _validate_source_refs(path: str, refs: Any) -> None:
        if not isinstance(refs, list) or not refs:
            errors.append(f"{path}.source_refs 必須是非空陣列")
            return
        for ref in refs:
            normalized_ref = str(ref or "").strip()
            if normalized_ref not in valid_refs:
                errors.append(f"{path}.source_refs 包含未知 canonical ref: {normalized_ref}")

    scenarios = matrix_blueprint.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("matrix_blueprint.scenarios 必須是非空陣列")
        return ValidationSummary(ok=False, errors=errors, warnings=warnings)

    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            errors.append(f"matrix_blueprint.scenarios[{index}] 必須是 object")
            continue
        scenario_key = str(scenario.get("scenario_key") or "").strip()
        if scenario_key not in known_scenarios:
            errors.append(f"matrix_blueprint.scenarios[{index}].scenario_key 未知: {scenario_key}")
        if not str(scenario.get("title") or "").strip():
            errors.append(f"matrix_blueprint.scenarios[{index}].title 不可為空")
        _validate_source_refs(f"matrix_blueprint.scenarios[{index}]", scenario.get("source_refs"))

        assertions = scenario.get("assertions")
        if not isinstance(assertions, list) or not assertions:
            errors.append(f"matrix_blueprint.scenarios[{index}].assertions 必須是非空陣列")
        else:
            for assert_index, assertion in enumerate(assertions):
                if not isinstance(assertion, dict):
                    errors.append(f"matrix_blueprint.scenarios[{index}].assertions[{assert_index}] 必須是 object")
                    continue
                if not str(assertion.get("assertion_key") or "").strip():
                    errors.append(f"matrix_blueprint.scenarios[{index}].assertions[{assert_index}].assertion_key 不可為空")
                if not str(assertion.get("text") or "").strip():
                    errors.append(f"matrix_blueprint.scenarios[{index}].assertions[{assert_index}].text 不可為空")
                _validate_source_refs(
                    f"matrix_blueprint.scenarios[{index}].assertions[{assert_index}]",
                    assertion.get("source_refs"),
                )

        dimensions = scenario.get("dimensions")
        if not isinstance(dimensions, list):
            errors.append(f"matrix_blueprint.scenarios[{index}].dimensions 必須是陣列")
        else:
            for dim_index, dimension in enumerate(dimensions):
                if not isinstance(dimension, dict):
                    errors.append(f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}] 必須是 object")
                    continue
                if not str(dimension.get("dimension_key") or "").strip():
                    errors.append(f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].dimension_key 不可為空")
                options = dimension.get("options")
                if not isinstance(options, list) or not options:
                    errors.append(f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].options 必須是非空陣列")
                    continue
                for option_index, option in enumerate(options):
                    if not isinstance(option, dict):
                        errors.append(f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].options[{option_index}] 必須是 object")
                        continue
                    if not str(option.get("option_key") or "").strip():
                        errors.append(
                            f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].options[{option_index}].option_key 不可為空"
                        )
                    _validate_source_refs(
                        f"matrix_blueprint.scenarios[{index}].dimensions[{dim_index}].options[{option_index}]",
                        option.get("source_refs"),
                    )

        for field_name in ("constraints", "forbidden_combinations", "applicability_rules", "unresolved_constraints"):
            value = scenario.get(field_name)
            if not isinstance(value, list):
                errors.append(f"matrix_blueprint.scenarios[{index}].{field_name} 必須是陣列")

    return ValidationSummary(ok=not errors, errors=errors, warnings=warnings)


def _fetch_issue(*, ticket_key: str, include_comments: bool) -> Dict[str, Any]:
    issue_manager = JiraIssueManager(JiraAuthManager())
    fields = ["summary", "description", "comment"]
    issue = issue_manager.get_issue(ticket_key, fields=fields)
    if not issue:
        raise RuntimeError(f"找不到 Jira ticket: {ticket_key}")
    raw_fields = issue.get("fields") or {}
    comments: List[str] = []
    if include_comments:
        for item in (raw_fields.get("comment") or {}).get("comments", []):
            body = _coerce_jira_text(item.get("body"))
            if body.strip():
                comments.append(body.strip())
    return {
        "summary": _coerce_jira_text(raw_fields.get("summary")).strip(),
        "description": _coerce_jira_text(raw_fields.get("description")).strip(),
        "comments": comments,
    }


def _build_report(
    *,
    ticket_key: str,
    normalizer_model: str,
    matrix_model: str,
    include_comments: bool,
    preclean_payload: Dict[str, Any],
    normalization_response: Dict[str, Any],
    normalization_result: Dict[str, Any],
    normalization_validation: ValidationSummary,
    matrix_response: Dict[str, Any],
    matrix_blueprint: Dict[str, Any],
    matrix_validation: ValidationSummary,
) -> Dict[str, Any]:
    normalization_usage = normalization_response.get("usage") or {}
    matrix_usage = matrix_response.get("usage") or {}
    canonical_sections = normalization_result.get("canonical_sections") or {}
    matrix_scenarios = matrix_blueprint.get("scenarios") or []
    return {
        "ticket_key": ticket_key,
        "models": {
            "normalizer": normalizer_model,
            "matrix": matrix_model,
        },
        "include_comments": include_comments,
        "summary": {
            "preclean_block_count": len(preclean_payload.get("source_blocks") or []),
            "reference_count": len(preclean_payload.get("references") or []),
            "ticket_ref_count": len(preclean_payload.get("ticket_refs") or []),
            "normalized_criteria_count": len(canonical_sections.get("criteria") or []),
            "normalized_technical_count": len(canonical_sections.get("technical_specifications") or []),
            "normalized_ac_count": len(canonical_sections.get("acceptance_criteria") or []),
            "duplicate_group_count": len(normalization_result.get("duplicate_groups") or []),
            "excluded_block_count": len(normalization_result.get("excluded_blocks") or []),
            "matrix_scenario_count": len(matrix_scenarios),
            "matrix_dimension_count": sum(len((item or {}).get("dimensions") or []) for item in matrix_scenarios),
            "matrix_assertion_count": sum(len((item or {}).get("assertions") or []) for item in matrix_scenarios),
            "matrix_unresolved_constraint_count": sum(
                len((item or {}).get("unresolved_constraints") or []) for item in matrix_scenarios
            ),
        },
        "usage": {
            "normalizer": {
                "prompt_tokens": int(
                    normalization_usage.get("prompt_tokens") or normalization_usage.get("promptTokens") or 0
                ),
                "completion_tokens": int(
                    normalization_usage.get("completion_tokens") or normalization_usage.get("completionTokens") or 0
                ),
                "total_tokens": int(
                    normalization_usage.get("total_tokens") or normalization_usage.get("totalTokens") or 0
                ),
            },
            "matrix": {
                "prompt_tokens": int(matrix_usage.get("prompt_tokens") or matrix_usage.get("promptTokens") or 0),
                "completion_tokens": int(
                    matrix_usage.get("completion_tokens") or matrix_usage.get("completionTokens") or 0
                ),
                "total_tokens": int(matrix_usage.get("total_tokens") or matrix_usage.get("totalTokens") or 0),
            },
        },
        "validation": {
            "normalization": {
                "ok": normalization_validation.ok,
                "errors": normalization_validation.errors,
                "warnings": normalization_validation.warnings,
            },
            "matrix": {
                "ok": matrix_validation.ok,
                "errors": matrix_validation.errors,
                "warnings": matrix_validation.warnings,
            },
            "overall_ok": normalization_validation.ok and matrix_validation.ok,
        },
        "preclean": preclean_payload,
        "normalization": normalization_result,
        "matrix_blueprint": matrix_blueprint,
        "raw_model_content": {
            "normalizer": str((((normalization_response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip(),
            "matrix": str((((matrix_response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip(),
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QA AI Helper normalization + matrix blueprint smoke test")
    parser.add_argument("--ticket-key", required=True, help="Jira ticket key，例如 TCG-125547")
    parser.add_argument("--include-comments", action="store_true", help="一併抓取 Jira comments")
    parser.add_argument(
        "--model",
        default="google/gemini-3-flash-preview",
        help="低階 normalizer 使用的 OpenRouter model id，預設 google/gemini-3-flash-preview",
    )
    parser.add_argument(
        "--matrix-model",
        default="google/gemini-3.1-pro-preview",
        help="高階 matrix planner 使用的 OpenRouter model id，預設 google/gemini-3.1-pro-preview",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8000,
        help="低階 normalizer max_tokens，預設 8000",
    )
    parser.add_argument(
        "--matrix-max-tokens",
        type=int,
        default=10000,
        help="高階 matrix planner max_tokens，預設 10000",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="輸出 JSON 檔路徑；未指定則輸出到 scripts/output/qa_ai_helper_normalization_<ticket>.json",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    normalizer_model = _normalize_model_name(args.model)
    matrix_model = _normalize_model_name(args.matrix_model or args.model)

    issue_payload = _fetch_issue(ticket_key=args.ticket_key, include_comments=bool(args.include_comments))
    preclean_payload = _build_preclean_payload(
        summary=issue_payload["summary"],
        description=issue_payload["description"],
        comments=issue_payload["comments"],
    )
    canonical_language = _suggest_canonical_language(preclean_payload)

    normalization_prompt = _build_normalizer_prompt(
        ticket_key=args.ticket_key,
        preclean_payload=preclean_payload,
        canonical_language=canonical_language,
    )
    normalization_response = _call_openrouter(
        model=normalizer_model,
        prompt=normalization_prompt,
        max_tokens=int(args.max_tokens),
    )
    normalization_content = str((((normalization_response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
    normalization_result = _extract_json_object(normalization_content)
    normalization_validation = _validate_normalization_result(
        preclean_payload=preclean_payload,
        normalized=normalization_result,
    )

    matrix_prompt = _build_matrix_prompt(
        ticket_key=args.ticket_key,
        canonical_language=str(normalization_result.get("canonical_language") or canonical_language),
        normalized=normalization_result,
    )
    matrix_response = _call_openrouter(
        model=matrix_model,
        prompt=matrix_prompt,
        max_tokens=int(args.matrix_max_tokens),
    )
    matrix_content = str((((matrix_response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
    matrix_blueprint = _extract_json_object(matrix_content)
    matrix_validation = _validate_matrix_blueprint(
        normalized=normalization_result,
        matrix_blueprint=matrix_blueprint,
    )

    report = _build_report(
        ticket_key=args.ticket_key,
        normalizer_model=normalizer_model,
        matrix_model=matrix_model,
        include_comments=bool(args.include_comments),
        preclean_payload=preclean_payload,
        normalization_response=normalization_response,
        normalization_result=normalization_result,
        normalization_validation=normalization_validation,
        matrix_response=matrix_response,
        matrix_blueprint=matrix_blueprint,
        matrix_validation=matrix_validation,
    )

    output_path = args.output or (
        PROJECT_ROOT / "scripts" / "output" / f"qa_ai_helper_normalization_{args.ticket_key.lower()}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"ticket_key={args.ticket_key}")
    print(f"normalizer_model={normalizer_model}")
    print(f"matrix_model={matrix_model}")
    print(f"output={output_path}")
    print(f"preclean_blocks={report['summary']['preclean_block_count']}")
    print(f"normalized_ac={report['summary']['normalized_ac_count']}")
    print(f"matrix_scenarios={report['summary']['matrix_scenario_count']}")
    print(f"matrix_dimensions={report['summary']['matrix_dimension_count']}")
    print(f"normalization_ok={normalization_validation.ok}")
    print(f"matrix_ok={matrix_validation.ok}")
    if normalization_validation.errors:
        print("normalization_errors=" + "; ".join(normalization_validation.errors))
    if normalization_validation.warnings:
        print("normalization_warnings=" + "; ".join(normalization_validation.warnings))
    if matrix_validation.errors:
        print("matrix_errors=" + "; ".join(matrix_validation.errors))
    if matrix_validation.warnings:
        print("matrix_warnings=" + "; ".join(matrix_validation.warnings))
    return 0 if (normalization_validation.ok and matrix_validation.ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
