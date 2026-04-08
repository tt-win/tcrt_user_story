from pathlib import Path


def test_team_statistics_template_no_longer_exposes_helper_tab_or_sections():
    html = Path("app/templates/team_statistics.html").read_text(encoding="utf-8")

    forbidden_markers = [
        'id="helper-ai-tab"',
        'data-bs-target="#helper-ai-pane"',
        'id="helper-ai-pane"',
        'id="helper-ai-progress-tbody"',
        'id="helper-ai-team-usage-tbody"',
        'id="helper-ai-cost-total"',
        'id="helper-ai-token-total"',
        'id="helper-ai-stage-metrics-tbody"',
        'id="helper-ai-coverage-hint"',
        'data-i18n="teamStats.tabs.helperAi"',
    ]
    for marker in forbidden_markers:
        assert marker not in html


def test_team_statistics_js_no_longer_loads_helper_analytics_pipeline():
    script = Path("app/static/js/team_statistics.js").read_text(encoding="utf-8")

    forbidden_markers = [
        "loadHelperAiAnalytics()",
        "helper_ai_analytics",
        "renderHelperProgressRows",
        "renderHelperTeamUsageRows",
        "renderHelperCostSummary",
        "renderHelperStageMetricsRows",
        "renderHelperCoverageHint",
        "renderHelperErrorState",
        "helperPhaseBadgeClass",
        "helperStatusBadgeClass",
        "helperTokenTypeLabel",
        "TEAM_STATS_HELPER_TRANSLATION_PATCH",
        "ensureHelperAiTranslationPatch()",
    ]
    for marker in forbidden_markers:
        assert marker not in script

    assert "loadAllStatistics()" in script
    assert "loadOverview()" in script
    assert "loadAuditAnalysis()" in script


def test_i18n_language_detection_handles_safari_chinese_variants():
    script = Path("app/static/js/i18n.js").read_text(encoding="utf-8").lower()

    for marker in ["navigator.languages", "zh-hant", "zh-hans", "zh-tw", "zh-cn"]:
        assert marker in script, (
            f"app/static/js/i18n.js missing Safari locale handling marker: {marker}"
        )

