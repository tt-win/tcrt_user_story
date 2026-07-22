"""Filter batch-update-by-filter endpoint and confirmation fingerprint STALE behavior."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.test_run_items import (
    FILTER_BATCH_MATCHED_CAP,
    BatchUpdateByFilterFilter,
    resolve_filter_batch_matches_sync,
)
from app.auth.models import UserRole
from app.config import AssistantConfig
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import (
    Team,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
    TestRunConfig,
    TestRunItem,
)
from app.services.assistant.tool_executor import ToolExecutor
from app.services.assistant.tool_registry import get_tool_registry
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def filter_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "filter_batch.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    with bundle["sync_session_factory"]() as session:
        session.add(Team(id=1, name="ART", description="", wiki_token="wt", test_case_table_id="tbl1"))
        session.commit()
        tcs = TestCaseSet(team_id=1, name="Default", description="", is_default=True)
        session.add(tcs)
        session.flush()
        session.add(TestCaseSection(test_case_set_id=tcs.id, name="Unassigned", level=1, sort_order=0))
        cfg = TestRunConfig(team_id=1, name="Run A", description="")
        session.add(cfg)
        session.flush()
        for i in range(5):
            session.add(
                TestCaseLocal(
                    team_id=1,
                    test_case_number=f"TC-{i:03d}",
                    title=f"Title {i}",
                    test_case_set_id=tcs.id,
                )
            )
        session.flush()
        for i in range(5):
            session.add(
                TestRunItem(
                    team_id=1,
                    config_id=cfg.id,
                    test_case_number=f"TC-{i:03d}",
                    assignee_name=None if i < 3 else "Bob",
                )
            )
        session.commit()
        ids = {"config_id": cfg.id, "set_id": tcs.id}

    yield {"bundle": bundle, "ids": ids}
    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(bundle)


def test_resolve_filter_unassigned_and_mutual_exclusion(filter_db):
    bundle = filter_db["bundle"]
    config_id = filter_db["ids"]["config_id"]
    with bundle["sync_session_factory"]() as session:
        matches = resolve_filter_batch_matches_sync(
            session,
            team_id=1,
            config_id=config_id,
            filt=BatchUpdateByFilterFilter(assignee_unassigned=True),
        )
        assert len(matches) == 3
        assert all(not (m.assignee_name or "").strip() for m in matches)

        with pytest.raises(HTTPException) as exc:
            resolve_filter_batch_matches_sync(
                session,
                team_id=1,
                config_id=config_id,
                filt=BatchUpdateByFilterFilter(assignee_unassigned=True, assignee_name="Bob"),
            )
        assert exc.value.status_code == 422


def test_resolve_filter_zero_match(filter_db):
    bundle = filter_db["bundle"]
    config_id = filter_db["ids"]["config_id"]
    with bundle["sync_session_factory"]() as session:
        matches = resolve_filter_batch_matches_sync(
            session,
            team_id=1,
            config_id=config_id,
            filt=BatchUpdateByFilterFilter(assignee_name="Nobody"),
        )
        assert matches == []


@pytest.mark.asyncio
async def test_search_membership_confirm_matches_shared_resolver(filter_db):
    """Title-only search must yield the same matched_ids for confirm summary and API resolver.

    Regression for confirm path that only LIKEd test_case_number (missed title matches).
    """
    bundle = filter_db["bundle"]
    config_id = filter_db["ids"]["config_id"]
    set_id = filter_db["ids"]["set_id"]

    with bundle["sync_session_factory"]() as session:
        # Unique title keyword not present in any test_case_number.
        session.add(
            TestCaseLocal(
                team_id=1,
                test_case_number="TC-TITLE-ONLY",
                title="UniqueZebraTitleKeyword for search",
                test_case_set_id=set_id,
            )
        )
        session.flush()
        session.add(
            TestRunItem(
                team_id=1,
                config_id=config_id,
                test_case_number="TC-TITLE-ONLY",
            )
        )
        session.commit()

        api_rows = resolve_filter_batch_matches_sync(
            session,
            team_id=1,
            config_id=config_id,
            filt=BatchUpdateByFilterFilter(search="UniqueZebraTitleKeyword"),
        )
        api_ids = [int(r.id) for r in api_rows]
        assert len(api_ids) == 1

    cfg = AssistantConfig()
    executor = ToolExecutor(
        app=app,
        main_boundary=get_main_access_boundary(),
        config=cfg,
        registry=get_tool_registry(),
    )
    tool = get_tool_registry().get("batch_update_test_run_items_by_filter")
    assert tool is not None
    summary_pair = await executor.build_confirmation_summary(
        tool,
        path_params={"config_id": config_id},
        body_params={
            "filter": {"search": "UniqueZebraTitleKeyword"},
            "patch": {"assignee_name": "Alice"},
        },
    )
    assert summary_pair is not None
    _summary, identity = summary_pair
    assert identity["matched_ids"] == api_ids


@pytest.mark.asyncio
async def test_filter_batch_cap_plus_one_rejects_pending_and_http(filter_db):
    """cap+1 matches → confirmation fail-closed (None) and HTTP 422."""
    from httpx import ASGITransport, AsyncClient
    from app.auth.dependencies import get_current_user
    from app.models.database_models import User

    bundle = filter_db["bundle"]
    config_id = filter_db["ids"]["config_id"]
    set_id = filter_db["ids"]["set_id"]
    # Seed enough unassigned items so filter matches FILTER_BATCH_MATCHED_CAP + 1.
    with bundle["sync_session_factory"]() as session:
        already_unassigned = (
            session.query(TestRunItem)
            .filter(
                TestRunItem.config_id == config_id,
                (TestRunItem.assignee_name.is_(None)) | (TestRunItem.assignee_name == ""),
            )
            .count()
        )
        need = FILTER_BATCH_MATCHED_CAP + 1 - already_unassigned
        for i in range(max(0, need)):
            num = f"TC-CAP-{i:04d}"
            session.add(
                TestCaseLocal(
                    team_id=1,
                    test_case_number=num,
                    title=f"Cap seed {i}",
                    test_case_set_id=set_id,
                )
            )
            session.add(
                TestRunItem(
                    team_id=1,
                    config_id=config_id,
                    test_case_number=num,
                    assignee_name=None,
                )
            )
        session.commit()
        overflow = resolve_filter_batch_matches_sync(
            session,
            team_id=1,
            config_id=config_id,
            filt=BatchUpdateByFilterFilter(assignee_unassigned=True),
        )
        assert len(overflow) == FILTER_BATCH_MATCHED_CAP + 1

    cfg = AssistantConfig()
    executor = ToolExecutor(
        app=app,
        main_boundary=get_main_access_boundary(),
        config=cfg,
        registry=get_tool_registry(),
    )
    tool = get_tool_registry().get("batch_update_test_run_items_by_filter")
    assert tool is not None
    summary_pair = await executor.build_confirmation_summary(
        tool,
        path_params={"config_id": config_id},
        body_params={
            "filter": {"assignee_unassigned": True},
            "patch": {"assignee_name": "Alice"},
        },
    )
    assert summary_pair is None, "over-cap must not create confirmable pending"

    async def _fake_user():
        return User(
            id=1,
            username="tester",
            full_name="Tester",
            email="t@example.com",
            role=UserRole.ADMIN,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/teams/1/test-run-configs/{config_id}/items/batch-update-by-filter",
                json={
                    "filter": {"assignee_unassigned": True},
                    "patch": {"assignee_name": "Alice"},
                },
            )
        assert resp.status_code == 422
        assert "500" in resp.text or "narrow" in resp.text.lower() or "more than" in resp.text.lower()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_filter_batch_confirmation_summary_and_stale(filter_db):
    cfg = AssistantConfig()
    boundary = get_main_access_boundary()
    registry = get_tool_registry()
    executor = ToolExecutor(app=app, main_boundary=boundary, config=cfg, registry=registry)
    tool = registry.get("batch_update_test_run_items_by_filter")
    assert tool is not None
    config_id = filter_db["ids"]["config_id"]

    summary_pair = await executor.build_confirmation_summary(
        tool,
        path_params={"config_id": config_id},
        body_params={
            "filter": {"assignee_unassigned": True},
            "patch": {"assignee_name": "Alice"},
        },
    )
    assert summary_pair is not None
    summary, identity = summary_pair
    assert summary["matched_count"] == 3
    assert summary["affected_count"] == 3
    assert len(summary["sample_ids"]) <= 10
    assert identity["kind"] == "filter_batch"
    assert len(identity["matched_ids"]) == 3
    fp1 = executor.compute_fingerprint(summary, identity)

    # Change membership → fingerprint must change (STALE path input).
    bundle = filter_db["bundle"]
    with bundle["sync_session_factory"]() as session:
        item = (
            session.query(TestRunItem)
            .filter(TestRunItem.config_id == config_id, TestRunItem.assignee_name.is_(None))
            .first()
        )
        item.assignee_name = "Changed"
        session.commit()

    summary_pair2 = await executor.build_confirmation_summary(
        tool,
        path_params={"config_id": config_id},
        body_params={
            "filter": {"assignee_unassigned": True},
            "patch": {"assignee_name": "Alice"},
        },
    )
    assert summary_pair2 is not None
    summary2, identity2 = summary_pair2
    assert summary2["matched_count"] == 2
    fp2 = executor.compute_fingerprint(summary2, identity2)
    assert fp1 != fp2


@pytest.mark.asyncio
async def test_batch_update_by_filter_endpoint_mutates(filter_db):
    """Drive the real HTTP endpoint (ASGI) for filter batch assign."""
    from httpx import ASGITransport, AsyncClient
    from app.auth.dependencies import get_current_user
    from app.models.database_models import User

    async def _fake_user():
        return User(
            id=1,
            username="tester",
            full_name="Tester",
            email="t@example.com",
            role=UserRole.ADMIN,
            is_active=True,
        )

    app.dependency_overrides[get_current_user] = _fake_user
    config_id = filter_db["ids"]["config_id"]
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/teams/1/test-run-configs/{config_id}/items/batch-update-by-filter",
                json={
                    "filter": {"assignee_unassigned": True},
                    "patch": {"assignee_name": "Alice"},
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["matched_count"] == 3
        assert body["success_count"] == 3
        assert body["success"] is True
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    bundle = filter_db["bundle"]
    with bundle["sync_session_factory"]() as session:
        unassigned = (
            session.query(TestRunItem)
            .filter(
                TestRunItem.config_id == config_id,
                (TestRunItem.assignee_name.is_(None)) | (TestRunItem.assignee_name == ""),
            )
            .count()
        )
        alice = (
            session.query(TestRunItem)
            .filter(TestRunItem.config_id == config_id, TestRunItem.assignee_name == "Alice")
            .count()
        )
        assert unassigned == 0
        assert alice == 3


@pytest.mark.asyncio
async def test_filter_batch_zero_match_no_summary(filter_db):
    cfg = AssistantConfig()
    boundary = get_main_access_boundary()
    registry = get_tool_registry()
    executor = ToolExecutor(app=app, main_boundary=boundary, config=cfg, registry=registry)
    tool = registry.get("batch_update_test_run_items_by_filter")
    config_id = filter_db["ids"]["config_id"]
    summary_pair = await executor.build_confirmation_summary(
        tool,
        path_params={"config_id": config_id},
        body_params={
            "filter": {"assignee_name": "Ghost"},
            "patch": {"assignee_name": "Alice"},
        },
    )
    # high_impact with unresolvable → None (fail-closed, no pending)
    assert summary_pair is None
