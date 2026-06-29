"""Tests for TCRT-managed automation environment configs.

Covers: environment catalog + shared params + per-script overrides, secret
masking / encryption, effective-value resolution, declared-vars discovery,
the run-trigger env resolution/validation bundle, and the bootstrap key guard.
See manage-automation-environment-configs.
"""

import base64
import json
import logging
import secrets

import pytest
from sqlalchemy import select, text

from app.config import get_settings
from app.models.automation_environment import EnvParamInput
from app.models.database_models import (
    AutomationEnvironment,
    AutomationProviderSlot,
    AutomationScript,
    AutomationScriptFormat,
    Team,
    TeamAutomationProvider,
    TestRunSet,
)
from app.services.automation.environment_service import EnvironmentService
from app.services.automation.marker_parse import _extract_declared_vars
from app.services.automation.script_group_service import (
    AutomationEnvironmentIncompleteError,
    AutomationEnvironmentRequiredError,
    AutomationScriptGroupService,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
)


def _key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    monkeypatch.setattr(get_settings().automation_provider, "encryption_key", _key())


_DECLARED = [
    {"name": "BASE_URL", "secret": False, "required": True},
    {"name": "API_TOKEN", "secret": True, "required": True},
    {"name": "SCRIPT_ONLY", "secret": False, "required": True},
]


@pytest.fixture
def env_db(tmp_path):
    bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    with bundle["sync_session_factory"]() as session:
        team = Team(name="QA", description="", wiki_token="w", test_case_table_id="t")
        session.add(team)
        session.commit()
        provider = TeamAutomationProvider(
            team_id=team.id,
            provider_slot=AutomationProviderSlot.STORAGE,
            provider_type="storage:github",
            name="GitHub",
            config_json=json.dumps({"owner": "x", "repo": "y", "default_branch": "main"}),
            is_active=True,
        )
        session.add(provider)
        session.commit()
        script = AutomationScript(
            team_id=team.id,
            provider_id=provider.id,
            name="login",
            script_format=AutomationScriptFormat.PYTEST,
            ref_repo="",
            ref_path="tests/test_login.py",
            ref_branch="main",
            declared_vars_json=json.dumps(_DECLARED),
        )
        session.add(script)
        session.commit()
        ids = {"team_id": team.id, "provider_id": provider.id, "script_id": script.id}
    yield {**ids, "async_sessionmaker": bundle["async_session_factory"], "sync_engine": bundle["sync_engine"]}
    dispose_managed_test_database(bundle)


@pytest.mark.asyncio
async def test_create_environment_masks_secret_in_response(env_db):
    async with env_db["async_sessionmaker"]() as session:
        svc = EnvironmentService(session)
        env = await svc.create_environment(
            team_id=env_db["team_id"], name="sit", is_default=False,
            params=[
                EnvParamInput(key="BASE_URL", value="https://sit", is_secret=False),
                EnvParamInput(key="API_TOKEN", value="tok_wxyz", is_secret=True),
            ],
            actor="9",
        )
        await session.commit()
        params = {p.key: p for p in env.params}
        assert params["BASE_URL"].value == "https://sit"
        # Secret never returned in plaintext; only is_set + fingerprint.
        assert params["API_TOKEN"].value is None
        assert params["API_TOKEN"].is_set is True
        assert params["API_TOKEN"].fingerprint == "***wxyz"


@pytest.mark.asyncio
async def test_single_default_per_team(env_db):
    async with env_db["async_sessionmaker"]() as session:
        svc = EnvironmentService(session)
        a = await svc.create_environment(team_id=env_db["team_id"], name="dev",
                                         is_default=True, params=[], actor="9")
        b = await svc.create_environment(team_id=env_db["team_id"], name="prod",
                                         is_default=True, params=[], actor="9")
        await session.commit()
        envs = {e.name: e.is_default for e in await svc.list_environments(env_db["team_id"])}
        assert envs == {"dev": False, "prod": True}


@pytest.mark.asyncio
async def test_rename_environment_cascades_to_run_set_reference(env_db):
    """Renaming an environment must keep test run sets that reference it by
    name in sync — a stale name would silently orphan the set's default."""
    async with env_db["async_sessionmaker"]() as session:
        svc = EnvironmentService(session)
        env = await svc.create_environment(
            team_id=env_db["team_id"], name="sit", is_default=False, params=[], actor="9")
        session.add(TestRunSet(
            team_id=env_db["team_id"], name="Regression", default_automation_environment="sit"))
        await session.commit()

        await svc.update_environment(
            team_id=env_db["team_id"], env_id=env.id, name="staging", is_default=None, actor="9")
        await session.commit()

        renamed = (await svc.list_environments(env_db["team_id"]))[0]
        assert renamed.name == "staging"
        run_set = (await session.execute(
            select(TestRunSet).where(TestRunSet.team_id == env_db["team_id"])
        )).scalar_one()
        assert run_set.default_automation_environment == "staging"


@pytest.mark.asyncio
async def test_rename_to_existing_name_conflicts(env_db):
    """A rename that collides with another env's name is a 409, not a crash."""
    async with env_db["async_sessionmaker"]() as session:
        svc = EnvironmentService(session)
        await svc.create_environment(team_id=env_db["team_id"], name="sit", is_default=False, params=[], actor="9")
        prod = await svc.create_environment(team_id=env_db["team_id"], name="prod", is_default=False, params=[], actor="9")
        await session.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            await svc.update_environment(
                team_id=env_db["team_id"], env_id=prod.id, name="sit", is_default=None, actor="9")
        assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_per_script_override_resolution_and_coverage(env_db):
    async with env_db["async_sessionmaker"]() as session:
        svc = EnvironmentService(session)
        sit = await svc.create_environment(
            team_id=env_db["team_id"], name="sit", is_default=True,
            params=[
                EnvParamInput(key="BASE_URL", value="https://sit", is_secret=False),
                EnvParamInput(key="API_TOKEN", value="tok", is_secret=True),
            ],
            actor="9",
        )
        await svc.set_script_override(
            team_id=env_db["team_id"], script_id=env_db["script_id"], env_id=sit.id,
            key="SCRIPT_ONLY", value="ov", is_secret=False, actor="9",
        )
        await session.commit()

        view = await svc.get_script_env_vars(team_id=env_db["team_id"], script_id=env_db["script_id"])
        cells = {c.key: c for c in view.cells if c.environment_name == "sit"}
        assert cells["BASE_URL"].source == "shared"
        assert cells["SCRIPT_ONLY"].source == "override" and cells["SCRIPT_ONLY"].value == "ov"
        assert cells["API_TOKEN"].is_secret and cells["API_TOKEN"].value is None
        assert view.coverage["sit"]["missing_required"] == []


@pytest.mark.asyncio
async def test_resolve_env_bundle_paths(env_db):
    async with env_db["async_sessionmaker"]() as session:
        env_svc = EnvironmentService(session)
        sit = await env_svc.create_environment(
            team_id=env_db["team_id"], name="sit", is_default=True,
            params=[
                EnvParamInput(key="BASE_URL", value="https://sit", is_secret=False),
                EnvParamInput(key="API_TOKEN", value="tok_abcd", is_secret=True),
                EnvParamInput(key="SCRIPT_ONLY", value="s", is_secret=False),
            ],
            actor="9",
        )
        await session.commit()
        script = (await session.execute(
            select(AutomationScript).where(AutomationScript.id == env_db["script_id"])
        )).scalar_one()
        gsvc = AutomationScriptGroupService(session)

        # Complete → decrypted bundle (incl. secret), env name resolved.
        name, bundle = await gsvc.resolve_env_bundle(
            team_id=env_db["team_id"], scripts=[script], environment="sit")
        assert name == "sit"
        assert bundle["tests/test_login.py"]["API_TOKEN"] == "tok_abcd"

        # Default fallback (environment=None → catalog default).
        name2, _ = await gsvc.resolve_env_bundle(
            team_id=env_db["team_id"], scripts=[script], environment=None)
        assert name2 == "sit"

        # No declared vars → (None, None) (backward compatible).
        script.declared_vars_json = "[]"
        await session.flush()
        assert await gsvc.resolve_env_bundle(
            team_id=env_db["team_id"], scripts=[script], environment="sit") == (None, None)


@pytest.mark.asyncio
async def test_resolve_env_bundle_incomplete_and_required(env_db):
    async with env_db["async_sessionmaker"]() as session:
        env_svc = EnvironmentService(session)
        # Environment with NO values → required vars unmet.
        sit = await env_svc.create_environment(
            team_id=env_db["team_id"], name="sit",
            is_default=False, params=[], actor="9")
        await session.commit()
        script = (await session.execute(
            select(AutomationScript).where(AutomationScript.id == env_db["script_id"])
        )).scalar_one()
        gsvc = AutomationScriptGroupService(session)

        with pytest.raises(AutomationEnvironmentIncompleteError) as ei:
            await gsvc.resolve_env_bundle(team_id=env_db["team_id"], scripts=[script], environment="sit")
        assert "tests/test_login.py" in ei.value.missing

        # No env name + no default → required error listing available envs.
        with pytest.raises(AutomationEnvironmentRequiredError) as er:
            await gsvc.resolve_env_bundle(team_id=env_db["team_id"], scripts=[script], environment=None)
        assert "sit" in er.value.available


@pytest.mark.asyncio
async def test_export_masks_secrets(env_db):
    async with env_db["async_sessionmaker"]() as session:
        svc = EnvironmentService(session)
        sit = await svc.create_environment(
            team_id=env_db["team_id"], name="sit", is_default=False,
            params=[
                EnvParamInput(key="BASE_URL", value="https://sit", is_secret=False),
                EnvParamInput(key="API_TOKEN", value="tok_secret", is_secret=True),
            ],
            actor="9",
        )
        await session.commit()
        out = await svc.export_params(team_id=env_db["team_id"], env_id=sit.id)
        assert "https://sit" in out
        assert "tok_secret" not in out  # secret value never exported
        assert "'***'" in out or "***" in out


def test_declared_vars_discovery_fail_open():
    declared, warns = _extract_declared_vars(
        'TCRT_VARS = ["BASE_URL", {"name": "API_TOKEN", "secret": True}]\n'
    )
    assert [d["name"] for d in declared] == ["BASE_URL", "API_TOKEN"]
    assert declared[1]["secret"] is True
    assert warns == []
    # Non-literal → fail-open, no declared vars, warning recorded.
    declared2, warns2 = _extract_declared_vars("TCRT_VARS = SOME_LIST\n")
    assert declared2 == []
    assert warns2 and warns2[0]["type"] == "non_literal_var"


def test_bootstrap_guard_requires_key_when_env_secret_exists(env_db, monkeypatch):
    # An encrypted env secret row exists but the key is absent → block startup.
    engine = env_db["sync_engine"]
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO automation_environments (team_id, name, is_default, created_at, updated_at) "
            "VALUES (:t, 'sit', 0, '2026-06-24', '2026-06-24')"
        ), {"t": env_db["team_id"]})
        env_id = conn.execute(text("SELECT id FROM automation_environments WHERE name='sit'")).scalar()
        conn.execute(text(
            "INSERT INTO automation_environment_params "
            "(environment_id, key, is_secret, value_encrypted, created_at, updated_at) "
            "VALUES (:e, 'API_TOKEN', 1, 'envelope-placeholder', '2026-06-24', '2026-06-24')"
        ), {"e": env_id})
    monkeypatch.setattr(get_settings().automation_provider, "encryption_key", "")
    from database_init import verify_automation_provider_encryption_key

    ok, message = verify_automation_provider_encryption_key(engine, logging.getLogger("test"))
    assert ok is False
    assert message and "encryption key" in message


def test_script_response_model_preserves_declared_vars():
    """Regression: the list/detail script API serializes via AutomationScriptResponse.
    declared_vars/var_warnings MUST survive that Pydantic boundary, else the
    Script view "Configure variables" entry never renders (the field is silently
    dropped by Pydantic if absent from the model)."""
    from datetime import datetime

    from app.models.automation_script import AutomationScriptResponse
    from app.models.database_models import AutomationScript, AutomationScriptFormat
    from app.services.automation.script_service import script_to_dict

    script = AutomationScript(
        id=1, team_id=1, provider_id=1, name="x",
        script_format=AutomationScriptFormat.PYTEST, ref_repo="",
        ref_path="tests/ui/test_case_search.py", ref_branch="main",
        cached_content='TCRT_VARS = ["BASE_URL", {"name": "SEARCH_KEYWORD"}]\n',
        linked_test_case_count=0, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    resp = AutomationScriptResponse(**script_to_dict(script))
    assert [v["name"] for v in resp.declared_vars] == ["BASE_URL", "SEARCH_KEYWORD"]


@pytest.mark.asyncio
async def test_list_declared_variables_aggregates_across_scripts(env_db):
    """The add-variable editor suggests names scanned from scripts' TCRT_VARS.
    Aggregated distinct by name; secret/required True if any script marks so."""
    async with env_db["async_sessionmaker"]() as session:
        out = await EnvironmentService(session).list_declared_variables(team_id=env_db["team_id"])
    by = {v["name"]: v for v in out}
    assert set(by) == {"BASE_URL", "API_TOKEN", "SCRIPT_ONLY"}
    assert by["API_TOKEN"]["secret"] is True
    assert by["BASE_URL"]["secret"] is False
    assert by["API_TOKEN"]["scripts"] == ["tests/test_login.py"]
