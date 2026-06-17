"""Marker parser unit tests (pure functions, no DB).

Covers `_extract_test_entries` — test-entry detection + `@pytest.mark.tcrt(...)`
parsing — which backs script sync's marker reconcile and the Suites Test view.
"""

from app.services.automation.marker_parse import _extract_test_entries


def _entries_by_name(entries):
    return {entry.name: entry for entry in entries}


def test_marker_parser_python_single_tc():
    content = (
        "import pytest\n"
        "\n"
        "@pytest.mark.tcrt(\"TC-001\")\n"
        "def test_login_happy():\n"
        "    assert True\n"
    )
    entries, warnings = _extract_test_entries("tests/test_login.py", content)
    assert warnings == []
    entry = _entries_by_name(entries)["test_login_happy"]
    assert entry.kind == "function"
    assert len(entry.markers) == 1
    marker = entry.markers[0]
    assert marker.tc_ids == ["TC-001"]
    assert marker.link_type == "covers"
    assert marker.source_line == 3


def test_marker_parser_python_multi_tc_with_link_type():
    content = (
        "import pytest\n"
        "\n"
        "@pytest.mark.tcrt(\"TC-001\", \"TC-005\", link_type=\"primary\")\n"
        "def test_login_critical():\n"
        "    \"\"\"Verifies primary login flow.\"\"\"\n"
        "    pass\n"
    )
    entries, warnings = _extract_test_entries("tests/test_login.py", content)
    assert warnings == []
    entry = _entries_by_name(entries)["test_login_critical"]
    assert entry.docstring == "Verifies primary login flow."
    assert len(entry.markers) == 1
    assert entry.markers[0].tc_ids == ["TC-001", "TC-005"]
    assert entry.markers[0].link_type == "primary"


def test_marker_parser_python_stacked_markers():
    content = (
        "import pytest\n"
        "\n"
        "@pytest.mark.tcrt(\"TC-001\", link_type=\"primary\")\n"
        "@pytest.mark.tcrt(\"TC-005\")\n"
        "def test_login_mixed():\n"
        "    pass\n"
    )
    entries, warnings = _extract_test_entries("tests/test_login.py", content)
    assert warnings == []
    entry = _entries_by_name(entries)["test_login_mixed"]
    assert {(tuple(m.tc_ids), m.link_type) for m in entry.markers} == {
        (("TC-001",), "primary"),
        (("TC-005",), "covers"),
    }


def test_marker_parser_python_non_literal_argument_warns():
    content = (
        "import pytest\n"
        "\n"
        "MY_TC = \"TC-001\"\n"
        "@pytest.mark.tcrt(MY_TC)\n"
        "def test_login(): pass\n"
    )
    entries, warnings = _extract_test_entries("tests/test_login.py", content)
    entry = _entries_by_name(entries)["test_login"]
    assert entry.markers == []
    assert any(w["type"] == "non_literal_marker" for w in warnings)


def test_marker_parser_python_invalid_link_type_warns():
    content = (
        "import pytest\n"
        "\n"
        "@pytest.mark.tcrt(\"TC-001\", link_type=\"bogus\")\n"
        "def test_login(): pass\n"
    )
    entries, warnings = _extract_test_entries("tests/test_login.py", content)
    entry = _entries_by_name(entries)["test_login"]
    assert entry.markers == []
    assert any(w["type"] == "invalid_link_type" and w["value"] == "bogus" for w in warnings)


def test_marker_parser_python_invalid_tc_format_warns():
    content = (
        "import pytest\n"
        "\n"
        "@pytest.mark.tcrt(\"TC 001\")\n"
        "def test_login(): pass\n"
    )
    entries, warnings = _extract_test_entries("tests/test_login.py", content)
    entry = _entries_by_name(entries)["test_login"]
    assert entry.markers == []
    assert any(w["type"] == "invalid_tc_format" and w["tc_id"] == "TC 001" for w in warnings)


def test_marker_parser_python_class_level_marker():
    content = (
        "import pytest\n"
        "\n"
        "@pytest.mark.tcrt(\"TC-010\")\n"
        "class TestCheckout:\n"
        "    def test_cart(self):\n"
        "        pass\n"
    )
    entries, warnings = _extract_test_entries("tests/test_checkout.py", content)
    assert warnings == []
    by_name = _entries_by_name(entries)
    assert by_name["TestCheckout"].kind == "class"
    assert by_name["TestCheckout"].markers[0].tc_ids == ["TC-010"]
    # Inner test_cart picks up nothing of its own
    assert by_name["test_cart"].markers == []


def test_marker_parser_python_syntax_error_fail_open():
    content = "def test_oops(:\n"  # broken syntax
    entries, warnings = _extract_test_entries("tests/test_broken.py", content)
    assert entries == []
    assert any(w["type"] == "parse_error" for w in warnings)
