from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings
from app.services.qa_ai_helper_llm_service import QAAIHelperLLMService
from app.services.qa_ai_helper_prompt_service import QAAIHelperPromptService


def test_seed_stage_reads_markdown_prompt_file(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "seed.md").write_text(
        "plan={requirement_plan_json}\nitems={generation_items_json}",
        encoding="utf-8",
    )

    service = QAAIHelperPromptService(
        Settings().ai.qa_ai_helper,
        prompt_dir=prompt_dir,
    )
    rendered = service.render_stage_prompt(
        "seed",
        {
            "requirement_plan_json": '{"status":"locked"}',
            "generation_items_json": '[{"item_index":0}]',
        },
    )

    assert rendered == 'plan={"status":"locked"}\nitems=[{"item_index":0}]'


def test_missing_seed_refine_prompt_uses_deterministic_fallback(tmp_path: Path) -> None:
    helper = Settings().ai.qa_ai_helper.model_copy(deep=True)
    helper.models.seed.model = "custom/seed"
    helper.models.seed_refine = None

    service = QAAIHelperPromptService(
        helper,
        prompt_dir=tmp_path / "missing-prompts",
    )
    rendered = service.render_stage_prompt(
        "seed_refine",
        {"seed_comments_json": '[{"seed_reference_key":"seed-1","comment_text":"請補充前置條件"}]'},
    )

    assert "testcase seed 修補器" in rendered
    assert "SEED_COMMENTS" in rendered
    assert service.get_stage_model("seed_refine").model == "custom/seed"


def test_testcase_prompt_file_supports_seed_reference_contract(tmp_path: Path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / "testcase.md").write_text(
        "items={generation_items_json}\nmin_steps={min_steps}\nseed_ref={selected_references_json}",
        encoding="utf-8",
    )

    service = QAAIHelperPromptService(
        Settings().ai.qa_ai_helper,
        prompt_dir=prompt_dir,
    )
    rendered = service.render_stage_prompt(
        "testcase",
        {
            "generation_items_json": '[{"item_index":0,"seed_reference_key":"seed-1"}]',
            "selected_references_json": '[{"reference_id":"seed-1"}]',
        },
    )

    assert "seed_reference_key" in rendered
    assert "min_steps=3" in rendered


def test_default_testcase_fallback_requires_numbering_for_multi_item_fields(tmp_path: Path) -> None:
    service = QAAIHelperPromptService(
        Settings().ai.qa_ai_helper,
        prompt_dir=tmp_path / "missing-prompts",
    )

    rendered = service.render_stage_prompt("testcase")

    assert "多於 1 個項目" in rendered
    assert "1. ..., 2. ..." in rendered
    assert "只有 1 項，則不要加編號" in rendered
    assert "不得直接複製 title_hint" in rendered


def test_default_repair_fallback_requires_numbering_for_multi_item_fields(tmp_path: Path) -> None:
    service = QAAIHelperPromptService(
        Settings().ai.qa_ai_helper,
        prompt_dir=tmp_path / "missing-prompts",
    )

    rendered = service.render_stage_prompt("repair")

    assert "多於 1 個項目" in rendered
    assert "1. ..., 2. ..." in rendered
    assert "只有 1 項，則不要加編號" in rendered


def test_llm_fallback_preserves_seed_reference_key_for_testcase_stage() -> None:
    service = QAAIHelperLLMService()
    payload = service._fallback_generate_from_prompt(
        (
            'GENERATION_ITEMS=[{"item_index":0,"item_key":"item-1","seed_reference_key":"seed-1",'
            '"title_hint":"使用者點擊 audience name 後應成功開啟詳情頁並顯示狀態",'
            '"step_hints":["點擊 audience name"],'
            '"expected_hints":["使用者點擊 audience name 後應成功開啟詳情頁並顯示狀態"]}]'
        ),
        "testcase",
    )

    assert payload["outputs"][0]["item_index"] == 0
    assert payload["outputs"][0]["seed_reference_key"] == "seed-1"
    assert payload["outputs"][0]["title"] == "成功開啟詳情頁並顯示狀態"
