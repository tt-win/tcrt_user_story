import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_rewritten_helper_entrypoints_replace_legacy_modal_in_templates():
    management_html = Path("app/templates/test_case_management.html").read_text(
        encoding="utf-8"
    )
    set_list_html = Path("app/templates/test_case_set_list.html").read_text(
        encoding="utf-8"
    )
    helper_page_html = Path("app/templates/qa_ai_helper.html").read_text(
        encoding="utf-8"
    )

    assert 'id="openQaAiHelperFromSetListBtn"' in set_list_html
    assert 'data-i18n="qaAiHelper.entryButton"' in set_list_html
    assert "_partials/ai_test_case_helper_modal.html" not in set_list_html
    assert "/static/js/test-case-management/ai-helper.js" not in set_list_html

    assert 'id="openQaAiHelperPageBtn"' in management_html
    assert 'href="/qa-ai-helper{% if set_id %}?set_id={{ set_id }}{% endif %}"' in management_html
    assert "_partials/ai_test_case_helper_modal.html" not in management_html
    assert "/static/js/test-case-management/ai-helper.js" not in management_html
    assert "window.__TCM_HELPER_MODE__" not in management_html

    assert 'id="qaAiHelperPage"' in helper_page_html
    assert "/static/css/qa-ai-helper.css" in helper_page_html
    assert "/static/js/qa-ai-helper/main.js" in helper_page_html
    assert 'id="qaHelperPhaseRail"' in helper_page_html
    assert 'data-phase-target="fetch"' in helper_page_html
    assert 'data-phase-target="canonical"' in helper_page_html
    assert 'data-phase-target="plan"' in helper_page_html
    assert 'data-phase-target="draft"' in helper_page_html
    assert 'data-phase-panel="fetch"' in helper_page_html
    assert 'data-phase-panel="canonical"' in helper_page_html
    assert 'data-phase-panel="plan"' in helper_page_html
    assert 'data-phase-panel="draft"' in helper_page_html
    assert 'id="qaHelperPlanTable"' in helper_page_html
    assert 'id="qaHelperDraftList"' in helper_page_html


def test_rewritten_helper_button_visible_when_config_enable_true():
    client = TestClient(app)
    original = settings.ai.qa_ai_helper.enable
    settings.ai.qa_ai_helper.enable = True
    try:
        resp = client.get("/test-case-sets")
        assert resp.status_code == 200
        assert 'id="openQaAiHelperFromSetListBtn"' in resp.text
    finally:
        settings.ai.qa_ai_helper.enable = original


def test_rewritten_helper_button_hidden_when_config_enable_false():
    client = TestClient(app)
    original = settings.ai.qa_ai_helper.enable
    settings.ai.qa_ai_helper.enable = False
    try:
        resp = client.get("/test-case-sets")
        assert resp.status_code == 200
        assert 'id="openQaAiHelperFromSetListBtn"' not in resp.text

        hidden_route = client.get("/qa-ai-helper", follow_redirects=False)
        assert hidden_route.status_code == 303
        assert hidden_route.headers["location"] == "/test-case-sets"
    finally:
        settings.ai.qa_ai_helper.enable = original


def test_rewritten_helper_frontend_redirects_to_dedicated_page():
    set_list_script = Path("app/static/js/test-case-set-list/main.js").read_text(
        encoding="utf-8"
    )
    helper_script = Path("app/static/js/qa-ai-helper/main.js").read_text(
        encoding="utf-8"
    )

    assert "openQaAiHelperFromSetListBtn" in set_list_script
    assert "window.location.href = `/qa-ai-helper?team_id=${encodeURIComponent(teamId)}`;" in set_list_script
    assert "AiTestCaseHelper.openModal" not in set_list_script

    required_markers = [
        "qaAiHelperPage",
        "qaHelperCreateSessionBtn",
        "qaHelperFetchTicketBtn",
        "qaHelperSaveCanonicalBtn",
        "qaHelperPlanBtn",
        "qaHelperApplyOverridesBtn",
        "qaHelperApplyDeltaBtn",
        "qaHelperPrevPhaseBtn",
        "qaHelperNextPhaseBtn",
        "qaHelperLockBtn",
        "qaHelperGenerateBtn",
        "qaHelperSaveDraftBtn",
        "qaHelperCommitBtn",
        "qaHelperDiscardDraftBtn",
        "/qa-ai-helper/sessions",
        "/planning-overrides",
        "/requirement-deltas",
        "/generate",
        "/discard",
        "/commit",
        "activePhaseView",
        "renderPhaseWorkflow",
    ]
    for marker in required_markers:
        assert marker in helper_script


def test_rewritten_helper_i18n_keys_exist_in_all_locales():
    locale_files = [
        Path("app/static/locales/zh-TW.json"),
        Path("app/static/locales/zh-CN.json"),
        Path("app/static/locales/en-US.json"),
    ]

    required_keys = [
        "pageTitle",
        "entryButton",
        "sessionCardTitle",
        "canonicalTitle",
        "planTitle",
        "draftTitle",
        "workflowTitle",
        "phaseFetch",
        "phaseCanonical",
        "phasePlan",
        "phaseDraft",
        "createSession",
        "fetchTicket",
        "planAction",
        "lockAction",
        "generateDrafts",
        "commitDrafts",
    ]

    for file_path in locale_files:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        qa_helper = payload.get("qaAiHelper", {})
        for key in required_keys:
            assert qa_helper.get(key), f"{file_path} missing qaAiHelper.{key}"


def test_rewritten_helper_styles_follow_dedicated_page_structure():
    css = Path("app/static/css/qa-ai-helper.css").read_text(encoding="utf-8")
    required_markers = [
        ".qa-helper-card",
        ".qa-helper-table-wrap",
        ".qa-helper-plan-table",
        ".qa-helper-draft-list",
        ".qa-helper-phase-rail",
        ".qa-helper-phase-step",
        ".qa-helper-phase-toolbar",
        ".qa-helper-pill",
        ".qa-helper-kv",
    ]
    for marker in required_markers:
        assert marker in css
