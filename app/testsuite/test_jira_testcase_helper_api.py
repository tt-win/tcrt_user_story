from pathlib import Path
import sys
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.models.database_models import Base, Team, TestCaseSet, User


class FakeHelperLLM:
    async def call_stage(self, *, stage, prompt, system_prompt_override=None, max_tokens=4000):
        if stage == "analysis":
            prompt_text = str(prompt or "")
            if "可編輯 Markdown" in prompt_text:
                return SimpleNamespace(
                    content="# Requirement\n\n- Login",
                    usage={"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20},
                    cost=0.0,
                    cost_note="",
                    response_id="normalize-1",
                )
            if "需求結構化引擎" in prompt_text:
                return SimpleNamespace(
                    content='{"ticket":{"key":"TCG-130078","summary":"登入流程優化","components":["Auth"]},"scenarios":[{"rid":"REQ-001","g":"Auth","t":"登入成功","ac":["帳密正確"],"rules":[]}],"reference_columns":[]}',
                    usage={"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20},
                    cost=0.0,
                    cost_note="",
                    response_id="requirement-ir-1",
                )
            return SimpleNamespace(
                content='{"analysis":{"sec":[{"g":"Auth","it":[{"id":"010.001","t":"登入成功","det":["帳密正確"],"rid":["REQ-001"]},{"id":"010.002","t":"OTP 驗證","det":["OTP 有效"],"rid":["REQ-001"]}]}],"it":[{"id":"010.001","t":"登入成功","det":["帳密正確"],"rid":["REQ-001"]},{"id":"010.002","t":"OTP 驗證","det":["OTP 有效"],"rid":["REQ-001"]}]},"coverage":{"seed":[{"g":"Auth","t":"登入成功流程","ax":"happy","cat":"happy","st":"ok","ref":["010.001"],"rid":["REQ-001"]},{"g":"Auth","t":"OTP 邊界值驗證","ax":"edge","cat":"boundary","st":"ok","ref":["010.002"],"rid":["REQ-001"]},{"g":"Auth","t":"OTP 過期錯誤","ax":"error","cat":"negative","st":"ok","ref":["010.002"],"rid":["REQ-001"]},{"g":"Auth","t":"權限不足不得操作 OTP 設定","ax":"permission","cat":"negative","st":"assume","a":"需求未明確定義角色矩陣","ref":["010.001"],"rid":["REQ-001"]}]}}',
                usage={"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20},
                cost=0.0,
                cost_note="",
                response_id="analysis-2",
            )

        if stage == "coverage":
            return SimpleNamespace(
                content='{"seed":[{"g":"Auth","t":"登入成功流程","cat":"happy","st":"ok","ref":["010.001"],"rid":["REQ-001"]}]}',
                usage={"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20},
                cost=0.0,
                cost_note="",
                response_id="coverage-1",
            )

        if stage == "testcase":
            return SimpleNamespace(
                content=(
                    '{"tc":[{"id":"TEMP","t":"登入成功流程","pre":["開啟登入頁"],'
                    '"s":["輸入帳密並送出"],"exp":["登入成功"],"priority":"Medium"}]}'
                ),
                usage={"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20},
                cost=0.0,
                cost_note="",
                response_id="testcase-1",
            )

        if stage == "audit":
            return SimpleNamespace(
                content=(
                    '{"tc":[{"id":"TEMP","t":"登入成功流程（審核）","pre":["開啟登入頁"],'
                    '"s":["輸入帳密並送出"],"exp":["登入成功"],"priority":"High"}]}'
                ),
                usage={"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20},
                cost=0.0,
                cost_note="",
                response_id="audit-1",
            )

        raise AssertionError(f"Unexpected stage: {stage}")

    async def create_embedding(self, text, model="", api_url=""):
        return [0.1, 0.2, 0.3]

    @staticmethod
    def strip_json_fences(content):
        return content


class FakeQdrantClient:
    async def query_jira_referances_context(self, embedding):
        return []

    async def query_similar_context(self, embedding):
        return {"test_cases": [], "usm_nodes": []}


@pytest.fixture
def helper_api_db(tmp_path, monkeypatch):
    db_path = tmp_path / "helper_api.db"
    sync_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"timeout": 30},
        pool_pre_ping=True,
    )

    TestingSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)
    AsyncTestingSessionLocal = async_sessionmaker(
        bind=async_engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )

    Base.metadata.create_all(bind=sync_engine)

    with TestingSessionLocal() as session:
        team = Team(
            name="Helper API Team",
            description="",
            wiki_token="wiki-helper-api",
            test_case_table_id="tbl-helper-api",
        )
        session.add(team)
        session.commit()

        user = User(
            username="helper-api-admin",
            email="helper-api-admin@example.com",
            hashed_password="hashed-password",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        session.commit()

        test_set = TestCaseSet(
            team_id=team.id,
            name=f"Helper-API-Set-{team.id}",
            description="",
            is_default=True,
        )
        session.add(test_set)
        session.commit()

        team_id = team.id
        set_id = test_set.id
        user_id = user.id

    import app.database as app_database

    monkeypatch.setattr(app_database, "engine", async_engine)
    monkeypatch.setattr(app_database, "SessionLocal", AsyncTestingSessionLocal)

    async def override_get_db():
        async with AsyncTestingSessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id,
        username="helper-api-admin",
        role=UserRole.SUPER_ADMIN,
    )

    fake_llm = FakeHelperLLM()
    import app.services.jira_testcase_helper_service as helper_service_module

    monkeypatch.setattr(
        helper_service_module,
        "get_jira_testcase_helper_llm_service",
        lambda: fake_llm,
    )
    monkeypatch.setattr(
        helper_service_module,
        "get_qdrant_client",
        lambda: FakeQdrantClient(),
    )
    monkeypatch.setattr(
        helper_service_module.JiraClient,
        "get_issue",
        lambda self, key, fields=None: {
            "key": key,
            "fields": {
                "summary": "登入流程優化",
                "description": "新增 OTP",
                "components": [{"name": "Auth"}],
            },
        },
    )

    yield {
        "team_id": team_id,
        "set_id": set_id,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    asyncio.run(async_engine.dispose())
    sync_engine.dispose()


def test_helper_api_session_lifecycle_and_phase_transitions(helper_api_db):
    team_id = helper_api_db["team_id"]
    set_id = helper_api_db["set_id"]
    client = TestClient(app)

    start_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions",
        json={
            "test_case_set_id": set_id,
            "output_locale": "zh-TW",
            "review_locale": "zh-TW",
            "initial_middle": "010",
        },
    )
    assert start_resp.status_code == 201
    session_payload = start_resp.json()
    session_id = session_payload["id"]
    assert session_payload["current_phase"] == "init"

    ticket_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}/ticket",
        json={"ticket_key": "TCG-130078"},
    )
    assert ticket_resp.status_code == 200
    assert ticket_resp.json()["ticket_key"] == "TCG-130078"

    analyze_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}/analyze",
        json={"retry": False},
    )
    assert analyze_resp.status_code == 200, analyze_resp.text
    analyze_payload = analyze_resp.json()
    assert analyze_payload["session"]["current_phase"] == "pretestcase"
    assert analyze_payload["session"]["phase_status"] == "waiting_confirm"

    generate_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}/generate",
        json={
            "pretestcase_payload": analyze_payload["payload"]["pretestcase"],
            "retry": False,
        },
    )
    assert generate_resp.status_code == 200, generate_resp.text
    generated_payload = generate_resp.json()
    assert generated_payload["session"]["current_phase"] == "testcase"
    assert generated_payload["session"]["phase_status"] == "waiting_confirm"
    expected_case_count = len(
        (
            analyze_payload.get("payload", {})
            .get("pretestcase", {})
            .get("en", [])
            or []
        )
    )
    assert expected_case_count > 0
    assert len(generated_payload["payload"]["tc"]) == expected_case_count

    commit_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}/commit",
        json={"testcases": generated_payload["payload"]["tc"]},
    )
    assert commit_resp.status_code == 200
    commit_payload = commit_resp.json()
    assert commit_payload["created_count"] == expected_case_count

    session_after_commit = client.get(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}"
    )
    assert session_after_commit.status_code == 200
    session_data = session_after_commit.json()
    assert session_data["current_phase"] == "commit"
    assert session_data["status"] == "completed"


def test_helper_api_commit_validation_and_section_fallback(helper_api_db):
    team_id = helper_api_db["team_id"]
    set_id = helper_api_db["set_id"]
    client = TestClient(app)

    start_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions",
        json={
            "test_case_set_id": set_id,
            "output_locale": "zh-TW",
            "review_locale": "zh-TW",
            "initial_middle": "010",
        },
    )
    assert start_resp.status_code == 201
    session_id = start_resp.json()["id"]

    invalid_commit = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}/commit",
        json={
            "testcases": [
                {
                    "id": "TCG-130078.010.010",
                    "t": "invalid exp",
                    "pre": ["前置"],
                    "s": ["步驟"],
                    "exp": ["結果1", "結果2"],
                    "priority": "Medium",
                    "section_path": "Auth",
                }
            ]
        },
    )
    assert invalid_commit.status_code == 400

    fallback_commit = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}/commit",
        json={
            "testcases": [
                {
                    "id": "TCG-130078.010.020",
                    "t": "deep section fallback",
                    "pre": ["前置"],
                    "s": ["步驟"],
                    "exp": ["結果"],
                    "priority": "Medium",
                    "section_path": "A/B/C/D/E/F",
                }
            ]
        },
    )
    assert fallback_commit.status_code == 200
    assert fallback_commit.json()["section_fallback_count"] == 1


def test_helper_api_analyze_warning_gate_and_override_flow(helper_api_db):
    team_id = helper_api_db["team_id"]
    set_id = helper_api_db["set_id"]
    client = TestClient(app)

    start_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions",
        json={
            "test_case_set_id": set_id,
            "output_locale": "zh-TW",
            "review_locale": "zh-TW",
            "initial_middle": "010",
        },
    )
    assert start_resp.status_code == 201
    session_id = start_resp.json()["id"]

    ticket_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}/ticket",
        json={"ticket_key": "TCG-130078"},
    )
    assert ticket_resp.status_code == 200

    incomplete_requirement = (
        "h1. Menu\\n"
        " * 活動紅利 > 活動公告管理\\n\\n"
        "h1. Criteria\\n"
        " * 關閉活動內容時公告內文仍需顯示\\n"
    )

    warning_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}/analyze",
        json={
            "retry": False,
            "requirement_markdown": incomplete_requirement,
        },
    )
    assert warning_resp.status_code == 200, warning_resp.text
    warning_payload = warning_resp.json()
    assert warning_payload["stage"] == "requirement_validation_warning"
    assert warning_payload["payload"]["requires_override"] is True
    assert warning_payload["payload"]["warning"]["quality_level"] in {"medium", "low"}
    assert warning_payload["session"]["current_phase"] == "requirement"

    proceed_resp = client.post(
        f"/api/teams/{team_id}/test-case-helper/sessions/{session_id}/analyze",
        json={
            "retry": False,
            "requirement_markdown": incomplete_requirement,
            "override_incomplete_requirement": True,
        },
    )
    assert proceed_resp.status_code == 200, proceed_resp.text
    proceed_payload = proceed_resp.json()
    assert proceed_payload["stage"] == "analysis_coverage"
    assert proceed_payload["session"]["current_phase"] == "pretestcase"
    assert len(proceed_payload["payload"]["pretestcase"]["en"]) >= 1
