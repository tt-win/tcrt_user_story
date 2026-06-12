import json

import pytest
from sqlalchemy import select

from app.models.database_models import (
    AutomationProviderSlot,
    AutomationScript,
    AutomationScriptCaseLink,
    AutomationScriptFormat,
    AutomationScriptLinkType,
    Team,
    TeamAutomationProvider,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
)
from app.services.automation.providers.base import ScriptContent, ScriptRef
from app.services.automation.script_service import (
    AutomationScriptService,
    MARKER_SYNC_CREATED_BY,
    build_marker_note,
    is_ai_suggest_link,
    is_marker_sync_link,
    parse_ai_suggest_user_id,
    parse_marker_note,
    script_to_dict,
)
from app.testsuite.db_test_helpers import create_managed_test_database, dispose_managed_test_database


class FakeStorageProvider:
    def __init__(
        self,
        *,
        manifest: str | None = None,
        scripts: list[ScriptRef] | None = None,
        contents: dict[str, ScriptContent] | None = None,
    ) -> None:
        self.manifest = manifest
        self.scripts = scripts or []
        self.contents = contents or {}
        self.list_calls: list[tuple[str, str | None, bool]] = []

    async def list_scripts(self, path: str, ref: str | None = None, recursive: bool = True) -> list[ScriptRef]:
        self.list_calls.append((path, ref, recursive))
        return self.scripts

    async def read_script(self, path: str, ref: str | None = None, etag: str | None = None) -> ScriptContent:
        if path == "tcrt-automation.yml":
            if self.manifest is None:
                raise FileNotFoundError(path)
            return ScriptContent(path=path, content=self.manifest, etag="manifest-sha", ref=ref)
        content = self.contents[path]
        if etag and etag == content.etag:
            return ScriptContent(path=path, content="", etag=etag, ref=ref, not_modified=True)
        return content


class _RepoFake:
    """A single-repo view used by MultiRepoFakeStorage's fan-out."""

    def __init__(self, slug: str, scripts: list[ScriptRef]) -> None:
        self.active_repo_slug = slug
        self.default_ref = "main"
        self._scripts = scripts

    async def list_scripts(self, path: str, ref: str | None = None, recursive: bool = True) -> list[ScriptRef]:
        return list(self._scripts)

    async def read_script(self, path: str, ref: str | None = None, etag: str | None = None) -> ScriptContent:
        # No manifest → repo contract falls back to the provider's scan_path.
        raise FileNotFoundError(path)


class MultiRepoFakeStorage:
    """Fake GitHub-style provider holding several repos (exposes fan-out)."""

    def __init__(self, repo_scripts: dict[str, list[ScriptRef]]) -> None:
        self._repo_scripts = repo_scripts

    def iter_repo_providers(self) -> list[_RepoFake]:
        return [_RepoFake(slug, scripts) for slug, scripts in self._repo_scripts.items()]


@pytest.fixture
def automation_script_db(tmp_path):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = database_bundle["sync_session_factory"]
    AsyncSessionLocal = database_bundle["async_session_factory"]

    with SyncSessionLocal() as session:
        team = Team(
            name="QA Team",
            description="",
            wiki_token="wiki-token",
            test_case_table_id="tbl-test",
        )
        session.add(team)
        session.commit()

        provider = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps(
                {
                    "owner": "example",
                    "repo": "automation",
                    "default_branch": "main",
                    "scan_path": "fallback-tests/",
                    "smart_scan": {"use_manifest": True},
                }
            ),
            credentials_encrypted=None,
            is_active=True,
        )
        session.add(provider)
        session.commit()
        team_id = team.id
        provider_id = provider.id

    yield {
        "team_id": team_id,
        "provider_id": provider_id,
        "async_sessionmaker": AsyncSessionLocal,
    }

    dispose_managed_test_database(database_bundle)


@pytest.mark.asyncio
async def test_sync_scripts_uses_manifest_tests_path_and_excludes_support_files(automation_script_db):
    manifest = """
version: 1
framework: pytest
paths:
  tests: tests/
  pages: pages/
  flows: flows/
  fixtures: fixtures/
  resources: resources/
  config: config/
scan:
  include:
    - "test_*.py"
  exclude:
    - "*/pages/*"
    - "*/resources/*"
"""
    provider = FakeStorageProvider(
        manifest=manifest,
        scripts=[
            ScriptRef(
                path="tests/auth/test_login.py",
                name="test_login.py",
                script_format="PYTEST",
                ref="main",
                etag="a1",
            ),
            ScriptRef(
                path="tests/pages/login_page.py",
                name="login_page.py",
                script_format="OTHER",
                ref="main",
                etag="p1",
            ),
            ScriptRef(
                path="tests/resources/users.yaml",
                name="users.yaml",
                script_format="OTHER",
                ref="main",
                etag="r1",
            ),
        ],
    )

    async with automation_script_db["async_sessionmaker"]() as session:
        service = AutomationScriptService(session)
        summary = await service.sync_scripts(
            team_id=automation_script_db["team_id"],
            provider_id=automation_script_db["provider_id"],
            actor="1",
            storage_provider=provider,
        )
        await session.commit()

        rows = list((await session.execute(select(AutomationScript))).scalars().all())

    assert provider.list_calls == [("tests/", "main", True)]
    assert summary.added == 1
    assert summary.total == 1
    assert summary.repo_contract.manifest_found is True
    assert summary.repo_contract.contract_status == "VALID"
    assert [row.ref_path for row in rows] == ["tests/auth/test_login.py"]
    assert rows[0].script_format == AutomationScriptFormat.PYTEST


@pytest.mark.asyncio
async def test_sync_scripts_falls_back_to_provider_scan_path_when_manifest_missing(automation_script_db):
    provider = FakeStorageProvider(
        scripts=[
            ScriptRef(
                path="fallback-tests/test_login.py",
                name="test_login.py",
                script_format="PYTEST",
                ref="main",
                etag="a1",
            )
        ],
    )

    async with automation_script_db["async_sessionmaker"]() as session:
        service = AutomationScriptService(session)
        summary = await service.sync_scripts(
            team_id=automation_script_db["team_id"],
            provider_id=automation_script_db["provider_id"],
            storage_provider=provider,
        )

    assert provider.list_calls == [("fallback-tests/", "main", True)]
    assert summary.repo_contract.manifest_found is False
    assert summary.repo_contract.contract_status == "MISSING"
    assert summary.scanned_path == "fallback-tests/"


def test_script_to_dict_serializes_test_entries_with_markers():
    """List endpoint surfaces test entries with their marker metadata."""
    script = AutomationScript(
        team_id=1,
        provider_id=1,
        name="test_login.py",
        script_format=AutomationScriptFormat.PYTEST,
        ref_path="tests/api/test_login.py",
        ref_branch="main",
        tags_json="[]",
        cached_content=(
            "import pytest\n\n"
            '@pytest.mark.tcrt("TC-1", link_type="primary")\n'
            "def test_login():\n    assert True\n"
        ),
    )
    data = script_to_dict(script)
    assert len(data["test_entries"]) == 1
    entry = data["test_entries"][0]
    assert entry["name"] == "test_login"
    assert entry["markers"] == [
        {
            "tc_ids": ["TC-1"],
            "link_type": "primary",
            "source_line": entry["markers"][0]["source_line"],
            "raw": entry["markers"][0]["raw"],
        }
    ]
    assert data["marker_warnings"] == []


def test_script_to_dict_empty_test_entries_without_content():
    script = AutomationScript(
        team_id=1,
        provider_id=1,
        name="test_login.py",
        script_format=AutomationScriptFormat.PYTEST,
        ref_path="tests/api/test_login.py",
        ref_branch="main",
        tags_json="[]",
        cached_content=None,
    )
    data = script_to_dict(script)
    assert data["test_entries"] == []
    assert data["marker_warnings"] == []


@pytest.mark.asyncio
async def test_sync_scripts_fetch_content_populates_cached_content(automation_script_db):
    """fetch_content=True caches the body so markers can be parsed on read."""
    provider = FakeStorageProvider(
        scripts=[
            ScriptRef(
                path="fallback-tests/test_login.py",
                name="test_login.py",
                script_format="PYTEST",
                ref="main",
                etag="a1",
            )
        ],
        contents={
            "fallback-tests/test_login.py": ScriptContent(
                path="fallback-tests/test_login.py",
                content='import pytest\n\n@pytest.mark.tcrt("TC-1")\ndef test_login():\n    assert True\n',
                etag="a1",
                ref="main",
            )
        },
    )

    async with automation_script_db["async_sessionmaker"]() as session:
        service = AutomationScriptService(session)
        await service.sync_scripts(
            team_id=automation_script_db["team_id"],
            provider_id=automation_script_db["provider_id"],
            actor="1",
            storage_provider=provider,
            fetch_content=True,
        )
        await session.commit()
        row = (await session.execute(select(AutomationScript))).scalars().one()

    assert row.cached_content is not None
    assert "pytest.mark.tcrt" in row.cached_content
    assert script_to_dict(row)["test_entries"][0]["markers"] == [
        {
            "tc_ids": ["TC-1"],
            "link_type": "covers",
            "source_line": script_to_dict(row)["test_entries"][0]["markers"][0]["source_line"],
            "raw": script_to_dict(row)["test_entries"][0]["markers"][0]["raw"],
        }
    ]


@pytest.mark.asyncio
async def test_sync_scripts_deletes_cache_rows_missing_from_repo(automation_script_db):
    provider = FakeStorageProvider(
        scripts=[
            ScriptRef(
                path="fallback-tests/test_login.py",
                name="test_login.py",
                script_format="PYTEST",
                ref="main",
                etag="a1",
            )
        ],
    )

    async with automation_script_db["async_sessionmaker"]() as session:
        service = AutomationScriptService(session)
        await service.sync_scripts(
            team_id=automation_script_db["team_id"],
            provider_id=automation_script_db["provider_id"],
            storage_provider=provider,
        )
        provider.scripts = []
        summary = await service.sync_scripts(
            team_id=automation_script_db["team_id"],
            provider_id=automation_script_db["provider_id"],
            storage_provider=provider,
        )
        await session.commit()

        remaining = list((await session.execute(select(AutomationScript))).scalars().all())

    assert summary.removed == 1
    assert remaining == []


@pytest.mark.asyncio
async def test_sync_scripts_fans_out_over_repos_and_tags_ref_repo(automation_script_db):
    """One provider holding two repos discovers + tags scripts per repo, even
    when both repos share the same ref_path (uniqueness now includes ref_repo)."""
    shared_path = "fallback-tests/test_login.py"
    provider = MultiRepoFakeStorage(
        {
            "acme/web": [ScriptRef(path=shared_path, name="test_login.py", script_format="PYTEST", ref="main", etag="w1")],
            "acme/api": [ScriptRef(path=shared_path, name="test_login.py", script_format="PYTEST", ref="main", etag="a1")],
        }
    )
    async with automation_script_db["async_sessionmaker"]() as session:
        service = AutomationScriptService(session)
        summary = await service.sync_scripts(
            team_id=automation_script_db["team_id"],
            provider_id=automation_script_db["provider_id"],
            storage_provider=provider,
        )
        await session.commit()
        rows = list((await session.execute(select(AutomationScript))).scalars().all())

    assert summary.added == 2
    assert {row.ref_repo: row.ref_path for row in rows} == {
        "acme/web": shared_path,
        "acme/api": shared_path,
    }


@pytest.mark.asyncio
async def test_sync_single_content_uses_etag_and_updates_cached_content(automation_script_db):
    async with automation_script_db["async_sessionmaker"]() as session:
        script = AutomationScript(
            team_id=automation_script_db["team_id"],
            provider_id=automation_script_db["provider_id"],
            name="test_login.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_login.py",
            ref_branch="main",
            cached_content="old",
            cached_content_etag="old-etag",
            tags_json="[]",
        )
        session.add(script)
        await session.flush()

        provider = FakeStorageProvider(
            contents={
                "tests/test_login.py": ScriptContent(
                    path="tests/test_login.py",
                    content="def test_login():\n    assert True\n",
                    etag="new-etag",
                    ref="main",
                )
            }
        )
        service = AutomationScriptService(session)
        refreshed = await service.sync_single_content(
            team_id=automation_script_db["team_id"],
            script_id=script.id,
            storage_provider=provider,
        )

    assert refreshed.cached_content == "def test_login():\n    assert True\n"
    assert refreshed.cached_content_etag == "new-etag"


@pytest.mark.asyncio
async def test_sync_single_content_keeps_cached_content_when_not_modified(automation_script_db):
    async with automation_script_db["async_sessionmaker"]() as session:
        script = AutomationScript(
            team_id=automation_script_db["team_id"],
            provider_id=automation_script_db["provider_id"],
            name="test_login.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_login.py",
            ref_branch="main",
            cached_content="old",
            cached_content_etag="same-etag",
            tags_json="[]",
        )
        session.add(script)
        await session.flush()

        provider = FakeStorageProvider(
            contents={
                "tests/test_login.py": ScriptContent(
                    path="tests/test_login.py",
                    content="new content should not be used",
                    etag="same-etag",
                    ref="main",
                )
            }
        )
        service = AutomationScriptService(session)
        refreshed = await service.sync_single_content(
            team_id=automation_script_db["team_id"],
            script_id=script.id,
            storage_provider=provider,
        )

    assert refreshed.cached_content == "old"
    assert refreshed.cached_content_etag == "same-etag"


@pytest.mark.asyncio
async def test_update_metadata_and_delete_script_cache_do_not_touch_repo(automation_script_db):
    async with automation_script_db["async_sessionmaker"]() as session:
        script = AutomationScript(
            team_id=automation_script_db["team_id"],
            provider_id=automation_script_db["provider_id"],
            name="test_login.py",
            script_format=AutomationScriptFormat.PYTEST,
            ref_path="tests/test_login.py",
            ref_branch="main",
            cached_content="old",
            cached_content_etag="etag",
            tags_json="[]",
        )
        session.add(script)
        await session.flush()

        service = AutomationScriptService(session)
        updated = await service.update_metadata(
            team_id=automation_script_db["team_id"],
            script_id=script.id,
            actor="1",
            name="Login smoke",
            tags=["smoke"],
            preferred_runner_label="self-hosted",
        )
        assert updated.name == "Login smoke"
        assert updated.tags_json == '["smoke"]'
        assert updated.preferred_runner_label == "self-hosted"

        await service.delete_script_cache(team_id=automation_script_db["team_id"], script_id=script.id)
        remaining = list((await session.execute(select(AutomationScript))).scalars().all())

    assert remaining == []


# ---------------------------------------------------------------------------
# Section 2 — marker reconcile integration tests
# ---------------------------------------------------------------------------


def test_created_by_sentinel_helpers():
    assert is_marker_sync_link("marker-sync") is True
    assert is_marker_sync_link("42") is False
    assert is_marker_sync_link(None) is False

    assert is_ai_suggest_link("ai-suggest:42") is True
    assert is_ai_suggest_link("ai-suggest:") is True  # prefix matches even with empty id
    assert is_ai_suggest_link("marker-sync") is False
    assert is_ai_suggest_link(None) is False

    assert parse_ai_suggest_user_id("ai-suggest:42") == "42"
    assert parse_ai_suggest_user_id("ai-suggest:") is None
    assert parse_ai_suggest_user_id("42") is None
    assert parse_ai_suggest_user_id(None) is None


def test_marker_note_round_trip():
    raw = build_marker_note(test_name="test_login_happy", line=12, marker_raw="@pytest.mark.tcrt('TC-001')")
    payload = parse_marker_note(raw)
    assert payload == {
        "test_name": "test_login_happy",
        "line": 12,
        "marker_raw": "@pytest.mark.tcrt('TC-001')",
    }
    assert parse_marker_note(None) is None
    assert parse_marker_note("not-json") is None


@pytest.fixture
def marker_sync_db(tmp_path):
    bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    SyncSessionLocal = bundle["sync_session_factory"]
    AsyncSessionLocal = bundle["async_session_factory"]

    with SyncSessionLocal() as session:
        team = Team(name="QA", description="", wiki_token="t", test_case_table_id="tbl")
        session.add(team)
        session.commit()

        provider = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps({"owner": "x", "repo": "y", "default_branch": "main"}),
            credentials_encrypted=None,
            is_active=True,
        )
        case_set = TestCaseSet(team_id=team.id, name="Default", description="", is_default=True)
        session.add_all([provider, case_set])
        session.commit()

        section = TestCaseSection(test_case_set_id=case_set.id, name="Smoke", level=1, sort_order=0)
        session.add(section)
        session.commit()

        tc001 = TestCaseLocal(
            team_id=team.id,
            test_case_set_id=case_set.id,
            test_case_section_id=section.id,
            test_case_number="TC-001",
            title="Login happy",
        )
        tc002 = TestCaseLocal(
            team_id=team.id,
            test_case_set_id=case_set.id,
            test_case_section_id=section.id,
            test_case_number="TC-002",
            title="Logout",
        )
        session.add_all([tc001, tc002])
        session.commit()

        ids = {
            "team_id": team.id,
            "provider_id": provider.id,
            "tc001_id": tc001.id,
            "tc002_id": tc002.id,
        }

    yield {"ids": ids, "async_sessionmaker": AsyncSessionLocal, "bundle": bundle}

    dispose_managed_test_database(bundle)


async def _make_script(session, team_id, provider_id, *, ref_path, content):
    script = AutomationScript(
        team_id=team_id,
        provider_id=provider_id,
        name=ref_path.rsplit("/", 1)[-1],
        script_format=AutomationScriptFormat.PYTEST,
        ref_path=ref_path,
        ref_branch="main",
        tags_json="[]",
        cached_content=content,
    )
    session.add(script)
    await session.flush()
    return script


async def _all_links(session, script_id):
    result = await session.execute(
        select(AutomationScriptCaseLink).where(
            AutomationScriptCaseLink.automation_script_id == script_id
        )
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_sync_scripts_does_not_create_marker_links(marker_sync_db):
    ids = marker_sync_db["ids"]
    provider = FakeStorageProvider(
        scripts=[
            ScriptRef(
                path="tests/test_login.py",
                name="test_login.py",
                script_format="PYTEST",
                ref="main",
                etag="a1",
            )
        ],
        contents={
            "tests/test_login.py": ScriptContent(
                path="tests/test_login.py",
                content='import pytest\n\n@pytest.mark.tcrt("TC-001")\ndef test_login():\n    pass\n',
                etag="a1",
                ref="main",
            )
        },
    )

    async with marker_sync_db["async_sessionmaker"]() as session:
        service = AutomationScriptService(session)
        summary = await service.sync_scripts(
            team_id=ids["team_id"],
            provider_id=ids["provider_id"],
            actor="42",
            storage_provider=provider,
            fetch_content=True,
        )
        await session.commit()
        links = list((await session.execute(select(AutomationScriptCaseLink))).scalars().all())

    assert summary.added == 1
    assert links == []


@pytest.mark.asyncio
async def test_marker_sync_resolves_dashed_marker_to_dotted_case_number(marker_sync_db):
    """Dotted TCG numbers can't appear in markers (tc_id grammar bans dots), so
    markers use the dash form; sync must still resolve them to the dotted case."""
    ids = marker_sync_db["ids"]
    async with marker_sync_db["async_sessionmaker"]() as session:
        tc001 = await session.get(TestCaseLocal, ids["tc001_id"])
        dotted = TestCaseLocal(
            team_id=ids["team_id"],
            test_case_set_id=tc001.test_case_set_id,
            test_case_section_id=tc001.test_case_section_id,
            test_case_number="TCG-100558.020.010",
            title="Related player filter",
        )
        session.add(dotted)
        await session.flush()
        dotted_id = dotted.id

        content = (
            "import pytest\n"
            "@pytest.mark.tcrt(\"TCG-100558-020-010\")\n"
            "def test_related_player_filter():\n    pass\n"
        )
        script = await _make_script(
            session, ids["team_id"], ids["provider_id"],
            ref_path="tests/test_related.py", content=content,
        )
        await session.commit()

        service = AutomationScriptService(session)
        summary = await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")
        await session.commit()
        links = await _all_links(session, script.id)

    assert summary.links_created == 1
    assert len(links) == 1
    assert links[0].test_case_id == dotted_id


@pytest.mark.asyncio
async def test_marker_sync_creates_new_link(marker_sync_db):
    ids = marker_sync_db["ids"]
    content = (
        "import pytest\n"
        "@pytest.mark.tcrt(\"TC-001\")\n"
        "def test_login_happy():\n    pass\n"
    )
    async with marker_sync_db["async_sessionmaker"]() as session:
        script = await _make_script(
            session, ids["team_id"], ids["provider_id"],
            ref_path="tests/test_login.py", content=content,
        )
        await session.commit()

        service = AutomationScriptService(session)
        summary = await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")
        await session.commit()

        links = await _all_links(session, script.id)

    assert summary.links_created == 1
    assert summary.links_updated == 0
    assert summary.links_removed == 0
    assert len(links) == 1
    link = links[0]
    assert link.created_by == MARKER_SYNC_CREATED_BY
    assert link.test_case_id == ids["tc001_id"]
    assert link.link_type == AutomationScriptLinkType.COVERS
    payload = parse_marker_note(link.note)
    assert payload["test_name"] == "test_login_happy"


@pytest.mark.asyncio
async def test_marker_sync_updates_link_type_on_same_source(marker_sync_db):
    ids = marker_sync_db["ids"]
    content_v1 = (
        "import pytest\n"
        "@pytest.mark.tcrt(\"TC-001\")\n"
        "def test_login_happy():\n    pass\n"
    )
    content_v2 = (
        "import pytest\n"
        "@pytest.mark.tcrt(\"TC-001\", link_type=\"primary\")\n"
        "def test_login_happy():\n    pass\n"
    )
    async with marker_sync_db["async_sessionmaker"]() as session:
        script = await _make_script(
            session, ids["team_id"], ids["provider_id"],
            ref_path="tests/test_login.py", content=content_v1,
        )
        await session.commit()
        service = AutomationScriptService(session)
        await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")
        await session.commit()

        script.cached_content = content_v2
        await session.flush()
        summary = await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")
        await session.commit()
        links = await _all_links(session, script.id)

    assert summary.links_created == 0
    assert summary.links_updated == 1
    assert summary.links_removed == 0
    assert len(links) == 1
    assert links[0].link_type == AutomationScriptLinkType.PRIMARY
    assert links[0].created_by == MARKER_SYNC_CREATED_BY


@pytest.mark.asyncio
async def test_marker_sync_cleans_up_when_marker_removed(marker_sync_db):
    ids = marker_sync_db["ids"]
    content_with = (
        "import pytest\n"
        "@pytest.mark.tcrt(\"TC-001\")\n"
        "def test_login_happy():\n    pass\n"
    )
    content_without = "def test_login_happy():\n    pass\n"

    async with marker_sync_db["async_sessionmaker"]() as session:
        script = await _make_script(
            session, ids["team_id"], ids["provider_id"],
            ref_path="tests/test_login.py", content=content_with,
        )
        await session.commit()
        service = AutomationScriptService(session)
        await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")
        await session.commit()

        # Remove marker
        script.cached_content = content_without
        await session.flush()
        summary = await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")
        await session.commit()
        links = await _all_links(session, script.id)

    assert summary.links_removed == 1
    assert links == []


@pytest.mark.asyncio
async def test_marker_sync_replaces_tc_when_marker_changes(marker_sync_db):
    """`@pytest.mark.tcrt("TC-001")` → `@pytest.mark.tcrt("TC-002")` swaps the link."""
    ids = marker_sync_db["ids"]
    content_v1 = (
        "import pytest\n"
        "@pytest.mark.tcrt(\"TC-001\")\n"
        "def test_login(): pass\n"
    )
    content_v2 = (
        "import pytest\n"
        "@pytest.mark.tcrt(\"TC-002\")\n"
        "def test_login(): pass\n"
    )
    async with marker_sync_db["async_sessionmaker"]() as session:
        script = await _make_script(
            session, ids["team_id"], ids["provider_id"],
            ref_path="tests/test_login.py", content=content_v1,
        )
        await session.commit()
        service = AutomationScriptService(session)
        await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")
        await session.commit()

        script.cached_content = content_v2
        await session.flush()
        summary = await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")
        await session.commit()
        links = await _all_links(session, script.id)

    assert summary.links_created == 1
    assert summary.links_removed == 1
    assert len(links) == 1
    assert links[0].test_case_id == ids["tc002_id"]


@pytest.mark.asyncio
async def test_marker_sync_preserves_human_link_and_warns_on_conflict(marker_sync_db):
    ids = marker_sync_db["ids"]
    content = (
        "import pytest\n"
        "@pytest.mark.tcrt(\"TC-001\", link_type=\"covers\")\n"
        "def test_login(): pass\n"
    )
    async with marker_sync_db["async_sessionmaker"]() as session:
        script = await _make_script(
            session, ids["team_id"], ids["provider_id"],
            ref_path="tests/test_login.py", content=content,
        )
        # Human link with different link_type
        human_link = AutomationScriptCaseLink(
            team_id=ids["team_id"],
            automation_script_id=script.id,
            test_case_id=ids["tc001_id"],
            link_type=AutomationScriptLinkType.PRIMARY,
            note="manual",
            created_by="42",
        )
        session.add(human_link)
        await session.commit()

        service = AutomationScriptService(session)
        summary = await service.sync_markers_for_team(team_id=ids["team_id"], actor="99")
        await session.commit()
        links = await _all_links(session, script.id)

    assert summary.links_created == 0
    assert summary.links_updated == 0
    assert summary.links_removed == 0
    # Human link unchanged
    assert len(links) == 1
    assert links[0].link_type == AutomationScriptLinkType.PRIMARY
    assert links[0].created_by == "42"
    # Conflict warning surfaced
    warnings = summary.per_script_warnings[script.id]
    assert any(
        w["type"] == "link_type_conflict"
        and w["tc_id"] == "TC-001"
        and w["human_link_type"] == "primary"
        and w["marker_link_type"] == "covers"
        for w in warnings
    )


@pytest.mark.asyncio
async def test_marker_sync_unknown_tc_does_not_create_link(marker_sync_db):
    ids = marker_sync_db["ids"]
    content = (
        "import pytest\n"
        "@pytest.mark.tcrt(\"TC-999\")\n"
        "def test_login(): pass\n"
    )
    async with marker_sync_db["async_sessionmaker"]() as session:
        script = await _make_script(
            session, ids["team_id"], ids["provider_id"],
            ref_path="tests/test_login.py", content=content,
        )
        await session.commit()
        service = AutomationScriptService(session)
        summary = await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")
        await session.commit()
        links = await _all_links(session, script.id)

    assert summary.links_created == 0
    assert links == []
    warnings = summary.per_script_warnings[script.id]
    assert any(w["type"] == "unknown_tc" and w["tc_id"] == "TC-999" for w in warnings)


@pytest.mark.asyncio
async def test_marker_sync_skips_scripts_without_cached_content(marker_sync_db):
    ids = marker_sync_db["ids"]
    async with marker_sync_db["async_sessionmaker"]() as session:
        await _make_script(
            session, ids["team_id"], ids["provider_id"],
            ref_path="tests/test_oversize.py", content=None,
        )
        await session.commit()
        service = AutomationScriptService(session)
        summary = await service.sync_markers_for_team(team_id=ids["team_id"], actor="42")

    assert summary.scripts_scanned == 0
    assert summary.scripts_skipped_no_content == 1
    assert summary.links_created == 0
