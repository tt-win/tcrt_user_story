from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database_models import (
    QAAIHelperCommitLink,
    QAAIHelperRequirementPlan,
    QAAIHelperSeedItem,
    QAAIHelperSeedSet,
    QAAIHelperSession,
    QAAIHelperTelemetryEvent,
    QAAIHelperTestcaseDraft,
    QAAIHelperTestcaseDraftSet,
    QAAIHelperTicketSnapshot,
    Team,
    TestCaseLocal,
    User,
)
from app.services.qa_ai_helper_service import (
    _DB_JSON_ZLIB_PREFIX,
    _json_storage_dumps,
    _json_storage_loads,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


def test_json_storage_helpers_compress_large_payload_round_trip() -> None:
    payload = {"description": "Audience detail\n" * 10000}

    encoded = _json_storage_dumps(payload)

    assert encoded is not None
    assert encoded.startswith(_DB_JSON_ZLIB_PREFIX)
    assert _json_storage_loads(encoded, {}) == payload


@pytest.fixture
def qa_ai_helper_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings.openrouter, "api_key", "")
    monkeypatch.setattr(settings.ai.qa_ai_helper.models, "repair", None)
    database_bundle = create_managed_test_database(tmp_path / "qa_ai_helper.db")
    testing_session_local = database_bundle["sync_session_factory"]
    async_testing_session_local = database_bundle["async_session_factory"]

    with testing_session_local() as session:
        team = Team(
            name="QA Helper Team",
            description="",
            wiki_token="wiki-qa-helper",
            test_case_table_id="tbl-qa-helper",
        )
        session.add(team)
        session.commit()

        user = User(
            username="qa-helper-admin",
            email="qa-helper-admin@example.com",
            hashed_password="hashed-password",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        session.commit()

        team_id = team.id
        user_id = user.id

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=async_testing_session_local,
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id,
        username="qa-helper-admin",
        role=UserRole.SUPER_ADMIN,
    )

    from app.services.jira_client import JiraClient

    monkeypatch.setattr(
        JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "View audience details",
                "description": (
                    "h1. User Story Narrative（使用者故事敘述）\n"
                    " * *As a* Brand Admin\n"
                    " * *I want* view audience details\n"
                    " * *So that* I can clearly understand created audiences\n\n"
                    "----\n"
                    "h1. Criteria\n"
                    " * *【Detail Page】* Click name opens detail page\n"
                    " * *【Display】* Status is displayed\n\n"
                    "----\n"
                    "h1. Technical Specifications（技術規格）\n"
                    " * Date format yyyy-MM-dd\n\n"
                    "----\n"
                    "h1. Acceptance Criteria（驗收標準）\n"
                    "h3. Scenario 1: Open details\n"
                    " * *Given* user is on list\n"
                    " * *When* clicking audience name\n"
                    " * *Then* detail opens in a new tab"
                ),
                "comment": {
                    "comments": [
                        {"body": "Comment A"},
                        {"body": "Comment B"},
                    ]
                },
            },
        },
    )

    yield {
        "team_id": team_id,
        "user_id": user_id,
        "sync_session_factory": testing_session_local,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(database_bundle)


def _create_session(client: TestClient, team_id: int, ticket_key: str = "130078") -> dict:
    resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions",
        json={
            "ticket_key": ticket_key,
            "output_locale": "zh-TW",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _prepare_locked_requirement_plan(client: TestClient, team_id: int) -> tuple[int, dict]:
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]
    initialized = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan")
    assert initialized.status_code == 200, initialized.text
    sections = initialized.json()["requirement_plan"]["sections"]
    save_payload = {
        "section_start_number": "010",
        "autosave": False,
        "sections": [
            {
                "id": sections[0]["id"],
                "section_key": sections[0]["section_key"],
                "section_title": sections[0]["section_title"],
                "given": sections[0]["given"],
                "when": sections[0]["when"],
                "then": sections[0]["then"],
                "verification_items": [
                    {
                        "category": "功能驗證",
                        "summary": "使用者點擊 audience name 後應成功開啟詳情頁並顯示狀態",
                        "check_conditions": [
                            {
                                "condition_text": "使用者點擊 audience name 後應成功開啟詳情頁並顯示狀態",
                                "coverage_tag": "Happy Path",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    saved = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan",
        json=save_payload,
    )
    assert saved.status_code == 200, saved.text
    locked = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan/lock")
    assert locked.status_code == 200, locked.text
    return session_id, locked.json()


def _prepare_locked_seed_set(client: TestClient, team_id: int) -> tuple[int, dict]:
    session_id, _locked_plan = _prepare_locked_requirement_plan(client, team_id)
    generated = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets")
    assert generated.status_code == 200, generated.text
    seed_set = generated.json()["seed_set"]
    locked = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets/{seed_set['id']}/lock"
    )
    assert locked.status_code == 200, locked.text
    return session_id, locked.json()


def _prepare_selected_testcase_draft(client: TestClient, team_id: int) -> tuple[int, dict]:
    session_id, _locked_seed_payload = _prepare_locked_seed_set(client, team_id)
    generated = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets",
        json={"force_regenerate": False},
    )
    assert generated.status_code == 200, generated.text
    draft_set = generated.json()["testcase_draft_set"]
    draft = draft_set["drafts"][0]
    selected = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/drafts/{draft['id']}/selection",
        json={"selected_for_commit": True},
    )
    assert selected.status_code == 200, selected.text
    return session_id, selected.json()


def test_ticket_submit_creates_v3_session_and_ticket_snapshot(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]

    before = client.get(f"/api/teams/{team_id}/qa-ai-helper/sessions?limit=20&offset=0")
    assert before.status_code == 200, before.text
    assert before.json()["total"] == 0

    payload = _create_session(client, team_id)

    assert payload["session"]["ticket_key"] == "TCG-130078"
    assert payload["session"]["target_test_case_set_id"] is None
    assert payload["session"]["current_screen"] == "ticket_confirmation"
    assert payload["session"]["status"] == "active"
    assert payload["ticket_snapshot"]["status"] == "validated"
    assert payload["ticket_snapshot"]["raw_ticket_markdown"].startswith("# TCG-130078")
    assert payload["ticket_snapshot"]["validation_summary"]["is_valid"] is True
    assert "verification_planning" in payload["screen_guard"]["allowed_next_screens"]
    assert payload["screen_guard"]["can_restart"] is True

    session_id = payload["session"]["id"]
    workspace = client.get(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}")
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["session"]["current_screen"] == "ticket_confirmation"

    after = client.get(f"/api/teams/{team_id}/qa-ai-helper/sessions?limit=20&offset=0")
    assert after.status_code == 200, after.text
    assert after.json()["total"] == 1


def test_ticket_snapshot_raw_markdown_preserves_original_ticket_blocks(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]

    payload = _create_session(client, team_id)
    markdown = payload["ticket_snapshot"]["raw_ticket_markdown"]

    assert markdown.startswith("# TCG-130078 View audience details")
    assert "# User Story Narrative（使用者故事敘述）" in markdown
    assert "# Acceptance Criteria（驗收標準）" in markdown
    assert "### Scenario 1: Open details" in markdown


def test_restart_deletes_unfinished_session_and_snapshot(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]
    ticket_snapshot_id = payload["ticket_snapshot"]["id"]

    restart = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/restart")
    assert restart.status_code == 200, restart.text
    assert restart.json() == {
        "reset": True,
        "session_id": session_id,
        "next_screen": "ticket_input",
    }

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        assert (
            sync_db.query(QAAIHelperSession)
            .filter(QAAIHelperSession.id == session_id)
            .first()
            is None
        )
        assert (
            sync_db.query(QAAIHelperTicketSnapshot)
            .filter(QAAIHelperTicketSnapshot.id == ticket_snapshot_id)
            .first()
            is None
        )


def test_completed_session_cannot_be_restarted(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        session = (
            sync_db.query(QAAIHelperSession)
            .filter(QAAIHelperSession.id == session_id)
            .first()
        )
        session.status = "completed"
        session.current_screen = "commit_result"
        sync_db.commit()

    restart = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/restart")
    assert restart.status_code == 400
    assert "不支援重新開始" in restart.text


def test_screen_guard_blocks_verification_when_parser_gate_fails(
    qa_ai_helper_db,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.services.jira_client import JiraClient

    monkeypatch.setattr(
        JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "Broken ticket",
                "description": "h1. Acceptance Criteria\nh3. Scenario 1: Broken\n * *When* clicking\n * *Then* detail opens",
                "comment": {"comments": []},
            },
        },
    )

    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id, "TCG-130099")

    assert payload["ticket_snapshot"]["validation_summary"]["is_valid"] is False
    assert "verification_planning" not in payload["screen_guard"]["allowed_next_screens"]


def test_intake_routes_use_managed_boundary_instead_of_request_db(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]

    async def broken_get_db():
        raise AssertionError("qa_ai_helper routes 不應再依賴 request db session")
        yield

    app.dependency_overrides[get_db] = broken_get_db

    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]

    workspace = client.get(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}")
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["ticket_snapshot"]["validation_summary"]["is_valid"] is True


def test_requirement_plan_initializes_from_ticket_snapshot(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]

    response = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan")
    assert response.status_code == 200, response.text

    workspace = response.json()
    plan = workspace["requirement_plan"]
    assert workspace["session"]["current_screen"] == "verification_planning"
    assert plan["status"] == "draft"
    assert plan["section_start_number"] == "010"
    assert len(plan["sections"]) == 1
    assert plan["sections"][0]["section_id"] == "TCG-130078.010"
    assert plan["sections"][0]["section_title"] == "Open details"
    assert plan["sections"][0]["given"] == ["user is on list"]
    assert plan["sections"][0]["when"] == ["clicking audience name"]
    assert plan["sections"][0]["then"] == ["detail opens in a new tab"]


def test_requirement_plan_save_and_lock_workflow(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]

    initialized = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan")
    assert initialized.status_code == 200, initialized.text
    sections = initialized.json()["requirement_plan"]["sections"]

    save_payload = {
        "section_start_number": "030",
        "autosave": False,
        "sections": [
            {
                "id": sections[0]["id"],
                "section_key": sections[0]["section_key"],
                "section_title": sections[0]["section_title"],
                "given": sections[0]["given"],
                "when": sections[0]["when"],
                "then": sections[0]["then"],
                "verification_items": [
                    {
                        "category": "功能驗證",
                        "summary": "使用者點擊 audience name 開啟詳情頁",
                        "check_conditions": [
                            {
                                "condition_text": "成功開啟詳情頁並顯示狀態",
                                "coverage_tag": "Happy Path",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    saved = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan",
        json=save_payload,
    )
    assert saved.status_code == 200, saved.text
    saved_plan = saved.json()["requirement_plan"]
    assert saved_plan["section_start_number"] == "030"
    assert saved_plan["sections"][0]["section_id"] == "TCG-130078.030"
    assert saved_plan["autosave_summary"]["mode"] == "manual"
    assert saved_plan["validation_summary"]["is_valid"] is True

    locked = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan/lock")
    assert locked.status_code == 200, locked.text
    locked_payload = locked.json()
    assert locked_payload["requirement_plan"]["status"] == "locked"
    assert "seed_review" in locked_payload["screen_guard"]["allowed_next_screens"]


def test_requirement_plan_autosave_records_autosave_summary(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]

    initialized = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan")
    assert initialized.status_code == 200, initialized.text
    section = initialized.json()["requirement_plan"]["sections"][0]

    autosave_payload = {
        "section_start_number": "010",
        "autosave": True,
        "sections": [
            {
                "id": section["id"],
                "section_key": section["section_key"],
                "section_title": section["section_title"],
                "given": section["given"],
                "when": section["when"],
                "then": section["then"],
                "verification_items": [
                    {
                        "category": "UI",
                        "summary": "檢視 audience 詳情頁狀態欄位",
                        "detail": {
                            "ui_context": "Audience Detail 頁面 / Status 欄位",
                        },
                        "check_conditions": [
                            {
                                "condition_text": "狀態欄位會顯示 audience status",
                                "coverage_tag": "Happy Path",
                            }
                        ],
                    }
                ],
            }
        ],
    }

    autosaved = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan",
        json=autosave_payload,
    )
    assert autosaved.status_code == 200, autosaved.text
    workspace = autosaved.json()

    assert workspace["session"]["current_screen"] == "verification_planning"
    assert workspace["requirement_plan"]["status"] == "draft"
    assert workspace["requirement_plan"]["autosave_summary"]["mode"] == "autosave"
    assert workspace["requirement_plan"]["validation_summary"]["is_valid"] is True


def test_requirement_plan_unlock_allows_follow_up_manual_save(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]

    initialized = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan")
    assert initialized.status_code == 200, initialized.text
    section = initialized.json()["requirement_plan"]["sections"][0]

    save_payload = {
        "section_start_number": "010",
        "autosave": False,
        "sections": [
            {
                "id": section["id"],
                "section_key": section["section_key"],
                "section_title": section["section_title"],
                "given": section["given"],
                "when": section["when"],
                "then": section["then"],
                "verification_items": [
                    {
                        "category": "功能驗證",
                        "summary": "開啟 audience detail 頁",
                        "check_conditions": [
                            {
                                "condition_text": "可正常進入 detail 頁",
                                "coverage_tag": "Happy Path",
                            }
                        ],
                    }
                ],
            }
        ],
    }

    saved = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan",
        json=save_payload,
    )
    assert saved.status_code == 200, saved.text

    locked = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan/lock")
    assert locked.status_code == 200, locked.text

    locked_save = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan",
        json=save_payload,
    )
    assert locked_save.status_code == 400
    assert "需求已鎖定" in locked_save.text

    unlocked = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan/unlock")
    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["requirement_plan"]["status"] == "draft"

    save_payload["section_start_number"] = "020"
    resaved = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan",
        json=save_payload,
    )
    assert resaved.status_code == 200, resaved.text
    assert resaved.json()["requirement_plan"]["section_start_number"] == "020"
    assert resaved.json()["requirement_plan"]["autosave_summary"]["mode"] == "manual"


def test_lock_requirement_plan_blocks_incomplete_sections(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]

    initialized = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan")
    assert initialized.status_code == 200, initialized.text

    locked = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan/lock")
    assert locked.status_code == 400
    assert "尚未新增任何驗證目標及檢查條件" in locked.text


def test_unlock_requirement_plan_supersedes_downstream_seed_and_testcase_sets(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]

    initialized = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan")
    plan = initialized.json()["requirement_plan"]
    sections = plan["sections"]
    save_payload = {
        "section_start_number": "010",
        "autosave": False,
        "sections": [
            {
                "id": sections[0]["id"],
                "section_key": sections[0]["section_key"],
                "section_title": sections[0]["section_title"],
                "given": sections[0]["given"],
                "when": sections[0]["when"],
                "then": sections[0]["then"],
                "verification_items": [
                    {
                        "category": "API",
                        "summary": "呼叫 audience detail API",
                        "detail": {
                            "api_url": "/api/audiences/{id}"
                        },
                        "check_conditions": [
                            {
                                "condition_text": "回傳 audience 詳情資料",
                                "coverage_tag": "Happy Path",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    saved = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan",
        json=save_payload,
    )
    assert saved.status_code == 200, saved.text

    locked = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan/lock")
    assert locked.status_code == 200, locked.text
    requirement_plan_id = locked.json()["requirement_plan"]["id"]

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        session = sync_db.query(QAAIHelperSession).filter(QAAIHelperSession.id == session_id).first()
        seed_set = QAAIHelperSeedSet(
            session_id=session_id,
            requirement_plan_id=requirement_plan_id,
            status="locked",
            generation_round=1,
            source_type="initial",
            generated_seed_count=1,
            included_seed_count=1,
        )
        sync_db.add(seed_set)
        sync_db.flush()
        testcase_draft_set = QAAIHelperTestcaseDraftSet(
            session_id=session_id,
            seed_set_id=seed_set.id,
            status="draft",
            generated_testcase_count=1,
            selected_for_commit_count=0,
        )
        sync_db.add(testcase_draft_set)
        sync_db.flush()
        session.active_seed_set_id = seed_set.id
        session.active_testcase_draft_set_id = testcase_draft_set.id
        sync_db.commit()

    unlocked = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan/unlock")
    assert unlocked.status_code == 200, unlocked.text
    unlocked_payload = unlocked.json()
    assert unlocked_payload["requirement_plan"]["status"] == "draft"
    assert "seed_review" not in unlocked_payload["screen_guard"]["allowed_next_screens"]

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        session = sync_db.query(QAAIHelperSession).filter(QAAIHelperSession.id == session_id).first()
        assert session.active_seed_set_id is None
        assert session.active_testcase_draft_set_id is None
        assert sync_db.query(QAAIHelperSeedSet).filter(QAAIHelperSeedSet.session_id == session_id).first().status == "superseded"
        assert (
            sync_db.query(QAAIHelperTestcaseDraftSet)
            .filter(QAAIHelperTestcaseDraftSet.session_id == session_id)
            .first()
            .status
            == "superseded"
        )


def test_generate_seed_set_from_locked_requirement_plan(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, _locked_payload = _prepare_locked_requirement_plan(client, team_id)

    generated = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets")
    assert generated.status_code == 200, generated.text

    payload = generated.json()
    assert payload["session"]["current_screen"] == "seed_review"
    seed_set = payload["seed_set"]
    assert seed_set["status"] == "draft"
    assert seed_set["generated_seed_count"] == 1
    assert seed_set["included_seed_count"] == 1
    assert seed_set["adoption_rate"] == 1.0
    assert seed_set["seed_items"][0]["seed_reference_key"].startswith("TCG-130078.010.V001")
    assert "testcase_review" not in payload["screen_guard"]["allowed_next_screens"]


def test_generate_seed_set_reuse_existing_when_force_regenerate_false(qa_ai_helper_db):
    """Calling seed generation with force_regenerate=false reuses existing seeds."""
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, _locked_payload = _prepare_locked_requirement_plan(client, team_id)

    first = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets")
    assert first.status_code == 200, first.text
    first_seed_set_id = first.json()["seed_set"]["id"]

    # Call again with force_regenerate=false → should reuse
    reused = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets",
        json={"force_regenerate": False},
    )
    assert reused.status_code == 200, reused.text
    assert reused.json()["seed_set"]["id"] == first_seed_set_id

    # Call again with force_regenerate=true → should create new
    regenerated = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets",
        json={"force_regenerate": True},
    )
    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["seed_set"]["id"] != first_seed_set_id


def test_generate_seed_set_splits_legacy_multi_condition_item_into_multiple_seeds(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    payload = _create_session(client, team_id)
    session_id = payload["session"]["id"]

    initialized = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan")
    assert initialized.status_code == 200, initialized.text
    section = initialized.json()["requirement_plan"]["sections"][0]

    save_payload = {
        "section_start_number": "010",
        "autosave": False,
        "sections": [
            {
                "id": section["id"],
                "section_key": section["section_key"],
                "section_title": section["section_title"],
                "given": section["given"],
                "when": section["when"],
                "then": section["then"],
                "verification_items": [
                    {
                        "category": "功能驗證",
                        "summary": "點擊 audience name 開啟詳情頁",
                        "check_conditions": [
                            {
                                "condition_text": "成功開啟詳情頁並顯示狀態",
                                "coverage_tag": "Happy Path",
                            },
                            {
                                "condition_text": "無權限時不可進入詳情頁",
                                "coverage_tag": "Permission",
                            },
                        ],
                    }
                ],
            }
        ],
    }
    saved = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan",
        json=save_payload,
    )
    assert saved.status_code == 200, saved.text

    locked = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-plan/lock")
    assert locked.status_code == 200, locked.text

    generated = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets")
    assert generated.status_code == 200, generated.text
    seed_set = generated.json()["seed_set"]

    assert seed_set["generated_seed_count"] == 2
    assert [item["seed_reference_key"] for item in seed_set["seed_items"]] == [
        "TCG-130078.010.V001.S010",
        "TCG-130078.010.V001.S020",
    ]
    assert seed_set["seed_items"][0]["coverage_tags"] == ["Happy Path"]
    assert seed_set["seed_items"][1]["coverage_tags"] == ["Permission"]


def test_seed_review_supports_include_toggle_and_section_bulk_inclusion(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, _locked_payload = _prepare_locked_requirement_plan(client, team_id)

    generated = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets")
    assert generated.status_code == 200, generated.text
    seed_set = generated.json()["seed_set"]
    seed_item = seed_set["seed_items"][0]

    excluded = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets/{seed_set['id']}/items/{seed_item['id']}",
        json={"included_for_testcase_generation": False},
    )
    assert excluded.status_code == 200, excluded.text
    excluded_payload = excluded.json()
    assert excluded_payload["seed_set"]["status"] == "draft"
    assert excluded_payload["seed_set"]["included_seed_count"] == 0
    assert excluded_payload["seed_set"]["adoption_rate"] == 0.0
    assert excluded_payload["seed_set"]["seed_items"][0]["included_for_testcase_generation"] is False

    included = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets/{seed_set['id']}/sections/{seed_item['section_id']}/inclusion",
        json={"included": True},
    )
    assert included.status_code == 200, included.text
    included_payload = included.json()
    assert included_payload["seed_set"]["included_seed_count"] == 1
    assert included_payload["seed_set"]["seed_items"][0]["included_for_testcase_generation"] is True


def test_seed_refine_only_updates_items_with_dirty_comments(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, _locked_payload = _prepare_locked_requirement_plan(client, team_id)

    generated = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets")
    assert generated.status_code == 200, generated.text
    seed_set = generated.json()["seed_set"]
    seed_item = seed_set["seed_items"][0]

    refined = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets/{seed_set['id']}/refine",
        json={
            "items": [
                {
                    "seed_item_id": seed_item["id"],
                    "comment_text": "請補充權限驗證的限制與角色差異",
                }
            ]
        },
    )
    assert refined.status_code == 200, refined.text
    refined_payload = refined.json()
    refined_item = refined_payload["seed_set"]["seed_items"][0]
    assert refined_payload["seed_set"]["status"] == "draft"
    assert refined_item["comment_text"] == "請補充權限驗證的限制與角色差異"
    assert refined_item["user_edited"] is True
    assert "請補充權限驗證的限制與角色差異" in refined_item["seed_summary"] or "請補充權限驗證的限制與角色差異" in refined_item["seed_body"]["text"]


def test_seed_lock_and_unlock_gate_testcase_generation(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, locked_payload = _prepare_locked_requirement_plan(client, team_id)

    generated = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets")
    assert generated.status_code == 200, generated.text
    seed_set = generated.json()["seed_set"]

    locked_seed = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets/{seed_set['id']}/lock"
    )
    assert locked_seed.status_code == 200, locked_seed.text
    locked_payload = locked_seed.json()
    assert locked_payload["seed_set"]["status"] == "locked"
    assert "testcase_review" in locked_payload["screen_guard"]["allowed_next_screens"]

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        session = sync_db.query(QAAIHelperSession).filter(QAAIHelperSession.id == session_id).first()
        testcase_draft_set = QAAIHelperTestcaseDraftSet(
            session_id=session_id,
            seed_set_id=seed_set["id"],
            status="draft",
            generated_testcase_count=1,
            selected_for_commit_count=0,
        )
        sync_db.add(testcase_draft_set)
        sync_db.flush()
        session.active_testcase_draft_set_id = testcase_draft_set.id
        sync_db.commit()

    unlocked_seed = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets/{seed_set['id']}/unlock"
    )
    assert unlocked_seed.status_code == 200, unlocked_seed.text
    unlocked_payload = unlocked_seed.json()
    assert unlocked_payload["seed_set"]["status"] == "draft"
    assert "testcase_review" not in unlocked_payload["screen_guard"]["allowed_next_screens"]

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        session = sync_db.query(QAAIHelperSession).filter(QAAIHelperSession.id == session_id).first()
        assert session.active_testcase_draft_set_id is None
        assert (
            sync_db.query(QAAIHelperTestcaseDraftSet)
            .filter(QAAIHelperTestcaseDraftSet.session_id == session_id)
            .first()
            .status
            == "superseded"
        )


def test_generate_testcase_draft_set_assigns_deterministic_numbers(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, locked_seed_payload = _prepare_locked_seed_set(client, team_id)
    seed_set = locked_seed_payload["seed_set"]

    generated = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets",
        json={"force_regenerate": False},
    )
    assert generated.status_code == 200, generated.text

    payload = generated.json()
    assert payload["session"]["current_screen"] == "testcase_review"
    draft_set = payload["testcase_draft_set"]
    assert draft_set["status"] == "reviewing"
    assert draft_set["generated_testcase_count"] == 1
    assert draft_set["selected_for_commit_count"] == 0
    assert draft_set["drafts"][0]["assigned_testcase_id"] == f"{seed_set['seed_items'][0]['section_id']}.010"
    assert draft_set["drafts"][0]["seed_reference_key"] == seed_set["seed_items"][0]["seed_reference_key"]


def test_testcase_draft_invalid_body_cannot_be_selected_until_fixed(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, _locked_seed_payload = _prepare_locked_seed_set(client, team_id)

    generated = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets",
        json={"force_regenerate": False},
    )
    draft_set = generated.json()["testcase_draft_set"]
    draft = draft_set["drafts"][0]

    broken = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/drafts/{draft['id']}",
        json={
            "body": {
                "title": draft["body"]["title"],
                "priority": "Medium",
                "preconditions": [],
                "steps": [],
                "expected_results": [],
            }
        },
    )
    assert broken.status_code == 200, broken.text
    broken_draft = broken.json()["testcase_draft_set"]["drafts"][0]
    assert broken_draft["validation_summary"]["is_valid"] is False

    select_invalid = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/drafts/{draft['id']}/selection",
        json={"selected_for_commit": True},
    )
    assert select_invalid.status_code == 400
    assert "至少需要一筆" in select_invalid.text

    fixed = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/drafts/{draft['id']}",
        json={
            "body": {
                "title": "Audience 詳情頁顯示內容",
                "priority": "High",
                "preconditions": ["已登入品牌管理員帳號"],
                "steps": ["點擊 audience 名稱"],
                "expected_results": ["成功開啟詳情頁並顯示對應內容"],
            }
        },
    )
    assert fixed.status_code == 200, fixed.text
    fixed_draft = fixed.json()["testcase_draft_set"]["drafts"][0]
    assert fixed_draft["validation_summary"]["is_valid"] is True

    selected = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/drafts/{draft['id']}/selection",
        json={"selected_for_commit": True},
    )
    assert selected.status_code == 200, selected.text
    selected_payload = selected.json()["testcase_draft_set"]
    assert selected_payload["selected_for_commit_count"] == 1
    assert selected_payload["adoption_rate"] == 1.0
    assert "set_selection" in selected.json()["screen_guard"]["allowed_next_screens"]


def test_testcase_section_selection_selects_only_valid_drafts(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, _locked_payload = _prepare_locked_requirement_plan(client, team_id)

    generated = client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets")
    seed_set = generated.json()["seed_set"]

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        first_seed = sync_db.query(QAAIHelperSeedItem).filter(QAAIHelperSeedItem.id == seed_set["seed_items"][0]["id"]).first()
        extra_seed = QAAIHelperSeedItem(
            seed_set_id=first_seed.seed_set_id,
            plan_section_id=first_seed.plan_section_id,
            verification_item_id=first_seed.verification_item_id,
            check_condition_refs_json=_json_storage_dumps([]),
            coverage_tags_json=_json_storage_dumps(["Happy Path"]),
            seed_reference_key=f"{first_seed.plan_section.section_id}.V001.S020",
            seed_summary="第二筆 testcase seed",
            seed_body_json=_json_storage_dumps({"text": "第二筆 testcase seed body"}),
            included_for_testcase_generation=True,
            is_ai_generated=True,
            user_edited=False,
        )
        sync_db.add(extra_seed)
        seed_set_row = sync_db.query(QAAIHelperSeedSet).filter(QAAIHelperSeedSet.id == first_seed.seed_set_id).first()
        seed_set_row.generated_seed_count = 2
        seed_set_row.included_seed_count = 2
        seed_set_row.adoption_rate = 1.0
        sync_db.commit()

    locked_seed = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets/{seed_set['id']}/lock"
    )
    assert locked_seed.status_code == 200, locked_seed.text

    testcase_generated = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets",
        json={"force_regenerate": False},
    )
    assert testcase_generated.status_code == 200, testcase_generated.text
    draft_set = testcase_generated.json()["testcase_draft_set"]
    assert [draft["assigned_testcase_id"] for draft in draft_set["drafts"]] == [
        "TCG-130078.010.010",
        "TCG-130078.010.020",
    ]

    invalid_draft = draft_set["drafts"][1]
    broken = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/drafts/{invalid_draft['id']}",
        json={
            "body": {
                "title": invalid_draft["body"]["title"],
                "priority": invalid_draft["body"]["priority"],
                "preconditions": invalid_draft["body"]["preconditions"],
                "steps": [],
                "expected_results": [],
            }
        },
    )
    assert broken.status_code == 200, broken.text

    bulk_selected = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/sections/TCG-130078.010/selection",
        json={"selected": True},
    )
    assert bulk_selected.status_code == 200, bulk_selected.text
    selected_drafts = bulk_selected.json()["testcase_draft_set"]["drafts"]
    assert [draft["selected_for_commit"] for draft in selected_drafts] == [True, False]
    assert bulk_selected.json()["testcase_draft_set"]["selected_for_commit_count"] == 1


def test_seed_change_supersedes_existing_testcase_draft_set(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, locked_seed_payload = _prepare_locked_seed_set(client, team_id)
    seed_set = locked_seed_payload["seed_set"]

    generated = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets",
        json={"force_regenerate": False},
    )
    assert generated.status_code == 200, generated.text
    draft_set_id = generated.json()["testcase_draft_set"]["id"]

    toggled = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/seed-sets/{seed_set['id']}/items/{seed_set['seed_items'][0]['id']}",
        json={"included_for_testcase_generation": False},
    )
    assert toggled.status_code == 200, toggled.text

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        draft_set = (
            sync_db.query(QAAIHelperTestcaseDraftSet)
            .filter(QAAIHelperTestcaseDraftSet.id == draft_set_id)
            .first()
        )
        assert draft_set.status == "superseded"
        session = sync_db.query(QAAIHelperSession).filter(QAAIHelperSession.id == session_id).first()
        assert session.active_testcase_draft_set_id is None


def test_open_set_selection_requires_selected_valid_drafts(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, selected_workspace = _prepare_selected_testcase_draft(client, team_id)
    draft_set = selected_workspace["testcase_draft_set"]

    opened = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/set-selection"
    )
    assert opened.status_code == 200, opened.text
    payload = opened.json()
    assert payload["session"]["current_screen"] == "set_selection"
    assert payload["testcase_draft_set"]["selected_for_commit_count"] == 1


def test_commit_selected_testcases_to_existing_set_creates_links_and_result_summary(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, selected_workspace = _prepare_selected_testcase_draft(client, team_id)
    draft_set = selected_workspace["testcase_draft_set"]
    draft = draft_set["drafts"][0]

    target_set_resp = client.post(
        f"/api/teams/{team_id}/test-case-sets",
        json={"name": "QA Helper Commit Target", "description": "commit target"},
    )
    assert target_set_resp.status_code == 201, target_set_resp.text
    target_set = target_set_resp.json()

    opened = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/set-selection"
    )
    assert opened.status_code == 200, opened.text

    committed = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/commit",
        json={
            "testcase_draft_set_id": draft_set["id"],
            "selected_draft_ids": [draft["id"]],
            "target_test_case_set_id": target_set["id"],
            "new_test_case_set_payload": None,
        },
    )
    assert committed.status_code == 200, committed.text
    payload = committed.json()
    assert payload["session"]["current_screen"] == "commit_result"
    assert payload["session"]["status"] == "completed"
    assert payload["commit_result"]["target_test_case_set_id"] == target_set["id"]
    assert payload["commit_result"]["target_test_case_set_name"] == target_set["name"]
    assert payload["commit_result"]["created_count"] == 1
    assert payload["commit_result"]["failed_count"] == 0
    assert payload["commit_result"]["skipped_count"] == 0
    assert payload["commit_result"]["created_test_case_ids"] == [draft["assigned_testcase_id"]]
    assert payload["commit_result"]["draft_results"][0]["status"] == "created"
    assert payload["commit_result"]["target_set_link_available"] is True

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        case = (
            sync_db.query(TestCaseLocal)
            .filter(TestCaseLocal.team_id == team_id, TestCaseLocal.test_case_number == draft["assigned_testcase_id"])
            .first()
        )
        assert case is not None
        assert case.test_case_set_id == target_set["id"]
        commit_link = (
            sync_db.query(QAAIHelperCommitLink)
            .filter(QAAIHelperCommitLink.test_case_id == case.id)
            .first()
        )
        assert commit_link is not None
        assert commit_link.testcase_draft_id == draft["id"]
        telemetry = (
            sync_db.query(QAAIHelperTelemetryEvent)
            .filter(
                QAAIHelperTelemetryEvent.session_id == session_id,
                QAAIHelperTelemetryEvent.stage == "commit",
                QAAIHelperTelemetryEvent.event_name == "result",
            )
            .order_by(QAAIHelperTelemetryEvent.id.desc())
            .first()
        )
        assert telemetry is not None


def test_commit_selected_testcases_can_create_new_target_set(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, selected_workspace = _prepare_selected_testcase_draft(client, team_id)
    draft_set = selected_workspace["testcase_draft_set"]
    draft = draft_set["drafts"][0]

    opened = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/set-selection"
    )
    assert opened.status_code == 200, opened.text

    committed = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/commit",
        json={
            "testcase_draft_set_id": draft_set["id"],
            "selected_draft_ids": [draft["id"]],
            "target_test_case_set_id": None,
            "new_test_case_set_payload": {
                "name": "QA Helper New Target",
                "description": "created from helper",
            },
        },
    )
    assert committed.status_code == 200, committed.text
    payload = committed.json()
    assert payload["commit_result"]["created_count"] == 1
    assert payload["commit_result"]["target_test_case_set_name"] == "QA Helper New Target"

    set_list = client.get(f"/api/teams/{team_id}/test-case-sets")
    assert set_list.status_code == 200, set_list.text
    assert any(item["name"] == "QA Helper New Target" for item in set_list.json())


def test_commit_selected_testcases_reports_failed_and_skipped_results(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    session_id, selected_workspace = _prepare_selected_testcase_draft(client, team_id)
    draft_set = selected_workspace["testcase_draft_set"]
    draft = draft_set["drafts"][0]

    target_set_resp = client.post(
        f"/api/teams/{team_id}/test-case-sets",
        json={"name": "QA Helper Duplicate Target", "description": "duplicate target"},
    )
    assert target_set_resp.status_code == 201, target_set_resp.text
    target_set = target_set_resp.json()

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        sync_db.add(
            TestCaseLocal(
                team_id=team_id,
                test_case_set_id=target_set["id"],
                test_case_section_id=None,
                test_case_number=draft["assigned_testcase_id"],
                title="existing duplicate",
            )
        )
        sync_db.commit()

    committed = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/testcase-draft-sets/{draft_set['id']}/commit",
        json={
            "testcase_draft_set_id": draft_set["id"],
            "selected_draft_ids": [draft["id"], 999999],
            "target_test_case_set_id": target_set["id"],
            "new_test_case_set_payload": None,
        },
    )
    assert committed.status_code == 200, committed.text
    result = committed.json()["commit_result"]
    assert result["created_count"] == 0
    assert result["failed_count"] == 1
    assert result["skipped_count"] == 1
    assert result["failed_drafts"][0]["reason"].startswith("Test Case 編號已存在")
    assert result["skipped_drafts"][0]["reason"] == "找不到 testcase draft"
