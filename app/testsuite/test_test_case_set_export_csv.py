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


def _seed_test_data_cases(TestingSessionLocal, cases):
    """建立獨立 team/set，寫入 (number -> test_data_json) 的多筆案例"""
    with TestingSessionLocal() as session:
        team = Team(name="TD Contract Team", wiki_token="tok-td", test_case_table_id="tbl-td")
        session.add(team)
        session.commit()

        target_set = TestCaseSet(team_id=team.id, name="TD Set", is_default=True)
        session.add(target_set)
        session.commit()

        for number, test_data_json in cases.items():
            session.add(
                TestCaseLocal(
                    team_id=team.id,
                    test_case_set_id=target_set.id,
                    test_case_number=number,
                    title=f"Case {number}",
                    priority=Priority.MEDIUM,
                    test_data_json=test_data_json,
                )
            )
        session.commit()
        return team.id, target_set.id


def _export_test_data_cells(client, team_id, set_id):
    response = client.get(f"/api/teams/{team_id}/test-case-sets/{set_id}/export-csv")
    assert response.status_code == 200
    rows = _parse_csv_response(response)
    idx = {col: i for i, col in enumerate(rows[0])}
    return {row[idx["test_case_number"]]: row[idx["test_data"]] for row in rows[1:]}


def test_export_csv_test_data_cell_contract(temp_db):
    """通過共用可 round-trip 判定的非空陣列保真輸出；其餘輸出空 cell"""
    sync_engine, TestingSessionLocal = temp_db
    valid_json = json.dumps(
        [
            {"id": "11111111-1111-1111-1111-111111111111", "name": "user", "category": "email", "value": "qa@example.com"},
            {"name": "password", "category": "credential", "value": "s3cret-plain"},
        ],
        ensure_ascii=False,
    )
    cases = {
        "TD-VALID": valid_json,
        "TD-NULL": None,
        "TD-EMPTY-STR": "",
        "TD-EMPTY-ARR": "[]",
        "TD-MALFORMED": "{not valid json",
        "TD-NON-ARRAY": json.dumps({"name": "x", "value": "y"}),
        "TD-SCALAR-ELEM": json.dumps([1]),
        "TD-MISSING-VALUE": json.dumps([{"name": "x"}]),
        "TD-NUMERIC-ID": json.dumps([{"id": 1, "name": "x", "value": "y"}]),
        "TD-UNKNOWN-CATEGORY": json.dumps([{"name": "x", "value": "y", "category": "not-a-real-category"}]),
    }
    team_id, set_id = _seed_test_data_cases(TestingSessionLocal, cases)

    client = TestClient(app)
    cells = _export_test_data_cells(client, team_id, set_id)

    parsed = json.loads(cells["TD-VALID"])
    assert len(parsed) == 2
    assert parsed[0] == {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "user",
        "category": "email",
        "value": "qa@example.com",
    }
    # credential value 保真，不遮罩
    assert parsed[1]["value"] == "s3cret-plain"

    for number in cases:
        if number == "TD-VALID":
            continue
        assert cells[number] == "", f"{number} 應輸出空 cell，實際為 {cells[number]!r}"


def test_export_csv_test_data_normalize_boundaries_empty_cell(temp_db):
    """會被 normalize 拒絕或改寫的陣列一律輸出空 cell"""
    sync_engine, TestingSessionLocal = temp_db
    cases = {
        # (a) 清洗後重複 name（"a" 與 " a "）
        "TD-DUP-CLEANED": json.dumps([{"name": "a", "value": ""}, {"name": " a ", "value": ""}]),
        # (b) 101 筆
        "TD-101-ITEMS": json.dumps([{"name": f"n{i}", "value": ""} for i in range(101)]),
        # (c) name / value 超長
        "TD-NAME-TOO-LONG": json.dumps([{"name": "n" * 501, "value": ""}]),
        "TD-VALUE-TOO-LONG": json.dumps([{"name": "n", "value": "v" * 100_001}]),
        # (d) name 含需清洗字元
        "TD-NAME-LEADING-SPACE": json.dumps([{"name": " x", "value": ""}]),
        "TD-NAME-NEWLINE": json.dumps([{"name": "x\ny", "value": ""}]),
        "TD-NAME-CONTROL": json.dumps([{"name": "x\x01y", "value": ""}]),
        "TD-NAME-BIDI": json.dumps([{"name": "x\u202ey", "value": ""}]),
        # (e) value 含 null byte
        "TD-VALUE-NULL-BYTE": json.dumps([{"name": "x", "value": "a\x00b"}]),
    }
    team_id, set_id = _seed_test_data_cases(TestingSessionLocal, cases)

    client = TestClient(app)
    cells = _export_test_data_cells(client, team_id, set_id)

    for number in cases:
        assert cells[number] == "", f"{number} 應輸出空 cell，實際為 {cells[number]!r}"


def test_export_csv_test_data_unicode_parity_boundaries(temp_db):
    """code point 長度與 Python strip 集合的 parity 契約（與前端第 8 欄同規則）

    - 300 emoji name（600 UTF-16 units、300 code points）→ 穩定、非空 cell
    - \ufeff(BOM) 開頭：Python strip 不移除 → 穩定、非空 cell
    - \x85(NEL) 結尾：Python strip 會移除 → 不穩定、空 cell
    """
    sync_engine, TestingSessionLocal = temp_db
    emoji_name = "😀" * 300
    cases = {
        "TD-EMOJI-300": json.dumps([{"name": emoji_name, "value": "v"}], ensure_ascii=False),
        "TD-BOM-NAME": json.dumps([{"name": "\ufeffx", "value": "v"}], ensure_ascii=False),
        "TD-NEL-NAME": json.dumps([{"name": "x\x85", "value": "v"}], ensure_ascii=False),
    }
    team_id, set_id = _seed_test_data_cases(TestingSessionLocal, cases)

    client = TestClient(app)
    cells = _export_test_data_cells(client, team_id, set_id)

    assert json.loads(cells["TD-EMOJI-300"])[0]["name"] == emoji_name
    assert json.loads(cells["TD-BOM-NAME"])[0]["name"] == "\ufeffx"
    assert cells["TD-NEL-NAME"] == ""


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
