"""Tests for the org-level Automation Hub entry-visibility toggle API.

Covers the spec scenarios in `automation-hub-entry-toggle`:
- default enabled (true) when never set,
- Super Admin toggling persists,
- non-super-admin write rejected (403),
- unauthenticated read rejected.
"""

from pathlib import Path
import sys
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.auth.permission_service import permission_service
from app.database import get_db
from app.main import app
from app.models.database_models import User
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def toggle_test_env(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )

    current_user_ref = {"value": None}

    def override_get_current_user():
        return current_user_ref["value"]
    app.dependency_overrides[get_current_user] = override_get_current_user

    session = TestingSessionLocal()
    try:
        super_admin = User(
            username="super-admin",
            email="super-admin@example.com",
            hashed_password="x",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        admin = User(
            username="admin-user",
            email="admin-user@example.com",
            hashed_password="x",
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add_all([super_admin, admin])
        session.commit()
        super_admin_id = super_admin.id
        admin_id = admin.id
    finally:
        session.close()

    def set_user(role: UserRole, user_id: int):
        current_user_ref["value"] = SimpleNamespace(
            id=user_id,
            username=role.value,
            role=role.value,
            is_active=True,
        )

    set_user(UserRole.SUPER_ADMIN, super_admin_id)
    asyncio.run(permission_service.cache.clear_all())

    yield {
        "current_user_ref": current_user_ref,
        "super_admin_id": super_admin_id,
        "admin_id": admin_id,
        "set_user": set_user,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    asyncio.run(permission_service.cache.clear_all())
    dispose_managed_test_database(database_bundle)


def test_get_returns_default_enabled_true(toggle_test_env):
    client = TestClient(app)
    response = client.get("/api/system/automation-hub/settings")
    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_super_admin_can_toggle_off_and_persists(toggle_test_env):
    client = TestClient(app)

    put_resp = client.put(
        "/api/system/automation-hub/settings", json={"enabled": False}
    )
    assert put_resp.status_code == 200
    assert put_resp.json() == {"enabled": False}

    # Persisted: a fresh GET reflects the new state.
    get_resp = client.get("/api/system/automation-hub/settings")
    assert get_resp.status_code == 200
    assert get_resp.json() == {"enabled": False}

    # Toggling back on works too.
    put_back = client.put(
        "/api/system/automation-hub/settings", json={"enabled": True}
    )
    assert put_back.status_code == 200
    assert client.get("/api/system/automation-hub/settings").json() == {"enabled": True}


def test_non_super_admin_cannot_update(toggle_test_env):
    client = TestClient(app)
    toggle_test_env["set_user"](UserRole.ADMIN, toggle_test_env["admin_id"])
    asyncio.run(permission_service.cache.clear_all())

    resp = client.put(
        "/api/system/automation-hub/settings", json={"enabled": False}
    )
    assert resp.status_code == 403

    # State unchanged (still default enabled). Admin may still read.
    get_resp = client.get("/api/system/automation-hub/settings")
    assert get_resp.status_code == 200
    assert get_resp.json() == {"enabled": True}


def test_unauthenticated_get_rejected(toggle_test_env):
    # Drop the override so the real Bearer dependency runs; no auth header → 401/403.
    app.dependency_overrides.pop(get_current_user, None)
    client = TestClient(app)
    resp = client.get("/api/system/automation-hub/settings")
    assert resp.status_code in (401, 403)
