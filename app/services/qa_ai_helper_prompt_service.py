"""Prompt loading for the rewritten QA AI Helper.

此模組處理 seed / seed_refine / testcase prompt，並暫時保留 legacy repair alias。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Literal, Optional

from app.config import QAAIHelperConfig, QAAIHelperStageModelConfig, get_settings

QAAIHelperPromptStage = Literal["seed", "seed_refine", "testcase", "repair"]

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_DIR = (
    Path(__file__).resolve().parents[2] / "prompts" / "jira_testcase_helper"
)
PROMPT_FILE_MAP: Dict[QAAIHelperPromptStage, str] = {
    "seed": "seed.md",
    "seed_refine": "seed_refine.md",
    "testcase": "testcase.md",
    "repair": "repair.md",
}

FALLBACK_PROMPTS: Dict[QAAIHelperPromptStage, str] = {
    "seed": (
        "你是 testcase seed 產生器。使用 {output_language}。\n"
        "你只能根據 requirement plan 與 verification items 產生 seed，"
        "不得新增未提供的需求範圍或 section。\n"
        "每個 item_index 必須輸出且只能輸出一筆 seed。\n"
        "只輸出 JSON，禁止輸出 Markdown、說明或 code fence。\n\n"
        "SECTION_SUMMARY={section_summary_json}\n"
        "REQUIREMENT_PLAN={requirement_plan_json}\n"
        "GENERATION_ITEMS={generation_items_json}\n\n"
        "輸出 schema:\n"
        '{"outputs":[{"item_index":0,"seed_reference_key":"","section_id":"","verification_item_ref":"","check_condition_ids":[],"seed_summary":"","seed_body":"","coverage_tags":["Happy Path"]}]}'
    ),
    "seed_refine": (
        "你是 testcase seed 修補器。使用 {output_language}。\n"
        "你只能根據 seed 註解修補既有 seed；除非註解明確要求拆分，否則不得新增 seed。\n"
        "只輸出 JSON，禁止輸出 Markdown、說明或 code fence。\n\n"
        "SEED_ITEMS={seed_items_json}\n"
        "SEED_COMMENTS={seed_comments_json}\n\n"
        "輸出 schema:\n"
        '{"outputs":[{"item_index":0,"seed_reference_key":"","section_id":"","verification_item_ref":"","check_condition_ids":[],"seed_summary":"","seed_body":"","coverage_tags":["Happy Path"]}]}'
    ),
    "testcase": (
        "你是 testcase body 轉換器。使用 {output_language}。\n"
        "你只能根據 generation_items 與 required_assertions 產生 testcase body，"
        "不得新增未提供的 requirement、案例或 metadata。\n"
        "每個 item_index 必須輸出且只能輸出一筆 testcase body。\n"
        "preconditions 至少 {min_preconditions} 條，steps 至少 {min_steps} 步，"
        "expected_results 至少 1 條且需為可觀測結果。\n"
        "只輸出 JSON，禁止輸出 Markdown、說明或 code fence。\n\n"
        "SECTION_SUMMARY={section_summary_json}\n"
        "SHARED_CONSTRAINTS={shared_constraints_json}\n"
        "SELECTED_REFERENCES={selected_references_json}\n"
        "GENERATION_ITEMS={generation_items_json}\n\n"
        "輸出 schema:\n"
        '{"outputs":[{"item_index":0,"seed_reference_key":"","title":"","priority":"Medium","preconditions":[""],"steps":["","",""],"expected_results":[""]}]}'
    ),
    "repair": (
        "你是 testcase body 修補器。使用 {output_language}。\n"
        "只能修補 validator 指出的 testcase body 欄位錯誤，不得新增 testcase、"
        "不得調整 item_index、不得更改 requirement scope。\n"
        "preconditions 至少 {min_preconditions} 條，steps 至少 {min_steps} 步，"
        "expected_results 至少 1 條且需為可觀測結果。\n"
        "只輸出 JSON，禁止輸出其他文字。\n\n"
        "INVALID_OUTPUTS={invalid_outputs_json}\n"
        "VALIDATOR_ERRORS={validator_errors_json}\n\n"
        "輸出 schema:\n"
        '{"outputs":[{"item_index":0,"title":"","priority":"Medium","preconditions":[""],"steps":["","",""],"expected_results":[""]}]}'
    ),
}


class QAAIHelperPromptService:
    """管理 seed/testcase prompt 與 model metadata。"""

    def __init__(
        self,
        helper_config: Optional[QAAIHelperConfig] = None,
        prompt_dir: Optional[Path] = None,
    ) -> None:
        settings = get_settings()
        self._config = helper_config or settings.ai.qa_ai_helper
        self._prompt_dir = Path(prompt_dir) if prompt_dir else DEFAULT_PROMPT_DIR

    def get_stage_model(self, stage: QAAIHelperPromptStage) -> QAAIHelperStageModelConfig:
        if stage == "seed":
            return self._config.models.seed
        if stage == "seed_refine":
            return self._config.models.seed_refine or self._config.models.seed
        if stage == "repair":
            return self._config.models.repair or self._config.models.testcase
        return self._config.models.testcase

    def get_stage_prompt_template(self, stage: QAAIHelperPromptStage) -> str:
        filename = PROMPT_FILE_MAP[stage]
        path = self._prompt_dir / filename
        try:
            template = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning(
                "讀取 qa_ai_helper prompt 檔失敗，改用 fallback: stage=%s path=%s error=%s",
                stage,
                path,
                exc,
            )
            template = ""

        if template:
            return template

        logger.warning(
            "qa_ai_helper prompt 檔不存在或為空，改用 fallback template: stage=%s path=%s",
            stage,
            path,
        )
        return FALLBACK_PROMPTS[stage]

    def render_stage_prompt(
        self,
        stage: QAAIHelperPromptStage,
        replacements: Optional[Dict[str, str]] = None,
    ) -> str:
        rendered = self.get_stage_prompt_template(stage)
        values: Dict[str, str] = {
            "output_language": "繁體中文",
            "min_steps": str(self._config.min_steps),
            "min_preconditions": str(self._config.min_preconditions),
            "section_summary_json": "{}",
            "requirement_plan_json": "{}",
            "shared_constraints_json": "[]",
            "selected_references_json": "[]",
            "generation_items_json": "[]",
            "seed_items_json": "[]",
            "seed_comments_json": "[]",
            "invalid_outputs_json": "[]",
            "validator_errors_json": "[]",
        }
        for key, value in (replacements or {}).items():
            values[key] = "" if value is None else str(value)
        for key, value in values.items():
            rendered = rendered.replace("{" + key + "}", value)
        return rendered


_qa_ai_helper_prompt_service: Optional[QAAIHelperPromptService] = None


def get_qa_ai_helper_prompt_service() -> QAAIHelperPromptService:
    global _qa_ai_helper_prompt_service
    if _qa_ai_helper_prompt_service is None:
        _qa_ai_helper_prompt_service = QAAIHelperPromptService()
    return _qa_ai_helper_prompt_service
