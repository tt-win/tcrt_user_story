from pathlib import Path
import sys
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.models.database_models import Base, Team, AdHocRun, AdHocRunSheet, AdHocRunItem
from app.models.lark_types import Priority
from app.models.test_run_config import TestRunStatus as RunStatus


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_case_repo.db"
    sync_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"timeout": 30},
        pool_pre_ping=True,
    )

    TestingSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)
    AsyncTestingSessionLocal = async_sessionmaker(
        bind=async_engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )
    Base.metadata.create_all(bind=sync_engine)

    import app.database as app_database

    monkeypatch.setattr(app_database, "engine", async_engine)
    monkeypatch.setattr(app_database, "SessionLocal", AsyncTestingSessionLocal)

    async def override_get_db():
        async with AsyncTestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        username="pytest-admin",
        full_name="Pytest Admin",
        role=UserRole.SUPER_ADMIN,
    )

    yield TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    asyncio.run(async_engine.dispose())
    sync_engine.dispose()


def _seed_adhoc_run(session):
    team = Team(
        name="QA Team",
        description="",
        wiki_token="wiki-team-1",
        test_case_table_id="tbl-team-1",
    )
    session.add(team)
    session.commit()

    run = AdHocRun(
        team_id=team.id,
        name="AdHoc Run",
        description="",
        status=RunStatus.ACTIVE,
    )
    session.add(run)
    session.commit()
    return run.id


def test_create_sheet_returns_items_without_lazyload_error(temp_db):
    SessionLocal = temp_db
    client = TestClient(app)

    with SessionLocal() as session:
        run_id = _seed_adhoc_run(session)

    response = client.post(
        f"/api/adhoc-runs/{run_id}/sheets",
        json={"name": "Sheet A", "sort_order": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["adhoc_run_id"] == run_id
    assert payload["name"] == "Sheet A"
    assert payload["sort_order"] == 1
    assert payload["items"] == []


def test_update_sheet_returns_items_without_lazyload_error(temp_db):
    SessionLocal = temp_db
    client = TestClient(app)

    with SessionLocal() as session:
        run_id = _seed_adhoc_run(session)
        sheet = AdHocRunSheet(adhoc_run_id=run_id, name="Sheet Old", sort_order=0)
        session.add(sheet)
        session.flush()
        item = AdHocRunItem(
            sheet_id=sheet.id,
            row_index=0,
            test_case_number="TC-1",
            title="Case 1",
            priority=Priority.MEDIUM,
        )
        session.add(item)
        session.commit()
        sheet_id = sheet.id
        item_id = item.id

    response = client.put(
        f"/api/adhoc-runs/{run_id}/sheets/{sheet_id}",
        json={"name": "Sheet New", "sort_order": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == sheet_id
    assert payload["name"] == "Sheet New"
    assert payload["sort_order"] == 3
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == item_id
