from datetime import datetime
from pathlib import Path
import sys
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.api.test_run_items import TestRunItemUpdate
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.models.database_models import Team, TestRunConfig, TestRunItem, TestCaseLocal, TestCaseSet
from app.models.lark_types import TestResultStatus, Priority
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


def _prepare_schema_with_missing_backup(engine):
    with engine.begin() as conn:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=OFF"))
        
        conn.execute(text("DROP TABLE IF EXISTS test_run_item_result_history"))
        conn.execute(text("DROP TABLE IF EXISTS test_run_items_backup_snapshot"))
        
        # Use simple standard DDL for cross-database compatibility (ignoring foreign key constraints for this test)
        conn.execute(
            text(
                "CREATE TABLE test_run_items_backup_snapshot ("
                "    id INTEGER PRIMARY KEY,"
                "    team_id INTEGER NOT NULL,"
                "    config_id INTEGER NOT NULL"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE test_run_item_result_history ("
                "    id INTEGER PRIMARY KEY,"
                "    team_id INTEGER NOT NULL,"
                "    config_id INTEGER NOT NULL,"
                "    item_id INTEGER NOT NULL,"
                "    prev_result VARCHAR(50),"
                "    new_result VARCHAR(50),"
                "    prev_executed_at DATETIME,"
                "    new_executed_at DATETIME,"
                "    changed_by_id VARCHAR(50),"
                "    changed_by_name VARCHAR(255),"
                "    change_source VARCHAR(50),"
                "    change_reason TEXT,"
                "    changed_at DATETIME"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX ix_result_history_team_config ON test_run_item_result_history (team_id, config_id)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX ix_result_history_item_time ON test_run_item_result_history (item_id, changed_at)"
            )
        )
        conn.execute(text("DROP TABLE test_run_items_backup_snapshot"))
        
        if dialect == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=ON"))

def _seed_base_data(session):
    team = Team(
        name="QA Team",
        description="",
        wiki_token="wiki-token",
        test_case_table_id="tbl-1",
    )
    session.add(team)
    session.commit()

    default_case_set = TestCaseSet(
        team_id=team.id,
        name=f"Default-{team.id}",
        description="",
        is_default=True,
    )
    session.add(default_case_set)
    session.commit()

    config = TestRunConfig(
        team_id=team.id,
        name="Smoke",
        description="",
    )
    config.test_case_set_ids_json = f"[{default_case_set.id}]"
    session.add(config)

    case = TestCaseLocal(
        team_id=team.id,
        test_case_set_id=default_case_set.id,
        test_case_number="TC-1",
        title="Login",
        priority=Priority.MEDIUM,
    )
    session.add(case)
    session.commit()

    item = TestRunItem(
        team_id=team.id,
        config_id=config.id,
        test_case_number=case.test_case_number,
    )
    session.add(item)
    session.commit()
    return team.id, config.id, item.id


def test_update_result_succeeds_without_snapshot_table(temp_db):
    engine, SessionLocal = temp_db

    _prepare_schema_with_missing_backup(engine)

    session = SessionLocal()
    team_id, config_id, item_id = _seed_base_data(session)
    session.close()

    client = TestClient(app)

    payload = TestRunItemUpdate(
        test_result=TestResultStatus.PASSED,
        executed_at=datetime.utcnow(),
    )

    response = client.put(
        f"/api/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}",
        data=payload.model_dump_json(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200

    session = SessionLocal()
    refreshed = session.query(TestRunItem).filter(TestRunItem.id == item_id).one()
    assert refreshed.test_result == TestResultStatus.PASSED
    session.close()
