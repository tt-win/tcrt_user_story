"""Tests for /api/admin/knowledge-query-logs (openspec: log-knowledge-graph-queries)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.audit.database import (
    KnowledgeQueryLogTable,
    KnowledgeQuerySource,
    KnowledgeQueryOperation,
    KnowledgeQueryStatus,
)
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.database import get_db
from app.main import app
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_audit_database_overrides,
    install_main_database_overrides,
)


KQL_URL = "/api/admin/knowledge-query-logs"


@pytest.fixture
def kql_env(tmp_path, monkeypatch):
    main_bundle = create_managed_test_database(tmp_path / "kql_main.db")
    audit_bundle = create_managed_test_database(
        tmp_path / "kql_audit.db", target_name="audit"
    )

    # Seed super + normal user in main DB
    from app.models.database_models import User

    with main_bundle["sync_session_factory"]() as session:
        super_user = User(
            username="kql-super",
            email="kql-super@example.com",
            hashed_password="x",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
        )
        normal_user = User(
            username="kql-normal",
            email="kql-normal@example.com",
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
    install_audit_database_overrides(
        monkeypatch=monkeypatch,
        async_session_factory=audit_bundle["async_session_factory"],
    )

    # Seed a few query log rows
    async def _seed():
        async with audit_bundle["async_session_factory"]() as session:
            rows = [
                KnowledgeQueryLogTable(
                    timestamp=datetime.utcnow() - timedelta(hours=2),
                    source=KnowledgeQuerySource.ASSISTANT.value,
                    operation=KnowledgeQueryOperation.SEARCH.value,
                    status=KnowledgeQueryStatus.SUCCESS.value,
                    user_id=42,
                    username="alice",
                    query_text="login test",
                    primary_team_id=1,
                    result_count=3,
                    schema_version=1,
                ),
                KnowledgeQueryLogTable(
                    timestamp=datetime.utcnow() - timedelta(hours=1),
                    source=KnowledgeQuerySource.API.value,
                    operation=KnowledgeQueryOperation.IMPACT.value,
                    status=KnowledgeQueryStatus.DEGRADED.value,
                    user_id=99,
                    username="bob",
                    query_text="impact:TC-1",
                    primary_team_id=2,
                    result_count=0,
                    schema_version=1,
                ),
                KnowledgeQueryLogTable(
                    timestamp=datetime.utcnow(),
                    source=KnowledgeQuerySource.QA_HELPER.value,
                    operation=KnowledgeQueryOperation.SEARCH.value,
                    status=KnowledgeQueryStatus.SUCCESS.value,
                    user_id=42,
                    username="alice",
                    query_text="qa helper query",
                    primary_team_id=1,
                    result_count=5,
                    schema_version=1,
                ),
            ]
            session.add_all(rows)
            await session.commit()

    import asyncio
    asyncio.run(_seed())

    yield {"super_id": super_id, "normal_id": normal_id, "audit": audit_bundle}

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(audit_bundle)
    dispose_managed_test_database(main_bundle)


def _login(user_id, username, role) -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id, username=username, role=role
    )


def test_anonymous_rejected(kql_env) -> None:
    client = TestClient(app)
    resp = client.get(KQL_URL)
    assert resp.status_code in (401, 403)


def test_non_super_admin_rejected(kql_env) -> None:
    _login(kql_env["normal_id"], "kql-normal", UserRole.USER)
    client = TestClient(app)
    resp = client.get(KQL_URL)
    assert resp.status_code == 403


def test_super_admin_lists_all(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    resp = client.get(KQL_URL)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    payload = resp.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    # most recent first
    assert payload["items"][0]["username"] == "alice"
    assert payload["items"][0]["source"] == "qa_helper"


def test_filter_by_source(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    resp = client.get(KQL_URL, params={"source": "api"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["source"] == "api"
    assert payload["items"][0]["operation"] == "impact"


def test_filter_by_status(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    resp = client.get(KQL_URL, params={"status": "degraded"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["status"] == "degraded"


def test_filter_by_team_id(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    resp = client.get(KQL_URL, params={"team_id": 1})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 2
    for item in payload["items"]:
        assert item["primary_team_id"] == 1


def test_filter_by_user_id(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    resp = client.get(KQL_URL, params={"user_id": 99})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["username"] == "bob"


def test_filter_by_time_range(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    now = datetime.utcnow()
    resp = client.get(
        KQL_URL,
        params={
            "start_time": (now - timedelta(minutes=30)).isoformat(),
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1  # 只有最新的那筆
    assert payload["items"][0]["source"] == "qa_helper"


def test_filter_by_query_text(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    resp = client.get(KQL_URL, params={"query_text": "login"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert "login" in (payload["items"][0]["query_text"] or "")


def test_pagination(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    resp = client.get(KQL_URL, params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2
    assert payload["total_pages"] == 2


def test_get_single_log(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    # find id first
    list_resp = client.get(KQL_URL)
    first_id = list_resp.json()["items"][0]["id"]
    detail = client.get(f"{KQL_URL}/{first_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == first_id
    assert "results_summary" in payload
    assert "process" in payload


def test_get_404(kql_env) -> None:
    _login(kql_env["super_id"], "kql-super", UserRole.SUPER_ADMIN)
    client = TestClient(app)
    resp = client.get(f"{KQL_URL}/99999")
    assert resp.status_code == 404
