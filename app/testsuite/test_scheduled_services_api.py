from pathlib import Path
import sys
import asyncio
from datetime import datetime
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
from app.models.database_models import ScheduledService, User
from app.services.scheduler import SchedulableServiceDefinition, TaskScheduler
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


@pytest.fixture
def scheduled_service_env(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_case_repo.db")
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )

    current_user_ref = {"value": None}

    def override_get_current_user():
        return current_user_ref["value"]

    app.dependency_overrides[get_current_user] = override_get_current_user

    scheduler = TaskScheduler()
    monkeypatch.setattr("app.services.scheduler.task_scheduler", scheduler)
    monkeypatch.setattr("app.api.organization_sync.task_scheduler", scheduler)

    session = TestingSessionLocal()
    try:
        super_admin = User(
            username="scheduled-super-admin",
            email="scheduled-super-admin@example.com",
            hashed_password="x",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        admin = User(
            username="scheduled-admin",
            email="scheduled-admin@example.com",
            hashed_password="x",
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add_all([super_admin, admin])
        session.commit()
        current_user_ref["value"] = SimpleNamespace(
            id=super_admin.id,
            username=super_admin.username,
            role=UserRole.SUPER_ADMIN.value,
            is_active=True,
        )
    finally:
        session.close()

    asyncio.run(permission_service.cache.clear_all())
    asyncio.run(scheduler.initialize())

    yield {
        "session_factory": TestingSessionLocal,
        "current_user_ref": current_user_ref,
        "scheduler": scheduler,
    }

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    asyncio.run(permission_service.cache.clear_all())
    dispose_managed_test_database(database_bundle)


def test_super_admin_can_list_scheduled_services(scheduled_service_env):
    client = TestClient(app)

    response = client.get("/api/organization/scheduled-services")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["scheduler_running"] is False
    assert len(payload["data"]["services"]) == 1
    assert payload["data"]["services"][0]["service_key"] == "lark_org_sync"
    assert payload["data"]["services"][0]["enabled"] is False


def test_super_admin_can_update_daily_schedule(scheduled_service_env):
    client = TestClient(app)
    session_factory = scheduled_service_env["session_factory"]

    response = client.put(
        "/api/organization/scheduled-services/lark_org_sync",
        json={"enabled": True, "run_at_time": "03:45"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["enabled"] is True
    assert payload["data"]["run_at_time"] == "03:45"
    assert payload["data"]["next_run_at"] is not None

    with session_factory() as session:
        record = session.query(ScheduledService).filter(ScheduledService.service_key == "lark_org_sync").one()
        assert record.enabled is True
        assert record.run_at_time == "03:45"
        assert record.next_run_at is not None


def test_scheduler_initialize_recovers_stale_running_state(scheduled_service_env):
    session_factory = scheduled_service_env["session_factory"]
    scheduler = scheduled_service_env["scheduler"]

    with session_factory() as session:
        record = session.query(ScheduledService).filter(ScheduledService.service_key == "lark_org_sync").one()
        record.enabled = True
        record.is_running = True
        record.run_at_time = "01:30"
        session.commit()

    asyncio.run(scheduler.initialize())

    with session_factory() as session:
        record = session.query(ScheduledService).filter(ScheduledService.service_key == "lark_org_sync").one()
        assert record.is_running is False
        assert record.last_run_status == "interrupted"
        assert record.next_run_at is not None


def test_update_schedule_rejects_invalid_time_format(scheduled_service_env):
    client = TestClient(app)

    response = client.put(
        "/api/organization/scheduled-services/lark_org_sync",
        json={"enabled": True, "run_at_time": "3pm"},
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["code"] == "SCHEDULE_INVALID_TIME"


def test_admin_cannot_access_scheduled_service_management(scheduled_service_env):
    client = TestClient(app)
    session_factory = scheduled_service_env["session_factory"]
    current_user_ref = scheduled_service_env["current_user_ref"]

    with session_factory() as session:
        admin = session.query(User).filter(User.role == UserRole.ADMIN).one()
        current_user_ref["value"] = SimpleNamespace(
            id=admin.id,
            username=admin.username,
            role=UserRole.ADMIN.value,
            is_active=True,
        )

    response = client.get("/api/organization/scheduled-services")
    assert response.status_code == 403


def test_scheduler_uses_local_time_to_calculate_next_run(scheduled_service_env, monkeypatch):
    scheduler = scheduled_service_env["scheduler"]
    local_now = datetime(2026, 3, 24, 1, 0, 0)
    monkeypatch.setattr(scheduler, "_current_local_time", lambda: local_now)

    payload = asyncio.run(
        scheduler.update_service_schedule(
            service_key="lark_org_sync",
            enabled=True,
            run_at_time="00:30",
        )
    )

    assert payload["next_run_at"] == datetime(2026, 3, 25, 0, 30, 0).isoformat()


def test_scheduler_runs_due_task_when_local_time_reaches_schedule(scheduled_service_env, monkeypatch):
    scheduler = scheduled_service_env["scheduler"]
    session_factory = scheduled_service_env["session_factory"]
    executed = []

    original_definition = scheduler.service_registry["lark_org_sync"]

    def fake_runner():
        executed.append("ran")
        return {"success": True, "message": "fake sync ok"}

    scheduler.service_registry["lark_org_sync"] = SchedulableServiceDefinition(
        service_key=original_definition.service_key,
        display_name=original_definition.display_name,
        description=original_definition.description,
        schedule_type=original_definition.schedule_type,
        default_run_at_time=original_definition.default_run_at_time,
        runner=fake_runner,
    )

    schedule_time = datetime(2026, 3, 24, 12, 59, 0)
    due_time = datetime(2026, 3, 24, 13, 0, 0)

    monkeypatch.setattr(scheduler, "_current_local_time", lambda: schedule_time)
    asyncio.run(
        scheduler.update_service_schedule(
            service_key="lark_org_sync",
            enabled=True,
            run_at_time="13:00",
        )
    )

    monkeypatch.setattr(scheduler, "_current_local_time", lambda: due_time)
    scheduler._run_due_tasks(reference_time=due_time)

    assert executed == ["ran"]
    assert scheduler.tasks["lark_org_sync"]["last_run_status"] == "completed"
    assert scheduler.tasks["lark_org_sync"]["next_run"] == datetime(2026, 3, 25, 13, 0, 0)

    with session_factory() as session:
        record = session.query(ScheduledService).filter(ScheduledService.service_key == "lark_org_sync").one()
        assert record.last_run_status == "completed"
        assert record.last_run_message == "fake sync ok"
        assert record.next_run_at == datetime(2026, 3, 25, 13, 0, 0)


def test_scheduler_thread_uses_bound_runtime_loop_for_async_db_calls(scheduled_service_env, monkeypatch):
    scheduler = scheduled_service_env["scheduler"]
    call_log = []

    async def fake_mark_started(service_key, started_at):
        call_log.append(("started", service_key, started_at))

    async def fake_mark_finished(service_key, *, finished_at, success, message, last_error):
        call_log.append(("finished", service_key, finished_at, success, message, last_error))

    async def fake_runner():
        call_log.append(("runner",))
        return {"success": True, "message": "async ok"}

    monkeypatch.setattr(scheduler, "_mark_task_started", fake_mark_started)
    monkeypatch.setattr(scheduler, "_mark_task_finished", fake_mark_finished)
    monkeypatch.setattr(scheduler, "_current_local_time", lambda: datetime(2026, 3, 24, 9, 0, 0))

    original_definition = scheduler.service_registry["lark_org_sync"]
    scheduler.service_registry["lark_org_sync"] = SchedulableServiceDefinition(
        service_key=original_definition.service_key,
        display_name=original_definition.display_name,
        description=original_definition.description,
        schedule_type=original_definition.schedule_type,
        default_run_at_time=original_definition.default_run_at_time,
        runner=fake_runner,
    )
    scheduler.tasks["lark_org_sync"] = scheduler._build_task_info(
        {
            "service_key": "lark_org_sync",
            "display_name": original_definition.display_name,
            "description": original_definition.description,
            "schedule_type": original_definition.schedule_type,
            "run_at_time": "09:00",
            "enabled": True,
            "is_running": False,
            "last_run_status": None,
            "last_run_message": None,
            "last_error": None,
            "last_run_started_at": None,
            "last_run_finished_at": None,
            "next_run_at": datetime(2026, 3, 24, 9, 0, 0).isoformat(),
        }
    )

    def run_from_thread():
        scheduler._execute_task("lark_org_sync", scheduler.tasks["lark_org_sync"])

    async def exercise():
        scheduler._bind_runtime_loop()
        await asyncio.to_thread(run_from_thread)

    asyncio.run(exercise())
    assert [entry[0] for entry in call_log] == ["started", "runner", "finished"]
