"""Tests for app token test case mutation API."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
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
    Team,
    TeamAppToken,
    TeamAppTokenStatus,
    TestCaseSet,
    User,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_app_tc_mut.db")
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
        scopes = ["test_case:read", "test_case:write", "test_case:admin"]

    team = Team(
        name="TC Mutation Team",
        description="Test",
        wiki_token="secret",
        test_case_table_id="tbl-tc",
    )
    session.add(team)
    session.commit()

    user = User(
        username="creator",
        email="creator@example.com",
        full_name="Creator",
        role="admin",
        is_active=True,
        hashed_password="dummy",
    )
    session.add(user)
    session.commit()

    raw_token, token_hash, token_prefix = generate_app_token()
    token = TeamAppToken(
        name="tc-mutation-token",
        owner_team_id=team.id,
        token_hash=token_hash,
        token_prefix=token_prefix,
        status=TeamAppTokenStatus.ACTIVE,
        scopes_json=json.dumps(scopes),
        expires_at=datetime.utcnow() + timedelta(days=90),
        created_by_user_id=user.id,
    )
    session.add(token)

    read_only_raw, read_only_hash, read_only_prefix = generate_app_token()
    read_only_token = TeamAppToken(
        name="read-only-token",
        owner_team_id=team.id,
        token_hash=read_only_hash,
        token_prefix=read_only_prefix,
        status=TeamAppTokenStatus.ACTIVE,
        scopes_json=json.dumps(["test_case:read"]),
        expires_at=datetime.utcnow() + timedelta(days=90),
        created_by_user_id=user.id,
    )
    session.add(read_only_token)

    other_team = Team(
        name="Other Team",
        description="Other",
        wiki_token="secret-other",
        test_case_table_id="tbl-other",
    )
    session.add(other_team)
    session.commit()

    session.commit()

    return {
        "team_id": team.id,
        "other_team_id": other_team.id,
        "write_token": raw_token,
        "read_token": read_only_raw,
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestCreateTestCase:
    def test_create_test_case(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={
                    "test_case_number": "TC-API-001",
                    "title": "API Created Test",
                    "priority": "High",
                    "precondition": "Precondition",
                    "steps": "1. Step one",
                    "expected_result": "Expected result",
                },
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["test_case_number"] == "TC-API-001"
            assert data["title"] == "API Created Test"

    def test_create_duplicate_number_conflict(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-DUP-001", "title": "First"},
                headers=_bearer(seeded["write_token"]),
            )
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-DUP-001", "title": "Second"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 409

    def test_create_with_test_data(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={
                    "test_case_number": "TC-TD-001",
                    "title": "With Test Data",
                    "test_data": [
                        {"id": "td-1", "name": "email", "category": "email", "value": "test@example.com"},
                        {"id": "td-2", "name": "password", "category": "credential", "value": "secret123"},
                    ],
                },
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 201
            data = resp.json()
            assert len(data["test_data"]) == 2

    def test_read_only_token_cannot_create(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-RO-001", "title": "Should Fail"},
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 403


class TestUpdateTestCase:
    def test_update_test_case(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-UPD-001", "title": "Original"},
                headers=_bearer(seeded["write_token"]),
            )
            case_id = create_resp.json()["id"]

            resp = client.put(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{case_id}",
                json={"title": "Updated Title", "priority": "Low"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["title"] == "Updated Title"

    def test_update_nonexistent_404(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.put(
                f"/api/app/teams/{seeded['team_id']}/test-cases/99999",
                json={"title": "No Such Case"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 404


class TestDeleteTestCase:
    def test_delete_test_case_requires_admin(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session, scopes=["test_case:read", "test_case:write"])
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-DEL-001", "title": "To Delete"},
                headers=_bearer(seeded["write_token"]),
            )
            case_id = create_resp.json()["id"]

            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{case_id}",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 403

    def test_delete_with_admin_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-DEL-002", "title": "To Delete"},
                headers=_bearer(seeded["write_token"]),
            )
            case_id = create_resp.json()["id"]

            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{case_id}",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 204


class TestBatchCreate:
    def test_batch_create(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/batch",
                json={
                    "items": [
                        {"test_case_number": "TC-BATCH-001", "title": "Batch 1"},
                        {"test_case_number": "TC-BATCH-002", "title": "Batch 2"},
                        {"test_case_number": "TC-BATCH-003", "title": "Batch 3"},
                    ]
                },
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 3
            assert data["success_count"] == 3

    def test_batch_partial_failure(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-PARTIAL-001", "title": "Already exists"},
                headers=_bearer(seeded["write_token"]),
            )
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/batch",
                json={
                    "items": [
                        {"test_case_number": "TC-PARTIAL-001", "title": "Duplicate"},
                        {"test_case_number": "TC-PARTIAL-002", "title": "New one"},
                    ]
                },
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
            assert data["success_count"] == 1


class TestCrossTeamRejection:
    def test_create_denied_for_other_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['other_team_id']}/test-cases",
                json={"test_case_number": "TC-CROSS-001", "title": "Cross team"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 403


class TestTestDataValidation:
    def test_create_rejects_duplicate_test_data_names(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={
                    "test_case_number": "TC-TDV-001",
                    "title": "Dup test data",
                    "test_data": [
                        {"name": "email", "category": "email", "value": "a@example.com"},
                        {"name": "email", "category": "email", "value": "b@example.com"},
                    ],
                },
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 400, resp.text


class TestCaseSetAndSectionManagement:
    def test_create_requires_admin_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session, scopes=["test_case:read", "test_case:write"])
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets",
                json={"name": f"Set-NoAdmin-{seeded['team_id']}"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 403

    def test_create_update_delete_set(self, temp_db):
        from app.services.test_case_set_service import TestCaseSetService

        with temp_db() as session:
            seeded = _seed_data(session)
            # `TestCaseSetService.delete` moves orphaned cases into the team's default
            # set (with its "Unassigned" section), so one must exist first — mirrors
            # real usage where creating any test case auto-provisions the default set.
            TestCaseSetService.get_or_create_default_sync(session, seeded["team_id"])
            session.commit()
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets",
                json={"name": f"Set-CRUD-{seeded['team_id']}", "description": "d"},
                headers=_bearer(seeded["write_token"]),
            )
            assert create_resp.status_code == 201, create_resp.text
            set_id = create_resp.json()["id"]

            update_resp = client.put(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets/{set_id}",
                json={"name": f"Set-CRUD-Renamed-{seeded['team_id']}"},
                headers=_bearer(seeded["write_token"]),
            )
            assert update_resp.status_code == 200, update_resp.text

            preview_resp = client.get(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets/{set_id}/impact-preview",
                headers=_bearer(seeded["write_token"]),
            )
            assert preview_resp.status_code == 200, preview_resp.text
            assert "impacted_item_count" in preview_resp.json()

            delete_resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets/{set_id}",
                headers=_bearer(seeded["write_token"]),
            )
            assert delete_resp.status_code == 200, delete_resp.text
            assert delete_resp.json()["success"] is True

    def test_set_not_found_for_other_team(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
            other_set = TestCaseSet(name=f"Other-{seeded['other_team_id']}", team_id=seeded["other_team_id"])
            session.add(other_set)
            session.commit()
            other_set_id = other_set.id
        with TestClient(app) as client:
            resp = client.put(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets/{other_set_id}",
                json={"name": "hijack"},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 404

    def test_create_update_delete_section(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            set_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets",
                json={"name": f"Set-Section-{seeded['team_id']}"},
                headers=_bearer(seeded["write_token"]),
            )
            set_id = set_resp.json()["id"]

            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets/{set_id}/sections",
                json={"name": "Section A"},
                headers=_bearer(seeded["write_token"]),
            )
            assert create_resp.status_code == 201, create_resp.text
            section_id = create_resp.json()["id"]

            update_resp = client.put(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets/{set_id}/sections/{section_id}",
                json={"name": "Section A Renamed"},
                headers=_bearer(seeded["write_token"]),
            )
            assert update_resp.status_code == 200, update_resp.text

            delete_resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-case-sets/{set_id}/sections/{section_id}",
                headers=_bearer(seeded["write_token"]),
            )
            assert delete_resp.status_code == 200, delete_resp.text


class TestAttachmentManagement:
    def test_upload_list_delete_attachment(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-ATT-001", "title": "Attachment case"},
                headers=_bearer(seeded["write_token"]),
            )
            case_id = create_resp.json()["id"]

            upload_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{case_id}/attachments",
                files={"files": ("note.txt", b"hello world", "text/plain")},
                headers=_bearer(seeded["write_token"]),
            )
            assert upload_resp.status_code == 201, upload_resp.text
            uploaded = upload_resp.json()["files"]
            assert len(uploaded) == 1
            assert "relative_path" in uploaded[0]
            assert "absolute_path" not in uploaded[0]

            list_resp = client.get(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{case_id}/attachments",
                headers=_bearer(seeded["write_token"]),
            )
            assert list_resp.status_code == 200
            assert list_resp.json()["count"] == 1

            target = uploaded[0]["stored_name"]
            delete_resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{case_id}/attachments/{target}",
                headers=_bearer(seeded["write_token"]),
            )
            assert delete_resp.status_code == 200, delete_resp.text

    def test_upload_requires_write_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-ATT-002", "title": "Attachment case"},
                headers=_bearer(seeded["write_token"]),
            )
            case_id = create_resp.json()["id"]

            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{case_id}/attachments",
                files={"files": ("note.txt", b"hello", "text/plain")},
                headers=_bearer(seeded["read_token"]),
            )
            assert resp.status_code == 403

    def test_delete_requires_admin_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session, scopes=["test_case:read", "test_case:write"])
        with TestClient(app) as client:
            create_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases",
                json={"test_case_number": "TC-ATT-003", "title": "Attachment case"},
                headers=_bearer(seeded["write_token"]),
            )
            case_id = create_resp.json()["id"]
            upload_resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{case_id}/attachments",
                files={"files": ("note.txt", b"hello", "text/plain")},
                headers=_bearer(seeded["write_token"]),
            )
            target = upload_resp.json()["files"][0]["stored_name"]

            resp = client.delete(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{case_id}/attachments/{target}",
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 403


class TestBatchOperationsAndBulkClone:
    def _create_case(self, client, seeded, number, title="Batch case"):
        resp = client.post(
            f"/api/app/teams/{seeded['team_id']}/test-cases",
            json={"test_case_number": number, "title": title},
            headers=_bearer(seeded["write_token"]),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_batch_update_priority(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            self._create_case(client, seeded, "TC-BOP-001")
            self._create_case(client, seeded, "TC-BOP-002")

            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/batch-operations",
                json={
                    "operation": "update_priority",
                    "record_ids": ["TC-BOP-001", "TC-BOP-002"],
                    "update_data": {"priority": "High"},
                },
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["success"] is True
            assert data["success_count"] == 2

    def test_batch_delete_requires_admin_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session, scopes=["test_case:read", "test_case:write"])
        with TestClient(app) as client:
            created = self._create_case(client, seeded, "TC-BOP-DEL-1")

            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/batch-operations",
                json={"operation": "delete", "record_ids": [str(created["id"])]},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 403

    def test_batch_delete_with_admin_and_partial_errors(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            created = self._create_case(client, seeded, "TC-BOP-DEL-2")

            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/batch-operations",
                json={"operation": "delete", "record_ids": [str(created["id"]), "TC-MISSING-999"]},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["success_count"] == 1
            assert data["error_count"] == 1

            detail = client.get(
                f"/api/app/teams/{seeded['team_id']}/test-cases/{created['id']}",
                headers=_bearer(seeded["write_token"]),
            )
            assert detail.status_code == 404

    def test_batch_unsupported_operation(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/batch-operations",
                json={"operation": "explode", "record_ids": ["TC-X"]},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 400

    def test_bulk_clone_success_then_duplicate_rejected(self, temp_db):
        with temp_db() as session:
            seeded = _seed_data(session)
        with TestClient(app) as client:
            source = self._create_case(client, seeded, "TC-CLONE-SRC", title="Source case")

            resp = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/bulk-clone",
                json={"items": [{"source_record_id": str(source["id"]), "test_case_number": "TC-CLONE-001"}]},
                headers=_bearer(seeded["write_token"]),
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["success"] is True
            assert data["created_count"] == 1

            dup = client.post(
                f"/api/app/teams/{seeded['team_id']}/test-cases/bulk-clone",
                json={"items": [{"source_record_id": str(source["id"]), "test_case_number": "TC-CLONE-001"}]},
                headers=_bearer(seeded["write_token"]),
            )
            assert dup.status_code == 200, dup.text
            assert dup.json()["success"] is False
            assert dup.json()["duplicates"] == ["TC-CLONE-001"]
