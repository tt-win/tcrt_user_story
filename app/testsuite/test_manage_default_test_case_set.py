from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import and_

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.models.database_models import Team, TestCaseSet, TestCaseSection
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    sync_engine = database_bundle["sync_engine"]
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )
    
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        username="pytest-admin",
        full_name="Pytest Admin",
        role=UserRole.SUPER_ADMIN,
    )

    yield sync_engine, TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(database_bundle)

@pytest.fixture
def test_data(temp_db):
    sync_engine, TestingSessionLocal = temp_db
    with TestingSessionLocal() as session:
        team = Team(name="Test Team", wiki_token="test_token", test_case_table_id="test_table")
        session.add(team)
        session.commit()

        set1 = TestCaseSet(team_id=team.id, name="Set 1", is_default=True)
        set2 = TestCaseSet(team_id=team.id, name="Set 2", is_default=False)
        session.add_all([set1, set2])
        session.commit()
        
        return {
            "team_id": team.id,
            "set1_id": set1.id,
            "set2_id": set2.id,
        }

def test_set_default_success_and_atomicity(temp_db, test_data):
    sync_engine, TestingSessionLocal = temp_db
    
    client = TestClient(app)
    team_id = test_data["team_id"]
    set2_id = test_data["set2_id"]

    response = client.put(f"/api/teams/{team_id}/test-case-sets/{set2_id}/default")
    assert response.status_code == 200
    
    with TestingSessionLocal() as session:
        # Check defaults are updated
        set1 = session.query(TestCaseSet).filter(TestCaseSet.id == test_data["set1_id"]).first()
        set2 = session.query(TestCaseSet).filter(TestCaseSet.id == test_data["set2_id"]).first()
        assert not set1.is_default
        assert set2.is_default
        
        # Check unassigned section is created
        unassigned = session.query(TestCaseSection).filter(
            and_(
                TestCaseSection.test_case_set_id == set2.id,
                TestCaseSection.name == "Unassigned"
            )
        ).first()
        assert unassigned is not None

def test_set_default_forbidden_for_normal_user(temp_db, test_data):
    # Override to normal user
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=2,
        username="pytest-user",
        full_name="Pytest User",
        role=UserRole.USER,
    )
    
    client = TestClient(app)
    team_id = test_data["team_id"]
    set2_id = test_data["set2_id"]

    response = client.put(f"/api/teams/{team_id}/test-case-sets/{set2_id}/default")
    assert response.status_code == 403
    assert "僅管理員" in response.json()["detail"]
