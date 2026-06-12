import json
from dataclasses import dataclass

import pytest
from sqlalchemy import select

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationScript,
    AutomationScriptFormat,
    AutomationSmartScanStatus,
    Team,
    TeamAutomationProvider,
)
from app.services.automation.smart_scan_service import (
    SmartScanError,
    SmartScanService,
    _extract_test_entries,
    _resolve_scan_config,
    create_smart_scan_run,
    smart_scan_result_to_dict,
)
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


@dataclass
class _ScriptContent:
    content: str


class _FakeStorage:
    def __init__(self, manifest_content: str | None) -> None:
        self.manifest_content = manifest_content

    async def read_script(self, path: str, ref: str | None = None, etag: str | None = None):
        if self.manifest_content is None:
            raise FileNotFoundError(path)
        return _ScriptContent(content=self.manifest_content)


@pytest.fixture
def smart_scan_db(tmp_path):
    bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = bundle["sync_session_factory"]
    AsyncSessionLocal = bundle["async_session_factory"]

    with SyncSessionLocal() as session:
        team = Team(name="QA", description="", wiki_token="t", test_case_table_id="tbl")
        session.add(team)
        session.commit()

        storage = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps({"owner": "x", "repo": "y", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add(storage)
        session.commit()

        scripts = [
            AutomationScript(
                team_id=team.id, provider_id=storage.id,
                name="test_login.py", script_format=AutomationScriptFormat.PYTEST,
                ref_path="tests/auth/test_login.py", ref_branch="main", tags_json="[]",
                cached_content="def test_login():\n    assert True\n",
            ),
            AutomationScript(
                team_id=team.id, provider_id=storage.id,
                name="test_logout.py", script_format=AutomationScriptFormat.PYTEST,
                ref_path="tests/auth/test_logout.py", ref_branch="main", tags_json="[]",
                cached_content="async def test_logout():\n    assert True\n",
            ),
            AutomationScript(
                team_id=team.id, provider_id=storage.id,
                name="test_search.py", script_format=AutomationScriptFormat.PYTEST,
                ref_path="tests/search/test_search.py", ref_branch="main", tags_json="[]",
                cached_content="class TestSearch:\n    def test_keyword(self):\n        assert True\n",
            ),
            AutomationScript(
                team_id=team.id, provider_id=storage.id,
                name="login_page.py", script_format=AutomationScriptFormat.PLAYWRIGHT_PY_ASYNC,
                ref_path="pages/login_page.py", ref_branch="main", tags_json="[]",
            ),
            AutomationScript(
                team_id=team.id, provider_id=storage.id,
                name="users.yaml", script_format=AutomationScriptFormat.OTHER,
                ref_path="resources/data/users.yaml", ref_branch="main", tags_json="[]",
            ),
        ]
        session.add_all(scripts)
        session.commit()

        ids = {"team_id": team.id}

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal}
    dispose_managed_test_database(bundle)


@pytest.mark.asyncio
async def test_scan_proposes_one_suite_per_subdirectory(smart_scan_db, monkeypatch):
    ids = smart_scan_db["ids"]
    fake = _FakeStorage(manifest_content=None)

    # Stub the storage provider lookup so we don't need real credentials
    async def _load(self, team_id):
        # Return a stub provider record + our fake storage
        result = await self.session.execute(
            select(TeamAutomationProvider).where(TeamAutomationProvider.team_id == team_id)
        )
        record = result.scalars().first()
        return record, fake

    monkeypatch.setattr(SmartScanService, "_load_storage_provider", _load)

    async with smart_scan_db["async_sessionmaker"]() as session:
        service = SmartScanService(session)
        result = await service.scan(team_id=ids["team_id"])

    # 3 test files under tests/auth/ + tests/search/ → 2 proposals (auth, search)
    assert len(result.entry_points) == 3
    assert len(result.scan_config_hash) == 64
    proposals = {p.name: p for p in result.proposals}
    assert "Auth Suite" in proposals
    assert "Search Suite" in proposals
    assert sorted(proposals["Auth Suite"].script_paths) == [
        "tests/auth/test_login.py",
        "tests/auth/test_logout.py",
    ]
    # Non-test files excluded
    excluded_paths = {item["ref_path"] for item in result.excluded}
    assert "pages/login_page.py" in excluded_paths
    assert "resources/data/users.yaml" in excluded_paths


@pytest.mark.asyncio
async def test_scan_validates_repo_contract(smart_scan_db, monkeypatch):
    ids = smart_scan_db["ids"]
    fake = _FakeStorage(manifest_content="paths:\n  tests: tests/\nscan:\n  scan_path: tests/")

    async def _load(self, team_id):
        result = await self.session.execute(
            select(TeamAutomationProvider).where(TeamAutomationProvider.team_id == team_id)
        )
        return result.scalars().first(), fake

    monkeypatch.setattr(SmartScanService, "_load_storage_provider", _load)

    async with smart_scan_db["async_sessionmaker"]() as session:
        service = SmartScanService(session)
        result = await service.scan(team_id=ids["team_id"])

    contract = result.contract
    assert contract.manifest_found is True
    assert "tests" in contract.standard_paths_present
    assert "pages" in contract.standard_paths_present
    assert "resources" in contract.standard_paths_present
    # support paths surface the support directories present
    pages_label = next((s for s in contract.support_paths if s["path"] == "pages"), None)
    assert pages_label is not None
    assert pages_label["label"] == "Page Objects"
    assert contract.effective_tests_path == "tests/"


@pytest.mark.asyncio
async def test_scan_raises_when_no_storage_provider(smart_scan_db):
    """Scan must fail clearly when the team has no active Storage provider."""

    bundle = smart_scan_db
    async with bundle["async_sessionmaker"]() as session:
        # Deactivate the provider
        result = await session.execute(select(TeamAutomationProvider))
        provider = result.scalars().first()
        provider.is_active = False
        await session.flush()

        service = SmartScanService(session)
        with pytest.raises(SmartScanError):
            await service.scan(team_id=bundle["ids"]["team_id"])


@pytest.mark.asyncio
async def test_scan_flat_layout_groups_into_single_full_regression(smart_scan_db, monkeypatch):
    """A repo with test files directly under tests/ (no subdirs) yields one suite."""
    ids = smart_scan_db["ids"]
    fake = _FakeStorage(manifest_content=None)

    async def _load(self, team_id):
        result = await self.session.execute(
            select(TeamAutomationProvider).where(TeamAutomationProvider.team_id == team_id)
        )
        return result.scalars().first(), fake

    monkeypatch.setattr(SmartScanService, "_load_storage_provider", _load)

    async with smart_scan_db["async_sessionmaker"]() as session:
        # Replace test paths with flat layout
        result = await session.execute(select(AutomationScript))
        for script in result.scalars().all():
            if script.ref_path.startswith("tests/"):
                # Flatten: move from tests/foo/test_x.py to tests/test_x.py
                script.ref_path = "tests/" + script.ref_path.rsplit("/", 1)[-1]
        await session.flush()

        service = SmartScanService(session)
        result = await service.scan(team_id=ids["team_id"])

    assert len(result.proposals) == 1
    assert result.proposals[0].name == "Full Regression"
    assert len(result.proposals[0].script_paths) == 3


@pytest.mark.asyncio
async def test_scan_filters_python_false_positive_by_ast(smart_scan_db, monkeypatch):
    ids = smart_scan_db["ids"]
    fake = _FakeStorage(manifest_content=None)

    async def _load(self, team_id):
        result = await self.session.execute(
            select(TeamAutomationProvider).where(TeamAutomationProvider.team_id == team_id)
        )
        return result.scalars().first(), fake

    monkeypatch.setattr(SmartScanService, "_load_storage_provider", _load)

    async with smart_scan_db["async_sessionmaker"]() as session:
        result = await session.execute(select(AutomationScript).where(AutomationScript.name == "test_search.py"))
        script = result.scalars().one()
        script.name = "test_data_builder.py"
        script.ref_path = "tests/auth/test_data_builder.py"
        script.cached_content = "def build_login_user():\n    return {'name': 'qa'}\n"
        await session.flush()

        service = SmartScanService(session)
        scan = await service.scan(team_id=ids["team_id"])

    assert "tests/auth/test_data_builder.py" not in {ep.ref_path for ep in scan.entry_points}
    excluded = {item["ref_path"]: item["reason"] for item in scan.excluded}
    assert excluded["tests/auth/test_data_builder.py"] == "false_positive"


@pytest.mark.asyncio
async def test_create_smart_scan_run_persists_queued_state(smart_scan_db):
    ids = smart_scan_db["ids"]

    async with smart_scan_db["async_sessionmaker"]() as session:
        run = await create_smart_scan_run(session, team_id=ids["team_id"], actor="42")
        await session.flush()

    assert run.id > 0
    assert AutomationSmartScanStatus(run.status) == AutomationSmartScanStatus.QUEUED
    assert len(run.scan_config_hash) == 64
    assert json.loads(run.progress_json) == {"step": "queued", "complete": 0, "total": 3}
    assert run.created_by == "42"


# ---------------------------------------------------------------------------
# Marker parser unit tests (Section 1 — pure functions, no DB).
# ---------------------------------------------------------------------------


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


def test_resolve_scan_config_reads_canonical_scan_include_exclude():
    """Unified contract: smart-scan honors the same glob `scan.include`/`exclude`
    keys that script sync uses, so one manifest block drives both stages."""
    manifest = {
        "paths": {"tests": "tests/"},
        "scan": {
            "include": ["test_*.py", "flow_*.py"],
            "exclude": ["*/pages/*"],
        },
    }
    config = _resolve_scan_config(manifest, {})
    assert config["scan_path"] == "tests/"
    assert config["include_patterns"] == ["test_*.py", "flow_*.py"]
    assert config["exclude_patterns"] == ["*/pages/*"]


def test_resolve_scan_config_accepts_patterns_alias():
    """Legacy `include_patterns`/`exclude_patterns` keys still work as aliases."""
    manifest = {"scan": {"include_patterns": ["flow_*.py"], "exclude_patterns": ["*/utils/*"]}}
    config = _resolve_scan_config(manifest, {})
    assert config["include_patterns"] == ["flow_*.py"]
    assert config["exclude_patterns"] == ["*/utils/*"]


@pytest.mark.asyncio
async def test_scan_response_exposes_test_entries_with_marker_links(
    smart_scan_db, monkeypatch
):
    """Smart Scan surfaces marker links and warnings on the public payload."""
    ids = smart_scan_db["ids"]
    fake = _FakeStorage(manifest_content=None)

    async def _load(self, team_id):
        result = await self.session.execute(
            select(TeamAutomationProvider).where(TeamAutomationProvider.team_id == team_id)
        )
        return result.scalars().first(), fake

    monkeypatch.setattr(SmartScanService, "_load_storage_provider", _load)

    # Replace one of the cached_content blobs with marker-bearing source.
    async with smart_scan_db["async_sessionmaker"]() as session:
        script_result = await session.execute(
            select(AutomationScript).where(AutomationScript.name == "test_login.py")
        )
        script = script_result.scalars().one()
        script.cached_content = (
            "import pytest\n"
            "\n"
            "@pytest.mark.tcrt(\"TC-001\", link_type=\"primary\")\n"
            "def test_login():\n"
            "    \"\"\"Happy path login.\"\"\"\n"
            "    assert True\n"
            "\n"
            "@pytest.mark.tcrt(\"TC 999 bad\")\n"  # invalid TC format → warning
            "def test_login_bad_marker():\n"
            "    assert True\n"
        )
        await session.flush()

        service = SmartScanService(session)
        result = await service.scan(team_id=ids["team_id"])

    payload = smart_scan_result_to_dict(result)
    login_entry = next(
        ep for ep in payload["entry_points"]
        if ep["ref_path"] == "tests/auth/test_login.py"
    )
    # Back-compat: test_names still populated.
    assert "test_login" in login_entry["test_names"]
    test_entries = {entry["name"]: entry for entry in login_entry["test_entries"]}
    assert test_entries["test_login"]["docstring"] == "Happy path login."
    # Markers are exposed (TCRT Automation Hub Test view consumes these).
    assert test_entries["test_login"]["markers"] == [
        {
            "tc_ids": ["TC-001"],
            "link_type": "primary",
            "source_line": test_entries["test_login"]["markers"][0]["source_line"],
            "raw": test_entries["test_login"]["markers"][0]["raw"],
        }
    ]
    # Invalid TC format emits an `invalid_tc_format` warning.
    warning_types = {w["type"] for w in login_entry["marker_warnings"]}
    assert "invalid_tc_format" in warning_types
