"""Runtime helpers for QA AI Helper generation, merge, and validation."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from app.models.qa_ai_helper import QAAIHelperDraftBody
from app.services.qa_ai_helper_common import json_compact_dumps
from app.services.qa_ai_helper_title_utils import (
    build_testcase_title_summary,
    is_direct_testcase_title_copy,
)


def _normalize_body(payload: Dict[str, Any]) -> Dict[str, Any]:
    model = QAAIHelperDraftBody(
        title=str(payload.get("title") or "").strip(),
        priority=str(payload.get("priority") or "Medium").strip() or "Medium",
        preconditions=[str(item).strip() for item in (payload.get("preconditions") or []) if str(item).strip()],
        steps=[str(item).strip() for item in (payload.get("steps") or []) if str(item).strip()],
        expected_results=[str(item).strip() for item in (payload.get("expected_results") or []) if str(item).strip()],
    )
    return model.model_dump()


def post_merge_generation_outputs(
    *,
    generation_items: Sequence[Dict[str, Any]],
    model_outputs: Sequence[Dict[str, Any]],
    selected_references: Sequence[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    output_by_index = {int(item.get("item_index", -1)): item for item in model_outputs if item is not None}
    references = list(selected_references or [])
    merged: List[Dict[str, Any]] = []
    for expected_index, generation_item in enumerate(generation_items):
        source_output = output_by_index.get(expected_index) or {}
        preconditions = source_output.get("preconditions") or generation_item.get("precondition_hints") or []
        steps = source_output.get("steps") or generation_item.get("step_hints") or []
        expected_results = source_output.get("expected_results") or generation_item.get("expected_hints") or []
        raw_title = str(source_output.get("title") or "").strip()
        title = raw_title
        if not title or is_direct_testcase_title_copy(
            title,
            [
                generation_item.get("title_hint"),
                generation_item.get("verification_item_summary"),
                generation_item.get("intent"),
            ],
        ):
            title = build_testcase_title_summary(
                steps=steps,
                expected_results=expected_results,
                step_hints=generation_item.get("step_hints") or [],
                expected_hints=generation_item.get("expected_hints") or [],
                seed_body_text=generation_item.get("seed_body_text"),
                scenario_title=generation_item.get("scenario_title"),
                section_title=generation_item.get("section_title"),
                title_hint=generation_item.get("title_hint"),
                verification_item_summary=generation_item.get("verification_item_summary"),
                fallback_title=generation_item.get("seed_id") or generation_item["item_key"],
                disallowed_titles=[
                    generation_item.get("title_hint"),
                    generation_item.get("verification_item_summary"),
                    generation_item.get("intent"),
                ],
            )
        body = _normalize_body(
            {
                "title": title,
                "priority": source_output.get("priority") or generation_item.get("priority") or "Medium",
                "preconditions": preconditions,
                "steps": steps,
                "expected_results": expected_results,
            }
        )
        merged.append(
            {
                "item_key": generation_item["item_key"],
                "seed_id": generation_item.get("seed_id"),
                "testcase_id": generation_item.get("seed_id") or generation_item["item_key"],
                "body": body,
                "trace": {
                    "seed_reference_key": source_output.get("seed_reference_key")
                    or generation_item.get("seed_reference_key")
                    or generation_item.get("seed_id")
                    or generation_item.get("item_key"),
                    "section_id": generation_item.get("section_id"),
                    "scenario_title": generation_item.get("scenario_title"),
                    "row_key": generation_item.get("row_key"),
                    "row_group_key": generation_item.get("row_group_key"),
                    "coverage_category": generation_item.get("coverage_category"),
                    "assertion_refs": generation_item.get("assertion_refs") or [],
                    "required_assertions": generation_item.get("required_assertions") or [],
                    "hard_fact_refs": generation_item.get("hard_fact_refs") or [],
                    "missing_required_facts": generation_item.get("missing_required_facts") or [],
                    "applicability": generation_item.get("applicability"),
                    "override_reason": generation_item.get("override_reason"),
                    "reference_ids_used": [
                        item.get("reference_id") or item.get("id") or item.get("ref_id")
                        for item in references
                        if item.get("reference_id") or item.get("id") or item.get("ref_id")
                    ],
                },
            }
        )
    return merged


def validate_merged_drafts(
    *,
    generation_items: Sequence[Dict[str, Any]],
    merged_drafts: Sequence[Dict[str, Any]],
    min_preconditions: int,
    min_steps: int,
    coverage_index: Dict[str, List[str]] | None = None,
) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    expected_keys = [item["item_key"] for item in generation_items]
    actual_keys = [str(item.get("item_key") or "") for item in merged_drafts]

    if len(actual_keys) != len(expected_keys):
        errors.append(
            {
                "code": "cardinality_mismatch",
                "message": f"draft 數量與 generation items 不一致: expected={len(expected_keys)} actual={len(actual_keys)}",
            }
        )

    for expected_key in expected_keys:
        if expected_key not in actual_keys:
            errors.append(
                {
                    "code": "missing_item",
                    "item_key": expected_key,
                    "message": f"缺少 draft item: {expected_key}",
                }
            )

    seen_assertions: Dict[str, List[str]] = {}
    for draft in merged_drafts:
        item_key = str(draft.get("item_key") or "")
        body = draft.get("body") or {}
        trace = draft.get("trace") or {}
        title = str(body.get("title") or "").strip()
        preconditions = body.get("preconditions") or []
        steps = body.get("steps") or []
        expected_results = body.get("expected_results") or []
        if not title:
            errors.append({"code": "empty_title", "item_key": item_key, "message": "title 不可為空"})
        if len(preconditions) < min_preconditions:
            errors.append(
                {
                    "code": "preconditions_too_short",
                    "item_key": item_key,
                    "message": f"preconditions 至少需 {min_preconditions} 條",
                }
            )
        if len(steps) < min_steps:
            errors.append(
                {
                    "code": "steps_too_short",
                    "item_key": item_key,
                    "message": f"steps 至少需 {min_steps} 步",
                }
            )
        if len(expected_results) < 1:
            errors.append(
                {
                    "code": "expected_results_empty",
                    "item_key": item_key,
                    "message": "expected_results 至少需 1 條",
                }
            )
        for assertion_ref in trace.get("assertion_refs") or []:
            seen_assertions.setdefault(str(assertion_ref), []).append(item_key)
        if trace.get("missing_required_facts"):
            errors.append(
                {
                    "code": "missing_required_facts",
                    "item_key": item_key,
                    "message": "draft 仍包含缺漏 hard facts",
                }
            )

    for assertion_ref, expected_item_keys in (coverage_index or {}).items():
        actual_item_keys = seen_assertions.get(assertion_ref, [])
        if not actual_item_keys and expected_item_keys:
            errors.append(
                {
                    "code": "assertion_uncovered",
                    "assertion_ref": assertion_ref,
                    "message": f"assertion 未被任何 draft 覆蓋: {assertion_ref}",
                }
            )

    return {
        "ok": not errors,
        "error_count": len(errors),
        "errors": errors,
        "expected_count": len(expected_keys),
        "actual_count": len(actual_keys),
    }


def build_repair_prompt_payload(
    *,
    merged_drafts: Sequence[Dict[str, Any]],
    validation_errors: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    invalid_outputs: List[Dict[str, Any]] = []
    invalid_keys = {str(error.get("item_key") or "") for error in validation_errors if str(error.get("item_key") or "")}
    for draft in merged_drafts:
        if draft.get("item_key") in invalid_keys:
            invalid_outputs.append(
                {
                    "item_index": len(invalid_outputs),
                    "item_key": draft.get("item_key"),
                    **(draft.get("body") or {}),
                }
            )
    return {
        "invalid_outputs_json": json_compact_dumps(invalid_outputs),
        "validator_errors_json": json_compact_dumps(list(validation_errors)),
    }
