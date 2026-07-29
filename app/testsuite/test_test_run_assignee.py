from __future__ import annotations

import pytest

from app.api.app_test_runs import AppTestRunItemReadItem
from app.auth.models import UserRole
from app.models.database_models import Team, TestRunConfig, TestRunItem, User
from app.services.assistant.tools_test_runs import _ITEM_PROJECTION
from app.services.test_run_assignee import (
    AssigneeValidationError,
    apply_resolved_assignee,
    resolve_assignee,
    resolve_clone_assignee,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
)


@pytest.fixture
def assignee_db(tmp_path):
    bundle = create_managed_test_database(tmp_path / "assignee.db")
    with bundle["sync_session_factory"]() as session:
        team = Team(name="Assignee Team", description="", wiki_token="", test_case_table_id="")
        session.add(team)
        session.flush()
        config = TestRunConfig(team_id=team.id, name="Assignee Run")
        session.add(config)
        session.flush()
        local_only = User(
            username="local-only",
            full_name="Local Only",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=True,
        )
        lark_user = User(
            username="lark-user",
            full_name="Lark User",
            lark_user_id="ou-lark-user",
            email="lark@example.com",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=True,
        )
        inactive_user = User(
            username="inactive-user",
            full_name="Inactive User",
            lark_user_id="ou-inactive-user",
            email="inactive@example.com",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=False,
        )
        viewer = User(
            username="viewer-user",
            full_name="Viewer User",
            lark_user_id="ou-viewer-user",
            email="viewer@example.com",
            hashed_password="hashed",
            role=UserRole.VIEWER,
            is_active=True,
        )
        collision = User(
            username="collision-user",
            full_name="Collision User",
            lark_user_id="ou-other-user",
            email="collision@example.com",
            hashed_password="hashed",
            role=UserRole.USER,
            is_active=True,
        )
        session.add_all([local_only, lark_user, inactive_user, viewer, collision])
        session.commit()
        ids = {
            "team": team.id,
            "config": config.id,
            "local_only": local_only.id,
            "lark": lark_user.id,
            "inactive": inactive_user.id,
            "viewer": viewer.id,
            "collision": collision.id,
        }
    yield bundle, ids
    dispose_managed_test_database(bundle)


def test_tcrt_only_user_creates_stable_local_assignment(assignee_db):
    bundle, ids = assignee_db
    with bundle["sync_session_factory"]() as session:
        resolved = resolve_assignee(
            session,
            team_id=ids["team"],
            payload={"assignee_user_id": ids["local_only"]},
        )
        item = TestRunItem(
            team_id=ids["team"], config_id=ids["config"], test_case_number="TC-LOCAL"
        )
        apply_resolved_assignee(item, resolved)

    assert item.assignee_user_id == ids["local_only"]
    assert item.assignee_name == "Local Only"
    assert item.assignee_id is None
    assert item.assignee_email is None


def test_local_assignment_uses_username_when_full_name_is_blank(assignee_db):
    bundle, ids = assignee_db
    with bundle["sync_session_factory"]() as session:
        user = session.get(User, ids["local_only"])
        user.full_name = "   "
        resolved = resolve_assignee(
            session,
            team_id=ids["team"],
            payload={"assignee_user_id": ids["local_only"]},
        )

    assert resolved.assignee_name == "local-only"


def test_app_token_and_assistant_minimal_item_projections_do_not_expose_local_user_id():
    assert "assignee_user_id" not in AppTestRunItemReadItem.model_fields
    assert "assignee_user_id" not in _ITEM_PROJECTION


def test_lark_id_and_normalized_email_link_only_when_the_same_user(assignee_db):
    bundle, ids = assignee_db
    with bundle["sync_session_factory"]() as session:
        resolved = resolve_assignee(
            session,
            team_id=ids["team"],
            payload={
                "assignee": {
                    "id": " ou-lark-user ",
                    "name": "Lark Snapshot",
                    "email": " LARK@example.COM ",
                }
            },
        )

        assert resolved.assignee_user_id == ids["lark"]
        assert resolved.assignee_id == "ou-lark-user"
        assert resolved.assignee_email == "lark@example.com"

        with pytest.raises(AssigneeValidationError, match="different accounts"):
            resolve_assignee(
                session,
                team_id=ids["team"],
                payload={
                    "assignee": {
                        "id": "ou-lark-user",
                        "email": "collision@example.com",
                    }
                },
            )


def test_trimmed_local_lark_identity_is_resolved_exactly(assignee_db):
    bundle, ids = assignee_db
    with bundle["sync_session_factory"]() as session:
        user = session.get(User, ids["lark"])
        user.lark_user_id = " ou-lark-user "
        session.flush()
        resolved = resolve_assignee(
            session,
            team_id=ids["team"],
            payload={"assignee": {"id": "ou-lark-user", "name": "Lark Snapshot"}},
        )

    assert resolved.assignee_user_id == ids["lark"]


def test_inactive_or_viewer_lark_candidate_stays_snapshot_only(assignee_db):
    bundle, ids = assignee_db
    with bundle["sync_session_factory"]() as session:
        inactive = resolve_assignee(
            session,
            team_id=ids["team"],
            payload={"assignee": {"id": "ou-inactive-user", "name": "Inactive Snapshot"}},
        )
        viewer = resolve_assignee(
            session,
            team_id=ids["team"],
            payload={"assignee": {"id": "ou-viewer-user", "name": "Viewer Snapshot"}},
        )

    assert inactive.assignee_user_id is None
    assert inactive.assignee_id == "ou-inactive-user"
    assert viewer.assignee_user_id is None
    assert viewer.assignee_id == "ou-viewer-user"


def test_omitted_assignment_preserves_but_name_only_and_clear_remove_machine_identity(assignee_db):
    bundle, ids = assignee_db
    with bundle["sync_session_factory"]() as session:
        item = TestRunItem(
            team_id=ids["team"],
            config_id=ids["config"],
            test_case_number="TC-PRESERVE",
            assignee_user_id=ids["lark"],
            assignee_id="ou-lark-user",
            assignee_name="Lark User",
            assignee_email="lark@example.com",
            assignee_json='{"id":"ou-lark-user"}',
        )
        apply_resolved_assignee(
            item,
            resolve_assignee(session, team_id=ids["team"], payload={}),
        )
        assert item.assignee_user_id == ids["lark"]

        apply_resolved_assignee(
            item,
            resolve_assignee(session, team_id=ids["team"], payload={"assignee_name": "  Named only  "}),
        )
        assert item.assignee_user_id is None
        assert item.assignee_id is None
        assert item.assignee_email is None
        assert item.assignee_name == "Named only"

        apply_resolved_assignee(
            item,
            resolve_assignee(session, team_id=ids["team"], payload={"assignee_name": None}),
        )
        assert item.assignee_user_id is None
        assert item.assignee_name is None
        assert item.assignee_json is None


def test_legacy_structured_display_only_assignee_stays_name_only(assignee_db):
    bundle, ids = assignee_db
    with bundle["sync_session_factory"]() as session:
        resolved = resolve_assignee(
            session,
            team_id=ids["team"],
            payload={"assignee": {"name": "Legacy display", "en_name": "Legacy Display"}},
        )

    assert resolved.assignee_user_id is None
    assert resolved.assignee_id is None
    assert resolved.assignee_email is None
    assert resolved.assignee_name == "Legacy display"
    assert resolved.assignee_en_name == "Legacy Display"


def test_app_token_structured_assignee_cannot_create_local_fk(assignee_db):
    bundle, ids = assignee_db
    with bundle["sync_session_factory"]() as session:
        resolved = resolve_assignee(
            session,
            team_id=ids["team"],
            payload={"assignee": {"id": "ou-lark-user", "name": "Lark Snapshot"}},
            allow_local_user_id=False,
            allow_structured_local_link=False,
        )

    assert resolved.assignee_user_id is None
    assert resolved.assignee_id == "ou-lark-user"


def test_restart_clone_of_disabled_local_identity_keeps_display_snapshot_only(assignee_db):
    bundle, ids = assignee_db
    with bundle["sync_session_factory"]() as session:
        source = TestRunItem(
            team_id=ids["team"],
            config_id=ids["config"],
            test_case_number="TC-CLONE",
            assignee_user_id=ids["inactive"],
            assignee_id="ou-inactive-user",
            assignee_name="Inactive User",
            assignee_email="inactive@example.com",
            assignee_json='{"id":"ou-inactive-user"}',
        )
        resolved = resolve_clone_assignee(session, team_id=ids["team"], source=source)

    assert resolved.assignee_user_id is None
    assert resolved.assignee_name == "Inactive User"
    assert resolved.assignee_id is None
    assert resolved.assignee_email is None
