from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.qa_ai_helper import QAAIHelperApplicabilityStatus
from app.services.qa_ai_helper_planner import QAAIHelperPlanner


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "qa_ai_helper"


def _canonical_content() -> dict:
    return {
        "userStoryNarrative": (
            "As a QA user\n"
            "I want to generate test cases\n"
            "So that I can review coverage"
        ),
        "criteria": "- Detail page opens in a new tab\n- Display current status",
        "technicalSpecifications": "- API path: /detail/view\n- Date format: yyyy-MM-dd",
        "acceptanceCriteria": (
            "Scenario 1: Open detail page\n"
            "Given the user is on the list page\n"
            "When the user clicks the detail name\n"
            "Then the detail page opens in a new tab\n"
            "And the tab title matches the entity name\n\n"
            "Scenario 2: Display current status\n"
            "Given the user is on the detail page\n"
            "When the page is loaded\n"
            "Then the current status is displayed\n"
            "And the updated date uses yyyy-MM-dd"
        ),
        "assumptions": [],
        "unknowns": [],
    }


def test_resolve_raw_sources_extracts_multilingual_blocks_and_references() -> None:
    planner = QAAIHelperPlanner()

    payload = planner.resolve_raw_sources(
        summary="View audience details",
        description=(
            "Original:\n"
            "Scenario 1: Open detail page\n"
            "Then display yyyy-MM-dd\n\n"
            "品牌管理員查看人群詳情\n"
            "【0323 更新】原計算基準時間改為資料截止時間\n"
            "DOC: https://example.com/spec\n"
            "Ref: TCG-125418"
        ),
        comments=["補充說明 comment"],
    )

    assert payload["comments"] == ["補充說明 comment"]
    assert set(payload["language_variants"]) >= {"en", "zh"}
    assert any(block["source_type"] == "update_note" for block in payload["source_blocks"])
    assert "https://example.com/spec" in payload["references"]
    assert "TCG-125418" in payload["references"]


def test_validate_canonical_content_detects_missing_fields_and_unresolved_markers() -> None:
    planner = QAAIHelperPlanner()

    result = planner.validate_canonical_content(
        {
            "userStoryNarrative": "As a QA user\nI want TBD",
            "criteria": "TODO",
            "technicalSpecifications": "unknown",
            "acceptanceCriteria": "Scenario 1: TBD",
            "assumptions": [],
            "unknowns": [],
        }
    )

    assert result["quality_level"] == "low"
    assert "userStoryNarrative.so_that" in result["missing_fields"]
    assert "criteria" in result["unresolved_items"]
    assert result["override_required"] is True


def test_build_plan_allocates_sections_with_ten_step_ids_and_override_trace() -> None:
    planner = QAAIHelperPlanner()
    base_plan = planner.build_plan(
        ticket_key="TCG-130078",
        canonical_revision_id=11,
        canonical_language="en",
        content=_canonical_content(),
        counter_settings={"middle": "010", "tail": "010"},
    )

    first_row_key = base_plan["sections"][0]["matrix"]["row_groups"][0]["rows"][0]["row_key"]
    plan = planner.build_plan(
        ticket_key="TCG-130078",
        canonical_revision_id=11,
        canonical_language="en",
        content=_canonical_content(),
        counter_settings={"middle": "010", "tail": "010"},
        applicability_overrides={
            first_row_key: {
                "status": QAAIHelperApplicabilityStatus.MANUAL_EXEMPT.value,
                "reason": "manual review",
            }
        },
        selected_references={"section_references": {"TCG-130078.010": [{"reference_id": "ref-1"}]}},
    )

    assert [section["section_id"] for section in plan["sections"]] == [
        "TCG-130078.010",
        "TCG-130078.020",
    ]
    assert plan["impact_summary"]["selected_reference_count"] == 1
    row = plan["sections"][0]["matrix"]["row_groups"][0]["rows"][0]
    assert row["applicability"] == "manual_exempt"
    assert row["override_reason"] == "manual review"
    assert all(int(item["seed_id"].split(".")[-1]) % 10 == 0 for item in plan["generation_items"])
    assert plan["coverage_index"]


def test_requirement_delta_impact_uses_scoped_replanning_for_acceptance_modify() -> None:
    planner = QAAIHelperPlanner()
    content = _canonical_content()
    previous_plan = planner.build_plan(
        ticket_key="TCG-130078",
        canonical_revision_id=1,
        canonical_language="en",
        content=content,
        counter_settings={"middle": "010", "tail": "010"},
    )
    updated_content = planner.apply_requirement_delta(
        content=content,
        delta={
            "delta_type": "modify",
            "target_scope": "Acceptance Criteria",
            "target_scenario_key": "ac.scenario_001",
            "proposed_content": {
                "title": "Open detail page updated",
                "text": (
                    "Given the user is on the list page\n"
                    "When the user clicks the detail name\n"
                    "Then the detail page opens in a new tab\n"
                    "And the breadcrumb is displayed"
                ),
            },
        },
    )
    delta_impact = planner.analyze_requirement_delta_impact(
        previous_content=content,
        updated_content=updated_content,
        delta={
            "delta_type": "modify",
            "target_scope": "Acceptance Criteria",
            "target_scenario_key": "ac.scenario_001",
        },
    )
    new_plan = planner.build_plan(
        ticket_key="TCG-130078",
        canonical_revision_id=2,
        canonical_language="en",
        content=updated_content,
        counter_settings={"middle": "010", "tail": "010"},
        previous_plan=previous_plan,
        delta_impact=delta_impact,
    )

    assert delta_impact["mode"] == "scoped"
    assert new_plan["impact_summary"]["replanning_mode"] == "scoped"
    assert new_plan["impact_summary"]["impacted_scenario_keys"] == ["ac.scenario_001"]
    assert new_plan["sections"][0]["scenario_title"] == "Open detail page updated"
    assert new_plan["sections"][1] == previous_plan["sections"][1]


def test_build_persistable_plan_compacts_redundant_payload_and_runtime_hydration_restores_assertions() -> None:
    planner = QAAIHelperPlanner()
    plan = planner.build_plan(
        ticket_key="TCG-130078",
        canonical_revision_id=11,
        canonical_language="en",
        content=_canonical_content(),
        counter_settings={"middle": "010", "tail": "010"},
    )

    compact = planner.build_persistable_plan(plan)
    first_section = compact["sections"][0]
    assert "criteria_items" not in compact
    assert "technical_items" not in compact
    assert "coverage_index" not in compact
    assert isinstance(compact["generation_items"][0], str)
    assert "generation_items" not in first_section
    assert "hard_facts" not in first_section
    assert "assertions" not in first_section
    assert "projected_constraints" not in first_section
    assert "given" not in first_section
    assert "when" not in first_section
    assert "then" not in first_section
    assert "and" not in first_section
    assert first_section["generation_budget"]["planned_row_count"] >= 1


def test_missing_hard_facts_trigger_complexity_guard_and_payload_filter() -> None:
    planner = QAAIHelperPlanner()
    content = {
        "userStoryNarrative": "As a QA user\nI want TBD\nSo that I can review placeholders",
        "criteria": "- Display format TBD",
        "technicalSpecifications": "- API path TBD",
        "acceptanceCriteria": (
            "Scenario 1: Show format\n"
            "Given the user opens detail\n"
            "When the detail loads\n"
            "Then the page shows date format TBD"
        ),
        "assumptions": [],
        "unknowns": ["format TBD"],
    }
    plan = planner.build_plan(
        ticket_key="TCG-130099",
        canonical_revision_id=3,
        canonical_language="en",
        content=content,
        counter_settings={"middle": "010", "tail": "010"},
    )
    section = plan["sections"][0]
    complexity = planner.compute_complexity(section)
    payload = planner.build_model_facing_payload(
        ticket_key="TCG-130099",
        output_language="zh-TW",
        section={
            **section,
            "generation_items": [
                {
                    **section["generation_items"][0],
                    "applicability": "applicable",
                }
            ],
        },
        section_references=[{"reference_id": "ref-1", "title": "Ref"}],
    )

    assert section["generation_items"][0]["missing_required_facts"]
    assert complexity["hard_trigger"] is True
    assert complexity["batch_mode"] == "one-seed-per-call"
    assert len(payload["generation_items"]) == 1
    assert payload["selected_references"][0]["reference_id"] == "ref-1"


def test_build_plan_avoids_cross_product_for_unrelated_explicit_axes() -> None:
    planner = QAAIHelperPlanner()
    content = {
        "userStoryNarrative": (
            "As a QA user\n"
            "I want to validate explicit option groups\n"
            "So that matrix planning does not multiply unrelated rules"
        ),
        "criteria": (
            "- Quick selections: Today / Yesterday / Last 7 Days / Last 14 Days / Last 30 Days\n"
            "- Operation Status: Running / Paused\n"
            "- Creation Type: Rule-based / Import-based"
        ),
        "technicalSpecifications": "- Date format: yyyy-MM-dd",
        "acceptanceCriteria": (
            "Scenario 1: Review detail filters\n"
            "Given the admin opens the detail page\n"
            "When the admin reviews available filters\n"
            "Then quick selections are shown correctly"
        ),
        "assumptions": [],
        "unknowns": [],
    }

    plan = planner.build_plan(
        ticket_key="TCG-130111",
        canonical_revision_id=9,
        canonical_language="en",
        content=content,
        counter_settings={"middle": "010", "tail": "010"},
    )

    first_section = plan["sections"][0]
    assert first_section["generation_budget"]["planned_row_count"] == 9
    assert len(first_section["matrix"]["row_groups"]) == 3
    assert all(
        len(row["axis_values"]) == 1
        for group in first_section["matrix"]["row_groups"]
        for row in group["rows"]
    )


def test_team_extensions_add_normalized_traits_constraints_and_seed_hints() -> None:
    planner = QAAIHelperPlanner()

    plan = planner.build_plan(
        ticket_key="TCG-130078",
        canonical_revision_id=11,
        canonical_language="en",
        content=_canonical_content(),
        counter_settings={"middle": "010", "tail": "010"},
        team_extensions=[
            {
                "scenario_key": "ac.scenario_001",
                "traits": ["custom_team_trait"],
                "constraints": ["Must display custom extension banner"],
                "seed_hints": [
                    {
                        "category": "edge",
                        "title_hint": "Verify extension-specific banner",
                        "precondition_hints": ["已啟用 team extension"],
                        "step_hints": ["進入 detail 頁", "檢查 extension banner", "確認 banner 文案"],
                        "expected_hints": ["顯示 extension banner"],
                    }
                ],
            }
        ],
    )

    first_section = plan["sections"][0]
    second_section = plan["sections"][1]

    assert "custom_team_trait" in first_section["detected_traits"]
    assert all(constraint["text"] != "Must display custom extension banner" for constraint in second_section["projected_constraints"])
    assert any(constraint["text"] == "Must display custom extension banner" for constraint in first_section["projected_constraints"])
    assert any(item["override_reason"] == "team_extension" for item in first_section["generation_items"])
    assert plan["team_extensions"][0]["traits"] == ["custom_team_trait"]


def test_planner_contract_fixture_matches_expected_snapshot() -> None:
    fixture = json.loads(
        (FIXTURE_DIR / "planner_contract_fixture.json").read_text(encoding="utf-8")
    )
    planner = QAAIHelperPlanner()

    plan = planner.build_plan(
        ticket_key=fixture["ticket_key"],
        canonical_revision_id=fixture["canonical_revision_id"],
        canonical_language=fixture["canonical_language"],
        content=fixture["content"],
        counter_settings=fixture["counter_settings"],
    )

    expected = fixture["expected"]
    assert [section["section_id"] for section in plan["sections"]] == expected["section_ids"]
    assert [section["scenario_title"] for section in plan["sections"]] == expected["scenario_titles"]
    assert len(plan["generation_items"]) == expected["generation_item_count"]
    assert sorted(plan["coverage_index"].keys()) == expected["coverage_keys"]

    first_section = plan["sections"][0]
    assert first_section["matrix"]["row_groups"][0]["group_key"] == expected["first_row_group_key"]
    assert first_section["generation_budget"]["planned_row_count"] == expected["first_generation_budget"]["planned_row_count"]
    assert first_section["generation_budget"]["estimated_output_tokens"] == expected["first_generation_budget"]["estimated_output_tokens"]

    payload = planner.build_model_facing_payload(
        ticket_key=fixture["ticket_key"],
        output_language="zh-TW",
        section=first_section,
        section_references=[
            {
                "reference_id": expected["first_payload"]["selected_reference_id"],
                "title": "history",
            }
        ],
    )

    assert payload["section_summary"]["section_id"] == expected["first_payload"]["section_id"]
    assert payload["selected_references"][0]["reference_id"] == expected["first_payload"]["selected_reference_id"]
    assert len(payload["generation_items"]) == expected["first_payload"]["generation_item_count"]
    assert [item["item_key"] for item in payload["generation_items"]] == expected["first_payload"]["item_keys"]
    assert payload["generation_rules"]["complexity"]["score"] == expected["first_payload"]["complexity"]["score"]
    assert payload["generation_rules"]["complexity"]["batch_mode"] == expected["first_payload"]["complexity"]["batch_mode"]
    assert payload["generation_rules"]["complexity"]["hard_trigger"] is expected["first_payload"]["complexity"]["hard_trigger"]
