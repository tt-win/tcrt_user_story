from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.services.qa_ai_helper_prompt_service import QAAIHelperPromptService

GOLDEN_STAGES = ("seed", "seed_refine", "testcase", "repair")

GOLDEN_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "qa_ai_helper" / "prompts"

GOLDEN_REPLACEMENTS = {
    "seed": {
        "output_language": "繁體中文",
        "section_summary_json": '{"golden":"section_summary"}',
        "requirement_plan_json": '{"golden":"requirement_plan"}',
        "generation_items_json": '[{"golden":"generation_item"}]',
    },
    "seed_refine": {
        "output_language": "繁體中文",
        "seed_items_json": '[{"golden":"seed_item"}]',
        "seed_comments_json": '[{"golden":"seed_comment"}]',
    },
    "testcase": {
        "output_language": "繁體中文",
        "min_steps": "3",
        "min_preconditions": "1",
        "section_summary_json": '{"golden":"section_summary"}',
        "shared_constraints_json": "[]",
        "selected_references_json": "[]",
        "generation_items_json": '[{"golden":"generation_item"}]',
    },
    "repair": {
        "output_language": "繁體中文",
        "min_steps": "3",
        "min_preconditions": "1",
        "invalid_outputs_json": '[{"golden":"invalid_output"}]',
        "validator_errors_json": '[{"golden":"validator_error"}]',
    },
}


def render_stage(stage: str) -> str:
    service = QAAIHelperPromptService(Settings().ai.qa_ai_helper)
    return service.render_stage_prompt(stage, GOLDEN_REPLACEMENTS[stage])


def regenerate() -> None:
    GOLDEN_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for stage in GOLDEN_STAGES:
        rendered = render_stage(stage)
        fixture_path = GOLDEN_FIXTURE_DIR / f"{stage}.golden.txt"
        fixture_path.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    regenerate()
