"""Tests for ``app.services.assistant.deep_links.build_deep_links``.

Covers each tool name in ``_LINK_RULES``, missing/invalid IDs, type validation,
URL encoding of special characters, and non-create tool names returning empty.
"""

from __future__ import annotations

from pathlib import Path
import sys

from app.services.assistant.deep_links import build_deep_links, build_list_deep_links

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestCreateTestCase:
    def test_basic(self):
        result = {"test_case_number": "TC001", "test_case_set_id": 5}
        links = build_deep_links("create_test_case", result, {})
        assert links == {"test_case": "/test-case-management?set_id=5&tc=TC001"}

    def test_special_chars_in_number(self):
        result = {"test_case_number": "TC 1&2", "test_case_set_id": 3}
        links = build_deep_links("create_test_case", result, {})
        assert "tc=TC%201%262" in links["test_case"]

    def test_missing_number(self):
        result = {"test_case_set_id": 5}
        links = build_deep_links("create_test_case", result, {})
        assert links == {}

    def test_missing_set_id(self):
        result = {"test_case_number": "TC001"}
        links = build_deep_links("create_test_case", result, {})
        assert links == {}


class TestCreateTestCaseSet:
    def test_basic(self):
        result = {"id": 10, "name": "Login"}
        links = build_deep_links("create_test_case_set", result, {})
        assert links == {"test_case_set": "/test-case-management?set_id=10"}

    def test_missing_id(self):
        links = build_deep_links("create_test_case_set", {"name": "X"}, {})
        assert links == {}

    def test_non_int_id(self):
        links = build_deep_links("create_test_case_set", {"id": "abc"}, {})
        assert links == {}


class TestCreateTestRunConfig:
    def test_basic(self):
        result = {"id": 42, "name": "Sprint 43"}
        links = build_deep_links("create_test_run_config", result, {})
        assert links == {"test_run": "/test-run-execution?config_id=42"}


class TestCreateTestRunSet:
    def test_basic(self):
        result = {"id": 7, "name": "Release 2.0"}
        links = build_deep_links("create_test_run_set", result, {})
        assert links == {"test_run_set": "/test-run-management?set_id=7"}


class TestRestartTestRun:
    def test_basic(self):
        result = {"new_config_id": 99, "mode": "failed"}
        links = build_deep_links("restart_test_run", result, {})
        assert links == {"test_run": "/test-run-execution?config_id=99"}

    def test_missing_new_config_id(self):
        links = build_deep_links("restart_test_run", {"mode": "all"}, {})
        assert links == {}


class TestBulkCreateTestCases:
    def test_basic_from_args(self):
        result = {"success": True, "created_count": 5}
        args = {"test_case_set_id": 12}
        links = build_deep_links("bulk_create_test_cases", result, args)
        assert links == {"test_case_set": "/test-case-management?set_id=12"}

    def test_missing_set_id_in_args(self):
        links = build_deep_links("bulk_create_test_cases", {"created_count": 5}, {})
        assert links == {}


class TestBulkCloneTestCases:
    def test_basic_from_args(self):
        args = {"test_case_set_id": 8}
        links = build_deep_links("bulk_clone_test_cases", {"created_count": 3}, args)
        assert links == {"test_case_set": "/test-case-management?set_id=8"}


class TestNonCreateTools:
    def test_unknown_tool(self):
        links = build_deep_links("list_test_cases", {"id": 1}, {})
        assert links == {}

    def test_update_tool(self):
        links = build_deep_links("update_test_case", {"id": 1}, {})
        assert links == {}

    def test_delete_tool(self):
        links = build_deep_links("delete_test_case", {}, {"record_id": "1"})
        assert links == {}


class TestEdgeCases:
    def test_none_result_payload(self):
        links = build_deep_links("create_test_case", None, {})
        assert links == {}

    def test_non_dict_result(self):
        links = build_deep_links("create_test_case", "not a dict", {})
        assert links == {}

    def test_none_id_value(self):
        links = build_deep_links("create_test_case_set", {"id": None}, {})
        assert links == {}

    def test_string_id_for_int_field(self):
        links = build_deep_links("create_test_case_set", {"id": "5"}, {})
        assert links == {"test_case_set": "/test-case-management?set_id=5"}

    def test_float_id_truncated(self):
        links = build_deep_links("create_test_case_set", {"id": 5.9}, {})
        assert links == {"test_case_set": "/test-case-management?set_id=5"}

    def test_empty_arguments(self):
        links = build_deep_links("bulk_create_test_cases", {"created_count": 1}, {})
        assert links == {}

    def test_url_is_relative(self):
        links = build_deep_links("create_test_run_config", {"id": 1}, {})
        assert links["test_run"].startswith("/")
        assert not links["test_run"].startswith("//")


class TestGetTestCase:
    def test_basic(self):
        result = {"test_case_number": "TC001", "test_case_set_id": 5}
        links = build_deep_links("get_test_case", result, {})
        assert links == {"test_case": "/test-case-management?set_id=5&tc=TC001"}

    def test_missing_set_id(self):
        links = build_deep_links("get_test_case", {"test_case_number": "TC001"}, {})
        assert links == {}


class TestGetTestCaseSet:
    def test_basic(self):
        links = build_deep_links("get_test_case_set", {"id": 3}, {})
        assert links == {"test_case_set": "/test-case-management?set_id=3"}


class TestGetTestRun:
    def test_basic(self):
        links = build_deep_links("get_test_run", {"id": 42}, {})
        assert links == {"test_run": "/test-run-execution?config_id=42"}


class TestGetTestRunSet:
    def test_basic(self):
        links = build_deep_links("get_test_run_set", {"id": 7}, {})
        assert links == {"test_run_set": "/test-run-management?set_id=7"}


class TestListDeepLinks:
    def test_list_test_cases_bare_list(self):
        payload = [
            {"test_case_number": "TC001", "test_case_set_id": 5},
            {"test_case_number": "TC002", "test_case_set_id": 5},
        ]
        injected = build_list_deep_links("list_test_cases", payload)
        assert injected is True
        assert payload[0]["_deep_links"] == {"test_case": "/test-case-management?set_id=5&tc=TC001"}
        assert payload[1]["_deep_links"] == {"test_case": "/test-case-management?set_id=5&tc=TC002"}

    def test_list_test_cases_envelope(self):
        payload = {
            "items": [
                {"test_case_number": "TC001", "test_case_set_id": 3},
            ],
            "total": 1,
        }
        injected = build_list_deep_links("list_test_cases", payload)
        assert injected is True
        assert payload["items"][0]["_deep_links"] == {"test_case": "/test-case-management?set_id=3&tc=TC001"}

    def test_list_test_case_sets(self):
        payload = [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]
        build_list_deep_links("list_test_case_sets", payload)
        assert payload[0]["_deep_links"] == {"test_case_set": "/test-case-management?set_id=1"}
        assert payload[1]["_deep_links"] == {"test_case_set": "/test-case-management?set_id=2"}

    def test_list_test_runs(self):
        payload = [{"id": 10, "name": "Run A"}]
        build_list_deep_links("list_test_runs", payload)
        assert payload[0]["_deep_links"] == {"test_run": "/test-run-execution?config_id=10"}

    def test_list_test_run_sets(self):
        payload = [{"id": 5, "name": "Set A"}]
        build_list_deep_links("list_test_run_sets", payload)
        assert payload[0]["_deep_links"] == {"test_run_set": "/test-run-management?set_id=5"}

    def test_list_test_run_items(self):
        payload = [{"id": 1, "config_id": 42, "title": "Case A"}]
        build_list_deep_links("list_test_run_items", payload)
        assert payload[0]["_deep_links"] == {"test_run": "/test-run-execution?config_id=42"}

    def test_non_list_tool_returns_false(self):
        payload = [{"id": 1}]
        assert build_list_deep_links("create_test_case", payload) is False

    def test_empty_list(self):
        payload = []
        assert build_list_deep_links("list_test_cases", payload) is False

    def test_item_missing_id_skipped(self):
        payload = [
            {"test_case_number": "TC001"},
            {"test_case_number": "TC002", "test_case_set_id": 5},
        ]
        injected = build_list_deep_links("list_test_cases", payload)
        assert injected is True
        assert "_deep_links" not in payload[0]
        assert payload[1]["_deep_links"] == {"test_case": "/test-case-management?set_id=5&tc=TC002"}

    def test_non_dict_items_skipped(self):
        payload = ["not a dict", 42, {"test_case_number": "TC001", "test_case_set_id": 1}]
        injected = build_list_deep_links("list_test_cases", payload)
        assert injected is True
        assert "_deep_links" not in payload[0]
        assert payload[2]["_deep_links"] == {"test_case": "/test-case-management?set_id=1&tc=TC001"}

    def test_none_payload(self):
        assert build_list_deep_links("list_test_cases", None) is False


class TestCreateTestCaseTempUploadId:
    """Tests for create_test_case temp_upload_id schema and injection."""

    def _get_create_test_case_tool(self):
        from app.services.assistant.tools_test_cases import TOOLS
        for tool in TOOLS:
            if tool.name == "create_test_case":
                return tool
        raise AssertionError("create_test_case tool not found")

    def test_temp_upload_id_in_schema(self):
        """create_test_case body_schema should include temp_upload_id."""
        tool = self._get_create_test_case_tool()
        body_schema = tool.body_schema
        assert "temp_upload_id" in body_schema.get("properties", {})

    def test_temp_upload_id_is_optional(self):
        """temp_upload_id should not be in required fields."""
        tool = self._get_create_test_case_tool()
        body_schema = tool.body_schema
        assert "temp_upload_id" not in body_schema.get("required", [])

    def test_temp_upload_id_type_is_string(self):
        """temp_upload_id should be string type."""
        tool = self._get_create_test_case_tool()
        body_schema = tool.body_schema
        prop = body_schema["properties"]["temp_upload_id"]
        assert prop["type"] == "string"


class TestGetTestCaseGlobal:
    """Tests for extend-assistant-deep-links-global: get_test_case_global rule."""

    def test_basic(self):
        result = {
            "team_id": 3,
            "set_id": 63,
            "test_case_number": "TCG-114460.030.060",
            "title": "X",
        }
        links = build_deep_links("get_test_case_global", result, {})
        assert links == {
            "test_case": "/test-case-management?team_id=3&set_id=63&tc=TCG-114460.030.060"
        }

    def test_missing_set_id(self):
        links = build_deep_links("get_test_case_global", {"team_id": 3, "test_case_number": "TC001"}, {})
        assert links == {}

    def test_missing_team_id(self):
        # team_id is required so the frontend does not fall back to the user's
        # session team, which can be wrong for cross-team deep links.
        links = build_deep_links("get_test_case_global", {"set_id": 5, "test_case_number": "TC001"}, {})
        assert links == {}

    def test_missing_test_case_number(self):
        links = build_deep_links("get_test_case_global", {"team_id": 3, "set_id": 5}, {})
        assert links == {}


class TestSearchTestCasesGlobalList:
    """Tests for search_test_cases_global {results:[...]} envelope rule."""

    def test_injects_per_item(self):
        payload = {
            "status": "success",
            "total": 2,
            "results": [
                {"team_id": 4, "test_case_number": "TC001", "set_id": 5, "title": "A"},
                {"team_id": 3, "test_case_number": "TC002", "set_id": 5, "title": "B"},
            ],
        }
        assert build_list_deep_links("search_test_cases_global", payload) is True
        assert payload["results"][0]["_deep_links"] == {
            "test_case": "/test-case-management?team_id=4&set_id=5&tc=TC001"
        }
        assert payload["results"][1]["_deep_links"] == {
            "test_case": "/test-case-management?team_id=3&set_id=5&tc=TC002"
        }

    def test_set_id_none_skips_item(self):
        payload = {
            "status": "success",
            "total": 2,
            "results": [
                {"team_id": 3, "test_case_number": "TC001", "set_id": 5, "title": "A"},
                {"team_id": 3, "test_case_number": "ORPHAN", "set_id": None, "title": "no set"},
            ],
        }
        build_list_deep_links("search_test_cases_global", payload)
        assert "_deep_links" in payload["results"][0]
        assert "_deep_links" not in payload["results"][1]

    def test_missing_team_id_skips_item(self):
        # Without team_id, frontend would fall back to the session team and may
        # land on the wrong team. Skip the link rather than mislead the user.
        payload = {
            "status": "success",
            "total": 1,
            "results": [
                {"test_case_number": "TC001", "set_id": 5, "title": "no team_id"},
            ],
        }
        build_list_deep_links("search_test_cases_global", payload)
        assert "_deep_links" not in payload["results"][0]

    def test_special_chars_in_number(self):
        payload = {
            "results": [
                {"team_id": 3, "test_case_number": "TCG 1&2", "set_id": 3, "title": "X"},
            ],
        }
        build_list_deep_links("search_test_cases_global", payload)
        assert "tc=TCG%201%262" in payload["results"][0]["_deep_links"]["test_case"]


class TestSearchKnowledgeList:
    """Tests for search_knowledge rule: entity_type filter + nested metadata."""

    def test_test_case_entity_gets_link(self):
        payload = {
            "status": "success",
            "fallback_recommended": False,
            "results": [
                {
                    "entity_type": "test_case",
                    "entity_id": "TCG-1",
                    "team_id": 3,
                    "title": "A",
                    "metadata": {"test_case_set_id": 3, "test_case_number": "TCG-1"},
                },
            ],
        }
        build_list_deep_links("search_knowledge", payload)
        assert payload["results"][0]["_deep_links"] == {
            "test_case": "/test-case-management?team_id=3&set_id=3&tc=TCG-1"
        }

    def test_non_test_case_entities_skipped(self):
        payload = {
            "results": [
                {"entity_type": "usm_node", "entity_id": "USM-1", "team_id": 3, "title": "X", "metadata": {}},
                {"entity_type": "jira_ticket", "entity_id": "JIRA-1", "team_id": 3, "title": "Y", "metadata": {}},
            ],
        }
        build_list_deep_links("search_knowledge", payload)
        for item in payload["results"]:
            assert "_deep_links" not in item

    def test_mixed_entities_only_test_case_linked(self):
        payload = {
            "results": [
                {"entity_type": "usm_node", "entity_id": "USM-1", "team_id": 3, "metadata": {}},
                {
                    "entity_type": "test_case",
                    "entity_id": "TCG-2",
                    "team_id": 4,
                    "metadata": {"test_case_set_id": 7, "test_case_number": "TCG-2"},
                },
            ],
        }
        build_list_deep_links("search_knowledge", payload)
        assert "_deep_links" not in payload["results"][0]
        assert payload["results"][1]["_deep_links"] == {
            "test_case": "/test-case-management?team_id=4&set_id=7&tc=TCG-2"
        }

    def test_test_case_without_metadata_skipped(self):
        payload = {
            "results": [
                {"entity_type": "test_case", "entity_id": "TCG-9", "team_id": 3, "title": "X"},
            ],
        }
        build_list_deep_links("search_knowledge", payload)
        assert "_deep_links" not in payload["results"][0]

    def test_test_case_without_top_level_team_id_skipped(self):
        payload = {
            "results": [
                {
                    "entity_type": "test_case",
                    "entity_id": "TCG-1",
                    "metadata": {"test_case_set_id": 3, "test_case_number": "TCG-1"},
                },
            ],
        }
        build_list_deep_links("search_knowledge", payload)
        assert "_deep_links" not in payload["results"][0]


class TestResultsEnvelope:
    """Generic {results:[...]} envelope support in build_list_deep_links."""

    def test_results_key_recognized(self):
        payload = {"status": "ok", "results": [{"team_id": 3, "test_case_number": "X", "set_id": 1, "title": "t"}]}
        # search_test_cases_global rule applies; verifies envelope handler picks up
        # the list even when not called via a known tool.
        assert build_list_deep_links("search_test_cases_global", payload) is True

    def test_no_results_no_items_returns_false(self):
        payload = {"status": "ok"}
        assert build_list_deep_links("search_test_cases_global", payload) is False


class TestDottedPathResolution:
    """_build_single / _resolve_field dotted-path support."""

    def test_flat_still_works(self):
        links = build_deep_links("get_test_case", {"test_case_set_id": 5, "test_case_number": "TC001"}, {})
        assert links == {"test_case": "/test-case-management?set_id=5&tc=TC001"}

    def test_dotted_metadata_resolved(self):
        from app.services.assistant.deep_links import _resolve_field, _build_single
        src = {"metadata": {"test_case_set_id": 9, "test_case_number": "TCG-9"}}
        assert _resolve_field(src, "metadata.test_case_set_id") == 9
        assert _resolve_field(src, "metadata.test_case_number") == "TCG-9"
        assert _resolve_field(src, "metadata.missing") is None
        result = _build_single(
            "test_case",
            "/test-case-management?set_id={set_id}&tc={tc}",
            {"set_id": "metadata.test_case_set_id", "tc": "metadata.test_case_number"},
            src,
        )
        assert result == {"test_case": "/test-case-management?set_id=9&tc=TCG-9"}

    def test_dotted_through_non_dict_returns_none(self):
        from app.services.assistant.deep_links import _resolve_field
        # metadata is a list, not a dict → resolve must return None, not raise.
        assert _resolve_field({"metadata": []}, "metadata.foo") is None
        assert _resolve_field({"metadata": "str"}, "metadata.foo") is None


class TestHistoryCompactionResultsEnvelope:
    """history_builder._struct_compact_tool_content must preserve _deep_links
    for the {results:[...]} envelope (used by search_test_cases_global /
    search_knowledge)."""

    def test_results_envelope_preserves_sampled_links(self):
        import json as _json
        from app.services.assistant.history_builder import _struct_compact_tool_content
        data = {
            "status": "success",
            "total": 2,
            "truncated": False,
            "source_count": 2,
            "returned_count": 2,
            "results": [
                {
                    "test_case_number": "TC001",
                    "set_id": 5,
                    "_deep_links": {"test_case": "/test-case-management?set_id=5&tc=TC001"},
                },
                {
                    "test_case_number": "TC002",
                    "set_id": 5,
                    "_deep_links": {"test_case": "/test-case-management?set_id=5&tc=TC002"},
                },
            ],
        }
        compacted = _json.loads(_struct_compact_tool_content(_json.dumps(data, ensure_ascii=False)))
        assert compacted["compacted"] is True
        assert compacted["source_count"] == 2
        assert compacted["id_sample"] == ["TC001", "TC002"]
        assert compacted["_deep_links"] == {"test_case": "/test-case-management?set_id=5&tc=TC001"}
