"""Global assistant targeting regressions: explicit selector, immutable pending target, no page coupling."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.config import settings
from app.database import get_db
from app.db_access.main import get_main_access_boundary
from app.main import app
from app.models.database_models import (
    AssistantPendingAction,
    AssistantToolExecution,
    AssistantTurn,
    Team,
    AssistantMessage,
    TestCaseSection,
    TestCaseSet,
    User,
    TestRunConfig,
    TestRunItem,
)
from app.models.team import TeamStatus
from app.models.test_run_config import TestRunStatus
import app.services.assistant.assistant_llm_service as llm_mod
from app.services.assistant import conversation_service as conversation_service_module
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)

HEADERS = {"Authorization": "Bearer dummy"}


class _FakeLLM:
    def __init__(self):
        self.script = []
        self.calls = 0
        self.last_tools = []
        self.last_system_prompt = ""

    def is_configured(self):
        return True

    async def call(self, *, system_prompt, messages, tools):
        self.calls += 1
        self.last_tools = tools
        self.last_system_prompt = system_prompt
        if self.script:
            return self.script.pop(0)
        return llm_mod.AssistantLLMResult(content="(fallback) done", tool_calls=[])



def _push_tool_call(fake, name, arguments):
    fake.script.append(
        llm_mod.AssistantLLMResult(
            content=None,
            tool_calls=[
                llm_mod.ParsedToolCall(
                    provider_tool_call_id="p", name=name, arguments=arguments
                )
            ],
        )
    )



def _push_text(fake, content="done"):
    fake.script.append(llm_mod.AssistantLLMResult(content=content, tool_calls=[]))


@pytest.fixture
def team_ctx_db(tmp_path, monkeypatch):
    bundle = create_managed_test_database(tmp_path / "assistant_team_target.db")
    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=bundle["async_engine"],
        async_session_factory=bundle["async_session_factory"],
    )
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, username="target-tester", role=UserRole.USER
    )
    monkeypatch.setattr(settings.ai.assistant, "enabled", True)
    monkeypatch.setattr(settings.openrouter, "api_key", "fake-key-for-test")

    fake_llm = _FakeLLM()
    monkeypatch.setattr(llm_mod, "_service_singleton", fake_llm)
    monkeypatch.setattr(
        conversation_service_module,
        "_fire_and_forget_title_generation",
        lambda *args, **kwargs: None,
    )

    with bundle["sync_session_factory"]() as session:
        session.add(
            User(
                id=1,
                username="target-tester",
                email="target@example.com",
                lark_user_id="target-lark",
                hashed_password="x",
                role=UserRole.USER,
                is_active=True,
                is_verified=True,
            )
        )
        session.add_all(
            [
                Team(
                    id=1,
                    name="ART",
                    description="",
                    wiki_token="wt",
                    test_case_table_id="tbl1",
                ),
                Team(
                    id=2,
                    name="CID",
                    description="",
                    wiki_token="wt2",
                    test_case_table_id="tbl2",
                ),
            ]
        )
        session.commit()
        art_set = TestCaseSet(team_id=1, name="ART Default", description="", is_default=True)
        cid_set = TestCaseSet(team_id=2, name="CID Default", description="", is_default=True)
        session.add_all([art_set, cid_set])
        session.flush()
        session.add_all(
            [
                TestCaseSection(
                    test_case_set_id=art_set.id,
                    name="Unassigned",
                    level=1,
                    sort_order=0,
                ),
                TestCaseSection(
                    test_case_set_id=cid_set.id,
                    name="Unassigned",
                    level=1,
                    sort_order=0,
                ),
            ]
        )
        session.commit()
        ids = {"art_set_id": art_set.id, "cid_set_id": cid_set.id}

    yield {"bundle": bundle, "llm": fake_llm, **ids}

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    dispose_managed_test_database(bundle)



def _client():
    return TestClient(app)



def _global_conversation(client) -> int:
    response = client.post(
        "/api/assistant/conversations",
        json={"scope_type": "global"},
        headers=HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]



def _send(client, conv_id, *, text, message_id, context_team_id=None):
    data = {"text": text, "client_message_id": message_id}
    # Deliberately retain this hostile legacy field in tests: the API must ignore it.
    if context_team_id is not None:
        data["context_team_id"] = str(context_team_id)
    return client.post(
        f"/api/assistant/conversations/{conv_id}/messages",
        headers=HEADERS,
        data=data,
    )



def _tool_schema(fake, name):
    return next(item["function"] for item in fake.last_tools if item["function"]["name"] == name)



def _pending(bundle) -> AssistantPendingAction:
    with bundle["sync_session_factory"]() as session:
        row = session.query(AssistantPendingAction).order_by(AssistantPendingAction.id.desc()).first()
        assert row is not None
        session.expunge(row)
        return row



def _pending_action_id(client, conv_id) -> int:
    history = client.get(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS
    ).json()["messages"]
    pending = [
        item
        for item in history
        if item.get("pending_action") and item["pending_action"]["status"] == "pending"
    ]
    assert len(pending) == 1, history
    return pending[0]["pending_action"]["action_id"]



def _pending_summary(client, conv_id) -> dict:
    history = client.get(
        f"/api/assistant/conversations/{conv_id}/messages", headers=HEADERS
    ).json()["messages"]
    cards = [item["pending_action"] for item in history if item.get("pending_action")]
    assert cards, history
    return cards[-1]["confirmation_summary"]



def test_global_catalog_is_role_based_and_schema_requires_exact_selector(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)

    response = _send(
        client,
        conv_id,
        text="hi",
        message_id="m1",
        context_team_id=999,
    )
    assert response.status_code == 200, response.text

    schema = _tool_schema(team_ctx_db["llm"], "create_test_case_set")["parameters"]
    assert "target_team" in schema["required"]
    assert schema["properties"]["target_team"]["required"] == ["id", "name"]
    assert schema["properties"]["target_team"]["additionalProperties"] is False
    assert _tool_schema(team_ctx_db["llm"], "list_teams")["parameters"].get(
        "required", []
    ) == []
    assert "沒有目前／預設 team" in team_ctx_db["llm"].last_system_prompt
    assert "不得要求使用者切換 workspace" in team_ctx_db["llm"].last_system_prompt

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        turn = session.query(AssistantTurn).one()
        assert not hasattr(turn, "context_team_id")



def test_global_list_teams_read_completes_with_accessible_teams(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(fake, "list_teams", {})
    _push_text(fake, "可存取團隊已列出")

    response = _send(client, conv_id, text="列出團隊", message_id="m1")

    assert response.status_code == 200, response.text
    assert '"tool_name": "list_teams"' in response.text
    assert '"ok": true' in response.text
    assert "transport_error" not in response.text

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        journal = session.query(AssistantToolExecution).one()
        assert journal.tool_name == "list_teams"
        assert journal.status == "succeeded"
        assert journal.team_id is None


def test_global_assignment_lookups_use_signed_in_user_across_teams(team_ctx_db):
    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        art_run = TestRunConfig(
            team_id=1,
            name="ART active",
            description="",
            status=TestRunStatus.ACTIVE,
        )
        cid_run = TestRunConfig(
            team_id=2,
            name="CID draft",
            description="",
            status=TestRunStatus.DRAFT,
        )
        completed_run = TestRunConfig(
            team_id=1,
            name="Completed historical run",
            description="",
            status=TestRunStatus.COMPLETED,
        )
        session.add_all([art_run, cid_run, completed_run])
        session.flush()
        session.add_all(
            [
                TestRunItem(
                    team_id=1,
                    config_id=art_run.id,
                    test_case_number="ART-ASSIGNED",
                    assignee_user_id=1,
                    assignee_name="Mandy",
                ),
                # Item rows can retain a legacy source team after their config moves.
                # Navigation must still target the config's owning team.
                TestRunItem(
                    team_id=1,
                    config_id=cid_run.id,
                    test_case_number="CID-LEGACY",
                    assignee_id="target-lark",
                    assignee_name="Mandy",
                ),
                TestRunItem(
                    team_id=1,
                    config_id=completed_run.id,
                    test_case_number="ART-COMPLETED",
                    assignee_user_id=1,
                    assignee_name="Mandy",
                ),
            ]
        )
        session.commit()

    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(fake, "list_my_test_run_assignments", {})
    _push_text(fake, "目前指派的 test run 已列出")

    response = _send(client, conv_id, text="目前有哪些 test run 指派給我？", message_id="m1")
    assert response.status_code == 200, response.text
    assert '"tool_name": "list_my_test_run_assignments"' in response.text

    schema = _tool_schema(fake, "list_my_test_run_assignments")["parameters"]
    assert "target_team" not in schema["properties"]
    assert "target_team" not in schema.get("required", [])

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        journal = session.query(AssistantToolExecution).one()
        assert journal.status == "succeeded"
        assert journal.team_id is None
        assert journal.target_selector_json is None
        tool_message = session.query(AssistantMessage).filter_by(role="tool").one()
        payload = json.loads(tool_message.content)

    runs = {row["run_name"]: row for row in payload["results"]}
    assert set(runs) == {"ART active", "CID draft", "Completed historical run"}
    assert runs["ART active"]["assigned_item_count"] == 1
    assert runs["CID draft"]["team_name"] == "CID"
    assert runs["CID draft"]["team_id"] == 2
    assert runs["CID draft"]["_deep_links"]["test_run"].startswith(
        "/test-run-execution?team_id=2&config_id="
    )

    _push_tool_call(fake, "search_test_run_assignments", {"assignee_name": "Mandy"})
    _push_text(fake, "Mandy 的 test run 已列出")
    response = _send(client, conv_id, text="目前有哪些 test run assign 給 Mandy？", message_id="m2")
    assert response.status_code == 200, response.text
    assert '"tool_name": "search_test_run_assignments"' in response.text

    named_schema = _tool_schema(fake, "search_test_run_assignments")["parameters"]
    assert "target_team" not in named_schema["properties"]
    assert "assignee_name" in named_schema["required"]

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        journals = session.query(AssistantToolExecution).order_by(AssistantToolExecution.id).all()
        assert [journal.tool_name for journal in journals] == [
            "list_my_test_run_assignments",
            "search_test_run_assignments",
        ]
        named_message = (
            session.query(AssistantMessage)
            .filter_by(role="tool")
            .order_by(AssistantMessage.id.desc())
            .first()
        )
        named_payload = json.loads(named_message.content)

    assert {row["run_name"] for row in named_payload["results"]} == {
        "ART active",
        "CID draft",
        "Completed historical run",
    }


def test_global_read_uses_selector_and_journals_raw_pair(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(fake, "list_test_cases", {"target_team": {"id": 2, "name": "CID"}})
    _push_text(fake)

    response = _send(client, conv_id, text="列出 CID 測試案例", message_id="m1")
    assert response.status_code == 200, response.text
    assert "tool_finished" in response.text

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        journal = session.query(AssistantToolExecution).one()
        assert journal.team_id == 2
        assert journal.target_selector_json == '{"id":2,"name":"CID"}'



def test_missing_selector_is_rejected_without_pending(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(fake, "create_test_case_set", {"name": "NoTarget", "description": ""})
    _push_text(fake, "需要目標 team")

    response = _send(client, conv_id, text="建立 set", message_id="m1")
    assert response.status_code == 200, response.text
    assert "confirmation_required" not in response.text
    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        assert session.query(AssistantPendingAction).count() == 0
        assert session.query(TestCaseSet).filter_by(name="NoTarget").first() is None


@pytest.mark.parametrize(
    "selector",
    [
        {"id": 1, "name": "CID"},
        {"id": 999, "name": "ART"},
        {"id": 1, "name": " art "},
        {"id": 1, "name": "ART", "override": "CID"},
    ],
)
def test_forged_or_stale_selector_is_rejected_generically(team_ctx_db, selector):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake,
        "create_test_case_set",
        {"target_team": selector, "name": "ForgedTarget", "description": ""},
    )
    _push_text(fake)

    response = _send(client, conv_id, text="建立 set", message_id="m1")
    assert response.status_code == 200, response.text
    assert "confirmation_required" not in response.text
    assert "team_selector_unresolved" in response.text or "schema_invalid" in response.text



def test_resource_owner_must_equal_selector(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake,
        "create_test_case_section",
        {
            "target_team": {"id": 1, "name": "ART"},
            "set_id": team_ctx_db["cid_set_id"],
            "name": "Cross-team",
        },
    )
    _push_text(fake)

    response = _send(client, conv_id, text="建立 section", message_id="m1")
    assert response.status_code == 200, response.text
    assert "confirmation_required" not in response.text
    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        assert session.query(TestCaseSection).filter_by(name="Cross-team").first() is None



def test_inaccessible_selector_is_rejected_before_pending(team_ctx_db, monkeypatch):
    from app.auth.permission_service import permission_service

    async def _only_art(user_id):
        return [1]

    monkeypatch.setattr(permission_service, "get_user_accessible_teams", _only_art)
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake,
        "create_test_case_set",
        {
            "target_team": {"id": 2, "name": "CID"},
            "name": "Inaccessible",
            "description": "",
        },
    )
    _push_text(fake)

    response = _send(client, conv_id, text="建立 set", message_id="m1")
    assert response.status_code == 200, response.text
    assert "confirmation_required" not in response.text



def test_inactive_selector_is_rejected_before_pending(team_ctx_db):
    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        session.get(Team, 2).status = TeamStatus.INACTIVE
        session.commit()

    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake,
        "create_test_case_set",
        {
            "target_team": {"id": 2, "name": "CID"},
            "name": "Inactive",
            "description": "",
        },
    )
    _push_text(fake)

    response = _send(client, conv_id, text="建立 set", message_id="m1")
    assert response.status_code == 200, response.text
    assert "confirmation_required" not in response.text
    assert "team_selector_unresolved" in response.text


def test_global_write_persists_target_and_confirm_ignores_page_team(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake,
        "create_test_case_set",
        {
            "target_team": {"id": 1, "name": "ART"},
            "name": "SelectorWins",
            "description": "",
        },
    )

    response = _send(
        client,
        conv_id,
        text="在 ART 建立 SelectorWins",
        message_id="m1",
        context_team_id=2,
    )
    assert response.status_code == 200, response.text
    assert "confirmation_required" in response.text
    assert _pending_summary(client, conv_id)["team_name"] == "ART"

    pending = _pending(team_ctx_db["bundle"])
    assert pending.target_team_id == 1
    assert pending.target_team_name_snapshot == "ART"
    assert pending.target_selector_json == '{"id":1,"name":"ART"}'
    assert '"target_team_id": 1' in pending.execution_payload_json

    _push_text(fake, "created")
    confirm = client.post(
        f"/api/assistant/conversations/{conv_id}/actions/{pending.id}/confirm",
        headers=HEADERS,
        params={"context_team_id": 2},
    )
    assert confirm.status_code == 200, confirm.text
    assert '"outcome": "succeeded"' in confirm.text

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        created = session.query(TestCaseSet).filter_by(name="SelectorWins").one()
        assert created.team_id == 1
        journal = (
            session.query(AssistantToolExecution)
            .filter(AssistantToolExecution.tool_name == "create_test_case_set")
            .one()
        )
        assert journal.team_id == 1
        assert journal.target_selector_json == '{"id":1,"name":"ART"}'



def test_one_global_conversation_can_target_two_teams(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]

    for message_id, team_id, team_name, set_name in (
        ("m1", 1, "ART", "ART Created"),
        ("m2", 2, "CID", "CID Created"),
    ):
        _push_tool_call(
            fake,
            "create_test_case_set",
            {
                "target_team": {"id": team_id, "name": team_name},
                "name": set_name,
                "description": "",
            },
        )
        sent = _send(client, conv_id, text=f"在 {team_name} 建立 set", message_id=message_id)
        assert sent.status_code == 200, sent.text
        action_id = _pending_action_id(client, conv_id)
        _push_text(fake)
        confirmed = client.post(
            f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm",
            headers=HEADERS,
        )
        assert confirmed.status_code == 200, confirmed.text

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        rows = {
            row.name: row.team_id
            for row in session.query(TestCaseSet)
            .filter(TestCaseSet.name.in_(["ART Created", "CID Created"]))
            .all()
        }
        assert rows == {"ART Created": 1, "CID Created": 2}



def test_team_rename_expires_existing_confirmation(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake,
        "create_test_case_set",
        {
            "target_team": {"id": 1, "name": "ART"},
            "name": "RenameBlocked",
            "description": "",
        },
    )
    _send(client, conv_id, text="建立 set", message_id="m1")
    action_id = _pending_action_id(client, conv_id)

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        session.get(Team, 1).name = "ART-Renamed"
        session.commit()

    confirm = client.post(
        f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm",
        headers=HEADERS,
    )
    assert confirm.status_code == 409, confirm.text
    assert confirm.json()["detail"]["code"] == "CONFIRMATION_STALE"



def test_missing_pending_target_expires_without_dispatch(team_ctx_db):
    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake,
        "create_test_case_set",
        {
            "target_team": {"id": 1, "name": "ART"},
            "name": "MissingTarget",
            "description": "",
        },
    )
    _send(client, conv_id, text="建立 set", message_id="m1")
    action_id = _pending_action_id(client, conv_id)

    with team_ctx_db["bundle"]["sync_session_factory"]() as session:
        pending = session.get(AssistantPendingAction, action_id)
        pending.target_team_id = None
        session.commit()

    confirm = client.post(
        f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm",
        headers=HEADERS,
    )
    assert confirm.status_code == 409, confirm.text
    assert confirm.json()["detail"]["code"] == "TARGET_TEAM_UNAVAILABLE"



def test_permission_revocation_expires_existing_confirmation(team_ctx_db, monkeypatch):
    from app.auth.permission_service import permission_service

    client = _client()
    conv_id = _global_conversation(client)
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake,
        "create_test_case_set",
        {
            "target_team": {"id": 1, "name": "ART"},
            "name": "Revoked",
            "description": "",
        },
    )
    _send(client, conv_id, text="建立 set", message_id="m1")
    action_id = _pending_action_id(client, conv_id)

    async def _denied(*args, **kwargs):
        return SimpleNamespace(has_permission=False)

    monkeypatch.setattr(permission_service, "check_team_permission", _denied)
    confirm = client.post(
        f"/api/assistant/conversations/{conv_id}/actions/{action_id}/confirm",
        headers=HEADERS,
    )
    assert confirm.status_code == 403, confirm.text
    assert confirm.json()["detail"]["code"] == "TOOL_PERMISSION_DENIED"



def test_team_bound_conversation_rejects_cross_team_resource(team_ctx_db):
    client = _client()
    created = client.post(
        "/api/assistant/conversations",
        json={"scope_type": "team", "team_id": 1},
        headers=HEADERS,
    )
    assert created.status_code == 201, created.text
    fake = team_ctx_db["llm"]
    _push_tool_call(
        fake,
        "create_test_case_section",
        {"set_id": team_ctx_db["cid_set_id"], "name": "Cross-team"},
    )
    _push_text(fake)

    response = _send(
        client,
        created.json()["id"],
        text="建立 section",
        message_id="m1",
        context_team_id=2,
    )
    assert response.status_code == 200, response.text
    assert "confirmation_required" not in response.text



def test_target_team_is_part_of_confirmation_fingerprint(team_ctx_db):
    from app.config import AssistantConfig
    from app.services.assistant.tool_executor import ToolExecutor
    from app.services.assistant.tool_registry import get_tool_registry

    executor = ToolExecutor(
        app=app,
        main_boundary=get_main_access_boundary(),
        config=AssistantConfig(),
        registry=get_tool_registry(),
    )
    tool = get_tool_registry().get("create_test_case_set")

    async def _fingerprints():
        art = await executor.build_confirmation_summary(
            tool, path_params={}, body_params={"name": "Same Name"}, team_id=1
        )
        cid = await executor.build_confirmation_summary(
            tool, path_params={}, body_params={"name": "Same Name"}, team_id=2
        )
        return art, cid

    art, cid = asyncio.run(_fingerprints())
    assert art[0]["team_name"] == "ART"
    assert cid[0]["team_name"] == "CID"
    assert executor.compute_fingerprint(*art) != executor.compute_fingerprint(*cid)
