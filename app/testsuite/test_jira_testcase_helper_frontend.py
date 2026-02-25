from pathlib import Path


def test_helper_entrypoint_is_on_set_list_page():
    management_html = Path("app/templates/test_case_management.html").read_text(
        encoding="utf-8"
    )
    set_list_html = Path("app/templates/test_case_set_list.html").read_text(
        encoding="utf-8"
    )
    helper_modal_partial_html = Path(
        "app/templates/_partials/ai_test_case_helper_modal.html"
    ).read_text(encoding="utf-8")

    assert 'id="openAiHelperFromSetListBtn"' in set_list_html
    assert 'data-i18n="aiHelper.entryButton"' in set_list_html
    assert "_partials/ai_test_case_helper_modal.html" in set_list_html
    assert 'id="aiTestCaseHelperModal"' in helper_modal_partial_html
    assert 'data-i18n="aiHelper.step.requirement"' not in helper_modal_partial_html
    assert 'id="helperAnalyzeBtn"' not in helper_modal_partial_html
    assert 'id="helperRequirementEditor"' not in helper_modal_partial_html
    assert 'id="helperStartOverBtn"' in helper_modal_partial_html
    assert 'id="helperConfirmModal"' in helper_modal_partial_html
    assert 'id="helperConfirmOkBtn"' in helper_modal_partial_html
    assert 'id="helperConfirmCancelBtn"' in helper_modal_partial_html
    assert 'id="helperErrorBox"' not in helper_modal_partial_html
    assert 'id="helperSuccessBox"' not in helper_modal_partial_html
    footer_index = helper_modal_partial_html.find('<div class="modal-footer tc-helper-footer">')
    start_over_index = helper_modal_partial_html.find('id="helperStartOverBtn"')
    assert footer_index >= 0 and start_over_index > footer_index
    assert 'data-i18n="aiHelper.phaseRequirement"' not in helper_modal_partial_html
    assert 'data-i18n="aiHelper.phaseAnalysis"' not in helper_modal_partial_html
    assert 'data-i18n="aiHelper.phasePretestcase"' not in helper_modal_partial_html
    assert 'data-i18n="aiHelper.phaseTestcase"' not in helper_modal_partial_html
    assert 'data-i18n="aiHelper.phaseCommit"' not in helper_modal_partial_html
    assert 'data-helper-step="3"' in helper_modal_partial_html
    assert 'data-helper-step="4"' not in helper_modal_partial_html
    assert 'id="helperPreSectionList"' in helper_modal_partial_html
    assert 'id="helperPreEntryList"' in helper_modal_partial_html
    assert 'id="helperPreDetailForm"' in helper_modal_partial_html
    assert 'id="helperPreRequirementSummary"' in helper_modal_partial_html
    assert 'id="helperPreRequirementContent"' in helper_modal_partial_html
    assert 'id="helperPreSpecRequirements"' in helper_modal_partial_html
    assert 'id="helperPreVerificationPoints"' in helper_modal_partial_html
    assert 'id="helperPreExpectedOutcomes"' in helper_modal_partial_html
    assert 'id="helperPreTraceMeta"' in helper_modal_partial_html
    assert '<option value="permission">' not in helper_modal_partial_html
    assert '<option value="error">' not in helper_modal_partial_html
    assert 'id="helperFinalSectionList"' in helper_modal_partial_html
    assert 'id="helperFinalCaseList"' in helper_modal_partial_html
    assert 'id="helperFinalDetailForm"' in helper_modal_partial_html
    assert '/static/js/test-case-management/ai-helper.js' in set_list_html
    assert 'id="aiTestCaseHelperBtn"' not in management_html
    assert "_partials/ai_test_case_helper_modal.html" in management_html
    assert "window.__TCM_HELPER_MODE__" in management_html
    assert '/static/js/test-case-management/ai-helper.js' in management_html
    assert '/static/js/test-case-management/section-list-init.js' not in management_html


def test_helper_frontend_uses_phase_api_endpoints_and_redirect_highlight():
    script = Path("app/static/js/test-case-management/ai-helper.js").read_text(encoding="utf-8")
    set_list_script = Path("app/static/js/test-case-set-list/main.js").read_text(
        encoding="utf-8"
    )
    set_integration_script = Path("app/static/js/test-case-set-integration.js").read_text(
        encoding="utf-8"
    )

    assert '/test-case-helper/sessions' in script
    assert '/sessions/${helperState.sessionId}/ticket' in script
    assert '/normalize' not in script
    assert '/analyze' in script
    assert "override_incomplete_requirement" in script
    assert '/generate' in script
    assert '/commit' in script
    assert 'helper_created' in script
    assert "params.get('helper')" in script
    assert "helperLoadTeamFromLocalStorage" in script
    assert "helperResolveTeam(requestedTeamId)" in script
    assert "helperSetStep(2);" in script
    assert "helperSetStep(3);" in script
    assert "const STEP_COUNT = 3;" in script
    assert "function helperRenderPreSectionList()" in script
    assert "function helperRenderFinalSectionList()" in script
    assert "function helperFormatSectionLabel(" in script
    assert "helperFormatSectionLabel(section.sn, name)" in script
    assert "helperSyncSelectedPreEntryFromDetail" in script
    assert "helperSyncSelectedFinalCaseFromDetail" in script
    assert "data-helper-pre-section" in script
    assert "data-helper-final-section" in script
    assert "helperStartOverBtn" in script
    assert "helperStartOver(" in script
    assert "helperFallbackMarkdown" in script
    assert "helperNormalizeEscapedMarkdownForRender" in script
    assert "replace(/\\\\\\*\\\\\\*([^\\n]+?)\\\\\\*\\\\\\*/g, '**$1**')" in script
    assert "typeof marked === 'function'" in script
    assert ".replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')" in script
    assert "function helperNotify(message, level)" in script
    assert "async function helperConfirm(message, options = {})" in script
    assert "requires_override" in script
    assert "proceedAnyway" in script
    assert "goBackAndFix" in script
    assert "AppUtils[methodName](content);" in script
    assert "window.confirm(" not in script
    assert "alert(" not in script
    assert "sessionRestored" in script
    assert "startOverDone" in script
    assert "window.AiTestCaseHelper.openModal({ teamId })" in set_list_script
    assert "openModal({ teamId })" in set_list_script
    assert "params.set('helper', '1')" not in set_list_script
    assert "sessionStorage.removeItem('selectedTestCaseSetId')" in set_list_script
    assert "window.__TCM_HELPER_MODE__" in set_integration_script
    assert "this.getUrlParam('helper')" in set_integration_script
    assert "helperMode" in set_integration_script


def test_helper_i18n_keys_exist_in_all_locales():
    locale_files = [
        Path("app/static/locales/zh-TW.json"),
        Path("app/static/locales/zh-CN.json"),
        Path("app/static/locales/en-US.json"),
    ]

    required_markers = [
        '"aiHelper"',
        '"entryButton"',
        '"normalizeAction"',
        '"generateAction"',
        '"commitAction"',
        '"createdHighlightNotice"',
        '"startOver"',
        '"startOverConfirm"',
        '"startOverDone"',
        '"startOverFailed"',
        '"loadingReset"',
        '"sectionListTitle"',
        '"entryListTitle"',
        '"testcaseListTitle"',
        '"preDetailEmpty"',
        '"finalDetailEmpty"',
        '"reqMappingTitle"',
        '"reqMappingEmpty"',
        '"requirementSummaryTitle"',
        '"requirementContentTitle"',
        '"specRequirementsTitle"',
        '"verificationPointsTitle"',
        '"expectedOutcomesTitle"',
        '"traceMetaTitle"',
        '"proceedAnyway"',
        '"goBackAndFix"',
        '"requirementIncompleteWarningDialogTitle"',
        '"phaseAnalysis"',
        '"phasePretestcase"',
        '"phaseTestcase"',
        '"phaseCommit"',
    ]

    for file_path in locale_files:
        content = file_path.read_text(encoding="utf-8")
        for marker in required_markers:
            assert marker in content, f"{file_path} missing marker: {marker}"


def test_helper_markdown_table_style_has_visible_border():
    helper_modal_css = Path("app/static/css/test-case-helper-modal.css").read_text(
        encoding="utf-8"
    )
    management_css = Path("app/static/css/test-case-management.css").read_text(
        encoding="utf-8"
    )

    required_css_markers = [
        "#aiTestCaseHelperModal .tc-helper-preview table",
        "#aiTestCaseHelperModal .tc-helper-case-preview table",
        "#aiTestCaseHelperModal .tc-helper-preview th",
        "#aiTestCaseHelperModal .tc-helper-preview td",
        "border: 1px solid #c7d5ea",
        "position: sticky;",
        "background: #f5f8fd;",
        "overflow: hidden;",
        "grid-template-columns: repeat(3, minmax(0, 1fr));",
        ".tc-helper-split",
        "grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);",
        ".tc-helper-list",
        ".tc-helper-split-right",
    ]

    for marker in required_css_markers:
        assert marker in helper_modal_css, (
            f"app/static/css/test-case-helper-modal.css missing marker: {marker}"
        )
        assert marker in management_css, (
            f"app/static/css/test-case-management.css missing marker: {marker}"
        )
