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