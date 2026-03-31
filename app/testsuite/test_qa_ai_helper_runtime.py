from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.qa_ai_helper_runtime import (
    build_repair_prompt_payload,
    post_merge_generation_outputs,
    validate_merged_drafts,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "qa_ai_helper"


def test_post_merge_generation_outputs_restores_trace_and_reference_ids() -> None:
    merged = post_merge_generation_outputs(
        generation_items=[
            {
                "item_key": "TCG-1.010.010",
                "seed_id": "TCG-1.010.010",
                "section_id": "TCG-1.010",
                "scenario_title": "Open detail",
                "row_key": "TCG-1.010.rg-001.row-001",
                "row_group_key": "rg-001",
                "coverage_category": "happy",
                "assertion_refs": ["as-001"],
                "required_assertions": [{"assertion_id": "as-001", "text": "detail opens"}],
                "hard_fact_refs": ["hf-001"],
                "missing_required_facts": [],
                "applicability": "applicable",
                "override_reason": None,
                "title_hint": "Open detail",
                "precondition_hints": ["login"],
                "step_hints": ["click detail", "observe page", "verify title"],
                "expected_hints": ["detail opens"],
            }
        ],
        model_outputs=[
            {
                "item_index": 0,
                "title": "Open detail testcase",
                "priority": "High",
                "preconditions": ["已登入"],
                "steps": ["進入列表", "點擊 detail", "確認新分頁"],
                "expected_results": ["成功開啟 detail 頁面"],
            }
        ],
        selected_references=[{"reference_id": "ref-001", "title": "history case"}],
    )

    assert merged[0]["body"]["title"] == "Open detail testcase"
    assert merged[0]["trace"]["assertion_refs"] == ["as-001"]
    assert merged[0]["trace"]["reference_ids_used"] == ["ref-001"]


def test_validate_merged_drafts_reports_cardinality_coverage_and_missing_facts() -> None:
    generation_items = [
        {"item_key": "A"},
        {"item_key": "B"},
    ]
    merged_drafts = [
        {
            "item_key": "A",
            "body": {
                "title": "A",
                "priority": "Medium",
                "preconditions": ["p1"],
                "steps": ["s1", "s2", "s3"],
                "expected_results": ["ok"],
            },
            "trace": {"assertion_refs": ["as-001"], "missing_required_facts": []},
        },
        {
            "item_key": "B",
            "body": {
                "title": "B",
                "priority": "Medium",
                "preconditions": [],
                "steps": ["only-one-step"],
                "expected_results": [],
            },
            "trace": {"assertion_refs": [], "missing_required_facts": ["placeholder"]},
        },
    ]

    summary = validate_merged_drafts(
        generation_items=generation_items,
        merged_drafts=merged_drafts,
        min_preconditions=1,
        min_steps=3,
        coverage_index={"as-001": ["A"], "as-002": ["B"]},
    )

    assert summary["ok"] is False
    codes = {error["code"] for error in summary["errors"]}
    assert "preconditions_too_short" in codes
    assert "steps_too_short" in codes
    assert "expected_results_empty" in codes
    assert "missing_required_facts" in codes
    assert "assertion_uncovered" in codes


def test_build_repair_prompt_payload_only_includes_invalid_items() -> None:
    payload = build_repair_prompt_payload(
        merged_drafts=[
            {
                "item_key": "A",
                "body": {"title": "A", "priority": "Medium"},
            },
            {
                "item_key": "B",
                "body": {"title": "B", "priority": "Medium"},
            },
        ],
        validation_errors=[
            {"item_key": "B", "code": "steps_too_short"},
            {"item_key": "B", "code": "expected_results_empty"},
        ],
    )

    assert '"item_key":"B"' in payload["invalid_outputs_json"]
    assert '"item_key":"A"' not in payload["invalid_outputs_json"]
    assert '"steps_too_short"' in payload["validator_errors_json"]


def test_runtime_contract_fixture_matches_expected_snapshot() -> None:
    fixture = json.loads(
        (FIXTURE_DIR / "runtime_contract_fixture.json").read_text(encoding="utf-8")
    )

    merged = post_merge_generation_outputs(
        generation_items=fixture["generation_items"],
        model_outputs=fixture["model_outputs"],
        selected_references=fixture["selected_references"],
    )
    expected = fixture["expected"]

    assert merged[0]["item_key"] == expected["merged_item_key"]
    assert merged[0]["trace"]["reference_ids_used"] == expected["reference_ids_used"]

    summary = validate_merged_drafts(
        generation_items=fixture["generation_items"],
        merged_drafts=merged,
        min_preconditions=1,
        min_steps=3,
        coverage_index=fixture["coverage_index"],
    )

    assert summary["ok"] is False
    codes = {error["code"] for error in summary["errors"]}
    for code in expected["validation_error_codes"]:
        assert code in codes
