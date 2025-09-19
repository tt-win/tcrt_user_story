from datetime import datetime
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.api.test_run_items import TestRunItemUpdate
from app.database import get_db
from app.models.database_models import Base, Team, TestRunConfig, TestRunItem, TestCaseLocal
from app.models.lark_types import TestResultStatus, Priority


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_case_repo.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )

    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    import app.database as app_database

    monkeypatch.setattr(app_database, "engine", engine)
    monkeypatch.setattr(app_database, "SessionLocal", TestingSessionLocal)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield engine, TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _prepare_schema_with_missing_backup(engine):
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("DROP TABLE IF EXISTS test_run_item_result_history"))
        conn.execute(text("DROP TABLE IF EXISTS test_run_items_backup_snapshot"))
        conn.execute(
            text(
                "CREATE TABLE test_run_items_backup_snapshot (\n"
                "    id INTEGER PRIMARY KEY,\n"
                "    team_id INTEGER NOT NULL,\n"
                "    config_id INTEGER NOT NULL\n"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE test_run_item_result_history (\n"
                "    id INTEGER PRIMARY KEY,\n"
                "    team_id INTEGER NOT NULL,\n"
                "    config_id INTEGER NOT NULL,\n"
                "    item_id INTEGER NOT NULL,\n"
                "    prev_result VARCHAR,\n"
                "    new_result VARCHAR,\n"
                "    prev_executed_at DATETIME,\n"
                "    new_executed_at DATETIME,\n"
                "    changed_by_id VARCHAR,\n"
                "    changed_by_name VARCHAR,\n"
                "    change_source VARCHAR,\n"
                "    change_reason TEXT,\n"
                "    changed_at DATETIME,\n"
                "    FOREIGN KEY(team_id) REFERENCES teams (id),\n"
                "    FOREIGN KEY(config_id) REFERENCES test_run_configs (id),\n"
                "    FOREIGN KEY(item_id) REFERENCES test_run_items_backup_snapshot (id) ON DELETE CASCADE\n"
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

    config = TestRunConfig(
        team_id=team.id,
        name="Smoke",
        description="",
    )
    session.add(config)

    case = TestCaseLocal(
        team_id=team.id,
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

    from app.models.database_models import ensure_test_run_item_history_fk

    ensure_test_run_item_history_fk(engine)

    client = TestClient(app)

    with engine.connect() as conn:
        sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name='test_run_item_result_history'")
        ).scalar_one()
        assert "test_run_items_backup_snapshot" not in (sql or "")

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
