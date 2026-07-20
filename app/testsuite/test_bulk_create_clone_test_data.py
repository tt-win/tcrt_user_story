"""JWT bulk_create / bulk_clone 的 test_data 行為測試

涵蓋 openspec change support-test-data-bulk-create-export-clone：
- bulk_create 含/不含 test_data、兩階段原子性、422 / duplicates / errors 分層
- category 正規化、audit 不含 credential 明文
- bulk_clone 複製 test_data_json
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

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
from app.models.lark_types import Priority
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_bulk_td.db")
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

    yield TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(database_bundle)


@pytest.fixture
def seeded_team(temp_db):
    with temp_db() as session:
        team = Team(name="Bulk TD Team", wiki_token="tok", test_case_table_id="tbl")
        session.add(team)
        session.commit()
        return {"team_id": team.id}


def _count_cases(session_factory, team_id):
    with session_factory() as session:
        return session.query(TestCaseLocal).filter(TestCaseLocal.team_id == team_id).count()


def _count_sets_and_sections(session_factory, team_id):
    with session_factory() as session:
        set_count = session.query(TestCaseSet).filter(TestCaseSet.team_id == team_id).count()
        section_count = (
            session.query(TestCaseSection)
            .join(TestCaseSet, TestCaseSection.test_case_set_id == TestCaseSet.id)
            .filter(TestCaseSet.team_id == team_id)
            .count()
        )
        return set_count, section_count


def _get_case(session_factory, team_id, number):
    with session_factory() as session:
        return (
            session.query(TestCaseLocal)
            .filter(TestCaseLocal.team_id == team_id, TestCaseLocal.test_case_number == number)
            .first()
        )


class TestBulkCreateTestData:
    def test_bulk_create_with_test_data_persists_and_omitted_stays_null(self, temp_db, seeded_team):
        client = TestClient(app)
        team_id = seeded_team["team_id"]

        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-001",
                        "title": "With test data",
                        "test_data": [
                            {"name": "user", "category": "email", "value": "qa@example.com"}
                        ],
                    },
                    {"test_case_number": "TD-002", "title": "Without test data"},
                ]
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["created_count"] == 2

        with_td = _get_case(temp_db, team_id, "TD-001")
        parsed = json.loads(with_td.test_data_json)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "user"
        assert parsed[0]["category"] == "email"
        assert parsed[0]["value"] == "qa@example.com"
        assert parsed[0]["id"]  # server 補齊 id

        without_td = _get_case(temp_db, team_id, "TD-002")
        assert without_td.test_data_json is None

    def test_bulk_create_normalize_failure_returns_errors_and_writes_nothing(self, temp_db, seeded_team):
        client = TestClient(app)
        team_id = seeded_team["team_id"]

        # 第 1 筆合法、第 2 筆同 case 內 name 重複 → 整批拒絕
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-101",
                        "title": "Valid",
                        "test_data": [{"name": "a", "value": "1"}],
                    },
                    {
                        "test_case_number": "TD-102",
                        "title": "Duplicate names",
                        "test_data": [
                            {"name": "dup", "value": "1"},
                            {"name": "dup", "value": "2"},
                        ],
                    },
                ]
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["created_count"] == 0
        assert body["errors"]
        assert body["duplicates"] == []
        assert _count_cases(temp_db, team_id) == 0

        # 僅空白字元 name（schema 合法、normalize 失敗）
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-103",
                        "title": "Valid",
                        "test_data": [{"name": "a", "value": "1"}],
                    },
                    {
                        "test_case_number": "TD-104",
                        "title": "Whitespace name",
                        "test_data": [{"name": " ", "value": "1"}],
                    },
                ]
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["errors"]
        assert body["duplicates"] == []
        assert _count_cases(temp_db, team_id) == 0

    def test_bulk_create_failure_creates_no_set_or_section(self, temp_db, seeded_team):
        """驗證失敗（duplicates / normalize errors）時不得附帶建立預設 Set / Unassigned Section"""
        client = TestClient(app)
        team_id = seeded_team["team_id"]
        assert _count_sets_and_sections(temp_db, team_id) == (0, 0)

        # normalize 失敗（同 case 內 name 重複）
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-901",
                        "title": "Normalize fail",
                        "test_data": [{"name": "dup", "value": "1"}, {"name": "dup", "value": "2"}],
                    }
                ]
            },
        )
        assert response.status_code == 200 and response.json()["success"] is False
        assert _count_sets_and_sections(temp_db, team_id) == (0, 0)

        # 同一 request 內編號重複
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {"test_case_number": "TD-902", "title": "First"},
                    {"test_case_number": "TD-902", "title": "Second"},
                ]
            },
        )
        assert response.status_code == 200 and response.json()["success"] is False
        assert _count_sets_and_sections(temp_db, team_id) == (0, 0)
        assert _count_cases(temp_db, team_id) == 0

        # 省略 set_id、team 尚無 default set、但提供無效 section_id：
        # 不得為了驗證 section 而先建立（並 commit）default Set / Unassigned
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [{"test_case_number": "TD-903", "title": "Invalid section"}],
                "test_case_section_id": 999999,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["errors"]
        assert _count_sets_and_sections(temp_db, team_id) == (0, 0)
        assert _count_cases(temp_db, team_id) == 0

    def test_bulk_create_accepts_astral_unicode_within_code_point_limits(self, temp_db, seeded_team):
        """name / value 長度以 Unicode code point 計：300 個 emoji 的 name 必須可寫入"""
        client = TestClient(app)
        team_id = seeded_team["team_id"]
        emoji_name = "😀" * 300  # 300 code points（UTF-16 length 600）

        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-951",
                        "title": "Astral name",
                        "test_data": [{"name": emoji_name, "value": "v"}],
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        stored = json.loads(_get_case(temp_db, team_id, "TD-951").test_data_json)
        assert stored[0]["name"] == emoji_name

    def test_bulk_create_schema_violation_returns_422_and_writes_nothing(self, temp_db, seeded_team):
        client = TestClient(app)
        team_id = seeded_team["team_id"]

        # 缺 value → HTTP 422（FastAPI validation error，非 envelope）
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-201",
                        "title": "Missing value",
                        "test_data": [{"name": "user"}],
                    }
                ]
            },
        )
        assert response.status_code == 422
        assert _count_cases(temp_db, team_id) == 0

        # id 為 number → HTTP 422
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-202",
                        "title": "Numeric id",
                        "test_data": [{"id": 1, "name": "user", "value": "x"}],
                    }
                ]
            },
        )
        assert response.status_code == 422
        assert _count_cases(temp_db, team_id) == 0

    def test_bulk_create_duplicates_keep_duplicates_field(self, temp_db, seeded_team):
        client = TestClient(app)
        team_id = seeded_team["team_id"]

        # (a) DB 已存在相同編號
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={"items": [{"test_case_number": "TD-301", "title": "Seed"}]},
        )
        assert response.status_code == 200 and response.json()["success"] is True

        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-301",
                        "title": "Conflict with DB",
                        "test_data": [{"name": "a", "value": "1"}],
                    }
                ]
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["created_count"] == 0
        assert "TD-301" in body["duplicates"]
        assert body["errors"] == []
        assert _count_cases(temp_db, team_id) == 1

        # (b) 同一 request 內兩筆相同編號（DB 尚無該編號）
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {"test_case_number": "TD-302", "title": "First"},
                    {"test_case_number": "TD-302", "title": "Second"},
                ]
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["created_count"] == 0
        assert "TD-302" in body["duplicates"]
        assert body["errors"] == []
        assert _count_cases(temp_db, team_id) == 1  # 只有 TD-301 seed

    def test_bulk_create_category_normalization(self, temp_db, seeded_team):
        client = TestClient(app)
        team_id = seeded_team["team_id"]

        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-401",
                        "title": "Category normalization",
                        "test_data": [
                            {"name": "omitted", "value": "1"},
                            {"name": "null_cat", "value": "1", "category": None},
                            {"name": "empty_cat", "value": "1", "category": ""},
                            {"name": "upper_cat", "value": "1", "category": "EMAIL"},
                        ],
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        case = _get_case(temp_db, team_id, "TD-401")
        categories = {item["name"]: item["category"] for item in json.loads(case.test_data_json)}
        assert categories == {
            "omitted": "text",
            "null_cat": "text",
            "empty_cat": "text",
            "upper_cat": "email",
        }

    def test_bulk_create_audit_details_exclude_credential_value(self, temp_db, seeded_team, monkeypatch):
        from app.api import test_cases as test_cases_module

        captured = []

        async def _capture_log_action(**kwargs):
            captured.append(kwargs)

        monkeypatch.setattr(test_cases_module.audit_service, "log_action", _capture_log_action)

        client = TestClient(app)
        team_id = seeded_team["team_id"]
        secret = "unique-s3cret-value-93178"

        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "TD-501",
                        "title": "With credential",
                        "test_data": [
                            {"name": "password", "category": "credential", "value": secret}
                        ],
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        assert captured, "bulk_create 成功時應寫入 audit"
        details_text = json.dumps(captured[0].get("details"), ensure_ascii=False, default=str)
        assert secret not in details_text
        # 仍保留 test_data 統計資訊
        assert '"test_data_count": 1' in details_text or "'test_data_count': 1" in details_text


class TestBulkCloneTestData:
    @pytest.fixture
    def seeded_sources(self, temp_db, seeded_team):
        team_id = seeded_team["team_id"]
        with temp_db() as session:
            case_set = TestCaseSet(team_id=team_id, name="Clone Set", is_default=True)
            session.add(case_set)
            session.commit()

            section = TestCaseSection(
                test_case_set_id=case_set.id, name="Unassigned", level=1, sort_order=0
            )
            session.add(section)
            session.commit()

            with_td = TestCaseLocal(
                team_id=team_id,
                test_case_set_id=case_set.id,
                test_case_section_id=section.id,
                test_case_number="SRC-001",
                title="Source with test data",
                priority=Priority.HIGH,
                test_data_json=json.dumps(
                    [
                        {"id": "id-1", "name": "user", "category": "email", "value": "qa@example.com"},
                        {"id": "id-2", "name": "pwd", "category": "credential", "value": "s3cret"},
                    ],
                    ensure_ascii=False,
                ),
            )
            without_td = TestCaseLocal(
                team_id=team_id,
                test_case_set_id=case_set.id,
                test_case_section_id=section.id,
                test_case_number="SRC-002",
                title="Source without test data",
                priority=Priority.LOW,
            )
            session.add_all([with_td, without_td])
            session.commit()
            return {
                "team_id": team_id,
                "with_td_id": with_td.id,
                "without_td_id": without_td.id,
                "with_td_json": with_td.test_data_json,
            }

    def test_bulk_clone_copies_test_data(self, temp_db, seeded_sources):
        client = TestClient(app)
        team_id = seeded_sources["team_id"]

        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_clone",
            json={
                "items": [
                    {
                        "source_record_id": str(seeded_sources["with_td_id"]),
                        "test_case_number": "CLONE-001",
                        "title": "Cloned with test data",
                    },
                    {
                        "source_record_id": str(seeded_sources["without_td_id"]),
                        "test_case_number": "CLONE-002",
                        "title": "Cloned without test data",
                    },
                ]
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["created_count"] == 2

        cloned = _get_case(temp_db, team_id, "CLONE-001")
        assert json.loads(cloned.test_data_json) == json.loads(seeded_sources["with_td_json"])

        cloned_empty = _get_case(temp_db, team_id, "CLONE-002")
        assert cloned_empty.test_data_json is None


class TestSampleCsvExecutable:
    def test_sample_csv_rows_bulk_create_successfully(self, temp_db, seeded_team):
        """出貨的 bulk_test_cases_sample.csv 必須可實際執行：

        - 三列（含 8 欄與 7 欄混用）皆可成功 bulk_create
        - 完整形狀列保留指定 category；最小形狀列 category 預設 text、id 由 server 補發
        """
        import csv
        from pathlib import Path

        sample_path = (
            Path(__file__).resolve().parents[1] / "static" / "samples" / "bulk_test_cases_sample.csv"
        )
        with sample_path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        header, data_rows = rows[0], rows[1:]
        assert header[7] == "Test Data"
        assert len(data_rows) == 3

        items = []
        for row in data_rows:
            padded = row + [""] * (8 - len(row))
            test_data_cell = padded[7].strip()
            items.append(
                {
                    "test_case_number": padded[0],
                    "title": padded[1],
                    "precondition": padded[2] or None,
                    "steps": padded[3] or None,
                    "expected_result": padded[4] or None,
                    "priority": padded[6] or "Medium",
                    "tcg_numbers": [t for t in padded[5].split("|") if t],
                    **({"test_data": json.loads(test_data_cell)} if test_data_cell else {}),
                }
            )

        client = TestClient(app)
        team_id = seeded_team["team_id"]
        response = client.post(f"/api/teams/{team_id}/testcases/bulk_create", json={"items": items})
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["created_count"] == 3

        # 列 1：email / credential / number；credential value 保真
        row1 = json.loads(_get_case(temp_db, team_id, "TC-10000.010.010").test_data_json)
        assert [(i["name"], i["category"]) for i in row1] == [
            ("login_email", "email"),
            ("login_password", "credential"),
            ("retry_limit", "number"),
        ]
        assert row1[1]["value"] == "ChangeMe123!"

        # 列 2：第 8 欄省略 → 無 test_data
        assert _get_case(temp_db, team_id, "TC-10000.010.020").test_data_json is None

        # 列 3：url / json / identifier / date / other + 最小形狀（category 預設 text、id 補發）
        row3 = json.loads(_get_case(temp_db, team_id, "TC-10000.010.030").test_data_json)
        assert [(i["name"], i["category"]) for i in row3] == [
            ("health_url", "url"),
            ("expected_status_codes", "json"),
            ("request_id", "identifier"),
            ("checked_at", "date"),
            ("fallback_note", "other"),
            ("service_name", "text"),
        ]
        assert row3[-1]["id"]

        # 範例整體必須覆蓋全部 category enum
        from app.models.test_case import TestDataCategory

        demonstrated = {i["category"] for i in row1 + row3}
        assert demonstrated == {c.value for c in TestDataCategory}


class TestExportCellRoundTrip:
    def test_export_cell_round_trips_into_bulk_create(self, temp_db, seeded_team):
        """Export 非空 test_data cell 可作為 Bulk Create 的 test_data 並保真寫入"""
        client = TestClient(app)
        team_id = seeded_team["team_id"]

        source_test_data = [
            {"name": "login_email", "category": "email", "value": "qa@example.com"},
            {"name": "login_password", "category": "credential", "value": "ChangeMe123!"},
        ]
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "RT-001",
                        "title": "Round trip source",
                        "test_data": source_test_data,
                    }
                ]
            },
        )
        assert response.status_code == 200 and response.json()["success"] is True

        with temp_db() as session:
            set_id = (
                session.query(TestCaseLocal.test_case_set_id)
                .filter(TestCaseLocal.team_id == team_id)
                .scalar()
            )

        export = client.get(f"/api/teams/{team_id}/test-case-sets/{set_id}/export-csv")
        assert export.status_code == 200

        import csv
        import io

        rows = list(csv.reader(io.StringIO(export.content.decode("utf-8-sig"))))
        idx = {col: i for i, col in enumerate(rows[0])}
        cell = rows[1][idx["test_data"]]
        assert cell, "round-trip 判定通過的資料應輸出非空 cell"

        # 將 cell 作為新 case 的 test_data 再次 bulk_create
        response = client.post(
            f"/api/teams/{team_id}/testcases/bulk_create",
            json={
                "items": [
                    {
                        "test_case_number": "RT-002",
                        "title": "Round trip target",
                        "test_data": json.loads(cell),
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        target = _get_case(temp_db, team_id, "RT-002")
        stored = json.loads(target.test_data_json)
        assert [(i["name"], i["value"], i["category"]) for i in stored] == [
            ("login_email", "qa@example.com", "email"),
            ("login_password", "ChangeMe123!", "credential"),
        ]
