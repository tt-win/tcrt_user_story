"""API regressions for local Test Run assignee identity."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.database import get_db
from app.main import app
from app.models.database_models import Team, TestRunConfig, TestRunItem, TestRunItemResultHistory, User
from app.services.dashboard_service import _load_assigned_rows
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def assignee_api_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assignee-api.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    auth_context: dict[str, object] = {}
    app.dependency_overrides[get_current_user] = lambda: auth_context["user"]

    with bundle["sync_session_factory"]() as session:
        team = Team(name="Identity Team", description="", wiki_token="", test_case_table_id="")
        session.add(team)
        session.flush()
        config = TestRunConfig(team_id=team.id, name="Identity Run")
        session.add(config)
        writer = User(
            username="writer",
            full_name="Writer",
            email="writer@example.com",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=True,
        )
        local_only = User(
            username="local-only",
            full_name="Local only",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=True,
        )
        viewer = User(
            username="viewer",
            full_name="Viewer",
            hashed_password="hashed",
            role=UserRole.VIEWER,
            is_active=True,
        )
        inactive = User(
            username="inactive",
            full_name="Inactive",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=False,
        )
        admin = User(
            username="identity-admin",
            full_name="Identity admin",
            hashed_password="hashed",
            role=UserRole.ADMIN,
            is_active=True,
        )
        removed = User(
            username="removed-user",
            full_name="Removed display snapshot",
            lark_user_id=" ou-removed ",
            email="removed@example.com",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=True,
        )
        session.add_all([writer, local_only, viewer, inactive, admin, removed])
        session.flush()
        assigned_item = TestRunItem(
            team_id=team.id,
            config_id=config.id,
            test_case_number="TC-REMOVED",
            assignee_user_id=removed.id,
            assignee_id="ou-removed",
            assignee_name=removed.full_name,
            assignee_email=" REMOVED@EXAMPLE.COM ",
            assignee_json='{"id":"ou-removed"}',
        )
        session.add(assigned_item)
        session.commit()
        auth_context["writer"] = SimpleNamespace(
            id=writer.id,
            username=writer.username,
            full_name=writer.full_name,
            role=UserRole.USER,
        )
        auth_context["viewer"] = SimpleNamespace(
            id=viewer.id,
            username=viewer.username,
            full_name=viewer.full_name,
            role=UserRole.VIEWER,
        )
        auth_context["admin"] = SimpleNamespace(
            id=admin.id,
            username=admin.username,
            full_name=admin.full_name,
            role=UserRole.ADMIN,
        )
        auth_context["ids"] = {
            "team": team.id,
            "config": config.id,
            "writer": writer.id,
            "local_only": local_only.id,
            "viewer": viewer.id,
            "inactive": inactive.id,
            "removed": removed.id,
            "item": assigned_item.id,
        }
        auth_context["user"] = auth_context["writer"]

    yield bundle, auth_context

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(bundle)


def test_assignee_lookup_is_minimal_limited_and_rejects_viewers(assignee_api_db):
    _, auth_context = assignee_api_db
    ids = auth_context["ids"]
    with TestClient(app) as client:
        response = client.get(f"/api/teams/{ids['team']}/test-run-assignees/?limit=50")

        assert response.status_code == 200, response.text
        options = response.json()
        assert {option["id"] for option in options} >= {ids["writer"], ids["local_only"]}
        assert ids["viewer"] not in {option["id"] for option in options}
        assert ids["inactive"] not in {option["id"] for option in options}
        assert all(set(option) == {"id", "display_name", "lark_linked"} for option in options)

        auth_context["user"] = auth_context["viewer"]
        denied = client.get(f"/api/teams/{ids['team']}/test-run-assignees/")
        denied_assignment = client.put(
            f"/api/teams/{ids['team']}/test-run-configs/{ids['config']}/items/{ids['item']}",
            json={"assignee_user_id": ids["local_only"]},
        )

    assert denied.status_code == 403
    assert denied_assignment.status_code == 403


def test_user_delete_scrubs_machine_identity_before_identity_reuse(assignee_api_db):
    bundle, auth_context = assignee_api_db
    ids = auth_context["ids"]
    auth_context["user"] = auth_context["admin"]

    with TestClient(app) as client:
        response = client.delete(f"/api/users/{ids['removed']}")

    assert response.status_code == 200, response.text
    with bundle["sync_session_factory"]() as session:
        item = session.get(TestRunItem, ids["item"])
        assert item is not None
        assert item.assignee_user_id is None
        assert item.assignee_id is None
        assert item.assignee_email is None
        assert item.assignee_json is None
        assert item.assignee_name == "Removed display snapshot"
        assert session.get(User, ids["removed"]) is None

        replacement = User(
            username="replacement-user",
            full_name="Replacement",
            lark_user_id="ou-removed",
            email="removed@example.com",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=True,
        )
        session.add(replacement)
        session.commit()
        rows = _load_assigned_rows(
            session,
            SimpleNamespace(
                id=replacement.id,
                lark_user_id=replacement.lark_user_id,
                email=replacement.email,
            ),
            [ids["team"]],
        )

    assert rows == []


def test_assignment_only_write_keeps_history_clean_and_batch_preflight_is_atomic(assignee_api_db):
    bundle, auth_context = assignee_api_db
    ids = auth_context["ids"]
    with bundle["sync_session_factory"]() as session:
        first = TestRunItem(
            team_id=ids["team"],
            config_id=ids["config"],
            test_case_number="TC-ASSIGN-ONE",
            assignee_name="Original",
        )
        second = TestRunItem(
            team_id=ids["team"],
            config_id=ids["config"],
            test_case_number="TC-ASSIGN-TWO",
            assignee_name="Original two",
        )
        session.add_all([first, second])
        session.commit()
        first_id = first.id
        second_id = second.id

    with TestClient(app) as client:
        single = client.put(
            f"/api/teams/{ids['team']}/test-run-configs/{ids['config']}/items/{first_id}",
            json={"assignee_user_id": ids["local_only"]},
        )
        batch = client.post(
            f"/api/teams/{ids['team']}/test-run-configs/{ids['config']}/items/batch-update-results",
            json={
                "updates": [
                    {"id": first_id, "assignee_name": "Would be changed"},
                    {"id": second_id, "assignee_user_id": ids["viewer"]},
                ]
            },
        )
        assistant_filtered = client.post(
            f"/api/teams/{ids['team']}/test-run-configs/{ids['config']}/items/batch-update-by-filter",
            json={
                "filter": {"search": "TC-ASSIGN-ONE"},
                "patch": {"assignee_user_id": ids["local_only"]},
            },
        )

    assert single.status_code == 200, single.text
    assert single.json()["assignee_user_id"] == ids["local_only"]
    assert batch.status_code == 422, batch.text
    assert assistant_filtered.status_code == 422, assistant_filtered.text
    with bundle["sync_session_factory"]() as session:
        first = session.get(TestRunItem, first_id)
        assert first.assignee_user_id == ids["local_only"]
        assert first.assignee_name == "Local only"
        assert (
            session.query(TestRunItemResultHistory)
            .filter(TestRunItemResultHistory.item_id == first_id)
            .count()
            == 0
        )
