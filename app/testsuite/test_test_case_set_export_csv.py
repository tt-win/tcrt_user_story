"""Test Case Set CSV 匯出 API 行為測試"""

import csv
import io
import json
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.models.database_models import (
    Team,
    TestCaseSet,
    TestCaseSection,
    TestCaseLocal,
)
from app.models.lark_types import Priority, TestResultStatus
from app.api.test_case_sets import TEST_CASE_SET_CSV_COLUMNS
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
    created_at = datetime(2026, 1, 15, 10, 30, 0)
    updated_at = datetime(2026, 1, 16, 12, 0, 0)
    last_sync_at = datetime(2026, 1, 17, 9, 15, 0)

    with TestingSessionLocal() as session:
        team = Team(name="Export Team", wiki_token="tok", test_case_table_id="tbl")
        other_team = Team(name="Other Team", wiki_token="tok2", test_case_table_id="tbl2")
        session.add_all([team, other_team])
        session.commit()

        target_set = TestCaseSet(team_id=team.id, name="Target Set", is_default=True)
        empty_set = TestCaseSet(team_id=team.id, name="Empty Set", is_default=False)
        other_set = TestCaseSet(team_id=other_team.id, name="Other Team Set", is_default=True)
        session.add_all([target_set, empty_set, other_set])
        session.commit()

        section = TestCaseSection(
            test_case_set_id=target_set.id,
            name="Smoke",
            level=1,
            sort_order=0,
        )
        session.add(section)
        session.commit()

        case1 = TestCaseLocal(
            team_id=team.id,
            test_case_set_id=target_set.id,
            test_case_section_id=section.id,
            lark_record_id="rec-1",
            test_case_number="TC-001",
            title="Login, happy path",
            priority=Priority.HIGH,
            precondition="Line 1\nLine 2",
            steps="1. Open\n2. Submit",
            expected_result="User sees dashboard",
            test_result=TestResultStatus.PASSED,
            assignee_json=json.dumps({"name": "Ada", "email": "ada@example.com"}, ensure_ascii=False),
            attachments_json=json.dumps(
                [{"name": "evidence.png", "stored_name": "evidence.png"}], ensure_ascii=False
            ),
            test_results_files_json=json.dumps([{"name": "result.log"}], ensure_ascii=False),
            user_story_map_json=json.dumps([{"display_text": "USM-1"}], ensure_ascii=False),
            tcg_json=json.dumps(["TCG-1", "TP-2"], ensure_ascii=False),
            parent_record_json=json.dumps([{"record_id": "parent-1"}], ensure_ascii=False),
            raw_fields_json=json.dumps({"Custom": "值"}, ensure_ascii=False),
            test_data_json=json.dumps(
                [{"name": "account", "value": "demo"}], ensure_ascii=False
            ),
            created_at=created_at,
            updated_at=updated_at,
            last_sync_at=last_sync_at,
        )
        case2 = TestCaseLocal(
            team_id=team.id,
            test_case_set_id=target_set.id,
            test_case_section_id=None,
            lark_record_id="rec-2",
            test_case_number="TC-002",
            title="Logout",
            priority=Priority.MEDIUM,
            precondition=None,
            steps="Click logout",
            expected_result="User is logged out",
            test_result=None,
            created_at=created_at,
            updated_at=updated_at,
            last_sync_at=last_sync_at,
        )
        # Belongs to other team's set — must NOT appear in target set export
        other_case = TestCaseLocal(
            team_id=other_team.id,
            test_case_set_id=other_set.id,
            test_case_section_id=None,
            lark_record_id="rec-other",
            test_case_number="TC-OTHER",
            title="Other team case",
            priority=Priority.LOW,
        )
        session.add_all([case1, case2, other_case])
        session.commit()

        return {
            "team_id": team.id,
            "other_team_id": other_team.id,
            "target_set_id": target_set.id,
            "empty_set_id": empty_set.id,
            "other_set_id": other_set.id,
            "section_id": section.id,
        }


def _parse_csv_response(response):
    text = response.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return rows


def test_export_csv_returns_complete_header_and_set_rows(temp_db, test_data):
    client = TestClient(app)
    team_id = test_data["team_id"]
    set_id = test_data["target_set_id"]

    response = client.get(f"/api/teams/{team_id}/test-case-sets/{set_id}/export-csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    assert "attachment; filename=test_case_set_" in response.headers.get("content-disposition", "")

    rows = _parse_csv_response(response)
    assert rows[0] == TEST_CASE_SET_CSV_COLUMNS
    # Header + 2 data rows (case1, case2), no other-team case
    assert len(rows) == 3
    numbers = [r[0] for r in rows[1:]]
    assert "TC-001" in numbers
    assert "TC-002" in numbers
    assert "TC-OTHER" not in numbers


def test_export_csv_preserves_multiline_and_json_fields(temp_db, test_data):
    client = TestClient(app)
    team_id = test_data["team_id"]
    set_id = test_data["target_set_id"]

    response = client.get(f"/api/teams/{team_id}/test-case-sets/{set_id}/export-csv")
    assert response.status_code == 200

    rows = _parse_csv_response(response)
    header = rows[0]
    idx = {col: i for i, col in enumerate(header)}

    tc001 = None
    for row in rows[1:]:
        if row[idx["test_case_number"]] == "TC-001":
            tc001 = row
            break
    assert tc001 is not None, "TC-001 row not found"

    # Multiline text preserved
    assert tc001[idx["precondition"]] == "Line 1\nLine 2"
    # JSON fields are compact JSON
    assert json.loads(tc001[idx["tcg"]]) == ["TCG-1", "TP-2"]
    assert json.loads(tc001[idx["test_data"]]) == [{"name": "account", "value": "demo"}]
    # Section metadata
    assert tc001[idx["section_name"]] == "Smoke"
    assert tc001[idx["priority"]] == "High"


def test_export_csv_empty_set_returns_header_only(temp_db, test_data):
    client = TestClient(app)
    team_id = test_data["team_id"]
    empty_set_id = test_data["empty_set_id"]

    response = client.get(f"/api/teams/{team_id}/test-case-sets/{empty_set_id}/export-csv")
    assert response.status_code == 200

    rows = _parse_csv_response(response)
    assert len(rows) == 1
    assert rows[0] == TEST_CASE_SET_CSV_COLUMNS


def test_export_csv_missing_or_wrong_team_set_returns_404(temp_db, test_data):
    client = TestClient(app)
    team_id = test_data["team_id"]
    other_team_id = test_data["other_team_id"]
    target_set_id = test_data["target_set_id"]

    # Non-existent set
    response = client.get(f"/api/teams/{team_id}/test-case-sets/999999/export-csv")
    assert response.status_code == 404

    # Wrong team trying to access target set
    response = client.get(f"/api/teams/{other_team_id}/test-case-sets/{target_set_id}/export-csv")
    assert response.status_code == 404
