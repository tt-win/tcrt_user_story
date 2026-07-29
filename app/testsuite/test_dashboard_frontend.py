"""Frontend safety contracts for the role-aware dashboard client."""

from __future__ import annotations

import subprocess
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_client_keeps_preference_and_workspace_context_separate() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    save_preference = source.split("function savePreferredTeam", 1)[1].split(
        "function preferredTeamFrom", 1
    )[0]

    assert "tcrt:dashboard:preferred-team:${userId}" in source
    assert "setCurrentTeam" not in save_preference
    assert "function navigateWithTeam" in source
    assert "window.AppUtils.setCurrentTeam" in source
    assert "event.persisted" in source
    assert "requestId !== state.requestId" in source
    auth_ready = source.split("document.addEventListener('authReady'", 1)[1].split(
        "document.addEventListener('tokenRefreshed'", 1
    )[0]
    assert "state.requestId += 1" in auth_ready
    assert "clearDashboard()" in auth_ready
    storage_handler = source.split("window.addEventListener('storage'", 1)[1].split(
        "document.addEventListener('languageChanged'", 1
    )[0]
    assert "event.key !== 'access_token' && event.key !== 'token_expiry'" in storage_handler
    assert "state.requestId += 1" in storage_handler
    assert "hasStoredAuthSession()" in storage_handler
    assert "window.localStorage.getItem('token_expiry')" in source


def test_dashboard_client_uses_first_visit_preference_modal_and_single_team_entry() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    template = (_ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    stylesheet = (_ROOT / "app" / "static" / "css" / "index.css").read_text(
        encoding="utf-8"
    )

    assert 'id="dashboard-preference-modal"' in template
    assert 'role="radiogroup"' in template
    assert "openPreferredTeamModal(items, true)" in source
    assert "const preferredTeam = preferredTeamFrom(items);" in source
    assert "ordered.teams.forEach" not in source
    assert "state.preferredTeam = { userId, teamId };" in source
    assert "renderResume(main, sections.resume);" in source
    assert "renderActivity(side, sections.activity);" in source
    assert "dashboard-preference-options')?.replaceChildren()" in source
    assert "dashboard-activity-modal-list')?.replaceChildren()" in source
    assert "!modalElement?.classList.contains('show')" in source
    teams_renderer = source.split("function renderTeams", 1)[1].split(
        "function renderResume", 1
    )[0]
    assert "dashboard.openTeam" not in teams_renderer
    assert "dashboard-preferred-team-card" in teams_renderer
    assert "dashboard-preferred-team-value" in teams_renderer
    assert "dashboard-team-entry-preferred" not in teams_renderer
    assert ".dashboard-compact-card-body {" in stylesheet
    assert ".dashboard-preferred-team-value {" in stylesheet
    assert ".dashboard-team-entry-preferred" not in stylesheet


def test_dashboard_resume_renders_safe_cross_feature_work_with_cohesive_layout() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    stylesheet = (_ROOT / "app" / "static" / "css" / "index.css").read_text(
        encoding="utf-8"
    )
    renderer = source.split("function renderResume", 1)[1].split(
        "function renderAssigned", 1
    )[0]

    assert "dashboard-resume-run" in renderer
    assert "dashboard-resume-run-mark" in renderer
    assert "dashboard-resume-run-name" in renderer
    assert "dashboard-resume-run-kind" in renderer
    assert "dashboard-resume-run-meta" in renderer
    assert "test_run" in renderer
    assert "test_case" in renderer
    assert "user_story_map" in renderer
    assert "automation_hub" in renderer
    assert "item.run?.name" in renderer
    assert "item.resource?.id" in renderer
    assert "item.team.name" in renderer
    assert "item.last_activity_at" in renderer
    assert "navigateWithTeam(item.team, item.link)" in renderer
    assert "dashboard.returnToRun" in renderer
    assert "item.test_result" not in renderer
    assert "item.test_run_set" not in renderer
    assert "item.set_link" not in renderer
    assert ".dashboard-resume-run {" in stylesheet
    assert "min-height: 2.75rem;" in stylesheet
    assert "grid-template-columns: 1.5rem minmax(0, 1fr) 14rem;" in stylesheet
    assert "grid-template-columns: 7rem minmax(0, 1fr) 5rem 9.5rem;" in stylesheet
    assert "display: contents;" in stylesheet
    assert "width: 14rem;" in stylesheet
    assert ".dashboard-resume-run-action-label {" in stylesheet
    assert "border-bottom: 1px solid var(--tr-border-light);" in stylesheet
    assert "dashboard-resume-run-action-label" in renderer
    assert "lastWorked.append(document.createTextNode(lastWorkedAt))" in renderer
    assert ".dashboard-resume-run-action {" in stylesheet


def test_dashboard_client_limits_visible_activity_and_uses_bounded_modal() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    template = (_ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    stylesheet = (_ROOT / "app" / "static" / "css" / "index.css").read_text(
        encoding="utf-8"
    )
    activity_styles = stylesheet.split(
        ".dashboard-activity-detail-table-wrap", 1
    )[1].split(".dashboard-assigned-runs", 1)[0]

    assert "const MAX_VISIBLE_ACTIVITY_ITEMS = 5;" in source
    assert "items.slice(0, MAX_VISIBLE_ACTIVITY_ITEMS)" in source
    assert "openActivityModal(items)" in source
    assert "function activitySummaryEntry(item)" in source
    assert "function activityDetailEntry(item)" in source
    summary = source.split("function activitySummaryEntry", 1)[1].split(
        "function activityDetailEntry", 1
    )[0]
    detail = source.split("function activityDetailEntry", 1)[1].split(
        "function openActivityModal", 1
    )[0]
    assert "item.run" not in summary
    assert "item.test_case" not in summary
    assert "item.team" not in summary
    assert "item.run?.name" in detail
    assert "item.test_case?.number" in detail
    assert "item.team?.name" in detail
    assert "bindTeamAnchor(openLink, item.team, item.run_link)" in detail
    assert "element('tr', 'dashboard-activity-detail-entry')" in detail
    assert "dashboard-activity-detail-context" in detail
    assert "dashboard-activity-detail-test-case" in detail
    assert "openLink.setAttribute('aria-label', actionLabel)" in detail
    assert "activityDetailField" not in source
    assert "items.length > MAX_VISIBLE_ACTIVITY_ITEMS" not in source
    assert 'id="dashboard-activity-modal"' in template
    assert 'class="dashboard-activity-detail-list"' in template
    assert "table table-sm table-hover align-middle mb-0" in template
    assert 'class="sticky-top"' in template
    assert "modal-xl modal-fullscreen-lg-down modal-dialog-scrollable" in template
    assert "padding: 0.375rem 0.5rem !important;" in activity_styles
    assert "dashboard-activity-detail-field" not in activity_styles
    assert "grid-template-columns: repeat(3" not in activity_styles


def test_dashboard_uses_fixed_workspace_with_internal_section_scrolling() -> None:
    template = (_ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    base = (_ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    stylesheet = (_ROOT / "app" / "static" / "css" / "index.css").read_text(
        encoding="utf-8"
    )

    assert '{% set body_class = "dashboard-page" %}' in template
    assert "{% if body_class %} {{ body_class }}{% endif %}" in base
    assert "body.dashboard-page .app-main" in stylesheet
    assert "height: 100vh;" in stylesheet
    assert "#dashboard-content" in stylesheet
    assert "grid-template-rows: auto minmax(0, 1fr);" in stylesheet
    assert ".dashboard-column > .card > .card-body" in stylesheet
    assert "overflow-y: auto;" in stylesheet
    assert "dashboard-main-column" in source
    assert "dashboard-side-column" in source


def test_dashboard_greeting_prefers_lark_name_then_tcrt_username() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")

    assert "function preferredDisplayName(authUser, dashboardUser)" in source
    assert "authUser?.lark_name, authUser?.username, dashboardUser?.display_name" in source
    assert "dashboard.current_user.display_name = preferredDisplayName" in source


def test_dashboard_quick_actions_use_compact_responsive_layout() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    service = (_ROOT / "app" / "services" / "dashboard_service.py").read_text(
        encoding="utf-8"
    )
    stylesheet = (_ROOT / "app" / "static" / "css" / "index.css").read_text(
        encoding="utf-8"
    )

    compact_styles = stylesheet.split(".dashboard-quick-actions-compact", 1)[1].split(
        ".dashboard-preference-options", 1
    )[0]

    assert "display: flex;" in compact_styles
    assert "overflow: hidden;" in compact_styles
    assert "width: 100%;" in compact_styles
    assert "min-height: 2.25rem" in compact_styles
    assert "width: auto;" in compact_styles
    assert "height: 2.25rem;" in compact_styles
    assert "flex: 1 1 0;" in compact_styles
    assert "dashboard-quick-action-label" in source
    assert "if (!compact)" in source
    assert "actionButton.setAttribute('aria-label', actionLabel)" in source
    assert "actionButton.title = actionLabel" in source
    assert "action.href.includes('{team_id}')" in source
    assert "action.href.replace('{team_id}', encodeURIComponent(String(preferredTeam.id)))" in source
    assert "navigateWithTeam(preferredTeam, actionHref)" in source
    assert "actionButton.disabled = requiresTeamPath && !preferredTeam" in source
    assert (
        "renderQuickActions(side, state.dashboard.quick_actions || [], preferredTeam, true)"
        in source
    )
    assert 'key="dashboard.quickAction.automationHub"' in service
    assert 'href="/automation-hub"' in service
    assert 'key="dashboard.quickAction.userStoryMap"' in service
    assert 'href="/user-story-map/{team_id}"' in service


def test_dashboard_quick_action_hover_does_not_move_outside_compact_rail() -> None:
    stylesheet = (_ROOT / "app" / "static" / "css" / "index.css").read_text(
        encoding="utf-8"
    )
    action_styles = stylesheet.split(".dashboard-quick-action {", 1)[1].split(
        ".dashboard-quick-action-icon", 1
    )[0]

    assert "translateY" not in action_styles
    assert "padding: 0.125rem;" in stylesheet


def test_system_dashboard_uses_compact_aligned_workspace_components() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    stylesheet = (_ROOT / "app" / "static" / "css" / "index.css").read_text(
        encoding="utf-8"
    )
    renderer = source.split("function systemMetric", 1)[1].split(
        "function renderDashboard", 1
    )[0]

    assert "dashboard-system-overview-card" in renderer
    assert "dashboard-system-metrics" in renderer
    assert "dashboard-system-metric" in renderer
    assert "card dashboard-metric-card" not in renderer
    assert "dashboard-metric-grid" not in renderer
    assert (
        "table table-sm table-hover align-middle mb-0 "
        "dashboard-system-service-table"
    ) in renderer
    assert "element('thead', 'sticky-top')" in renderer
    assert "dashboard-system-service-table-wrap" in renderer
    assert "function appendSystemHealthGroup" in source
    assert "const stateNotice = sectionState(section)" in renderer
    assert "function renderSystemProviders" not in source
    assert "function renderSystemAttention" not in source
    assert "renderSystemHealth(side, sections.providers, sections.attention)" in renderer
    assert (
        "renderQuickActions(side, state.dashboard.quick_actions || [], null, true)"
        in renderer
    )
    assert (
        ".dashboard-system-main-column {\n"
        "    grid-template-rows: auto minmax(0, 1fr);"
    ) in stylesheet
    assert (
        ".dashboard-system-side-column {\n"
        "    grid-template-rows: auto minmax(0, 1fr);"
    ) in stylesheet
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in stylesheet
    assert ".dashboard-system-service-table-wrap {" in stylesheet
    assert ".dashboard-system-health-group {" in stylesheet


def test_system_dashboard_labels_exist_in_all_locales() -> None:
    for locale in ("en-US", "zh-CN", "zh-TW"):
        messages = (
            _ROOT / "app" / "static" / "locales" / f"{locale}.json"
        ).read_text(encoding="utf-8")
        for key in (
            "systemHealth",
            "service",
            "lastRun",
            "serviceState",
            "serviceResult",
        ):
            assert f'"{key}":' in messages


def test_dashboard_outcomes_use_accessible_svg_pie_chart_with_text_legend() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    stylesheet = (_ROOT / "app" / "static" / "css" / "index.css").read_text(
        encoding="utf-8"
    )
    renderer = source.split("function renderOutcomes", 1)[1].split(
        "function renderQuickActions", 1
    )[0]

    assert "svgElement('svg', 'dashboard-outcome-chart-svg')" in renderer
    assert "svg.setAttribute('role', 'img')" in renderer
    assert "svg.setAttribute('aria-label', summaryText)" in renderer
    assert "setOutcomeCircleGeometry(segment)" in renderer
    assert "segment.setAttribute('stroke-dasharray'" in renderer
    assert "dashboard-outcome-chart-center" in renderer
    assert "dashboard-outcome-legend" in renderer
    assert "dashboard-outcome-legend-label" in renderer
    assert "dashboard-outcome-legend-count" in renderer
    assert "dashboard-outcome-card-body-has-state" in renderer
    assert "dashboard-outcome-track" not in renderer
    assert "dashboard-outcome-fill" not in renderer
    assert ".dashboard-outcome-chart-svg {" in stylesheet
    assert ".dashboard-outcome-legend {" in stylesheet
    assert "grid-template-rows: auto minmax(0, 1fr);" in stylesheet
    assert "grid-template-rows: auto auto minmax(0, 1fr);" in stylesheet
    assert "height: min(100%, 11rem);" in stylesheet
    assert "max-height: 6.5rem;" in stylesheet
    assert "aspect-ratio: 1;" in stylesheet
    assert "repeat(auto-fit, minmax(8.5rem, 1fr))" in stylesheet
    assert "stroke: var(--tr-success);" in stylesheet
    assert ".dashboard-outcome-track" not in stylesheet
    assert ".dashboard-outcome-fill" not in stylesheet


def test_dashboard_assigned_runs_use_expandable_bounded_previews() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    stylesheet = (_ROOT / "app" / "static" / "css" / "index.css").read_text(
        encoding="utf-8"
    )
    renderer = source.split("function renderAssigned", 1)[1].split(
        "function activityLabel", 1
    )[0]

    assert "dashboard-assigned-runs" in renderer
    assert "element('details', 'dashboard-assigned-run')" in renderer
    assert "dashboard-assigned-run-summary" in renderer
    assert "dashboard-assigned-run-preview" in renderer
    assert "dashboard-assigned-preview-link" in renderer
    assert "item.item_count" in renderer
    assert "item.preview_items" in renderer
    assert "previewItem.test_case?.number" in renderer
    assert "bindTeamAnchor(openRun, item.team, item.run_link)" in renderer
    assert "item.updated_at" not in renderer
    assert "item.test_run_set" not in renderer
    assert "common.actions" not in renderer
    assert "dashboard.column.updated" not in renderer
    assert ".dashboard-assigned-run-summary {" in stylesheet
    assert ".dashboard-assigned-run-preview {" in stylesheet
    assert "min-height: 2.25rem" in stylesheet
    assert ".dashboard-assigned-run-link" not in stylesheet
    assert ".dashboard-action-cell" not in stylesheet


def test_personal_dashboard_does_not_render_audit_summary_card() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")

    assert "function renderAudit" not in source
    assert "renderAudit(side, sections.audit)" not in source
    assert "dashboard.auditFallback" not in source


def test_dashboard_client_uses_safe_dom_apis_and_role_specific_heading() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")

    assert "innerHTML" not in source
    assert "textContent" in source
    assert "dashboard-page-title" in source
    assert "system_administration" in source
    assert "cache: 'no-store'" in source


def test_dashboard_client_normalizes_the_existing_auth_me_user_id_contract() -> None:
    source = (_ROOT / "app" / "static" / "js" / "index.js").read_text(encoding="utf-8")
    auth_api = (_ROOT / "app" / "api" / "auth.py").read_text(encoding="utf-8")

    assert "user_id: int" in auth_api
    assert "function normalizeAuthUser(user)" in source
    assert "const userId = user.id ?? user.user_id" in source
    assert "const user = normalizeAuthUser(await window.AuthClient?.getUserInfo?.());" in source
    assert "state.currentUser = normalizeAuthUser(event.detail);" in source
    assert "if (token) showError();" in source


def test_local_assignee_selector_refreshes_eligible_users_without_persistent_cache() -> None:
    source = (_ROOT / "app" / "static" / "js" / "assignee-selector.js").read_text(
        encoding="utf-8"
    )

    assert "includeLocalUsers" in source
    assert "/test-run-assignees/?" in source
    assert "const canReuseCachedResult = !this.options.includeLocalUsers" in source
    assert "Promise.allSettled" in source


def test_test_run_assignment_ui_preserves_machine_readable_identity() -> None:
    render_source = (
        _ROOT / "app" / "static" / "js" / "test-run-execution" / "render.js"
    ).read_text(encoding="utf-8")
    init_source = (
        _ROOT / "app" / "static" / "js" / "test-run-execution" / "init.js"
    ).read_text(encoding="utf-8")
    builder = render_source.split("function buildAssigneeUpdate", 1)[1].split(
        "async function updateAssignee", 1
    )[0]
    batch_update = render_source.split("async function batchModifyItems", 1)[1].split(
        "function showBatchDeleteConfirm", 1
    )[0]

    assert "return { assignee_user_id: localUserId };" in builder
    assert "return { assignee: structuredAssignee };" in builder
    assert "selection.id" in builder
    assert "selection.email" in builder
    assert "String(selection.email).trim().toLowerCase()" in builder
    assert "if (larkId) structuredAssignee.id = larkId;" in builder
    assert "else if (email) structuredAssignee.email = email;" in builder
    assert builder.count("structuredAssignee.email = email;") == 1
    assert "getSelectedContact()" in render_source
    assert "Object.assign(updateData, assigneeUpdate);" in batch_update
    assert "updateData.assignee_name = modifications.assigneeName" not in batch_update
    batch_selector = init_source.split("const batchInput", 1)[1].split(
        "batchInput._assigneeSelector =", 1
    )[0]
    assert "includeLocalUsers: true" in batch_selector


def test_test_run_assignment_runtime_contract() -> None:
    result = subprocess.run(
        ["node", "--test", "app/testsuite/js/test-run-assignment.test.mjs"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
