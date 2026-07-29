"""Tests for the Test Case Set filter share link feature.

Covers:
- UI elements exist in template (button + modal)
- i18n keys present in all locales
- JS serialization/deserialization functions exist
- Login redirect fix uses `redirect` param
- Round-trip consistency of filter param names

Each test reads every artifact it needs once; the assertions are grouped by
artifact rather than split one-per-test so the whole file stays a handful of
cheap static checks.
"""
import json
import re
from pathlib import Path

TEMPLATE = Path("app/templates/test_case_management.html")
MODAL_JS = Path("app/static/js/test-case-management/modal.js")
INIT_JS = Path("app/static/js/test-case-management/init.js")
LOGIN_JS = Path("app/static/js/login.js")
LOCALES_DIR = Path("app/static/locales")
LOCALE_FILES = ["zh-TW.json", "en-US.json", "zh-CN.json"]
FILTER_PARAMS = ["f_num", "f_kw", "f_tcg", "f_pri"]


# ─── Task 4.1: Authenticated direct-open shared link ───

def test_share_link_ui_elements_exist():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="generateFilterLinkBtn"' in html
    assert 'id="shareFilterLinkModal"' in html
    assert 'id="shareFilterLinkInput"' in html
    assert "readonly" in html.split('id="shareFilterLinkInput"')[1].split(">")[0]
    assert 'id="copyShareFilterLinkBtn"' in html
    assert 'data-i18n="testCaseSet.shareFilter.generateLink"' in html


def test_share_link_js_functions_and_bindings_exist():
    modal_js = MODAL_JS.read_text(encoding="utf-8")
    for signature in (
        "function serializeFiltersToParams()",
        "function buildShareFilterURL()",
        "function restoreFiltersFromQueryString()",
        "function generateShareFilterLink()",
        "function copyShareFilterLink()",
    ):
        assert signature in modal_js, f"{signature} missing from {MODAL_JS}"

    init_js = INIT_JS.read_text(encoding="utf-8")
    for marker in (
        "generateFilterLinkBtn",
        "generateShareFilterLink",
        "copyShareFilterLinkBtn",
        "copyShareFilterLink",
    ):
        assert marker in init_js, f"{marker} not bound in {INIT_JS}"


# ─── Task 4.2: Unauthenticated login redirect preserves URL ───

def test_login_redirect_preserves_original_url():
    login_js = LOGIN_JS.read_text(encoding="utf-8")
    assert "urlParams.get('redirect')" in login_js
    assert "window.location.href = redirectTo" in login_js

    login_success_block = login_js.split("Login successful")[1].split("handleLoginError")[0]
    hardcoded = re.findall(r"window\.location\.href\s*=\s*'/'", login_success_block)
    assert len(hardcoded) == 0, "Login success should not hardcode redirect to '/'"

    # auth.js redirectToLogin should include pathname + search.
    auth_js = Path("app/static/js/auth.js").read_text(encoding="utf-8")
    assert "window.location.pathname + window.location.search" in auth_js


# ─── Task 4.3: Round-trip filter serialization/deserialization ───

def test_filter_params_round_trip():
    modal_js = MODAL_JS.read_text(encoding="utf-8")
    restore_fn = modal_js.split("function restoreFiltersFromQueryString")[1].split(
        "\nfunction "
    )[0]
    # buildShareFilterURL should remove old f_* params before merging.
    build_fn = modal_js.split("function buildShareFilterURL")[1].split("\nfunction ")[0]

    for param in FILTER_PARAMS:
        assert f"'{param}'" in modal_js or f'"{param}"' in modal_js, (
            f"Filter param {param} not found in serialization"
        )
        assert param in restore_fn, f"Filter param {param} not read in deserialization"
        assert f"'{param}'" in build_fn or f'"{param}"' in build_fn, (
            f"Filter param {param} not cleaned in buildShareFilterURL"
        )

    # buildShareFilterURL must ensure team_id and set_id in shared link.
    assert "team_id" in build_fn
    assert "set_id" in build_fn

    # Init should call applyFilters after restoring from QS.
    init_js = INIT_JS.read_text(encoding="utf-8")
    assert "restoreFiltersFromQueryString" in init_js
    assert "applyFilters()" in init_js


def test_url_team_id_takes_precedence_for_shared_links():
    # test-case-set-integration getTeamIdFromPage should prioritize URL.
    integration_js = Path("app/static/js/test-case-set-integration.js").read_text(
        encoding="utf-8"
    )
    assert "getUrlParam('team_id')" in integration_js or (
        'getUrlParam("team_id")' in integration_js
    )
    assert "getTeamIdFromPage" in integration_js

    # ensureTeamContext should use URL team_id when it differs from AppUtils.
    cache_js = Path("app/static/js/test-case-management/cache.js").read_text(
        encoding="utf-8"
    )
    assert "urlTeamId" in cache_js
    assert "getTeamIdForCache" in cache_js


# ─── i18n completeness ───

def test_share_filter_keys_in_all_locales():
    required_keys = [
        "generateLink",
        "generateLinkTooltip",
        "modalTitle",
        "noFilters",
    ]
    for locale_file in LOCALE_FILES:
        data = json.loads((LOCALES_DIR / locale_file).read_text(encoding="utf-8"))
        sf = data.get("testCaseSet", {}).get("shareFilter", {})
        for key in required_keys:
            assert key in sf, f"Missing key testCaseSet.shareFilter.{key} in {locale_file}"
            assert sf[key], f"Empty value for testCaseSet.shareFilter.{key} in {locale_file}"
