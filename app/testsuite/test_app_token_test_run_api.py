"""Tests for app token test run mutation API."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.app_token_dependencies import generate_app_token
from app.database import get_db
from app.main import app
from app.models.database_models import (
    AutomationScriptGroup,
    Team,
    TeamAppToken,
    TeamAppTokenStatus,
    TestCaseLocal,
    TestCaseSet,
    TestRunItem,
    TestRunSet,
    User,
)
from app.models.lark_types import Priority
from app.models.test_run_set import TestRunSetStatus
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_app_tr_mut.db")
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    import app.main as app_main
    import app.models.user_story_map_db as usm_db_module

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )

    async def _noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(app_main, "init_audit_database", _noop_async)
    monkeypatch.setattr(app_main, "cleanup_audit_database", _noop_async)
    monkeypatch.setattr(app_main.audit_service, "force_flush", _noop_async)
    monkeypatch.setattr(usm_db_module, "init_usm_db", _noop_async)

    yield TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(database_bundle)


def _seed_data(session, scopes=None):
    if scopes is None:
        scopes = ["test_run:read", "test_run:write", "test_run:execute", "test_run:admin"]

    team = Team(name="TR Team", description="Test", wiki_token="s", test_case_table_id="t")
    session.add(team)
    session.commit()

    user = User(username="tr_creator", email="tr@e.com", full_name="TR", role="admin", is_active=True, hashed_password="d")
    session.add(user)
    session.commit()

    raw, h, p = generate_app_token()
    session.add(TeamAppToken(
        name="tr-token", owner_team_id=team.id, token_hash=h, token_prefix=p,
        status=TeamAppTokenStatus.ACTIVE, scopes_json=json.dumps(scopes),
        expires_at=datetime.utcnow() + timedelta(days=90), created_by_user_id=user.id,
    ))

    read_raw, read_h, read_p = generate_app_token()
    session.add(TeamAppToken(
        name="tr-read-token", owner_team_id=team.id, token_hash=read_h, token_prefix=read_p,
        status=TeamAppTokenStatus.ACTIVE, scopes_json=json.dumps(["test_run:read"]),
        expires_at=datetime.utcnow() + timedelta(days=90), created_by_user_id=user.id,
    ))

    other_team = Team(name="Other TR", description="O", wiki_token="s2", test_case_table_id="t2")
    session.add(other_team)
    session.commit()

    return {
        "team_id": team.id,
        "other_team_id": other_team.id,
        "write_token": raw,
        "read_token": read_raw,
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestTestRunConfig:
    def test_create_config(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Config 1", "description": "Test config"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 201
            assert resp.json()["name"] == "Config 1"

    def test_update_config(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Config 2"},
                headers=_bearer(seeded["write_token"]),
            )
            cid = create_resp.json()["id"]
            resp = client.put(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{cid}",
                json={"name": "Updated Config"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "Updated Config"

    def test_delete_config_requires_admin(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session, scopes=["test_run:read", "test_run:write"])
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "To Delete"},
                headers=_bearer(seeded["write_token"]),
            )
            cid = create_resp.json()["id"]
            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{cid}",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 403

    def test_delete_config_with_admin(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Admin Delete"},
                headers=_bearer(seeded["write_token"]),
            )
            cid = create_resp.json()["id"]
            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{cid}",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 204


class TestTestRunSet:
    def test_create_set(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Set 1", "description": "Test set"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 201
            assert resp.json()["name"] == "Set 1"

    def test_delete_set_requires_admin(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session, scopes=["test_run:read", "test_run:write"])
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Set to Delete"},
                headers=_bearer(seeded["write_token"]),
            )
            sid = create_resp.json()["id"]
            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{sid}",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 403

    def test_delete_set_with_admin(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Admin Set Delete"},
                headers=_bearer(seeded["write_token"]),
            )
            sid = create_resp.json()["id"]
            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{sid}",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 204


class TestCrossTeamRejection:
    def test_create_config_denied_other_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['other_team_id']}/test-run-configs",
                json={"name": "Cross team"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 403


def _seed_with_case_set(session, scopes=None):
    seeded = _seed_data(session, scopes=scopes)
    case_set = TestCaseSet(name=f"Set-{seeded['team_id']}", description="", team_id=seeded["team_id"])
    session.add(case_set)
    session.commit()

    other_case_set = TestCaseSet(name=f"OtherSet-{seeded['other_team_id']}", description="", team_id=seeded["other_team_id"])
    session.add(other_case_set)
    session.commit()

    seeded["case_set_id"] = case_set.id
    seeded["other_case_set_id"] = other_case_set.id
    return seeded


class TestConfigMultiSetScope:
    def test_create_config_rejects_cross_team_set_id(self, temp_db):
        with temp_db() as session:
            seeded = _seed_with_case_set(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Bad scope", "test_case_set_ids": [seeded["other_case_set_id"]]},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 400, resp.text

    def test_create_config_accepts_same_team_set_id(self, temp_db):
        with temp_db() as session:
            seeded = _seed_with_case_set(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Good scope", "test_case_set_ids": [seeded["case_set_id"]]},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 201, resp.text
            assert resp.json()["test_case_set_ids"] == [seeded["case_set_id"]]

    def test_update_config_scope_reduction_returns_cleanup_summary(self, temp_db):
        with temp_db() as session:
            seeded = _seed_with_case_set(session)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Shrinking", "test_case_set_ids": [seeded["case_set_id"]]},
                headers=_bearer(seeded["write_token"]),
            )
            cid = create_resp.json()["id"]
            resp = client.put(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{cid}",
                json={"test_case_set_ids": []},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200, resp.text
            assert "cleanup_summary" in resp.json()


class TestSetAutomationSuiteIds:
    def test_create_set_rejects_cross_team_suite_id(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
            other_suite = AutomationScriptGroup(
                team_id=seeded["other_team_id"], name="OtherSuite", description="",
                ci_job_name="job", ci_job_type="JENKINS", script_paths_json="[]",
            )
            session.add(other_suite)
            session.commit()
            other_suite_id = other_suite.id
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Bad suite", "automation_suite_ids": [other_suite_id]},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 400, resp.text

    def test_create_set_accepts_same_team_suite_id(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
            suite = AutomationScriptGroup(
                team_id=seeded["team_id"], name="Suite", description="",
                ci_job_name="job", ci_job_type="JENKINS", script_paths_json="[]",
            )
            session.add(suite)
            session.commit()
            suite_id = suite.id
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Good suite", "automation_suite_ids": [suite_id]},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 201, resp.text
            assert resp.json()["automation_suite_ids"] == [suite_id]


class TestSetArchiveAndMembership:
    def test_archive_requires_admin(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session, scopes=["test_run:read", "test_run:write"])
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "To Archive"},
                headers=_bearer(seeded["write_token"]),
            )
            sid = create_resp.json()["id"]
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{sid}/archive",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 403

    def test_archive_with_admin_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "To Archive"},
                headers=_bearer(seeded["write_token"]),
            )
            sid = create_resp.json()["id"]
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{sid}/archive",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "archived"

    def test_attach_and_move_membership(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            set_a = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Set A"},
                headers=_bearer(seeded["write_token"]),
            ).json()
            set_b = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Set B"},
                headers=_bearer(seeded["write_token"]),
            ).json()
            config = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Config"},
                headers=_bearer(seeded["write_token"]),
            ).json()

            attach_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{set_a['id']}/members",
                json={"config_ids": [config["id"]]},
                headers=_bearer(seeded["write_token"]),
            )
            assert attach_resp.status_code == 200, attach_resp.text

            move_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/members/{config['id']}/move",
                json={"target_set_id": set_b["id"]},
                headers=_bearer(seeded["write_token"]),
            )
            assert move_resp.status_code == 200, move_resp.text
            assert move_resp.json()["set_id"] == set_b["id"]

    def test_move_rejects_cross_team_target_set(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
            other_set = TestRunSet(team_id=seeded["other_team_id"], name="Other Set", status=TestRunSetStatus.ACTIVE)
            session.add(other_set)
            session.commit()
            other_set_id = other_set.id
        with TestClient(app) as client:
            config = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Config"},
                headers=_bearer(seeded["write_token"]),
            ).json()
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/members/{config['id']}/move",
                json={"target_set_id": other_set_id},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 404, resp.text


class TestRunItemsBatchAndExecution:
    def test_batch_create_rejects_out_of_scope_case(self, temp_db):
        with temp_db() as session:
            seeded = _seed_with_case_set(session)
            case = TestCaseLocal(
                team_id=seeded["team_id"], lark_record_id="local-tri-1", test_case_number="TC-TRI-1",
                title="Case", priority=Priority.MEDIUM, test_case_set_id=seeded["other_case_set_id"],
            )
            session.add(case)
            session.commit()
        with TestClient(app) as client:
            config = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Scoped Config", "test_case_set_ids": [seeded["case_set_id"]]},
                headers=_bearer(seeded["write_token"]),
            ).json()
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items",
                json={"items": [{"test_case_number": "TC-TRI-1"}]},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 201, resp.text
            data = resp.json()
            assert data["created_count"] == 0
            assert len(data["errors"]) == 1

    def test_batch_create_and_update_result_and_delete(self, temp_db):
        with temp_db() as session:
            seeded = _seed_with_case_set(session)
            case = TestCaseLocal(
                team_id=seeded["team_id"], lark_record_id="local-tri-2", test_case_number="TC-TRI-2",
                title="Case", priority=Priority.MEDIUM, test_case_set_id=seeded["case_set_id"],
            )
            session.add(case)
            session.commit()
        with TestClient(app) as client:
            config = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Scoped Config 2", "test_case_set_ids": [seeded["case_set_id"]]},
                headers=_bearer(seeded["write_token"]),
            ).json()

            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items",
                json={"items": [{"test_case_number": "TC-TRI-2"}]},
                headers=_bearer(seeded["write_token"]),
            )
            assert create_resp.status_code == 201, create_resp.text
            assert create_resp.json()["created_count"] == 1

            list_resp = client.get(
                f"/api/app/teams/{seeded['team_id']}/test-runs",
                headers=_bearer(seeded["write_token"]),
            )
            assert list_resp.status_code == 200

    def test_result_update_requires_execute_scope_then_succeeds(self, temp_db):
        with temp_db() as session:
            seeded = _seed_with_case_set(
                session, scopes=["test_run:read", "test_run:write", "test_run:execute", "test_run:admin"]
            )
            case = TestCaseLocal(
                team_id=seeded["team_id"], lark_record_id="local-tri-3", test_case_number="TC-TRI-3",
                title="Case", priority=Priority.MEDIUM, test_case_set_id=seeded["case_set_id"],
            )
            session.add(case)
            session.commit()

        write_only_raw, write_only_hash, write_only_prefix = generate_app_token()
        with temp_db() as session:
            team = session.query(Team).filter(Team.id == seeded["team_id"]).one()
            session.add(TeamAppToken(
                name="write-only", owner_team_id=team.id, token_hash=write_only_hash, token_prefix=write_only_prefix,
                status=TeamAppTokenStatus.ACTIVE, scopes_json=json.dumps(["test_run:read", "test_run:write"]),
                expires_at=datetime.utcnow() + timedelta(days=90),
            ))
            session.commit()

        with TestClient(app) as client:
            config = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Config", "test_case_set_ids": [seeded["case_set_id"]]},
                headers=_bearer(seeded["write_token"]),
            ).json()
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items",
                json={"items": [{"test_case_number": "TC-TRI-3"}]},
                headers=_bearer(seeded["write_token"]),
            )
            assert create_resp.json()["created_count"] == 1

            with temp_db() as session:
                item = session.query(TestRunItem).filter(TestRunItem.config_id == config["id"]).one()
                item_id = item.id

            denied_resp = client.put(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items/{item_id}",
                json={"test_result": "Passed"},
                headers=_bearer(write_only_raw),
            )
            assert denied_resp.status_code == 403

            ok_resp = client.put(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items/{item_id}",
                json={"test_result": "Passed"},
                headers=_bearer(seeded["write_token"]),
            )
            assert ok_resp.status_code == 200, ok_resp.text
            assert ok_resp.json()["test_result"] == "Passed"

            delete_resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items/{item_id}",
                headers=_bearer(seeded["write_token"]),
            )
            assert delete_resp.status_code == 204

    def test_bug_ticket_lifecycle(self, temp_db):
        with temp_db() as session:
            seeded = _seed_with_case_set(session)
            case = TestCaseLocal(
                team_id=seeded["team_id"], lark_record_id="local-tri-4", test_case_number="TC-TRI-4",
                title="Case", priority=Priority.MEDIUM, test_case_set_id=seeded["case_set_id"],
            )
            session.add(case)
            session.commit()
        with TestClient(app) as client:
            config = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs",
                json={"name": "Config", "test_case_set_ids": [seeded["case_set_id"]]},
                headers=_bearer(seeded["write_token"]),
            ).json()
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items",
                json={"items": [{"test_case_number": "TC-TRI-4"}]},
                headers=_bearer(seeded["write_token"]),
            )
            assert create_resp.json()["created_count"] == 1

            with temp_db() as session:
                item = session.query(TestRunItem).filter(TestRunItem.config_id == config["id"]).one()
                item_id = item.id

            add_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items/{item_id}/bug-tickets",
                json={"ticket_number": "PRJ-123"},
                headers=_bearer(seeded["write_token"]),
            )
            assert add_resp.status_code == 201, add_resp.text
            assert add_resp.json()["ticket_number"] == "PRJ-123"

            dup_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items/{item_id}/bug-tickets",
                json={"ticket_number": "PRJ-123"},
                headers=_bearer(seeded["write_token"]),
            )
            assert dup_resp.status_code == 400

            list_resp = client.get(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items/{item_id}/bug-tickets",
                headers=_bearer(seeded["write_token"]),
            )
            assert list_resp.status_code == 200
            assert len(list_resp.json()) == 1

            remove_resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-run-configs/{config['id']}/items/{item_id}/bug-tickets/PRJ-123",
                headers=_bearer(seeded["write_token"]),
            )
            assert remove_resp.status_code == 204


class TestRunSetReport:
    def _patch_report_root(self, monkeypatch, tmp_path):
        import app.services.html_report_service as report_module

        original_init = report_module.HTMLReportService.__init__

        def patched_init(self, db_session, base_dir=None, report_root=None):
            original_init(self, db_session=db_session, report_root=tmp_path / "reports")

        monkeypatch.setattr(report_module.HTMLReportService, "__init__", patched_init)

    def test_lookup_before_generate_reports_not_exists(self, temp_db, tmp_path, monkeypatch):
        self._patch_report_root(monkeypatch, tmp_path)
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            set_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Report Set"},
                headers=_bearer(seeded["write_token"]),
            ).json()
            resp = client.get(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{set_resp['id']}/report",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["exists"] is False

    def test_generate_requires_write_scope(self, temp_db, tmp_path, monkeypatch):
        self._patch_report_root(monkeypatch, tmp_path)
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            set_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Report Set 2"},
                headers=_bearer(seeded["write_token"]),
            ).json()
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{set_resp['id']}/generate-report",
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 403

    def test_generate_then_lookup_reports_exists(self, temp_db, tmp_path, monkeypatch):
        self._patch_report_root(monkeypatch, tmp_path)
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            set_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets",
                json={"name": "Report Set 3"},
                headers=_bearer(seeded["write_token"]),
            ).json()
            generate_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{set_resp['id']}/generate-report",
                headers=_bearer(seeded["write_token"]),
            )
            assert generate_resp.status_code == 200, generate_resp.text
            assert generate_resp.json()["success"] is True
            assert (tmp_path / "reports" / f"team-{seeded['team_id']}-set-{set_resp['id']}.html").exists()

            lookup_resp = client.get(
                f"/api/app/teams/{seeded['team_id']}/test-run-sets/{set_resp['id']}/report",
                headers=_bearer(seeded["read_token"]),
            )
            assert lookup_resp.status_code == 200, lookup_resp.text
            assert lookup_resp.json()["exists"] is True
