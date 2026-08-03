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

import json
import re
from pathlib import Path

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


def test_index_is_dashboard_shell_without_current_team_badge_and_keeps_ai_widget(client):
    """The homepage is dashboard-owned while the global Assistant remains available."""
    soup = render_page(client, "/")
    assert soup.find(id="dashboard-root") is not None
    assert soup.find(id="dashboard-content") is not None
    assert soup.find(id="team-name-badge") is None
    script_sources = [script.get("src", "") for script in soup.find_all("script")]
    assert any("js/index.js" in source for source in script_sources)
    assert any("js/assistant-widget.js" in source for source in script_sources)


def test_index_dashboard_modals_use_canonical_structure(client):
    """Dashboard preference and activity dialogs follow SPEC-MDL-001."""
    soup = render_page(client, "/")
    for modal_id in ("dashboard-preference-modal", "dashboard-activity-modal"):
        modal = soup.find(id=modal_id)
        assert modal is not None
        dialog = modal.find(class_="modal-dialog")
        assert dialog is not None
        assert dialog.get("style") is None
        header = modal.find(class_="modal-header")
        assert header is not None
        assert header.find("h5", class_="modal-title") is not None
        assert header.find("button", class_="btn-close") is not None


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


# --------------------------------------------------------------------------- #
# App chrome layout — reachable toolbar, z-index tokens, dvh fallbacks
# --------------------------------------------------------------------------- #

_Z_TOKEN_RE = re.compile(r"z-index\s*:\s*var\(--z-[a-z-]+\)\s*;")
_Z_NUMERIC_RE = re.compile(r"z-index\s*:\s*(-?\d+)\s*(!important)?\s*;")
_Z_IMPORTANT_RE = re.compile(r"z-index\s*:[^;]*!important")
_HEIGHT_PROP_RE = re.compile(
    r"(?P<prop>(?:min-|max-)?height)\s*:\s*(?P<val>[^;{}]+);",
    re.I,
)
_VH_RE = re.compile(r"\d*\.?\d+vh\b")


def _css_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1] / "static" / "css"
    return sorted(root.glob("*.css"))


def _load_z_index_baseline() -> set[tuple[str, int]]:
    baseline_path = Path(__file__).resolve().parents[2] / "scripts" / "z-index-baseline.json"
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    allowed: set[tuple[str, int]] = set()
    for entry in data.get("numericLocalZIndex", []):
        allowed.add((entry["file"].replace("\\", "/"), int(entry["value"])))
    return allowed


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_header_toolbar_has_overflow_and_pin_structure(page_name, route, client):
    """App chrome: toolbar exposes overflow + pin zones; user menu stays pinned."""
    soup = render_page(client, route)
    # Pages that deliberately omit the shared chrome toolbar skip this.
    if not soup.find(class_="app-header"):
        return
    toolbar = soup.find(class_="header-toolbar")
    if toolbar is None:
        # e.g. first_login_setup empties {% block page_actions %}
        return
    assert soup.find(id="headerToolbarScroll"), f"{page_name}: missing #headerToolbarScroll"
    assert soup.find(id="headerToolbarItems"), f"{page_name}: missing #headerToolbarItems"
    assert soup.find(id="headerToolbarOverflow"), f"{page_name}: missing overflow menu"
    pin = soup.find(id="headerToolbarPin")
    assert pin, f"{page_name}: missing #headerToolbarPin"
    assert pin.find(class_="header-toolbar-user") or pin.find(id="user-info-container") or pin.find(
        id="userDropdown"
    ), f"{page_name}: user menu not in pin zone"
    # Overflow starts collapsed (d-none) until ResizeObserver folds items.
    overflow = soup.find(id="headerToolbarOverflow")
    assert "d-none" in _classes(overflow), f"{page_name}: overflow should start hidden"


def test_style_css_defines_z_index_token_scale():
    """ui-design-system: :root declares the six --z-* tokens."""
    style = (Path(__file__).resolve().parents[1] / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    for token in (
        "--z-dropdown",
        "--z-sticky",
        "--z-chrome",
        "--z-modal",
        "--z-toast",
        "--z-assistant",
    ):
        assert f"{token}:" in style, f"missing {token} in style.css :root"


def test_fixed_layer_z_index_uses_tokens_without_important():
    """App chrome: window-level z-index values resolve from --z-* with no !important."""
    allowed = _load_z_index_baseline()
    offenders: list[str] = []
    for path in _css_files():
        rel = str(path.relative_to(path.parents[2])).replace("\\", "/")
        # path is app/static/css/x.css — parents[2] is repo root? 
        # Path: .../app/static/css/file.css → parents[0]=css, [1]=static, [2]=app
        rel = f"app/static/css/{path.name}"
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if _Z_IMPORTANT_RE.search(line):
                offenders.append(f"{rel}:{i}: !important on z-index: {line.strip()}")
            for m in _Z_NUMERIC_RE.finditer(line):
                value = int(m.group(1))
                if value >= 1000:
                    offenders.append(f"{rel}:{i}: hardcoded window z-index {value}")
                elif (rel, value) not in allowed:
                    offenders.append(
                        f"{rel}:{i}: numeric z-index {value} not in scripts/z-index-baseline.json"
                    )
    assert not offenders, "z-index contract failures:\n  " + "\n  ".join(offenders)


def test_viewport_height_declarations_have_dvh_fallback():
    """App chrome: height/min-height/max-height vh units are paired with dvh overrides."""
    offenders: list[str] = []
    for path in _css_files():
        rel = f"app/static/css/{path.name}"
        text = path.read_text(encoding="utf-8")
        for m in _HEIGHT_PROP_RE.finditer(text):
            val = m.group("val")
            if not _VH_RE.search(val) or "dvh" in val:
                continue
            # Custom properties named *height* are allowed as long as a dvh twin follows.
            rest = text[m.end() :].lstrip()
            prop = m.group("prop")
            twin_ok = bool(re.match(re.escape(prop) + r"\s*:\s*[^;]*dvh", rest, re.I))
            # Also accept --foo-height: vh; --foo-height: dvh;
            if not twin_ok and prop.startswith("-"):
                twin_ok = bool(re.match(re.escape(prop) + r"\s*:\s*[^;]*dvh", rest, re.I))
            if not twin_ok:
                # For custom props ending in height matched by prop incorrectly — skip
                # if the match was a suffix of a custom property name.
                start = m.start()
                prefix = text[max(0, start - 40) : start]
                if re.search(r"--[A-Za-z0-9_-]*$", prefix):
                    continue
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{rel}:{line}: {m.group(0).strip()[:100]}")
        # Custom property values with vh
        for m in re.finditer(
            r"(--[A-Za-z0-9_-]*height[A-Za-z0-9_-]*)\s*:\s*([^;{}]+);", text, re.I
        ):
            prop, val = m.group(1), m.group(2)
            if not _VH_RE.search(val) or "dvh" in val:
                continue
            rest = text[m.end() :].lstrip()
            if not re.match(re.escape(prop) + r"\s*:\s*[^;]*dvh", rest, re.I):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{rel}:{line}: {prop}: {val.strip()[:60]}")
    assert not offenders, "vh without dvh fallback:\n  " + "\n  ".join(offenders)


def test_dead_fixed_pagination_chrome_removed():
    """App chrome: fixed-pagination-bar dead CSS must stay gone."""
    style = (Path(__file__).resolve().parents[1] / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    assert ".fixed-pagination-bar" not in style
    # And no templates/js references
    repo = Path(__file__).resolve().parents[2]
    hay = ""
    for base in (repo / "app" / "templates", repo / "app" / "static" / "js"):
        for path in base.rglob("*"):
            if path.suffix in {".html", ".js"}:
                hay += path.read_text(encoding="utf-8", errors="ignore")
    assert "fixed-pagination-bar" not in hay


def test_header_height_token_is_fixed_px():
    """App chrome: --header-height stays a fixed px value (overflow must not grow header)."""
    style = (Path(__file__).resolve().parents[1] / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    m = re.search(r"--header-height:\s*([^;]+);", style)
    assert m, "missing --header-height"
    assert m.group(1).strip().endswith("px"), f"--header-height must be px, got {m.group(1)!r}"


def test_app_header_does_not_clip_dropdowns():
    """App chrome reachability: header chrome must not clip dropdown menus."""
    style = (Path(__file__).resolve().parents[1] / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    header = re.search(r"\.app-header\s*\{([^}]+)\}", style)
    assert header, "missing .app-header rule"
    assert "overflow: hidden" not in header.group(1), (
        ".app-header { overflow: hidden } clips pinned user-menu dropdowns"
    )

    title = re.search(r"\.app-header-title\s*\{([^}]+)\}", style)
    assert title, "missing .app-header-title rule"
    assert "overflow: hidden" not in title.group(1), (
        ".app-header-title { overflow: hidden } clips team-nav dropdown (ART badge)"
    )
    assert "overflow: visible" in title.group(1)


def test_app_header_buttons_disable_hover_lift():
    """Header chrome buttons must not translateY on hover (scrollport would clip the top edge)."""
    style = (Path(__file__).resolve().parents[1] / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    block = re.search(
        r"\.app-header \.btn:hover,\s*\.app-header \.btn:focus-visible,[\s\S]*?\{([^}]+)\}",
        style,
    )
    assert block, "missing .app-header .btn:hover override"
    assert "transform: none" in block.group(1)


def test_chrome_dropdown_toggles_use_fixed_popper(client):
    """Every chrome dropdown toggle uses Popper fixed strategy (title + toolbar + footer)."""
    soup = render_page(client, "/team-management")
    header = soup.find(class_="app-header")
    assert header is not None
    offenders: list[str] = []
    for toggle in header.select('[data-bs-toggle="dropdown"]'):
        config = toggle.get("data-bs-popper-config") or ""
        if "fixed" not in config:
            tid = toggle.get("id") or " ".join(_classes(toggle))[:40]
            offenders.append(tid)
    assert not offenders, "header dropdowns missing Popper fixed strategy: " + ", ".join(offenders)

    lang = soup.find(id="languageDropdown")
    assert lang is not None
    assert "fixed" in (lang.get("data-bs-popper-config") or "")

    team = soup.find(id="team-name-badge")
    assert team is not None
    assert "fixed" in (team.get("data-bs-popper-config") or "")


def test_language_switcher_clears_assistant_fab():
    """Floating utilities: language switcher reserves clearance beside the Assistant FAB."""
    style = (Path(__file__).resolve().parents[1] / "static" / "css" / "style.css").read_text(
        encoding="utf-8"
    )
    assert "body:not([data-assistant-widget=\"off\"]) #language-switcher" in style
    assert "margin-right" in style
    assistant = (
        Path(__file__).resolve().parents[1] / "static" / "css" / "assistant-widget.css"
    ).read_text(encoding="utf-8")
    assert "var(--z-assistant)" in assistant
    assert "var(--footer-height)" in assistant


# --------------------------------------------------------------------------- #
# Self-hosted presentation assets + font token integrity
# --------------------------------------------------------------------------- #

_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
_VENDOR_DIR = _STATIC_DIR / "vendor"

# Page-scoped libraries not covered by the base-layout vendor set in
# fix-frontend-asset-and-font-integrity (tracked debt). New external hosts must
# not be added without extending vendor/ or this allowlist deliberately.
_ALLOWED_PAGE_SCOPED_ASSET_PREFIXES = (
    "https://cdn.jsdelivr.net/npm/chart.js@",
    "https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@",
    "https://cdn.jsdelivr.net/npm/reactflow@",
    "https://cdn.jsdelivr.net/npm/monaco-editor@",
    "https://cdn.jsdelivr.net/npm/handsontable@",
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/",
    "https://unpkg.com/dagre@",
    "https://unpkg.com/react@",
    "https://unpkg.com/react-dom@",
    "https://unpkg.com/reactflow@",
)


def _asset_url(attr: str | None) -> str:
    return (attr or "").strip()


def _is_external_http(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def _is_allowed_page_scoped_asset(url: str) -> bool:
    return any(url.startswith(prefix) for prefix in _ALLOWED_PAGE_SCOPED_ASSET_PREFIXES)


@pytest.mark.parametrize("page_name, route", all_page_routes())
def test_pages_have_no_external_presentation_asset_origins(page_name, route, client):
    """Presentation <link>/<script>/<img> stay on-origin; iframe/a are out of scope."""
    soup = render_page(client, route)
    offenders: list[str] = []

    for tag_name, attr in (("link", "href"), ("script", "src"), ("img", "src")):
        for node in soup.find_all(tag_name):
            url = _asset_url(node.get(attr))
            if not url or not _is_external_http(url):
                continue
            if tag_name in {"link", "script"} and _is_allowed_page_scoped_asset(url):
                continue
            offenders.append(f"{tag_name}[{attr}]={url}")

    assert not offenders, (
        f"{page_name}: external presentation assets must be self-hosted "
        f"(or an explicit page-scoped allowlist entry): " + "; ".join(offenders)
    )


def test_font_tokens_are_backed_by_vendor_files():
    """Every --font-* token maps to a declared self-hosted @font-face family + woff2."""
    style = (_STATIC_DIR / "css" / "style.css").read_text(encoding="utf-8")
    fonts_css = (_VENDOR_DIR / "fonts" / "fonts.css").read_text(encoding="utf-8")

    token_map = dict(re.findall(r"--(font-[\w-]+)\s*:\s*([^;]+);", style))
    assert "font-sans" in token_map
    assert "font-mono" in token_map
    assert "font-condensed" not in token_map

    for token, value in token_map.items():
        # First quoted family is the primary face that must be self-hosted.
        match = re.search(r"['\"]([^'\"]+)['\"]", value)
        assert match, f"--{token} has no quoted family: {value!r}"
        family = match.group(1)
        assert f"font-family: '{family}'" in fonts_css or f'font-family: "{family}"' in fonts_css, (
            f"--{token} family {family!r} missing from vendor fonts.css"
        )

    woff2_files = list((_VENDOR_DIR / "fonts").rglob("*.woff2"))
    assert woff2_files, "expected self-hosted woff2 files under app/static/vendor/fonts/"
    assert (_VENDOR_DIR / "bootstrap" / "bootstrap.min.css").is_file()
    assert (_VENDOR_DIR / "bootstrap" / "bootstrap.bundle.min.js").is_file()
    assert (_VENDOR_DIR / "fontawesome" / "css" / "all.min.css").is_file()
    assert (_VENDOR_DIR / "pako" / "pako.min.js").is_file()
    assert (_VENDOR_DIR / "MANIFEST.md").is_file()


def test_base_layout_uses_vendor_assets_not_cdn(client):
    """base.html common chrome loads Bootstrap / FA / fonts / pako from /static/vendor/."""
    soup = render_page(client, "/")
    hrefs = [_asset_url(n.get("href")) for n in soup.find_all("link")]
    srcs = [_asset_url(n.get("src")) for n in soup.find_all("script")]
    joined = "\n".join(hrefs + srcs)
    assert "/static/vendor/bootstrap/bootstrap.min.css" in joined
    assert "/static/vendor/fontawesome/css/all.min.css" in joined
    assert "/static/vendor/fonts/fonts.css" in joined
    assert "/static/vendor/bootstrap/bootstrap.bundle.min.js" in joined
    assert "/static/vendor/pako/pako.min.js" in joined
    for forbidden in (
        "fonts.googleapis.com",
        "fonts.gstatic.com",
        "cdn.jsdelivr.net/npm/bootstrap@",
        "cdn.jsdelivr.net/npm/pako@",
        "cdnjs.cloudflare.com/ajax/libs/font-awesome/",
        "gravatar.com",
        "feishucdn.com",
    ):
        assert forbidden not in joined, f"base layout still references {forbidden}"


# --------------------------------------------------------------------------- #
# Data view state contract (establish-data-view-state-contract)
# --------------------------------------------------------------------------- #

_NATIVE_DIALOG_RE = re.compile(r"(?<![\w.$])(alert|confirm)\s*\(")
_JS_ROOT = _STATIC_DIR / "js"
_TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates"


def test_app_utils_exposes_nonblocking_confirm_and_notify():
    """AppUtils must provide Promise-based confirm/notify (no native dialogs)."""
    app_js = (_JS_ROOT / "app.js").read_text(encoding="utf-8")
    assert re.search(r"\bconfirm\s*:\s*function\s*\(", app_js)
    assert re.search(r"\bnotify\s*:\s*function\s*\(", app_js)
    assert "window.confirm(" not in app_js
    assert "window.alert(" not in app_js


def test_frontend_js_has_no_native_alert_or_confirm():
    """Static JS must not call native alert()/confirm() (data-view-states contract)."""
    offenders: list[str] = []
    for path in sorted(_JS_ROOT.rglob("*.js")):
        if "vendor" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in _NATIVE_DIALOG_RE.finditer(text):
            # Allow matches that only appear inside comments on the same line.
            line_start = text.rfind("\n", 0, match.start()) + 1
            line = text[line_start : text.find("\n", match.start())]
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
                continue
            rel = path.relative_to(_JS_ROOT.parents[1])
            offenders.append(f"{rel}:{text.count(chr(10), 0, match.start()) + 1}:{line.strip()}")
    assert not offenders, "native alert/confirm remain:\n" + "\n".join(offenders)


def test_templates_have_no_native_alert_or_confirm():
    """Jinja templates must not embed native alert()/confirm() call sites."""
    offenders: list[str] = []
    for path in sorted(_TEMPLATE_ROOT.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in _NATIVE_DIALOG_RE.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line = text[line_start : text.find("\n", match.start())]
            stripped = line.lstrip()
            if stripped.startswith("//") or stripped.startswith("<!--"):
                continue
            rel = path.relative_to(_TEMPLATE_ROOT.parents[1])
            offenders.append(f"{rel}:{text.count(chr(10), 0, match.start()) + 1}:{line.strip()}")
    assert not offenders, "native alert/confirm in templates:\n" + "\n".join(offenders)


def test_shared_skeleton_and_empty_state_components_exist():
    """Shared data-view state macros must be present under components/."""
    skeleton = (_TEMPLATE_ROOT / "components" / "skeleton.html").read_text(encoding="utf-8")
    empty = (_TEMPLATE_ROOT / "components" / "empty_state.html").read_text(encoding="utf-8")
    assert "macro skeleton" in skeleton
    assert "tcrt-skeleton" in skeleton
    assert "variant='cards'" in skeleton or 'variant="cards"' in skeleton or "variant == 'cards'" in skeleton
    assert "macro empty_state" in empty
    assert "tcrt-empty-state" in empty
    style = (_STATIC_DIR / "css" / "style.css").read_text(encoding="utf-8")
    assert ".tcrt-skeleton" in style
    assert ".tcrt-empty-state" in style


def test_test_case_sets_page_has_state_containers_and_display_paths(client):
    """/test-case-sets must ship loading/empty/error containers with JS display paths."""
    soup = render_page(client, "/test-case-sets")
    for element_id in ("setsLoadingState", "emptyState", "setsErrorState", "noTeamState"):
        node = soup.find(id=element_id)
        assert node is not None, f"missing #{element_id}"

    retry = soup.find(id="setsErrorRetryBtn")
    assert retry is not None, "error state must expose a retry control"

    main_js = (_JS_ROOT / "test-case-set-list" / "main.js").read_text(encoding="utf-8")
    assert "showSetsViewState('empty')" in main_js
    assert "showSetsViewState('error'" in main_js or 'showSetsViewState("error"' in main_js
    assert "showSetsViewState('no-team')" in main_js
    assert "showSetsViewState('loading')" in main_js
    # Display path must actually unhide empty/error (not only add d-none).
    assert "setHidden(emptyState, state !== 'empty')" in main_js
    assert "setHidden(errorState, state !== 'error')" in main_js


def test_selection_dependent_personnel_actions_default_disabled(client):
    """Org personnel delete/reset must render disabled until a user is selected."""
    soup = render_page(client, "/organization-management")
    for element_id in ("pm-delete", "pm-reset"):
        btn = soup.find(id=element_id)
        assert btn is not None, f"missing #{element_id}"
        assert btn.has_attr("disabled"), f"#{element_id} must default to disabled"


def test_selection_dependent_batch_actions_default_disabled():
    """Test case batch actions must default to disabled with zero selection.

    `/test-case-management` redirects without a set id, so assert the template source.
    """
    template = (_TEMPLATE_ROOT / "test_case_management.html").read_text(encoding="utf-8")
    for element_id in ("batchModifyBtn", "batchCopyBtn", "batchDeleteBtn"):
        match = re.search(
            rf'id="{element_id}"[^>]*>',
            template,
        )
        assert match, f"missing #{element_id} in test_case_management.html"
        tag = match.group(0)
        assert "disabled" in tag, f"#{element_id} must default to disabled: {tag}"


def test_destructive_confirm_gates_are_not_bypassed():
    """High-risk destructive flows must await AppUtils.confirm before the mutating call."""
    personnel = (
        _JS_ROOT / "organization-management" / "personnel_management.js"
    ).read_text(encoding="utf-8")
    delete_fn = re.search(
        r"async function onDelete\([\s\S]*?\n  \}\n\n  async function onResetPwd",
        personnel,
    )
    assert delete_fn, "onDelete not found"
    delete_body = delete_fn.group(0)
    assert "await AppUtils.confirm(" in delete_body
    confirm_pos = delete_body.find("await AppUtils.confirm(")
    delete_pos = delete_body.find("method: 'DELETE'")
    assert confirm_pos != -1 and delete_pos != -1 and confirm_pos < delete_pos

    cross = (_JS_ROOT / "test-case-cross-set-ops.js").read_text(encoding="utf-8")
    move_fn = re.search(r"async confirmCrossSetMove\([\s\S]*?\n  \}", cross)
    assert move_fn, "confirmCrossSetMove not found"
    move_body = move_fn.group(0)
    assert "await AppUtils.confirm(" in move_body
    confirm_pos = move_body.find("await AppUtils.confirm(")
    api_pos = move_body.find("move-across-sets")
    assert confirm_pos != -1 and api_pos != -1 and confirm_pos < api_pos
