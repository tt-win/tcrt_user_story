"""Component specification tests for TCRT frontend (SPEC-BTN/BDG/TBL/MDL/CRD/TLB/TAB/DRP/HOM/NAV).

These tests render every page route via a stubbed-startup TestClient and assert the
rendered HTML conforms to the mandatory component specifications in AGENTS.md /
openspec/specs/ui-design-system.

Phase 0 establishes the scaffold and an xfail baseline. Each subsequent refactor
phase removes the xfail marks for the SPEC it satisfies. Phase 16 confirms zero
xfail remains.

The SPECs verified here mirror the table in AGENTS.md "前端測試需求".
"""

from __future__ import annotations


import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient



# --------------------------------------------------------------------------- #
# Test infrastructure
# --------------------------------------------------------------------------- #

# (page_name, route) for every content page. Routes that need a path param use
# a synthetic id (1) which the page handlers accept without DB access.
PAGE_ROUTES: list[tuple[str, str]] = [
    ("index", "/"),
    ("team_management", "/team-management"),
    ("organization_management", "/organization-management"),
    ("automation_provider_settings", "/automation-provider-settings"),
    ("automation_webhook_config", "/automation-webhook-config"),
    ("automation_hub", "/automation-hub"),
    ("audit_logs", "/audit-logs"),
    ("system_logs", "/system-logs"),
    ("test_case_set_list", "/test-case-sets"),
    ("test_case_management", "/test-case-management"),
    ("qa_ai_helper", "/qa-ai-helper"),
    ("test_run_management", "/test-run-management"),
    ("test_run_execution", "/test-run-execution"),
    ("test_case_reference", "/test-case-reference"),
    ("first_login_setup", "/first-login-setup"),
    ("profile", "/profile"),
    ("team_statistics", "/team-statistics"),
    ("user_story_map", "/user-story-map/1"),
    ("adhoc_test_run_execution", "/adhoc-runs/1/execution"),
    ("system_setup_standalone", "/setup"),
]


@pytest.fixture(scope="module")
def client():
    """TestClient with lifespan startup/shutdown stubbed (no DB / background services).

    Page routes only call ``templates.TemplateResponse`` and do not touch the DB,
    so the full lifespan init (audit DB, USM DB, scheduler, leader election) is
    unnecessary and would require heavyweight fixtures. We monkeypatch the two
    lifespan callbacks to no-ops and restore them on teardown.
    """
    import app.main as app_main

    async def _noop(*_args, **_kwargs):
        return None

    real_startup = app_main._run_startup
    real_shutdown = app_main._run_shutdown
    app_main._run_startup = _noop  # type: ignore[assignment]
    app_main._run_shutdown = _noop  # type: ignore[assignment]
    try:
        with TestClient(app_main.app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app_main._run_startup = real_startup  # type: ignore[assignment]
        app_main._run_shutdown = real_shutdown  # type: ignore[assignment]


def render_page(client: TestClient, route: str) -> BeautifulSoup:
    """GET a page route and return its BeautifulSoup-parsed HTML."""
    resp = client.get(route)
    assert resp.status_code == 200, f"{route} returned {resp.status_code}"
    return BeautifulSoup(resp.text, "html.parser")


def _classes(node) -> list[str]:
    """Return the class list of a node (empty list if none)."""
    return node.get("class", []) if node else []


def all_page_routes():
    """pytest parametrize helper: yields pytest.param for every page route."""
    return [pytest.param(name, route, id=name) for name, route in PAGE_ROUTES]


# --------------------------------------------------------------------------- #
# SPEC-HOM-001 — Home button unification
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_home_button_is_canonical(page_name, route, client):
    """SPEC-HOM-001: every home link (a[href='/'] with btn) says 回到首頁, class order btn btn-secondary btn-sm, icon+text inline."""
    soup = render_page(client, route)
    home_links = [a for a in soup.find_all("a", href="/") if "btn" in _classes(a)]
    if not home_links:
        pytest.skip(f"{page_name}: no home button on this page")
    for link in home_links:
        classes = _classes(link)
        assert "btn-secondary" in classes, f"{page_name}: home btn missing btn-secondary"
        assert "btn-sm" in classes, f"{page_name}: home btn missing btn-sm"
        # Class order: btn before btn-secondary before btn-sm
        assert classes.index("btn-secondary") > classes.index("btn"), f"{page_name}: class order wrong"
        assert classes.index("btn-sm") > classes.index("btn-secondary"), f"{page_name}: class order wrong"
        text = link.get_text(strip=True)
        assert text == "回到首頁", f"{page_name}: home btn text is {text!r}, expected '回到首頁'"


# --------------------------------------------------------------------------- #
# SPEC-BTN-001 — Button class cleanup
# --------------------------------------------------------------------------- #

FORBIDDEN_BUTTON_CLASSES = ["btn-xs", "btn-view", "btn-edit", "test-run-kebab-btn"]


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_no_forbidden_button_classes(page_name, route, client):
    """SPEC-BTN-001: no btn-xs / btn-view / btn-edit / test-run-kebab-btn anywhere."""
    soup = render_page(client, route)
    offenders: list[str] = []
    for node in soup.find_all(class_=True):
        classes = _classes(node)
        for forbidden in FORBIDDEN_BUTTON_CLASSES:
            if forbidden in classes:
                offenders.append(f"{forbidden} on <{node.name} class='{' '.join(classes)}'>")
    assert not offenders, f"{page_name}: forbidden button classes:\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_no_btn_info_dropdown_trigger(page_name, route, client):
    """SPEC-BTN-001 / SPEC-DRP-001: dropdown triggers use btn-secondary, never btn-info."""
    soup = render_page(client, route)
    for node in soup.find_all("button", class_=True):
        classes = _classes(node)
        if "dropdown-toggle" in classes and "btn-info" in classes:
            pytest.fail(f"{page_name}: btn-info dropdown-toggle forbidden; use btn-secondary")
    # Also catch <a> dropdown triggers
    for node in soup.find_all("a", class_=True):
        classes = _classes(node)
        if "dropdown-toggle" in classes and "btn-info" in classes:
            pytest.fail(f"{page_name}: btn-info <a> dropdown-toggle forbidden; use btn-secondary")


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_button_variant_before_size(page_name, route, client):
    """SPEC-BTN-001: class order is btn btn-{variant} btn-sm — variant before size."""
    variants = {"btn-primary", "btn-secondary", "btn-success", "btn-danger", "btn-warning", "btn-info", "btn-outline-primary", "btn-outline-danger", "btn-link"}
    soup = render_page(client, route)
    offenders: list[str] = []
    for node in soup.find_all(class_="btn"):
        classes = _classes(node)
        if "btn-sm" not in classes:
            continue
        variant_present = [c for c in classes if c in variants]
        if not variant_present:
            continue
        # variant must appear before btn-sm
        if any(classes.index(v) > classes.index("btn-sm") for v in variant_present):
            offenders.append(f"<{node.name} class='{' '.join(classes)}'>")
    assert not offenders, f"{page_name}: variant after btn-sm (wrong order):\n  " + "\n  ".join(offenders)


# --------------------------------------------------------------------------- #
# SPEC-BDG-001 — Badge cleanup
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_no_text_bg_classes(page_name, route, client):
    """SPEC-BDG-001: no text-bg-* classes (use bg-* instead)."""
    soup = render_page(client, route)
    for node in soup.find_all(class_=True):
        for c in _classes(node):
            assert not c.startswith("text-bg-"), f"{page_name}: text-bg-* forbidden on <{node.name}>"


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_badges_have_bg_class(page_name, route, client):
    """SPEC-BDG-001: every <span class='badge'> must have at least one bg-* class; no badge-role."""
    soup = render_page(client, route)
    offenders: list[str] = []
    for node in soup.find_all("span", class_="badge"):
        classes = _classes(node)
        if "badge-role" in classes:
            offenders.append(f"badge-role on <{node.name}>")
            continue
        if not any(c.startswith("bg-") for c in classes):
            offenders.append(f"bare badge without bg-*: <{node.name} class='{' '.join(classes)}'>")
    assert not offenders, f"{page_name}: badge violations:\n  " + "\n  ".join(offenders)


# --------------------------------------------------------------------------- #
# SPEC-TBL-001 — Table canonical classes
# --------------------------------------------------------------------------- #

REQUIRED_TABLE_CLASSES = {"table-sm", "table-hover", "align-middle"}


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_tables_have_canonical_classes(page_name, route, client):
    """SPEC-TBL-001: every <table class='table'> has table-sm + table-hover + align-middle."""
    soup = render_page(client, route)
    offenders: list[str] = []
    for table in soup.find_all("table", class_="table"):
        classes = set(_classes(table))
        missing = REQUIRED_TABLE_CLASSES - classes
        if missing:
            offenders.append(f"missing {missing}: <table class='{' '.join(sorted(classes))}'>")
    assert not offenders, f"{page_name}: tables missing canonical classes:\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_table_thead_no_table_light(page_name, route, client):
    """SPEC-TBL-001: <thead> must not use table-light."""
    soup = render_page(client, route)
    for table in soup.find_all("table", class_="table"):
        thead = table.find("thead")
        if thead and "table-light" in _classes(thead):
            pytest.fail(f"{page_name}: <thead> uses table-light (forbidden)")


# --------------------------------------------------------------------------- #
# SPEC-MDL-001 — Modal structure
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_no_inline_modal_size(page_name, route, client):
    """SPEC-MDL-001: .modal-dialog must not have inline style=."""
    soup = render_page(client, route)
    for dialog in soup.find_all(class_="modal-dialog"):
        assert not dialog.get("style"), f"{page_name}: modal-dialog has inline style={dialog.get('style')!r}"


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_modal_header_no_bg(page_name, route, client):
    """SPEC-MDL-001: .modal-header must not have bg-light / bg-danger / bg-warning / text-white."""
    soup = render_page(client, route)
    forbidden = {"bg-light", "bg-danger", "bg-warning", "text-white"}
    for header in soup.find_all(class_="modal-header"):
        classes = set(_classes(header))
        bad = forbidden & classes
        assert not bad, f"{page_name}: modal-header has {bad}"


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_modal_footer_no_bg_light(page_name, route, client):
    """SPEC-MDL-001: .modal-footer must not have bg-light."""
    soup = render_page(client, route)
    for footer in soup.find_all(class_="modal-footer"):
        assert "bg-light" not in _classes(footer), f"{page_name}: modal-footer has bg-light"


# --------------------------------------------------------------------------- #
# SPEC-CRD-001 — Card header canonical classes
# --------------------------------------------------------------------------- #

REQUIRED_CARD_HEADER_CLASSES = {"bg-light", "d-flex", "align-items-center", "justify-content-between"}


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_card_header_canonical(page_name, route, client):
    """SPEC-CRD-001: every .card-header has bg-light + d-flex + align-items-center + justify-content-between."""
    soup = render_page(client, route)
    offenders: list[str] = []
    for header in soup.find_all(class_="card-header"):
        classes = set(_classes(header))
        missing = REQUIRED_CARD_HEADER_CLASSES - classes
        if missing:
            offenders.append(f"missing {missing}: <card-header class='{' '.join(sorted(classes))}'>")
    assert not offenders, f"{page_name}: card-header violations:\n  " + "\n  ".join(offenders)


# --------------------------------------------------------------------------- #
# SPEC-TLB-001 — Toolbar
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_no_automation_toolbar(page_name, route, client):
    """SPEC-TLB-001: no automation-toolbar class anywhere."""
    soup = render_page(client, route)
    assert not soup.find(class_="automation-toolbar"), f"{page_name}: automation-toolbar forbidden"


# --------------------------------------------------------------------------- #
# SPEC-TAB-001 — Tab navigation
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_no_nav_pills(page_name, route, client):
    """SPEC-TAB-001: no nav-pills anywhere (use nav-tabs)."""
    soup = render_page(client, route)
    assert not soup.find(class_="nav-pills"), f"{page_name}: nav-pills forbidden"


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_nav_tabs_have_mb3(client, page_name, route):
    """SPEC-TAB-001: every <ul class='nav nav-tabs'> has mb-3."""
    soup = render_page(client, route)
    offenders: list[str] = []
    for ul in soup.find_all("ul", class_="nav-tabs"):
        if "mb-3" not in _classes(ul):
            offenders.append(f"<ul class='{' '.join(_classes(ul))}'>")
    assert not offenders, f"{page_name}: nav-tabs ul missing mb-3:\n  " + "\n  ".join(offenders)


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_tab_links_have_icons(page_name, route, client):
    """SPEC-TAB-001: every .nav-link inside .nav-tabs has an <i> icon."""
    soup = render_page(client, route)
    offenders: list[str] = []
    for ul in soup.find_all("ul", class_="nav-tabs"):
        for link in ul.find_all("a", class_="nav-link") + ul.find_all("button", class_="nav-link"):
            if not link.find("i"):
                offenders.append(f"<{link.name} class='{' '.join(_classes(link))}'> text={link.get_text(strip=True)!r}")
    assert not offenders, f"{page_name}: tab without icon:\n  " + "\n  ".join(offenders)


# --------------------------------------------------------------------------- #
# SPEC-DRP-001 — Dropdown
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_no_custom_status_dropdown(page_name, route, client):
    """SPEC-DRP-001: no custom-status-dropdown anywhere."""
    soup = render_page(client, route)
    assert not soup.find(class_="custom-status-dropdown"), f"{page_name}: custom-status-dropdown forbidden"


# --------------------------------------------------------------------------- #
# SPEC-NAV-001 — Navigation consolidation (header Admin dropdown)
# --------------------------------------------------------------------------- #

def test_admin_dropdown_present_in_base(client):
    """SPEC-NAV-001: base.html renders the Admin dropdown group ( 管理 )."""
    soup = render_page(client, "/")
    admin_group = soup.find(id="adminDropdownGroup")
    assert admin_group, "base.html missing #adminDropdownGroup"
    # The dropdown is hidden by default (d-none); base-auth.js reveals it for admins.
    assert "d-none" in _classes(admin_group), "admin dropdown should start hidden for RBAC"
    toggle = admin_group.find("button", class_="dropdown-toggle")
    assert toggle, "admin dropdown missing toggle button"
    assert "管理" in toggle.get_text(), "admin dropdown toggle should be labeled 管理"


def test_team_management_has_no_data_menu(client):
    """SPEC-NAV-001: team_management no longer carries its own data-menu dropdown."""
    soup = render_page(client, "/team-management")
    assert not soup.find(id="dataMenuGroup"), "team_management still has #dataMenuGroup"


# --------------------------------------------------------------------------- #
# i18n anti-pattern — no d-none divs carrying data-i18n strings
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_no_hidden_i18n_string_stores(page_name, route, client):
    """i18n anti-pattern: no d-none element whose id marks it as an i18n string store.

    The documented anti-pattern (organization_management.html's ``org-sync-i18n`` /
    ``personnel-i18n`` divs holding 100+ strings JS reads via ``.textContent``) is
    detected by an id containing ``i18n`` on a hidden container. Legitimate toggled
    elements (loading indicators, empty states, responsive labels) are NOT string
    stores and do not trip this check.
    """
    soup = render_page(client, route)
    offenders: list[str] = []
    for node in soup.find_all(class_="d-none"):
        node_id = node.get("id") or ""
        if "i18n" in node_id.lower():
            count = len(node.find_all(attrs={"data-i18n": True}))
            offenders.append(f"<{node.name} id='{node_id}'> ({count} data-i18n descendants)")
    assert not offenders, f"{page_name}: hidden i18n string-store containers:\n  " + "\n  ".join(offenders)
