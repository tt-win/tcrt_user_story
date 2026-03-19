from types import SimpleNamespace
from typing import Any

import pytest

from app.services.lark_department_service import LarkDepartmentService
from app.services.lark_notify_service import LarkNotifyService
from app.services.lark_org_sync_service import LarkOrgSyncService
from app.services.lark_user_service import LarkUserService


class _FakeSyncQuery:
    def __init__(self, first_result: Any = None, all_result: list[Any] | None = None):
        self._first_result = first_result
        self._all_result = list(all_result or [])

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def limit(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):
        return self._first_result

    def all(self):
        return list(self._all_result)


class _FakeSyncSession:
    def __init__(self, query_results: list[_FakeSyncQuery] | None = None):
        self._query_results = list(query_results or [])
        self.added: list[Any] = []
        self.flush_calls = 0
        self.refresh_calls = 0

    def query(self, *args, **kwargs):  # noqa: ANN002, ANN003
        if not self._query_results:
            raise AssertionError("unexpected query call")
        return self._query_results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flush_calls += 1
        for index, obj in enumerate(self.added, start=1):
            if getattr(obj, "id", None) is None:
                setattr(obj, "id", index)

    def refresh(self, obj: Any) -> None:
        self.refresh_calls += 1


class _FakeAsyncBoundary:
    def __init__(self, sync_session: _FakeSyncSession):
        self.sync_session = sync_session
        self.sync_read_calls = 0
        self.sync_write_calls = 0

    async def run_sync_read(self, operation):
        self.sync_read_calls += 1
        return operation(self.sync_session)

    async def run_sync_write(self, operation):
        self.sync_write_calls += 1
        return operation(self.sync_session)


@pytest.mark.asyncio
async def test_lark_notify_compute_end_stats_uses_boundary():
    config = SimpleNamespace(
        executed_cases=4,
        passed_cases=3,
        failed_cases=1,
    )
    items = [
        SimpleNamespace(bug_tickets_json='["BUG-1", "BUG-2"]'),
        SimpleNamespace(bug_tickets_json='["BUG-2", "BUG-3"]'),
    ]
    sync_session = _FakeSyncSession(
        query_results=[
            _FakeSyncQuery(first_result=config),
            _FakeSyncQuery(all_result=items),
        ]
    )
    boundary = _FakeAsyncBoundary(sync_session)
    service = LarkNotifyService()
    service.main_boundary = boundary

    stats = await service.compute_end_stats(team_id=1, config_id=9)

    assert boundary.sync_read_calls == 1
    assert stats == {
        "pass_rate": 75.0,
        "fail_rate": 25.0,
        "bug_count": 3,
    }


@pytest.mark.asyncio
async def test_lark_org_sync_history_write_uses_boundary():
    sync_session = _FakeSyncSession()
    boundary = _FakeAsyncBoundary(sync_session)
    service = LarkOrgSyncService(app_id="app-id", app_secret="app-secret")
    service.main_boundary = boundary

    sync_id = await service._create_sync_history(
        db=None,
        team_id=3,
        sync_type="full",
        trigger_type="manual",
        trigger_user="alice",
    )

    assert boundary.sync_write_calls == 1
    assert sync_id == 1
    assert sync_session.flush_calls == 1
    assert sync_session.refresh_calls == 1


@pytest.mark.asyncio
async def test_lark_department_save_department_uses_boundary():
    sync_session = _FakeSyncSession(query_results=[_FakeSyncQuery(first_result=None)])
    boundary = _FakeAsyncBoundary(sync_session)
    service = LarkDepartmentService(auth_manager=SimpleNamespace())
    service.main_boundary = boundary
    service._resolve_main_boundary = lambda db: boundary  # type: ignore[method-assign]

    saved = await service.save_department(
        db=object(),
        department_id="od_123",
        parent_id=None,
        level=0,
        children_data=[],
        path="/od_123",
    )

    assert saved is True
    assert boundary.sync_write_calls == 1
    assert sync_session.flush_calls == 1


@pytest.mark.asyncio
async def test_lark_user_save_user_uses_boundary():
    sync_session = _FakeSyncSession(query_results=[_FakeSyncQuery(first_result=None)])
    boundary = _FakeAsyncBoundary(sync_session)
    service = LarkUserService(auth_manager=SimpleNamespace())
    service.main_boundary = boundary
    service._resolve_main_boundary = lambda db: boundary  # type: ignore[method-assign]

    saved = await service.save_user(
        db=object(),
        user_data={
            "user_id": "ou_123",
            "name": "Alice",
            "department_ids_json": "[]",
        },
    )

    assert saved is True
    assert boundary.sync_write_calls == 1
    assert sync_session.flush_calls == 1
