"""Tests for the Test Case Set filter share link feature.

Covers:
- UI elements exist in template (button + modal)
- i18n keys present in all locales
- JS serialization/deserialization functions exist
- Login redirect fix uses `redirect` param
- Round-trip consistency of filter param names
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

class TestShareLinkUIElements:
    def test_generate_link_button_exists(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        assert 'id="generateFilterLinkBtn"' in html

    def test_share_modal_exists(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        assert 'id="shareFilterLinkModal"' in html

    def test_share_link_input_field_exists(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        assert 'id="shareFilterLinkInput"' in html
        assert "readonly" in html.split('id="shareFilterLinkInput"')[1].split(">")[0]

    def test_copy_button_exists(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        assert 'id="copyShareFilterLinkBtn"' in html

    def test_generate_button_has_i18n(self):
        html = TEMPLATE.read_text(encoding="utf-8")
        assert 'data-i18n="testCaseSet.shareFilter.generateLink"' in html


class TestShareLinkJSFunctions:
    def test_serialize_function_exists(self):
        js = MODAL_JS.read_text(encoding="utf-8")
        assert "function serializeFiltersToParams()" in js

    def test_build_url_function_exists(self):
        js = MODAL_JS.read_text(encoding="utf-8")
        assert "function buildShareFilterURL()" in js

    def test_restore_from_qs_function_exists(self):
        js = MODAL_JS.read_text(encoding="utf-8")
        assert "function restoreFiltersFromQueryString()" in js

    def test_generate_handler_exists(self):
        js = MODAL_JS.read_text(encoding="utf-8")
        assert "function generateShareFilterLink()" in js

    def test_copy_handler_exists(self):
        js = MODAL_JS.read_text(encoding="utf-8")
        assert "function copyShareFilterLink()" in js

    def test_event_binding_generate_link(self):
        js = INIT_JS.read_text(encoding="utf-8")
        assert "generateFilterLinkBtn" in js
        assert "generateShareFilterLink" in js

    def test_event_binding_copy_link(self):
        js = INIT_JS.read_text(encoding="utf-8")
        assert "copyShareFilterLinkBtn" in js
        assert "copyShareFilterLink" in js


# ─── Task 4.2: Unauthenticated login redirect preserves URL ───

class TestLoginRedirectPreservesURL:
    def test_login_success_uses_redirect_param(self):
        js = LOGIN_JS.read_text(encoding="utf-8")
        assert "urlParams.get('redirect')" in js
        assert "window.location.href = redirectTo" in js

    def test_login_success_does_not_hardcode_root(self):
        js = LOGIN_JS.read_text(encoding="utf-8")
        login_success_block = js.split("Login successful")[1].split("handleLoginError")[0]
        hardcoded = re.findall(r"window\.location\.href\s*=\s*'/'", login_success_block)
        assert len(hardcoded) == 0, "Login success should not hardcode redirect to '/'"

    def test_auth_redirect_preserves_query_string(self):
        """auth.js redirectToLogin should include pathname + search."""
        auth_js = Path("app/static/js/auth.js").read_text(encoding="utf-8")
        assert "window.location.pathname + window.location.search" in auth_js


# ─── Task 4.3: Round-trip filter serialization/deserialization ───

class TestFilterParamRoundTrip:
    def test_serialize_uses_correct_param_names(self):
        js = MODAL_JS.read_text(encoding="utf-8")
        for param in FILTER_PARAMS:
            assert f"'{param}'" in js or f'"{param}"' in js, (
                f"Filter param {param} not found in serialization"
            )

    def test_deserialize_reads_same_param_names(self):
        js = MODAL_JS.read_text(encoding="utf-8")
        restore_fn = js.split("function restoreFiltersFromQueryString")[1].split(
            "\nfunction "
        )[0]
        for param in FILTER_PARAMS:
            assert param in restore_fn, (
                f"Filter param {param} not read in deserialization"
            )

    def test_build_url_cleans_old_filter_params(self):
        """buildShareFilterURL should remove old f_* params before merging."""
        js = MODAL_JS.read_text(encoding="utf-8")
        build_fn = js.split("function buildShareFilterURL")[1].split("\nfunction ")[0]
        for param in FILTER_PARAMS:
            assert f"'{param}'" in build_fn or f'"{param}"' in build_fn

    def test_query_string_restoration_triggers_apply(self):
        """Init should call applyFilters after restoring from QS."""
        js = INIT_JS.read_text(encoding="utf-8")
        assert "restoreFiltersFromQueryString" in js
        assert "applyFilters()" in js

    def test_build_url_includes_team_id_and_set_id(self):
        """buildShareFilterURL must ensure team_id and set_id in shared link."""
        js = MODAL_JS.read_text(encoding="utf-8")
        build_fn = js.split("function buildShareFilterURL")[1].split("\nfunction ")[0]
        assert "team_id" in build_fn
        assert "set_id" in build_fn


class TestTeamIdFromUrlPriority:
    """URL team_id must take precedence for shared links."""

    def test_get_team_id_from_page_reads_url_first(self):
        """test-case-set-integration getTeamIdFromPage should prioritize URL."""
        js = Path("app/static/js/test-case-set-integration.js").read_text(encoding="utf-8")
        assert "getUrlParam('team_id')" in js or 'getUrlParam("team_id")' in js
        assert "getTeamIdFromPage" in js

    def test_ensure_team_context_respects_url_team_id(self):
        """ensureTeamContext should use URL team_id when it differs from AppUtils."""
        js = Path("app/static/js/test-case-management/cache.js").read_text(encoding="utf-8")
        assert "urlTeamId" in js
        assert "getTeamIdForCache" in js


# ─── i18n completeness ───

class TestI18nKeys:
    def _load_locale(self, name):
        return json.loads((LOCALES_DIR / name).read_text(encoding="utf-8"))

    def test_share_filter_keys_in_all_locales(self):
        required_keys = [
            "generateLink",
            "generateLinkTooltip",
            "modalTitle",
            "noFilters",
        ]
        for locale_file in LOCALE_FILES:
            data = self._load_locale(locale_file)
            sf = data.get("testCaseSet", {}).get("shareFilter", {})
            for key in required_keys:
                assert key in sf, f"Missing key testCaseSet.shareFilter.{key} in {locale_file}"
                assert sf[key], f"Empty value for testCaseSet.shareFilter.{key} in {locale_file}"
