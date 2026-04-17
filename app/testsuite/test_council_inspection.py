"""Tests for MAGI inspection pipeline (config / prompt / LLM / transform / SSE)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings, InspectionRoleConfig, InspectionConfig


# ── Task 10.1 — Config ─────────────────────────────────────────────


class TestInspectionConfig:
    """Test inspection model config loading, env var override, fallback."""

    def test_default_inspection_roles_count(self):
        cfg = InspectionConfig()
        assert len(cfg.roles) == 3

    def test_default_role_labels(self):
        cfg = InspectionConfig()
        labels = [r.label for r in cfg.roles]
        assert labels == ["A", "B", "C"]

    def test_max_scenarios_warning_default(self):
        cfg = InspectionConfig()
        assert cfg.max_scenarios_warning == 5

    def test_inspection_model_fields_exist(self):
        settings = Settings()
        models = settings.ai.qa_ai_helper.models
        assert hasattr(models, "inspection_extraction_a")
        assert hasattr(models, "inspection_extraction_b")
        assert hasattr(models, "inspection_extraction_c")
        assert hasattr(models, "inspection_consolidation")

    def test_env_var_override_inspection_models(self):
        env_overrides = {
            "QA_AI_HELPER_MODEL_INSPECTION_EXTRACTION_A": "test-model-a",
            "QA_AI_HELPER_MODEL_INSPECTION_EXTRACTION_B": "test-model-b",
            "QA_AI_HELPER_MODEL_INSPECTION_EXTRACTION_C": "test-model-c",
            "QA_AI_HELPER_MODEL_INSPECTION_CONSOLIDATION": "test-model-consol",
        }
        with patch.dict(os.environ, env_overrides):
            settings = Settings()
            models_cfg = settings.ai.qa_ai_helper.models
            # from_env should pick up env vars
            models_with_env = models_cfg.from_env()
            assert models_with_env.inspection_extraction_a.model == "test-model-a"
            assert models_with_env.inspection_extraction_b.model == "test-model-b"
            assert models_with_env.inspection_extraction_c.model == "test-model-c"
            assert models_with_env.inspection_consolidation.model == "test-model-consol"

    def test_inspection_model_fallback_to_default(self):
        settings = Settings()
        models_cfg = settings.ai.qa_ai_helper.models.from_env()
        # Should have non-None model values (either from env or default)
        assert models_cfg.inspection_extraction_a is not None
        assert models_cfg.inspection_consolidation is not None


# ── Task 10.2 — Prompt ─────────────────────────────────────────────


class TestInspectionPrompts:
    """Test inspection prompt loading and placeholder replacement."""

    def test_inspection_extraction_prompt_loads(self, tmp_path: Path):
        from app.services.qa_ai_helper_prompt_service import QAAIHelperPromptService

        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / "inspection_extraction.md").write_text(
            "role={role_name}\nfocus={role_focus}\nscenario={scenario_text}",
            encoding="utf-8",
        )
        service = QAAIHelperPromptService(
            Settings().ai.qa_ai_helper,
            prompt_dir=prompt_dir,
        )
        rendered = service.render_stage_prompt(
            "inspection_extraction",
            {
                "role_name": "Happy Path",
                "role_focus": "Permission checks",
                "scenario_text": "User clicks submit",
            },
        )
        assert "role=Happy Path" in rendered
        assert "focus=Permission checks" in rendered
        assert "scenario=User clicks submit" in rendered

    def test_inspection_consolidation_prompt_loads(self, tmp_path: Path):
        from app.services.qa_ai_helper_prompt_service import QAAIHelperPromptService

        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / "inspection_consolidation.md").write_text(
            "results={extraction_results}\nticket={ticket_key}",
            encoding="utf-8",
        )
        service = QAAIHelperPromptService(
            Settings().ai.qa_ai_helper,
            prompt_dir=prompt_dir,
        )
        rendered = service.render_stage_prompt(
            "inspection_consolidation",
            {
                "extraction_results": "model A output...",
                "ticket_key": "TCG-123",
            },
        )
        assert "results=model A output..." in rendered
        assert "ticket=TCG-123" in rendered

    def test_inspection_stages_in_prompt_stage_type(self):
        from app.services.qa_ai_helper_prompt_service import QAAIHelperPromptStage, PROMPT_FILE_MAP

        # QAAIHelperPromptStage is a Literal type; check PROMPT_FILE_MAP keys
        assert "inspection_extraction" in PROMPT_FILE_MAP
        assert "inspection_consolidation" in PROMPT_FILE_MAP


# ── Task 10.3 — LLM call layer ────────────────────────────────────


class TestInspectionLLMCalls:
    """Test inspection extraction / consolidation LLM method signatures."""

    def test_llm_service_has_inspection_methods(self):
        from app.services.qa_ai_helper_llm_service import QAAIHelperLLMService

        svc = QAAIHelperLLMService()
        assert hasattr(svc, "call_inspection_extraction")
        assert hasattr(svc, "call_inspection_consolidation")
        assert callable(svc.call_inspection_extraction)
        assert callable(svc.call_inspection_consolidation)

    def test_llm_stage_type_has_inspection_stages(self):
        from app.services.qa_ai_helper_llm_service import QAAIHelperLLMStage
        import typing

        args = typing.get_args(QAAIHelperLLMStage)
        assert "inspection_extraction_a" in args
        assert "inspection_extraction_b" in args
        assert "inspection_extraction_c" in args
        assert "inspection_consolidation" in args


# ── Task 10.4 — Core flow (transform + validate) ──────────────────


class TestInspectionTransform:
    """Test consolidation JSON → sections payload transform and validation."""

    def _make_service(self):
        from app.services.qa_ai_helper_service import QAAIHelperService

        return QAAIHelperService()

    def test_validate_consolidation_json_valid(self):
        svc = self._make_service()
        valid_data = {
            "sections": [
                {
                    "scenario_name": "Login Flow",
                    "given": "User on login page",
                    "when": "User submits credentials",
                    "then": "User is logged in",
                    "items": [
                        {
                            "category": "功能驗證",
                            "summary": "Login succeeds with valid creds",
                            "detail": "Details here",
                            "conditions": [
                                {
                                    "condition_text": "Check redirect",
                                    "coverage_tag": "Happy Path",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        result = svc._validate_consolidation_json(valid_data)
        assert result is None  # None = no error

    def test_validate_consolidation_json_missing_sections(self):
        svc = self._make_service()
        result = svc._validate_consolidation_json({})
        assert result is not None
        assert "sections" in result.lower()

    def test_validate_consolidation_json_empty_sections(self):
        svc = self._make_service()
        result = svc._validate_consolidation_json({"sections": []})
        # Empty sections list is valid (no items to validate), or may return None
        # The validation only checks type; empty list passes iteration
        assert result is None

    def test_transform_inspection_to_sections_payload(self):
        svc = self._make_service()
        consolidation_data = {
            "sections": [
                {
                    "scenario_name": "Login Flow",
                    "given": "User on login page",
                    "when": "User submits credentials",
                    "then": "User is logged in",
                    "items": [
                        {
                            "category": "功能驗證",
                            "summary": "Login succeeds",
                            "detail": "Enter valid creds and click login",
                            "conditions": [
                                {
                                    "condition_text": "Redirect to dashboard",
                                    "coverage_tag": "Happy Path",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        result = svc._transform_inspection_to_sections_payload(consolidation_data)
        assert isinstance(result, list)
        assert len(result) == 1
        section = result[0]
        assert "section_title" in section
        assert "verification_items" in section
        assert len(section["verification_items"]) == 1
        item = section["verification_items"][0]
        assert "check_conditions" in item
        assert len(item["check_conditions"]) == 1


# ── Task 10.5 — SSE endpoint format ───────────────────────────────


class TestMagiInspectionSSEEndpoint:
    """Test that the SSE endpoint is registered on the router."""

    def test_council_inspection_endpoint_exists(self):
        from app.api.qa_ai_helper import router

        routes = [r.path for r in router.routes if hasattr(r, "path")]
        matching = [r for r in routes if "council-inspection" in r]
        assert len(matching) >= 1, f"Expected council-inspection route, got: {routes}"


# ── Task 10.6 — Session screen enum ───────────────────────────────


class TestSessionScreenEnum:
    """Test that COUNCIL_INSPECTION is in the screen enum."""

    def test_council_inspection_screen_exists(self):
        from app.models.qa_ai_helper import QAAIHelperSessionScreen

        assert hasattr(QAAIHelperSessionScreen, "COUNCIL_INSPECTION")
        assert QAAIHelperSessionScreen.COUNCIL_INSPECTION.value == "council_inspection"
