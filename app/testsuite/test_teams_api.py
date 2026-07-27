# ruff: noqa: E402
"""Team CRUD API contract tests.

覆蓋 `remove-team-lark-repo-settings` change 的驗收條件：team 建立／編輯不再需要
Lark Bitable 欄位、回應不再帶 `lark_config`，且既有 team 資料庫列中的歷史
`wiki_token` / `test_case_table_id` 值完全不受影響（欄位保留、不做 migration）。
"""

from __future__ import annotations

from pathlib import Path
import sys
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
from app.models.database_models import Team
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)

FAKE_ADMIN = SimpleNamespace(
    id=1,
    username="pytest-admin",
    full_name="Pytest Admin",
    role=UserRole.ADMIN,
)

# 舊 team 在資料庫中的歷史值，用來驗證資料相容性。
LEGACY_WIKI_TOKEN = "Q4XxwaS2Cif80DkAku9lMKuAgof"
LEGACY_TABLE_ID = "tblEAg8srqYs0rzi"


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_teams_api.db")
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    import app.main as app_main
    import app.models.user_story_map_db as usm_db_module

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )

    async def _noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(app_main, "init_audit_database", _noop_async)
    monkeypatch.setattr(app_main, "cleanup_audit_database", _noop_async)
    monkeypatch.setattr(app_main.audit_service, "force_flush", _noop_async)
    monkeypatch.setattr(usm_db_module, "init_usm_db", _noop_async)

    # `require_admin()` 走 permission_service.check_user_role() 查 DB（不看注入物件的
    # role 屬性），因此僅 override get_current_user 不足以通過 admin-only 端點。
    async def _allow_role(*args, **kwargs):
        return True

    monkeypatch.setattr(permission_service, "check_user_role", _allow_role)

    app.dependency_overrides[get_current_user] = lambda: FAKE_ADMIN

    yield TestingSessionLocal

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(database_bundle)


def _seed_legacy_team(session) -> int:
    """建立一個帶有歷史 Lark 值的 team（刻意繞過 API，API 只會寫入空字串）。"""
    team = Team(
        name="Legacy Team",
        description="Created before the Lark settings removal",
        wiki_token=LEGACY_WIKI_TOKEN,
        test_case_table_id=LEGACY_TABLE_ID,
    )
    session.add(team)
    session.commit()
    return team.id


class TestTeamCreate:
    def test_create_without_lark_config(self, temp_db):
        with TestClient(app) as client:
            resp = client.post("/api/teams/", json={"name": "No Lark Team"})
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert "lark_config" not in body
            assert body["is_lark_configured"] is False

        with temp_db() as session:
            created = session.query(Team).filter(Team.name == "No Lark Team").one()
            # 欄位仍是 NOT NULL，新 team 以空字串代表「從未有過 Lark 設定」
            assert created.wiki_token == ""
            assert created.test_case_table_id == ""

    def test_lark_config_in_payload_is_ignored(self, temp_db):
        """舊 client 若仍送 lark_config，不得被偷偷寫回 DB。

        `TeamCreate` 沒有 `extra="forbid"`（只有 `Team` 有），Pydantic 2 預設忽略
        額外欄位，因此預期是 201 而非 422。
        """
        with TestClient(app) as client:
            resp = client.post(
                "/api/teams/",
                json={
                    "name": "Legacy Client Team",
                    "lark_config": {
                        "wiki_token": LEGACY_WIKI_TOKEN,
                        "test_case_table_id": LEGACY_TABLE_ID,
                    },
                },
            )
            assert resp.status_code == 201, resp.text
            assert "lark_config" not in resp.json()

        with temp_db() as session:
            created = session.query(Team).filter(Team.name == "Legacy Client Team").one()
            assert created.wiki_token == ""
            assert created.test_case_table_id == ""


class TestTeamRead:
    def test_list_omits_lark_config(self, temp_db):
        with temp_db() as session:
            _seed_legacy_team(session)

        with TestClient(app) as client:
            resp = client.get("/api/teams/")
            assert resp.status_code == 200, resp.text
            items = resp.json()
            assert len(items) == 1
            assert "lark_config" not in items[0]
            assert items[0]["is_lark_configured"] is False

    def test_legacy_team_with_stored_tokens_still_lists(self, temp_db):
        """舊 team 的歷史值不再通過任何 validator，讀取路徑必須完全忽略它們。"""
        with temp_db() as session:
            team_id = _seed_legacy_team(session)

        with TestClient(app) as client:
            listed = client.get("/api/teams/")
            assert listed.status_code == 200, listed.text
            assert [item["id"] for item in listed.json()] == [team_id]

            detail = client.get(f"/api/teams/{team_id}")
            assert detail.status_code == 200, detail.text
            assert "lark_config" not in detail.json()

        with temp_db() as session:
            stored = session.query(Team).filter(Team.id == team_id).one()
            assert stored.wiki_token == LEGACY_WIKI_TOKEN
            assert stored.test_case_table_id == LEGACY_TABLE_ID


class TestTeamUpdate:
    def test_update_preserves_stored_lark_values(self, temp_db):
        """回歸網：更新 team 不得清空 DB 中的歷史 Lark 值。

        移除 `TeamUpdate.lark_config` 後已無任何程式碼路徑會寫這兩個欄位，此測試
        用來擋住未來把寫入加回來，而不是資料層的保護機制。
        """
        with temp_db() as session:
            team_id = _seed_legacy_team(session)

        with TestClient(app) as client:
            resp = client.put(f"/api/teams/{team_id}", json={"name": "Renamed Legacy Team"})
            assert resp.status_code == 200, resp.text
            assert resp.json()["name"] == "Renamed Legacy Team"

        with temp_db() as session:
            stored = session.query(Team).filter(Team.id == team_id).one()
            assert stored.name == "Renamed Legacy Team"
            assert stored.wiki_token == LEGACY_WIKI_TOKEN
            assert stored.test_case_table_id == LEGACY_TABLE_ID


class TestLarkValidationEndpointsRemoved:
    def test_validate_endpoints_are_gone(self, temp_db):
        with TestClient(app) as client:
            validate = client.post(
                "/api/teams/validate",
                json={
                    "name": "x",
                    "lark_config": {
                        "wiki_token": LEGACY_WIKI_TOKEN,
                        "test_case_table_id": LEGACY_TABLE_ID,
                    },
                },
            )
            validate_table = client.post(
                "/api/teams/validate-table",
                json={"wiki_token": LEGACY_WIKI_TOKEN, "table_id": LEGACY_TABLE_ID},
            )

        # 兩支端點已移除。回應是 405 而非 404：路徑被同層的 `/{team_id}` 路由吃掉
        # （該路徑存在 GET/PUT/DELETE 但沒有 POST），FastAPI 因此回 Method Not Allowed。
        assert validate.status_code == 405
        assert validate_table.status_code == 405
