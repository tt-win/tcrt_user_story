from pathlib import Path
import sys
from types import SimpleNamespace
import json

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
    QAAIHelperCanonicalRevision,
    QAAIHelperDraftSet,
    QAAIHelperPlannedRevision,
    QAAIHelperSession,
    Team,
    TestCaseLocal,
    TestCaseSet,
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


def _canonical_payload() -> dict:
    return {
        "canonical_language": "en",
        "counter_settings": {"middle": "010", "tail": "010"},
        "content": {
            "userStoryNarrative": "As a QA user\nI want to generate test cases\nSo that I can review coverage",
            "criteria": "- Detail page opens in a new tab\n- Display current status",
            "technicalSpecifications": "- API path: /detail/view\n- Date format: yyyy-MM-dd",
            "acceptanceCriteria": (
                "Scenario 1: Open detail page\n"
                "Given the user is on the list page\n"
                "When the user clicks the detail name\n"
                "Then the detail page opens in a new tab\n"
                "And the tab title matches the entity name\n\n"
                "Scenario 2: Display current status\n"
                "Given the user is on the detail page\n"
                "When the page is loaded\n"
                "Then the current status is displayed\n"
                "And the updated date uses yyyy-MM-dd"
            ),
            "assumptions": [],
            "unknowns": [],
        },
    }


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
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    with TestingSessionLocal() as session:
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

        test_set = TestCaseSet(
            team_id=team.id,
            name=f"QA-Helper-Set-{team.id}",
            description="",
            is_default=True,
        )
        session.add(test_set)
        session.commit()

        team_id = team.id
        set_id = test_set.id
        user_id = user.id

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
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
                    "User Story\n"
                    "As a Brand Admin\n"
                    "I want to view audience details\n"
                    "So that I can clearly understand created audiences\n\n"
                    "Criteria\n"
                    "- Click name opens detail page\n"
                    "- Status is displayed\n\n"
                    "Technical Specifications\n"
                    "- Date format yyyy-MM-dd\n\n"
                    "Acceptance Criteria\n"
                    "Scenario 1: Open details\n"
                    "Given user is on list\n"
                    "When clicking audience name\n"
                    "Then detail opens in a new tab"
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
        "set_id": set_id,
        "user_id": user_id,
        "sync_session_factory": TestingSessionLocal,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(database_bundle)


def _create_session(client: TestClient, team_id: int, set_id: int) -> dict:
    resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions",
        json={
            "target_test_case_set_id": set_id,
            "ticket_key": "TCG-130078",
            "output_locale": "zh-TW",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_qa_ai_helper_full_lifecycle(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    set_id = qa_ai_helper_db["set_id"]

    session_payload = _create_session(client, team_id, set_id)
    session_id = session_payload["session"]["id"]
    assert session_payload["session"]["include_comments"] is False

    fetch_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/ticket",
        json={},
    )
    assert fetch_resp.status_code == 200, fetch_resp.text
    fetch_payload = fetch_resp.json()
    assert fetch_payload["session"]["ticket_key"] == "TCG-130078"
    assert fetch_payload["source_payload"]["comments"] == []
    assert fetch_payload["canonical_revision"]["status"] == "editable"

    save_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/canonical-revisions",
        json=_canonical_payload(),
    )
    assert save_resp.status_code == 200, save_resp.text
    save_payload = save_resp.json()
    assert save_payload["canonical_revision"]["status"] == "confirmed"

    plan_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/plan",
        json={},
    )
    assert plan_resp.status_code == 200, plan_resp.text
    plan_payload = plan_resp.json()
    planned_revision_id = plan_payload["planned_revision"]["id"]
    assert len(plan_payload["planned_revision"]["matrix"]["sections"]) == 2

    first_row_key = (
        plan_payload["planned_revision"]["matrix"]["sections"][0]["matrix"]["row_groups"][0]["rows"][0]["row_key"]
    )
    override_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/planning-overrides",
        json={
            "overrides": [
                {
                    "row_key": first_row_key,
                    "status": "manual_exempt",
                    "reason": "test override",
                }
            ]
        },
    )
    assert override_resp.status_code == 200, override_resp.text
    override_payload = override_resp.json()
    planned_revision_id = override_payload["planned_revision"]["id"]
    assert override_payload["planned_revision"]["revision_number"] == 2

    lock_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/lock",
        json={"planned_revision_id": planned_revision_id},
    )
    assert lock_resp.status_code == 200, lock_resp.text
    assert lock_resp.json()["planned_revision"]["status"] == "locked"

    generate_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/generate",
        json={},
    )
    assert generate_resp.status_code == 200, generate_resp.text
    generate_payload = generate_resp.json()
    draft_set = generate_payload["draft_set"]
    assert draft_set is not None
    assert len(draft_set["drafts"]) >= 2
    draft_set_id = draft_set["id"]
    draft_item = draft_set["drafts"][0]

    reopen_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/generate",
        json={},
    )
    assert reopen_resp.status_code == 200
    assert reopen_resp.json()["draft_set"]["id"] == draft_set_id

    update_resp = client.put(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/draft-sets/{draft_set_id}/drafts",
        json={
            "item_key": draft_item["item_key"],
            "body": {
                "title": "Updated testcase title",
                "priority": "High",
                "preconditions": ["A", "B"],
                "steps": ["1", "2", "3"],
                "expected_results": ["done"],
            },
        },
    )
    assert update_resp.status_code == 200, update_resp.text
    update_payload = update_resp.json()
    updated_item = next(
        item
        for item in update_payload["draft_set"]["drafts"]
        if item["item_key"] == draft_item["item_key"]
    )
    assert updated_item["body"]["title"] == "Updated testcase title"

    commit_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/draft-sets/{draft_set_id}/commit",
        json={},
    )
    assert commit_resp.status_code == 200, commit_resp.text
    commit_payload = commit_resp.json()
    assert commit_payload["created_count"] >= 1

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        created_cases = (
            sync_db.query(TestCaseLocal)
            .filter(TestCaseLocal.team_id == team_id)
            .all()
        )
        assert created_cases


def test_plan_flow_uses_managed_boundary_instead_of_request_db(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    set_id = qa_ai_helper_db["set_id"]

    async def broken_get_db():
        raise AssertionError("qa_ai_helper routes 不應再依賴 request db session")
        yield

    app.dependency_overrides[get_db] = broken_get_db

    session_id = _create_session(client, team_id, set_id)["session"]["id"]

    fetch_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/ticket",
        json={},
    )
    assert fetch_resp.status_code == 200, fetch_resp.text

    save_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/canonical-revisions",
        json=_canonical_payload(),
    )
    assert save_resp.status_code == 200, save_resp.text

    plan_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/plan",
        json={},
    )
    assert plan_resp.status_code == 200, plan_resp.text
    assert plan_resp.json()["planned_revision"]["status"] == "editable"


def test_planned_revision_persists_compact_matrix_payload(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    set_id = qa_ai_helper_db["set_id"]

    session_id = _create_session(client, team_id, set_id)["session"]["id"]
    client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/ticket", json={})
    client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/canonical-revisions",
        json=_canonical_payload(),
    )
    plan_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/plan",
        json={},
    )
    assert plan_resp.status_code == 200, plan_resp.text

    planned_revision_id = plan_resp.json()["planned_revision"]["id"]
    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        planned_revision = sync_db.query(QAAIHelperPlannedRevision).filter(
            QAAIHelperPlannedRevision.id == planned_revision_id
        ).first()
        assert planned_revision is not None
        matrix_payload = _json_storage_loads(planned_revision.matrix_json, {})
        seed_map_payload = _json_storage_loads(planned_revision.seed_map_json, {})

    assert "criteria_items" not in matrix_payload
    assert "technical_items" not in matrix_payload
    assert "coverage_index" not in matrix_payload
    assert isinstance(matrix_payload["generation_items"][0], str)
    assert "generation_items" not in matrix_payload["sections"][0]
    assert seed_map_payload == {}


def test_requirement_delta_marks_old_plan_and_drafts_stale(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    set_id = qa_ai_helper_db["set_id"]
    session_id = _create_session(client, team_id, set_id)["session"]["id"]

    client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/ticket", json={})
    client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/canonical-revisions",
        json=_canonical_payload(),
    )
    plan_payload = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/plan",
        json={},
    ).json()
    client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/lock",
        json={"planned_revision_id": plan_payload["planned_revision"]["id"]},
    )
    generate_payload = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/generate",
        json={},
    ).json()
    old_draft_set_id = generate_payload["draft_set"]["id"]
    old_planned_revision_id = generate_payload["planned_revision"]["id"]

    delta_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-deltas",
        json={
            "delta_type": "add",
            "target_scope": "Acceptance Criteria",
            "target_scenario_key": "ac.scenario_003",
            "proposed_content": {
                "title": "New Scenario",
                "text": "Given user is ready\nWhen applying new rule\nThen system saves new rule",
            },
            "reason": "missing scenario",
        },
    )
    assert delta_resp.status_code == 200, delta_resp.text
    delta_payload = delta_resp.json()
    assert delta_payload["planned_revision"]["id"] != old_planned_revision_id

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        old_plan = sync_db.query(QAAIHelperPlannedRevision).filter(QAAIHelperPlannedRevision.id == old_planned_revision_id).first()
        old_draft = sync_db.query(QAAIHelperDraftSet).filter(QAAIHelperDraftSet.id == old_draft_set_id).first()
        session_row = sync_db.query(QAAIHelperSession).filter(QAAIHelperSession.id == session_id).first()
        assert old_plan.status == "stale"
        assert old_draft.status == "outdated"
        assert session_row.active_draft_set_id is None


def test_force_regenerate_requires_discard_first(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    set_id = qa_ai_helper_db["set_id"]
    session_id = _create_session(client, team_id, set_id)["session"]["id"]

    client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/ticket", json={})
    client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/canonical-revisions",
        json=_canonical_payload(),
    )
    plan_payload = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/plan",
        json={},
    ).json()
    client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/lock",
        json={"planned_revision_id": plan_payload["planned_revision"]["id"]},
    )
    generate_payload = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/generate",
        json={},
    ).json()
    draft_set_id = generate_payload["draft_set"]["id"]

    force_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/generate",
        json={"force_regenerate": True},
    )
    assert force_resp.status_code == 400
    assert "active drafts" in force_resp.text

    discard_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/draft-sets/{draft_set_id}/discard",
        json={},
    )
    assert discard_resp.status_code == 200
    assert discard_resp.json()["draft_set"] is None

    regenerate_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/generate",
        json={"force_regenerate": True},
    )
    assert regenerate_resp.status_code == 200, regenerate_resp.text
    assert regenerate_resp.json()["draft_set"]["id"] != draft_set_id


def test_fetch_ticket_can_include_comments_and_canonical_revisions_supersede(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    set_id = qa_ai_helper_db["set_id"]
    session_id = _create_session(client, team_id, set_id)["session"]["id"]

    fetch_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/ticket",
        json={"include_comments": True},
    )
    assert fetch_resp.status_code == 200, fetch_resp.text
    assert fetch_resp.json()["source_payload"]["comments"] == ["Comment A", "Comment B"]

    first_save = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/canonical-revisions",
        json=_canonical_payload(),
    )
    assert first_save.status_code == 200, first_save.text
    first_revision_id = first_save.json()["canonical_revision"]["id"]

    modified = _canonical_payload()
    modified["counter_settings"] = {"middle": "020", "tail": "030"}
    modified["content"]["criteria"] += "\n- Extra rule"
    second_save = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/canonical-revisions",
        json=modified,
    )
    assert second_save.status_code == 200, second_save.text
    second_revision_id = second_save.json()["canonical_revision"]["id"]
    assert second_revision_id != first_revision_id

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        first_revision = (
            sync_db.query(QAAIHelperCanonicalRevision)
            .filter(QAAIHelperCanonicalRevision.id == first_revision_id)
            .first()
        )
        second_revision = (
            sync_db.query(QAAIHelperCanonicalRevision)
            .filter(QAAIHelperCanonicalRevision.id == second_revision_id)
            .first()
        )
        assert first_revision.status == "superseded"
        assert second_revision.status == "confirmed"


def test_planning_overrides_roundtrip_references_and_outdated_commit_guard(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    set_id = qa_ai_helper_db["set_id"]
    session_id = _create_session(client, team_id, set_id)["session"]["id"]

    client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/ticket", json={})
    client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/canonical-revisions",
        json=_canonical_payload(),
    )
    plan_payload = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/plan",
        json={},
    ).json()
    first_row_key = (
        plan_payload["planned_revision"]["matrix"]["sections"][0]["matrix"]["row_groups"][0]["rows"][0]["row_key"]
    )

    override_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/planning-overrides",
        json={
            "overrides": [{"row_key": first_row_key, "status": "not_applicable", "reason": "skip"}],
            "selected_references": {
                "section_references": {
                    "TCG-130078.010": [{"reference_id": "ref-1", "title": "history"}]
                }
            },
            "counter_settings": {"middle": "020", "tail": "030"},
        },
    )
    assert override_resp.status_code == 200, override_resp.text
    override_payload = override_resp.json()
    assert override_payload["planned_revision"]["counter_settings"] == {"middle": "020", "tail": "030"}
    assert override_payload["planned_revision"]["selected_references"]["section_references"]["TCG-130078.010"][0]["reference_id"] == "ref-1"

    planned_revision_id = override_payload["planned_revision"]["id"]
    client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/lock",
        json={"planned_revision_id": planned_revision_id},
    )
    generate_payload = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/generate",
        json={},
    ).json()
    draft_set_id = generate_payload["draft_set"]["id"]

    delta_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/requirement-deltas",
        json={
            "delta_type": "modify",
            "target_scope": "Acceptance Criteria",
            "target_scenario_key": "ac.scenario_001",
            "proposed_content": {
                "title": "Open detail page updated",
                "text": (
                    "Given the user is on the list page\n"
                    "When the user clicks the detail name\n"
                    "Then the detail page opens in a new tab\n"
                    "And the breadcrumb is displayed"
                ),
            },
            "reason": "scope update",
        },
    )
    assert delta_resp.status_code == 200, delta_resp.text
    assert delta_resp.json()["planned_revision"]["impact_summary"]["replanning_mode"] == "scoped"

    stale_commit = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/draft-sets/{draft_set_id}/commit",
        json={},
    )
    assert stale_commit.status_code == 400
    assert "不可 commit" in stale_commit.text


def test_generation_budget_and_missing_hard_fact_guards(qa_ai_helper_db):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    set_id = qa_ai_helper_db["set_id"]

    original_row_limit = settings.ai.qa_ai_helper.generation_budget_row_limit
    original_prompt_limit = settings.ai.qa_ai_helper.generation_budget_prompt_tokens
    original_output_limit = settings.ai.qa_ai_helper.generation_budget_output_tokens
    try:
        session_id = _create_session(client, team_id, set_id)["session"]["id"]
        client.post(f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/ticket", json={})
        client.post(
            f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/canonical-revisions",
            json=_canonical_payload(),
        )
        plan_payload = client.post(
            f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/plan",
            json={},
        ).json()
        client.post(
            f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/lock",
            json={"planned_revision_id": plan_payload["planned_revision"]["id"]},
        )

        settings.ai.qa_ai_helper.generation_budget_row_limit = 1
        settings.ai.qa_ai_helper.generation_budget_prompt_tokens = 1
        settings.ai.qa_ai_helper.generation_budget_output_tokens = 1
        budget_resp = client.post(
            f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/generate",
            json={},
        )
        assert budget_resp.status_code == 400
        assert "超出 budget" in budget_resp.text

        confirmed_resp = client.post(
            f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/generate",
            json={"confirm_exhaustive": True},
        )
        assert confirmed_resp.status_code == 200, confirmed_resp.text

        missing_session_id = _create_session(client, team_id, set_id)["session"]["id"]
        client.post(
            f"/api/teams/{team_id}/qa-ai-helper/sessions/{missing_session_id}/canonical-revisions",
            json={
                "canonical_language": "en",
                "counter_settings": {"middle": "010", "tail": "010"},
                "content": {
                    "userStoryNarrative": "As a QA user\nI want TBD\nSo that I can review placeholders",
                    "criteria": "- Display format TBD",
                    "technicalSpecifications": "- API path TBD",
                    "acceptanceCriteria": (
                        "Scenario 1: Show format\n"
                        "Given the user opens detail\n"
                        "When the detail loads\n"
                        "Then the page shows date format TBD"
                    ),
                    "assumptions": [],
                    "unknowns": ["format TBD"],
                },
            },
        )
        missing_plan = client.post(
            f"/api/teams/{team_id}/qa-ai-helper/sessions/{missing_session_id}/plan",
            json={},
        ).json()
        client.post(
            f"/api/teams/{team_id}/qa-ai-helper/sessions/{missing_session_id}/lock",
            json={"planned_revision_id": missing_plan["planned_revision"]["id"]},
        )
        missing_resp = client.post(
            f"/api/teams/{team_id}/qa-ai-helper/sessions/{missing_session_id}/generate",
            json={},
        )
        assert missing_resp.status_code == 400
        assert "缺少必要 hard facts" in missing_resp.text
    finally:
        settings.ai.qa_ai_helper.generation_budget_row_limit = original_row_limit
        settings.ai.qa_ai_helper.generation_budget_prompt_tokens = original_prompt_limit
        settings.ai.qa_ai_helper.generation_budget_output_tokens = original_output_limit


def test_fetch_large_ticket_payload_persists_without_truncation(qa_ai_helper_db, monkeypatch):
    client = TestClient(app)
    team_id = qa_ai_helper_db["team_id"]
    set_id = qa_ai_helper_db["set_id"]

    repeated_block = (
        "Criteria\n"
        "- Display all audience details\n"
        "- Respect farm timezone\n\n"
        "Technical Specifications\n"
        "- Date format yyyy-MM-dd HH:mm:ss\n"
        "- Keep source payload complete\n\n"
    )
    large_description = (
        "User Story\n"
        "As a Brand Admin\n"
        "I want to review a very large bilingual ticket\n"
        "So that I can preserve every requirement\n\n"
        "Acceptance Criteria\n"
        "Scenario 1: Open details\n"
        "Given the user is on the list page\n"
        "When the user clicks the audience name\n"
        "Then the detail page opens in a new tab\n\n"
        + (repeated_block * 500)
    )
    assert len(large_description.encode("utf-8")) > 65535

    from app.services.jira_client import JiraClient

    monkeypatch.setattr(
        JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "Large audience detail ticket",
                "description": large_description,
                "comment": {"comments": []},
            },
        },
    )

    session_id = _create_session(client, team_id, set_id)["session"]["id"]
    fetch_resp = client.post(
        f"/api/teams/{team_id}/qa-ai-helper/sessions/{session_id}/ticket",
        json={},
    )

    assert fetch_resp.status_code == 200, fetch_resp.text
    payload = fetch_resp.json()
    assert payload["source_payload"]["description"] == large_description.strip()

    with qa_ai_helper_db["sync_session_factory"]() as sync_db:
        session = sync_db.get(QAAIHelperSession, session_id)
        assert session is not None
        assert session.source_payload_json.startswith(_DB_JSON_ZLIB_PREFIX)
        stored_payload = _json_storage_loads(session.source_payload_json, {})

    assert stored_payload["description"] == large_description.strip()
