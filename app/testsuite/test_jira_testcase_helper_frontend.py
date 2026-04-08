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
    assert "新版 QA AI Helper" not in set_list_html
    assert "_partials/ai_test_case_helper_modal.html" not in set_list_html
    assert "/static/js/test-case-management/ai-helper.js" not in set_list_html

    assert 'id="openQaAiHelperPageBtn"' in management_html
    assert "新版 QA AI Helper" not in management_html
    assert (
        'href="/qa-ai-helper{% if set_id %}?set_id={{ set_id }}{% endif %}"'
        in management_html
    )
    assert "_partials/ai_test_case_helper_modal.html" not in management_html
    assert "/static/js/test-case-management/ai-helper.js" not in management_html
    assert "window.__TCM_HELPER_MODE__" not in management_html

    assert 'id="qaAiHelperPage"' in helper_page_html
    assert "/static/css/qa-ai-helper.css" in helper_page_html
    assert "/static/js/qa-ai-helper/main.js" in helper_page_html
    assert "QA AI Helper - TCRT" in helper_page_html
    assert 'id="qaHelperLoadTicketCard"' in helper_page_html
    assert 'id="qaHelperTicketConfirmationCard"' in helper_page_html
    assert 'id="qaHelperRequirementPlanCard"' in helper_page_html
    assert 'id="qaHelperSeedReviewCard"' in helper_page_html
    assert 'id="qaHelperTestcaseReviewCard"' in helper_page_html
    assert 'id="qaHelperSetSelectionCard"' in helper_page_html
    assert 'id="qaHelperCommitResultCard"' in helper_page_html
    assert 'id="qaHelperSessionManagerBtn"' in helper_page_html
    assert 'id="qaHelperSessionManagerModal"' in helper_page_html
    assert 'id="qaHelperSessionManagerList"' in helper_page_html
    assert 'id="qaHelperBackToTicketConfirmationBtn"' in helper_page_html
    assert 'id="qaHelperBackToRequirementPlanBtn"' in helper_page_html
    assert 'id="qaHelperBackToSeedReviewBtn"' in helper_page_html
    assert "qa-helper-step-card" in helper_page_html
    assert 'id="qaHelperPhaseRail"' not in helper_page_html
    assert 'id="qaHelperPlanTable"' not in helper_page_html
    assert 'id="qaHelperDraftList"' not in helper_page_html
    assert 'id="qaHelperCanonicalLanguage"' not in helper_page_html
    assert 'data-phase-target="fetch"' not in helper_page_html


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


def test_rewritten_helper_frontend_redirects_to_v3_page_and_workflow_markers():
    set_list_script = Path("app/static/js/test-case-set-list/main.js").read_text(
        encoding="utf-8"
    )
    helper_script = Path("app/static/js/qa-ai-helper/main.js").read_text(
        encoding="utf-8"
    )

    assert "openQaAiHelperFromSetListBtn" in set_list_script
    assert (
        "window.location.href = `/qa-ai-helper?team_id=${encodeURIComponent(teamId)}`;"
        in set_list_script
    )
    assert "AiTestCaseHelper.openModal" not in set_list_script

    required_markers = [
        "qaAiHelperPage",
        "qaHelperCreateSessionBtn",
        "qaHelperProceedVerificationBtn",
        "qaHelperSaveRequirementPlanBtn",
        "qaHelperLockRequirementPlanBtn",
        "qaHelperStartSeedReviewBtn",
        "qaHelperRefineSeedsBtn",
        "qaHelperLockSeedsBtn",
        "qaHelperStartTestcaseReviewBtn",
        "qaHelperSelectTargetSetBtn",
        "qaHelperCommitSelectedBtn",
        "qaHelperSessionManagerBtn",
        "qaHelperSessionManagerResumeBtn",
        "qaHelperSessionManagerDeleteSelectedBtn",
        "qaHelperSessionManagerClearBtn",
        "qaHelperBackToTicketConfirmationBtn",
        "qaHelperBackToRequirementPlanBtn",
        "qaHelperBackToSeedReviewBtn",
        "/qa-ai-helper/sessions",
        "/seed-sets",
        "/testcase-draft-sets",
        "/set-selection",
        "/commit",
        "window.bootstrap.Modal",
        "combineVerificationTargetAndCondition",
        "normalizeRequirementPlanForEditor",
        "qa-helper-goal-entry-top",
        "qa-helper-goal-entry-meta-top",
        "qa-helper-goal-entry-body-tight",
    ]
    for marker in required_markers:
        assert marker in helper_script
    assert "data-plan-add-condition-index" not in helper_script
    assert "data-plan-remove-condition-item" not in helper_script


def test_rewritten_helper_i18n_keys_exist_in_all_locales():
    locale_files = [
        Path("app/static/locales/zh-TW.json"),
        Path("app/static/locales/zh-CN.json"),
        Path("app/static/locales/en-US.json"),
    ]

    required_keys = [
        "pageTitle",
        "entryButton",
        "screen1Title",
        "screen2Title",
        "screen3Title",
        "screen4Title",
        "screen5Title",
        "screen6Title",
        "screen7Title",
        "loadTicketContent",
        "lockRequirementPlan",
        "startSeedGeneration",
        "lockSeeds",
        "startTestcaseGeneration",
        "commitSelectedTestcases",
        "sessionManager",
        "sessionManagerSummaryEmpty",
        "backToTicketConfirmation",
        "backToRequirementPlan",
        "backToSeedReview",
    ]

    for file_path in locale_files:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        qa_helper = payload.get("qaAiHelper", {})
        for key in required_keys:
            assert qa_helper.get(key), f"{file_path} missing qaAiHelper.{key}"
        assert qa_helper.get("pageTitle") == "QA AI Helper"
        assert qa_helper.get("entryButton") == "QA AI Helper"


def test_rewritten_helper_styles_follow_v3_workspace_structure():
    css = Path("app/static/css/qa-ai-helper.css").read_text(encoding="utf-8")
    required_markers = [
        ".qa-helper-step-card",
        ".qa-helper-markdown-card",
        ".qa-helper-section-rail",
        ".qa-helper-editor-shell",
        ".qa-helper-seed-list",
        ".qa-helper-action-bar",
        ".qa-helper-reference-card",
        ".qa-helper-item-section-head",
        ".qa-helper-item-section-action",
        ".qa-helper-session-manager-trigger",
        ".qa-helper-session-manager-list",
        ".qa-helper-session-manager-item",
    ]
    for marker in required_markers:
        assert marker in css
    assert ".qa-helper-step-card > .card-body" in css
