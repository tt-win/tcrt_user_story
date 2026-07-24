"""DB-backed assistant prompt/skills + Super Admin API (assistant-prompt-skills-admin)."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.dependencies import get_current_user  # noqa: E402
from app.auth.models import UserRole  # noqa: E402
from app.database import get_db  # noqa: E402
from app.db_access.main import get_main_access_boundary  # noqa: E402
from app.main import app  # noqa: E402
from app.models.database_models import User  # noqa: E402
from app.services.assistant import content_store as store  # noqa: E402
from app.services.assistant.content_store import (  # noqa: E402
    SKILL_CATALOG_TOKEN,
    assemble_system_prompt_for_agent,
    ensure_seeded,
    get_skill_enabled,
    list_enabled_skills,
    load_factory_system_prompt,
)
from app.testsuite.db_test_helpers import (  # noqa: E402
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def content_env(tmp_path, monkeypatch):
    main_bundle = create_managed_test_database(tmp_path / "asst_content.db")
    with main_bundle["sync_session_factory"]() as session:
        super_user = User(
            username="c-super",
            email="c-super@example.com",
            hashed_password="x",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
        )
        normal_user = User(
            username="c-user",
            email="c-user@example.com",
            hashed_password="x",
            role=UserRole.USER,
            is_active=True,
            is_verified=True,
        )
        session.add_all([super_user, normal_user])
        session.commit()
        super_id, normal_id = super_user.id, normal_user.id

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=main_bundle["async_engine"],
        async_session_factory=main_bundle["async_session_factory"],
    )
    store.invalidate_content_cache()

    def set_user(role: UserRole, uid: int):
        user = User(id=uid, username="x", email="x@x.com", hashed_password="x", role=role, is_active=True)

        async def _override():
            return user

        app.dependency_overrides[get_current_user] = _override

    yield {
        "super_id": super_id,
        "normal_id": normal_id,
        "set_user": set_user,
        "boundary": get_main_access_boundary(),
    }

    app.dependency_overrides.clear()
    dispose_managed_test_database(main_bundle)


@pytest.mark.asyncio
async def test_ensure_seeded_inserts_factory_and_is_idempotent(content_env):
    b = content_env["boundary"]
    # Migration may already seed; ensure_seeded must still leave a full factory catalog.
    await ensure_seeded(b)
    skills = await list_enabled_skills(b)
    assert any(s["skill_id"] == "assign-run-items-by-case-prefix" for s in skills)
    s2 = await ensure_seeded(b)
    assert s2["prompts"] == 0 and s2["skills"] == 0


@pytest.mark.asyncio
async def test_disable_hides_skill_from_agent(content_env):
    b = content_env["boundary"]
    await ensure_seeded(b)
    await store.update_skill(
        b, "assign-run-items-by-case-prefix", is_enabled=False, updated_by="test"
    )
    store.invalidate_content_cache()
    enabled = await list_enabled_skills(b)
    assert all(s["skill_id"] != "assign-run-items-by-case-prefix" for s in enabled)
    assert await get_skill_enabled(b, "assign-run-items-by-case-prefix") is None
    catalog = await assemble_system_prompt_for_agent(b)
    assert "assign-run-items-by-case-prefix" not in catalog


def test_super_admin_prompt_put_version_and_stale(content_env):
    content_env["set_user"](UserRole.SUPER_ADMIN, content_env["super_id"])
    client = TestClient(app)
    r = client.get("/api/admin/assistant/system-prompt")
    assert r.status_code == 200, r.text
    data = r.json()
    version = data["version"]
    content = data["content"]
    assert SKILL_CATALOG_TOKEN in content

    bad = client.put(
        "/api/admin/assistant/system-prompt",
        json={"content": content.replace(SKILL_CATALOG_TOKEN, ""), "expected_version": version},
    )
    assert bad.status_code == 422

    ok = client.put(
        "/api/admin/assistant/system-prompt",
        json={"content": content, "expected_version": version},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["version"] == version + 1

    stale = client.put(
        "/api/admin/assistant/system-prompt",
        json={"content": content, "expected_version": version},
    )
    assert stale.status_code == 409


def test_non_super_admin_forbidden(content_env):
    content_env["set_user"](UserRole.USER, content_env["normal_id"])
    client = TestClient(app)
    assert client.get("/api/admin/assistant/system-prompt").status_code == 403
    assert client.get("/api/admin/assistant/skills").status_code == 403
    assert client.post(
        "/api/admin/assistant/skills",
        json={
            "skill_id": "x-custom",
            "name": "n",
            "description": "d",
            "body": "b" * 50,
        },
    ).status_code == 403


def test_builtin_delete_allowed_and_custom_crud(content_env):
    content_env["set_user"](UserRole.SUPER_ADMIN, content_env["super_id"])
    client = TestClient(app)
    # seed
    assert client.get("/api/admin/assistant/skills").status_code == 200

    # Builtin skills CAN be deleted from the database. The UI gates this with
    # a second confirmation, but the API itself permits it: Super Admin is
    # trusted to understand the consequence (next overwrite-builtins restore
    # re-inserts the row).
    deleted_builtin = client.delete("/api/admin/assistant/skills/assign-run-items-by-case-prefix")
    assert deleted_builtin.status_code == 200, deleted_builtin.text
    body = deleted_builtin.json()
    assert body.get("ok") is True
    assert body.get("was_builtin") is True
    assert body.get("skill_id") == "assign-run-items-by-case-prefix"

    # Re-seed for downstream tests (the row must come back via the
    # overwrite-builtins restore path).
    restore = client.post(
        "/api/admin/assistant/restore",
        json={"mode": "overwrite-builtins", "confirm": True},
    )
    assert restore.status_code == 200, restore.text

    created = client.post(
        "/api/admin/assistant/skills",
        json={
            "skill_id": "my-custom-flow",
            "name": "Custom",
            "description": "desc",
            "body": "# custom body\n\nUse batch tools.",
            "triggers": ["custom"],
        },
    )
    assert created.status_code == 201, created.text

    reserved = client.post(
        "/api/admin/assistant/skills",
        json={
            "skill_id": "archive-not-delete",
            "name": "x",
            "description": "d",
            "body": "body text enough",
        },
    )
    assert reserved.status_code == 422

    deleted = client.delete("/api/admin/assistant/skills/my-custom-flow")
    assert deleted.status_code == 200


def test_overwrite_builtins_keeps_disabled_flag(content_env):
    content_env["set_user"](UserRole.SUPER_ADMIN, content_env["super_id"])
    client = TestClient(app)
    client.get("/api/admin/assistant/skills")
    client.put(
        "/api/admin/assistant/skills/assign-run-items-by-case-prefix",
        json={"is_enabled": False},
    )
    r = client.post(
        "/api/admin/assistant/restore",
        json={"mode": "overwrite-builtins", "confirm": True},
    )
    assert r.status_code == 200, r.text
    detail = client.get("/api/admin/assistant/skills/assign-run-items-by-case-prefix")
    assert detail.status_code == 200
    assert detail.json()["is_enabled"] is False


def test_factory_system_has_catalog_token():
    text = load_factory_system_prompt()
    assert text and text.count(SKILL_CATALOG_TOKEN) == 1


def test_overwrite_requires_confirm(content_env):
    content_env["set_user"](UserRole.SUPER_ADMIN, content_env["super_id"])
    client = TestClient(app)
    r = client.post(
        "/api/admin/assistant/restore",
        json={"mode": "overwrite-builtins", "confirm": False},
    )
    assert r.status_code == 400


def test_toggle_enabled_only_and_create_then_update(content_env):
    """Mirrors the admin UI payloads for enable/disable, create, and full edit."""
    content_env["set_user"](UserRole.SUPER_ADMIN, content_env["super_id"])
    client = TestClient(app)
    client.get("/api/admin/assistant/skills")

    # enable/disable with partial body (table checkbox)
    off = client.put(
        "/api/admin/assistant/skills/assign-run-items-by-case-prefix",
        json={"is_enabled": False},
    )
    assert off.status_code == 200, off.text
    assert off.json()["is_enabled"] is False
    on = client.put(
        "/api/admin/assistant/skills/assign-run-items-by-case-prefix",
        json={"is_enabled": True},
    )
    assert on.status_code == 200, on.text
    assert on.json()["is_enabled"] is True

    # create with mixed-case id (UI normalizes; API also normalizes)
    created = client.post(
        "/api/admin/assistant/skills",
        json={
            "skill_id": "My_UI_Flow",
            "name": "UI Flow",
            "description": "from admin ui",
            "body": "# steps\n\n1. list\n2. batch\n",
            "triggers": ["ui"],
            "is_enabled": True,
            "sort_order": 99,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["skill_id"] == "my-ui-flow"

    # full edit
    updated = client.put(
        "/api/admin/assistant/skills/my-ui-flow",
        json={
            "name": "UI Flow 2",
            "description": "updated",
            "body": "# steps\n\nupdated body\n",
            "triggers": ["ui", "edit"],
            "is_enabled": False,
            "sort_order": 100,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "UI Flow 2"
    assert updated.json()["is_enabled"] is False
