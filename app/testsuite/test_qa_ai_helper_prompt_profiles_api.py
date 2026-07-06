from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.database import get_db
from app.main import app
from app.models.database_models import QAAIHelperSession, Team, User
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def prompt_profiles_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "qa_ai_helper_prompt_profiles.db")
    testing_session_local = database_bundle["sync_session_factory"]
    async_testing_session_local = database_bundle["async_session_factory"]

    with testing_session_local() as session:
        team = Team(
            name="Prompt Profile Team",
            description="",
            wiki_token="wiki-prompt-profile",
            test_case_table_id="tbl-prompt-profile",
        )
        session.add(team)
        session.commit()

        admin_user = User(
            username="prompt-profile-admin",
            email="prompt-profile-admin@example.com",
            hashed_password="hashed-password",
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        member_user = User(
            username="prompt-profile-member",
            email="prompt-profile-member@example.com",
            hashed_password="hashed-password",
            role=UserRole.USER,
            is_active=True,
            is_verified=True,
        )
        session.add_all([admin_user, member_user])
        session.commit()

        team_id = team.id
        admin_user_id = admin_user.id
        member_user_id = member_user.id

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=async_testing_session_local,
    )

    yield {
        "team_id": team_id,
        "admin_user_id": admin_user_id,
        "member_user_id": member_user_id,
        "sync_session_factory": testing_session_local,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(database_bundle)


def _login_as_admin(prompt_profiles_db) -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=prompt_profiles_db["admin_user_id"],
        username="prompt-profile-admin",
        role=UserRole.ADMIN,
    )


def _login_as_member(prompt_profiles_db) -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=prompt_profiles_db["member_user_id"],
        username="prompt-profile-member",
        role=UserRole.USER,
    )


def _profiles_url(team_id: int, suffix: str = "") -> str:
    return f"/api/teams/{team_id}/qa-ai-helper/prompt-profiles{suffix}"


def test_create_list_update_delete_round_trip(prompt_profiles_db):
    _login_as_admin(prompt_profiles_db)
    client = TestClient(app)
    team_id = prompt_profiles_db["team_id"]

    created = client.post(
        _profiles_url(team_id),
        json={
            "name": "Concise Style",
            "description": "Short steps",
            "seed_instructions": "步驟用祈使句",
            "testcase_instructions": "expected_results 以「系統應」開頭",
        },
    )
    assert created.status_code == 201, created.text
    profile = created.json()
    assert profile["name"] == "Concise Style"
    assert profile["is_default"] is False

    listed = client.get(_profiles_url(team_id))
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["profiles"]) == 1

    updated = client.put(
        _profiles_url(team_id, f"/{profile['id']}"),
        json={
            "name": "Concise Style v2",
            "description": None,
            "seed_instructions": "步驟用祈使句",
            "testcase_instructions": None,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Concise Style v2"
    assert updated.json()["testcase_instructions"] is None

    deleted = client.delete(_profiles_url(team_id, f"/{profile['id']}"))
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"success": True}

    listed_after_delete = client.get(_profiles_url(team_id))
    assert listed_after_delete.json()["profiles"] == []


def test_duplicate_name_rejected(prompt_profiles_db):
    _login_as_admin(prompt_profiles_db)
    client = TestClient(app)
    team_id = prompt_profiles_db["team_id"]

    first = client.post(_profiles_url(team_id), json={"name": "Dup", "seed_instructions": "a"})
    assert first.status_code == 201, first.text

    second = client.post(_profiles_url(team_id), json={"name": "Dup", "seed_instructions": "b"})
    assert second.status_code == 409, second.text
    assert second.json()["detail"]["code"] == "PROMPT_PROFILE_NAME_DUPLICATE"

    renamed_conflict = client.post(_profiles_url(team_id), json={"name": "Other", "seed_instructions": "c"})
    assert renamed_conflict.status_code == 201, renamed_conflict.text
    conflict_update = client.put(
        _profiles_url(team_id, f"/{renamed_conflict.json()['id']}"),
        json={"name": "Dup", "seed_instructions": "c"},
    )
    assert conflict_update.status_code == 409, conflict_update.text


def test_both_instructions_empty_rejected(prompt_profiles_db):
    _login_as_admin(prompt_profiles_db)
    client = TestClient(app)
    team_id = prompt_profiles_db["team_id"]

    resp = client.post(_profiles_url(team_id), json={"name": "Empty"})
    assert resp.status_code == 422, resp.text


def test_instructions_over_length_limit_rejected(prompt_profiles_db):
    _login_as_admin(prompt_profiles_db)
    client = TestClient(app)
    team_id = prompt_profiles_db["team_id"]

    resp = client.post(
        _profiles_url(team_id),
        json={"name": "TooLong", "seed_instructions": "x" * 2001},
    )
    assert resp.status_code == 422, resp.text


def test_name_empty_rejected(prompt_profiles_db):
    _login_as_admin(prompt_profiles_db)
    client = TestClient(app)
    team_id = prompt_profiles_db["team_id"]

    resp = client.post(_profiles_url(team_id), json={"name": "  ", "seed_instructions": "a"})
    assert resp.status_code == 422, resp.text


def test_member_write_forbidden_but_can_list(prompt_profiles_db):
    _login_as_admin(prompt_profiles_db)
    client = TestClient(app)
    team_id = prompt_profiles_db["team_id"]
    created = client.post(_profiles_url(team_id), json={"name": "Admin Only", "seed_instructions": "a"})
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]

    _login_as_member(prompt_profiles_db)

    forbidden_create = client.post(_profiles_url(team_id), json={"name": "Member Try", "seed_instructions": "a"})
    assert forbidden_create.status_code == 403, forbidden_create.text

    forbidden_update = client.put(
        _profiles_url(team_id, f"/{profile_id}"),
        json={"name": "Member Try", "seed_instructions": "a"},
    )
    assert forbidden_update.status_code == 403, forbidden_update.text

    forbidden_delete = client.delete(_profiles_url(team_id, f"/{profile_id}"))
    assert forbidden_delete.status_code == 403, forbidden_delete.text

    forbidden_default = client.post(
        _profiles_url(team_id, f"/{profile_id}/set-default"),
        json={"is_default": True},
    )
    assert forbidden_default.status_code == 403, forbidden_default.text

    allowed_list = client.get(_profiles_url(team_id))
    assert allowed_list.status_code == 200, allowed_list.text
    assert len(allowed_list.json()["profiles"]) == 1


def test_team_not_found_returns_404(prompt_profiles_db):
    _login_as_admin(prompt_profiles_db)
    client = TestClient(app)

    resp = client.get(_profiles_url(999999))
    assert resp.status_code == 404, resp.text


def test_set_default_is_exclusive_per_team(prompt_profiles_db):
    _login_as_admin(prompt_profiles_db)
    client = TestClient(app)
    team_id = prompt_profiles_db["team_id"]

    profile_a = client.post(
        _profiles_url(team_id), json={"name": "A", "seed_instructions": "a", "is_default": True}
    ).json()
    profile_b = client.post(_profiles_url(team_id), json={"name": "B", "seed_instructions": "b"}).json()
    assert profile_a["is_default"] is True

    set_b_default = client.post(
        _profiles_url(team_id, f"/{profile_b['id']}/set-default"),
        json={"is_default": True},
    )
    assert set_b_default.status_code == 200, set_b_default.text
    assert set_b_default.json()["is_default"] is True

    listed = client.get(_profiles_url(team_id)).json()["profiles"]
    by_id = {p["id"]: p for p in listed}
    assert by_id[profile_a["id"]]["is_default"] is False
    assert by_id[profile_b["id"]]["is_default"] is True

    unset_b = client.post(
        _profiles_url(team_id, f"/{profile_b['id']}/set-default"),
        json={"is_default": False},
    )
    assert unset_b.status_code == 200, unset_b.text
    assert unset_b.json()["is_default"] is False

    listed_after_unset = client.get(_profiles_url(team_id)).json()["profiles"]
    assert all(not p["is_default"] for p in listed_after_unset)


def test_delete_clears_session_reference(prompt_profiles_db):
    _login_as_admin(prompt_profiles_db)
    client = TestClient(app)
    team_id = prompt_profiles_db["team_id"]

    profile = client.post(_profiles_url(team_id), json={"name": "Linked", "seed_instructions": "a"}).json()

    sync_session_factory = prompt_profiles_db["sync_session_factory"]
    with sync_session_factory() as db_session:
        session_row = QAAIHelperSession(
            team_id=team_id,
            created_by_user_id=prompt_profiles_db["admin_user_id"],
            ticket_key="TCG-1",
            output_locale="zh-TW",
            prompt_profile_id=profile["id"],
        )
        db_session.add(session_row)
        db_session.commit()
        session_id = session_row.id

    deleted = client.delete(_profiles_url(team_id, f"/{profile['id']}"))
    assert deleted.status_code == 200, deleted.text

    with sync_session_factory() as db_session:
        refreshed = db_session.get(QAAIHelperSession, session_id)
        assert refreshed.prompt_profile_id is None
