from pathlib import Path
import json


def test_team_statistics_template_contains_helper_tab_and_sections():
    html = Path("app/templates/team_statistics.html").read_text(encoding="utf-8")

    assert 'id="helper-ai-tab"' in html
    assert 'data-bs-target="#helper-ai-pane"' in html
    assert 'id="helper-ai-pane"' in html
    assert 'id="helper-ai-progress-tbody"' in html
    assert 'id="helper-ai-team-usage-tbody"' in html
    assert 'id="helper-ai-cost-total"' in html
    assert 'id="helper-ai-token-total"' in html
    assert 'id="helper-ai-pricing-version"' in html
    assert 'id="helper-ai-cost-breakdown-tbody"' in html
    assert 'id="helper-ai-stage-metrics-tbody"' in html
    assert 'id="helper-ai-coverage-hint"' in html
    assert 'data-i18n="teamStats.tabs.helperAi"' in html
    assert 'data-i18n="teamStats.helper.estimateDisclaimer"' in html


def test_team_statistics_js_contains_helper_analytics_pipeline_and_states():
    script = Path("app/static/js/team_statistics.js").read_text(encoding="utf-8")

    required_markers = [
        "loadHelperAiAnalytics()",
        "helper_ai_analytics",
        "renderHelperProgressRows",
        "renderHelperTeamUsageRows",
        "renderHelperCostSummary",
        "renderHelperStageMetricsRows",
        "renderHelperCoverageHint",
        "renderHelperErrorState",
        "teamStats.helper.noProgressData",
        "teamStats.helper.noTeamUsageData",
        "teamStats.helper.noTokenData",
        "teamStats.helper.noStageData",
        "teamStats.helper.loadFailed",
        "helperPhaseBadgeClass",
        "helperStatusBadgeClass",
        "helperTokenTypeLabel",
        "includeTeamFilter: true",
        "function formatUsd(value)",
        "function formatDurationMs(value)",
        "window.i18n.retranslate(pane)",
        "window.i18n.retranslate(tabElement)",
        "TEAM_STATS_HELPER_TRANSLATION_PATCH",
        "ensureHelperAiTranslationPatch()",
        "localStorage.setItem(`i18n_${language}_cache`",
    ]

    for marker in required_markers:
        assert marker in script, f"app/static/js/team_statistics.js missing marker: {marker}"


def test_team_statistics_helper_i18n_keys_exist_in_all_locales():
    locale_files = [
        Path("app/static/locales/zh-TW.json"),
        Path("app/static/locales/zh-CN.json"),
        Path("app/static/locales/en-US.json"),
    ]

    required_helper_keys = [
        "progressTitle",
        "teamUsageTitle",
        "costTitle",
        "sessions",
        "usersCount",
        "ticketsCount",
        "activeSessions",
        "completedSessions",
        "failedSessions",
        "estimateDisclaimer",
        "noProgressData",
        "noTeamUsageData",
        "noTokenData",
        "noStageData",
        "coveragePartial",
        "coverageComplete",
        "loadFailed",
        "tokenTypeInput",
        "tokenTypeOutput",
        "tokenTypeCacheRead",
        "tokenTypeCacheWrite",
        "tokenTypeInputAudio",
        "tokenTypeInputAudioCache",
    ]

    for file_path in locale_files:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        team_stats = payload.get("teamStats", {})
        assert team_stats.get("tabs", {}).get("helperAi"), f"{file_path} missing teamStats.tabs.helperAi"
        helper_section = team_stats.get("helper", {})
        for key in required_helper_keys:
            assert helper_section.get(key), f"{file_path} missing teamStats.helper.{key}"


def test_team_statistics_helper_locales_are_localized_for_zh_variants():
    expected_values = {
        Path("app/static/locales/zh-TW.json"): {
            ("teamStats", "tabs", "helperAi"): "QA AI Agent - 測試案例助手",
            ("teamStats", "helper", "sessions"): "工作階段數",
            ("teamStats", "helper", "tokens"): "Token 數",
            ("teamStats", "helper", "tokenTypeInput"): "輸入",
            ("teamStats", "helper", "tokenTypeOutput"): "輸出",
        },
        Path("app/static/locales/zh-CN.json"): {
            ("teamStats", "tabs", "helperAi"): "QA AI Agent - 测试用例助手",
            ("teamStats", "helper", "sessions"): "会话数",
            ("teamStats", "helper", "tokens"): "Token 数",
            ("teamStats", "helper", "tokenTypeInput"): "输入",
            ("teamStats", "helper", "tokenTypeOutput"): "输出",
        },
    }

    for file_path, expectations in expected_values.items():
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        for path, expected in expectations.items():
            current = payload
            for key in path:
                current = current[key]
            assert current == expected, f"{file_path} expected {'.'.join(path)} to be {expected!r}, got {current!r}"


def test_i18n_language_detection_handles_safari_chinese_variants():
    script = Path("app/static/js/i18n.js").read_text(encoding="utf-8").lower()

    for marker in ["navigator.languages", "zh-hant", "zh-hans", "zh-tw", "zh-cn"]:
        assert marker in script, f"app/static/js/i18n.js missing Safari locale handling marker: {marker}"


def test_team_statistics_has_page_level_helper_translation_self_heal():
    script = Path("app/static/js/team_statistics.js").read_text(encoding="utf-8")

    required_markers = [
        "const TEAM_STATS_HELPER_TRANSLATION_PATCH = Object.freeze({",
        "'zh-TW': {",
        "'zh-CN': {",
        "function ensureHelperAiTranslationPatch()",
        "localStorage.setItem(`i18n_${language}_cache`, JSON.stringify(window.i18n.translations[language]));",
        "document.addEventListener('languageChanged', function() {",
        "window.addEventListener('pageshow', function() {",
    ]

    for marker in required_markers:
        assert marker in script, f"app/static/js/team_statistics.js missing self-heal marker: {marker}"
