#!/usr/bin/env python3
"""QA AI Helper Step 2: AI normalization (低階模型).

讀取 Step 1 (preclean) 的 JSON 輸出，呼叫低階模型做多語去重與 canonical JSON
正規化，驗證輸出結構，輸出 JSON 供 Step 3 (matrix) 使用。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests

from app.config import get_settings

OPENROUTER_CHAT_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_ALIAS = {
    "google/gemini-3-flash": "google/gemini-3-flash-preview",
    "gemini-3-flash": "google/gemini-3-flash-preview",
}

SCENARIO_HEADING_RE = re.compile(r"^\s*scenario\s+\d+\s*[:：]?\s*(?P<title>.+?)\s*$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# OpenRouter API
# ---------------------------------------------------------------------------


def _base_headers() -> Dict[str, str]:
    settings = get_settings()
    api_key = (settings.openrouter.api_key or "").strip()
    if not api_key:
        raise RuntimeError("OpenRouter API key 未設定")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    base_url = settings.app.get_base_url() if settings.app else ""
    if base_url:
        headers["HTTP-Referer"] = base_url
        headers["X-Title"] = "TCRT QA AI Helper Normalize"
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


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _build_normalizer_prompt(
    *,
    ticket_key: str,
    preclean_payload: Dict[str, Any],
    canonical_language: str,
) -> str:
    # Build compact block list including sub_blocks for the model to reference
    compact_blocks = []
    for block in (preclean_payload.get("source_blocks") or []):
        entry: Dict[str, Any] = {
            "block_id": block.get("block_id"),
            "section_type": block.get("section_type"),
            "language": block.get("language"),
            "title": block.get("title"),
        }
        sub_blocks = block.get("sub_blocks") or []
        if sub_blocks:
            entry["sub_blocks"] = [
                {
                    "sub_block_id": sub.get("sub_block_id"),
                    "title": sub.get("title"),
                    "content": sub.get("content"),
                    "language": sub.get("language"),
                    **({"given": sub["given"], "when": sub["when"], "then": sub["then"], "and": sub["and"]}
                       if "given" in sub else {}),
                }
                for sub in sub_blocks
            ]
        else:
            entry["content"] = block.get("content")
        compact_blocks.append(entry)

    # source_block_ids should reference sub_block_ids for sections with sub_blocks,
    # or block_id for sections without (e.g. user_story_narrative, comments)
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
                    "source_block_ids": ["block-002-01"],
                }
            ],
            "technical_specifications": [
                {
                    "item_key": "tps-001",
                    "text": "",
                    "source_block_ids": ["block-003-01"],
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
                    "source_block_ids": ["block-004-01"],
                }
            ],
        },
        "duplicate_groups": [
            {
                "canonical_block_id": "block-002-01",
                "duplicate_block_ids": ["block-002-02"],
                "reason": "same requirement in another language",
            }
        ],
        "excluded_blocks": [
            {
                "block_id": "block-005",
                "reason": "comment with no new requirement",
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
        "4. source_block_ids 優先引用 sub_block_id（如 block-002-01）；"
        "若該 block 無 sub_blocks，才引用頂層 block_id。\n"
        "5. 每個 leaf ID（有 sub_blocks 的區塊以 sub_block_id 為準，無 sub_blocks 以 block_id 為準）"
        "必須被保留、判定為 duplicate，或判定為 excluded；禁止 silent drop。\n"
        "6. 若為雙語鏡像或重複需求，只保留一份 canonical 意義，但 duplicate block 仍要留 lineage。\n"
        "7. user_story_narrative / criteria / technical_specifications / acceptance_criteria 必須是後續 planner 可直接使用的 canonical JSON，不要保留 doc links、translation sheet、示意例子等雜訊。\n"
        "8. 若你無法確定是否為 duplicate 或是否應保留，放進 unresolved_questions，不要自行腦補。\n"
        "9. acceptance_criteria 必須盡量完整保留顯式 Scenario 結構；不要只挑幾個重點 scenario。\n\n"
        f"TICKET_KEY={ticket_key}\n"
        f"CANONICAL_LANGUAGE={canonical_language}\n"
        f"PRECLEAN_PAYLOAD={_json_dumps({'summary': preclean_payload.get('summary'), 'references': preclean_payload.get('references'), 'ticket_refs': preclean_payload.get('ticket_refs'), 'version_tags': preclean_payload.get('version_tags'), 'source_blocks': compact_blocks})}\n"
        f"OUTPUT_SCHEMA={_json_dumps(schema)}\n"
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class ValidationSummary:
    ok: bool
    errors: List[str]
    warnings: List[str]


def _collect_all_valid_ids(preclean_payload: Dict[str, Any]) -> Set[str]:
    """All referenceable IDs: both block_id and sub_block_id."""
    valid: Set[str] = set()
    for block in (preclean_payload.get("source_blocks") or []):
        bid = str(block.get("block_id") or "").strip()
        if bid:
            valid.add(bid)
        for sub in (block.get("sub_blocks") or []):
            sid = str(sub.get("sub_block_id") or "").strip()
            if sid:
                valid.add(sid)
    return valid


def _collect_leaf_ids(preclean_payload: Dict[str, Any]) -> Set[str]:
    """IDs that must be covered: sub_block_ids for sections with sub_blocks, block_id otherwise."""
    leaf: Set[str] = set()
    for block in (preclean_payload.get("source_blocks") or []):
        sub_blocks = block.get("sub_blocks") or []
        if sub_blocks:
            for sub in sub_blocks:
                sid = str(sub.get("sub_block_id") or "").strip()
                if sid:
                    leaf.add(sid)
        else:
            bid = str(block.get("block_id") or "").strip()
            if bid:
                leaf.add(bid)
    return leaf


def _validate_normalization_result(
    *,
    preclean_payload: Dict[str, Any],
    normalized: Dict[str, Any],
) -> ValidationSummary:
    errors: List[str] = []
    warnings: List[str] = []
    all_valid_ids = _collect_all_valid_ids(preclean_payload)
    leaf_ids = _collect_leaf_ids(preclean_payload)

    canonical_sections = normalized.get("canonical_sections")
    if not isinstance(canonical_sections, dict):
        errors.append("canonical_sections 必須是 object")
        return ValidationSummary(ok=False, errors=errors, warnings=warnings)

    retained_leaf_ids: Set[str] = set()

    def _validate_source_block_ids(path: str, refs: Any) -> None:
        if not isinstance(refs, list) or not refs:
            errors.append(f"{path}.source_block_ids 必須是非空陣列")
            return
        for ref in refs:
            block_id = str(ref or "").strip()
            if block_id not in all_valid_ids:
                errors.append(f"{path}.source_block_ids 包含未知 id: {ref}")
                continue
            if block_id in leaf_ids:
                retained_leaf_ids.add(block_id)

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
    duplicate_leaf_ids: Set[str] = set()
    if not isinstance(duplicate_groups, list):
        errors.append("duplicate_groups 必須是陣列")
    else:
        for index, group in enumerate(duplicate_groups):
            if not isinstance(group, dict):
                errors.append(f"duplicate_groups[{index}] 必須是 object")
                continue
            canonical_block_id = str(group.get("canonical_block_id") or "").strip()
            if canonical_block_id not in all_valid_ids:
                errors.append(f"duplicate_groups[{index}].canonical_block_id 未知: {canonical_block_id}")
            duplicate_ids = group.get("duplicate_block_ids")
            if not isinstance(duplicate_ids, list) or not duplicate_ids:
                errors.append(f"duplicate_groups[{index}].duplicate_block_ids 必須是非空陣列")
                continue
            for block_id in duplicate_ids:
                normalized_id = str(block_id or "").strip()
                if normalized_id not in all_valid_ids:
                    errors.append(f"duplicate_groups[{index}] 包含未知 id: {normalized_id}")
                    continue
                if normalized_id in leaf_ids:
                    duplicate_leaf_ids.add(normalized_id)

    excluded_blocks = normalized.get("excluded_blocks") or []
    excluded_leaf_ids: Set[str] = set()
    if not isinstance(excluded_blocks, list):
        errors.append("excluded_blocks 必須是陣列")
    else:
        for index, item in enumerate(excluded_blocks):
            if not isinstance(item, dict):
                errors.append(f"excluded_blocks[{index}] 必須是 object")
                continue
            block_id = str(item.get("block_id") or "").strip()
            if block_id not in all_valid_ids:
                errors.append(f"excluded_blocks[{index}] 包含未知 id: {block_id}")
                continue
            if block_id in leaf_ids:
                excluded_leaf_ids.add(block_id)
            if not str(item.get("reason") or "").strip():
                errors.append(f"excluded_blocks[{index}].reason 不可為空")

    covered_leaf_ids = retained_leaf_ids | duplicate_leaf_ids | excluded_leaf_ids
    missing_block_ids = sorted(leaf_ids - covered_leaf_ids)
    if missing_block_ids:
        errors.append(f"以下 source blocks 未被 canonical/duplicate/excluded 覆蓋: {', '.join(missing_block_ids)}")

    if not normalized.get("unresolved_questions"):
        warnings.append("unresolved_questions 為空；若 ticket 很大，需人工確認是否真的沒有未決資訊")

    return ValidationSummary(ok=not errors, errors=errors, warnings=warnings)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QA AI Helper Step 2: AI normalization (低階模型)")
    parser.add_argument("--input", required=True, type=Path, help="Step 1 (preclean) 輸出的 JSON 檔路徑")
    parser.add_argument(
        "--model",
        default="google/gemini-3-flash-preview",
        help="低階 normalizer 使用的 OpenRouter model id，預設 google/gemini-3-flash-preview",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=8000,
        help="max_tokens，預設 8000",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="輸出 JSON 檔路徑；未指定則根據 input 檔名自動產生",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    model = _normalize_model_name(args.model)

    preclean_payload = json.loads(args.input.read_text(encoding="utf-8"))
    ticket_key = preclean_payload.get("ticket_key", "UNKNOWN")
    canonical_language = preclean_payload.get("canonical_language", "en")

    prompt = _build_normalizer_prompt(
        ticket_key=ticket_key,
        preclean_payload=preclean_payload,
        canonical_language=canonical_language,
    )
    response = _call_openrouter(model=model, prompt=prompt, max_tokens=int(args.max_tokens))
    raw_content = str((((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
    normalization_result = _extract_json_object(raw_content)

    validation = _validate_normalization_result(
        preclean_payload=preclean_payload,
        normalized=normalization_result,
    )

    usage = response.get("usage") or {}
    canonical_sections = normalization_result.get("canonical_sections") or {}

    result = {
        "ticket_key": ticket_key,
        "model": model,
        "canonical_language": str(normalization_result.get("canonical_language") or canonical_language),
        "canonical_sections": canonical_sections,
        "duplicate_groups": normalization_result.get("duplicate_groups") or [],
        "excluded_blocks": normalization_result.get("excluded_blocks") or [],
        "unresolved_questions": normalization_result.get("unresolved_questions") or [],
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens") or usage.get("promptTokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or usage.get("completionTokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or usage.get("totalTokens") or 0),
        },
        "validation": {
            "ok": validation.ok,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "raw_model_content": raw_content,
    }

    output_path = args.output or (
        PROJECT_ROOT / "scripts" / "output" / f"normalized_{ticket_key.lower()}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"ticket_key={ticket_key}")
    print(f"model={model}")
    print(f"output={output_path}")
    print(f"canonical_language={result['canonical_language']}")
    print(f"criteria_count={len(canonical_sections.get('criteria') or [])}")
    print(f"technical_count={len(canonical_sections.get('technical_specifications') or [])}")
    print(f"ac_count={len(canonical_sections.get('acceptance_criteria') or [])}")
    print(f"duplicate_groups={len(result['duplicate_groups'])}")
    print(f"excluded_blocks={len(result['excluded_blocks'])}")
    print(f"validation_ok={validation.ok}")
    if validation.errors:
        print("validation_errors=" + "; ".join(validation.errors))
    if validation.warnings:
        print("validation_warnings=" + "; ".join(validation.warnings))
    return 0 if validation.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
